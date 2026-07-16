"""测试 LocalQuant MVP - 带调试信息"""
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
print("LocalQuant MVP Test - Debug Mode")
print("="*60)

dm = DataManager(cache_dir='./data_cache')
start = datetime(2022, 1, 1)
end = datetime(2024, 12, 31)

data = dm.get_data('AAPL', start, end, '1d', 'yahoo')
print(f"Data shape: {data.shape}")

strategy = SmaCrossStrategy(short_period=20, long_period=50)
strategy.symbols = ['AAPL']

engine = BacktestEngine(
    initial_cash=100000.0,
    commission_rate=0.001,
    start_date=start,
    end_date=end
)
engine.set_data(data)
engine.set_strategy(strategy)

# 手动运行前10条看看
strategy.initialize()

for i, (timestamp, row) in enumerate(data.iterrows()):
    if i >= 100:
        break
    
    market_data = engine._create_market_data(timestamp, row)
    strategy.on_data(market_data)
    
    if i >= 55 and i < 65:  # 打印第55-65条的数据
        hist = strategy.context.get_history('AAPL', 'close', lookback=60)
        if len(hist) >= 50:
            from localquant.strategy.indicators import sma
            s20 = sma(hist, 20).iloc[-1]
            s50 = sma(hist, 50).iloc[-1]
            print(f"[{i}] {timestamp.date()} close={hist.iloc[-1]:.2f} sma20={s20:.2f} sma50={s50:.2f} in_pos={strategy._in_position}")
        
    engine._process_events()

print(f"\nOrders placed: {len(engine.orders)}")
print(f"Fills: {len(engine.fills)}")
