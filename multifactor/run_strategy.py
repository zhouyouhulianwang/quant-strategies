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

if __name__ == '__main__':
    cleanup_runtime_files()

    parser = argparse.ArgumentParser(description='V14 MultiFactor Strategy')
    parser.add_argument('--backtest', action='store_true', help='Run backtest')
    parser.add_argument('--live', action='store_true', help='Run live')
    parser.add_argument('--real-data', action='store_true', help='Use real data')
    parser.add_argument('--paper', action='store_true', help='Use Paper Trading')
    parser.add_argument('--start', type=str, help='Start date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End date YYYY-MM-DD')

    parser.add_argument('--monitor', action='store_true', help='Enable intraday monitor')
    parser.add_argument('--weight-method', type=str, default='equal',
                       choices=['equal', 'risk_parity', 'momentum_weighted'],
                       help='Weight allocation method')

    args = parser.parse_args()

    # 进入 paper/live 模式需要 alpaca-py SDK
    if (args.paper or args.live) and not ALPACA_AVAILABLE:
        raise RuntimeError(
            "alpaca-py is not installed, cannot enter paper/live mode."
            "Run: pip install alpaca-py"
        )

    # 初始化策略 - 默认使用真实数据，回测模式
    strategy = V14Strategy(
        use_real_data=True,
        use_paper_trading=args.paper,
        enable_risk_monitor=True,
        enable_intraday_monitor=args.monitor,
        weight_method=args.weight_method
    )

    # 检查数据可用性
    if not strategy.use_real_data:
        logger.error("[ERROR] Real data unavailable, please check network connection or data source configuration")
        logger.error("   Please configure QuantConnect Lean CLI")
        logger.error("   Backtest aborted, mock data not used")
        exit(1)

    if args.backtest or not args.live:
        # 运行回测
        result = strategy.run_backtest(args.start, args.end)
        if len(result) == 0:
            logger.error("[ERROR] Backtest failed: no data or insufficient data")
            exit(1)

    if args.live:
        # 检查是否启用了 Paper Trading
        if not strategy.use_paper_trading:
            logger.error("[ERROR] Live mode requires --paper to enable Paper Trading")
            logger.error("   Run: python run_strategy.py --live --paper")
            exit(1)

        # 全自动实盘再平衡
        strategy.run_live_rebalance()

    # 打印状态
    status = strategy.get_status()
    logger.info(f"\nStrategy status: {status}")
