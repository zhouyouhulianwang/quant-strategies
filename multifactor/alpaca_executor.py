"""
Alpaca Paper Trading 执行模块
使用新版 alpaca-py SDK，支持订单提交、持仓查询、账户状态监控
新增: PDT 检查、限价单、Atomic 调仓预检查、流动性检查、Decimal 精度
"""

import os
import json
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Union
import logging

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

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('alpaca_executor')

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
    logger.warning(f"alpaca-py 未安装: {e}，使用模拟模式")
    ALPACA_AVAILABLE = False


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
        """
        # 尝试从 .env 文件读取
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

        # 实盘模式二次确认
        if not paper and not mock and require_live_confirmation:
            confirmed = self._confirm_live_mode()
            if not confirmed:
                raise RuntimeError("用户未确认实盘模式，已中止")

        if not self.api_key or not self.api_secret:
            if not mock:
                raise ValueError("请提供 Alpaca API Key 和 Secret，或在 .env 文件中设置")
            self.api_key = self.api_key or 'MOCK-KEY'
            self.api_secret = self.api_secret or 'MOCK-SECRET'

        # 未指定 base_url 时，根据 paper 模式使用默认值
        if not self.base_url:
            self.base_url = 'https://paper-api.alpaca.markets' if paper else 'https://api.alpaca.markets'

        # 初始化 API
        self.trading_client = None
        self.data_client = None
        if ALPACA_AVAILABLE and not mock:
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
                logger.info("✅ Alpaca API 已连接并启用速率限制 (200/min)")
            except ImportError:
                self.trading_client = raw_trading_client
                self.data_client = raw_data_client
                logger.info(f"✅ Alpaca API 已连接: {self.base_url}")
        else:
            if mock:
                logger.warning("⚠️ 使用模拟模式（不连接真实 API）")
            else:
                logger.warning("⚠️ 使用模拟模式（alpaca-py 未安装）")

        # PDT 追踪器（按 account_id 和 paper/live 分文件）
        self.pdt_tracker = None
        if PDT_AVAILABLE and enable_pdt:
            account_id = self._get_account_id() if not mock else ('paper' if paper else 'live')
            self.pdt_tracker = PDTTracker(
                account_id=account_id,
                paper=paper,
                min_equity_for_unlimited=pdt_min_equity,
                enabled=True,
            )
        self.enable_pdt = enable_pdt

        # 当前调仓会话 ID（用于订单幂等性）
        self.rebalance_session = None
        self.use_limit_orders = use_limit_orders
        self.limit_order_offset_pct = limit_order_offset_pct

        # 缓存
        self._price_cache = {}
        self._price_cache_time = {}

    def start_rebalance_session(self):
        """开始新的调仓会话，生成唯一 ID"""
        self.rebalance_session = uuid.uuid4().hex[:8]
        logger.info(f"🔄 开始调仓会话: {self.rebalance_session}")
        return self.rebalance_session

    def _confirm_live_mode(self) -> bool:
        """实盘模式二次确认"""
        import sys
        logger.critical("🚨🚨🚨 正在初始化实盘（LIVE）模式！🚨🚨🚨")
        logger.critical(f"   账户 API Key: {self.api_key[:8]}...")
        logger.critical(f"   Base URL: {self.base_url}")
        logger.critical("   请确认您确实要连接真实资金账户并执行交易。")
        try:
            answer = input("请输入 'LIVE' 以确认实盘模式（其他输入将中止）: ")
        except EOFError:
            # 非交互环境（如 CI、自动化脚本）默认拒绝
            logger.error("非交互环境，无法确认实盘模式，已中止")
            return False
        if answer.strip() == 'LIVE':
            logger.critical("✅ 已确认实盘模式，继续初始化")
            return True
        logger.critical("❌ 未确认实盘模式，已中止")
        return False

    def _get_account_id(self) -> str:
        """从 Alpaca 获取账户 ID，用于 PDT 状态文件区分"""
        if not self.trading_client:
            return 'paper' if self.paper else 'live'
        try:
            account = self.trading_client.get_account()
            return str(getattr(account, 'id', 'unknown'))
        except Exception as e:
            logger.warning(f"获取账户 ID 失败: {e}")
            return 'paper' if self.paper else 'live'

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
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
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
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
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
        """PDT 检查"""
        if not self.pdt_tracker or not self.enable_pdt:
            return {'allowed': True, 'reason': 'pdt_disabled'}

        account = self._get_account_raw()
        if not account:
            return {'allowed': True, 'reason': 'account_unavailable'}

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
    ):
        """构造 alpaca-py 的订单请求对象"""
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
                offset = self.limit_order_offset_pct
                if side.lower() == 'buy':
                    limit_price = current_price * (1 - offset)
                else:
                    limit_price = current_price * (1 + offset)
                logger.info(f"💰 自动计算限价: {symbol} {side} @ ${limit_price:.4f}")

            return LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side_enum,
                time_in_force=tif,
                limit_price=round(limit_price, 4),
            )

        return MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side_enum,
            time_in_force=tif,
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
        提交订单（支持幂等性、PDT 检查、限价单）

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
        if not self.trading_client:
            return self._mock_order(symbol, qty, side)

        # 买入前检查 PDT
        if side.lower() == 'buy':
            pdt_check = self._check_pdt(symbol, side)
            if not pdt_check['allowed']:
                logger.error(f"❌ PDT 阻止开仓: {symbol} ({pdt_check['reason']})")
                return None

        # 检查是否已有同会话的未完成订单（幂等性）
        session_prefix = self.rebalance_session or 'manual'
        client_order_id = f"v14-{session_prefix}-{symbol}-{side}"

        existing = self._find_order_by_client_id(client_order_id)
        if existing:
            logger.info(f"🔄 发现同会话订单，跳过重复提交: {client_order_id}")
            return existing

        # 如果未指定限价单价格，但配置为限价模式，则转限价单
        if self.use_limit_orders and order_type.lower() == 'market':
            order_type = 'limit'
            logger.info(f"💰 配置为限价模式，将 {symbol} 转为限价单")

        try:
            order_request = self._build_order_request(
                symbol, qty, side, order_type, time_in_force, limit_price
            )
            order = self.trading_client.submit_order(order_request)

            logger.info(f"✅ 订单已提交: {side.upper()} {qty} {symbol} (ID: {client_order_id})")
            result = self._order_to_dict(order)
            result['client_order_id'] = client_order_id

            return result
        except APIError as e:
            logger.error(f"Alpaca API 错误，提交订单失败: {e}")
            return None
        except Exception as e:
            logger.error(f"提交订单失败: {e}")
            return None

    def _find_order_by_client_id(self, client_order_id):
        """通过 client_order_id 查找已存在的订单"""
        if not self.trading_client:
            return None

        try:
            request = GetOrdersRequest(
                status=QueryOrderStatus.ALL,
                limit=100,
            )
            orders = self.trading_client.get_orders(request)
            for o in orders:
                o_dict = self._order_to_dict(o)
                if o_dict.get('client_order_id') == client_order_id:
                    return o_dict
        except Exception:
            pass

        return None

    def cancel_all_orders(self):
        """取消所有未成交订单"""
        if not self.trading_client:
            return True

        try:
            self.trading_client.cancel_orders()
            logger.info("✅ 所有订单已取消")
            return True
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
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
        except Exception as e:
            logger.error(f"获取订单失败: {e}")
            return []

    def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        """通过订单 ID 获取订单"""
        if not self.trading_client:
            return None

        try:
            order = self.trading_client.get_order_by_id(order_id)
            return self._order_to_dict(order)
        except Exception as e:
            logger.warning(f"获取订单 {order_id} 失败: {e}")
            return None

    def market_is_open(self):
        """检查市场是否开盘"""
        if not self.trading_client:
            return True  # 模拟模式假设市场开盘

        try:
            clock = self.trading_client.get_clock()
            return bool(getattr(clock, 'is_open', False))
        except Exception as e:
            logger.error(f"获取市场状态失败: {e}")
            return False

    def liquidate_all(self):
        """平掉所有持仓"""
        if not self.trading_client:
            positions = self.get_positions()
            for pos in positions:
                self._mock_order(pos['symbol'], pos['qty'], 'sell')
            return len(positions)

        try:
            self.trading_client.close_all_positions()
            logger.info("✅ 已平掉所有持仓")

            # 记录 PDT 平仓
            if self.pdt_tracker:
                for pos in self.get_positions():
                    self.pdt_tracker.record_fill(pos['symbol'], 'sell', pos['qty'])
            return 1
        except Exception as e:
            logger.error(f"平仓失败: {e}")
            # 回退到逐个卖出
            positions = self.get_positions()
            for pos in positions:
                self.submit_order(pos['symbol'], pos['qty'], 'sell')
            return len(positions)

    # ========== 模拟模式 ==========

    def record_fill(self, symbol: str, side: str, filled_qty: int):
        """记录一笔成交，用于 PDT 追踪"""
        if self.pdt_tracker and filled_qty > 0:
            self.pdt_tracker.record_fill(symbol, side, filled_qty)

    def sync_positions(self):
        """与 Alpaca 持仓同步，用于 PDT 准确追踪"""
        if not self.pdt_tracker:
            return
        positions = self.get_positions()
        self.pdt_tracker.sync_positions(positions)
        logger.info(f"🔄 PDT 持仓已同步 [{self.pdt_tracker.account_id}]: {len(positions)} 个持仓")

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
                    logger.warning(f"💰 现金差异: 本地 ${expected_cash:,.2f} vs 券商 ${broker_cash:,.2f}")
        
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
            logger.warning(f"⚠️ 对账发现差异: {report}")
        else:
            logger.info(f"✅ 对账一致 [{report['account_id']}]: {len(broker_positions)} 个持仓")
        
        return report

    def cancel_order(self, order_id: str) -> bool:
        """撤销指定订单"""
        if not self.trading_client:
            logger.warning(f"模拟模式：无法撤销订单 {order_id}")
            return True
        try:
            self.trading_client.cancel_order_by_id(order_id)
            logger.info(f"✅ 订单已撤销: {order_id}")
            return True
        except Exception as e:
            logger.error(f"撤销订单 {order_id} 失败: {e}")
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

    def _mock_order(self, symbol, qty, side):
        """模拟订单"""
        order_id = f"mock-{datetime.now().timestamp()}"
        logger.info(f"[模拟] {side.upper()} {qty} {symbol} (订单ID: {order_id})")
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
            'client_order_id': f"mock-{uuid.uuid4().hex[:8]}",
        }

    def _get_current_price(self, symbol):
        """获取当前实时价格（优先 Alpaca 最新成交价）"""
        import time as _time

        now = _time.time()
        cache_key = f"price_{symbol}"
        if cache_key in self._price_cache:
            if now - self._price_cache_time.get(cache_key, 0) < 300:
                return self._price_cache[cache_key]

        # 尝试 Alpaca API 获取最新成交
        if self.data_client:
            try:
                request = StockLatestTradeRequest(symbol_or_symbols=symbol)
                trades = self.data_client.get_stock_latest_trade(request)
                # 返回可能是 dict
                trade = trades.get(symbol) if isinstance(trades, dict) else trades
                price = float(getattr(trade, 'price', 0))
                if price > 0:
                    self._price_cache[cache_key] = price
                    self._price_cache_time[cache_key] = now
                    return price
            except Exception as e:
                logger.warning(f"Alpaca 获取 {symbol} 价格失败: {e}")

        # 回退: yfinance
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1m")
            if len(hist) > 0:
                price = float(hist['Close'].iloc[-1])
                self._price_cache[cache_key] = price
                self._price_cache_time[cache_key] = now
                return price
        except Exception as e:
            logger.warning(f"yfinance 获取 {symbol} 价格失败: {e}")

        # 最终回退
        logger.error(f"无法获取 {symbol} 价格，使用默认值 100")
        return 100.0

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


class V14AlpacaExecutor:
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

    def rebalance_portfolio(
        self,
        target_positions,
        max_position_pct=0.20,
        atomic_check=True,
        min_liquidity_ratio=2.0,
        order_type='market',
        limit_price=None,
    ):
        """
        再平衡组合（带 Atomic 预检查和流动性检查）

        参数:
            target_positions: dict, {symbol: target_value}
            max_position_pct: float, 单仓最大比例
            atomic_check: bool, 是否执行预检查
            min_liquidity_ratio: float, 最小流动性比例
            order_type: str, 'market' 或 'limit'
            limit_price: float, 限价（单只股票时有效，多只股票自动计算）
        """
        account = self.executor.get_account()
        if not account:
            logger.error("无法获取账户信息")
            return {'status': 'FAILED', 'reason': 'no_account'}

        portfolio_value = account['portfolio_value']
        current_positions = {p['symbol']: p for p in self.executor.get_positions()}

        logger.info(f"\n{'='*60}")
        logger.info(f"组合再平衡")
        logger.info(f"{'='*60}")
        logger.info(f"组合价值: ${portfolio_value:,.2f}")
        logger.info(f"目标持仓: {len(target_positions)} 只")

        # 归一化目标持仓
        if WEIGHT_ALLOC_NORM_AVAILABLE:
            original_total = sum(target_positions.values())
            target_positions = normalize_target_positions(target_positions, portfolio_value)
            if abs(original_total - sum(target_positions.values())) > 1:
                logger.info(f"📊 目标持仓已归一化: ${original_total:,.0f} → ${sum(target_positions.values()):,.0f}")

        # Atomic 预检查
        if atomic_check:
            precheck = self._atomic_precheck(
                target_positions, current_positions,
                portfolio_value, max_position_pct, min_liquidity_ratio
            )
            if not precheck['pass']:
                logger.error(f"❌ Atomic 预检查失败: {precheck['reason']}")
                return {'status': 'PRECHECK_FAILED', **precheck}
            logger.info(f"✅ Atomic 预检查通过 ({precheck['orders_count']} 笔订单)")

        # 记录调仓前状态
        pre_state = {
            'timestamp': datetime.now().isoformat(),
            'positions': current_positions.copy(),
            'cash': account['cash'],
        }

        executed_orders = []
        failed_orders = []

        # 阶段 1: 卖出不在目标列表中的持仓
        for symbol, pos in current_positions.items():
            if symbol not in target_positions:
                try:
                    result = self.executor.submit_order(symbol, pos['qty'], 'sell', order_type=order_type)
                    if result:
                        executed_orders.append(result)
                        logger.info(f"🔄 卖出: {symbol} x {pos['qty']}")
                    else:
                        failed_orders.append({'symbol': symbol, 'side': 'sell', 'reason': 'submit_failed'})
                        logger.error(f"❌ 卖出失败: {symbol}")
                except Exception as e:
                    failed_orders.append({'symbol': symbol, 'side': 'sell', 'reason': str(e)})
                    logger.error(f"❌ 卖出异常: {symbol}: {e}")

        # 阶段 2: 买入/调整目标持仓
        for symbol, target_value in target_positions.items():
            target_value = min(target_value, portfolio_value * max_position_pct)
            current_price = self._get_current_price(symbol)

            target_qty = self._calculate_qty(target_value, current_price)
            current_qty = current_positions.get(symbol, {}).get('qty', 0)
            diff = target_qty - current_qty

            if abs(diff) > 0:
                side = 'buy' if diff > 0 else 'sell'
                qty = abs(diff)

                logger.info(f"🔄 {side.upper()}: {symbol} x {qty} (目标: ${target_value:,.0f})")

                try:
                    result = self.executor.submit_order(symbol, qty, side, order_type=order_type)
                    if result:
                        executed_orders.append(result)
                    else:
                        failed_orders.append({'symbol': symbol, 'side': side, 'reason': 'submit_failed'})
                        logger.error(f"❌ 订单失败: {symbol} {side}")
                except Exception as e:
                    failed_orders.append({'symbol': symbol, 'side': side, 'reason': str(e)})
                    logger.error(f"❌ 订单异常: {symbol}: {e}")

        logger.info(f"✅ 再平衡完成: {len(executed_orders)} 笔成功, {len(failed_orders)} 笔失败")

        return {
            'status': 'COMPLETED' if not failed_orders else 'PARTIAL',
            'executed': executed_orders,
            'failed': failed_orders,
            'pre_state': pre_state,
        }

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
            current_price = self._get_current_price(symbol)
            target_qty = self._calculate_qty(target_value, current_price)

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
            current_price = self._get_current_price(symbol)
            target_qty = self._calculate_qty(target_value, current_price)
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

        except Exception as e:
            logger.warning(f"流动性检查失败 {symbol}: {e}")
            return {'sufficient': True, 'reason': 'check_failed_assuming_ok'}

    def _calculate_qty(self, target_value, current_price):
        """使用 Decimal 精度计算股数（返回整数，保持与原有逻辑兼容）"""
        if current_price <= 0:
            return 0

        value_d = Decimal(str(target_value))
        price_d = Decimal(str(current_price))
        qty_d = (value_d / price_d).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        return int(qty_d)


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    # 创建执行器
    executor = AlpacaPaperExecutor()

    # 获取账户信息
    account = executor.get_account()
    print(f"\n账户信息:")
    print(f"  现金: ${account['cash']:,.2f}")
    print(f"  组合价值: ${account['portfolio_value']:,.2f}")
    print(f"  购买力: ${account['buying_power']:,.2f}")
    print(f"  账户类型: {account.get('account_type', 'MARGIN')}")
    print(f"  5日 daytrade 数: {account.get('daytrade_count', 0)}")

    # 获取持仓
    positions = executor.get_positions()
    print(f"\n当前持仓 ({len(positions)}):")
    for p in positions:
        print(f"  {p['symbol']}: {p['qty']} 股, 市值 ${p['market_value']:,.2f}")

    # 检查市场状态
    is_open = executor.market_is_open()
    print(f"\n市场状态: {'开盘' if is_open else '收盘'}")
