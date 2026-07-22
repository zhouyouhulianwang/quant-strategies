"""
Regime-Aware Allocation (regime_allocator) 单元测试

覆盖:
- normalize_weights: 归一化、min_weight 下限、异常输入
- RegimeAllocator.target_weights: 各 regime 倾斜方向正确
- RegimeAllocator.allocate: 平滑（max single-step change）、未知 regime 回退
- StrategyPortfolio 集成: enabled 时按 regime 调整子策略权重，默认关闭
"""

import logging
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from regime_allocator import (
    RegimeAllocator,
    normalize_weights,
    DEFAULT_BASE_WEIGHTS,
    REGIME_WEIGHT_TILTS,
    VALID_REGIMES,
)


def _approx_sum1(weights, tol=1e-9):
    return abs(sum(weights.values()) - 1.0) < tol


class TestNormalizeWeights:
    def test_basic_normalization(self):
        w = normalize_weights({'a': 2.0, 'b': 1.0, 'c': 1.0})
        assert _approx_sum1(w)
        assert w['a'] == pytest.approx(0.5)
        assert w['b'] == pytest.approx(0.25)

    def test_min_weight_enforced(self):
        w = normalize_weights({'a': 0.97, 'b': 0.02, 'c': 0.01}, min_weight=0.05)
        assert _approx_sum1(w)
        assert all(v >= 0.05 - 1e-9 for v in w.values())

    def test_negative_and_nan_cleaned(self):
        w = normalize_weights({'a': 1.0, 'b': -0.5, 'c': float('nan')})
        assert _approx_sum1(w)
        assert w['a'] == pytest.approx(1.0)
        assert w['b'] == pytest.approx(0.0)

    def test_empty_input(self):
        assert normalize_weights({}) == {}

    def test_all_zero_equal_weights(self):
        w = normalize_weights({'a': 0.0, 'b': 0.0})
        assert _approx_sum1(w)
        assert w['a'] == pytest.approx(0.5)

    def test_infeasible_min_weight_ignored(self):
        # 5 strategies * 0.3 min > 1.0 -> 忽略下限但不崩溃
        w = normalize_weights({f's{i}': 1.0 for i in range(5)}, min_weight=0.3)
        assert _approx_sum1(w)


class TestRegimeTargetWeights:
    def test_all_regimes_normalized_and_feasible(self):
        allocator = RegimeAllocator()
        for regime in VALID_REGIMES:
            w = allocator.target_weights(regime)
            assert _approx_sum1(w), f"{regime} not normalized"
            assert all(v >= allocator.min_weight - 1e-9 for v in w.values()), \
                f"{regime} violates min_weight"

    def test_normal_matches_base(self):
        allocator = RegimeAllocator()
        w = allocator.target_weights('normal')
        for k, v in DEFAULT_BASE_WEIGHTS.items():
            assert w[k] == pytest.approx(v, abs=1e-6)

    def test_sector_lower_in_bear_and_volatile(self):
        allocator = RegimeAllocator()
        base = allocator.target_weights('normal')['sector_rotation']
        assert allocator.target_weights('bear')['sector_rotation'] < base
        assert allocator.target_weights('volatile')['sector_rotation'] < base
        # volatile 应比 bear 更低
        assert allocator.target_weights('volatile')['sector_rotation'] <= \
            allocator.target_weights('bear')['sector_rotation']

    def test_sector_higher_in_bull(self):
        allocator = RegimeAllocator()
        base = allocator.target_weights('normal')['sector_rotation']
        assert allocator.target_weights('bull')['sector_rotation'] > base

    def test_defensive_tilt_in_bear(self):
        allocator = RegimeAllocator()
        normal = allocator.target_weights('normal')
        bear = allocator.target_weights('bear')
        assert bear['quality'] > normal['quality']
        assert bear['value'] > normal['value']

    def test_offensive_tilt_in_bull(self):
        allocator = RegimeAllocator()
        normal = allocator.target_weights('normal')
        bull = allocator.target_weights('bull')
        assert bull['quality'] < normal['quality']

    def test_unknown_regime_falls_back(self):
        allocator = RegimeAllocator()
        w = allocator.target_weights('sideways')  # 非法 regime
        for k, v in DEFAULT_BASE_WEIGHTS.items():
            assert w[k] == pytest.approx(v, abs=1e-6)


