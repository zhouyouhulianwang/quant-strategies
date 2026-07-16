"""配对交易策略 - 统计套利经典模板

策略逻辑:
1. 找到两只高度相关的股票（相关系数>0.9）
2. 计算价差（Spread = Price_A - hedge_ratio * Price_B）
3. 价差 > 均值 + 2σ → 做空A，做多B
4. 价差 < 均值 - 2σ → 做多A，做空B
5. 价差回归均值 → 平仓

适用场景: 同行业股票对、ETF与其成分股
时间框架: 日线/小时线
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime
try:
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    import warnings
    warnings.warn("scipy未安装，配对交易策略将使用简化计算")

from localquant.strategy import BaseStrategy


class PairTradingStrategy(BaseStrategy):
    """
    配对交易策略 (统计套利)
    
    参数:
    - pair_symbols: 股票对，如 ['PEP', 'KO']
    - lookback: 回看周期计算均值和标准差
    - entry_z: Z值阈值(默认2.0)
    - exit_z: 平仓Z值(默认0.5)
    - hedge_ratio: 对冲比例(可选，自动计算)
    
    使用示例:
    ```python
    strategy = PairTradingStrategy(
        pair_symbols=['PEP', 'KO'],
        lookback=60,
        entry_z=2.0,
        exit_z=0.5
    )
    ```
    """
    
    def __init__(self, pair_symbols: List[str],
                 lookback: int = 60,
                 entry_z: float = 2.0,
                 exit_z: float = 0.5,
                 hedge_ratio: Optional[float] = None,
                 max_position_pct: float = 0.2):
        super().__init__()
        self.pair_symbols = pair_symbols
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.hedge_ratio = hedge_ratio
        self.max_position_pct = max_position_pct
        
        # 状态
        self.price_history = {s: [] for s in pair_symbols}
        self.spread_mean = None
        self.spread_std = None
        self.current_hedge_ratio = hedge_ratio
        
        # 持仓状态
        self.position_state = 0  # 0:无, 1:多A空B, -1:空A多B
        self.entry_spread = None
    
    def _calculate_spread(self, price_a: float, price_b: float) -> float:
        """计算价差"""
        if self.current_hedge_ratio is None:
            # 如果没有预设对冲比例，使用1:1
            return price_a - price_b
        return price_a - self.current_hedge_ratio * price_b
    
    def _update_stats(self, symbol_a: str, symbol_b: str):
        """更新价差统计量"""
        if len(self.price_history[symbol_a]) < self.lookback:
            return False
        
        prices_a = pd.Series(self.price_history[symbol_a][-self.lookback:])
        prices_b = pd.Series(self.price_history[symbol_b][-self.lookback:])
        
        # 自动计算对冲比例（线性回归）
        if self.hedge_ratio is None and len(prices_a) > 10:
            if SCIPY_AVAILABLE:
                slope, intercept, r_value, p_value, std_err = stats.linregress(
                    prices_b, prices_a
                )
                self.current_hedge_ratio = slope
                print(f"对冲比例: {slope:.4f} (R²={r_value**2:.4f})")
            else:
                # 简化计算：使用价格比例的中位数
                ratios = prices_a / prices_b
                self.current_hedge_ratio = ratios.median()
                print(f"对冲比例(简化): {self.current_hedge_ratio:.4f}")
        
        # 计算价差
        spreads = prices_a - self.current_hedge_ratio * prices_b if self.current_hedge_ratio else prices_a - prices_b
        
        self.spread_mean = spreads.mean()
        self.spread_std = spreads.std()
        
        return True
    
    def _calculate_z_score(self, spread: float) -> float:
        """计算Z值"""
        if self.spread_mean is None or self.spread_std is None or self.spread_std == 0:
            return 0.0
        return (spread - self.spread_mean) / self.spread_std
    
    def on_data(self, data: Dict):
        super().on_data(data)
        
        current_time = data['timestamp']
        bar_data = data['data']
        
        symbol_a, symbol_b = self.pair_symbols
        
        if symbol_a not in bar_data or symbol_b not in bar_data:
            return
        
        price_a = bar_data[symbol_a].get('close')
        price_b = bar_data[symbol_b].get('close')
        
        if price_a is None or price_b is None:
            return
        
        # 更新价格历史
        self.price_history[symbol_a].append(price_a)
        self.price_history[symbol_b].append(price_b)
        
        # 更新统计量
        if not self._update_stats(symbol_a, symbol_b):
            return
        
        # 计算当前价差
        spread = self._calculate_spread(price_a, price_b)
        z_score = self._calculate_z_score(spread)
        
        portfolio = self._engine.portfolio
        position_a = portfolio.positions.get(symbol_a)
        position_b = portfolio.positions.get(symbol_b)
        qty_a = position_a.quantity if position_a else 0
        qty_b = position_b.quantity if position_b else 0
        
        # 交易逻辑
        if self.position_state == 0:
            # 无持仓，寻找入场机会
            
            if z_score > self.entry_z:
                # 价差过高 → 做空A，做多B
                target_value = portfolio.cash * self.max_position_pct
                
                qty_a = int(target_value / price_a)
                qty_b = int(target_value / price_b)
                
                if qty_a > 0 and qty_b > 0:
                    self.sell(symbol_a, qty_a)
                    self.buy(symbol_b, qty_b)
                    self.position_state = -1
                    self.entry_spread = spread
                    
                    print(f"[{current_time}] 配对做空 {symbol_a}/{symbol_b} "
                          f"(Z={z_score:.2f}, 价差=${spread:.2f})")
            
            elif z_score < -self.entry_z:
                # 价差过低 → 做多A，做空B
                target_value = portfolio.cash * self.max_position_pct
                
                qty_a = int(target_value / price_a)
                qty_b = int(target_value / price_b)
                
                if qty_a > 0 and qty_b > 0:
                    self.buy(symbol_a, qty_a)
                    self.sell(symbol_b, qty_b)
                    self.position_state = 1
                    self.entry_spread = spread
                    
                    print(f"[{current_time}] 配对做多 {symbol_a}/{symbol_b} "
                          f"(Z={z_score:.2f}, 价差=${spread:.2f})")
        
        else:
            # 有持仓，检查平仓条件
            
            # 价差回归 → 平仓
            if abs(z_score) < self.exit_z:
                if self.position_state == 1:
                    # 平多A空B
                    if qty_a > 0:
                        self.sell(symbol_a, qty_a)
                    if qty_b < 0:
                        self.buy(symbol_b, abs(qty_b))
                    
                    profit = (spread - self.entry_spread) * qty_a if self.entry_spread else 0
                    print(f"[{current_time}] 配对平仓 (回归) {symbol_a}/{symbol_b} "
                          f"(Z={z_score:.2f}, 盈利=${profit:.2f})")
                
                elif self.position_state == -1:
                    # 平空A多B
                    if qty_a < 0:
                        self.buy(symbol_a, abs(qty_a))
                    if qty_b > 0:
                        self.sell(symbol_b, qty_b)
                    
                    profit = (self.entry_spread - spread) * abs(qty_a) if self.entry_spread else 0
                    print(f"[{current_time}] 配对平仓 (回归) {symbol_a}/{symbol_b} "
                          f"(Z={z_score:.2f}, 盈利=${profit:.2f})")
                
                self.position_state = 0
                self.entry_spread = None
            
            # 止损：价差继续扩大
            elif abs(z_score) > self.entry_z * 1.5:
                print(f"[{current_time}] 配对止损 (Z={z_score:.2f})")
                
                if self.position_state == 1:
                    if qty_a > 0:
                        self.sell(symbol_a, qty_a)
                    if qty_b < 0:
                        self.buy(symbol_b, abs(qty_b))
                elif self.position_state == -1:
                    if qty_a < 0:
                        self.buy(symbol_a, abs(qty_a))
                    if qty_b > 0:
                        self.sell(symbol_b, qty_b)
                
                self.position_state = 0
                self.entry_spread = None
    
    def get_parameters(self) -> Dict:
        return {
            'lookback': {'value': self.lookback, 'min': 20, 'max': 252, 'type': 'int'},
            'entry_z': {'value': self.entry_z, 'min': 1.0, 'max': 4.0, 'type': 'float'},
            'exit_z': {'value': self.exit_z, 'min': 0.0, 'max': 2.0, 'type': 'float'}
        }
    
    def get_description(self) -> str:
        return f"配对交易策略 - {self.pair_symbols[0]}/{self.pair_symbols[1]} 统计套利"
