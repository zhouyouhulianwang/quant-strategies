"""
FactorSubStrategy - 共享因子框架的子策略基类。

把 Momentum / Value / Quality / Growth 四个子策略中高度重复的代码：
- 数据准备 / mock 数据生成
- 因子打分 → 选股 → 权重分配 → 约束 overlay
- 月度回测引擎
- 状态/表示
统一抽取到本基类。子类只需声明 FACTOR_WEIGHTS、DEFAULT_WEIGHT_METHOD、MOCK_PARAMS。

同时修复了原先各子策略回测中存在的几个缺陷：
- 先卖出旧持仓再买入新持仓，避免现金透支
- 对 total_target > nav 的情况做缩放而非静默跳过
- 使用同一套配置读取 max_sector_pct / target_vol / lookback
"""

import logging
from abc import abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

try:
    from quantconnect_data import prepare_backtest_data_qc
    QC_DATA_AVAILABLE = True
except ImportError:
    QC_DATA_AVAILABLE = False

try:
    from main import TICKERS, INDUSTRY, compute_factors_v14, _get_next_trading_day
except ImportError:
    TICKERS = []
    INDUSTRY = {}
    compute_factors_v14 = None
    _get_next_trading_day = None

try:
    from weight_allocation import (
        WeightAllocator, normalize_target_positions,
        apply_sector_constraints, apply_volatility_target
    )
    WEIGHT_ALLOC_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_AVAILABLE = False