class TestRegimeAllocatorAllocate:
    def test_no_smoothing_hits_target_immediately(self):
        allocator = RegimeAllocator(max_step=None)
        current = dict(DEFAULT_BASE_WEIGHTS)
        result = allocator.allocate('bear', current)
        target = allocator.target_weights('bear')
        for k in target:
            assert result[k] == pytest.approx(target[k], abs=1e-6)
        assert _approx_sum1(result)

    def test_smoothing_limits_single_step(self):
        max_step = 0.10
        allocator = RegimeAllocator(max_step=max_step)
        current = dict(DEFAULT_BASE_WEIGHTS)
        result = allocator.allocate('volatile', current)
        for k in current:
            assert abs(result[k] - current[k]) <= max_step + 1e-6, \
                f"{k} changed by more than max_step"
        assert _approx_sum1(result)

    def test_smoothing_converges_over_steps(self):
        allocator = RegimeAllocator(max_step=0.10)
        current = dict(DEFAULT_BASE_WEIGHTS)
        # 反复保持同一 regime，应逐步逼近目标
        for _ in range(10):
            current = allocator.allocate('volatile', current)
        target = allocator.target_weights('volatile')
        for k in target:
            assert current[k] == pytest.approx(target[k], abs=1e-6)

    def test_smoothing_no_whipsaw_on_regime_flip(self):
        allocator = RegimeAllocator(max_step=0.10)
        current = dict(DEFAULT_BASE_WEIGHTS)
        # normal -> bear -> bull 快速切换，单步变化仍受限
        w1 = allocator.allocate('bear', current)
        w2 = allocator.allocate('bull', w1)
        for k in w1:
            assert abs(w2[k] - w1[k]) <= 0.10 + 1e-6
        assert _approx_sum1(w2)

    def test_disabled_returns_current(self):
        allocator = RegimeAllocator(enabled=False)
        current = dict(DEFAULT_BASE_WEIGHTS)
        result = allocator.allocate('bear', current)
        for k in current:
            assert result[k] == pytest.approx(current[k], abs=1e-6)

    def test_min_weight_preserved_after_smoothing(self):
        allocator = RegimeAllocator(min_weight=0.05, max_step=0.05)
        current = dict(DEFAULT_BASE_WEIGHTS)
        for regime in ['bear', 'volatile', 'bull', 'normal']:
            current = allocator.allocate(regime, current)
            assert all(v >= 0.05 - 1e-9 for v in current.values())
            assert _approx_sum1(current)

    def test_new_strategy_key_added_with_min_weight(self):
        allocator = RegimeAllocator(max_step=None)
        current = dict(DEFAULT_BASE_WEIGHTS)
        current['new_factor'] = 0.0  # 新策略，当前权重为 0
        result = allocator.allocate('normal', current)
        assert result['new_factor'] >= allocator.min_weight - 1e-9
        assert _approx_sum1(result)

    def test_last_state_tracked(self):
        allocator = RegimeAllocator()
        allocator.allocate('bear', dict(DEFAULT_BASE_WEIGHTS))
        assert allocator.last_regime == 'bear'
        assert allocator.last_weights is not None
        allocator.reset()
        assert allocator.last_regime is None
        assert allocator.last_weights is None


