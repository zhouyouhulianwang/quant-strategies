"""扩展标的池测试 - 50只标的 + 最优参数"""
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
print("50 Symbols + Optimized Parameters Test")
print("="*60)

# 从 strategy_config 获取50只标的
sys.path.insert(0, '/home/pc/.openclaw/workspace/AdaptiveMomentumV3_1')
from strategy_config import SECTOR_MAP

symbols = list(SECTOR_MAP.keys())[:50]
print(f"Testing with {len(symbols)} symbols:")
print(f"  {symbols[:10]}...")

start = datetime(2022, 1, 1)
end = datetime(2024, 12, 31)

dm = DataManager(cache_dir='./data_cache')

print(f"\nDownloading data...")
for sym in symbols:
    try:
        data = dm.get_data(sym, start, end, '1d', 'yahoo')
        print(f"  {sym}: {len(data)} rows", end='\r')
    except Exception as e:
        print(f"  {sym}: FAILED - {e}")
print()

print("Preparing multi-symbol data...")
multi_data = dm.get_multi_data(symbols, start, end, '1d')
print(f"Multi-data shape: {multi_data.shape}")

# 使用最优参数
strategy = AdaptiveMomentumV3(symbols=symbols)
strategy.max_position_pct = 0.10
strategy.rebalance_freq = 10
strategy.max_stocks = 10

engine = BacktestEngine(
    initial_cash=100000.0,
    commission_rate=0.001,
    start_date=start,
    end_date=end
)
engine.set_data(multi_data)
engine.set_strategy(strategy)

print("\nRunning backtest with optimized params...")
results = engine.run()

metrics = AnalyticsEngine.calculate_metrics(
    results['returns'],
    results['equity_curve'],
    results['trades'],
    engine.initial_cash
)

AnalyticsEngine.print_report(metrics)

# 保存
results['equity_curve'].to_csv('data_cache/50symbols_equity.csv')
if len(results['trades']) > 0:
    results['trades'].to_csv('data_cache/50symbols_trades.csv', index=False)

print(f"\n✓ Results saved to data_cache/50symbols_*.csv")

# 与基准对比
spy_data = dm.get_data('SPY', start, end, '1d')
spy_return = (spy_data['close'].iloc[-1] / spy_data['close'].iloc[0] - 1) * 100
print(f"\nBenchmark (SPY) return: {spy_return:+.2f}%")
print(f"Strategy outperformance: {metrics['total_return'] - spy_return:+.2f}%")
