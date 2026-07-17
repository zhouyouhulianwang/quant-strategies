"""
Alpaca Paper Trading 执行模块
使用新版 alpaca-py SDK，支持订单提交、持仓查询、账户状态监控
新增: PDT 检查、限价单、Atomic 调仓预检查、流动性检查、Decimal 精度
"""

import os
import json
import uuid
import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union, Any
import logging

# P1 修复：引入 requests 异常类，避免裸 except Exception
from requests.exceptions import RequestException, ConnectionError, Timeout

# 导入权重归一化工具
try:
    from weight_allocation import normalize_target_positions
    WEIGHT_ALLOC_NORM_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_NORM_AVAILABLE = False

# 导入 PDT 追踪器
try:
    from pdt_tracker import PDTTracker
    PDT_AVAILABLE = True
except ImportError:
    PDT_AVAILABLE = False


def adjust_for_split(symbol: str, ratio: float, lots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    按拆股比例更新本地 lot 数量

    参数:
        symbol: str, 股票代码
        ratio: float, 拆股比例（例如 1:2 拆股为 2.0，反向拆股为 0.5）
        lots: list, PDTTracker 仓位 lot 列表，每个 lot 为 {'entry_date': str, 'qty': int}

    返回:
        list: 更新后的 lot 列表（原地修改）
    """
    if not lots or ratio is None or ratio <= 0:
        return lots

    for lot in lots:
        if lot.get('symbol', symbol) == symbol:
            old_qty = int(lot.get('qty', 0))
            new_qty = int(round(old_qty * ratio))
            if new_qty != old_qty:
                logger.info(f"[SPLIT] Stock split adjustment: {symbol} {old_qty} -> {new_qty} (ratio={ratio})")
                lot['qty'] = new_qty

    return lots


# P2修复：引入统一告警管理器
try:
    from alert_manager import AlertManager
    ALERT_MGR_AVAILABLE = True
except ImportError:
    ALERT_MGR_AVAILABLE = False

# 导入统一撮合参数（Critical #2 修复：回测与 live 共享执行假设）
try:
    from matching_engine import ExecutionParameters, from_config
    MATCHING_ENGINE_AVAILABLE = True
except ImportError:
    MATCHING_ENGINE_AVAILABLE = False

# 设置日志（P2修复：统一使用 logging_config 的格式）
from logging_config import setup_logging
setup_logging()
logger = logging.getLogger('alpaca_executor')


def get_dynamic_limit_offset(symbol: str, price: float, atr: Optional[float] = None,
                             spread: Optional[float] = None, default_pct: float = 0.001) -> float:
    """
    计算动态限价单偏移比例。

    参数:
        symbol: 股票代码
        price: 当前参考价格
        atr: 可选 ATR 值；若提供，则使用 5% * (ATR / price) 作为偏移
        spread: 可选买卖价差（绝对金额）；若提供，则确保偏移至少大于 half-spread
        default_pct: 无 ATR 时的默认偏移比例

    返回:
        float: 建议的限价单偏移比例（例如 0.001 表示 0.1%）
    """
    if price <= 0:
        raise ValueError(f"{symbol}: price must be positive")

    if atr is not None and atr > 0:
        offset = 0.05 * (atr / price)
    else:
        offset = default_pct

    if spread is not None and spread > 0:
        min_offset = (spread / 2.0) / price
        if offset < min_offset:
            offset = min_offset

    return offset

# 尝试导入新版 alpaca-py SDK
# 先过滤 websockets.legacy 的弃用警告（alpaca-py 依赖的第三方库问题，不影响功能）
import warnings
warnings.filterwarnings(
    'ignore',
    message='websockets\\.legacy is deprecated',
    category=DeprecationWarning,
)

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest,
        LimitOrderRequest,
        GetOrdersRequest,
    )
    from alpaca.trading.enums import (
        OrderSide,
        OrderType,
        TimeInForce,
        QueryOrderStatus,
    )
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest, StockLatestQuoteRequest
    from alpaca.common.exceptions import APIError
    ALPACA_AVAILABLE = True
except ImportError as e:
    logger.warning(f"alpaca-py not installed: {e}, using mock mode")
    ALPACA_AVAILABLE = False


# ============================================================
# P0 修复：基于 SDK 对象的 fake client，模拟真实订单生命周期
# 避免 mock 模式过度短路真实路径
# ============================================================
class _FakeAlpacaClient:
    """轻量 fake client，返回 alpaca-py SDK 风格的命名元/对象"""
    
    def __init__(self, cash=1000000.0, positions=None):
        self._cash = cash
        self._positions = {p['symbol']: p for p in (positions or [])}
        self._orders = {}
        self._order_seq = 0
        self._clock_open = True
    
    def _next_id(self):
        self._order_seq += 1
        return f"fake-{self._order_seq:06d}-{uuid.uuid4().hex[:8]}"
    
    def get_account(self):
        class _Account:
            pass
        a = _Account()
        total = self._cash + sum(p['market_value'] for p in self._positions.values())
        a.id = 'fake-account'
        a.cash = self._cash
        a.portfolio_value = total
        a.equity = total
        a.buying_power = self._cash * 4.0
        a.status = 'ACTIVE'
        a.account_type = 'MARGIN'
        a.daytrade_count = 0
        a.pattern_day_trader = False
        a.trading_blocked = False
        a.trade_suspended_by_user = False
        return a
    
    def get_all_positions(self):
        class _Position:
            pass
        result = []
        for symbol, p in self._positions.items():
            pos = _Position()
            pos.symbol = symbol
            pos.qty = p['qty']
            pos.market_value = p['market_value']
            pos.avg_entry_price = p.get('avg_entry_price', 0)
            pos.current_price = p.get('current_price', p['market_value'] / max(p['qty'], 1))
            pos.unrealized_pl = 0
            pos.unrealized_plpc = 0
            result.append(pos)
        return result
    
    def get_clock(self):
        class _Clock:
            pass
        c = _Clock()
        c.is_open = self._clock_open
        return c
    
    def submit_order(self, order_request):
        class _Order:
            pass
        o = _Order()
        o.id = self._next_id()
        o.client_order_id = getattr(order_request, 'client_order_id', None)
        o.symbol = order_request.symbol
        o.qty = getattr(order_request, 'qty', 0)
        o.side = getattr(order_request, 'side', '')
        o.type = 'market' if not hasattr(order_request, 'limit_price') or order_request.limit_price is None else 'limit'
        o.status = 'filled'
        o.submitted_at = datetime.now()
        o.filled_qty = o.qty
        o.filled_avg_price = getattr(order_request, 'limit_price', None) or 100.0
        o.limit_price = getattr(order_request, 'limit_price', None)
        self._orders[o.id] = o
        # 更新 fake 持仓/现金
        self._apply_fill(o)
        return o
    
    def _apply_fill(self, order):
        qty = float(order.qty)
        price = float(order.filled_avg_price or 100.0)
        # 兼容 SDK 枚举与普通字符串 side
        side_raw = getattr(order.side, 'value', str(order.side))
        side = side_raw.lower() if isinstance(side_raw, str) else str(side_raw).lower()
        symbol = order.symbol
        if side == 'buy':
            self._cash -= qty * price
            if symbol in self._positions:
                self._positions[symbol]['qty'] += qty
                self._positions[symbol]['market_value'] += qty * price
            else:
                self._positions[symbol] = {
                    'qty': qty,
                    'market_value': qty * price,
                    'avg_entry_price': price,
                    'current_price': price,
                }
        elif side == 'sell':
            self._cash += qty * price
            if symbol in self._positions:
                self._positions[symbol]['qty'] -= qty
                self._positions[symbol]['market_value'] = max(0, self._positions[symbol]['market_value'] - qty * price)
                if self._positions[symbol]['qty'] <= 0:
                    del self._positions[symbol]
    
    def get_orders(self, request=None):
        return list(self._orders.values())
    
    def get_order_by_id(self, order_id):
        return self._orders.get(order_id)
    
    def cancel_order_by_id(self, order_id):
        order = self._orders.get(order_id)
        if order:
            order.status = 'canceled'
    
    def cancel_orders(self):
        for o in self._orders.values():
            o.status = 'canceled'
    
    def close_all_positions(self):
        for symbol, p in list(self._positions.items()):
            self._cash += p['qty'] * p['current_price']
        self._positions.clear()


class AlpacaPaperExecutor:
    """Alpaca Paper Trading 执行器（基于 alpaca-py）"""

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        base_url=None,
        paper=True,
        mock=False,
        require_live_confirmation=True,
        enable_pdt=True,
        pdt_min_equity=25000.0,
        use_limit_orders=False,
        limit_order_offset_pct=0.001,
        alert_manager=None,
        risk_monitor=None,
    ):
        """
        初始化 Alpaca 执行器

        参数:
            api_key: str, API Key (默认从 .env 文件读取)
            api_secret: str, API Secret
            base_url: str, API Base URL
            paper: bool, 是否使用纸交易（默认 True）
            mock: bool, 是否强制使用模拟模式（不连接真实 API，用于测试）
            require_live_confirmation: bool, live 模式是否需要二次确认
            enable_pdt: bool, 是否启用 PDT 检查
            pdt_min_equity: float, 不受 PDT 限制的最小权益
            use_limit_orders: bool, 是否默认使用限价单
            limit_order_offset_pct: float, 限价单偏移比例（默认 0.1%）
            alert_manager: AlertManager, 可选告警管理器（P2修复）
        """
        # 尝试从 .env 文件读取（不影响已存在的环境变量）
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_path) and not mock:
            with open(env_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.startswith('#') and not line.strip().startswith('ALPACA'):
                        # 只读取非 ALPACA 开头的变量？不，应该读取所有
                        pass
                    if '=' in line and not line.startswith('#'):
                        key, value = line.strip().split('=', 1)
                        # 不要覆盖已存在的环境变量
                        if key not in os.environ:
                            os.environ[key] = value

        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.api_secret = api_secret or os.getenv('ALPACA_API_SECRET')
        self.base_url = base_url or os.getenv('ALPACA_BASE_URL')
        self.paper = paper
        self.mock = mock
        self.require_live_confirmation = require_live_confirmation

        # P0 修复：先校验 API Key/Secret 存在性，再进入 live 确认；mock 模式使用假凭证
        if not self.api_key or not self.api_secret:
            if not mock:
                raise ValueError("Please provide Alpaca API Key and Secret, or set them in .env")
            self.api_key = self.api_key or 'MOCK-KEY'
            self.api_secret = self.api_secret or 'MOCK-SECRET'

        # 未指定 base_url 时，根据 paper 模式使用默认值；P1 修复：校验 base_url 合法性
        if not self.base_url:
            self.base_url = 'https://paper-api.alpaca.markets' if paper else 'https://api.alpaca.markets'
        if self.base_url not in ('https://paper-api.alpaca.markets', 'https://api.alpaca.markets'):
            raise ValueError(
                f"Invalid Alpaca base_url: {self.base_url}，"
                "仅允许 https://paper-api.alpaca.markets 或 https://api.alpaca.markets"
            )

        # 实盘模式二次确认（P0 修复：支持 ALPACA_LIVE_CONFIRMED=1 环境变量跳过交互）
        if not paper and not mock and require_live_confirmation:
            if os.getenv('ALPACA_LIVE_CONFIRMED') == '1':
                logger.critical("[OK] Skipping live confirmation via ALPACA_LIVE_CONFIRMED=1")
            else:
                confirmed = self._confirm_live_mode()
                if not confirmed:
                    raise RuntimeError("User did not confirm live mode, aborted")

        # 初始化 API
        self.trading_client = None
        self.data_client = None
        if mock:
            # P0 修复：mock 模式使用基于 SDK 对象的 fake client，避免过度短路真实路径
            self.trading_client = _FakeAlpacaClient()
            logger.warning("[WARN] Using mock mode (fake client, not connecting to real API)")
        elif ALPACA_AVAILABLE:
            raw_trading_client = TradingClient(
                api_key=self.api_key,
                secret_key=self.api_secret,
                paper=paper,
                raw_data=False,
            )
            raw_data_client = StockHistoricalDataClient(
                api_key=self.api_key,
                secret_key=self.api_secret,
            )
            # P1 修复：速率限制包装
            try:
                from rate_limiter import RateLimitedAPI
                self.trading_client = RateLimitedAPI(raw_trading_client, rate_per_min=200)
                self.data_client = RateLimitedAPI(raw_data_client, rate_per_min=200)
                logger.info("[OK] Alpaca API connected with rate limiting (200/min)")
            except ImportError:
                self.trading_client = raw_trading_client
                self.data_client = raw_data_client
                logger.info(f"[OK] Alpaca API connected: {self.base_url}")
        else:
            # P0-4 修复：非 mock 模式下 SDK 未安装时禁止静默 mock，必须显式抛错
            raise RuntimeError(
                "alpaca-py SDK is not installed, cannot enter real trading mode (paper/live)."
                "Run `pip install alpaca-py` to install the SDK;"
                "or explicitly set mock=True to use the mock executor."
            )

        # PDT 追踪器（按 account_id 和 paper/live 分文件）
        self.pdt_tracker = None
        if PDT_AVAILABLE and enable_pdt:
            # P1-5 修复：延迟获取账户 ID，避免构造时 API 调用失败阻塞启动；
            # 启动时通过 _sync_pdt_tracker 同步券商 daytrade_count
            self.pdt_tracker = PDTTracker(
                account_id='pending',
                paper=paper,
                min_equity_for_unlimited=pdt_min_equity,
                enabled=True,
            )
            self._sync_pdt_tracker()
        self.enable_pdt = enable_pdt

        # 当前调仓会话 ID（用于订单幂等性）
        self.rebalance_session = None
        self.use_limit_orders = use_limit_orders
        self.limit_order_offset_pct = limit_order_offset_pct

        # 缓存
        self._price_cache = {}
        self._price_cache_time = {}

        # P1 修复：int 截断累计误差补偿表 {symbol: residual_value}
        self._qty_residuals = {}

        # 最小订单数量（按价格估算，避免低于券商最小名义金额）
        self.min_notional = 1.0
        self.tick_size = 0.0001

        # P2修复：接入统一告警管理器（默认启用，可外部传入）
        self.alert_manager = alert_manager
        if self.alert_manager is None and ALERT_MGR_AVAILABLE:
            self.alert_manager = AlertManager(enabled=True)

        # 风控监控器引用（用于交易开关同步）
        self.risk_monitor = risk_monitor
        # 全局交易开关（可被风控线程/人工紧急停止触发）
        self.trading_halted = False

    def _send_alert(self, method, *args, **kwargs):
        """P2修复：统一封装告警调用，避免空告警管理器时出错"""
        if self.alert_manager is not None and hasattr(self.alert_manager, method):
            try:
                getattr(self.alert_manager, method)(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Alert send failed: {e}")

    def start_rebalance_session(self):
        """开始新的调仓会话，生成唯一 ID"""
        self.rebalance_session = uuid.uuid4().hex[:8]
        logger.info(f"[ROLLBACK] Starting rebalance session: {self.rebalance_session}")
        return self.rebalance_session

    def _confirm_live_mode(self) -> bool:
        """实盘模式二次确认（P0 修复：日志不打印任何 Key 片段）"""
        import sys
        logger.critical("[ALERT] [ALERT] [ALERT] Initializing LIVE trading mode! [ALERT] [ALERT] [ALERT]")
        logger.critical("   Will connect to real money account and execute trades.")
        logger.critical("   Please confirm API Key/Secret are configured for a LIVE account.")
        try:
            answer = input("Enter 'LIVE' to confirm live mode (other input will abort): ")
        except EOFError:
            # 非交互环境（如 CI、自动化脚本）默认拒绝
            logger.error("Non-interactive environment, cannot confirm live mode, aborted")
            return False
        if answer.strip() == 'LIVE':
            logger.critical("[OK] Live mode confirmed, continuing initialization")
            return True
        logger.critical("[ERROR] Live mode not confirmed, aborted")
        return False

    def _get_account_id(self) -> str:
        """从 Alpaca 获取账户 ID，用于 PDT 状态文件区分"""
        if not self.trading_client:
            return 'paper' if self.paper else 'live'
        try:
            account = self.trading_client.get_account()
            return str(getattr(account, 'id', 'unknown'))
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.warning(f"Failed to get account ID: {e}")
            return 'paper' if self.paper else 'live'

    def _sync_pdt_tracker(self):
        """P1-5 修复：启动时同步券商账户 ID、持仓和 daytrade_count"""
        if not self.pdt_tracker:
            return
        try:
            account_id = self._get_account_id()
            account = self._get_account_raw()
            broker_daytrade_count = account.get('daytrade_count', 0) if account else 0
            positions = self.get_positions()
            self.pdt_tracker.sync_positions(
                positions,
                broker_daytrade_count=broker_daytrade_count,
                account_id=account_id,
            )
        except Exception as e:
            logger.warning(f"Failed to sync PDT tracker: {e}, will continue with default account")

    @property
    def api(self):
        """兼容旧代码：返回 trading_client"""
        return self.trading_client

    def _get_account_raw(self) -> Optional[Dict]:
        """获取原始账户信息（统一转换为 dict）"""
        if not self.trading_client:
            return self._mock_account()

        try:
            account = self.trading_client.get_account()
            return self._account_to_dict(account)
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Failed to get account info: {e}")
            return None

    def _account_to_dict(self, account) -> Dict:
        """把 alpaca-py TradeAccount 对象转成 dict"""
        # 兼容 mock dict
        if isinstance(account, dict):
            return account

        return {
            'id': getattr(account, 'id', 'unknown'),
            'cash': float(getattr(account, 'cash', 0) or 0),
            'portfolio_value': float(getattr(account, 'portfolio_value', 0) or 0),
            'equity': float(getattr(account, 'equity', 0) or 0),
            'buying_power': float(getattr(account, 'buying_power', 0) or 0),
            'status': getattr(account, 'status', 'ACTIVE'),
            'account_type': getattr(account, 'account_type', 'MARGIN'),
            'daytrade_count': int(getattr(account, 'daytrade_count', 0) or 0),
            'pattern_day_trader': bool(getattr(account, 'pattern_day_trader', False)),
            'trading_blocked': bool(getattr(account, 'trading_blocked', False)),
            'trade_suspended_by_user': bool(getattr(account, 'trade_suspended_by_user', False)),
        }

    def get_account(self):
        """获取账户信息"""
        return self._get_account_raw()

    def get_positions(self):
        """获取当前持仓"""
        if not self.trading_client:
            return []

        try:
            positions = self.trading_client.get_all_positions()
            return [self._position_to_dict(p) for p in positions]
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def _position_to_dict(self, p) -> Dict:
        """把 Position 对象转成 dict"""
        if isinstance(p, dict):
            return p

        return {
            'symbol': getattr(p, 'symbol', ''),
            'qty': int(float(getattr(p, 'qty', 0))) if getattr(p, 'qty', None) is not None else 0,
            'market_value': float(getattr(p, 'market_value', 0)),
            'avg_entry_price': float(getattr(p, 'avg_entry_price', 0)),
            'current_price': float(getattr(p, 'current_price', 0)),
            'unrealized_pl': float(getattr(p, 'unrealized_pl', 0)),
            'unrealized_plpc': float(getattr(p, 'unrealized_plpc', 0)),
        }

    def _order_to_dict(self, o) -> Dict:
        """把 Order 对象转成 dict"""
        if isinstance(o, dict):
            return o

        return {
            'id': getattr(o, 'id', ''),
            'client_order_id': getattr(o, 'client_order_id', ''),
            'symbol': getattr(o, 'symbol', ''),
            'qty': int(float(getattr(o, 'qty', 0))) if getattr(o, 'qty', None) is not None else 0,
            'side': getattr(o, 'side', ''),
            'type': getattr(o, 'type', ''),
            'status': getattr(o, 'status', ''),
            'submitted_at': str(getattr(o, 'submitted_at', '')),
            'filled_qty': int(float(getattr(o, 'filled_qty', 0))) if getattr(o, 'filled_qty', None) is not None else 0,
            'filled_avg_price': float(getattr(o, 'filled_avg_price', 0)) if getattr(o, 'filled_avg_price', None) is not None else None,
            'limit_price': float(getattr(o, 'limit_price', 0)) if getattr(o, 'limit_price', None) is not None else None,
        }

    def _check_pdt(self, symbol: str, side: str) -> Dict:
        """PDT 检查（P0 修复：覆盖卖出侧）"""
        if not self.pdt_tracker or not self.enable_pdt:
            return {'allowed': True, 'reason': 'pdt_disabled'}

        account = self._get_account_raw()
        if not account:
            # P1-6 修复：账户 API 不可用时默认拒绝交易，防止在未知 PDT 状态下下单
            logger.warning(f"[WARN] Account info unavailable, rejecting {symbol} {side} trade")
            return {'allowed': False, 'reason': 'account_unavailable'}

        return self.pdt_tracker.can_open_position(
            symbol=symbol,
            side=side,
            account_type=account.get('account_type', 'MARGIN'),
            equity=account.get('equity', 0.0),
            broker_daytrade_count=account.get('daytrade_count', 0),
        )

    def _build_order_request(
        self,
        symbol: str,
        qty: Union[int, float],
        side: str,
        order_type: str = 'market',
        time_in_force: str = 'day',
        limit_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ):
        """构造 alpaca-py 的订单请求对象（P0 修复：显式传入 client_order_id 保证幂等性）"""
        side_enum = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

        # 时间有效性
        tif_map = {
            'day': TimeInForce.DAY,
            'gtc': TimeInForce.GTC,
            'ioc': TimeInForce.IOC,
            'opg': TimeInForce.OPG,
        }
        tif = tif_map.get(time_in_force.lower(), TimeInForce.DAY)

        # 如果是限价单且未提供价格，自动计算
        if order_type.lower() == 'limit':
            if limit_price is None:
                current_price = self._get_current_price(symbol)
                offset = get_dynamic_limit_offset(
                    symbol, current_price, atr=None, spread=None,
                    default_pct=self.limit_order_offset_pct
                )
                if side.lower() == 'buy':
                    limit_price = current_price * (1 - offset)
                else:
                    limit_price = current_price * (1 + offset)
                logger.info(f"[LIMIT] Auto-calculated limit price: {symbol} {side} @ ${limit_price:.4f}")

            # P1 修复：按最小价格增量（tick size）规整限价
            limit_price = round(math.floor(limit_price / self.tick_size) * self.tick_size, 4)

            return LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif,
                limit_price=limit_price,
                client_order_id=client_order_id,
            )

        return MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side_enum,
            time_in_force=tif,
            client_order_id=client_order_id,
        )

    def submit_order(
        self,
        symbol,
        qty,
        side,
        order_type='market',
        time_in_force='day',
        limit_price=None,
    ):
        """
        提交订单（支持幂等性、PDT 检查、限价单、购买力检查、最小订单数量检查）

        参数:
            symbol: str, 股票代码
            qty: int/float, 数量（小数股支持）
            side: str, 'buy' 或 'sell'
            order_type: str, 'market' 或 'limit'
            time_in_force: str, 'day', 'gtc', 'ioc', 'opg'
            limit_price: float, 限价单价格（None 则自动计算）

        返回:
            dict: 订单信息
        """
        # 参数基本校验
        if not symbol or not isinstance(symbol, str):
            logger.error("symbol must be a non-empty string")
            self._send_alert('order_failed', symbol or 'UNKNOWN', side, qty, 'invalid_symbol')
            return None
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            logger.error(f"qty must be numeric: {qty}")
            self._send_alert('order_failed', symbol, side, qty, 'invalid_qty')
            return None
        if qty <= 0:
            logger.error(f"qty must be greater than 0: {qty}")
            self._send_alert('order_failed', symbol, side, qty, 'qty_non_positive')
            return None
        if side.lower() not in ('buy', 'sell'):
            logger.error(f"side must be buy/sell: {side}")
            self._send_alert('order_failed', symbol, side, qty, 'invalid_side')
            return None

        # 全局交易开关检查（风控/人工紧急停止）
        if self.trading_halted or (self.risk_monitor and getattr(self.risk_monitor, 'trading_halted', False)):
            logger.error(f"[ERROR] Trading halted, rejecting order submission: {symbol} {side}")
            self._send_alert('order_failed', symbol, side, qty, 'trading_halted')
            return None

        # 检查是否已有同会话的未完成订单（幂等性）
        session_prefix = self.rebalance_session or 'manual'
        # P1-7 修复：client_order_id 加入数量，避免同 symbol-side 无法重复下单
        qty_str = str(int(float(qty))) if float(qty) == int(float(qty)) else str(float(qty))
        client_order_id = f"v14-{session_prefix}-{symbol}-{side.lower()}-{qty_str}"

        existing = self._find_order_by_client_id(client_order_id)
        if existing:
            logger.info(f"[ROLLBACK] Duplicate order found in same session, skipping: {client_order_id}")
            return existing

        # P0 修复：PDT 检查覆盖卖出侧（sell 也可能构成 day trade），mock 模式也检查
        pdt_check = self._check_pdt(symbol, side)
        if not pdt_check['allowed']:
            logger.error(f"[ERROR] PDT blocked opening: {symbol} ({pdt_check['reason']})")
            self._send_alert('pdt_blocked', symbol, side, pdt_check.get('reason', 'unknown'))
            return None

        if not self.trading_client:
            return self._mock_order(symbol, qty, side, client_order_id=client_order_id)

        # P0-4 修复：mock 模式且 SDK 未安装时，使用轻量模拟订单，避免引用未导入的 SDK 类
        if self.mock and not ALPACA_AVAILABLE:
            return self._mock_order(symbol, qty, side, client_order_id=client_order_id)

        # 价格/名义金额/购买力检查（仅在真实交易路径执行）
        current_price = self._get_current_price(symbol)
        notional = qty * current_price
        if notional < self.min_notional:
            logger.error(f"Order notional too small: {symbol} ${notional:.2f} < ${self.min_notional}")
            self._send_alert('order_failed', symbol, side, qty, 'notional_too_small', order_id=client_order_id)
            return None

        # P1 修复：买入侧购买力检查
        if side.lower() == 'buy':
            account = self._get_account_raw()
            if account:
                bp = account.get('buying_power', 0.0)
                if notional > bp:
                    logger.error(f"[ERROR] Insufficient buying power: {symbol} needs ${notional:.2f}, available ${bp:.2f}")
                    self._send_alert('order_failed', symbol, side, qty, 'insufficient_buying_power', order_id=client_order_id)
                    return None

        # 如果未指定限价单价格，但配置为限价模式，则转限价单
        if self.use_limit_orders and order_type.lower() == 'market':
            order_type = 'limit'
            logger.info(f"[LIMIT] Configured limit-order mode, converting {symbol} to limit order")

        try:
            order_request = self._build_order_request(
                symbol, qty, side, order_type, time_in_force, limit_price,
                client_order_id=client_order_id,
            )
            order = self.trading_client.submit_order(order_request)

            logger.info(f"[OK] Order submitted: {side.upper()} {qty} {symbol} (ID: {client_order_id})")
            result = self._order_to_dict(order)
            result['client_order_id'] = client_order_id

            return result
        except APIError as e:
            logger.error(f"Alpaca API error, order submission failed: {e}")
            self._send_alert('order_failed', symbol, side, qty, f'api_error: {e}', order_id=client_order_id)
            return None
        except (RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Network error, order submission failed: {e}")
            self._send_alert('order_failed', symbol, side, qty, f'network_error: {e}', order_id=client_order_id)
            return None
        except ValueError as e:
            logger.error(f"Parameter error, order submission failed: {e}")
            self._send_alert('order_failed', symbol, side, qty, f'value_error: {e}', order_id=client_order_id)
            return None

    def _find_order_by_client_id(self, client_order_id):
        """通过 client_order_id 查找已存在的订单（P0 修复：幂等性去重）"""
        if not self.trading_client:
            return None

        try:
            # mock 或无 SDK 时直接调用 fake client，避免引用未定义的 SDK 类
            if ALPACA_AVAILABLE:
                request = GetOrdersRequest(
                    status=QueryOrderStatus.ALL,
                    limit=100,
                )
            else:
                request = None
            orders = self.trading_client.get_orders(request)
            for o in orders:
                o_dict = self._order_to_dict(o)
                if o_dict.get('client_order_id') == client_order_id:
                    return o_dict
        except (APIError, RequestException, ConnectionError, Timeout, NameError) as e:
            logger.warning(f"Failed to find order by client_order_id: {e}")

        return None

    def cancel_all_orders(self):
        """取消所有未成交订单"""
        if not self.trading_client:
            return True

        try:
            self.trading_client.cancel_orders()
            logger.info("[OK] All orders canceled")
            return True
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Failed to cancel orders: {e}")
            return False

    def get_orders(self, status='open'):
        """获取订单列表"""
        if not self.trading_client:
            return []

        try:
            status_enum = QueryOrderStatus.OPEN if status.lower() == 'open' else QueryOrderStatus.ALL
            request = GetOrdersRequest(status=status_enum, limit=100)
            orders = self.trading_client.get_orders(request)
            return [self._order_to_dict(o) for o in orders]
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Failed to get orders: {e}")
            return []

    def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        """通过订单 ID 获取订单"""
        if not self.trading_client:
            return None

        try:
            order = self.trading_client.get_order_by_id(order_id)
            return self._order_to_dict(order)
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.warning(f"Get order {order_id} failed: {e}")
            return None

    def market_is_open(self):
        """检查市场是否开盘"""
        if not self.trading_client:
            return True  # 模拟模式假设市场开盘

        try:
            clock = self.trading_client.get_clock()
            return bool(getattr(clock, 'is_open', False))
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Failed to get market status: {e}")
            return False

    def liquidate_all(self):
        """平掉所有持仓（P0 修复：平仓前缓存持仓，按缓存记录 PDT）"""
        positions = self.get_positions()

        if not self.trading_client:
            for pos in positions:
                self._mock_order(pos['symbol'], pos['qty'], 'sell')
            return len(positions)

        try:
            # P0 修复：在清空前缓存持仓，避免 get_positions 返回空导致无法记录 PDT
            cached_positions = positions
            self.trading_client.close_all_positions()
            logger.info("[OK] All positions liquidated")

            # 记录 PDT 平仓（按缓存的持仓记录）
            if self.pdt_tracker:
                for pos in cached_positions:
                    self.pdt_tracker.record_fill(pos['symbol'], 'sell', pos['qty'])
            return 1
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Liquidation failed: {e}")
            # P2修复：平仓失败发送告警
            self._send_alert('execution_error', 'liquidate_all', str(e))
            # 回退到逐个卖出
            for pos in positions:
                self.submit_order(pos['symbol'], pos['qty'], 'sell')
            return len(positions)

    # ========== 模拟模式 ==========

    def record_fill(self, symbol: str, side: str, filled_qty: int):
        """记录一笔成交，用于 PDT 追踪"""
        if self.pdt_tracker and filled_qty > 0:
            self.pdt_tracker.record_fill(symbol, side, filled_qty)

    def sync_corporate_actions(self, symbols: List[str], start_date: Optional[str] = None, end_date: Optional[str] = None):
        """
        同步公司行为（拆股），并调整本地 PDT lot 数量

        参数:
            symbols: list, 股票代码列表
            start_date: str, 起始日期 'YYYY-MM-DD'（默认最近 7 天）
            end_date: str, 结束日期 'YYYY-MM-DD'（默认今天）
        """
        if not self.pdt_tracker or not symbols:
            return

        try:
            from data_source import get_corporate_actions

            if end_date is None:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if start_date is None:
                start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

            actions = get_corporate_actions(symbols, start_date, end_date)
            if actions is None or actions.empty:
                return

            # 只处理拆股事件
            splits = actions[actions['split'] != 1.0]
            for (date, symbol), row in splits.iterrows():
                ratio = float(row['split'])
                if symbol in self.pdt_tracker.positions:
                    adjust_for_split(symbol, ratio, self.pdt_tracker.positions[symbol])

            self.pdt_tracker._persist_state()
            logger.info(f"[SPLIT] Corporate action sync completed: {len(splits)} split(s)")
        except Exception as e:
            logger.warning(f"Failed to sync corporate actions: {e}")

    def sync_positions(self):
        """与 Alpaca 持仓同步，用于 PDT 准确追踪"""
        if not self.pdt_tracker:
            return
        positions = self.get_positions()
        self.pdt_tracker.sync_positions(positions)
        logger.info(f"[PDT] Positions synced [{self.pdt_tracker.account_id}]: {len(positions)} positions")

    def _calculate_qty(self, target_value, current_price, symbol=None):
        """使用 Decimal 精度计算股数（P1 修复：int 截断时累计误差补偿）"""
        if current_price <= 0:
            return 0
        # 累加之前截断产生的残余金额
        residual = self._qty_residuals.get(symbol, 0.0) if symbol else 0.0
        adjusted_value = target_value + residual
        value_d = Decimal(str(adjusted_value))
        price_d = Decimal(str(current_price))
        qty_d = (value_d / price_d).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        qty = int(qty_d)
        # 记录新的残余金额，避免长期累计误差
        if symbol:
            actual_spent = qty * current_price
            self._qty_residuals[symbol] = max(0.0, adjusted_value - actual_spent)
        return qty

    def reconcile(self, expected_cash=None, expected_positions=None) -> Dict:
        """持仓/现金对账（本地 vs Alpaca）
        
        参数:
            expected_cash: float, 预期现金（默认使用账户现金）
            expected_positions: dict, 预期持仓 {symbol: qty}
        
        返回:
            dict: 对账报告
        """
        report = {
            'account_id': self.pdt_tracker.account_id if self.pdt_tracker else ('paper' if self.paper else 'live'),
            'timestamp': datetime.now().isoformat(),
            'cash': {'broker': None, 'expected': expected_cash, 'diff': None},
            'positions': {'matched': [], 'mismatch': [], 'missing_local': [], 'missing_broker': []},
            'ok': True,
        }
        
        # 1. 现金对账
        account = self.get_account()
        if account:
            broker_cash = float(account.get('cash', 0))
            report['cash']['broker'] = broker_cash
            if expected_cash is not None:
                report['cash']['diff'] = broker_cash - expected_cash
                if abs(report['cash']['diff']) > 1.0:
                    report['ok'] = False
                    logger.warning(f"[CASH] Cash mismatch: local ${expected_cash:,.2f} vs broker ${broker_cash:,.2f}")
        
        # 2. 持仓对账
        broker_positions = {p['symbol']: int(p.get('qty', 0)) for p in self.get_positions() if p.get('qty', 0) > 0}
        local_positions = expected_positions or {}
        if self.pdt_tracker and not expected_positions:
            local_positions = {s: sum(l['qty'] for l in lots) for s, lots in self.pdt_tracker.positions.items()}
        
        all_symbols = set(broker_positions.keys()) | set(local_positions.keys())
        for symbol in all_symbols:
            b_qty = broker_positions.get(symbol, 0)
            l_qty = local_positions.get(symbol, 0)
            if b_qty == l_qty:
                report['positions']['matched'].append({'symbol': symbol, 'qty': b_qty})
            elif b_qty > 0 and l_qty > 0:
                report['positions']['mismatch'].append({'symbol': symbol, 'broker_qty': b_qty, 'local_qty': l_qty, 'diff': b_qty - l_qty})
                report['ok'] = False
            elif b_qty > 0 and l_qty == 0:
                report['positions']['missing_local'].append({'symbol': symbol, 'broker_qty': b_qty})
                report['ok'] = False
            elif l_qty > 0 and b_qty == 0:
                report['positions']['missing_broker'].append({'symbol': symbol, 'local_qty': l_qty})
                report['ok'] = False
        
        if not report['ok']:
            logger.warning(f"[WARN] Reconciliation mismatch: {report}")
        else:
            logger.info(f"[OK] Reconciliation consistent [{report['account_id']}]: {len(broker_positions)} positions")
        
        return report

    def cancel_order(self, order_id: str) -> bool:
        """撤销指定订单"""
        if not self.trading_client:
            logger.warning(f"Mock mode: cannot cancel order {order_id}")
            return True
        try:
            self.trading_client.cancel_order_by_id(order_id)
            logger.info(f"[OK] Order canceled: {order_id}")
            return True
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.error(f"Failed to cancel order {order_id} failed: {e}")
            return False

    def _mock_account(self):
        """模拟账户信息"""
        return {
            'id': 'mock-account',
            'cash': 1000000.0,
            'portfolio_value': 1000000.0,
            'equity': 1000000.0,
            'buying_power': 4000000.0,
            'status': 'ACTIVE',
            'account_type': 'MARGIN',
            'daytrade_count': 0,
            'pattern_day_trader': False,
            'trading_blocked': False,
            'trade_suspended_by_user': False,
        }

    def _mock_order(self, symbol, qty, side, client_order_id=None):
        """模拟订单（同时更新本地持仓和现金）"""
        order_id = f"mock-{datetime.now().timestamp()}"

        # 优先使用 fake client 更新持仓，保证 mock 模式下 get_positions/账户权益一致
        if self.trading_client and hasattr(self.trading_client, 'submit_order'):
            try:
                price = self._get_current_price(symbol) if self.mock else 100.0
            except Exception:
                price = 100.0

            class _SimpleOrderRequest:
                pass
            req = _SimpleOrderRequest()
            req.symbol = symbol
            req.qty = qty
            req.side = side
            req.client_order_id = client_order_id or f"mock-{uuid.uuid4().hex[:8]}"
            req.limit_price = None

            order = self.trading_client.submit_order(req)
            return self._order_to_dict(order)

        # 无 fake client 兜底
        logger.info(f"[MOCK] {side.upper()} {qty} {symbol} (orderID: {order_id})")
        return {
            'id': order_id,
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': 'market',
            'status': 'filled',
            'submitted_at': datetime.now().isoformat(),
            'filled_qty': qty,
            'filled_avg_price': 0.0,
            'client_order_id': client_order_id or f"mock-{uuid.uuid4().hex[:8]}",
        }

    def _get_current_price(self, symbol):
        """获取当前实时价格（P1 修复：优先 Alpaca LatestQuote，失败显式报错，不再回退到 100/yfinance）"""
        import time as _time

        now = _time.time()
        cache_key = f"price_{symbol}"
        if cache_key in self._price_cache:
            if now - self._price_cache_time.get(cache_key, 0) < 300:
                return self._price_cache[cache_key]

        if not self.data_client:
            # P1-9 修复：无真实价格源时暂停交易；但 mock 模式下保留默认价格，便于测试
            if self.mock:
                default_price = 100.0
                self._price_cache[cache_key] = default_price
                self._price_cache_time[cache_key] = now
                return default_price
            raise RuntimeError(f"No price source available, cannot get {symbol} price, trading paused")

        try:
            # P1 修复：优先使用报价（quote）而非成交价（trade），更反映当前市场
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self.data_client.get_stock_latest_quote(request)
            quote = quotes.get(symbol) if isinstance(quotes, dict) else quotes
            # 买入用 ask_price，卖出用 bid_price，通用取中间价
            bid = float(getattr(quote, 'bid_price', 0) or 0)
            ask = float(getattr(quote, 'ask_price', 0) or 0)
            price = (bid + ask) / 2.0 if bid > 0 and ask > 0 else max(bid, ask, 0)
            if price > 0:
                self._price_cache[cache_key] = price
                self._price_cache_time[cache_key] = now
                return price
        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.warning(f"Alpaca failed to get {symbol} quote failed: {e}")

        # 明确报错，不再回退
        raise RuntimeError(f"Cannot get {symbol} current price, trading paused")

    def close_all_positions(self):
        """平掉所有持仓（兼容 Alpaca SDK 方法名）"""
        return self.liquidate_all()

    def get_portfolio_summary(self):
        """获取组合摘要"""
        account = self.get_account()
        positions = self.get_positions()

        return {
            'timestamp': datetime.now().isoformat(),
            'cash': account.get('cash', 0.0),
            'portfolio_value': account.get('portfolio_value', 0.0),
            'positions_count': len(positions),
            'positions': positions,
        }


class AlpacaExecutor:
    """V14 策略专用 Alpaca 执行器

    新增功能:
    - PDT 规则检查
    - 限价单支持（自动价格方向）
    - Atomic 调仓预检查（避免部分成交导致组合状态异常）
    - 流动性检查（下单前验证市场深度）
    - Decimal 精度（资金计算使用 Decimal）
    """

    def __init__(self, api_key=None, api_secret=None, **kwargs):
        self.executor = AlpacaPaperExecutor(api_key, api_secret, **kwargs)
        self.positions_history = []

    def set_risk_monitor(self, risk_monitor):
        """设置风控监控器引用，实现交易开关同步。"""
        self.executor.risk_monitor = risk_monitor

    # 透传方法
    def market_is_open(self):
        return self.executor.market_is_open()

    def liquidate_all(self):
        return self.executor.liquidate_all()

    def submit_order(self, symbol, qty, side, order_type='market', time_in_force='day', limit_price=None):
        return self.executor.submit_order(symbol, qty, side, order_type, time_in_force, limit_price)

    def get_account(self):
        return self.executor.get_account()

    def get_positions(self):
        return self.executor.get_positions()

    def cancel_all_orders(self):
        return self.executor.cancel_all_orders()

    def get_orders(self, status='open'):
        return self.executor.get_orders(status)

    def start_rebalance_session(self):
        return self.executor.start_rebalance_session()

    def get_portfolio_summary(self):
        return self.executor.get_portfolio_summary()

    def _get_current_price(self, symbol):
        return self.executor._get_current_price(symbol)

    def sync_corporate_actions(self, symbols, start_date=None, end_date=None):
        """透传到执行器：同步公司行为并调整本地 lot"""
        return self.executor.sync_corporate_actions(symbols, start_date, end_date)

    def rebalance_portfolio(
        self,
        target_positions,
        max_position_pct=0.20,
        atomic_check=True,
        min_liquidity_ratio=2.0,
        order_type='market',
        limit_price=None,
        enable_rollback=True,
    ):
        """
        再平衡组合（带 Atomic 预检查、流动性检查、PDT 覆盖双向、回滚）

        参数:
            target_positions: dict, {symbol: target_value}
            max_position_pct: float, 单仓最大比例
            atomic_check: bool, 是否执行预检查
            min_liquidity_ratio: float, 最小流动性比例
            order_type: str, 'market' 或 'limit'
            limit_price: float, 限价（单只股票时有效，多只股票自动计算）
            enable_rollback: bool, 失败时是否回滚已卖出仓位
        """
        # 每次调仓前同步公司行为（拆股调整）
        self.sync_corporate_actions(list(target_positions.keys()))

        account = self.executor.get_account()
        if not account:
            logger.error("Cannot get account info")
            return {'status': 'FAILED', 'reason': 'no_account'}

        portfolio_value = account['portfolio_value']
        current_positions = {p['symbol']: p for p in self.executor.get_positions()}

        logger.info(f"\n{'='*60}")
        logger.info(f"Portfolio rebalance")
        logger.info(f"{'='*60}")
        logger.info(f"Portfolio value: ${portfolio_value:,.2f}")
        logger.info(f"Target positions: {len(target_positions)} symbols")

        # 归一化目标持仓
        if WEIGHT_ALLOC_NORM_AVAILABLE:
            original_total = sum(target_positions.values())
            target_positions = normalize_target_positions(target_positions, portfolio_value)
            if abs(original_total - sum(target_positions.values())) > 1:
                logger.info(f"[PORTFOLIO] Target positions normalized: ${original_total:,.0f} → ${sum(target_positions.values()):,.0f}")

        # Atomic 预检查
        if atomic_check:
            precheck = self._atomic_precheck(
                target_positions, current_positions,
                portfolio_value, max_position_pct, min_liquidity_ratio
            )
            if not precheck['pass']:
                logger.error(f"[ERROR] Atomic pre-check failed: {precheck['reason']}")
                self.executor._send_alert('execution_error', 'atomic_precheck', precheck['reason'])
                return {'status': 'PRECHECK_FAILED', **precheck}
            logger.info(f"[OK] Atomic pre-check passed ({precheck['orders_count']} orders)")

        # 记录调仓前状态
        pre_state = {
            'timestamp': datetime.now().isoformat(),
            'positions': current_positions.copy(),
            'cash': account['cash'],
        }

        executed_orders = []
        failed_orders = []
        sold_positions = []  # 用于回滚

        # 阶段 1: 卖出不在目标列表中的持仓
        for symbol, pos in current_positions.items():
            if symbol not in target_positions:
                # P0 修复：卖出侧也做 PDT 检查
                pdt_check = self.executor._check_pdt(symbol, 'sell')
                if not pdt_check['allowed']:
                    failed_orders.append({'symbol': symbol, 'side': 'sell', 'reason': pdt_check['reason']})
                    logger.error(f"[ERROR] PDT blocked sell: {symbol} ({pdt_check['reason']})")
                    continue
                try:
                    result = self.executor.submit_order(symbol, pos['qty'], 'sell', order_type=order_type)
                    if result:
                        executed_orders.append(result)
                        sold_positions.append({'symbol': symbol, 'qty': result.get('filled_qty', pos['qty'])})
                        self.executor.record_fill(symbol, 'sell', result.get('filled_qty', pos['qty']))
                        logger.info(f"[SELL] Selling: {symbol} x {pos['qty']}")
                    else:
                        failed_orders.append({'symbol': symbol, 'side': 'sell', 'reason': 'submit_failed'})
                        logger.error(f"[ERROR] Sell failed: {symbol}")
                except (APIError, RequestException, ConnectionError, Timeout, ValueError) as e:
                    failed_orders.append({'symbol': symbol, 'side': 'sell', 'reason': str(e)})
                    logger.error(f"[ERROR] Sell exception: {symbol}: {e}")

        # 阶段 2: 买入/调整目标持仓
        for symbol, target_value in target_positions.items():
            target_value = min(target_value, portfolio_value * max_position_pct)
            try:
                current_price = self._get_current_price(symbol)
            except RuntimeError as e:
                failed_orders.append({'symbol': symbol, 'side': 'buy', 'reason': str(e)})
                logger.error(f"[ERROR] Cannot get price: {symbol}: {e}")
                continue

            target_qty = self.executor._calculate_qty(target_value, current_price, symbol=symbol)
            current_qty = current_positions.get(symbol, {}).get('qty', 0)
            diff = target_qty - current_qty

            if abs(diff) > 0:
                side = 'buy' if diff > 0 else 'sell'
                qty = abs(diff)

                # P0 修复：PDT 检查覆盖卖出侧
                pdt_check = self.executor._check_pdt(symbol, side)
                if not pdt_check['allowed']:
                    failed_orders.append({'symbol': symbol, 'side': side, 'reason': pdt_check['reason']})
                    logger.error(f"[ERROR] PDT blocked {side}: {symbol} ({pdt_check['reason']})")
                    continue

                logger.info(f"[ROLLBACK] {side.upper()}: {symbol} x {qty} (target: ${target_value:,.0f})")

                try:
                    result = self.executor.submit_order(symbol, qty, side, order_type=order_type)
                    if result:
                        executed_orders.append(result)
                        self.executor.record_fill(symbol, side, result.get('filled_qty', qty))
                    else:
                        failed_orders.append({'symbol': symbol, 'side': side, 'reason': 'submit_failed'})
                        logger.error(f"[ERROR] Order failed: {symbol} {side}")
                        # P0 修复：买入失败时回滚已卖出仓位
                        if side == 'buy' and enable_rollback and sold_positions:
                            self._rollback_sells(sold_positions)
                            return {
                                'status': 'PARTIAL_ROLLBACK',
                                'executed': executed_orders,
                                'failed': failed_orders,
                                'pre_state': pre_state,
                            }
                except (APIError, RequestException, ConnectionError, Timeout, ValueError) as e:
                    failed_orders.append({'symbol': symbol, 'side': side, 'reason': str(e)})
                    logger.error(f"[ERROR] Order exception: {symbol}: {e}")
                    if side == 'buy' and enable_rollback and sold_positions:
                        self._rollback_sells(sold_positions)
                        return {
                            'status': 'PARTIAL_ROLLBACK',
                            'executed': executed_orders,
                            'failed': failed_orders,
                            'pre_state': pre_state,
                        }

        logger.info(f"[OK] Rebalance completed: {len(executed_orders)} success, {len(failed_orders)} failed")

        return {
            'status': 'COMPLETED' if not failed_orders else 'PARTIAL',
            'executed': executed_orders,
            'failed': failed_orders,
            'pre_state': pre_state,
        }

    def _rollback_sells(self, sold_positions):
        """P0 修复：回滚已卖出仓位（买入失败时买回）"""
        logger.warning(f"[ROLLBACK] Executing rollback: {len(sold_positions)} sell(s)")
        for sold in sold_positions:
            symbol = sold.get('symbol')
            qty = sold.get('qty', 0)
            if qty > 0 and symbol:
                try:
                    logger.info(f"[ROLLBACK] Rollback: buy back {symbol} x {qty}")
                    self.executor.submit_order(symbol, qty, 'buy')
                except (APIError, RequestException, ConnectionError, Timeout, ValueError) as e:
                    logger.error(f"Rollback failed {symbol}: {e}")

    def _atomic_precheck(self, target_positions, current_positions,
                         portfolio_value, max_position_pct, min_liquidity_ratio):
        """Atomic 预检查"""
        # 1. 市场状态
        if not self.executor.market_is_open():
            return {'pass': False, 'reason': 'market_closed', 'orders_count': 0}

        # 2. 账户状态
        account = self.executor.get_account()
        if not account or account.get('status') != 'ACTIVE':
            return {'pass': False, 'reason': 'account_not_active', 'orders_count': 0}

        if account.get('trading_blocked') or account.get('trade_suspended_by_user'):
            return {'pass': False, 'reason': 'account_blocked', 'orders_count': 0}

        # 3. 预估资金需求
        total_buy_value = Decimal('0')
        sell_release = Decimal('0')
        orders_count = 0

        for symbol, target_value in target_positions.items():
            target_value = min(target_value, portfolio_value * max_position_pct)
            current_qty = current_positions.get(symbol, {}).get('qty', 0)
            try:
                current_price = self._get_current_price(symbol)
            except RuntimeError as e:
                return {'pass': False, 'reason': f'price_unavailable: {symbol} {e}', 'orders_count': 0}
            target_qty = self.executor._calculate_qty(target_value, current_price, symbol=symbol)

            diff = target_qty - current_qty
            if diff > 0:
                total_buy_value += Decimal(str(target_value))
                orders_count += 1
            elif diff < 0:
                sell_release += Decimal(str(current_positions[symbol]['market_value']))
                orders_count += 1

        available_cash = Decimal(str(account['cash'])) + sell_release
        if total_buy_value > available_cash * Decimal('1.05'):
            return {
                'pass': False,
                'reason': f'insufficient_cash: need ${float(total_buy_value):,.0f}, have ${float(available_cash):,.0f}',
                'orders_count': 0
            }

        # 4. 流动性检查
        liquidity_issues = []
        for symbol, target_value in target_positions.items():
            target_value = min(target_value, portfolio_value * max_position_pct)
            try:
                current_price = self._get_current_price(symbol)
            except RuntimeError as e:
                liquidity_issues.append(f"{symbol}: price_unavailable")
                continue
            target_qty = self.executor._calculate_qty(target_value, current_price, symbol=symbol)
            current_qty = current_positions.get(symbol, {}).get('qty', 0)

            if target_qty > current_qty:
                liquidity = self._check_liquidity(symbol, target_qty - current_qty)
                if not liquidity['sufficient']:
                    liquidity_issues.append(f"{symbol}: {liquidity['reason']}")

        if liquidity_issues:
            return {
                'pass': False,
                'reason': f'liquidity_insufficient: {"; ".join(liquidity_issues)}',
                'orders_count': 0
            }

        return {'pass': True, 'reason': 'ok', 'orders_count': orders_count}

    def _check_liquidity(self, symbol, qty_needed):
        """检查标的流动性"""
        if not self.executor.trading_client:
            return {'sufficient': True, 'reason': 'mock_mode'}

        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self.executor.data_client.get_stock_latest_quote(request)
            quote = quotes.get(symbol) if isinstance(quotes, dict) else quotes

            ask_size = getattr(quote, 'ask_size', 0) or 0
            bid_size = getattr(quote, 'bid_size', 0) or 0
            avg_size = (ask_size + bid_size) / 2.0

            if avg_size == 0:
                return {'sufficient': False, 'reason': 'no_quote_size_available'}

            if qty_needed <= avg_size * 2:
                return {'sufficient': True, 'reason': f'ask_size={ask_size}, bid_size={bid_size}'}
            else:
                return {
                    'sufficient': False,
                    'reason': f'qty_needed={qty_needed} > 2*avg_size={avg_size*2}'
                }

        except (APIError, RequestException, ConnectionError, Timeout) as e:
            logger.warning(f"Liquidity check failed {symbol}: {e}")
            return {'sufficient': True, 'reason': 'check_failed_assuming_ok'}

    def _calculate_qty(self, target_value, current_price, symbol=None):
        """P0-2 修复：将 _calculate_qty 下放到 AlpacaPaperExecutor，
        V14 包装器透传到底层执行器，避免 AttributeError"""
        return self.executor._calculate_qty(target_value, current_price, symbol=symbol)


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    # 创建执行器
    executor = AlpacaPaperExecutor()

    # 获取账户信息
    account = executor.get_account()
    print(f"\nAccount info:")
    print(f"  Cash: ${account['cash']:,.2f}")
    print(f"  Portfolio value: ${account['portfolio_value']:,.2f}")
    print(f"  Buying power: ${account['buying_power']:,.2f}")
    print(f"  Account type: {account.get('account_type', 'MARGIN')}")
    print(f"  5-day daytrade count: {account.get('daytrade_count', 0)}")

    # 获取持仓
    positions = executor.get_positions()
    print(f"\nCurrent positions ({len(positions)}):")
    for p in positions:
        print(f"  {p['symbol']}: {p['qty']} shares, market value ${p['market_value']:,.2f}")

    # 检查市场状态
    is_open = executor.market_is_open()
    print(f"\nMarket status: {'open' if is_open else 'closed'}")
