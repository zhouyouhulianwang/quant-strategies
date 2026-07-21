#!/usr/bin/env python3
"""
生成目标持仓清单并与当前 Paper 持仓对比（只读，不发单）。

用法:
    python3 generate_target_positions.py
"""

import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from logging_config import setup_logging
from strategies.v14 import MultiFactorStrategy

setup_logging()
logger = logging.getLogger('generate_target_positions')


def main():
    strategy = MultiFactorStrategy(
        use_real_data=True,
        use_paper_trading=True,
        paper=True,
        enable_risk_monitor=True,
        weight_method='momentum_weighted',
    )

    if not strategy.executor:
        logger.error("[ERROR] Alpaca executor not initialized")
        return 1

    # 获取当前 paper 账户与持仓
    account = strategy.executor.get_account()
    if not account:
        logger.error("[ERROR] Cannot get paper account")
        return 1

    portfolio_value = account['portfolio_value']
    cash = account['cash']
    positions = {p['symbol']: p for p in strategy.executor.get_positions()}

    # 生成目标持仓（不发单）
    target_positions = strategy.generate_signals(live_mode=True)
    if not target_positions:
        logger.error("[ERROR] Failed to generate target positions")
        return 1

    total_target = sum(target_positions.values())

    print("\n" + "=" * 60)
    print("目标持仓清单（基于真实数据，未发单）")
    print("=" * 60)
    print(f"生成时间: {datetime.now(ZoneInfo('America/New_York')).isoformat()}")
    print(f"账户总值: ${portfolio_value:,.2f}")
    print(f"现金: ${cash:,.2f}")
    print(f"当前持仓数: {len(positions)}")
    print(f"目标持仓数: {len(target_positions)}")
    print(f"目标持仓总市值: ${total_target:,.2f} ({total_target/portfolio_value:.1%})")
    print()

    # 合并 symbol 集合
    all_symbols = set(positions.keys()) | set(target_positions.keys())

    # 计算差异
    diffs = []
    for symbol in sorted(all_symbols):
        current_value = positions.get(symbol, {}).get('market_value', 0.0)
        current_qty = positions.get(symbol, {}).get('qty', 0)
        target_value = target_positions.get(symbol, 0.0)
        diff_value = target_value - current_value
        diffs.append({
            'symbol': symbol,
            'current_value': current_value,
            'current_qty': current_qty,
            'target_value': target_value,
            'diff_value': diff_value,
        })

    # 排序：按目标市值降序
    diffs.sort(key=lambda x: x['target_value'], reverse=True)

    print(f"{'Symbol':<8} {'CurrentQty':>10} {'Current$':>12} {'Target$':>12} {'Diff$':>12} {'Action':>8}")
    print("-" * 68)
    for d in diffs:
        symbol = d['symbol']
        current_qty = d['current_qty']
        current_value = d['current_value']
        target_value = d['target_value']
        diff_value = d['diff_value']
        if abs(diff_value) < 1.0:
            action = 'HOLD'
        elif diff_value > 0:
            action = 'BUY'
        else:
            action = 'SELL'
        print(f"{symbol:<8} {current_qty:>10} ${current_value:>10,.2f} ${target_value:>10,.2f} ${diff_value:>10,.2f} {action:>8}")

    print("-" * 68)
    total_buy = sum(d['diff_value'] for d in diffs if d['diff_value'] > 1.0)
    total_sell = sum(-d['diff_value'] for d in diffs if d['diff_value'] < -1.0)
    print(f"预计买入总额: ${total_buy:,.2f}")
    print(f"预计卖出总额: ${total_sell:,.2f}")
    print(f"净调仓金额: ${total_buy - total_sell:,.2f}")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
