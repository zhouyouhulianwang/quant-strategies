"""
V14 MultiFactor Strategy - 入口封装

本文件现在是 V14Strategy 的薄入口点/包装器。
具体实现已迁移至 strategies/v14.py，本文件仅保留：
1. 顶层向后兼容的 V14Strategy 导出
2. 命令行入口
3. 启动时运行时文件清理（保留最近 30 天订单/告警/图表）
"""

import argparse
import logging
import sys

from logging_config import setup_logging
from runtime_cleanup import cleanup_old_files
from strategies.v14 import V14Strategy
from alpaca_executor import ALPACA_AVAILABLE

# 向后兼容：保留顶层导入
__all__ = ['V14Strategy']

setup_logging()
logger = logging.getLogger('run_strategy')


def cleanup_runtime_files():
    """启动时清理超过 30 天的订单、告警和图表文件。"""
    try:
        for directory in ['orders', 'alerts', 'charts']:
            cleanup_old_files(
                directory,
                max_age_days=30,
                max_size_mb=1024,
            )
        logger.info('Runtime files cleanup completed (orders/alerts/charts kept for 30 days)')
    except Exception as e:
        logger.warning(f"Runtime cleanup failed: {e}")


# ============================================================
# 主入口
# ============================================================

def main(argv=None):
    """命令行入口。

    参数:
        argv: 可选参数列表，用于测试注入；默认使用 sys.argv。
    """
    cleanup_runtime_files()

    parser = argparse.ArgumentParser(description='V14 MultiFactor Strategy')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--backtest', action='store_true', help='Run backtest using real data')
    group.add_argument('--paper', action='store_true', help='Run Alpaca Paper Trading (real Alpaca paper environment)')
    group.add_argument('--live', action='store_true', help='Run Alpaca Live Trading (real money)')
    group.add_argument('--mock', action='store_true', help='Run local simulation with mock data (no real API)')
    parser.add_argument('--real-data', action='store_true', help='Use real data')
    parser.add_argument('--start', type=str, help='Start date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End date YYYY-MM-DD')

    parser.add_argument('--monitor', action='store_true', help='Enable intraday monitor')
    parser.add_argument('--weight-method', type=str, default='equal',
                       choices=['equal', 'risk_parity', 'momentum_weighted'],
                       help='Weight allocation method')
    parser.add_argument('--confirm-live', action='store_true',
                       help='Explicitly confirm live trading (required with --live)')

    args = parser.parse_args(argv)

    # --live 必须显式确认，避免误触实盘
    if args.live and not args.confirm_live:
        parser.error('--live requires --confirm-live to avoid accidental real-money trading')

    # 进入 paper/live 模式需要 alpaca-py SDK
    if (args.paper or args.live) and not ALPACA_AVAILABLE:
        raise RuntimeError(
            "alpaca-py is not installed, cannot enter paper/live mode."
            "Run: pip install alpaca-py"
        )

    # 初始化策略：paper/live/mock 明确区分
    use_paper_trading = args.paper or args.live
    paper = args.paper  # True=paper, False=live
    strategy_kwargs = {
        'use_real_data': True,
        'enable_risk_monitor': True,
        'enable_intraday_monitor': args.monitor,
        'weight_method': args.weight_method,
    }
    if use_paper_trading:
        strategy_kwargs['use_paper_trading'] = True
        strategy_kwargs['paper'] = paper
    if args.mock:
        # 本地模拟使用 mock 数据，不连接任何真实 API
        strategy_kwargs['use_real_data'] = False

    strategy = V14Strategy(**strategy_kwargs)

    # 检查数据可用性（backtest/paper/live 默认需要真实数据，mock 使用本地数据）
    if not strategy.use_real_data and not args.mock:
        logger.error("[ERROR] Real data unavailable, please check network connection or data source configuration")
        logger.error("   Please configure QuantConnect Lean CLI")
        logger.error("   Backtest aborted, mock data not used")
        return 1

    if args.backtest or args.mock:
        # 运行回测 / 本地模拟
        result = strategy.run_backtest(args.start, args.end)
        if len(result) == 0:
            logger.error("[ERROR] Backtest / mock simulation failed: no data or insufficient data")
            return 1

    if args.paper or args.live:
        # 连接真实 Alpaca 环境并执行调仓
        mode = 'PAPER' if args.paper else 'LIVE'
        logger.info(f"[MODE] Running Alpaca {mode} trading (real environment)")
        strategy.run_live_rebalance()

    # 打印状态
    status = strategy.get_status()
    logger.info(f"\nStrategy status: {status}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