class FactorSubStrategy(BaseStrategy):
    """基于同一因子池、按不同权重选股的子策略基类。

    子类必须提供：
        - FACTOR_WEIGHTS: dict[str, float]   因子名 -> 权重
        - DEFAULT_WEIGHT_METHOD: str         默认权重分配方法
        - MOCK_PARAMS: dict                  模拟数据参数（seed, vol, drift, beta）
        - _strategy_name: str                 用于日志/状态显示的策略名

    Parameters
    ----------
    use_real_data : bool
    weight_method : str
    n_stocks : int
    max_position_pct : float
    max_sector_pct : float, optional
    target_vol : float, optional
    lookback : int, optional
    config : Any, optional
    """

    FACTOR_WEIGHTS: Dict[str, float] = {}
    DEFAULT_WEIGHT_METHOD: str = 'equal'
    MOCK_PARAMS: Dict[str, Any] = {'seed': 42, 'vol': 0.015, 'drift': 0.0003, 'beta': 0.3}
    _strategy_name: str = 'FactorSubStrategy'

    def __init__(
        self,
        use_real_data: bool = True,
        weight_method: Optional[str] = None,
        n_stocks: int = 15,
        max_position_pct: float = 0.20,
        max_sector_pct: Optional[float] = None,
        target_vol: Optional[float] = None,
        lookback: Optional[int] = None,
        config: Optional[Any] = None,
    ):
        super().__init__(config=config)
        self.use_real_data = use_real_data and QC_DATA_AVAILABLE
        self.weight_method = weight_method or self.DEFAULT_WEIGHT_METHOD
        self.n_stocks = n_stocks
        self.max_position_pct = max_position_pct
        self.max_sector_pct = self._resolve_param(max_sector_pct, 'max_sector_pct', 0.30)
        self.target_vol = self._resolve_param(target_vol, 'target_vol', 0.20)
        self.lookback = self._resolve_param(lookback, 'lookback', 60)
        self.weight_allocator = WeightAllocator(method=self.weight_method) if WEIGHT_ALLOC_AVAILABLE else None

    def _resolve_param(self, value: Optional[float], config_name: str, default: float) -> float:
        """优先使用传入值，其次从 config.risk 读取，最后使用默认值。"""
        if value is not None:
            return value
        if self.config and hasattr(self.config, 'risk'):
            risk = self.config.risk
            if hasattr(risk, config_name):
                return getattr(risk, config_name)
        return default

    # ------------------------------------------------------------------
    # 数据层
    # ------------------------------------------------------------------

    def _prepare_data(self, start_date, end_date) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """准备价格与市场数据。真实数据失败时回退到 mock。"""
        if self.use_real_data and QC_DATA_AVAILABLE:
            try:
                price_df, market_df = prepare_backtest_data_qc(
                    TICKERS, start_date, end_date, resolution='daily'
                )
                if price_df is not None and len(price_df) > 0:
                    return price_df, market_df
            except Exception as e:
                logger.warning(f"[{self._strategy_name}] Real data failed: {e}")
        return self._generate_mock_data(start_date, end_date)

    def _generate_mock_data(self, start_date, end_date) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """生成模拟价格与市场数据。"""
        dates = pd.bdate_range(start_date, end_date)
        n_days = len(dates)
        params = self.MOCK_PARAMS
        np.random.seed(params['seed'])
        prices = np.zeros((n_days, len(TICKERS)))
        prices[0] = np.random.uniform(20, 200, len(TICKERS))
        market_ret = np.random.normal(0.0003, 0.012, n_days)
        for i in range(1, n_days):
            for j, _ in enumerate(TICKERS):
                ret = np.random.normal(params['drift'], params['vol']) + params['beta'] * market_ret[i]
                prices[i, j] = prices[i - 1, j] * (1 + ret)
        price_df = pd.DataFrame(prices, index=dates, columns=TICKERS)
        price_df = price_df.replace(0, np.nan).ffill()
        market_df = pd.DataFrame({
            'VIX': np.clip(15 + np.cumsum(np.random.normal(0, 0.5, n_days)) * 0.08, 9, 55)
        }, index=dates)
        return price_df, market_df

    # ------------------------------------------------------------------
    # 打分与信号
    # ------------------------------------------------------------------

    @abstractmethod
    def _score(self, factors: pd.DataFrame) -> pd.Series:
        """子类实现：根据因子计算综合得分。"""
        ...

    def generate_signals(
        self,
        price_df: Optional[pd.DataFrame] = None,
        vix: Optional[float] = None,
        live_mode: bool = False,
        capital: Optional[float] = None,
    ) -> Dict[str, float]:
        """生成目标持仓（金额）。"""
        if price_df is None:
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')
            price_df, market_df = self._prepare_data(start, end)
            if price_df is None or len(price_df) == 0:
                return {}
            vix = market_df['VIX'].iloc[-1] if vix is None and 'VIX' in market_df.columns else vix

        if price_df is None or len(price_df) < 60:
            return {}

        price_slice = price_df.iloc[-252:]
        if compute_factors_v14 is None:
            return {}
        factors = compute_factors_v14(price_slice)
        score = self._score(factors)

        selected = list(score.sort_values(ascending=False).dropna().index[:self.n_stocks])
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

    def get_signals(self, date: datetime) -> Dict[str, float]:
        """获取指定日期的信号。"""
        end = date.strftime('%Y-%m-%d')
        start = (date - timedelta(days=400)).strftime('%Y-%m-%d')
        price_df, market_df = self._prepare_data(start, end)
        if price_df is None or len(price_df) == 0:
            return {}
        vix = market_df['VIX'].iloc[-1] if 'VIX' in market_df.columns else 20.0
        return self.generate_signals(price_df, vix=vix)

    # ------------------------------------------------------------------
    # 回测
    # ------------------------------------------------------------------

    def run_backtest(self, start_date=None, end_date=None, **kwargs) -> pd.DataFrame:
        """月度再平衡回测。修复：先卖出后买入、避免现金透支、目标超限时缩放。"""
        if start_date is None or end_date is None:
            start_date, end_date = self._default_backtest_dates()
        price_df, market_df = self._prepare_data(start_date, end_date)
        if price_df is None or len(price_df) < 252:
            logger.error(f"[{self._strategy_name}] Insufficient data for backtest")
            return pd.DataFrame()

        unique_ym = sorted(set((d.year, d.month) for d in price_df.index))
        monthly = []
        for y, m in unique_ym:
            days = price_df.index[(price_df.index.year == y) & (price_df.index.month == m)]
            if len(days) > 0:
                monthly.append(days[-1])
        monthly = [d for d in monthly if d >= price_df.index[252] and d in price_df.index]

        cash = 1_000_000.0
        positions: Dict[str, int] = {}
        records = []

        for signal_d in monthly:
            next_d = _get_next_trading_day(price_df, signal_d) if _get_next_trading_day else None
            if next_d is None or next_d not in price_df.index:
                continue

            # 用 next_d 价格重估当前持仓 NAV；持仓中存在 NaN 价格时以 0 估值，避免 NaN 传播
            prices = price_df.loc[next_d].fillna(0)
            if positions:
                equity = sum(
                    prices.get(s, 0) * qty for s, qty in positions.items()
                )
                nav = equity + cash
            else:
                nav = cash

            # 生成目标金额信号
            vix = market_df.loc[signal_d, 'VIX'] if 'VIX' in market_df.columns else 20.0
            price_slice = price_df.loc[:signal_d]
            raw_signals = self.generate_signals(price_slice, vix=vix, capital=nav)
            signals = {s: v for s, v in raw_signals.items() if v > 0 and s in prices and prices[s] > 0}
            total_target = sum(signals.values()) if signals else 0

            if total_target > 0:
                # 若目标金额超过 NAV，则按比例缩放，避免静默跳过整月
                scale = 1.0 if total_target <= nav else nav / total_target
                # 先卖出旧持仓
                cash = nav
                positions = {}
                # 再按目标金额买入，整股并检查现金非负
                for s, v in signals.items():
                    if s not in prices or prices[s] <= 0:
                        continue
                    target_value = v * scale
                    qty = int(target_value / prices[s])
                    if qty > 0:
                        cost = qty * prices[s]
                        if cost <= cash:
                            positions[s] = qty
                            cash -= cost
                        else:
                            # 现金不足，减少数量
                            qty = int(cash / prices[s])
                            if qty > 0:
                                positions[s] = qty
                                cash -= qty * prices[s]

            records.append({'date': next_d, 'nav': nav, 'cash': cash, 'n': len(positions)})

        result = pd.DataFrame(records)
        self.backtest_result = result
        return result

    # ------------------------------------------------------------------
    # 其他接口
    # ------------------------------------------------------------------

    def run_live_rebalance(self) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} 需通过 StrategyPortfolio 执行 live rebalance"
        )

    def live_trade(self, target_positions, **kwargs) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} 不直接执行 live trade"
        )

    def check_risk(self, **kwargs) -> None:
        """子策略级风控钩子。当前组合级风控已统一处理，子策略保留占位。"""
        pass

    def get_status(self) -> Dict[str, Any]:
        return {
            'strategy': self._strategy_name,
            'use_real_data': self.use_real_data,
            'weight_method': self.weight_method,
            'n_stocks': self.n_stocks,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(weight_method={self.weight_method}, n_stocks={self.n_stocks})"
