"""
Multi-Strategy Portfolio - 命令行入口

支持：
- 组合回测
- 每个子策略单独回测
- Paper/Live 组合调仓

示例:
    python3 run_multi_strategy.py --backtest --start 2020-01-01 --end 2024-01-01
    python3 run_multi_strategy.py --paper
    python3 run_multi_strategy.py --individual --backtest
"""

import argparse
import logging
import sys
from datetime import datetime

from logging_config import setup_logging
from runtime_cleanup import cleanup_old_files
from strategies.v14 import MultiFactorStrategy
from strategies.momentum import MomentumStrategy
from strategies.value import ValueStrategy
from strategies.quality import QualityStrategy
from strategies.growth import GrowthStrategy
from strategies.sector_rotation import SectorRotationStrategy
from strategies.portfolio import StrategyPortfolio
from alpaca_executor import ALPACA_AVAILABLE
from config import get_config, reload_config

setup_logging()
logger = logging.getLogger('run_multi_strategy')


def cleanup_runtime_files():
    """启动时清理旧文件。"""
    try:
        for directory in ['orders', 'alerts', 'charts']:
            cleanup_old_files(directory, max_age_days=30, max_size_mb=1024)
        logger.info('Runtime files cleanup completed')
    except Exception as e:
        logger.warning(f"Runtime cleanup failed: {e}")


def build_portfolio(args) -> StrategyPortfolio:
    """根据配置构建多策略组合。"""
    config = reload_config()

    # 默认组合：V14 30% + 高成长 25% + 动量 20% + 价值 15% + 质量 10%
    # 后续可通过 config.json 的 strategies 字段配置
    strategies_config = []
    if hasattr(config, 'strategies') and config.strategies:
        strategies_config = config.strategies
    else:
        strategies_config = [
            {'name': 'multifactor', 'class': 'MultiFactorStrategy', 'weight': 0.20, 'params': {'weight_method': 'momentum_weighted'}},
            {'name': 'growth', 'class': 'GrowthStrategy', 'weight': 0.20, 'params': {'weight_method': 'momentum_weighted'}},
            {'name': 'momentum', 'class': 'MomentumStrategy', 'weight': 0.15, 'params': {'weight_method': 'momentum_weighted'}},
            {'name': 'sector_rotation', 'class': 'SectorRotationStrategy', 'weight': 0.20, 'params': {'top_sectors': 4, 'sector_lookback': 80, 'sector_weight': 0.4}},
            {'name': 'value', 'class': 'ValueStrategy', 'weight': 0.15, 'params': {'weight_method': 'equal'}},
            {'name': 'quality', 'class': 'QualityStrategy', 'weight': 0.10, 'params': {'weight_method': 'risk_parity'}},
        ]

    strategies = []
    for item in strategies_config:
        name = item['name']
        class_name = item['class']
        weight = item['weight']
        params = item.get('params', {})
        params['use_real_data'] = args.real_data

        if class_name == 'MultiFactorStrategy':
            strategy = MultiFactorStrategy(**params)
        elif class_name == 'MomentumStrategy':
            strategy = MomentumStrategy(**params)
        elif class_name == 'ValueStrategy':
            strategy = ValueStrategy(**params)
        elif class_name == 'QualityStrategy':
            strategy = QualityStrategy(**params)
        elif class_name == 'GrowthStrategy':
            strategy = GrowthStrategy(**params)
        elif class_name == 'SectorRotationStrategy':
            strategy = SectorRotationStrategy(**params)
        else:
            raise ValueError(f"Unknown strategy class: {class_name}")
        strategies.append((name, strategy, weight))

    portfolio = StrategyPortfolio(
        strategies=strategies,
        enable_risk_monitor=args.enable_risk_monitor,
        use_paper_trading=args.paper or args.live,
        paper=args.paper,
        config=config,
    )
    return portfolio


def main(argv=None):
    parser = argparse.ArgumentParser(description='Multi-Strategy Portfolio')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--backtest', action='store_true', help='Run portfolio backtest')
    group.add_argument('--individual', action='store_true', help='Run individual strategy backtests')
    group.add_argument('--paper', action='store_true', help='Run Alpaca Paper Trading')
    group.add_argument('--live', action='store_true', help='Run Alpaca Live Trading')
    group.add_argument('--status', action='store_true', help='Print portfolio status')
    parser.add_argument('--real-data', action='store_true', help='Use real data')
    parser.add_argument('--no-real-data', action='store_true', help='Use mock data')
    parser.add_argument('--start', type=str, help='Start date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End date YYYY-MM-DD')
    parser.add_argument('--confirm-live', action='store_true', help='Explicitly confirm live trading')
    parser.add_argument('--enable-risk-monitor', action='store_true', default=True, help='Enable risk monitor')
    parser.add_argument('--disable-risk-monitor', action='store_true', help='Disable risk monitor')
    parser.add_argument('--no-report', action='store_true', help='Skip visualization report')

    args = parser.parse_args(argv)
    cleanup_runtime_files()

    if args.live and not args.confirm_live:
        parser.error('--live requires --confirm-live')

    if (args.paper or args.live) and not ALPACA_AVAILABLE:
        raise RuntimeError("alpaca-py is not installed")

    if args.paper or args.live:
        config = reload_config()
        expected = 'https://paper-api.alpaca.markets' if args.paper else 'https://api.alpaca.markets'
        if config.alpaca_base_url != expected:
            parser.error(
                f"alpaca_base_url mismatch: mode={'paper' if args.paper else 'live'}, "
                f"config={config.alpaca_base_url}, expected={expected}"
            )

    if args.disable_risk_monitor:
        args.enable_risk_monitor = False

    if args.real_data:
        use_real_data = True
    elif args.no_real_data:
        use_real_data = False
    elif args.backtest or args.individual:
        use_real_data = True
    else:
        use_real_data = False
    args.real_data = use_real_data

    portfolio = build_portfolio(args)

    if args.backtest:
        result = portfolio.run_backtest(args.start, args.end)
        if len(result) == 0:
            logger.error("[ERROR] Portfolio backtest failed")
            return 1

    if args.individual:
        results = portfolio.run_individual_backtests(args.start, args.end)
        if not results:
            logger.error("[ERROR] Individual backtests failed")
            return 1

    if args.paper or args.live:
        mode = 'PAPER' if args.paper else 'LIVE'
        logger.info(f"[MODE] Running Alpaca {mode} multi-strategy rebalance")
        portfolio.run_live_rebalance()

    if args.status:
        status = portfolio.get_status()
        logger.info(f"\nPortfolio status: {status}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
