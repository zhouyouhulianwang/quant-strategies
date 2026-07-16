"""实盘交易接口基类 - 所有实盘接口的抽象基类"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, List, Callable
from enum import Enum

class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"

@dataclass
class Order:
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    stop_price: Optional[float] = None
    order_id: Optional[str] = None
    timestamp: Optional[datetime] = None

@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float

@dataclass
class Account:
    cash: float
    equity: float
    buying_power: float
    positions: Dict[str, Position]

class LiveBroker(ABC):
    """实盘经纪商抽象基类"""
    
    def __init__(self, name: str):
        self.name = name
        self.is_connected = False
        self.order_callbacks: List[Callable] = []
    
    @abstractmethod
    def connect(self, **kwargs) -> bool:
        """连接交易服务器"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        pass
    
    @abstractmethod
    def place_order(self, order: Order) -> Optional[str]:
        """下单，返回订单ID"""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """获取订单状态"""
        pass
    
    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        """获取当前持仓"""
        pass
    
    @abstractmethod
    def get_account(self) -> Optional[Account]:
        """获取账户信息"""
        pass
    
    @abstractmethod
    def get_market_price(self, symbol: str) -> Optional[float]:
        """获取实时市场价格"""
        pass
    
    def subscribe_order_updates(self, callback: Callable) -> None:
        """订阅订单状态更新"""
        self.order_callbacks.append(callback)
    
    def _notify_order_update(self, order_id: str, status: str, data: Dict) -> None:
        """通知订单更新"""
        for callback in self.order_callbacks:
            try:
                callback(order_id, status, data)
            except Exception as e:
                print(f"Order callback error: {e}")
