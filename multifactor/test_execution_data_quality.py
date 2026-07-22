"""
执行质量与数据质量模块测试
覆盖 execution_quality.MarketImpactModel 与 data_validation 各函数，
以及 cost_model 与 MarketImpactModel 的集成。
"""

import numpy as np
import pandas as pd
import pytest

from execution_quality import MarketImpactModel, estimate_market_impact_bps
from data_validation import (
    validate_price_data,
    detect_survivorship_bias,
    validate_corporate_actions,
)
from cost_model import TradingCostModel


# ============================================================
# MarketImpactModel
# ============================================================

class TestMarketImpactModel:
    def test_init_rejects_bad_model(self):
        with pytest.raises(ValueError):
            MarketImpactModel(model_type='cubic')

    def test_zero_notional_returns_zero(self):
        m = MarketImpactModel()
        assert m.estimate_impact_bps(0, adv=1e6) == 0.0
        assert m.estimate_impact_bps(-100, adv=1e6) == 0.0

    def test_no_adv_returns_half_spread_only(self):
        m = MarketImpactModel(model_type='square_root', impact_bps=50.0)
        slip = m.estimate_impact_bps(notional=100_000, adv=0, spread_bps=10.0)
        assert slip == pytest.approx(5.0)  # half of 10 bps spread

    def test_linear_model_scales_with_participation(self):
        m = MarketImpactModel(model_type='linear', impact_bps=100.0)
        # 参与率 1% -> 冲击 1 bps + half spread
        slip = m.estimate_impact_bps(notional=10_000, adv=1_000_000, spread_bps=0)
        assert slip == pytest.approx(1.0)
        # 参与率 2% -> 冲击 2 bps（线性翻倍）
        slip2 = m.estimate_impact_bps(notional=20_000, adv=1_000_000, spread_bps=0)
        assert slip2 == pytest.approx(2.0)

    def test_square_root_model_sublinear(self):
        m = MarketImpactModel(model_type='square_root', impact_bps=100.0)
        # 参与率 1% -> sqrt(0.01)=0.1 -> 10 bps
        slip = m.estimate_impact_bps(notional=10_000, adv=1_000_000, spread_bps=0)
        assert slip == pytest.approx(10.0)
        # 参与率 4% -> sqrt(0.04)=0.2 -> 20 bps（参与率 4 倍，冲击仅 2 倍）
        slip2 = m.estimate_impact_bps(notional=40_000, adv=1_000_000, spread_bps=0)
        assert slip2 == pytest.approx(20.0)

    def test_participation_capped(self):
        m = MarketImpactModel(model_type='linear', impact_bps=50.0, max_participation=1.0)
        # 参与率 200% -> 截断到 100% -> 50 bps
        slip = m.estimate_impact_bps(notional=2_000_000, adv=1_000_000, spread_bps=0)
        assert slip == pytest.approx(50.0)

    def test_spread_added(self):
        m = MarketImpactModel(model_type='linear', impact_bps=0.0)
        slip = m.estimate_impact_bps(notional=1000, adv=1e9, spread_bps=8.0)
        assert slip == pytest.approx(4.0)  # half spread only

    def test_estimate_impact_cost(self):
        m = MarketImpactModel(model_type='linear', impact_bps=100.0)
        # 参与率 1% -> 1 bps -> $1 on $10k
        cost = m.estimate_impact_cost(notional=10_000, adv=1_000_000, spread_bps=0)
        assert cost == pytest.approx(1.0)

    def test_apply_impact_to_price(self):
        px_buy = MarketImpactModel.apply_impact_to_price(100.0, 'buy', 10.0)
        px_sell = MarketImpactModel.apply_impact_to_price(100.0, 'sell', 10.0)
        assert px_buy == pytest.approx(100.1)
        assert px_sell == pytest.approx(99.9)
        # 零滑点 / 无效价格不调整
        assert MarketImpactModel.apply_impact_to_price(100.0, 'buy', 0) == 100.0
        assert MarketImpactModel.apply_impact_to_price(0, 'buy', 10.0) == 0

    def test_convenience_function(self):
        slip = estimate_market_impact_bps(
            notional=10_000, adv=1_000_000, spread_bps=0,
            model_type='linear', impact_bps=100.0,
        )
        assert slip == pytest.approx(1.0)


