"""参数优化测试 - AdaptiveMomentumV3.1"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.data.manager import DataManager
from localquant.optimization import ParamOptimizer
from strategies.adaptive_momentum_v3 import AdaptiveMomentumV3

print("="*60)
print("Parameter Optimization - AdaptiveMomentumV3.1")
print("="*60)

# 使用测试标的
test_symbols = [
    'SPY', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'NFLX', 'AMD',
    'JPM', 'JNJ', 'XOM', 'V', 'WMT', 'MA', 'PG', 'HD', 'BAC', 'CVX',
    'TLT', 'GLD', 'VIXY'
]

start = datetime(2022, 1, 1)
end = datetime(2024, 12, 31)

dm = DataManager(cache_dir='./data_cache')

print(f"\nPreparing data for {len(test_symbols)} symbols...")
multi_data = dm.get_multi_data(test_symbols, start, end, '1d')
print(f"Data shape: {multi_data.shape}")

# 参数搜索空间（先做2个关键参数，快速验证）
param_grid = {
    'max_position_pct': [0.10, 0.15, 0.20],
    'rebalance_freq': [5, 10, 15]
}

print(f"\nParameter grid:")
for k, v in param_grid.items():
    print(f"  {k}: {v}")

optimizer = ParamOptimizer(
    strategy_class=AdaptiveMomentumV3,
    symbols=test_symbols,
    data=multi_data,
    start=start,
    end=end,
    initial_cash=100000,
    commission_rate=0.001
)

# 优化目标：夏普比率（最大化）
best_params, all_results = optimizer.grid_search(
    param_grid=param_grid,
    scoring='sharpe_ratio',
    maximize=True,
    n_jobs=1  # 单进程，避免多进程问题
)

# 打印详细结果
optimizer.print_top_results(n=5, scoring='sharpe_ratio')

# 也看看按总收益排序
optimizer.print_top_results(n=5, scoring='total_return')

# 也看看按 Calmar 排序
optimizer.print_top_results(n=5, scoring='calmar_ratio')

# 保存结果
results_df = optimizer.get_results_df()
results_df.to_csv('data_cache/optimization_results.csv', index=False)
print(f"\n✓ Results saved to data_cache/optimization_results.csv")
print(f"  Total combinations: {len(all_results)}")
print(f"  Valid results: {len([r for r in all_results if r['success']])}")
