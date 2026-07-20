#!/usr/bin/env python3
"""
Walk-forward / out-of-sample backtest for V14 MultiFactor strategy.

将完整区间切分为多个 rolling train/test 窗口：
  - train 窗口用于训练/参数选择
  - test 窗口完全独立，用于产生 OOS 收益

用法示例:
    python3 walk_forward_test.py --start 2020-01-01 --end 2024-12-31 \\
        --train-years 2 --test-months 6 --weight-method equal
"""

import argparse
import logging
import sys
from typing import List, Tuple

import numpy as np
import pandas as pd

from logging_config import setup_logging
from strategies.v14 import V14Strategy

setup_logging()
logger = logging.getLogger('walk_forward_test')


def generate_windows(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    train_years: int,
    test_months: int,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """生成滚动 train/test 窗口 (train_start, train_end, test_start, test_end)."""
    windows = []
    current = start_date
    step = pd.DateOffset(months=test_months)
    while True:
        train_start = current
        train_end = current + pd.DateOffset(years=train_years) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)
        if test_end > end_date:
            test_end = end_date
        if train_end >= end_date or test_start > end_date:
            break
        windows.append((train_start, train_end, test_start, test_end))
        current = current + step
    return windows


def compute_metrics(returns: pd.Series) -> dict:
    """从收益率序列（支持日/月/季等任意频率）计算年化绩效指标。"""
    if len(returns) == 0 or returns.std() == 0:
        return {}

    total_return = (1 + returns).prod() - 1

    # 根据时间索引推断年化频率；无时序索引则按 252 日年化
    if isinstance(returns.index, pd.DatetimeIndex):
        median_delta = returns.index.to_series().diff().median()
        if pd.isna(median_delta) or median_delta.total_seconds() <= 0:
            periods_per_year = 252.0
            years = len(returns) / 252.0
        else:
            periods_per_year = float(pd.Timedelta(days=365.25) / median_delta)
            years = (returns.index[-1] - returns.index[0]).total_seconds() / (365.25 * 24 * 3600)
    else:
        periods_per_year = 252.0
        years = len(returns) / 252.0

    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
    vol = returns.std() * np.sqrt(periods_per_year)
    sharpe = cagr / vol if vol > 0 else 0.0

    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    max_dd = drawdown.min()

    return {
        'total_return': total_return,
        'cagr': cagr,
        'volatility': vol,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'n_periods': len(returns),
        'periods_per_year': periods_per_year,
        'years': years,
    }


def run_walk_forward(
    start: str,
    end: str,
    train_years: int,
    test_months: int,
    weight_method: str,
    generate_report: bool = True,
):
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)

    windows = generate_windows(start_date, end_date, train_years, test_months)
    if not windows:
        logger.error("未生成有效的 walk-forward 窗口，请检查日期参数")
        sys.exit(1)

    logger.info(f"计划运行 {len(windows)} 个 walk-forward 窗口")

    all_daily_returns = []
    per_window_records = []

    for i, (train_start, train_end, test_start, test_end) in enumerate(windows, 1):
        logger.info(
            f"窗口 {i}/{len(windows)}: train {train_start.date()}~{train_end.date()}, "
            f"test {test_start.date()}~{test_end.date()}"
        )

        strategy = V14Strategy(
            use_real_data=True,
            weight_method=weight_method,
            enable_risk_monitor=True,
        )
        # P0: 回测引擎需要 252 日预热；传入 train_start~test_end 保证足够历史数据，
        # 再按 test_start~test_end 切片得到 OOS 结果。
        result = strategy.run_backtest(
            str(train_start.date()),
            str(test_end.date()),
            generate_report=generate_report,
        )

        if result is None or len(result) == 0:
            logger.warning(f"窗口 {i} 没有返回结果，跳过")
            continue

        if 'date' not in result.columns:
            logger.warning(f"窗口 {i} 结果缺少 date 列，跳过")
            continue

        result['date'] = pd.to_datetime(result['date'])
        result = result[(result['date'] >= test_start) & (result['date'] <= test_end)]

        if result is None or len(result) == 0:
            logger.warning(f"窗口 {i} 在测试区间内没有调仓记录，跳过")
            continue

        nav_col = 'nav_after_cost' if 'nav_after_cost' in result.columns else 'nav'
        if nav_col not in result.columns:
            logger.warning(f"窗口 {i} 结果缺少 NAV 列，跳过")
            continue

        nav = result[nav_col].dropna()
        if len(nav) < 2:
            logger.warning(f"窗口 {i} 数据点不足，跳过")
            continue

        # 保留调仓日期作为收益率索引，以便正确推断频率和年化
        dates = pd.to_datetime(result['date']).iloc[1:]
        daily_rets = pd.Series(nav.pct_change().dropna().values, index=dates)
        all_daily_returns.append(daily_rets)

        per_window_records.append({
            'window': i,
            'test_start': test_start.date(),
            'test_end': test_end.date(),
            'weight_method': weight_method,
            'final_nav': nav.iloc[-1],
            'total_return': (1 + daily_rets).prod() - 1,
        })

    if not all_daily_returns:
        logger.error("没有产生任何 test 窗口收益，无法聚合")
        sys.exit(1)

    combined_returns = pd.concat(all_daily_returns)
    overall = compute_metrics(combined_returns)

    # 打印各窗口结果
    logger.info("\n" + "=" * 60)
    logger.info("各窗口 OOS 结果")
    logger.info("=" * 60)
    for rec in per_window_records:
        logger.info(
            f"窗口 {rec['window']}: {rec['test_start']} ~ {rec['test_end']}, "
            f"method={rec['weight_method']}, final_nav={rec['final_nav']:.4f}, "
            f"return={rec['total_return']:.2%}"
        )

    # 打印整体指标
    logger.info("\n" + "=" * 60)
    logger.info("Walk-forward 聚合结果")
    logger.info("=" * 60)
    logger.info(f"  总周期数: {overall.get('n_periods', 0)}")
    logger.info(f"  年化频率: {overall.get('periods_per_year', 0):.1f} 期/年")
    logger.info(f"  总收益:   {overall.get('total_return', 0):.2%}")
    logger.info(f"  CAGR:     {overall.get('cagr', 0):.2%}")
    logger.info(f"  Vol:      {overall.get('volatility', 0):.2%}")
    logger.info(f"  Sharpe:   {overall.get('sharpe', 0):.3f}")
    logger.info(f"  MaxDD:    {overall.get('max_drawdown', 0):.2%}")
    logger.info("=" * 60)

    return overall, per_window_records, combined_returns


def main():
    parser = argparse.ArgumentParser(description='V14 Walk-forward / OOS backtest')
    parser.add_argument('--start', type=str, default='2020-01-01',
                        help='总起始日期 YYYY-MM-DD')
    parser.add_argument('--end', type=str, default='2024-12-31',
                        help='总结束日期 YYYY-MM-DD')
    parser.add_argument('--train-years', type=int, default=2,
                        help='训练窗口长度（年）')
    parser.add_argument('--test-months', type=int, default=6,
                        help='测试窗口长度（月）')
    parser.add_argument('--weight-method', type=str, default='momentum_weighted',
                        choices=['equal', 'risk_parity', 'momentum_weighted'],
                        help='权重分配方法')
    parser.add_argument('--no-report', action='store_true',
                        help='跳过每个窗口的可视化报告生成，节省磁盘')
    args = parser.parse_args()

    run_walk_forward(
        start=args.start,
        end=args.end,
        train_years=args.train_years,
        test_months=args.test_months,
        weight_method=args.weight_method,
        generate_report=not args.no_report,
    )


if __name__ == '__main__':
    main()