class TestPortfolioIntegration:
    """StrategyPortfolio 集成测试（不依赖真实数据 / 网络）"""

    def _make_portfolio(self, regime_allocator=None, config=None):
        from strategies.portfolio import StrategyPortfolio
        from strategies.minimal_example import MinimalExampleStrategy

        strategies = [
            ('growth', MinimalExampleStrategy(), 0.40),
            ('sector_rotation', MinimalExampleStrategy(), 0.20),
            ('momentum', MinimalExampleStrategy(), 0.15),
            ('value', MinimalExampleStrategy(), 0.10),
            ('quality', MinimalExampleStrategy(), 0.15),
        ]
        return StrategyPortfolio(
            strategies,
            enable_risk_monitor=False,
            use_paper_trading=False,
            config=config,
            regime_allocator=regime_allocator,
        )

    def test_default_off_no_allocator(self):
        portfolio = self._make_portfolio()
        assert portfolio.regime_allocator is None

    def test_explicit_allocator_accepted(self):
        allocator = RegimeAllocator()
        portfolio = self._make_portfolio(regime_allocator=allocator)
        assert portfolio.regime_allocator is allocator

    def test_config_enabled_creates_allocator(self):
        from config import V14StrategyConfig
        cfg = V14StrategyConfig()
        cfg.risk.regime_allocator_enabled = True
        portfolio = self._make_portfolio(config=cfg)
        assert portfolio.regime_allocator is not None
        assert isinstance(portfolio.regime_allocator, RegimeAllocator)

    def test_config_default_disabled(self):
        from config import V14StrategyConfig
        cfg = V14StrategyConfig()
        assert cfg.risk.regime_allocator_enabled is False
        portfolio = self._make_portfolio(config=cfg)
        assert portfolio.regime_allocator is None

    def test_generate_signals_applies_regime_weights(self, monkeypatch):
        allocator = RegimeAllocator(max_step=None)  # 不平滑，一步到目标
        portfolio = self._make_portfolio(regime_allocator=allocator)

        # Mock 数据加载与 regime 检测，避免真实 IO
        import strategies.portfolio as portfolio_mod
        monkeypatch.setattr(portfolio_mod, 'QC_DATA_AVAILABLE', False)
        monkeypatch.setattr(portfolio_mod, 'regime_detect', lambda df, vix: 'bear')

        captured = {}

        def fake_signals(self, price_df=None, vix=None, capital=0, live_mode=False):
            captured['capital'] = captured.get('capital', []) + [capital]
            return {'AAPL': capital}

        monkeypatch.setattr(
            'strategies.minimal_example.MinimalExampleStrategy.generate_signals',
            fake_signals,
        )

        portfolio.generate_signals(total_value=1_000_000)

        # bear 目标: growth=0.35, sector=0.10, momentum=0.15, value=0.15, quality=0.25
        expected = portfolio.regime_allocator.target_weights('bear')
        weights = {item['name']: item['weight'] for item in portfolio.strategies}
        for k, v in expected.items():
            assert weights[k] == pytest.approx(v, abs=1e-6)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

        # 资金分配应与权重一致
        assert len(captured['capital']) == 5

    def test_generate_signals_regime_failure_keeps_static(self, monkeypatch):
        allocator = RegimeAllocator()
        portfolio = self._make_portfolio(regime_allocator=allocator)

        import strategies.portfolio as portfolio_mod
        monkeypatch.setattr(portfolio_mod, 'QC_DATA_AVAILABLE', False)

        def bad_regime(df, vix):
            raise RuntimeError("boom")

        monkeypatch.setattr(portfolio_mod, 'regime_detect', bad_regime)
        monkeypatch.setattr(
            'strategies.minimal_example.MinimalExampleStrategy.generate_signals',
            lambda self, price_df=None, vix=None, capital=0, live_mode=False: {'AAPL': capital},
        )

        portfolio.generate_signals(total_value=1_000_000)
        weights = {item['name']: item['weight'] for item in portfolio.strategies}
        # 静态权重保持不变
        assert weights['growth'] == pytest.approx(0.40)
        assert weights['sector_rotation'] == pytest.approx(0.20)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, '-v'])
