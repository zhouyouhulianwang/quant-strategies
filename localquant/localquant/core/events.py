"""事件驱动系统 - 回测引擎的基础"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Dict, Optional

class EventType(Enum):
    MARKET_DATA = auto()
    SIGNAL = auto()
    ORDER = auto()
    FILL = auto()
    REBALANCE = auto()

@dataclass
class Event:
    event_type: EventType
    timestamp: datetime
    symbol: Optional[str] = None
    data: Dict = field(default_factory=dict)

@dataclass  
class MarketDataEvent(Event):
    """市场行情数据事件"""
    timestamp: datetime = field(default_factory=datetime.now)
    symbol: Optional[str] = None
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    data: Dict = field(default_factory=dict)
    event_type: EventType = EventType.MARKET_DATA

@dataclass
class SignalEvent(Event):
    """交易信号事件"""
    timestamp: datetime = field(default_factory=datetime.now)
    symbol: Optional[str] = None
    signal_type: str = ""  # 'BUY', 'SELL', 'HOLD'
    strength: float = 1.0
    data: Dict = field(default_factory=dict)
    event_type: EventType = EventType.SIGNAL

@dataclass
class OrderEvent(Event):
    """订单事件"""
    timestamp: datetime = field(default_factory=datetime.now)
    symbol: Optional[str] = None
    order_type: str = "MARKET"  # MARKET, LIMIT
    quantity: int = 0
    price: float = 0.0
    data: Dict = field(default_factory=dict)
    event_type: EventType = EventType.ORDER

@dataclass
class FillEvent(Event):
    """成交事件"""
    timestamp: datetime = field(default_factory=datetime.now)
    symbol: Optional[str] = None
    fill_price: float = 0.0
    fill_quantity: int = 0
    commission: float = 0.0
    data: Dict = field(default_factory=dict)
    event_type: EventType = EventType.FILL
