"""牛市增强策略 - 在牛市中跑赢SPY"""
import numpy as np
import pandas as pd
from typing import Dict, List
from datetime import datetime

from localquant.strategy import BaseStrategy


class BullMomentumStrategy(BaseStrategy):
    """
    牛市增强策略
    
    核心逻辑:
    1. 只在 SPY > SMA20 时入场 (牛市确认)
    2. 筛选过去 20-60 天涨幅最高的科技股
    3. 集中持仓 top_n 只，每只 10-15%
    4. 10% 收益自动止盈，-8% 止损
    5. 每周再平衡
    """
    
    def __init__(self, symbols: List[str],
                 top_n: int = 10,
                 momentum_lookback: int = 20,
                 spy_filter: bool = True,
                 profit_target: float = 0.10,
                 stop_loss_pct: float = 0.08,
                 max_position_pct: float = 0.15,
                 rebalance_freq: int = 5):
        super().__init__()
        self.symbols = [s for s in symbols if s != 'SPY']
        self.top_n = top_n
        self.momentum_lookback = momentum_lookback
        self.spy_filter = spy_filter
        self.profit_target = profit_target
        self.stop_loss_pct = stop_loss_pct
        self.max_position_pct = max_position_pct
        self.rebalance_freq = rebalance_freq
        
        self.last_rebalance = None
        self.entry_prices = {}  # 记录买入价用于止盈
    
    def initialize(self):
        super().initialize()
        self.last_rebalance = self.context.current_time
    
    def on_data(self, data: Dict):
        super().on_data(data)
        
        current_time = data['timestamp']
        bar_data = data['data']
        
        # 检查是否需要再平衡
        should_rebalance = False
        if self.last_rebalance is None:
            should_rebalance = True
            self.last_rebalance = current_time
        else:
            days_since = (current_time - self.last_rebalance).days
            if days_since >= self.rebalance_freq:
                should_rebalance = True
        
        # SPY 动量过滤
        if self.spy_filter:
            spy_data = bar_data.get('SPY', {})
            if spy_data:
                spy_close = spy_data.get('close', spy_data.get('adj_close'))
                if spy_close:
                    # 简化：检查 SPY 是否在 20 日均线之上
                    spy_hist = self.context.get_history('SPY', 'close', self.momentum_lookback)
                    if len(spy_hist) >= self.momentum_lookback:
                        spy_sma20 = spy_hist.mean()
                        if spy_close < spy_sma20:
                            # 熊市信号：清仓
                            self._liquidate_all()
                            self.last_rebalance = current_time
                            return
        
        # 止盈检查
        self._check_profit_targets(bar_data, current_time)
        
        # 止损检查
        self._check_stop_losses(bar_data, current_time)
        
        if not should_rebalance:
            return
        
        # 计算动量得分
        momentum_scores = {}
        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            
            price_data = bar_data[symbol]
            close = price_data.get('close', price_data.get('adj_close'))
            if close is None:
                continue
            
            # 计算动量
            hist = self.context.get_history(symbol, 'close', self.momentum_lookback)
            if len(hist) >= self.momentum_lookback:
                momentum = close / hist.iloc[0] - 1
                momentum_scores[symbol] = momentum
        
        if not momentum_scores:
            return
        
        # 选择 top_n
        top_symbols = sorted(momentum_scores.items(), 
                            key=lambda x: x[1], 
                            reverse=True)[:self.top_n]
        
        print(f"\n[{current_time.date()}] BullMomentum 再平衡:")
        print(f"  Top {self.top_n}: {[(s, f'{m:.1%}') for s, m in top_symbols]}")
        
        # 清仓不在 top_n 的
        portfolio = self._engine.portfolio
        for symbol in list(portfolio.positions.keys()):
            if symbol not in [s for s, _ in top_symbols]:
                position = portfolio.positions[symbol]
                if position.quantity > 0:
                    self.sell(symbol, position.quantity)
                    if symbol in self.entry_prices:
                        del self.entry_prices[symbol]
        
        # 买入 top_n（等权重）
        target_pct = self.max_position_pct
        for symbol, momentum in top_symbols:
            self.target_percent(symbol, target_pct)
            # 记录买入价
            price = bar_data.get(symbol, {}).get('close')
            if price and symbol not in self.entry_prices:
                self.entry_prices[symbol] = price
        
        self.last_rebalance = current_time
    
    def _check_profit_targets(self, bar_data, current_time):
        """检查止盈"""
        portfolio = self._engine.portfolio
        for symbol, position in list(portfolio.positions.items()):
            if position.quantity <= 0 or symbol not in self.entry_prices:
                continue
            if symbol not in bar_data:
                continue
            
            current_price = bar_data[symbol].get('close')
            if current_price is None:
                continue
            
            entry_price = self.entry_prices[symbol]
            gain = current_price / entry_price - 1
            
            if gain >= self.profit_target:
                print(f"  止盈 {symbol}: +{gain:.1%}")
                self.sell(symbol, position.quantity)
                del self.entry_prices[symbol]
    
    def _check_stop_losses(self, bar_data, current_time):
        """检查止损"""
        portfolio = self._engine.portfolio
        for symbol, position in list(portfolio.positions.items()):
            if position.quantity <= 0 or symbol not in self.entry_prices:
                continue
            if symbol not in bar_data:
                continue
            
            current_price = bar_data[symbol].get('close')
            if current_price is None:
                continue
            
            entry_price = self.entry_prices[symbol]
            loss = entry_price / current_price - 1
            
            if loss >= self.stop_loss_pct:
                print(f"  止损 {symbol}: -{loss:.1%}")
                self.sell(symbol, position.quantity)
                del self.entry_prices[symbol]
    
    def _liquidate_all(self):
        """清仓"""
        portfolio = self._engine.portfolio
        for symbol, position in portfolio.positions.items():
            if position.quantity > 0:
                self.sell(symbol, position.quantity)
        self.entry_prices.clear()
