"""Alpha多因子策略 - 量化投资经典模板

策略逻辑:
1. 价值因子: 低PE, 低PB, 高股息率
2. 质量因子: 高ROE, 低负债率, 稳定盈利
3. 动量因子: 近期强势
4. 规模因子: 中小盘溢价
5. 综合评分选股

适用场景: 股票多头、市场中性
时间框架: 月度再平衡
"""
import numpy as np
import pandas as pd
from typing import Dict, List
from datetime import datetime

from localquant.strategy import BaseStrategy


class AlphaFactorStrategy(BaseStrategy):
    """
    Alpha多因子策略
    
    参数:
    - value_weight: 价值因子权重
    - quality_weight: 质量因子权重
    - momentum_weight: 动量因子权重
    - top_n: 选股数量
    - rebalance_freq: 再平衡频率(天)
    
    使用示例:
    ```python
    strategy = AlphaFactorStrategy(
        symbols=sp500_symbols,
        value_weight=0.3,
        quality_weight=0.3,
        momentum_weight=0.4,
        top_n=20,
        rebalance_freq=20
    )
    ```
    
    注: 此策略需要基本面数据(PE, PB, ROE等)
    实际使用时需要接入财务数据API
    """
    
    def __init__(self, symbols: List[str],
                 value_weight: float = 0.3,
                 quality_weight: float = 0.3,
                 momentum_weight: float = 0.4,
                 size_weight: float = 0.0,
                 top_n: int = 20,
                 rebalance_freq: int = 20,
                 max_position_pct: float = 0.05):
        super().__init__()
        self.symbols = symbols
        self.value_weight = value_weight
        self.quality_weight = quality_weight
        self.momentum_weight = momentum_weight
        self.size_weight = size_weight
        self.top_n = top_n
        self.rebalance_freq = rebalance_freq
        self.max_position_pct = max_position_pct
        
        # 状态
        self.last_rebalance = None
        
        # 模拟基本面数据 (实际应从数据库/API获取)
        self.fundamentals = {}
    
    def _get_fundamental_data(self, symbol: str) -> Dict:
        """获取基本面数据 (模拟)"""
        # 实际使用时应从数据库或API获取
        # 这里用随机数模拟
        if symbol not in self.fundamentals:
            # 模拟: 市值越大，PE/PB越合理
            np.random.seed(hash(symbol) % 10000)
            self.fundamentals[symbol] = {
                'pe': np.random.uniform(10, 40),
                'pb': np.random.uniform(1, 5),
                'roe': np.random.uniform(0.05, 0.30),
                'debt_ratio': np.random.uniform(0.2, 0.8),
                'dividend_yield': np.random.uniform(0.0, 0.05),
                'market_cap': np.random.uniform(1e9, 2e12)
            }
        return self.fundamentals[symbol]
    
    def _calculate_value_score(self, symbol: str) -> float:
        """计算价值因子得分"""
        f = self._get_fundamental_data(symbol)
        
        # PE 越低越好
        pe_score = 1.0 / max(f['pe'], 1)
        
        # PB 越低越好
        pb_score = 1.0 / max(f['pb'], 0.1)
        
        # 股息率越高越好
        div_score = f['dividend_yield']
        
        return (pe_score * 0.4 + pb_score * 0.4 + div_score * 0.2)
    
    def _calculate_quality_score(self, symbol: str) -> float:
        """计算质量因子得分"""
        f = self._get_fundamental_data(symbol)
        
        # ROE 越高越好
        roe_score = f['roe']
        
        # 负债率越低越好
        debt_score = 1.0 - f['debt_ratio']
        
        return (roe_score * 0.6 + debt_score * 0.4)
    
    def _calculate_momentum_score(self, symbol: str, bar_data: Dict) -> float:
        """计算动量因子得分"""
        if symbol not in bar_data:
            return 0.0
        
        close = bar_data[symbol].get('close')
        if close is None:
            return 0.0
        
        # 获取历史价格
        hist = self.context.get_history(symbol, 'close', 60)
        if len(hist) < 20:
            return 0.0
        
        # 20日动量
        momentum_20 = close / hist.iloc[-20] - 1
        
        # 60日动量
        momentum_60 = close / hist.iloc[0] - 1 if len(hist) >= 60 else 0
        
        return momentum_20 * 0.6 + momentum_60 * 0.4
    
    def _calculate_size_score(self, symbol: str) -> float:
        """计算规模因子得分 (小盘溢价)"""
        f = self._get_fundamental_data(symbol)
        
        # 市值越小得分越高 (取倒数)
        market_cap = f['market_cap']
        # 归一化: 假设市值范围 1B - 2T
        return 1.0 / (1.0 + np.log10(market_cap / 1e9))
    
    def on_data(self, data: Dict):
        super().on_data(data)
        
        current_time = data['timestamp']
        bar_data = data['data']
        
        # 检查再平衡
        if self.last_rebalance is not None:
            days_since = (current_time - self.last_rebalance).days
            if days_since < self.rebalance_freq:
                return
        
        # 计算综合评分
        scores = {}
        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            
            value = self._calculate_value_score(symbol)
            quality = self._calculate_quality_score(symbol)
            momentum = self._calculate_momentum_score(symbol, bar_data)
            size = self._calculate_size_score(symbol)
            
            # 加权综合
            total_score = (
                value * self.value_weight +
                quality * self.quality_weight +
                momentum * self.momentum_weight +
                size * self.size_weight
            )
            
            scores[symbol] = total_score
        
        if not scores:
            return
        
        # 选择Top N
        top_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:self.top_n]
        
        print(f"\n[{current_time.date()}] AlphaFactor 再平衡:")
        print(f"  Top {self.top_n}:")
        for symbol, score in top_stocks[:5]:
            f = self._get_fundamental_data(symbol)
            print(f"    {symbol}: Score={score:.3f} (PE={f['pe']:.1f}, ROE={f['roe']:.1%})")
        
        # 清仓
        portfolio = self._engine.portfolio
        for symbol, position in list(portfolio.positions.items()):
            if position.quantity > 0 and symbol not in [s for s, _ in top_stocks]:
                self.sell(symbol, position.quantity)
        
        # 买入Top N (等权重)
        target_pct = min(1.0 / self.top_n, self.max_position_pct)
        for symbol, _ in top_stocks:
            self.target_percent(symbol, target_pct)
        
        self.last_rebalance = current_time
    
    def get_parameters(self) -> Dict:
        return {
            'value_weight': {'value': self.value_weight, 'min': 0, 'max': 1, 'type': 'float'},
            'quality_weight': {'value': self.quality_weight, 'min': 0, 'max': 1, 'type': 'float'},
            'momentum_weight': {'value': self.momentum_weight, 'min': 0, 'max': 1, 'type': 'float'},
            'top_n': {'value': self.top_n, 'min': 5, 'max': 100, 'type': 'int'}
        }
    
    def get_description(self) -> str:
        return (f"Alpha多因子策略 - 价值({self.value_weight:.0%})+"
                f"质量({self.quality_weight:.0%})+动量({self.momentum_weight:.0%})")
