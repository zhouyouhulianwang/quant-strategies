"""
Alpaca Paper Trading 执行模块
支持订单提交、持仓查询、账户状态监控
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

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
            self.api = REST(self.api_key, self.api_secret, self.base_url)
            logger.info(f"✅ Alpaca API 已连接: {self.base_url}")
        else:
            self.api = None
            logger.warning("⚠️ 使用模拟模式（无实际交易）")
    
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
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []
    
    def submit_order(self, symbol, qty, side, order_type='market', time_in_force='day', limit_price=None):
        """
        提交订单
        
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
        
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=order_type,
                time_in_force=time_in_force,
                limit_price=limit_price
            )
            
            logger.info(f"✅ 订单已提交: {side.upper()} {qty} {symbol}")
            return {
                'id': order.id,
                'symbol': order.symbol,
                'qty': int(order.qty),
                'side': order.side,
                'type': order.type,
                'status': order.status,
                'submitted_at': order.submitted_at,
            }
        except Exception as e:
            logger.error(f"提交订单失败: {e}")
            return None
    
    def cancel_all_orders(self):
        """取消所有未成交订单"""
        if not self.api:
            return True
        
        try:
            self.api.cancel_all_orders()
            logger.info("✅ 所有订单已取消")
            return True
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
    """V14 策略专用 Alpaca 执行器"""
    
    def __init__(self, api_key=None, api_secret=None):
        self.executor = AlpacaPaperExecutor(api_key, api_secret)
        self.positions_history = []
    
    def rebalance_portfolio(self, target_positions, max_position_pct=0.20):
        """
        再平衡组合
        
        参数:
            target_positions: dict, {symbol: target_value}
            max_position_pct: float, 单仓最大比例
        """
        account = self.executor.get_account()
        if not account:
            logger.error("无法获取账户信息")
            return
        
        portfolio_value = account['portfolio_value']
        current_positions = {p['symbol']: p for p in self.executor.get_positions()}
        
        logger.info(f"\n{'='*60}")
        logger.info(f"组合再平衡")
        logger.info(f"{'='*60}")
        logger.info(f"组合价值: ${portfolio_value:,.2f}")
        logger.info(f"目标持仓: {len(target_positions)} 只")
        
        # 卖出不在目标列表中的持仓
        for symbol, pos in current_positions.items():
            if symbol not in target_positions:
                logger.info(f"🔄 卖出: {symbol} x {pos['qty']}")
                self.executor.submit_order(symbol, pos['qty'], 'sell')
        
        # 调整目标持仓
        for symbol, target_value in target_positions.items():
            target_value = min(target_value, portfolio_value * max_position_pct)
            target_qty = int(target_value / self._get_current_price(symbol))
            
            current_qty = current_positions.get(symbol, {}).get('qty', 0)
            diff = target_qty - current_qty
            
            if abs(diff) > 0:
                side = 'buy' if diff > 0 else 'sell'
                qty = abs(diff)
                logger.info(f"🔄 {side.upper()}: {symbol} x {qty} (目标: ${target_value:,.0f})")
                self.executor.submit_order(symbol, qty, side)
        
        logger.info(f"✅ 再平衡完成")
    
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
