"""生产级系统验证 - 确保所有模块真正可用"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

print("="*70)
print("LocalQuant 生产级系统验证")
print("="*70)

errors = []
success = []

# 1. 验证核心引擎
print("\n[1/10] 验证核心引擎...")
try:
    from localquant.core.events import EventType, OrderEvent
    from localquant.core.portfolio import Portfolio
    from localquant.core.broker import SimulatedBroker
    from localquant.core.engine import BacktestEngine
    
    p = Portfolio(100000)
    p.execute_order('AAPL', 100, 150.0, 1.0)
    assert p.positions['AAPL'].quantity == 100
    
    success.append("核心引擎")
except Exception as e:
    errors.append(f"核心引擎: {e}")

# 2. 验证技术指标
print("[2/10] 验证技术指标库...")
try:
    import pandas as pd
    import numpy as np
    from localquant.strategy.indicators import sma, ema, rsi, macd, bollinger_bands
    
    data = pd.Series(np.random.randn(100).cumsum() + 100)
    assert len(sma(data, 20)) == 100
    assert len(ema(data, 20)) == 100
    assert len(rsi(data, 14)) == 100
    assert 'macd' in macd(data, 12, 26, 9).columns
    assert 'upper' in bollinger_bands(data, 20, 2).columns
    
    success.append("技术指标")
except Exception as e:
    errors.append(f"技术指标: {e}")

# 3. 验证数据源 - Yahoo Finance
print("[3/10] 验证 Yahoo Finance 数据源...")
try:
    from localquant.data.manager import DataManager
    dm = DataManager(cache_dir='./data_cache')
    data = dm.get_data('AAPL', datetime(2024,1,1), datetime(2024,1,31), '1d', 'yahoo')
    assert len(data) > 0
    assert 'close' in data.columns
    
    success.append("Yahoo Finance")
except Exception as e:
    errors.append(f"Yahoo Finance: {e}")

# 4. 验证数据源 - CCXT/币安
print("[4/10] 验证 CCXT 币安数据源...")
try:
    from localquant.sources.ccxt import CCXTSource
    src = CCXTSource('binance')
    data = src.fetch('BTC/USDT', datetime(2024,1,1), datetime(2024,1,10), '1d')
    assert data is not None and len(data) > 0
    
    success.append("CCXT/Binance")
except Exception as e:
    errors.append(f"CCXT/Binance: {e}")

# 5. 验证数据源 - AKShare
print("[5/10] 验证 AKShare A股数据源...")
try:
    from localquant.sources.akshare import AKShareSource
    src = AKShareSource()
    data = src.fetch('600519', datetime(2024,1,1), datetime(2024,1,31), '1d')
    assert data is not None and len(data) > 0
    
    success.append("AKShare")
except Exception as e:
    errors.append(f"AKShare: {e}")

# 6. 验证回测引擎完整运行
print("[6/10] 验证回测引擎完整运行...")
try:
    from localquant.analytics import AnalyticsEngine
    from strategies.adaptive_momentum_v3 import AdaptiveMomentumV3
    
    symbols = ['AAPL', 'MSFT']
    multi_data = dm.get_multi_data(symbols, datetime(2024,1,1), datetime(2024,3,31), '1d')
    
    strategy = AdaptiveMomentumV3(symbols=symbols)
    strategy.max_position_pct = 0.30
    strategy.rebalance_freq = 20
    strategy.max_stocks = 2
    
    engine = BacktestEngine(initial_cash=100000, commission_rate=0.001)
    engine.set_data(multi_data)
    engine.set_strategy(strategy)
    
    results = engine.run()
    metrics = AnalyticsEngine.calculate_metrics(results['returns'], results['equity_curve'], results['trades'], 100000)
    
    assert metrics['total_return'] is not None
    assert metrics['sharpe_ratio'] is not None
    
    success.append("回测引擎")
except Exception as e:
    errors.append(f"回测引擎: {e}")

# 7. 验证实盘接口 - Binance
print("[7/10] 验证币安实盘接口...")
try:
    from localquant.live.binance import BinanceBroker
    from localquant.live.base import Order, OrderSide, OrderType
    
    broker = BinanceBroker(sandbox=True)
    connected = broker.connect()
    assert connected
    
    price = broker.get_market_price('BTC/USDT')
    assert price is not None and price > 0
    
    broker.disconnect()
    
    success.append("Binance实盘接口")
except Exception as e:
    errors.append(f"Binance实盘: {e}")

# 8. 验证参数优化
print("[8/10] 验证参数优化框架...")
try:
    from localquant.optimization import ParamOptimizer
    success.append("参数优化")
except Exception as e:
    errors.append(f"参数优化: {e}")

# 9. 验证可视化
print("[9/10] 验证可视化生成...")
try:
    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[1,2,3], y=[1,2,3]))
    fig.write_image('/tmp/test_chart.png', width=100, height=100)
    
    success.append("可视化")
except Exception as e:
    errors.append(f"可视化: {e}")

# 10. 验证测试套件
print("[10/10] 验证单元测试...")
try:
    import subprocess
    result = subprocess.run(
        ['python3', 'tests/unit/test_core.py'],
        cwd=str(root),
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Tests failed: {result.stdout}"
    
    success.append("单元测试")
except Exception as e:
    errors.append(f"单元测试: {e}")

# 结果汇总
print("\n" + "="*70)
print("验证结果汇总")
print("="*70)

print(f"\n✅ 成功 ({len(success)}/{len(success)+len(errors)}):")
for s in success:
    print(f"  ✓ {s}")

if errors:
    print(f"\n❌ 失败 ({len(errors)}):")
    for e in errors:
        print(f"  ✗ {e}")
else:
    print("\n🎉 所有模块验证通过！系统已就绪。")

print("\n" + "="*70)
