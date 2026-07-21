"""
QualityStrategy - 质量/低波动策略

基于 V14 因子框架中的质量（quality、lowvol）、趋势（ma_trend）和
一致性（momentum_consistency）选股，强调防御性和稳健收益。
"""

import pandas as pd

from strategies.factor_strategy import FactorSubStrategy


class QualityStrategy(FactorSubStrategy):
    """质量/低波动策略：选择盈利质量高、波动低、趋势稳健的标的。"""

    _strategy_name = 'QualityStrategy'
    DEFAULT_WEIGHT_METHOD = 'risk_parity'
    MOCK_PARAMS = {'seed': 45, 'vol': 0.012, 'drift': 0.0002, 'beta': 0.25}
    FACTOR_WEIGHTS = {
        'quality': 0.35,
        'lowvol': 0.35,
        'ma_trend': 0.15,
        'momentum_consistency': 0.15,
    }

    def _score(self, factors: pd.DataFrame) -> pd.Series:
        """质量打分。"""
        score = factors[list(self.FACTOR_WEIGHTS.keys())].fillna(0.5)
        return (score * pd.Series(self.FACTOR_WEIGHTS)).sum(axis=1)
