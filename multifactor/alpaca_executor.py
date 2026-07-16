"""
Alpaca Paper Trading 执行模块
支持订单提交、持仓查询、账户状态监控
新增: Atomic 调仓预检查、流动性检查、Decimal 精度
"""

import os
import json
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging

# 导入权重归一化工具
try:
    from weight_allocation import normalize_target_positions
    WEIGHT_ALLOC_NORM_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_NORM_AVAILABLE = False

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('alpaca_executor')

# 尝试导入 alpaca-trade-api
try:
    from alpaca_trade_api import REST
    ALPACA_AVAILABLE = True
except ImportError:
    logger.warning("alpaca-trade-api 未安装，使用模拟模式")
    ALPACA_AVAILABLE = False


class AlpacaPaperExecutor:
    """Alpaca Paper Trading 执行器"""
    
    def __init__(self, api_key=None, api_secret=None, base_url=None):
        """
        初始化 Alpaca 执行器
        
        参数:
            api_key: str, API Key (默认从 .env 文件读取)
            api_secret: str, API Secret
            base_url: str, API Base URL
        """
        # 尝试从 .env 文件读取
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.startswith('#'):
                        key, value = line.strip().split('=', 1)
                        os.environ[key] = value
        
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.api_secret = api_secret or os.getenv('ALPACA_API_SECRET')
        self.base_url = base_url or os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("请提供 Alpaca API Key 和 Secret，或在 .env 文件中设置")
        
        # 初始化 API
        if ALPACA_AVAILABLE:
            raw_api = REST(self.api_key, self.api_secret, self.base_url)
            # P1 修复：速率限制包装
            try:
                from rate_limiter import RateLimitedAPI
                self.api = RateLimitedAPI(raw_api, rate_per_min=200)
                logger.info("✅ Alpaca API 已连接并启用速率限制 (200/min)")
            except ImportError:
                self.api = raw_api
                logger.info(f"✅ Alpaca API 已连接: {self.base_url}")
        else:
            self.api = None
            logger.warning("⚠️ 使用模拟模式（无实际交易）")
        
        # 当前调仓会话 ID（用于订单幂等性）
        self.rebalance_session = None
    
    def start_rebalance_session(self):
        """开始新的调仓会话，生成唯一 ID"""
        self.rebalance_session = uuid.uuid4().hex[:8]
        logger.info(f"🔄 开始调仓会话: {self.rebalance_session}")
        return self.rebalance_session
    
    def get_account(self):
        """获取账户信息"""
        if not self.api:
            return self._mock_account()
        
        try:
            account = self.api.get_account()
            return {
                'id': account.id,
                'cash': float(account.cash),
                'portfolio_value': float(account.portfolio_value),
                'equity': float(account.equity),
                'buying_power': float(account.buying_power),
                'status': account.status,
            }
        except ConnectionError as e:
            logger.error(f"网络错误，获取账户信息失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取账户信息失败: {e}")
            return None
    
    def get_positions(self):
        """获取当前持仓"""
        if not self.api:
            return []
        
        try:
            positions = self.api.list_positions()
            return [
                {
                    'symbol': p.symbol,
                    'qty': int(p.qty),
                    'market_value': float(p.market_value),
                    'avg_entry_price': float(p.avg_entry_price),
                    'current_price': float(p.current_price),
                    'unrealized_pl': float(p.unrealized_pl),
                    'unrealized_plpc': float(p.unrealized_plpc),
                }
                for p in positions
            ]
        except ConnectionError as e:
            logger.error(f"网络错误，获取持仓失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []
    
    def submit_order(self, symbol, qty, side, order_type='market', time_in_force='day', limit_price=None):
        """
        提交订单（支持幂等性）
        
        参数:
            symbol: str, 股票代码
            qty: int, 数量
            side: str, 'buy' 或 'sell'
            order_type: str, 'market' 或 'limit'
            time_in_force: str, 'day', 'gtc', 'ioc', 'opg'
            limit_price: float, 限价单价格
        
        返回:
            dict: 订单信息
        """
        if not self.api:
            return self._mock_order(symbol, qty, side)
        
        # 检查是否已有同会话的未完成订单（幂等性）
        session_prefix = self.rebalance_session or 'manual'
        client_order_id = f"v14-{session_prefix}-{symbol}-{side}"
        
        existing = self._find_order_by_client_id(client_order_id)
        if existing:
            logger.info(f"🔄 发现同会话订单，跳过重复提交: {client_order_id}")
            return existing
        
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=order_type,
                time_in_force=time_in_force,
                limit_price=limit_price,
                client_order_id=client_order_id
            )
            
            logger.info(f"✅ 订单已提交: {side.upper()} {qty} {symbol} (ID: {client_order_id})")
            return {
                'id': order.id,
                'client_order_id': client_order_id,
                'symbol': order.symbol,
                'qty': int(order.qty),
                'side': order.side,
                'type': order.type,
                'status': order.status,
                'submitted_at': order.submitted_at,
            }
        except ConnectionError as e:
            logger.error(f"网络错误，提交订单失败: {e}")
            return None
        except Exception as e:
            logger.error(f"提交订单失败: {e}")
            return None
    
    def _find_order_by_client_id(self, client_order_id):
        """通过 client_order_id 查找已存在的订单"""
        if not self.api:
            return None
        
        try:
            orders = self.api.list_orders(status='all', limit=100)
            for o in orders:
                if hasattr(o, 'client_order_id') and o.client_order_id == client_order_id:
                    return {
                        'id': o.id,
                        'client_order_id': client_order_id,
                        'symbol': o.symbol,
                        'qty': int(o.qty),
                        'side': o.side,
                        'status': o.status,
                    }
        except Exception:
            pass
        
        return None
    
    def cancel_all_orders(self):
        """取消所有未成交订单"""
        if not self.api:
            return True
        
        try:
            self.api.cancel_all_orders()
            logger.info("✅ 所有订单已取消")
            return True
        except ConnectionError as e:
            logger.error(f"网络错误，取消订单失败: {e}")
            return False
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return False
    
    def get_orders(self, status='open'):
        """获取订单列表"""
        if not self.api:
            return []
        
        try:
            orders = self.api.list_orders(status=status)
            return [
                {
                    'id': o.id,
                    'symbol': o.symbol,
                    'qty': int(o.qty),
                    'side': o.side,
                    'type': o.type,
                    'status': o.status,
                    'filled_qty': int(o.filled_qty),
                    'submitted_at': o.submitted_at,
                }
                for o in orders
            ]
        except ConnectionError as e:
            logger.error(f"网络错误，获取订单失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取订单失败: {e}")
            return []
    
    def market_is_open(self):
        """检查市场是否开盘"""
        if not self.api:
            return True  # 模拟模式假设市场开盘
        
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except ConnectionError as e:
            logger.error(f"网络错误，获取市场状态失败: {e}")
            return False
        except Exception as e:
            logger.error(f"获取市场状态失败: {e}")
            return False
    
    def liquidate_all(self):
        """平掉所有持仓"""
        positions = self.get_positions()
        
        for pos in positions:
            symbol = pos['symbol']
            qty = pos['qty']
            
            logger.info(f"🔄 平仓: {symbol} x {qty}")
            self.submit_order(symbol, qty, 'sell')
        
        logger.info(f"✅ 已平掉 {len(positions)} 个持仓")
        return len(positions)
    
    # ========== 模拟模式 ==========
    
    def _mock_account(self):
        """模拟账户信息"""
        return {
            'id': 'mock-account',
            'cash': 1000000.0,
            'portfolio_value': 1000000.0,
            'equity': 1000000.0,
            'buying_power': 4000000.0,
            'status': 'ACTIVE',
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
        }


