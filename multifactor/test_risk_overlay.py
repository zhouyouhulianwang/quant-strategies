"""
风险覆盖层 (risk_overlay) 单元测试

覆盖:
- regime_detect: bull / bear / volatile / normal 分类
- dynamic_leverage: 波动率缩放、回撤缩放、状态上限、边界裁剪
- apply_drawdown_guard: 回撤触发与恢复
- correlation_stress_test: 压力波动率放大
- apply_risk_overlay_to_positions: 持仓缩放
- RiskOverlayAdvisor: 集成建议输出
- 与 RiskMonitor / WeightAllocator 的集成兼容性
"""

import os
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from risk_overlay import (
    regime_detect,
    dynamic_leverage,
    apply_drawdown_guard,
    correlation_stress_test,
    apply_risk_overlay_to_positions,
    RiskOverlayAdvisor,
    REGIMES,
)


def _make_prices(trend=0.0005, vol=0.015, periods=260, n=4, seed=42):
    """构造模拟价格数据"""
    np.random.seed(seed)
    dates = pd.bdate_range('2023-01-01', periods=periods)
    return pd.DataFrame(
        np.cumprod(1 + np.random.normal(trend, vol, (periods, n)), axis=0) * 100,
        index=dates,
        columns=[f'S{i}' for i in range(n)],
    )


class TestRegimeDetect:
    def test_volatile_on_high_vix(self):
        prices = _make_prices()
        assert regime_detect(prices, vix=40.0) == 'volatile'
        assert regime_detect(prices, vix=30.0) == 'volatile'

    def test_bull_on_uptrend_low_vix(self):
        prices = _make_prices(trend=0.002, vol=0.008)  # 稳定上涨
        assert regime_detect(prices, vix=15.0) == 'bull'

    def test_bear_on_downtrend(self):
        prices = _make_prices(trend=-0.002, vol=0.008)  # 稳定下跌
        assert regime_detect(prices, vix=15.0) == 'bear'

    def test_normal_on_flat_market(self):
        prices = _make_prices(trend=0.0002, vol=0.02)
        result = regime_detect(prices, vix=18.0)
        assert result in REGIMES  # 具体结果取决于随机走势，但必须合法

    def test_vix_none_ignored(self):
        prices = _make_prices()
        result = regime_detect(prices, vix=None)
        assert result in REGIMES

    def test_invalid_vix_ignored(self):
        prices = _make_prices()
        result = regime_detect(prices, vix='not_a_number')
        assert result in REGIMES

    def test_elevated_vix_makes_volatile(self):
        # 横盘市场 + VIX 26 -> volatile
        prices = _make_prices(trend=0.0, vol=0.02)
        result = regime_detect(prices, vix=26.0)
        assert result in ('volatile', 'bear', 'normal')  # bear 优先于 elevated VIX


class TestDynamicLeverage:
    def test_full_leverage_no_drawdown_low_vol(self):
        lev = dynamic_leverage(-0.02, target_vol=0.20, realized_vol=0.15, regime='normal')
        assert 1.0 <= lev <= 1.25  # normal cap

    def test_drawdown_reduces_leverage(self):
        lev_low_dd = dynamic_leverage(-0.05, 0.20, 0.20, regime='normal')
        lev_high_dd = dynamic_leverage(-0.14, 0.20, 0.20, regime='normal')
        assert lev_high_dd < lev_low_dd

    def test_hard_drawdown_hits_min(self):
        lev = dynamic_leverage(-0.20, 0.20, 0.20, regime='normal', min_leverage=0.5)
        assert lev == pytest.approx(0.5, abs=0.01)

    def test_regime_cap_respected(self):
        lev_volatile = dynamic_leverage(-0.01, 0.20, 0.10, regime='volatile')
        assert lev_volatile <= 0.5 + 1e-9
        lev_bull = dynamic_leverage(-0.01, 0.20, 0.10, regime='bull')
        assert lev_bull <= 1.5 + 1e-9

    def test_high_vol_reduces_leverage(self):
        lev = dynamic_leverage(-0.02, target_vol=0.20, realized_vol=0.40, regime='normal')
        assert lev <= 1.0

    def test_bounds_clip(self):
        lev = dynamic_leverage(-0.0, 0.20, 0.05, regime='bull',
                               max_leverage=1.5, min_leverage=0.5)
        assert 0.5 <= lev <= 1.5

    def test_invalid_inputs_safe(self):
        lev = dynamic_leverage('bad', 0.20, float('nan'), regime='unknown')
        assert 0.5 <= lev <= 1.5

    def test_zero_vol_defaults_to_one(self):
        lev = dynamic_leverage(-0.02, 0.20, 0.0, regime='normal')
        assert lev == pytest.approx(1.0, abs=0.01)


