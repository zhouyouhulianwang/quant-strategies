import numpy as np
import pandas as pd
import pytest

from factor_decay_monitor import (
    FactorDecayMonitor,
    compute_ic,
    compute_ic_series,
    factor_half_life,
    format_decay_report,
    summarize_ic,
)


def test_compute_ic_perfect_correlation():
    f = pd.Series([1, 2, 3, 4, 5], index=['A', 'B', 'C', 'D', 'E'])
    r = pd.Series([1, 2, 3, 4, 5], index=['A', 'B', 'C', 'D', 'E'])
    assert np.isclose(compute_ic(f, r, method='spearman'), 1.0, atol=0.01)


def test_compute_ic_inverse_correlation():
    f = pd.Series([1, 2, 3, 4, 5], index=['A', 'B', 'C', 'D', 'E'])
    r = pd.Series([5, 4, 3, 2, 1], index=['A', 'B', 'C', 'D', 'E'])
    assert np.isclose(compute_ic(f, r, method='spearman'), -1.0, atol=0.01)


def test_compute_ic_too_few_samples():
    f = pd.Series([1, 2], index=['A', 'B'])
    r = pd.Series([1, 2], index=['A', 'B'])
    assert np.isnan(compute_ic(f, r))


def test_compute_ic_series():
    np.random.seed(0)
    dates = pd.bdate_range('2022-01-01', periods=100)
    symbols = ['A', 'B', 'C', 'D', 'E']
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.normal(0, 0.01, (len(dates), len(symbols))), axis=0),
        index=dates, columns=symbols
    )
    factor = pd.DataFrame(
        np.random.rand(len(dates), len(symbols)),
        index=dates, columns=symbols
    )
    ic = compute_ic_series(factor, prices, forward_period=1)
    assert len(ic) > 0
    assert (-1 <= ic).all() and (ic <= 1).all()


def test_summarize_ic():
    ic = pd.Series([0.1, 0.2, -0.05, 0.15, 0.05])
    s = summarize_ic(ic)
    assert 'mean' in s
    assert 'ir' in s
    assert 'win_rate' in s
    assert np.isclose(s['mean'], 0.09)
    assert np.isclose(s['win_rate'], 0.8)


def test_factor_half_life():
    # 构造指数衰减的 IC 自相关
    np.random.seed(42)
    ic = pd.Series(np.random.normal(0, 0.1, 100))
    # 人为增加自相关，使半衰期可计算
    for i in range(1, len(ic)):
        ic.iloc[i] = 0.7 * ic.iloc[i-1] + 0.3 * ic.iloc[i]
    hl = factor_half_life(ic, max_lags=20)
    assert hl is not None
    assert hl > 0


def test_factor_half_life_too_short():
    ic = pd.Series([0.1, 0.2])
    assert factor_half_life(ic) is None


def test_factor_decay_monitor():
    np.random.seed(0)
    dates = pd.bdate_range('2022-01-01', periods=100)
    symbols = ['A', 'B', 'C', 'D', 'E']
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.normal(0, 0.01, (len(dates), len(symbols))), axis=0),
        index=dates, columns=symbols
    )
    factor = pd.DataFrame(
        np.random.rand(len(dates), len(symbols)),
        index=dates, columns=symbols
    )
    monitor = FactorDecayMonitor(forward_period=1)
    monitor.add_factor('dummy', factor)
    report = monitor.analyze(prices)
    assert 'summary' in report
    assert 'ranking' in report
    assert 'dummy' in report['summary']


def test_format_decay_report():
    np.random.seed(0)
    dates = pd.bdate_range('2022-01-01', periods=100)
    symbols = ['A', 'B', 'C', 'D', 'E']
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.normal(0, 0.01, (len(dates), len(symbols))), axis=0),
        index=dates, columns=symbols
    )
    factor = pd.DataFrame(
        np.random.rand(len(dates), len(symbols)),
        index=dates, columns=symbols
    )
    monitor = FactorDecayMonitor(forward_period=1)
    monitor.add_factor('dummy', factor)
    report = monitor.analyze(prices)
    text = format_decay_report(report)
    assert 'Factor Decay Monitor Report' in text
    assert 'dummy' in text