# ============================================================
# validate_price_data
# ============================================================

def _make_prices(n=60, seed=0):
    dates = pd.date_range('2024-01-01', periods=n, freq='B')
    rng = np.random.default_rng(seed)
    px = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.Series(px, index=dates)


class TestValidatePriceData:
    def test_clean_data_passes(self):
        df = pd.DataFrame({'AAA': _make_prices(seed=1), 'BBB': _make_prices(seed=2)})
        rep = validate_price_data(df)
        assert rep['ok'] is True
        assert rep['issues'] == []
        assert rep['n_rows'] == 60 and rep['n_cols'] == 2

    def test_empty_df_fails(self):
        rep = validate_price_data(pd.DataFrame())
        assert rep['ok'] is False
        assert 'empty' in rep['issues'][0]

    def test_missing_values_detected(self):
        s = _make_prices()
        s.iloc[10:15] = np.nan
        rep = validate_price_data(pd.DataFrame({'AAA': s}))
        assert rep['ok'] is False
        assert rep['missing_values']['AAA']['count'] == 5

    def test_negative_prices_detected(self):
        s = _make_prices()
        s.iloc[20] = -5.0
        rep = validate_price_data(pd.DataFrame({'AAA': s}))
        assert rep['ok'] is False
        assert 'AAA' in rep['negative_prices']

    def test_stale_prices_detected(self):
        s = _make_prices()
        s.iloc[10:25] = s.iloc[10]  # 15 天相同
        rep = validate_price_data(pd.DataFrame({'AAA': s}), stale_days=10)
        assert rep['ok'] is False
        assert 'AAA' in rep['stale_prices']
        assert rep['stale_prices']['AAA'][0]['days'] == 15

    def test_suspicious_jumps_detected(self):
        s = _make_prices()
        s.iloc[30] = s.iloc[29] * 1.5  # +50% 跳变
        rep = validate_price_data(pd.DataFrame({'AAA': s}), jump_pct=0.30)
        assert rep['ok'] is False
        assert 'AAA' in rep['suspicious_jumps']
        assert rep['suspicious_jumps']['AAA'][0]['return'] == pytest.approx(0.5, abs=0.01)

    def test_input_not_modified(self):
        df = pd.DataFrame({'AAA': _make_prices()})
        snapshot = df.copy(deep=True)
        validate_price_data(df)
        pd.testing.assert_frame_equal(df, snapshot)


# ============================================================
# detect_survivorship_bias
# ============================================================

class TestSurvivorshipBias:
    def test_full_coverage_ok(self):
        rep = detect_survivorship_bias(['AAPL', 'MSFT'], available=['AAPL', 'MSFT'])
        assert rep['ok'] is True
        assert rep['coverage_pct'] == 1.0
        assert rep['missing_from_data'] == []

    def test_missing_tickers_reported(self):
        rep = detect_survivorship_bias(
            ['AAPL', 'MSFT', 'ENRON'], available=['AAPL', 'MSFT'],
        )
        assert rep['ok'] is False
        assert rep['missing_from_data'] == ['ENRON']
        assert rep['coverage_pct'] == pytest.approx(2 / 3, abs=0.001)
        assert 'survivorship' in rep['warning']

    def test_delisted_file(self, tmp_path):
        f = tmp_path / 'delisted.json'
        f.write_text('["ENRON", "LEH"]')
        rep = detect_survivorship_bias(
            ['AAPL', 'ENRON'], available=['AAPL', 'ENRON'],
            delisted_file=str(f),
        )
        assert rep['ok'] is False
        assert rep['known_delisted'] == ['ENRON']

    def test_empty_universe(self):
        rep = detect_survivorship_bias([], available=['AAPL'])
        assert rep['ok'] is False

    def test_case_insensitive(self):
        rep = detect_survivorship_bias(['aapl', 'msft'], available=['AAPL', 'MSFT'])
        assert rep['ok'] is True