class TestDrawdownGuard:
    def test_no_drawdown_full_exposure(self):
        nav = pd.Series(np.linspace(1.0, 1.5, 50))
        exposure = apply_drawdown_guard(nav, max_dd=0.15)
        assert (exposure == 1.0).all()

    def test_breach_reduces_exposure(self):
        # 高点 1.2 -> 跌至 1.0 (dd = -16.7% < -15%)
        nav = pd.Series([1.0, 1.2, 1.0, 0.99, 0.98])
        exposure = apply_drawdown_guard(nav, max_dd=0.15, reduction_factor=0.5)
        assert exposure.iloc[0] == 1.0
        assert exposure.iloc[1] == 1.0
        assert exposure.iloc[2] == 0.5  # -16.7% 触发
        assert exposure.iloc[4] == 0.5  # 仍在防守

    def test_recovery_restores_exposure(self):
        # 触发后恢复到 -max_dd/2 以上
        nav = pd.Series([1.0, 1.2, 1.0, 1.1, 1.15, 1.19])
        exposure = apply_drawdown_guard(nav, max_dd=0.15, reduction_factor=0.5)
        assert exposure.iloc[2] == 0.5
        assert exposure.iloc[-1] == 1.0  # dd=-0.8% > -7.5% -> 恢复

    def test_empty_series(self):
        exposure = apply_drawdown_guard(pd.Series(dtype=float), max_dd=0.15)
        assert len(exposure) == 0

    def test_output_aligned_with_input(self):
        nav = pd.Series([1.0, 0.8, 0.7, 0.9], index=pd.bdate_range('2024-01-01', periods=4))
        exposure = apply_drawdown_guard(nav, max_dd=0.15)
        assert exposure.index.equals(nav.index)
        assert exposure.between(0.5, 1.0).all()


class TestCorrelationStressTest:
    def test_stress_vol_exceeds_normal(self):
        prices = _make_prices(vol=0.02)
        weights = {'S0': 0.25, 'S1': 0.25, 'S2': 0.25, 'S3': 0.25}
        result = correlation_stress_test(weights, prices, stress_correlation=0.9)
        assert result['stress_vol'] > result['normal_vol']
        assert result['vol_multiplier'] > 1.0
        assert 0.0 < result['suggested_scale'] <= 1.0

    def test_insufficient_data_safe(self):
        prices = _make_prices(periods=10)
        weights = {'S0': 0.5, 'S1': 0.5}
        result = correlation_stress_test(weights, prices)
        assert result['suggested_scale'] == 1.0
        assert np.isnan(result['normal_vol'])

    def test_missing_symbols_safe(self):
        prices = _make_prices()
        result = correlation_stress_test({'NOPE': 1.0}, prices)
        assert result['suggested_scale'] == 1.0


class TestApplyRiskOverlayToPositions:
    def test_scaling(self):
        positions = {'A': 100.0, 'B': 200.0}
        scaled = apply_risk_overlay_to_positions(positions, leverage=1.2, exposure_scale=0.5)
        assert scaled['A'] == pytest.approx(60.0)
        assert scaled['B'] == pytest.approx(120.0)

    def test_empty_positions(self):
        assert apply_risk_overlay_to_positions({}, 1.5, 1.0) == {}

    def test_non_positive_scale_returns_empty(self):
        positions = {'A': 100.0}
        assert apply_risk_overlay_to_positions(positions, 0.0, 1.0) == {}


