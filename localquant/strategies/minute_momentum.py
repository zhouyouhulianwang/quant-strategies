"""分钟级动量策略 - 专为短周期数据设计"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

from localquant.strategy import BaseStrategy
from localquant.strategy.indicators import rsi, sma

class MinuteMomentumStrategy(BaseStrategy):
    """分钟级动量策略 - 使用短周期参数"""
    
    def __init__(self, symbols=None, **kwargs):
        super().__init__()
        
        self.symbols = symbols or ['AAPL']
        self.lookback_periods = {'short': 12, 'medium': 48, 'long': 96}  # 5m bars: 1h, 4h, 8h
        self.weights = {'short': 0.5, 'medium': 0.3, 'long': 0.2}
        self.top_n = 3
        self.max_position_pct = 0.33
        
        self.rebalance_hours = 4  # 每4小时再平衡
        self._last_rebalance = None
        self._in_position = set()
    
    def initialize(self):
        print(f"MinuteMomentum initialized: {self.symbols}")
    
    def on_data(self, data):
        super().on_data(data)
        
        timestamp = self.context.current_time
        
        # 再平衡判断（基于小时）
        if self._last_rebalance is not None:
            hours_since = (timestamp - self._last_rebalance).total_seconds() / 3600
            if hours_since < self.rebalance_hours:
                return
        
        # 计算动量得分
        scores = {}
        for symbol in self.symbols:
            if symbol not in self.context.current_data:
                continue
            
            history = self.context.get_history(symbol, 'close', 200)
            if len(history) < 100:
                continue
            
            price = self.context.get_price(symbol, 'close')
            if price is None:
                continue
            
            score = 0
            for name, bars in self.lookback_periods.items():
                if len(history) > bars:
                    past = history.iloc[-bars - 1]
                    ret = (price - past) / past * 100
                    score += ret * self.weights[name]
            
            # RSI 过滤
            rsi_val = rsi(history, 14).iloc[-1]
            if not np.isnan(rsi_val):
                if rsi_val > 70:
                    score *= 0.5
                elif rsi_val < 30:
                    score *= 1.5
            
            scores[symbol] = score
        
        if not scores:
            return
        
        # 排序选择 Top N
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top = [s for s, _ in sorted_scores[:self.top_n]]
        
        # 清仓
        for symbol in list(self._in_position):
            if symbol not in top:
                self.liquidate(symbol)
                self._in_position.discard(symbol)
        
        # 买入
        for symbol in top:
            if symbol not in self._in_position:
                price = self.context.get_price(symbol, 'close')
                if price is None or price == 0 or np.isnan(price):
                    continue
                self.target_percent(symbol, self.max_position_pct)
                self._in_position.add(symbol)
        
        self._last_rebalance = timestamp
