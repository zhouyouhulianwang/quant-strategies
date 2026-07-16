"""模拟经纪商 - 处理订单、滑点、手续费"""
import random
from typing import Optional, Tuple
from .events import OrderEvent, FillEvent
from .portfolio import Portfolio

class SimulatedBroker:
    """模拟经纪商 - 处理订单执行"""
    
    def __init__(self, 
                 commission_rate: float = 0.001,  # 0.1% 手续费
                 min_commission: float = 1.0,        # 最低手续费
                 slippage_model: str = 'fixed',    # 滑点模型
                 slippage_amount: float = 0.001):  # 0.1% 滑点
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.slippage_model = slippage_model
        self.slippage_amount = slippage_amount
    
    def calculate_commission(self, quantity: int, price: float) -> float:
        """计算手续费"""
        commission = abs(quantity) * price * self.commission_rate
        return max(commission, self.min_commission)
    
    def apply_slippage(self, price: float, direction: int) -> float:
        """应用滑点"""
        if self.slippage_model == 'fixed':
            slip = price * self.slippage_amount
            return price + slip * direction
        elif self.slippage_model == 'random':
            slip = price * self.slippage_amount * random.uniform(0.5, 1.5)
            return price + slip * direction
        return price
    
    def execute_order(self, order: OrderEvent, market_price: float) -> Optional[FillEvent]:
        """执行订单，返回成交事件"""
        direction = 1 if order.quantity > 0 else -1
        
        # 应用滑点
        fill_price = self.apply_slippage(market_price, direction)
        
        # 计算手续费
        commission = self.calculate_commission(order.quantity, fill_price)
        
        return FillEvent(
            event_type=__import__('localquant.core.events', fromlist=['EventType']).EventType.FILL,
            timestamp=order.timestamp,
            symbol=order.symbol,
            fill_price=fill_price,
            fill_quantity=order.quantity,
            commission=commission,
            data={'order_type': order.order_type}
        )
