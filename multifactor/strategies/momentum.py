"""
MomentumStrategy - 动量策略

基于 V14 因子框架中的动量相关因子（momentum、growth、technical、price_accel、
rel_strength_accel、industry_momentum）选股，强调趋势跟踪。
"""

import pandas as pd

from strategies.factor_strategy import FactorSubStrategy


class MomentumStrategy(FactorSubStrategy):
    """动量策略：选择趋势最强、相对强度加速的标的。"""

    _strategy_name = 'MomentumStrategy'
    DEFAULT_WEIGHT_METHOD = 'momentum_weighted'
    MOCK_PARAMS = {'seed': 43, 'vol': 0.015, 'drift': 0.0005, 'beta': 0.5}
    FACTOR_WEIGHTS = {
        'momentum': 0.30,
        'growth': 0.20,
        'technical': 0.15,
        'price_accel': 0.15,
        'rel_strength_accel': 0.15,
        'industry_momentum': 0.05,
    }

    def _score(self, factors: pd.DataFrame) -> pd.Series:
        """动量打分。"""
        score = factors[list(self.FACTOR_WEIGHTS.keys())].fillna(0.5)
        return (score * pd.Series(self.FACTOR_WEIGHTS)).sum(axis=1)
