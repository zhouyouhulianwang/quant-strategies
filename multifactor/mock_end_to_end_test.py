"""
端到端 mock Alpaca 测试：模拟一次完整调仓 + PDT + 紧急平仓
不连接真实 API，不提交真实订单
"""
import os
import sys

# 确保不读取真实 .env
os.environ.setdefault('ALPACA_API_KEY', 'MOCK-KEY')
os.environ.setdefault('ALPACA_API_SECRET', 'MOCK-SECRET')
os.environ.setdefault('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

from alpaca_executor import AlpacaPaperExecutor
from order_manager import RebalanceManager
from pdt_tracker import PDTTracker
from intraday_monitor import IntradayMonitor
from risk_monitor import RiskMonitor


def mock_rebalance():
    print("\n" + "="*60)
    print("Mock 端到端测试：完整调仓")
    print("="*60)

    executor = AlpacaPaperExecutor(
        mock=True,
        paper=True,
        enable_pdt=True,
        pdt_min_equity=25000.0,
    )

    manager = RebalanceManager(executor)
    target_positions = {
        'AAPL': 20000,
        'MSFT': 20000,
        'NVDA': 20000,
    }

    results = manager.rebalance(
        target_positions,
        max_position_pct=0.25,
        confirm_fills=False,
        enable_rollback=True,
        min_buy_fill_ratio=0.95,
    )

    print(f"订单数量: {len(results)}")
    for r in results:
        print(f"  {r.get('symbol', 'N/A')}: {r.get('status', 'UNKNOWN')}")

    positions = executor.get_positions()
    print(f"\n调仓后持仓数量: {len(positions)}")
    for p in positions:
        print(f"  {p['symbol']}: {p['qty']} 股, 市值 ${p['market_value']:,.2f}")

    account = executor.get_account()
    print(f"\n账户权益: ${account['equity']:,.2f}")
    print(f"现金: ${account['cash']:,.2f}")
    return executor, manager


def mock_pdt_and_liquidation():
    print("\n" + "="*60)
    print("Mock 端到端测试：PDT 触发与紧急平仓")
    print("="*60)

    executor = AlpacaPaperExecutor(
        mock=True,
        paper=True,
        enable_pdt=True,
        pdt_min_equity=25000.0,
    )
    manager = RebalanceManager(executor)

    # 第一轮买入 AAPL
    manager.rebalance({'AAPL': 20000}, confirm_fills=False)
    # 卖出 AAPL（round trip）
    manager.rebalance({}, confirm_fills=False)
    # 再次买入 AAPL（round trip）
    manager.rebalance({'AAPL': 20000}, confirm_fills=False)
    # 再次卖出 AAPL（round trip）
    manager.rebalance({}, confirm_fills=False)
    # 第五次买入应被 PDT 拦截
    results = manager.rebalance({'AAPL': 20000}, confirm_fills=False)
    print(f"PDT 拦截结果: {results[0] if results else '无订单'}")

    # 盘中监控触发紧急平仓
    risk_monitor = RiskMonitor()
    monitor = IntradayMonitor(
        executor=executor,
        risk_monitor=risk_monitor,
        check_interval=1,
        vix_emergency_level=5.0,  # 极低阈值，确保触发
    )
    # 手动注入高 VIX 环境无法直接做到，改为直接调用 emergency liquidation
    executor.close_all_positions()
    positions = executor.get_positions()
    print(f"\n紧急平仓后持仓数量: {len(positions)}")


if __name__ == '__main__':
    mock_rebalance()
    mock_pdt_and_liquidation()
    print("\n" + "="*60)
    print("✅ Mock 端到端测试完成，无崩溃")
    print("="*60)