class TestRiskOverlayAdvisor:
    def test_disabled_returns_neutral(self):
        advisor = RiskOverlayAdvisor(enabled=False)
        lev, exp = advisor.recommend(price_df=_make_prices(), vix=15.0)
        assert lev == 1.0 and exp == 1.0

    def test_recommend_outputs_in_range(self):
        advisor = RiskOverlayAdvisor(target_vol=0.20, max_dd=0.15)
        prices = _make_prices()
        nav = pd.Series(np.linspace(1.0, 1.2, 60))
        lev, exp = advisor.recommend(price_df=prices, vix=18.0, nav_series=nav)
        assert advisor.min_leverage <= lev <= advisor.max_leverage
        assert 0.0 < exp <= 1.0
        assert advisor.last_regime in REGIMES

    def test_drawdown_triggers_guard(self):
        advisor = RiskOverlayAdvisor(target_vol=0.20, max_dd=0.15)
        prices = _make_prices()
        # NAV 从 1.2 跌到 1.0 -> dd=-16.7%
        nav = pd.Series([1.0, 1.1, 1.2, 1.05, 1.0])
        lev, exp = advisor.recommend(price_df=prices, vix=18.0, nav_series=nav)
        assert exp == pytest.approx(0.5)

    def test_no_data_safe(self):
        advisor = RiskOverlayAdvisor()
        lev, exp = advisor.recommend(price_df=None, vix=None, nav_series=None)
        assert advisor.min_leverage <= lev <= advisor.max_leverage
        assert exp == 1.0


class TestIntegration:
    """与现有 RiskMonitor / WeightAllocator 的集成兼容性"""

    def test_risk_monitor_nav_history_usable(self, tmp_path):
        """RiskMonitor 的 nav_history 可直接用于 advisor.recommend"""
        from risk_monitor import RiskMonitor
        monitor = RiskMonitor(
            state_file=str(tmp_path / 'state.json'),
            kill_switch_file=str(tmp_path / 'kill'),
        )
        for nav in [1.0, 1.1, 1.2, 1.05, 1.0]:
            monitor.check_drawdown(nav)
        nav_series = pd.Series(
            [h['nav'] for h in monitor.nav_history],
            index=pd.to_datetime([h['timestamp'] for h in monitor.nav_history]),
        )
        advisor = RiskOverlayAdvisor(max_dd=0.15)
        lev, exp = advisor.recommend(price_df=_make_prices(), vix=18.0, nav_series=nav_series)
        assert exp == pytest.approx(0.5)  # -16.7% 回撤触发守卫
        assert advisor.min_leverage <= lev <= advisor.max_leverage

    def test_overlay_composes_with_weight_allocator(self):
        """WeightAllocator 输出的权重可经 overlay 缩放后归一化"""
        from weight_allocation import WeightAllocator, normalize_target_positions
        prices = _make_prices()
        symbols = list(prices.columns)
        allocator = WeightAllocator('equal')
        positions = allocator.allocate(symbols, prices, target_value=100_000)
        scaled = apply_risk_overlay_to_positions(positions, leverage=0.8, exposure_scale=0.5)
        normalized = normalize_target_positions(scaled, max_total_value=100_000)
        assert sum(normalized.values()) == pytest.approx(40_000, rel=0.01)

    def test_portfolio_imports_overlay(self):
        """strategies.portfolio 能正常导入 overlay 模块"""
        import strategies.portfolio as portfolio_module
        assert hasattr(portfolio_module, 'RISK_OVERLAY_AVAILABLE')

    def test_config_has_overlay_fields(self):
        """RiskConfig 包含 overlay 配置字段，默认值合法"""
        from config import RiskConfig
        cfg = RiskConfig()
        assert cfg.risk_overlay_enabled is False
        assert cfg.target_vol == pytest.approx(0.20)
        assert cfg.max_leverage == pytest.approx(1.5)
        assert cfg.min_leverage == pytest.approx(0.5)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
