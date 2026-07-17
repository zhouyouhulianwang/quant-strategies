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
        logger.info('运行时文件清理完成（orders/alerts/charts 保留近 30 天）')
    except Exception as e:
        logger.warning(f"运行时清理失败: {e}")


# ============================================================
# 主入口
# ============================================================

if __name__ == '__main__':
    cleanup_runtime_files()

    parser = argparse.ArgumentParser(description='V14 MultiFactor Strategy')
    parser.add_argument('--backtest', action='store_true', help='运行回测')
    parser.add_argument('--live', action='store_true', help='运行实盘')
    parser.add_argument('--real-data', action='store_true', help='使用真实数据')
    parser.add_argument('--paper', action='store_true', help='使用 Paper Trading')
    parser.add_argument('--start', type=str, help='开始日期 YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='结束日期 YYYY-MM-DD')

    parser.add_argument('--monitor', action='store_true', help='启用盘中监控')
    parser.add_argument('--weight-method', type=str, default='equal',
                       choices=['equal', 'risk_parity', 'momentum_weighted'],
                       help='权重分配方法')

    args = parser.parse_args()

    # 进入 paper/live 模式需要 alpaca-py SDK
    if (args.paper or args.live) and not ALPACA_AVAILABLE:
        raise RuntimeError(
            "alpaca-py 未安装，无法进入 paper/live 模式。"
            "请运行: pip install alpaca-py"
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
        logger.error("❌ 真实数据不可用，请检查网络连接或数据源配置")
        logger.error("   请配置 QuantConnect Lean CLI")
        logger.error("   回测已中止，未使用模拟数据")
        exit(1)

    if args.backtest or not args.live:
        # 运行回测
        result = strategy.run_backtest(args.start, args.end)
        if len(result) == 0:
            logger.error("❌ 回测失败: 无数据或数据不足")
            exit(1)

    if args.live:
        # 检查是否启用了 Paper Trading
        if not strategy.use_paper_trading:
            logger.error("❌ 实盘模式需要 --paper 参数启用 Paper Trading")
            logger.error("   运行: python run_strategy.py --live --paper")
            exit(1)

        # 全自动实盘再平衡
        strategy.run_live_rebalance()

    # 打印状态
    status = strategy.get_status()
    logger.info(f"\n策略状态: {status}")
