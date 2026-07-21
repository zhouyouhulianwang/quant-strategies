"""
SectorRotationStrategy - 行业轮动策略

逻辑：
1. 计算每个行业的行业级动量（成分股平均收益/动量）
2. 选择动量最强的前 K 个行业
3. 在入选行业内，用综合因子打分选股
4. 目标持仓在行业与个股两个维度做动量加权

继承 FactorSubStrategy 以复用数据加载、回测和约束逻辑，
主要重写 generate_signals 加入行业筛选层。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from strategies.factor_strategy import FactorSubStrategy

try:
    from main import INDUSTRY, TICKERS, compute_factors_v14
except ImportError:
    INDUSTRY = {}
    TICKERS = []
    compute_factors_v14 = None

try:
    from weight_allocation import (
        WeightAllocator, normalize_target_positions,
        apply_sector_constraints, apply_volatility_target
    )
    WEIGHT_ALLOC_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_AVAILABLE = False

logger = logging.getLogger(__name__)


class SectorRotationStrategy(FactorSubStrategy):
    """行业轮动策略：先选强势行业，再在行业内选强势个股。

    Parameters
    ----------
    top_sectors : int
        选择的行业数量。
    sector_lookback : int
        行业动量计算回望天数。
    sector_weight : float
        行业动量在个股综合得分中的权重（0-1）。
    """

    _strategy_name = 'SectorRotationStrategy'
    DEFAULT_WEIGHT_METHOD = 'momentum_weighted'
    MOCK_PARAMS = {'seed': 47, 'vol': 0.016, 'drift': 0.0005, 'beta': 0.45}
    FACTOR_WEIGHTS = {
        'momentum': 0.25,
        'growth': 0.20,
        'price_accel': 0.15,
        'rel_strength_accel': 0.15,
        'industry_momentum': 0.10,
        'technical': 0.10,
        'momentum_consistency': 0.05,
    }

    def _score(self, factors: pd.DataFrame) -> pd.Series:
        """行业轮动下的个股因子打分。"""
        cols = [c for c in self.FACTOR_WEIGHTS.keys() if c in factors.columns]
        if not cols:
            return pd.Series(0.0, index=factors.index)
        score = factors[cols].fillna(0.5)
        weights = {c: self.FACTOR_WEIGHTS[c] for c in cols}
        return (score * pd.Series(weights)).sum(axis=1)

    def __init__(
        self,
        use_real_data: bool = True,
        weight_method: Optional[str] = None,
        n_stocks: int = 15,
        max_position_pct: float = 0.20,
        top_sectors: int = 3,
        sector_lookback: int = 60,
        sector_weight: float = 0.40,
        **kwargs,
    ):
        super().__init__(
            use_real_data=use_real_data,
            weight_method=weight_method,
            n_stocks=n_stocks,
            max_position_pct=max_position_pct,
            **kwargs,
        )
        self.top_sectors = top_sectors
        self.sector_lookback = sector_lookback
        self.sector_weight = sector_weight

    # ------------------------------------------------------------------
    # 行业轮动层
    # ------------------------------------------------------------------

    def _compute_sector_momentum(self, price_df: pd.DataFrame) -> pd.Series:
        """计算每个行业的行业级动量得分。

        使用成分股在 sector_lookback 窗口内的平均收益，
        按市值近似（等权）聚合到行业层面。
        """
        if not INDUSTRY or len(price_df) < self.sector_lookback:
            return pd.Series(dtype=float)

        # 只保留有行业映射的股票
        mapped = {s: INDUSTRY[s] for s in price_df.columns if s in INDUSTRY}
        if not mapped:
            return pd.Series(dtype=float)

        # 计算个股在回望窗口内的收益
        returns = price_df.pct_change(self.sector_lookback).iloc[-1]
        # 按行业聚合平均收益
        sector_returns = {}
        for stock, sector in mapped.items():
            sector_returns.setdefault(sector, []).append(returns.get(stock, np.nan))
        sector_momentum = pd.Series({
            sector: np.nanmean(vals) for sector, vals in sector_returns.items()
        }).dropna()

        # 平滑：加入短期 20 日收益作为辅助确认
        short_returns = price_df.pct_change(20).iloc[-1]
        sector_short = {}
        for stock, sector in mapped.items():
            sector_short.setdefault(sector, []).append(short_returns.get(stock, np.nan))
        sector_short_score = pd.Series({
            sector: np.nanmean(vals) for sector, vals in sector_short.items()
        }).dropna()

        # 综合：60% 中期 + 40% 短期
        combined = sector_momentum * 0.6 + sector_short_score.reindex(sector_momentum.index, fill_value=0) * 0.4
        return combined.sort_values(ascending=False)

    def _select_sectors(self, price_df: pd.DataFrame) -> set:
        """返回动量最强的前 top_sectors 个行业。"""
        sector_momentum = self._compute_sector_momentum(price_df)
        if sector_momentum.empty:
            logger.warning("[SectorRotation] Industry mapping empty, fallback to all stocks")
            return set()
        selected = set(sector_momentum.index[:self.top_sectors])
        logger.info(f"[SectorRotation] Top sectors ({self.top_sectors}): {sorted(selected)}")
        return selected

    # ------------------------------------------------------------------
    # 重写信号生成
    # ------------------------------------------------------------------

    def generate_signals(
        self,
        price_df: Optional[pd.DataFrame] = None,
        vix: Optional[float] = None,
        live_mode: bool = False,
        capital: Optional[float] = None,
    ) -> Dict[str, float]:
        """生成行业轮动策略目标持仓。"""
        if price_df is None:
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')
            price_df, market_df = self._prepare_data(start, end)
            if price_df is None or len(price_df) == 0:
                return {}

        if price_df is None or len(price_df) < 60:
            return {}

        selected_sectors = self._select_sectors(price_df)

        # 个股因子打分
        price_slice = price_df.iloc[-252:]
        if compute_factors_v14 is None:
            return {}
        factors = compute_factors_v14(price_slice)
        base_score = self._score(factors)

        # 如果没有行业映射，退化为纯因子选股
        if not selected_sectors:
            stock_score = base_score
        else:
            # 给入选行业的个股加分
            sector_bonus = pd.Series(0.0, index=factors.index)
            for stock in factors.index:
                if INDUSTRY.get(stock) in selected_sectors:
                    sector_bonus[stock] = 1.0
            # 个股得分 = (1 - sector_weight) * 因子得分 + sector_weight * 行业 bonus
            stock_score = base_score * (1 - self.sector_weight) + sector_bonus * self.sector_weight

        selected = list(stock_score.sort_values(ascending=False).dropna().index[:self.n_stocks])
        if not selected:
            return {}

        portfolio_value = capital if capital is not None else 1_000_000.0

        if self.weight_allocator and WEIGHT_ALLOC_AVAILABLE:
            target_positions = self.weight_allocator.allocate(
                selected, price_df=price_df, target_value=portfolio_value
            )
        else:
            target_positions = {s: portfolio_value / len(selected) for s in selected}

        if WEIGHT_ALLOC_AVAILABLE and target_positions:
            weights = {s: v / sum(target_positions.values()) for s, v in target_positions.items()}
            weights = {s: min(v, self.max_position_pct) for s, v in weights.items()}
            total = sum(weights.values())
            weights = {s: v / total for s, v in weights.items()}
            if INDUSTRY:
                weights = apply_sector_constraints(weights, INDUSTRY, max_sector_pct=self.max_sector_pct)
            target_positions = {s: portfolio_value * w for s, w in weights.items()}
            target_positions = apply_volatility_target(
                target_positions, price_df, target_vol=self.target_vol, lookback=self.lookback
            )
            target_positions = normalize_target_positions(target_positions, portfolio_value)

        return target_positions

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status['top_sectors'] = self.top_sectors
        status['sector_lookback'] = self.sector_lookback
        return status

    def __repr__(self) -> str:
        return (
            f"SectorRotationStrategy(weight_method={self.weight_method}, "
            f"n_stocks={self.n_stocks}, top_sectors={self.top_sectors})"
        )
