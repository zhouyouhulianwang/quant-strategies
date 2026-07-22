#!/usr/bin/env python3
"""
Walk-forward / out-of-sample backtest for the StrategyPortfolio combination
(growth + sector_rotation + momentum + value + quality).

将完整区间切分为多个 rolling train/test 窗口：
  - train 窗口：可选运行权重优化（coarse sweep），或用固定权重
  - test 窗口：完全独立，用 train 得到的权重运行 StrategyPortfolio，产生 OOS 收益

用法示例:
    # 固定权重 walk-forward
    python3 walk_forward_portfolio.py --start 2020-01-01 --end 2024-12-31 \\
        --train-years 2 --test-months 6 --weights equal

    # 每个 train 窗口内做权重优化，然后在 test 窗口验证
    python3 walk_forward_portfolio.py --optimize --weights-optimize-metric sharpe

输出:
    optimization_walkforward_portfolio.json — 聚合 OOS 指标 + 每窗口结果
"""

import argparse
import itertools
import json
import logging
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from logging_config import setup_logging
from strategies.portfolio import StrategyPortfolio
from strategies.momentum import MomentumStrategy
from strategies.value import ValueStrategy
from strategies.quality import QualityStrategy
from strategies.growth import GrowthStrategy
from strategies.sector_rotation import SectorRotationStrategy
from walk_forward_test import generate_windows, compute_metrics

try:
    from main import INDUSTRY, TICKERS
except ImportError:
    INDUSTRY = {}
    TICKERS = []

try:
    from regime_allocator import RegimeAllocator
    from risk_overlay import regime_detect
    from quantconnect_data import prepare_backtest_data_qc
    REGIME_TOOLS_AVAILABLE = True
except ImportError:
    RegimeAllocator = None
    regime_detect = None
    prepare_backtest_data_qc = None
    REGIME_TOOLS_AVAILABLE = False

setup_logging()
logger = logging.getLogger('walk_forward_portfolio')

STRATEGY_NAMES = ['growth', 'sector_rotation', 'momentum', 'value', 'quality']

# 与 optimize_portfolio_weights.py 保持一致的子策略参数化
def build_strategies() -> Dict[str, object]:
    return {
        'growth': GrowthStrategy(use_real_data=True, weight_method='momentum_weighted', n_stocks=25),
        'sector_rotation': SectorRotationStrategy(use_real_data=True, weight_method='momentum_weighted',
                                                  n_stocks=15, top_sectors=4, sector_lookback=80,
                                                  sector_weight=0.4),
        'momentum': MomentumStrategy(use_real_data=True, weight_method='momentum_weighted', n_stocks=10),
        'value': ValueStrategy(use_real_data=True, weight_method='equal', n_stocks=20),
        'quality': QualityStrategy(use_real_data=True, weight_method='risk_parity', n_stocks=20),
    }


def build_portfolio(weights: Dict[str, float], regime_aware: bool = False) -> StrategyPortfolio:
    """用给定权重构造 StrategyPortfolio。weight=0 的策略也保留（由 portfolio 归一化）。"""
    strategy_map = build_strategies()
    strategies = [
        (name, strategy_map[name], float(weights.get(name, 0.0)))
        for name in STRATEGY_NAMES
    ]
    regime_allocator = None
    if regime_aware and REGIME_TOOLS_AVAILABLE and RegimeAllocator is not None:
        regime_allocator = RegimeAllocator(enabled=True)
        logger.info("[OK] Regime-aware allocation enabled for walk-forward (live mode)")
    return StrategyPortfolio(
        strategies=strategies,
        enable_risk_monitor=False,
        use_paper_trading=False,
        paper=False,
        regime_allocator=regime_allocator,
    )


