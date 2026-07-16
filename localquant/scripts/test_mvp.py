"""测试 LocalQuant MVP - 下载数据并运行回测"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from strategies.sma_cross import SmaCrossStrategy

print("="*60)
print("LocalQuant MVP Test")
print("="*60)

# 1. 获取数据
print("\n1. Fetching AAPL data...")
dm = DataManager(cache_dir='./data_cache')
start = datetime(2022, 1, 1)
end = datetime(2024, 12, 31)

data = dm.get_data('AAPL', start, end, '1d', 'yahoo')
print(f"   Data shape: {data.shape}")
print(f"   Date range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"   Columns: {list(data.columns)}")

# 2. 创建策略
print("\n2. Initializing strategy...")
strategy = SmaCrossStrategy(short_period=20, long_period=50)
strategy.symbols = ['AAPL']

# 3. 运行回测
print("\n3. Running backtest...")
engine = BacktestEngine(
    initial_cash=100000.0,
    commission_rate=0.001,
    start_date=start,
    end_date=end
)
engine.set_data(data, symbol_name='AAPL')
engine.set_strategy(strategy)

results = engine.run()

# 4. 分析结果
print("\n4. Analyzing results...")
metrics = AnalyticsEngine.calculate_metrics(
    results['returns'],
    results['equity_curve'],
    results['trades'],
    engine.initial_cash
)

AnalyticsEngine.print_report(metrics)

# 5. 保存结果
print("\n5. Saving results...")
results['equity_curve'].to_csv('data_cache/equity_curve.csv')
if len(results['trades']) > 0:
    results['trades'].to_csv('data_cache/trades.csv', index=False)
    print("   ✓ Results saved to data_cache/")

print("\n" + "="*60)
print("MVP Test Complete!")
print("="*60)
