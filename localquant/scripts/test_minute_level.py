"""分钟级回测测试 - AdaptiveMomentumV3.1"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from strategies.adaptive_momentum_v3 import AdaptiveMomentumV3

print("="*60)
print("Minute-Level Backtest Test")
print("="*60)

# 使用小标的集快速测试
test_symbols = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'SPY']

# 短时间范围（1周）用于分钟级测试
start = datetime(2024, 1, 1)
end = datetime(2024, 1, 10)  # 10天

dm = DataManager(cache_dir='./data_cache')

print(f"\nDownloading 15m data for {test_symbols}...")
print("(Note: yfinance 15m data限制60天, 1m数据限制7天)")
for sym in test_symbols:
    try:
        data = dm.get_data(sym, start, end, '15m', 'yahoo')
        print(f"  {sym}: {len(data)} rows (15m)")
        if len(data) > 0:
            print(f"    Date range: {data.index[0]} to {data.index[-1]}")
    except Exception as e:
        print(f"  {sym}: FAILED - {e}")

print("\nPreparing multi-symbol data...")
multi_data = dm.get_multi_data(test_symbols, start, end, '15m')
print(f"Multi-data shape: {multi_data.shape}")

if len(multi_data) == 0:
    print("\n⚠ No minute data available. Falling back to daily for demo.")
    print("(Minute data requires: 1) yfinance supports it, 2) within 60 days for 15m)")
    
    # 回退到日线测试
    start = datetime(2024, 1, 1)
    end = datetime(2024, 3, 31)
    multi_data = dm.get_multi_data(test_symbols, start, end, '1d')
    print(f"Daily data shape: {multi_data.shape}")
    
    strategy = AdaptiveMomentumV3(symbols=test_symbols)
    strategy.max_position_pct = 0.10
    strategy.rebalance_freq = 10  # 每10天（在日线中）
    strategy.max_stocks = 3
else:
    # 分钟级回测
    strategy = AdaptiveMomentumV3(symbols=test_symbols)
    strategy.max_position_pct = 0.10
    # 在分钟级中，rebalance_freq 需要调整
    # 如果是15m数据，每天约26个bar（6.5小时交易），10天 = 260 bars
    strategy.rebalance_freq = 260  # 约10个交易日
    strategy.max_stocks = 3

engine = BacktestEngine(
    initial_cash=100000.0,
    commission_rate=0.001,
    start_date=start,
    end_date=end
)
engine.set_data(multi_data)
engine.set_strategy(strategy)

print("\nRunning backtest...")
results = engine.run()

metrics = AnalyticsEngine.calculate_metrics(
    results['returns'],
    results['equity_curve'],
    results['trades'],
    engine.initial_cash
)

AnalyticsEngine.print_report(metrics)

print(f"\n✓ Minute-level test complete!")
print(f"  Bars: {len(results['equity_curve'])}")
print(f"  Trades: {len(results['trades'])}")