def apply_regime_at_date(weights: Dict[str, float], date: pd.Timestamp,
                         lookback_days: int = 400) -> Dict[str, float]:
    """
    在指定日期用当时可见的数据检测市场状态，并返回 regime-aware 调整后的权重。

    用于 walk-forward OOS：在每个 test 窗口开始时（train_end）检测 regime，
    避免使用 test 窗口内的未来数据。
    """
    if not REGIME_TOOLS_AVAILABLE:
        return dict(weights)
    try:
        end = date.strftime('%Y-%m-%d')
        start = (date - pd.Timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        price_df, market_df = prepare_backtest_data_qc(TICKERS, start, end, resolution='daily')
        if price_df is None or len(price_df) == 0:
            logger.warning(f"[REGIME_OOS] No data for {end}, keeping static weights")
            return dict(weights)
        vix = None
        if market_df is not None and 'VIX' in market_df.columns:
            vix = float(market_df['VIX'].iloc[-1])
        regime = regime_detect(price_df, vix)
        allocator = RegimeAllocator(enabled=True)
        adjusted = allocator.allocate(regime, weights)
        logger.info(f"[REGIME_OOS] date={end}, regime={regime}, adjusted weights: {adjusted}")
        return adjusted
    except Exception as e:
        logger.warning(f"[REGIME_OOS] Failed to apply regime at {date}: {e}")
        return dict(weights)


def resolve_fixed_weights(spec: str) -> Dict[str, float]:
    """解析固定权重：'equal' 或 'g:0.30,s:0.25,m:0.10,v:0.20,q:0.15' 形式。"""
    if spec == 'equal':
        return {name: 1.0 / len(STRATEGY_NAMES) for name in STRATEGY_NAMES}
    alias = {'g': 'growth', 's': 'sector_rotation', 'm': 'momentum',
             'v': 'value', 'q': 'quality'}
    weights = {}
    for part in spec.split(','):
        key, val = part.split(':')
        name = alias.get(key.strip(), key.strip())
        if name not in STRATEGY_NAMES:
            raise ValueError(f"未知策略名: {name}")
        weights[name] = float(val)
    for name in STRATEGY_NAMES:
        weights.setdefault(name, 0.0)
    return weights


def generate_weight_grid(step: int = 10, min_weight: int = 5) -> List[Dict[str, float]]:
    """生成粗粒度权重组合（百分比，总和 100，每项 >= min_weight）。

    以 step 为单位把 100 拆成 len(STRATEGY_NAMES) 份的有序组合
    （compositions），避免步长取模导致总和无法凑齐的问题。
    """
    n = len(STRATEGY_NAMES)
    units_total = 100 // step
    units_min = min_weight // step
    if units_min * n > units_total:
        raise ValueError(f"min_weight={min_weight} 过大，无法凑成总和 100")
    combos = []

    def _rec(remaining_units: int, slots: int, acc: List[int]):
        if slots == 1:
            if remaining_units >= units_min:
                combos.append({name: w * step / 100.0
                               for name, w in zip(STRATEGY_NAMES, acc + [remaining_units])})
            return
        for u in range(units_min, remaining_units - units_min * (slots - 1) + 1):
            _rec(remaining_units - u, slots - 1, acc + [u])

    _rec(units_total, n, [])
    return combos


def backtest_portfolio(weights: Dict[str, float], start: str, end: str,
                       regime_aware: bool = False) -> Optional[pd.DataFrame]:
    """运行组合回测，返回 NAV 曲线 DataFrame（date, nav）。失败返回 None。"""
    try:
        portfolio = build_portfolio(weights, regime_aware=regime_aware)
        result = portfolio.run_backtest(start, end)
        if result is None or len(result) == 0:
            return None
        if 'date' not in result.columns:
            return None
        nav_col = 'nav_after_cost' if 'nav_after_cost' in result.columns else 'nav'
        if nav_col not in result.columns:
            return None
        df = result[['date', nav_col]].copy()
        df['date'] = pd.to_datetime(df['date'])
        return df
    except Exception as e:
        logger.error(f"  组合回测失败 (weights={weights}): {e}")
        return None


def portfolio_metrics(result: pd.DataFrame) -> Optional[dict]:
    """从 (date, nav) 曲线计算指标（与 optimize_portfolio_weights.metrics 一致风格）。"""
    nav_col = 'nav_after_cost' if 'nav_after_cost' in result.columns else 'nav'
    nav = result[nav_col].dropna()
    if len(nav) < 2:
        return None
    returns = nav.pct_change().dropna()
    years = (result['date'].iloc[-1] - result['date'].iloc[0]).days / 365.25
    if years <= 0:
        return None
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
    periods = max(1, int(round(len(result) / years)))
    vol = returns.std() * (periods ** 0.5)
    sharpe = cagr / vol if vol > 0 else 0
    maxdd = ((nav / nav.cummax()) - 1).min()
    return {'cagr': float(cagr), 'sharpe': float(sharpe), 'maxdd': float(maxdd),
            'vol': float(vol)}


def optimize_weights(train_start: str, train_end: str, metric: str = 'sharpe',
                     max_combos: Optional[int] = None,
                     regime_aware: bool = False) -> Tuple[Dict[str, float], List[dict]]:
    """在 train 窗口内做权重 sweep，返回最优权重与全部结果。"""
    combos = generate_weight_grid()
    if max_combos is not None and len(combos) > max_combos:
        # 均匀抽样限制组合数（避免超长优化）
        idx = np.linspace(0, len(combos) - 1, max_combos).astype(int)
        combos = [combos[i] for i in sorted(set(idx))]
    logger.info(f"  train 窗口权重优化: {len(combos)} 个组合, metric={metric}")

    results = []
    best_weights, best_score = None, -np.inf
    for i, weights in enumerate(combos, 1):
        logger.info(f"  [{i}/{len(combos)}] {weights}")
        result = backtest_portfolio(weights, train_start, train_end, regime_aware=regime_aware)
        if result is None:
            continue
        m = portfolio_metrics(result)
        if m is None:
            continue
        row = {'weights': weights}
        row.update(m)
        results.append(row)
        score = m.get(metric, -np.inf)
        if score > best_score:
            best_score = score
            best_weights = weights
        logger.info(f"    CAGR={m['cagr']:.2%} Sharpe={m['sharpe']:.3f} MaxDD={m['maxdd']:.2%}")

    if best_weights is None:
        logger.warning("  train 窗口优化失败，回退到等权重")
        best_weights = resolve_fixed_weights('equal')
    return best_weights, results


def run_walk_forward(
    start: str,
    end: str,
    train_years: int,
    test_months: int,
    fixed_weights: Optional[Dict[str, float]] = None,
    optimize: bool = False,
    optimize_metric: str = 'sharpe',
    optimize_max_combos: Optional[int] = None,
    output_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'optimization_walkforward_portfolio.json'),
    regime_aware: bool = False,
):
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)

    windows = generate_windows(start_date, end_date, train_years, test_months)
    if not windows:
        logger.error("未生成有效的 walk-forward 窗口，请检查日期参数")
        sys.exit(1)

    logger.info(f"计划运行 {len(windows)} 个 walk-forward 窗口 "
                f"(mode={'optimize' if optimize else 'fixed weights'})")

    all_returns = []
    per_window_records = []

    for i, (train_start, train_end, test_start, test_end) in enumerate(windows, 1):
        logger.info(
            f"\n窗口 {i}/{len(windows)}: train {train_start.date()}~{train_end.date()}, "
            f"test {test_start.date()}~{test_end.date()}"
        )

        # 1) train 阶段：确定本窗口使用的权重
        if optimize:
            weights, train_results = optimize_weights(
                str(train_start.date()), str(train_end.date()),
                metric=optimize_metric, max_combos=optimize_max_combos,
                regime_aware=regime_aware)
        else:
            weights = dict(fixed_weights)
            train_results = []

        logger.info(f"  窗口 {i} 使用权重: {weights}")

        # 1.5) Regime-aware OOS: 在 train_end 用当时可见数据检测 regime，调整 test 窗口权重
        if regime_aware:
            weights = apply_regime_at_date(weights, train_end)

        # 2) test 阶段：回测区间从 train_start 开始（保证预热），再切片到 test 区间
        result = backtest_portfolio(weights, str(train_start.date()), str(test_end.date()),
                                    regime_aware=False)
        if result is None:
            logger.warning(f"窗口 {i} 没有返回结果，跳过")
            continue

        result = result[(result['date'] >= test_start) & (result['date'] <= test_end)]
        if len(result) == 0:
            logger.warning(f"窗口 {i} 在测试区间内没有调仓记录，跳过")
            continue

        nav_col = 'nav_after_cost' if 'nav_after_cost' in result.columns else 'nav'
        nav = result[nav_col].dropna()
        if len(nav) < 2:
            logger.warning(f"窗口 {i} 数据点不足，跳过")
            continue

        dates = pd.to_datetime(result['date']).iloc[1:]
        rets = pd.Series(nav.pct_change().dropna().values, index=dates)
        all_returns.append(rets)

        rec = {
            'window': i,
            'train_start': str(train_start.date()),
            'train_end': str(train_end.date()),
            'test_start': str(test_start.date()),
            'test_end': str(test_end.date()),
            'weights': weights,
            'final_nav': float(nav.iloc[-1]),
            'total_return': float((1 + rets).prod() - 1),
        }
        if train_results:
            # 只保留 top-5 train 结果，控制 JSON 体积
            top = sorted(train_results, key=lambda r: r.get(optimize_metric, -np.inf),
                         reverse=True)[:5]
            rec['train_top5'] = top
        per_window_records.append(rec)

        logger.info(f"  窗口 {i} OOS: return={rec['total_return']:.2%}, "
                    f"final_nav={rec['final_nav']:.4f}")

        # 增量保存，防止长任务中断丢失全部进度
        _save_results(output_path, {}, per_window_records)

    if not all_returns:
        logger.error("没有产生任何 test 窗口收益，无法聚合")
        sys.exit(1)

    combined_returns = pd.concat(all_returns)
    overall = compute_metrics(combined_returns)

    # 打印各窗口结果
    logger.info("\n" + "=" * 60)
    logger.info("各窗口 OOS 结果 (portfolio)")
    logger.info("=" * 60)
    for rec in per_window_records:
        logger.info(
            f"窗口 {rec['window']}: {rec['test_start']} ~ {rec['test_end']}, "
            f"return={rec['total_return']:.2%}, weights={rec['weights']}"
        )

    # 打印整体指标
    logger.info("\n" + "=" * 60)
    logger.info("Walk-forward 聚合结果 (portfolio OOS)")
    logger.info("=" * 60)
    logger.info(f"  总周期数: {overall.get('n_periods', 0)}")
    logger.info(f"  年化频率: {overall.get('periods_per_year', 0):.1f} 期/年")
    logger.info(f"  总收益:   {overall.get('total_return', 0):.2%}")
    logger.info(f"  CAGR:     {overall.get('cagr', 0):.2%}")
    logger.info(f"  Vol:      {overall.get('volatility', 0):.2%}")
    logger.info(f"  Sharpe:   {overall.get('sharpe', 0):.3f}")
    logger.info(f"  MaxDD:    {overall.get('max_drawdown', 0):.2%}")
    logger.info("=" * 60)

    summary = {
        'mode': ('regime_aware_' + ('optimize' if optimize else 'fixed')) if regime_aware else ('optimize' if optimize else 'fixed'),
        'optimize_metric': optimize_metric if optimize else None,
        'start': start,
        'end': end,
        'train_years': train_years,
        'test_months': test_months,
        'n_windows': len(per_window_records),
        'aggregate': {k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                      for k, v in overall.items()},
        'windows': per_window_records,
    }
    _save_results(output_path, summary, per_window_records)
    logger.info(f"\n结果已保存到 {output_path}")

    return overall, per_window_records, combined_returns


