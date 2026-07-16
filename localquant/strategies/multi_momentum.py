"""多周期动量策略 - 基于 MomentumProjects 的 LocalQuant 适配版"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

import pandas as pd
import numpy as np
from localquant.strategy import BaseStrategy
from localquant.strategy.indicators import rsi, sma, atr

class MultiMomentumStrategy(BaseStrategy):
    """
    多周期动量策略
    
    原理：
    - 计算多周期（20d, 60d, 120d）收益率，加权得分
    - RSI 过滤（超买减分，超卖加分）
    - 趋势过滤（价格 > 200SMA 才能买入）
    - 选择动量得分最高的 N 只标的持有
    """
    
    def __init__(self,
                 symbols=None,
                 momentum_periods=None,
                 momentum_weights=None,
                 top_n=5,
                 rsi_period=14,
                 trend_ma_period=200,
                 use_trend_filter=True):
        super().__init__()
        
        self.symbols = symbols or ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 
                                    'TSLA', 'META', 'NFLX', 'AMD', 'INTC']
        self.momentum_periods = momentum_periods or {'short': 20, 'medium': 60, 'long': 120}
        self.momentum_weights = momentum_weights or {'short': 0.5, 'medium': 0.3, 'long': 0.2}
        self.top_n = top_n
        self.rsi_period = rsi_period
        self.trend_ma_period = trend_ma_period
        self.use_trend_filter = use_trend_filter
        
        self.scores = {}
        self.rebalance_freq = 20  # 每20天再平衡
        self._last_rebalance = None
        self._in_position = set()
    
    def initialize(self):
        """初始化策略"""
        self.name = "MultiMomentum"
        print(f"Strategy initialized: {self.name}")
        print(f"  Symbols: {self.symbols}")
        print(f"  Top N: {self.top_n}")
        print(f"  Rebalance every {self.rebalance_freq} days")
    
    def on_data(self, data):
        """处理每个数据 bar"""
        super().on_data(data)
        
        timestamp = self.context.current_time
        
        # 检查是否到再平衡时间
        if self._last_rebalance is not None:
            days_since = (timestamp - self._last_rebalance).days
            if days_since < self.rebalance_freq:
                return
        
        # 计算所有标得分
        self.scores = {}
        for symbol in self.symbols:
            if symbol not in self.context.current_data:
                continue
            
            score = self._calculate_score(symbol)
            if score is not None:
                self.scores[symbol] = score
        
        if not self.scores:
            return
        
        # 排序并选择 Top N
        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        top_symbols = {s for s, _ in sorted_scores[:self.top_n]}
        
        print(f"\n[{timestamp.date()}] Rebalancing...")
        print(f"  Top picks: {[(s, round(sc,2)) for s, sc in sorted_scores[:self.top_n]]}")
        
        # 清仓不在 Top N 的
        for symbol in list(self._in_position):
            if symbol not in top_symbols:
                self.liquidate(symbol)
                self._in_position.discard(symbol)
                print(f"  SELL {symbol} (not in top {self.top_n})")
        
        # 买入 Top N 中未持有的
        for symbol in top_symbols:
            if symbol not in self._in_position:
                # 等权重分配
                target_pct = 1.0 / self.top_n
                self.target_percent(symbol, target_pct)
                self._in_position.add(symbol)
                print(f"  BUY {symbol} (score: {self.scores.get(symbol, 0):.2f})")
        
        self._last_rebalance = timestamp
    
    def _calculate_score(self, symbol) -> float:
        """计算单个标的的动量得分"""
        max_period = max(self.momentum_periods.values()) + 5
        history = self.context.get_history(symbol, 'close', max_period)
        
        if len(history) < max(self.momentum_periods.values()):
            return None
        
        closes = history.values
        current_price = closes[-1]
        
        # 多周期动量得分
        momentum_scores = {}
        for period_name, period_days in self.momentum_periods.items():
            if len(closes) > period_days:
                past_price = closes[-period_days - 1]
                ret = (current_price / past_price - 1) * 100
                weight = self.momentum_weights[period_name]
                momentum_scores[period_name] = ret * weight
        
        if not momentum_scores:
            return None
        
        base_score = sum(momentum_scores.values())
        
        # RSI 过滤
        rsi_score = 0
        rsi_val = rsi(history, self.rsi_period).iloc[-1]
        if not np.isnan(rsi_val):
            if rsi_val > 70:
                rsi_score = -5
            elif rsi_val < 30:
                rsi_score = +5
        
        # 趋势过滤
        trend_score = 0
        if self.use_trend_filter:
            ma = sma(history, self.trend_ma_period).iloc[-1]
            if not np.isnan(ma):
                if current_price > ma:
                    trend_score = +3
                else:
                    trend_score = -5
        
        final_score = base_score + rsi_score + trend_score
        return round(final_score, 3)
