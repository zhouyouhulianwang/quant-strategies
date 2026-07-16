"""Dual Thrust 日内突破策略 - 经典期货策略模板

策略逻辑:
1. 计算前N日的 HH-LC 和 HC-LL
2. 上轨 = 开盘价 + m * max(HH-LC, HC-LL)
3. 下轨 = 开盘价 - m * max(HH-LC, HC-LL)
4. 价格突破上轨 → 做多
5. 价格跌破下轨 → 做空/平仓

适用场景: 股指期货、商品期货日内交易
时间框架: 1分钟/5分钟/15分钟
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, time

from localquant.strategy import BaseStrategy


class DualThrustStrategy(BaseStrategy):
    """
    Dual Thrust 日内突破策略
    
    参数:
    - n: 回看周期(默认5)
    - m: 系数(默认0.5)
    - stop_loss_pct: 止损比例
    
    使用示例:
    ```python
    strategy = DualThrustStrategy(
        symbols=['ES=F'],  # 标普500期货
        n=5,
        m=0.5,
        stop_loss_pct=0.01
    )
    ```
    """
    
    def __init__(self, symbols: List[str],
                 n: int = 5,
                 m: float = 0.5,
                 stop_loss_pct: float = 0.01,
                 use_end_of_day_close: bool = True):
        super().__init__()
        self.symbols = symbols
        self.n = n
        self.m = m
        self.stop_loss_pct = stop_loss_pct
        self.use_end_of_day_close = use_end_of_day_close
        
        # 日内状态
        self.daily_high = {}
        self.daily_low = {}
        self.daily_open = {}
        self.entry_prices = {}
        self.today = None
        
        # 历史数据
        self.history = {s: [] for s in symbols}
    
    def _calculate_range(self, symbol: str) -> float:
        """计算前N日的价格区间"""
        if len(self.history[symbol]) < self.n:
            return 0.0
        
        # 取最近N天的日数据
        recent_data = self.history[symbol][-self.n:]
        
        HH = max(d['high'] for d in recent_data)  # 最高价
        LC = min(d['close'] for d in recent_data)  # 最低收盘价
        HC = max(d['close'] for d in recent_data)  # 最高收盘价
        LL = min(d['low'] for d in recent_data)    # 最低价
        
        return max(HH - LC, HC - LL)
    
    def on_data(self, data: Dict):
        super().on_data(data)
        
        current_time = data['timestamp']
        bar_data = data['data']
        
        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            
            price_data = bar_data[symbol]
            close = price_data.get('close')
            high = price_data.get('high', close)
            low = price_data.get('low', close)
            
            if close is None:
                continue
            
            # 日期切换检测
            if self.today != current_time.date():
                # 保存昨日数据
                if self.today and symbol in self.daily_high:
                    self.history[symbol].append({
                        'date': self.today,
                        'high': self.daily_high.get(symbol, close),
                        'low': self.daily_low.get(symbol, close),
                        'open': self.daily_open.get(symbol, close),
                        'close': close
                    })
                    # 保留最近20天
                    self.history[symbol] = self.history[symbol][-20:]
                
                self.today = current_time.date()
                self.daily_high[symbol] = high
                self.daily_low[symbol] = low
                self.daily_open[symbol] = close
            else:
                # 更新日内高低点
                self.daily_high[symbol] = max(self.daily_high.get(symbol, high), high)
                self.daily_low[symbol] = min(self.daily_low.get(symbol, low), low)
            
            # 计算上下轨
            if len(self.history[symbol]) < self.n:
                continue
            
            range_value = self._calculate_range(symbol)
            open_price = self.daily_open.get(symbol, close)
            
            upper_band = open_price + self.m * range_value
            lower_band = open_price - self.m * range_value
            
            # 交易逻辑
            portfolio = self._engine.portfolio
            position = portfolio.positions.get(symbol)
            current_qty = position.quantity if position else 0
            
            # 突破上轨 → 做多
            if close > upper_band and current_qty <= 0:
                # 清仓反手做多
                if current_qty < 0:
                    self.buy(symbol, abs(current_qty))
                
                target_qty = int(portfolio.cash * 0.2 / close)
                if target_qty > 0:
                    self.buy(symbol, target_qty)
                    self.entry_prices[symbol] = close
                    print(f"[{current_time}] DualThrust 做多 {symbol} @ ${close:.2f} (上轨: ${upper_band:.2f})")
            
            # 跌破下轨 → 做空/平仓
            elif close < lower_band and current_qty > 0:
                # 平多仓
                self.sell(symbol, current_qty)
                if symbol in self.entry_prices:
                    del self.entry_prices[symbol]
                print(f"[{current_time}] DualThrust 平仓 {symbol} @ ${close:.2f} (下轨: ${lower_band:.2f})")
            
            # 止损
            if current_qty > 0 and symbol in self.entry_prices:
                entry = self.entry_prices[symbol]
                if entry > 0 and (entry - close) / entry >= self.stop_loss_pct:
                    self.sell(symbol, current_qty)
                    del self.entry_prices[symbol]
                    print(f"[{current_time}] DualThrust 止损 {symbol} @ ${close:.2f}")
    
    def get_parameters(self) -> Dict:
        """返回可调参数"""
        return {
            'n': {'value': self.n, 'min': 1, 'max': 20, 'type': 'int'},
            'm': {'value': self.m, 'min': 0.1, 'max': 2.0, 'type': 'float'},
            'stop_loss_pct': {'value': self.stop_loss_pct, 'min': 0.005, 'max': 0.05, 'type': 'float'}
        }
    
    def get_description(self) -> str:
        return "Dual Thrust 日内突破策略 - 经典期货策略，适合日内交易"
