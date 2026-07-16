"""策略框架 - 基类与上下文"""
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

class StrategyContext:
    """策略上下文 - 提供给策略的运行时环境"""
    
    def __init__(self, engine=None):
        self.engine = engine
        self.current_time: Optional[datetime] = None
        self.current_data: Dict = {}
        self.historical_data: Dict[str, pd.DataFrame] = {}
        self.symbols: List[str] = []
    
    def get_price(self, symbol: str, field: str = 'close') -> Optional[float]:
        """获取当前价格"""
        if symbol in self.current_data:
            return self.current_data[symbol].get(field)
        return None
    
    def get_history(self, symbol: str, field: str = 'close', 
                    lookback: int = 20) -> pd.Series:
        """获取历史数据"""
        if symbol in self.historical_data:
            df = self.historical_data[symbol]
            if field in df.columns:
                return df[field].iloc[-lookback:]
        return pd.Series()

class BaseStrategy:
    """策略基类 - 继承此类实现自定义策略"""
    
    def __init__(self):
        self.context = StrategyContext()
        self.name = self.__class__.__name__
        self.symbols: List[str] = []
        self.indicators: Dict = {}
        self._engine = None
        self._history_buffer: Dict[str, List] = {}  # 历史数据缓存
    
    def set_engine(self, engine):
        """设置引擎引用"""
        self._engine = engine
        self.context.engine = engine
    
    def initialize(self):
        """初始化策略 - 设置参数、订阅数据"""
        pass
    
    def on_data(self, data: Dict):
        """
        每个数据 bar 触发
        data: {'timestamp': datetime, 'data': {symbol: {open, high, low, close, volume}}}
        """
        self.context.current_time = data['timestamp']
        self.context.current_data = data['data']
        
        # 更新历史数据缓存
        for symbol, bar in data['data'].items():
            if symbol not in self._history_buffer:
                self._history_buffer[symbol] = []
            self._history_buffer[symbol].append(bar)
            # 保留最近 500 条
            self._history_buffer[symbol] = self._history_buffer[symbol][-500:]
        
        # 构建 DataFrame 历史数据
        self.context.historical_data = {
            symbol: pd.DataFrame(self._history_buffer[symbol])
            for symbol in self._history_buffer
        }
    
    def buy(self, symbol: str, quantity: int):
        """买入"""
        if self._engine:
            self._engine.place_order(symbol, quantity)
    
    def sell(self, symbol: str, quantity: int):
        """卖出"""
        if self._engine:
            self._engine.place_order(symbol, -quantity)
    
    def target_percent(self, symbol: str, target_pct: float):
        """设置目标仓位百分比"""
        if not self._engine:
            return
        
        price = self.context.get_price(symbol, 'close')
        if price is None or price == 0:
            return
        
        # 需要当前价格来计算 total_value
        current_prices = {symbol: price}
        for s in self._engine.portfolio.positions:
            if s in self.context.current_data:
                current_prices[s] = self.context.current_data[s].get('close', 0)
        
        total_value = self._engine.portfolio.total_value(current_prices)
        target_value = total_value * target_pct
        target_qty = int(target_value / price)
        
        current_qty = 0
        if symbol in self._engine.portfolio.positions:
            current_qty = self._engine.portfolio.positions[symbol].quantity
        
        order_qty = target_qty - current_qty
        if order_qty != 0:
            self._engine.place_order(symbol, order_qty)
    
    def liquidate(self, symbol: str):
        """清仓"""
        if symbol in self._engine.portfolio.positions:
            qty = self._engine.portfolio.positions[symbol].quantity
            if qty > 0:
                self.sell(symbol, qty)
