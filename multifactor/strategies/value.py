"""
ValueStrategy - 价值策略

基于 V14 因子框架中的估值相关因子（relative_value、garp、price_position）选股，
强调行业相对估值和行业调整后的成长价值比（GARP）。
"""

import pandas as pd

from strategies.factor_strategy import FactorSubStrategy


class ValueStrategy(FactorSubStrategy):
    """价值策略：选择行业相对估值低、GARP 合理的标的。"""

    _strategy_name = 'ValueStrategy'
    DEFAULT_WEIGHT_METHOD = 'equal'
    MOCK_PARAMS = {'seed': 44, 'vol': 0.015, 'drift': 0.0003, 'beta': 0.3}
    FACTOR_WEIGHTS = {
        'relative_value': 0.45,
        'garp': 0.40,
        'price_position': 0.15,
    }

    def _score(self, factors: pd.DataFrame) -> pd.Series:
        """价值打分。"""
        score = factors[list(self.FACTOR_WEIGHTS.keys())].fillna(0.5)
        return (score * pd.Series(self.FACTOR_WEIGHTS)).sum(axis=1)
