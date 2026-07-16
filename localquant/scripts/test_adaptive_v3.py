"""测试 AdaptiveMomentumV3.1 LocalQuant 适配版"""
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
print("AdaptiveMomentumV3.1 LocalQuant Test")
print("="*60)

# 使用较小标的集进行测试
test_symbols = [
    'SPY', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'NFLX', 'AMD',
    'JPM', 'JNJ', 'XOM', 'V', 'WMT', 'MA', 'PG', 'HD', 'BAC', 'CVX',
    'TLT', 'GLD', 'VIXY'
]

start = datetime(2022, 1, 1)
end = datetime(2024, 12, 31)

dm = DataManager(cache_dir='./data_cache')

print(f"\nDownloading data for {len(test_symbols)} symbols...")
for sym in test_symbols:
    try:
        data = dm.get_data(sym, start, end, '1d', 'yahoo')
        print(f"  {sym}: {len(data)} rows")
    except Exception as e:
        print(f"  {sym}: FAILED - {e}")

print("\nPreparing multi-symbol data...")
multi_data = dm.get_multi_data(test_symbols, start, end, '1d')
print(f"Multi-data shape: {multi_data.shape}")

# 运行回测
strategy = AdaptiveMomentumV3(symbols=test_symbols)

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

# 分析
metrics = AnalyticsEngine.calculate_metrics(
    results['returns'],
    results['equity_curve'],
    results['trades'],
    engine.initial_cash
)

AnalyticsEngine.print_report(metrics)

# 保存
results['equity_curve'].to_csv('data_cache/adaptive_v3_equity.csv')
if len(results['trades']) > 0:
    results['trades'].to_csv('data_cache/adaptive_v3_trades.csv', index=False)

print("\n✓ Results saved to data_cache/adaptive_v3_*.csv")
