import numpy as np
import pandas as pd
import pytest

from pnl_attribution import (
    attribute_factors,
    attribute_pnl,
    calculate_returns,
    format_attribution_report,
    max_drawdown,
)


def make_nav(start=100, n=252, drift=0.0005, vol=0.015, seed=1):
    np.random.seed(seed)
    dates = pd.bdate_range('2022-01-01', periods=n)
    rets = np.random.normal(drift, vol, n)
    return pd.Series(start * (1 + rets).cumprod(), index=dates, name='nav')


def test_calculate_returns():
    nav = pd.Series([100, 110, 121], index=pd.to_datetime(['2022-01-01', '2022-01-02', '2022-01-03']))
    rets = calculate_returns(nav)
    assert np.isclose(rets.iloc[0], 0.10)
    assert np.isclose(rets.iloc[1], 0.10)


def test_max_drawdown():
    nav = pd.Series([100, 110, 90, 120], index=pd.to_datetime(['2022-01-01', '2022-01-02', '2022-01-03', '2022-01-04']))
    assert np.isclose(max_drawdown(nav), -0.1818, atol=0.001)


def test_attribute_pnl_basic():
    nav_a = make_nav(seed=10, drift=0.001, vol=0.015)
    nav_b = make_nav(seed=11, drift=0.000, vol=0.010)
    weights = {'strategy_a': 0.6, 'strategy_b': 0.4}
    res = attribute_pnl({'strategy_a': nav_a, 'strategy_b': nav_b}, weights)
    assert 'portfolio' in res
    assert 'attributions' in res
    assert len(res['attributions']) == 2
    total = sum(a['weight'] for a in res['attributions'])
    assert np.isclose(total, 1.0)
    # strategy_a 应该有更高的 CAGR 和贡献
    a = next(x for x in res['attributions'] if x['strategy'] == 'strategy_a')
    b = next(x for x in res['attributions'] if x['strategy'] == 'strategy_b')
    assert a['cagr'] > b['cagr']
    assert a['total_contribution'] > b['total_contribution']


def test_attribute_pnl_empty():
    assert attribute_pnl({}, {}) == {}


def test_attribute_factors():
    factor_weights = {
        'growth': {'growth': 0.30, 'price_accel': 0.20, 'momentum': 0.10},
        'value': {'value': 0.50, 'momentum': 0.10},
    }
    strategy_weights = {'growth': 0.6, 'value': 0.4}
    exposure = attribute_factors(factor_weights, strategy_weights)
    assert np.isclose(sum(exposure.values()), 1.0)
    assert 'growth' in exposure
    assert 'value' in exposure
    assert 'momentum' in exposure
    # 组合层面：growth = 0.6*0.3 = 0.18; value = 0.4*0.5 = 0.20，所以 value 略高于 growth
    assert exposure['value'] > exposure['growth']


def test_format_attribution_report():
    nav_a = make_nav(seed=10)
    nav_b = make_nav(seed=11)
    res = attribute_pnl({'strategy_a': nav_a, 'strategy_b': nav_b}, {'strategy_a': 0.5, 'strategy_b': 0.5})
    report = format_attribution_report(res)
    assert 'P&L Attribution Report' in report
    assert 'strategy_a' in report
    assert 'strategy_b' in report


def test_attribute_pnl_dataframe_input():
    nav_a = make_nav(seed=10)
    df = pd.DataFrame({'date': nav_a.index, 'nav': nav_a.values})
    res = attribute_pnl({'strategy_a': df}, {'strategy_a': 1.0})
    assert len(res['attributions']) == 1
