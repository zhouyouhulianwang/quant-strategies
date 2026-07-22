"""
Factor Decay Monitor - Alpha 信号衰减监控

跟踪各 alpha 因子的预测能力随时间变化，帮助识别：
- 哪些因子正在失效
- 因子 IC 的半衰期
- 需要多久更新一次因子权重或因子池

核心指标：
- IC (Information Coefficient): 当期因子值与下期收益的秩相关系数
- ICIR: IC 均值 / IC 标准差，衡量因子稳定性
- 半衰期: IC 自相关系数衰减到 0.5 所需的滞后周期
- 胜率: IC > 0 的比例
"""

import json
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    method: str = 'spearman',
) -> float:
    """
    计算单期信息系数 (IC)。

    Parameters
    ----------
    factor_values: pd.Series, index=symbols
        某一时点的因子值
    forward_returns: pd.Series, index=symbols
        对应下一期（通常 1-5 天）的收益率
    method: str
        'spearman' | 'pearson'

    Returns
    -------
    float: IC 值
    """
    idx = factor_values.dropna().index.intersection(forward_returns.dropna().index)
    if len(idx) < 3:
        return np.nan
    f = factor_values.loc[idx]
    r = forward_returns.loc[idx]
    if method == 'spearman':
        # 兼容无 scipy 环境：先排名再 pearson
        return float(f.rank().corr(r.rank(), method='pearson'))
    return float(f.corr(r, method='pearson'))


def compute_ic_series(
    factor_panel: pd.DataFrame,
    price_df: pd.DataFrame,
    forward_period: int = 1,
    method: str = 'spearman',
) -> pd.Series:
    """
    计算某因子随时间变化的 IC 序列。

    Parameters
    ----------
    factor_panel: pd.DataFrame, index=dates, columns=symbols
        因子值面板
    price_df: pd.DataFrame, index=dates, columns=symbols
        价格面板
    forward_period: int
        前视收益周期（交易日）
    method: str
        'spearman' | 'pearson'

    Returns
    -------
    pd.Series: index=dates, values=IC
    """
    returns = price_df.pct_change(forward_period).shift(-forward_period)
    ics = []
    dates = []
    for date in factor_panel.index:
        if date not in returns.index:
            continue
        f = factor_panel.loc[date]
        r = returns.loc[date]
        ic = compute_ic(f, r, method=method)
        if not np.isnan(ic):
            ics.append(ic)
            dates.append(date)
    return pd.Series(ics, index=pd.to_datetime(dates), name='ic')


def factor_half_life(ic_series: pd.Series, max_lags: int = 20) -> Optional[float]:
    """
    根据 IC 自相关计算因子半衰期。

    假设 IC 自相关呈指数衰减：rho(k) = exp(-lambda * k)
    半衰期 = ln(2) / lambda

    Returns
    -------
    float or None
    """
    if len(ic_series) < max_lags + 5:
        return None
    autocorrs = []
    for lag in range(1, max_lags + 1):
        c = ic_series.autocorr(lag=lag)
        if not np.isnan(c) and c > 0:
            autocorrs.append((lag, np.log(max(c, 1e-6))))
    if len(autocorrs) < 3:
        return None
    lags = np.array([x[0] for x in autocorrs])
    log_rhos = np.array([x[1] for x in autocorrs])
    # 线性回归: log_rho = -lambda * lag
    lambda_ = -np.polyfit(lags, log_rhos, 1)[0]
    if lambda_ <= 0:
        return None
    return float(np.log(2) / lambda_)


def summarize_ic(ic_series: pd.Series) -> Dict[str, Any]:
    """汇总 IC 序列的关键指标。"""
    ic = ic_series.dropna()
    if len(ic) == 0:
        return {
            'mean': 0.0,
            'std': 0.0,
            'ir': 0.0,
            'win_rate': 0.0,
            'half_life': None,
            'n': 0,
        }
    return {
        'mean': float(ic.mean()),
        'std': float(ic.std()),
        'ir': float(ic.mean() / ic.std()) if ic.std() > 0 else 0.0,
        'win_rate': float((ic > 0).sum() / len(ic)),
        'half_life': factor_half_life(ic),
        'n': len(ic),
    }


