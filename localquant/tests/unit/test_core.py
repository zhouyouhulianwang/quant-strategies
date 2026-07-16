"""测试套件 - LocalQuant 核心模块测试"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

# 设置正确的导入路径
root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.core.events import EventType, OrderEvent, FillEvent
from localquant.core.portfolio import Portfolio, Position
from localquant.core.broker import SimulatedBroker
from localquant.core.engine import BacktestEngine
from localquant.strategy import BaseStrategy
from localquant.strategy.indicators import sma, ema, rsi, macd, bollinger_bands
from localquant.analytics import AnalyticsEngine
from localquant.data import ParquetCache

class TestEvents(unittest.TestCase):
    """测试事件系统"""
    
    def test_order_event_creation(self):
        order = OrderEvent(
            event_type=EventType.ORDER,
            timestamp=datetime.now(),
            symbol='AAPL',
            order_type='MARKET',
            quantity=100,
            price=150.0
        )
        self.assertEqual(order.symbol, 'AAPL')
        self.assertEqual(order.quantity, 100)
        self.assertEqual(order.price, 150.0)

class TestPortfolio(unittest.TestCase):
    """测试投资组合"""
    
    def setUp(self):
        self.portfolio = Portfolio(initial_cash=100000.0)
    
    def test_initial_state(self):
        self.assertEqual(self.portfolio.cash, 100000.0)
        self.assertEqual(len(self.portfolio.positions), 0)
    
    def test_buy_position(self):
        self.portfolio.execute_order('AAPL', 100, 150.0, 1.0)
        self.assertEqual(self.portfolio.cash, 100000 - 150*100 - 1.0)
        self.assertIn('AAPL', self.portfolio.positions)
        self.assertEqual(self.portfolio.positions['AAPL'].quantity, 100)
    
    def test_sell_position(self):
        self.portfolio.execute_order('AAPL', 100, 150.0, 1.0)
        pnl = self.portfolio.execute_order('AAPL', -100, 160.0, 1.0)
        self.assertEqual(pnl, 100 * (160 - 150))  # 已实现盈亏 = 1000
        self.assertNotIn('AAPL', self.portfolio.positions)
    
    def test_insufficient_funds(self):
        result = self.portfolio.execute_order('AAPL', 1000, 150.0, 1.0)
        self.assertIsNone(result)  # 资金不足
    
    def test_total_value(self):
        self.portfolio.execute_order('AAPL', 100, 150.0, 1.0)
        prices = {'AAPL': 160.0}
        total = self.portfolio.total_value(prices)
        expected = self.portfolio.cash + 100 * 160.0
        self.assertEqual(total, expected)

class TestIndicators(unittest.TestCase):
    """测试技术指标"""
    
    def setUp(self):
        np.random.seed(42)
        self.data = pd.Series(np.random.randn(100).cumsum() + 100)
    
    def test_sma(self):
        result = sma(self.data, 20)
        self.assertEqual(len(result), len(self.data))
        self.assertTrue(np.isnan(result.iloc[0]))  # 前19个应为NaN
        self.assertFalse(np.isnan(result.iloc[19]))  # 第20个应有值
    
    def test_ema(self):
        result = ema(self.data, 20)
        self.assertEqual(len(result), len(self.data))
        self.assertFalse(np.isnan(result.iloc[0]))  # EMA 从第一个就有值
    
    def test_rsi(self):
        result = rsi(self.data, 14)
        self.assertEqual(len(result), len(self.data))
        self.assertTrue(np.isnan(result.iloc[0]))
        self.assertFalse(np.isnan(result.iloc[13]))
        # RSI 应在 0-100 之间
        valid = result.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 100).all())
    
    def test_macd(self):
        result = macd(self.data, 12, 26, 9)
        self.assertEqual(len(result), len(self.data))
        self.assertIn('macd', result.columns)
        self.assertIn('signal', result.columns)
        self.assertIn('histogram', result.columns)
    
    def test_bollinger_bands(self):
        result = bollinger_bands(self.data, 20, 2.0)
        self.assertEqual(len(result), len(self.data))
        self.assertIn('upper', result.columns)
        self.assertIn('middle', result.columns)
        self.assertIn('lower', result.columns)
        # 上轨 > 中轨 > 下轨
        valid = result.dropna()
        self.assertTrue((valid['upper'] >= valid['middle']).all())
        self.assertTrue((valid['middle'] >= valid['lower']).all())

class TestBroker(unittest.TestCase):
    """测试经纪商"""
    
    def setUp(self):
        self.broker = SimulatedBroker(
            commission_rate=0.001,
            min_commission=1.0,
            slippage_model='fixed',
            slippage_amount=0.001
        )
    
    def test_commission_calculation(self):
        commission = self.broker.calculate_commission(100, 150.0)
        expected = 100 * 150.0 * 0.001  # 15.0
        self.assertEqual(commission, max(expected, 1.0))
    
    def test_slippage(self):
        price = 150.0
        # 买入滑点
        buy_price = self.broker.apply_slippage(price, 1)
        self.assertGreater(buy_price, price)
        # 卖出滑点
        sell_price = self.broker.apply_slippage(price, -1)
        self.assertLess(sell_price, price)

class TestBacktestEngine(unittest.TestCase):
    """测试回测引擎"""
    
    def setUp(self):
        self.engine = BacktestEngine(initial_cash=100000.0)
    
    def test_initial_state(self):
        self.assertEqual(self.engine.initial_cash, 100000.0)
        self.assertIsNone(self.engine.data)
        self.assertIsNone(self.engine.strategy)
    
    def test_missing_data_error(self):
        with self.assertRaises(ValueError):
            self.engine.run()
    
    def test_missing_strategy_error(self):
        # 创建模拟数据
        data = pd.DataFrame({
            'open': [100, 101, 102],
            'high': [101, 102, 103],
            'low': [99, 100, 101],
            'close': [101, 102, 103],
            'volume': [1000, 2000, 3000]
        }, index=pd.date_range('2023-01-01', periods=3))
        
        self.engine.set_data(data, symbol_name='TEST')
        with self.assertRaises(ValueError):
            self.engine.run()

class TestAnalytics(unittest.TestCase):
    """测试绩效分析"""
    
    def test_calculate_metrics(self):
        # 创建模拟数据
        equity = pd.Series([100, 105, 103, 110, 108, 115], 
                          index=pd.date_range('2023-01-01', periods=6))
        returns = equity.pct_change().fillna(0)
        trades = pd.DataFrame({
            'timestamp': pd.date_range('2023-01-01', periods=3),
            'symbol': ['AAPL', 'AAPL', 'AAPL'],
            'quantity': [100, -100, 100],
            'price': [100, 110, 105],
            'commission': [1.0, 1.0, 1.0],
            'realized_pnl': [0, 1000, 0]
        })
        
        metrics = AnalyticsEngine.calculate_metrics(returns, equity, trades, 100)
        
        self.assertEqual(metrics['initial_capital'], 100)
        self.assertEqual(metrics['final_equity'], 115)
        self.assertAlmostEqual(metrics['total_return'], 15.0, places=10)  # 浮点数精度

class TestDataCache(unittest.TestCase):
    """测试数据缓存"""
    
    def setUp(self):
        self.cache = ParquetCache(cache_dir='/tmp/test_cache')
    
    def test_cache_write_read(self):
        data = pd.DataFrame({
            'open': [100, 101],
            'high': [101, 102],
            'low': [99, 100],
            'close': [101, 102],
            'volume': [1000, 2000]
        }, index=pd.date_range('2023-01-01', periods=2))
        data.index.name = 'date'
        
        self.cache.write('TEST', '1d', data)
        self.assertTrue(self.cache.exists('TEST', '1d'))
        
        read_data = self.cache.read('TEST', '1d')
        self.assertIsNotNone(read_data)
        self.assertEqual(len(read_data), 2)
    
    def tearDown(self):
        # 清理测试缓存
        import shutil
        if Path('/tmp/test_cache').exists():
            shutil.rmtree('/tmp/test_cache')

def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