def _save_results(output_path: str, summary: dict, windows: List[dict]):
    """增量/最终保存。summary 为空 dict 时只保存 windows。"""
    payload = summary if summary else {'windows': windows, 'partial': True}
    try:
        with open(output_path, 'w') as f:
            json.dump(payload, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"保存结果失败: {e}")


def main():
    parser = argparse.ArgumentParser(description='StrategyPortfolio walk-forward / OOS backtest')
    parser.add_argument('--start', type=str, default='2020-01-01',
                        help='总起始日期 YYYY-MM-DD')
    parser.add_argument('--end', type=str, default='2024-12-31',
                        help='总结束日期 YYYY-MM-DD')
    parser.add_argument('--train-years', type=int, default=2,
                        help='训练窗口长度（年）')
    parser.add_argument('--test-months', type=int, default=6,
                        help='测试窗口长度（月）')
    parser.add_argument('--weights', type=str, default='equal',
                        help="固定权重: 'equal' 或 'g:0.30,s:0.25,m:0.10,v:0.20,q:0.15'")
    parser.add_argument('--optimize', action='store_true',
                        help='在每个 train 窗口内做权重 sweep，用最优权重跑 test')
    parser.add_argument('--weights-optimize-metric', type=str, default='sharpe',
                        choices=['sharpe', 'cagr'],
                        help='train 窗口权重优化目标')
    parser.add_argument('--optimize-max-combos', type=int, default=None,
                        help='限制 train 窗口内 sweep 的组合数（均匀抽样）')
    parser.add_argument('--output', type=str,
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             'optimization_walkforward_portfolio.json'),
                        help='结果输出 JSON 路径')
    parser.add_argument('--smoke-test', action='store_true',
                        help='冒烟测试：验证窗口生成/权重解析/网格生成，不运行回测')
    parser.add_argument('--regime-aware', action='store_true',
                        help='启用 regime-aware 子策略权重分配')
    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
        return

    fixed_weights = resolve_fixed_weights(args.weights)
    if not args.optimize:
        total = sum(fixed_weights.values())
        if total <= 0:
            logger.error("固定权重总和必须 > 0")
            sys.exit(1)

    run_walk_forward(
        start=args.start,
        end=args.end,
        train_years=args.train_years,
        test_months=args.test_months,
        fixed_weights=fixed_weights,
        optimize=args.optimize,
        optimize_metric=args.weights_optimize_metric,
        optimize_max_combos=args.optimize_max_combos,
        output_path=args.output,
        regime_aware=args.regime_aware,
    )


