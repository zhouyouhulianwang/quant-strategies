"""真实分钟级回测 - 使用最近5天数据"""
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
print("Real Minute-Level Backtest (5m data, last 30 days)")
print("="*60)

# 使用小标的集
test_symbols = ['AAPL', 'MSFT', 'NVDA', 'SPY']

end = datetime.now()
start = end - timedelta(days=20)  # 20天内
dm = DataManager(cache_dir='./data_cache')

print(f"\nDownloading 5m data...")
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
    # 分钟级回测
    strategy = AdaptiveMomentumV3(symbols=test_symbols)
    strategy.max_position_pct = 0.20  # 更集中，因为标的少
    strategy.rebalance_freq = 2  # 2天
    strategy.max_stocks = 3
    strategy.min_hold_days = 0  # 分钟级中允许更快交易
    
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
    print(f"  Data frequency: ~5min per bar")
else:
    print("\n⚠ No 5m data available")
