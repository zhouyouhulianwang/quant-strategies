"""测试多周期动量策略"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from strategies.multi_momentum import MultiMomentumStrategy

print("="*60)
print("Multi-Momentum Strategy Test")
print("="*60)

# 获取数据
symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'NFLX', 'AMD', 'INTC']
start = datetime(2022, 1, 1)
end = datetime(2024, 12, 31)

dm = DataManager(cache_dir='./data_cache')

print(f"\nDownloading data for {len(symbols)} symbols...")
for sym in symbols:
    data = dm.get_data(sym, start, end, '1d', 'yahoo')
    print(f"  {sym}: {len(data)} rows")

print("\nPreparing multi-symbol data...")
multi_data = dm.get_multi_data(symbols, start, end, '1d')
print(f"Multi-data shape: {multi_data.shape}")
print(f"Symbols: {multi_data.columns.get_level_values(1).unique().tolist()}")

# 运行回测
strategy = MultiMomentumStrategy(
    symbols=symbols,
    top_n=5
)
strategy.rebalance_freq = 20  # 设置再平衡频率

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
results['equity_curve'].to_csv('data_cache/momentum_equity.csv')
if len(results['trades']) > 0:
    results['trades'].to_csv('data_cache/momentum_trades.csv', index=False)

print("\n✓ Results saved to data_cache/momentum_*.csv")