def smoke_test():
    """不跑回测的冒烟测试：验证各组件可正常构造与调用。"""
    logger.info("=== smoke test ===")

    # 1) 窗口生成
    windows = generate_windows(pd.Timestamp('2020-01-01'), pd.Timestamp('2024-12-31'), 2, 6)
    assert len(windows) > 0, "窗口生成为空"
    logger.info(f"[OK] generate_windows: {len(windows)} windows")

    # 2) 权重解析
    w_equal = resolve_fixed_weights('equal')
    assert abs(sum(w_equal.values()) - 1.0) < 1e-9
    w_custom = resolve_fixed_weights('g:0.30,s:0.25,m:0.10,v:0.20,q:0.15')
    assert abs(sum(w_custom.values()) - 1.0) < 1e-9
    assert set(w_custom.keys()) == set(STRATEGY_NAMES)
    logger.info(f"[OK] resolve_fixed_weights: equal & custom OK")

    # 3) 权重网格
    grid = generate_weight_grid()
    assert len(grid) > 0
    assert all(abs(sum(w.values()) - 1.0) < 1e-9 for w in grid)
    logger.info(f"[OK] generate_weight_grid: {len(grid)} combos")

    # 4) 组合构造（不跑回测）
    portfolio = build_portfolio(w_equal)
    total_w = sum(item['weight'] for item in portfolio.strategies)
    assert abs(total_w - 1.0) < 1e-9, f"权重未归一化: {total_w}"
    names = [item['name'] for item in portfolio.strategies]
    assert names == STRATEGY_NAMES
    logger.info(f"[OK] build_portfolio: {names}, weights normalized to {total_w:.6f}")

    # 5) compute_metrics 空输入健壮性
    assert compute_metrics(pd.Series(dtype=float)) == {}
    logger.info("[OK] compute_metrics handles empty input")

    logger.info("=== smoke test PASSED ===")


if __name__ == '__main__':
    main()
