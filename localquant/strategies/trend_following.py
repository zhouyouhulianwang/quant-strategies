"""趋势跟踪策略 - 均线突破+MACD确认"""
import numpy as np
import pandas as pd
from typing import Dict, List
from datetime import datetime

from localquant.strategy import BaseStrategy


class TrendFollowingStrategy(BaseStrategy):
    """
    趋势跟踪策略
    
    核心逻辑:
    1. 价格 > SMA50 = 多头趋势
    2. 价格 < SMA50 = 空头/空仓
    3. MACD 确认：MACD > Signal 才入场
    4. ATR 仓位管理：波动大时减仓
    5.  trailing stop: 2×ATR
    """
    
    def __init__(self, symbols: List[str],
                 fast_ma: int = 20,
                 slow_ma: int = 50,
                 use_macd: bool = True,
                 risk_per_trade: float = 0.02,
                 atr_period: int = 14,
                 trailing_atr_mult: float = 2.0):
        super().__init__()
        self.symbols = symbols
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
        self.use_macd = use_macd
        self.risk_per_trade = risk_per_trade
        self.atr_period = atr_period
        self.trailing_atr_mult = trailing_atr_mult
        
        self.position_high = {}  # 跟踪最高价格用于移动止损
        self.entry_atr = {}      # 入场时的ATR
    
    def _calculate_sma(self, prices: pd.Series, period: int) -> float:
        """计算SMA"""
        if len(prices) < period:
            return prices.mean()
        return prices.iloc[-period:].mean()
    
    def _calculate_macd(self, prices: pd.Series) -> tuple:
        """计算MACD"""
        if len(prices) < 26:
            return 0, 0
        
        ema12 = prices.ewm(span=12).mean().iloc[-1]
        ema26 = prices.ewm(span=26).mean().iloc[-1]
        macd = ema12 - ema26
        
        signal = prices.ewm(span=12).mean().ewm(span=9).mean().iloc[-1] - \
                 prices.ewm(span=26).mean().ewm(span=9).mean().iloc[-1]
        
        return macd, signal
    
    def _calculate_atr(self, df: pd.DataFrame) -> float:
        """计算ATR"""
        if len(df) < 2:
            return 0.0
        
        high = df['high'].iloc[-self.atr_period:]
        low = df['low'].iloc[-self.atr_period:]
        close = df['close'].iloc[-self.atr_period:]
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.mean()
        
        return atr
    
    def on_data(self, data: Dict):
        super().on_data(data)
        
        current_time = data['timestamp']
        bar_data = data['data']
        
        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            
            price_data = bar_data[symbol]
            close = price_data.get('close', price_data.get('adj_close'))
            if close is None:
                continue
            
            # 获取历史数据
            hist = self.context.get_history(symbol, 'close', max(self.slow_ma, 26) + 10)
            if len(hist) < self.slow_ma:
                continue
            
            # 计算指标
            sma_fast = hist.iloc[-self.fast_ma:].mean()
            sma_slow = hist.iloc[-self.slow_ma:].mean()
            
            # 趋势判断
            in_uptrend = close > sma_slow
            
            # MACD确认
            macd_bull = True
            if self.use_macd:
                ema12 = hist.ewm(span=12).mean().iloc[-1]
                ema26 = hist.ewm(span=26).mean().iloc[-1]
                macd = ema12 - ema26
                
                # Signal line (EMA9 of MACD)
                macd_series = hist.ewm(span=12).mean() - hist.ewm(span=26).mean()
                signal = macd_series.ewm(span=9).mean().iloc[-1]
                
                macd_bull = macd > signal
            
            # 当前持仓
            portfolio = self._engine.portfolio
            position = portfolio.positions.get(symbol)
            current_qty = position.quantity if position else 0
            
            # 入场信号：上升趋势 + MACD确认
            if in_uptrend and macd_bull:
                if current_qty <= 0:
                    # 计算仓位（基于ATR）
                    atr = self._calculate_atr(
                        pd.DataFrame(self._history_buffer.get(symbol, []))
                    ) if hasattr(self, '_history_buffer') else close * 0.02
                    
                    if atr > 0:
                        # 简化仓位计算
                        target_value = portfolio.cash * 0.1
                        qty = int(target_value / close)
                        qty = max(qty, 1)
                    else:
                        qty = int(portfolio.cash * 0.1 / close)
                    
                    print(f"[{current_time.date()}] 买入 {symbol} @ ${close:.2f} (趋势+MACD)")
                    self.buy(symbol, qty)
                    
                    self.position_high[symbol] = close
                    self.entry_atr[symbol] = atr if atr > 0 else close * 0.02
            
            # 出场信号：趋势反转
            elif not in_uptrend:
                if current_qty > 0:
                    print(f"[{current_time.date()}] 卖出 {symbol} @ ${close:.2f} (趋势反转)")
                    self.sell(symbol, current_qty)
                    if symbol in self.position_high:
                        del self.position_high[symbol]
                    if symbol in self.entry_atr:
                        del self.entry_atr[symbol]
            
            # 移动止损（只在有持仓时检查）
            if current_qty > 0 and symbol in self.position_high:
                if close > self.position_high[symbol]:
                    self.position_high[symbol] = close
                
                atr = self.entry_atr.get(symbol, close * 0.02)
                stop_price = self.position_high[symbol] - self.trailing_atr_mult * atr
                
                if close < stop_price:
                    print(f"[{current_time.date()}] 移动止损 {symbol} @ ${close:.2f}")
                    self.sell(symbol, current_qty)
                    if symbol in self.position_high:
                        del self.position_high[symbol]
                    if symbol in self.entry_atr:
                        del self.entry_atr[symbol]
