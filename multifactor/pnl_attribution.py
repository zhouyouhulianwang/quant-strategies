"""
P&L Attribution - 组合收益归因分析

将组合收益拆解到各个子策略和因子维度，帮助识别：
- 哪些子策略在贡献/拖累收益
- 各因子的风险贡献和收益贡献
- 交互效应（diversification benefit）

输出可用于：
- 月度/季度投资报告
- 因子权重再平衡决策
- 识别失效或表现异常的子策略
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _ensure_nav_series(nav: Any) -> pd.Series:
    """统一 NAV 输入为以日期为索引的 pandas Series。"""
    if isinstance(nav, pd.Series):
        s = nav.copy()
    elif isinstance(nav, pd.DataFrame):
        if 'nav' in nav.columns:
            s = nav.set_index('nav').index.to_series() if nav.index.name == 'date' else nav['nav'].copy()
        elif 'nav_after_cost' in nav.columns:
            s = nav['nav_after_cost'].copy()
        else:
            s = nav.iloc[:, 0].copy()
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index)
        return s
    else:
        raise TypeError(f"nav must be pd.Series or pd.DataFrame, got {type(nav)}")

    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    return s.sort_index()


def calculate_returns(nav: pd.Series) -> pd.Series:
    """从 NAV 序列计算日收益率。"""
    nav = _ensure_nav_series(nav)
    returns = nav.pct_change().dropna()
    return returns


def annualized_return(nav: pd.Series, periods_per_year: float = 252.0) -> float:
    """年化收益。"""
    nav = _ensure_nav_series(nav)
    total = nav.iloc[-1] / nav.iloc[0] - 1.0
    n = len(nav)
    if n <= 1:
        return 0.0
    years = n / periods_per_year
    return float((1 + total) ** (1 / max(years, 1e-6)) - 1)


def annualized_volatility(returns: pd.Series, periods_per_year: float = 252.0) -> float:
    """年化波动率。"""
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: float = 252.0) -> float:
    """夏普比率。"""
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    vol = excess.std() * np.sqrt(periods_per_year)
    if vol <= 0:
        return 0.0
    return float(excess.mean() * periods_per_year / vol)


def max_drawdown(nav: pd.Series) -> float:
    """最大回撤（负值）。"""
    nav = _ensure_nav_series(nav)
    cummax = nav.cummax()
    dd = (nav - cummax) / cummax
    return float(dd.min())


def _align_nav_series(nav_series: Dict[str, pd.Series]) -> pd.DataFrame:
    """将多个 NAV 序列对齐到同一日期索引。"""
    cleaned = {}
    for name, nav in nav_series.items():
        s = _ensure_nav_series(nav).rename(name)
        cleaned[name] = s[~s.index.duplicated(keep='last')]
    aligned = pd.concat(cleaned.values(), axis=1)
    aligned = aligned.ffill().dropna()
    return aligned


def attribute_pnl(
    nav_series: Dict[str, pd.Series],
    weights: Dict[str, float],
    portfolio_nav: Optional[pd.Series] = None,
    risk_free_rate: float = 0.0,
    periods_per_year: float = 252.0,
) -> Dict[str, Any]:
    """
    对组合收益进行子策略层面的归因。

    Parameters
    ----------
    nav_series: dict
        {strategy_name: nav_series}
    weights: dict
        {strategy_name: weight}
    portfolio_nav: pd.Series, optional
        组合 NAV 序列；为 None 时按 weights 加权计算
    risk_free_rate: float
        年化无风险利率
    periods_per_year: float
        每年的交易日数

    Returns
    -------
    dict: 包含聚合指标和每个子策略的归因
    """
    if not nav_series or not weights:
        return {}
    aligned = _align_nav_series(nav_series)
    if aligned.empty:
        return {}

    # 组合 NAV
    if portfolio_nav is not None:
        portfolio = _ensure_nav_series(portfolio_nav).reindex(aligned.index).ffill()
    else:
        w = pd.Series({k: weights.get(k, 0.0) for k in aligned.columns})
        w = w / w.sum() if w.sum() > 0 else w
        portfolio = (aligned * w).sum(axis=1)

    portfolio_returns = calculate_returns(portfolio)
    total_cagr = annualized_return(portfolio, periods_per_year)
    total_vol = annualized_volatility(portfolio_returns, periods_per_year)
    total_sharpe = sharpe_ratio(portfolio_returns, risk_free_rate, periods_per_year)
    total_mdd = max_drawdown(portfolio)

    attributions = []
    # 加权组合收益（不含交互效应）
    weighted_returns = pd.DataFrame({
        name: calculate_returns(aligned[name]) * weights.get(name, 0.0)
        for name in aligned.columns
    })
    sum_weighted_return = weighted_returns.sum(axis=1)
    # 交互效应 = 组合实际收益 - 加权各策略收益
    interaction = portfolio_returns - sum_weighted_return

    for name in aligned.columns:
        nav = aligned[name]
        ret = calculate_returns(nav)
        cagr = annualized_return(nav, periods_per_year)
        vol = annualized_volatility(ret, periods_per_year)
        sharpe = sharpe_ratio(ret, risk_free_rate, periods_per_year)
        mdd = max_drawdown(nav)

        weight = weights.get(name, 0.0)
        #  standalone contribution ≈ weight * strategy return
        standalone_contribution = (ret * weight).mean() * periods_per_year
        #  交互效应归因按各策略加权收益占比分配
        denom = sum_weighted_return.abs().sum()
        if denom > 0 and not np.isnan(denom):
            interaction_alloc = (weighted_returns[name].abs().sum() / denom) * interaction.mean() * periods_per_year
        else:
            interaction_alloc = 0.0
        total_contribution = standalone_contribution + interaction_alloc

        # 风险贡献（基于协方差）
        cov = pd.concat([portfolio_returns, ret], axis=1).cov().iloc[0, 1] * periods_per_year
        marginal_risk = cov / (total_vol if total_vol > 0 else 1.0)
        risk_contribution = weight * marginal_risk

        attributions.append({
            'strategy': name,
            'weight': float(weight),
            'cagr': cagr,
            'volatility': vol,
            'sharpe': sharpe,
            'max_drawdown': mdd,
            'standalone_contribution': standalone_contribution,
            'interaction_allocation': interaction_alloc,
            'total_contribution': total_contribution,
            'risk_contribution': float(risk_contribution),
        })

    return {
        'start_date': aligned.index[0].strftime('%Y-%m-%d'),
        'end_date': aligned.index[-1].strftime('%Y-%m-%d'),
        'periods_per_year': periods_per_year,
        'portfolio': {
            'cagr': total_cagr,
            'volatility': total_vol,
            'sharpe': total_sharpe,
            'max_drawdown': total_mdd,
        },
        'interaction_effect': float(interaction.mean() * periods_per_year),
        'attributions': attributions,
    }


def attribute_factors(
    factor_weights: Dict[str, Dict[str, float]],
    strategy_weights: Dict[str, float],
) -> Dict[str, float]:
    """
    将各子策略的因子权重聚合到组合层面的因子暴露。

    Parameters
    ----------
    factor_weights: dict
        {strategy_name: {factor_name: weight}}
    strategy_weights: dict
        {strategy_name: portfolio_weight}

    Returns
    -------
    dict: {factor_name: portfolio_factor_exposure}
    """
    exposure = {}
    for strategy, factors in factor_weights.items():
        sw = strategy_weights.get(strategy, 0.0)
        for factor, fw in factors.items():
            exposure[factor] = exposure.get(factor, 0.0) + sw * fw
    total = sum(exposure.values())
    if total > 0:
        exposure = {k: v / total for k, v in exposure.items()}
    return exposure


def format_attribution_report(result: Dict[str, Any]) -> str:
    """将归因结果格式化为人类可读报告。"""
    lines = [
        "=" * 60,
        "P&L Attribution Report",
        "=" * 60,
        f"Period: {result['start_date']} ~ {result['end_date']}",
        "",
        "Portfolio Metrics:",
        f"  CAGR:      {result['portfolio']['cagr']*100:.2f}%",
        f"  Vol:       {result['portfolio']['volatility']*100:.2f}%",
        f"  Sharpe:    {result['portfolio']['sharpe']:.3f}",
        f"  MaxDD:     {result['portfolio']['max_drawdown']*100:.2f}%",
        "",
        "Strategy Attribution:",
        "-" * 60,
    ]
    for attr in result['attributions']:
        lines.append(
            f"  {attr['strategy']:20s} weight={attr['weight']*100:5.1f}% | "
            f"CAGR={attr['cagr']*100:6.2f}% | Sharpe={attr['sharpe']:5.2f} | "
            f"contr={attr['total_contribution']*100:6.2f}% | risk={attr['risk_contribution']*100:6.2f}%"
        )
    lines.append("-" * 60)
    lines.append(f"  Interaction effect: {result['interaction_effect']*100:.2f}%")
    lines.append("=" * 60)
    return "\n".join(lines)


if __name__ == '__main__':
    # 简单 sanity check：两个不相关资产的归因
    dates = pd.bdate_range('2022-01-01', '2023-01-01')
    np.random.seed(0)
    nav_a = pd.Series(100 * (1 + np.random.normal(0.0008, 0.015, len(dates))).cumprod(), index=dates)
    nav_b = pd.Series(100 * (1 + np.random.normal(0.0003, 0.010, len(dates))).cumprod(), index=dates)
    res = attribute_pnl(
        {'strategy_a': nav_a, 'strategy_b': nav_b},
        {'strategy_a': 0.6, 'strategy_b': 0.4},
    )
    print(format_attribution_report(res))