# ============================================================
# validate_corporate_actions
# ============================================================

class TestCorporateActions:
    def test_clean_data_passes(self):
        df = pd.DataFrame({'AAA': _make_prices(seed=3)})
        rep = validate_corporate_actions(df)
        assert rep['ok'] is True
        assert rep['suspected_unadjusted_splits'] == {}

    def test_unadjusted_split_detected(self):
        s = _make_prices()
        s.iloc[30] = s.iloc[29] * 0.5  # 1:2 拆股未调整 -> -50%
        df = pd.DataFrame({'AAA': s})
        rep = validate_corporate_actions(df)
        assert rep['ok'] is False
        assert 'AAA' in rep['suspected_unadjusted_splits']
        assert rep['suspected_unadjusted_splits']['AAA'][0]['implied_ratio'] == '1:2'

    def test_splits_file_mismatch(self, tmp_path):
        s = _make_prices()
        split_date = s.index[30]
        s.iloc[30:] = s.iloc[30:] * 0.5  # 拆股后价格未调整
        f = tmp_path / 'splits.json'
        f.write_text('{"AAA": [{"date": "%s", "ratio": 2.0}]}' % split_date.strftime('%Y-%m-%d'))
        rep = validate_corporate_actions(pd.DataFrame({'AAA': s}), splits_file=str(f))
        assert rep['split_events_checked'] == 1
        assert len(rep['split_events_mismatched']) == 1
        assert rep['ok'] is False

    def test_splits_file_adjusted_ok(self, tmp_path):
        s = _make_prices()
        split_date = s.index[30]
        # 价格已按拆股调整：前后无比率跳变（历史价格已乘以 1/2）
        s.iloc[:30] = s.iloc[:30] / 2.0
        f = tmp_path / 'splits.json'
        f.write_text('{"AAA": [{"date": "%s", "ratio": 2.0}]}' % split_date.strftime('%Y-%m-%d'))
        rep = validate_corporate_actions(pd.DataFrame({'AAA': s}), splits_file=str(f))
        assert rep['split_events_checked'] == 1
        assert rep['split_events_mismatched'] == []


# ============================================================
# cost_model 集成
# ============================================================

class TestCostModelImpactIntegration:
    def test_default_behavior_unchanged(self):
        """不传 adv 时维持原有固定冲击逻辑"""
        m = TradingCostModel()
        cost = m.calculate_cost('AAPL', 1000, 150.0)  # $150k > $100k 阈值
        assert cost['market_impact'] == pytest.approx(150_000 * 0.0005)

    def test_impact_model_used_when_adv_given(self):
        impact_model = MarketImpactModel(model_type='linear', impact_bps=100.0)
        m = TradingCostModel(impact_model=impact_model)
        # $10k trade, ADV $1M -> 参与率 1% -> 冲击 1 bps + half spread(2.5) = 3.5 bps
        cost = m.calculate_cost('AAPL', 100, 100.0, adv=1_000_000, spread_bps=5.0)
        expected = 10_000 * 3.5 / 10_000
        assert cost['market_impact'] == pytest.approx(expected, rel=1e-6)
        # 此时固定阈值逻辑（>$100k）不应生效
        assert cost['market_impact'] != pytest.approx(10_000 * 0.0005)

    def test_impact_model_ignored_without_adv(self):
        impact_model = MarketImpactModel(model_type='linear', impact_bps=100.0)
        m = TradingCostModel(impact_model=impact_model)
        cost = m.calculate_cost('AAPL', 1000, 150.0)  # $150k, 无 adv -> 固定模型
        assert cost['market_impact'] == pytest.approx(150_000 * 0.0005)

    def test_invalid_price_returns_zero(self):
        impact_model = MarketImpactModel()
        m = TradingCostModel(impact_model=impact_model)
        cost = m.calculate_cost('AAPL', 100, 0, adv=1e6)
        assert cost['total_cost'] == 0.0
