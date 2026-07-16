"""Binance 实盘交易接口 - 基于 CCXT"""
import logging
from datetime import datetime
from typing import Optional, Dict, List

from .base import LiveBroker, Order, OrderSide, OrderType, Position, Account

logger = logging.getLogger(__name__)

class BinanceBroker(LiveBroker):
    """币安实盘交易接口"""
    
    def __init__(self, api_key: str = None, secret: str = None, sandbox: bool = True):
        super().__init__("Binance")
        self.api_key = api_key
        self.secret = secret
        self.sandbox = sandbox
        self._exchange = None
    
    def connect(self, **kwargs) -> bool:
        """连接币安"""
        try:
            import ccxt
            
            config = {
                'apiKey': self.api_key,
                'secret': self.secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot'
                }
            }
            
            if self.sandbox:
                config['sandbox'] = True
                logger.info("Using Binance sandbox mode")
            
            self._exchange = ccxt.binance(config)
            
            # 测试连接
            self._exchange.load_markets()
            self.is_connected = True
            logger.info("Connected to Binance successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Binance: {e}")
            return False
    
    def disconnect(self) -> None:
        """断开连接"""
        self.is_connected = False
        self._exchange = None
        logger.info("Disconnected from Binance")
    
    def place_order(self, order: Order) -> Optional[str]:
        """下单"""
        if not self.is_connected or not self._exchange:
            logger.error("Not connected to Binance")
            return None
        
        try:
            side = 'buy' if order.side == OrderSide.BUY else 'sell'
            
            # 转换订单类型
            order_type_map = {
                OrderType.MARKET: 'market',
                OrderType.LIMIT: 'limit',
                OrderType.STOP: 'stop_loss',
                OrderType.STOP_LIMIT: 'stop_loss_limit'
            }
            
            order_type = order_type_map.get(order.order_type, 'market')
            
            params = {
                'symbol': order.symbol,
                'type': order_type,
                'side': side,
                'amount': order.quantity,
            }
            
            if order.order_type in [OrderType.LIMIT, OrderType.STOP_LIMIT] and order.price:
                params['price'] = order.price
            
            if order.order_type in [OrderType.STOP, OrderType.STOP_LIMIT] and order.stop_price:
                params['stopPrice'] = order.stop_price
            
            result = self._exchange.create_order(**params)
            order_id = result.get('id')
            
            logger.info(f"Order placed: {order_id} | {side} {order.quantity} {order.symbol} @ {order_type}")
            return order_id
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        if not self.is_connected:
            return False
        
        try:
            self._exchange.cancel_order(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """获取订单状态"""
        if not self.is_connected:
            return None
        
        try:
            order = self._exchange.fetch_order(order_id)
            return {
                'id': order.get('id'),
                'status': order.get('status'),
                'symbol': order.get('symbol'),
                'side': order.get('side'),
                'amount': order.get('amount'),
                'filled': order.get('filled'),
                'remaining': order.get('remaining'),
                'price': order.get('price'),
                'cost': order.get('cost')
            }
        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            return None
    
    def get_positions(self) -> Dict[str, Position]:
        """获取持仓"""
        if not self.is_connected:
            return {}
        
        try:
            balance = self._exchange.fetch_balance()
            positions = {}
            
            for asset, data in balance.get('total', {}).items():
                if data > 0 and asset != 'USDT':
                    # 获取当前价格
                    ticker = self._exchange.fetch_ticker(f"{asset}/USDT")
                    price = ticker.get('last', 0)
                    
                    positions[asset] = Position(
                        symbol=asset,
                        quantity=data,
                        avg_cost=0,  # 币安不直接提供平均成本
                        market_value=data * price,
                        unrealized_pnl=0
                    )
            
            return positions
            
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return {}
    
    def get_account(self) -> Optional[Account]:
        """获取账户信息"""
        if not self.is_connected:
            return None
        
        try:
            balance = self._exchange.fetch_balance()
            total = balance.get('total', {}).get('USDT', 0)
            free = balance.get('free', {}).get('USDT', 0)
            
            positions = self.get_positions()
            position_value = sum(p.market_value for p in positions.values())
            
            return Account(
                cash=free,
                equity=total,
                buying_power=free,
                positions=positions
            )
            
        except Exception as e:
            logger.error(f"Failed to get account: {e}")
            return None
    
    def get_market_price(self, symbol: str) -> Optional[float]:
        """获取市场价格"""
        if not self.is_connected:
            return None
        
        try:
            ticker = self._exchange.fetch_ticker(symbol)
            return ticker.get('last')
        except Exception as e:
            logger.error(f"Failed to get market price: {e}")
            return None
