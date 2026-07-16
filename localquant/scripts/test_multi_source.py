"""测试多数据源支持"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.data.manager import DataManager

print("="*60)
print("Multi-Source Data Test")
print("="*60)

dm = DataManager(cache_dir='./data_cache')

# 1. Yahoo Finance (美股)
print("\n1. Yahoo Finance - AAPL")
try:
    data = dm.get_data('AAPL', datetime(2024,1,1), datetime(2024,1,31), '1d', 'yahoo')
    print(f"  ✓ {len(data)} rows, cols: {list(data.columns)}")
    print(f"  Date range: {data.index[0].date()} to {data.index[-1].date()}")
except Exception as e:
    print(f"  ✗ {e}")

# 2. CCXT (加密货币) - 可选
print("\n2. CCXT - BTC/USDT")
try:
    data = dm.get_data('BTC/USDT', datetime(2024,1,1), datetime(2024,1,31), '1d', 'ccxt')
    if data is not None and len(data) > 0:
        print(f"  ✓ {len(data)} rows, cols: {list(data.columns)}")
        print(f"  Date range: {data.index[0].date()} to {data.index[-1].date()}")
    else:
        print("  ⚠ No data (CCXT may not be installed)")
except ImportError:
    print("  ⚠ ccxt not installed. Run: pip install ccxt")
except Exception as e:
    print(f"  ✗ {e}")

# 3. AKShare (A股) - 可选
print("\n3. AKShare - 贵州茅台 (600519)")
try:
    data = dm.get_data('600519', datetime(2024,1,1), datetime(2024,1,31), '1d', 'akshare')
    if data is not None and len(data) > 0:
        print(f"  ✓ {len(data)} rows, cols: {list(data.columns)}")
        print(f"  Date range: {data.index[0].date()} to {data.index[-1].date()}")
    else:
        print("  ⚠ No data (AKShare may not be installed)")
except ImportError:
    print("  ⚠ akshare not installed. Run: pip install akshare")
except Exception as e:
    print(f"  ✗ {e}")

print("\n✓ Multi-source test complete!")