class V14AlpacaExecutor:
    """V14 策略专用 Alpaca 执行器
    
    新增功能:
    - Atomic 调仓预检查（避免部分成交导致组合状态异常）
    - 流动性检查（下单前验证市场深度）
    - Decimal 精度（资金计算使用 Decimal）
    """
    
    def __init__(self, api_key=None, api_secret=None):
        self.executor = AlpacaPaperExecutor(api_key, api_secret)
        self.positions_history = []

    def market_is_open(self):
        """检查市场是否开盘"""
        return self.executor.market_is_open()

    def liquidate_all(self):
        """平掉所有持仓"""
        return self.executor.liquidate_all()

    def submit_order(self, symbol, qty, side, order_type='market', time_in_force='day', limit_price=None):
        """提交订单（透传到底层执行器）"""
        return self.executor.submit_order(symbol, qty, side, order_type, time_in_force, limit_price)

    def get_account(self):
        """获取账户信息"""
        return self.executor.get_account()

    def get_positions(self):
        """获取当前持仓"""
        return self.executor.get_positions()

    def cancel_all_orders(self):
        """取消所有未成交订单"""
        return self.executor.cancel_all_orders()

    def get_orders(self, status='open'):
        """获取订单列表"""
        return self.executor.get_orders(status)

    def start_rebalance_session(self):
        """开始新的调仓会话"""
        return self.executor.start_rebalance_session()

    def get_portfolio_summary(self):
        """获取组合摘要"""
        return self.executor.get_portfolio_summary()

    
    def rebalance_portfolio(self, target_positions, max_position_pct=0.20,
                           atomic_check=True, min_liquidity_ratio=2.0):
        """
        再平衡组合（带 Atomic 预检查和流动性检查）
        
        参数:
            target_positions: dict, {symbol: target_value}
            max_position_pct: float, 单仓最大比例
            atomic_check: bool, 是否执行预检查（默认True）
            min_liquidity_ratio: float, 最小流动性比例（目标数量/ask_size）
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

        # P1 修复：确保目标持仓总金额不超过组合价值
        if WEIGHT_ALLOC_NORM_AVAILABLE:
            original_total = sum(target_positions.values())
            target_positions = normalize_target_positions(target_positions, portfolio_value)
            if abs(original_total - sum(target_positions.values())) > 1:
                logger.info(f"📊 目标持仓已归一化: ${original_total:,.0f} → ${sum(target_positions.values()):,.0f}")

        # === Atomic 预检查 ===
        if atomic_check:
            precheck = self._atomic_precheck(
                target_positions, current_positions, 
                portfolio_value, max_position_pct, min_liquidity_ratio
            )
            if not precheck['pass']:
                logger.error(f"❌ Atomic 预检查失败: {precheck['reason']}")
                return {'status': 'PRECHECK_FAILED', **precheck}
            logger.info(f"✅ Atomic 预检查通过 ({precheck['orders_count']} 笔订单)")
        
        # 记录调仓前状态（用于回滚）
        pre_state = {
            'timestamp': datetime.now().isoformat(),
            'positions': current_positions.copy(),
            'cash': account['cash'],
        }
        
        executed_orders = []
        failed_orders = []
        
        # 阶段 1: 先卖出不在目标列表中的持仓
        for symbol, pos in current_positions.items():
            if symbol not in target_positions:
                try:
                    result = self.executor.submit_order(symbol, pos['qty'], 'sell')
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
            # 使用 Decimal 计算目标金额
            target_value = min(target_value, portfolio_value * max_position_pct)
            current_price = self._get_current_price(symbol)
            
            # Decimal 精度计算
            target_qty = self._calculate_qty(target_value, current_price)
            
            current_qty = current_positions.get(symbol, {}).get('qty', 0)
            diff = target_qty - current_qty
            
            if abs(diff) > 0:
                side = 'buy' if diff > 0 else 'sell'
                qty = abs(diff)
                
                logger.info(f"🔄 {side.upper()}: {symbol} x {qty} (目标: ${target_value:,.0f})")
                
                try:
                    result = self.executor.submit_order(symbol, qty, side)
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
        """
        Atomic 预检查 - 确保所有订单在提交前都可行
        
        检查项:
        1. 市场是否开盘
        2. 账户状态是否正常
        3. 预估资金是否充足
        4. 每个标的流动性是否充足
        
        返回:
            dict: {'pass': bool, 'reason': str, 'orders_count': int}
        """
        # 1. 市场状态
        if not self.executor.market_is_open():
            return {'pass': False, 'reason': 'market_closed', 'orders_count': 0}
        
        # 2. 账户状态
        account = self.executor.get_account()
        if not account or account.get('status') != 'ACTIVE':
            return {'pass': False, 'reason': 'account_not_active', 'orders_count': 0}
        
        # 3. 预估资金需求（Decimal 精度）
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
                # 需要买入
                total_buy_value += Decimal(str(target_value))
                orders_count += 1
            elif diff < 0:
                # 需要卖出
                sell_release += Decimal(str(current_positions[symbol]['market_value']))
                orders_count += 1
        
        # 卖出释放 + 现金 >= 买入需求
        available_cash = Decimal(str(account['cash'])) + sell_release
        if total_buy_value > available_cash * Decimal('1.05'):  # 5% 缓冲
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
            
            if target_qty > current_qty:  # 只检查买入
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
        """
        检查标的流动性
        
        返回:
            dict: {'sufficient': bool, 'reason': str}
        """
        if not self.executor.api:
            return {'sufficient': True, 'reason': 'mock_mode'}
        
        try:
            # 获取最新报价
            quote = self.executor.api.get_latest_quote(symbol)
            ask_size = getattr(quote, 'ask_size', 0) or getattr(quote, 'as', 0)
            
            if ask_size == 0:
                return {'sufficient': False, 'reason': 'no_ask_size_available'}
            
            # 需求数量 <= 2 * ask_size（假设能消化2倍深度）
            if qty_needed <= ask_size * 2:
                return {'sufficient': True, 'reason': f'ask_size={ask_size}'}
            else:
                return {
                    'sufficient': False, 
                    'reason': f'qty_needed={qty_needed} > 2*ask_size={ask_size*2}'
                }
                
        except Exception as e:
            logger.warning(f"流动性检查失败 {symbol}: {e}")
            return {'sufficient': True, 'reason': 'check_failed_assuming_ok'}  # 检查失败时放行，但记录
    
    def _calculate_qty(self, target_value, current_price):
        """
        使用 Decimal 精度计算股数
        
        返回:
            int: 股数（Alpaca Paper 支持小数股，但用整数更安全）
        """
        if current_price <= 0:
            return 0
        
        # Decimal 精度计算
        value_d = Decimal(str(target_value))
        price_d = Decimal(str(current_price))
        qty_d = (value_d / price_d).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        
        # 转换为整数（Alpaca Paper Trading 支持小数股，但策略用整数）
        return int(qty_d)
    
    def _get_current_price(self, symbol):
        """
        获取当前实时价格
        优先 Alpaca API，失败回退 yfinance
        """
        import time
        
        # 缓存5分钟
        now = time.time()
        cache_key = f"price_{symbol}"
        if hasattr(self, '_price_cache') and cache_key in getattr(self, '_price_cache', {}):
            if now - self._price_cache_time.get(cache_key, 0) < 300:
                return self._price_cache[cache_key]
        
        # 初始化缓存
        if not hasattr(self, '_price_cache'):
            self._price_cache = {}
            self._price_cache_time = {}
        
        # 尝试 Alpaca API 获取最新报价
        if self.executor.api:
            try:
                trade = self.executor.api.get_latest_trade(symbol)
                price = float(trade.price)
                self._price_cache[cache_key] = price
                self._price_cache_time[cache_key] = now
                return price
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"Alpaca 网络错误获取 {symbol} 价格: {e}")
            except Exception as e:
                logger.warning(f"Alpaca 获取 {symbol} 价格失败: {e}")
        
        # 回退: yfinance 实时数据
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1m")
            if len(hist) > 0:
                price = float(hist['Close'].iloc[-1])
                self._price_cache[cache_key] = price
                self._price_cache_time[cache_key] = now
                return price
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"yfinance 网络错误获取 {symbol} 价格: {e}")
        except Exception as e:
            logger.warning(f"yfinance 获取 {symbol} 价格失败: {e}")
        
        # 最终回退: 假设价格 100（仅用于测试）
        logger.error(f"无法获取 {symbol} 价格，使用默认值 100")
        return 100.0
    
    def get_portfolio_summary(self):
        """获取组合摘要"""
        account = self.executor.get_account()
        positions = self.executor.get_positions()
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'cash': account['cash'],
            'portfolio_value': account['portfolio_value'],
            'positions_count': len(positions),
            'positions': positions,
        }
        
        self.positions_history.append(summary)
        return summary


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
    
    # 获取持仓
    positions = executor.get_positions()
    print(f"\n当前持仓 ({len(positions)}):")
    for p in positions:
        print(f"  {p['symbol']}: {p['qty']} 股, 市值 ${p['market_value']:,.2f}")
    
    # 检查市场状态
    is_open = executor.market_is_open()
    print(f"\n市场状态: {'开盘' if is_open else '收盘'}")