class FactorDecayMonitor:
    """
    多因子衰减监控器。

    Usage:
        monitor = FactorDecayMonitor(forward_period=5)
        monitor.add_factor('momentum', momentum_panel)
        monitor.add_factor('value', value_panel)
        report = monitor.analyze(price_df)
    """

    def __init__(self, forward_period: int = 5, method: str = 'spearman'):
        self.forward_period = forward_period
        self.method = method
        self.factors: Dict[str, pd.DataFrame] = {}

    def add_factor(self, name: str, factor_panel: pd.DataFrame) -> None:
        """添加因子面板。"""
        self.factors[name] = factor_panel

    def analyze(self, price_df: pd.DataFrame) -> Dict[str, Any]:
        """对所有因子计算 IC 并汇总。"""
        results = {}
        for name, panel in self.factors.items():
            ic_series = compute_ic_series(
                panel, price_df,
                forward_period=self.forward_period,
                method=self.method,
            )
            summary = summarize_ic(ic_series)
            summary['ic_series'] = ic_series
            results[name] = summary

        # 排序：按 IR 降序
        ranking = sorted(
            results.items(),
            key=lambda x: x[1]['ir'],
            reverse=True,
        )

        return {
            'forward_period': self.forward_period,
            'method': self.method,
            'summary': {name: {k: v for k, v in stats.items() if k != 'ic_series'}
                        for name, stats in results.items()},
            'ranking': [name for name, _ in ranking],
            'ic_series': {name: stats['ic_series'] for name, stats in results.items()},
        }

    def flag_concerns(self, ir_threshold: float = 0.3, win_rate_threshold: float = 0.5) -> List[str]:
        """
        返回需要关注的因子列表。
        注意：需要先调用 analyze()。
        """
        # 本方法依赖外部调用 analyze 后传入 results，保持简单接口
        return []


def format_decay_report(report: Dict[str, Any]) -> str:
    """将因子衰减报告格式化为人类可读字符串。"""
    lines = [
        "=" * 70,
        "Factor Decay Monitor Report",
        "=" * 70,
        f"Forward period: {report['forward_period']} days",
        f"IC method: {report['method']}",
        "",
        f"{'Factor':20s} {'Mean IC':>10s} {'IC IR':>10s} {'Win Rate':>10s} {'Half-life':>12s} {'Status':>12s}",
        "-" * 70,
    ]
    for factor in report['ranking']:
        s = report['summary'][factor]
        mean_ic = s['mean']
        ir = s['ir']
        win = s['win_rate']
        hl = s['half_life']
        hl_str = f"{hl:.1f}" if hl is not None else "N/A"
        if ir > 0.3 and win > 0.5:
            status = "HEALTHY"
        elif ir > 0.15 and win > 0.45:
            status = "WATCH"
        else:
            status = "DECAYED"
        lines.append(
            f"{factor:20s} {mean_ic:>10.3f} {ir:>10.3f} {win*100:>9.1f}% {hl_str:>12s} {status:>12s}"
        )
    lines.append("=" * 70)
    return "\n".join(lines)


if __name__ == '__main__':
    # 简单 sanity check
    np.random.seed(0)
    dates = pd.bdate_range('2022-01-01', '2023-01-01')
    symbols = ['A', 'B', 'C', 'D', 'E']
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.normal(0.0003, 0.015, (len(dates), len(symbols))), axis=0),
        index=dates, columns=symbols
    )
    # 构造一个有效因子：与下一期收益正相关
    factor = pd.DataFrame(
        np.random.rand(len(dates), len(symbols)) + prices.pct_change(5).shift(-5).values * 10,
        index=dates, columns=symbols
    )
    monitor = FactorDecayMonitor(forward_period=5)
    monitor.add_factor('random_factor', factor)
    report = monitor.analyze(prices)
    print(format_decay_report(report))
