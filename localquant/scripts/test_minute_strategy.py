"""分钟级回测 - 使用短周期策略"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from strategies.minute_momentum import MinuteMomentumStrategy

print("="*60)
print("Minute-Level Backtest (5m data, 30 days)")
print("="*60)

test_symbols = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'SPY']

end = datetime.now()
start = end - timedelta(days=30)
dm = DataManager(cache_dir='./data_cache')

print(f"Downloading 5m data...")
for sym in test_symbols:
    try:
        data = dm.get_data(sym, start, end, '5m', 'yahoo')
        print(f"  {sym}: {len(data)} rows")
    except Exception as e:
        print(f"  {sym}: {e}")

print("\nPreparing multi-symbol data...")
multi_data = dm.get_multi_data(test_symbols, start, end, '5m')
print(f"Multi-data shape: {multi_data.shape}")

if len(multi_data) > 0:
    strategy = MinuteMomentumStrategy(symbols=test_symbols)
    strategy.rebalance_hours = 4
    strategy.max_position_pct = 0.33
    
    engine = BacktestEngine(
        initial_cash=100000.0,
        commission_rate=0.001,
        start_date=start,
        end_date=end
    )
    engine.set_data(multi_data)
    engine.set_strategy(strategy)
    
    print(f"\nRunning 5m backtest...")
    results = engine.run()
    
    metrics = AnalyticsEngine.calculate_metrics(
        results['returns'],
        results['equity_curve'],
        results['trades'],
        engine.initial_cash
    )
    
    AnalyticsEngine.print_report(metrics)
    
    print(f"\n✓ 5m backtest complete!")
    print(f"  Total bars: {len(results['equity_curve'])}")
    print(f"  Total trades: {len(results['trades'])}")
else:
    print("\n⚠ No 5m data available")
