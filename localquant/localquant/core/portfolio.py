"""投资组合管理 - 持仓、现金流、市值计算"""
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Position:
    """单个标的持仓"""
    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    
    def market_value(self, price: float) -> float:
        return self.quantity * price
    
    def unrealized_pnl(self, price: float) -> float:
        return self.quantity * (price - self.avg_cost)
    
    def add(self, quantity: int, price: float):
        """增加持仓（买入）"""
        total_cost = self.quantity * self.avg_cost + quantity * price
        self.quantity += quantity
        if self.quantity > 0:
            self.avg_cost = total_cost / self.quantity
    
    def reduce(self, quantity: int, price: float) -> float:
        """减少持仓（卖出），返回已实现盈亏"""
        realized_pnl = quantity * (price - self.avg_cost)
        self.quantity -= quantity
        if self.quantity == 0:
            self.avg_cost = 0.0
        return realized_pnl

class Portfolio:
    """投资组合管理器"""
    
    def __init__(self, initial_cash: float = 100000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict[str, Position] = {}
        self.history: List[Dict] = []
        self.current_date: Optional[datetime] = None
    
    def total_value(self, prices: Optional[Dict[str, float]] = None) -> float:
        """总资产价值"""
        position_value = 0.0
        if prices:
            for symbol, position in self.positions.items():
                price = prices.get(symbol, 0)
                position_value += position.market_value(price)
        return self.cash + position_value
    
    def update_market(self, date: datetime, prices: Dict[str, float]):
        """更新市场行情"""
        self.current_date = date
        total = self.total_value(prices)
        self.history.append({
            'date': date,
            'cash': self.cash,
            'positions': {
                s: {
                    'quantity': p.quantity,
                    'value': p.market_value(prices.get(s, 0))
                }
                for s, p in self.positions.items()
            },
            'total_value': total
        })
    
    def execute_order(self, symbol: str, quantity: int, price: float, 
                     commission: float = 0.0) -> Optional[float]:
        """执行订单，返回已实现盈亏（卖出时）"""
        cost = quantity * price + commission
        
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol)
        
        position = self.positions[symbol]
        
        if quantity > 0:  # 买入
            if cost > self.cash:
                return None  # 资金不足
            self.cash -= cost
            position.add(quantity, price)
            return 0.0
        elif quantity < 0:  # 卖出
            sell_qty = abs(quantity)
            if sell_qty > position.quantity:
                return None  # 持仓不足
            self.cash += sell_qty * price - commission
            pnl = position.reduce(sell_qty, price)
            if position.quantity == 0:
                del self.positions[symbol]
            return pnl
        
        return 0.0
    
    def get_returns(self) -> pd.Series:
        """获取每日收益率序列"""
        if not self.history:
            return pd.Series()
        df = pd.DataFrame(self.history)
        df.set_index('date', inplace=True)
        return df['total_value'].pct_change().fillna(0)
    
    def get_equity_curve(self) -> pd.Series:
        """获取权益曲线"""
        if not self.history:
            return pd.Series()
        df = pd.DataFrame(self.history)
        df.set_index('date', inplace=True)
        return df['total_value']
