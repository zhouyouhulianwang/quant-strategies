"""调试策略数据流"""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'localquant')

from datetime import datetime
from localquant.data.manager import DataManager
from strategies.sma_cross import SmaCrossStrategy

dm = DataManager(cache_dir='./data_cache')
data = dm.get_data('AAPL', datetime(2022,1,1), datetime(2024,12,31), '1d')

strategy = SmaCrossStrategy(short_period=20, long_period=50)
strategy.symbols = ['AAPL']
strategy.initialize()

# 模拟运行60条数据
for i, (timestamp, row) in enumerate(data.iterrows()):
    if i >= 60:
        break
    
    market_data = {
        'timestamp': timestamp,
        'data': {
            'AAPL': {
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume']
            }
        }
    }
    strategy.on_data(market_data)

print(f"Buffer keys: {list(strategy._history_buffer.keys())}")
print(f"Buffer length for AAPL: {len(strategy._history_buffer.get('AAPL', []))}")
if strategy._history_buffer.get('AAPL'):
    print(f"First entry: {strategy._history_buffer['AAPL'][0]}")
    print(f"Last entry: {strategy._history_buffer['AAPL'][-1]}")

# 检查 historical_data
print(f"\nHistorical data keys: {list(strategy.context.historical_data.keys())}")
if 'AAPL' in strategy.context.historical_data:
    df = strategy.context.historical_data['AAPL']
    print(f"DataFrame shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(f"Dtypes:\n{df.dtypes}")
    print(f"Head:\n{df.head(3)}")
    
    # 测试 get_history
    hist = strategy.context.get_history('AAPL', 'close', 60)
    print(f"\nget_history result: {len(hist)} items, type={type(hist)}")
    if len(hist) > 0:
        print(f"First: {hist.iloc[0]}, Last: {hist.iloc[-1]}")
