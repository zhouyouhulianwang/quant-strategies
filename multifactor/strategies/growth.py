"""
GrowthStrategy - 高成长策略

聚焦高成长标的：
- 短期/中期收益加速（growth、price_accel、rel_strength_accel）
- 行业相对成长（industry_momentum）
- 波动率压缩后突破（vol_contraction、base_breakout）
- 动量一致性（momentum_consistency）
"""

import pandas as pd

from strategies.factor_strategy import FactorSubStrategy


class GrowthStrategy(FactorSubStrategy):
    """高成长策略：选择收益/价格加速、行业相对强度领先的标的。"""

    _strategy_name = 'GrowthStrategy'
    DEFAULT_WEIGHT_METHOD = 'momentum_weighted'
    MOCK_PARAMS = {'seed': 46, 'vol': 0.018, 'drift': 0.0006, 'beta': 0.55}
    FACTOR_WEIGHTS = {
        'growth': 0.30,
        'price_accel': 0.20,
        'rel_strength_accel': 0.15,
        'industry_momentum': 0.10,
        'vol_contraction': 0.10,
        'base_breakout': 0.10,
        'momentum_consistency': 0.05,
    }

    def _score(self, factors: pd.DataFrame) -> pd.Series:
        """成长打分。"""
        score = factors[list(self.FACTOR_WEIGHTS.keys())].fillna(0.5)
        return (score * pd.Series(self.FACTOR_WEIGHTS)).sum(axis=1)
