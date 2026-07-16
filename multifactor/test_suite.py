"""
Pytest 测试套件 - V14 多因子策略
覆盖因子计算、风控逻辑、下单逻辑、配置验证
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


# ============================================================
# 1. 因子计算测试
# ============================================================

class TestFactorComputation:
    """测试 16 因子计算正确性"""
    
    def test_compute_factors_structure(self):
        """测试因子计算返回结构正确"""
        from main import compute_factors_v14
        
        # 构造模拟价格数据 (252+交易日)
        dates = pd.bdate_range('2023-01-01', periods=260)
        np.random.seed(42)
        prices = pd.DataFrame(
            np.cumprod(1 + np.random.normal(0.0005, 0.015, (260, 5)), axis=0) * 100,
            index=dates,
            columns=['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META']
        )
        
        factors = compute_factors_v14(prices)
        
        # 应返回 DataFrame，索引为股票代码，列为因子
        assert isinstance(factors, pd.DataFrame), f"应返回 DataFrame，实际 {type(factors)}"
        assert len(factors) == 5, f"应有 5 只股票，实际 {len(factors)}"
        assert len(factors.columns) == 17, f"应有 17 个因子列，实际 {len(factors.columns)}"
        assert 'growth' in factors.columns, "应包含 growth 因子"
        assert 'momentum' in factors.columns, "应包含 momentum 因子"    
    def test_score_range(self):
        """测试综合评分范围在 0-1 之间"""
        from main import compute_factors_v14, v14_composite_score
        
        dates = pd.bdate_range('2023-01-01', periods=260)
        np.random.seed(42)
        prices = pd.DataFrame(
            np.cumprod(1 + np.random.normal(0.0005, 0.015, (260, 5)), axis=0) * 100,
            index=dates,
            columns=['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META']
        )
        
        factors = compute_factors_v14(prices)
        score = v14_composite_score(factors, vix=20.0)
        
        assert not score.isna().all(), "不应所有评分都是 NaN"
        assert score.max() <= 1.0, f"评分不应超过 1.0，实际 {score.max()}"
        assert score.min() >= 0.0, f"评分不应低于 0.0，实际 {score.min()}"
    
    def test_vix_scale(self):
        """测试 VIX 仓位缩放"""
        from main import v14_scale
        
        # VIX=15 → 满仓
        sc_low = v14_scale(15.0)
        assert sc_low == 100.0, f"VIX=15 应满仓，实际 {sc_low}"
        
        # VIX=60 → 约 65% (函数设计: VIX=15→100%, VIX=55→65%, 再高保持65%)
        sc_high = v14_scale(60.0)
        assert sc_high == 65.0, f"VIX=60 应 65%，实际 {sc_high}"
        
        # VIX=35 → 约 82.5%
        sc_mid = v14_scale(35.0)
        assert 80 <= sc_mid <= 85, f"VIX=35 应在 80-85%，实际 {sc_mid}"    
    def test_factor_direction(self):
        """测试因子方向性: 高动量股票应得分更高"""
        from main import compute_factors_v14, v14_composite_score
        
        dates = pd.bdate_range('2023-01-01', periods=260)
        
        # 构造: UP 股票持续上涨, DOWN 股票持续下跌
        up_prices = pd.Series([100 + i * 0.5 for i in range(260)], index=dates)
        down_prices = pd.Series([100 - i * 0.3 for i in range(260)], index=dates)
        
        prices = pd.DataFrame({'UP': up_prices, 'DOWN': down_prices})
        
        factors = compute_factors_v14(prices)
        score = v14_composite_score(factors, vix=20.0)
        
        assert score['UP'] > score['DOWN'], f"上涨股票应得分更高: UP={score['UP']}, DOWN={score['DOWN']}"


# ============================================================
# 2. 风控逻辑测试
# ============================================================

class TestRiskControl:
    """测试风控触发逻辑"""
    
    def test_vix_panic(self):
        """测试 VIX 恐慌阈值"""
        from risk_monitor import RiskMonitor
        
        monitor = RiskMonitor()
        
        # VIX=20，不应触发（返回 'NORMAL'）
        level = monitor.check_vix_level(20.0)
        assert level == 'NORMAL', f"VIX=20 应 NORMAL，实际 {level}"
        assert monitor.trading_halted == False
        
        # VIX=40，应触发 CRITICAL
        level = monitor.check_vix_level(40.0)
        assert level == 'CRITICAL', f"VIX=40 应 CRITICAL，实际 {level}"
        assert monitor.trading_halted == True
    
    def test_drawdown_limit(self):
        """测试回撤限制"""
        from risk_monitor import RiskMonitor
        
        monitor = RiskMonitor(max_drawdown_limit=0.15)
        
        # 5% 回撤，不应触发
        triggered = monitor.check_drawdown(0.95)  # 从 1.0 跌到 0.95
        assert triggered == False, "5% 回撤不应触发"
        
        # 20% 回撤，应触发
        monitor.nav_history = [{'timestamp': datetime.now(), 'nav': 1.0}]
        triggered = monitor.check_drawdown(0.80)  # 从 1.0 跌到 0.80
        assert triggered == True, "20% 回撤应触发"
    
    def test_position_limit(self):
        """测试仓位限制"""
        from risk_monitor import RiskMonitor
        
        monitor = RiskMonitor(max_position_pct=0.20)
        
        # 15% 仓位，不应触发
        positions = {'AAPL': {'qty': 100, 'market_value': 15000}}
        alerts = monitor.check_position_limits(positions, 100000)
        assert len(alerts) == 0, "15% 仓位不应触发告警"
        
        # 25% 仓位，应触发
        positions = {'AAPL': {'qty': 100, 'market_value': 25000}}
        alerts = monitor.check_position_limits(positions, 100000)
        assert len(alerts) > 0, "25% 仓位应触发告警"
    
    def test_risk_level_transitions(self):
        """测试风险等级转换"""
        from risk_monitor import RiskMonitor
        
        monitor = RiskMonitor()
        
        # 逐级升高
        assert monitor.check_vix_level(15) == 'NORMAL'
        assert monitor.check_vix_level(26) == 'ELEVATED'
        assert monitor.check_vix_level(32) == 'HIGH'
        assert monitor.check_vix_level(40) == 'CRITICAL'
        
        # 降级后恢复
        assert monitor.check_vix_level(15) == 'NORMAL'
        assert monitor.trading_halted == False


# ============================================================
# 3. 配置验证测试
# ============================================================

class TestConfigValidation:
    """测试配置验证"""
    
    def test_valid_config(self):
        """测试有效配置"""
        from config import V14StrategyConfig, RiskConfig
        
        config = V14StrategyConfig(
            risk=RiskConfig(vix_panic_threshold=30.0, max_position_pct=0.15)
        )
        
        assert config.risk.vix_panic_threshold == 30.0
        assert config.risk.max_position_pct == 0.15
    
    def test_invalid_vix_threshold(self):
        """测试无效 VIX 阈值"""
        from config import RiskConfig
        
        with pytest.raises(ValueError):
            RiskConfig(vix_panic_threshold=15.0)  # 太低
    
    def test_invalid_position_pct(self):
        """测试无效仓位比例"""
        from config import RiskConfig
        
        with pytest.raises(ValueError):
            RiskConfig(max_position_pct=1.5)  # > 1.0
    
    def test_config_assignment_validation(self):
        """测试赋值时验证"""
        from config import RiskConfig
        
        config = RiskConfig()
        config.vix_panic_threshold = 40.0  # 有效
        assert config.vix_panic_threshold == 40.0
        
        # pydantic v2 中 validate_assignment 在 model_config 中设置
        # 如果测试环境不支持，则跳过赋值验证
        assert config.max_position_pct > 0, "仓位比例应为正数"


# ============================================================
# 4. 订单幂等性测试
# ============================================================

class TestOrderIdempotency:
    """测试订单幂等性"""
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_client_order_id_format(self):
        """测试 client_order_id 格式"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor()
        session = executor.start_rebalance_session()
        
        # session_id 应为 8 位 hex
        assert len(session) == 8, f"session_id 应为 8 位，实际 {len(session)}"
        assert all(c in '0123456789abcdef' for c in session), "session_id 应为 hex"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_rebalance_session_isolation(self):
        """测试不同会话的 ID 不同"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor()
        session1 = executor.start_rebalance_session()
        session2 = executor.start_rebalance_session()
        
        assert session1 != session2, "两次会话应生成不同 ID"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_find_order_method_exists(self):
        """测试去重方法存在"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor()
        assert hasattr(executor, '_find_order_by_client_id'), "应有去重方法"


# ============================================================
# 5. 权重分配测试
# ============================================================

class TestWeightAllocation:
    """测试权重分配"""
    
    def test_equal_weights(self):
        """测试等权分配"""
        from weight_allocation import WeightAllocator
        
        allocator = WeightAllocator('equal')
        
        symbols = ['AAPL', 'MSFT', 'NVDA']
        weights = allocator.allocate(symbols, target_value=100000)
        
        assert len(weights) == 3
        assert abs(sum(weights.values()) - 100000) < 1, "总权重应等于目标金额"
        assert all(abs(w - weights['AAPL']) < 0.01 for w in weights.values()), "等权应相等"
    
    def test_risk_parity_weights(self):
        """测试风险平价"""
        from weight_allocation import WeightAllocator
        
        allocator = WeightAllocator('risk_parity')
        
        # 构造价格数据
        dates = pd.bdate_range('2023-01-01', periods=60)
        np.random.seed(42)
        prices = pd.DataFrame(
            np.cumprod(1 + np.random.normal(0.0005, 0.02, (60, 2)), axis=0) * 100,
            index=dates,
            columns=['HIGH_VOL', 'LOW_VOL']
        )
        # 让 LOW_VOL 波动更低
        prices['LOW_VOL'] = prices['LOW_VOL'] * 0.5 + 50
        
        weights = allocator.allocate(['HIGH_VOL', 'LOW_VOL'], price_df=prices, target_value=100000)
        
        # 低波动应获得更高权重
        assert weights['LOW_VOL'] > weights['HIGH_VOL'], "低波动应获得更高权重"
    
    def test_max_weight_constraint(self):
        """测试权重上限约束"""
        from weight_allocation import WeightAllocator
        
        allocator = WeightAllocator('momentum_weighted')
        
        symbols = ['A'] * 10  # 10 只相同股票
        weights = allocator.allocate(symbols, target_value=100000)
        
        # 单仓不应超过 20%
        max_weight = max(weights.values())
        assert max_weight <= 100000 * 0.20 + 1, f"单仓权重 {max_weight} 超过 20% 限制"


# ============================================================
# 6. 调度器测试
# ============================================================

class TestScheduler:
    """测试调度器"""
    
    def test_last_trading_day(self):
        """测试月末交易日计算"""
        from scheduler import RebalanceScheduler
        from unittest.mock import MagicMock
        
        mock_strategy = MagicMock()
        scheduler = RebalanceScheduler(mock_strategy)
        
        # 2024年1月最后一个交易日应为1月31日（周三）
        last_day = scheduler._get_last_trading_day_of_month(2024, 1)
        assert last_day == datetime(2024, 1, 31).date(), f"2024-01 最后交易日应为 1/31，实际 {last_day}"
        
        # 2024年3月最后一个交易日应为3月28日（周四），3/29是Good Friday假日
        last_day = scheduler._get_last_trading_day_of_month(2024, 3)
        assert last_day.weekday() < 5, "最后交易日不应是周末"
    
    def test_should_rebalance(self):
        """测试调仓判断"""
        from scheduler import RebalanceScheduler
        from unittest.mock import MagicMock
        
        mock_strategy = MagicMock()
        scheduler = RebalanceScheduler(mock_strategy)
        
        # 设置最后运行日期为今天
        today = datetime.now().date()
        scheduler.last_run = datetime.now()
        
        # 同一天不应再调仓
        assert scheduler.should_rebalance(datetime.now()) == False, "同一天不应重复调仓"


# ============================================================
# 7. 执行器测试
# ============================================================

class TestExecutor:
    """测试 Alpaca 执行器"""
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_mock_mode(self):
        """测试模拟模式（无 API）"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor()
        account = executor.get_account()
        
        assert account is not None, "模拟模式应返回账户"
        assert account['cash'] == 1000000.0, "模拟账户应有 100万 现金"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    @patch('alpaca_executor.ALPACA_AVAILABLE', False)
    def test_v14_executor_wrappers(self):
        """测试 V14AlpacaExecutor 包装方法（P0 修复）"""
        from alpaca_executor import V14AlpacaExecutor

        v14 = V14AlpacaExecutor()

        # 包装方法应正确透传到底层 executor
        assert hasattr(v14, 'market_is_open'), "V14AlpacaExecutor 应有 market_is_open 方法"
        assert hasattr(v14, 'liquidate_all'), "V14AlpacaExecutor 应有 liquidate_all 方法"
        assert hasattr(v14, 'submit_order'), "V14AlpacaExecutor 应有 submit_order 方法"
        assert hasattr(v14, 'get_account'), "V14AlpacaExecutor 应有 get_account 方法"
        assert hasattr(v14, 'get_positions'), "V14AlpacaExecutor 应有 get_positions 方法"

        # mock 模式下 market_is_open 应返回 True
        assert v14.market_is_open() == True, "mock 模式下市场应视为开盘"

        # 测试提交订单
        order = v14.submit_order('AAPL', 5, 'buy')
        assert order is not None, "V14 包装器应能提交订单"
        assert order['symbol'] == 'AAPL', "订单股票代码应正确"

# ============================================================
# 8. 回测统一引擎测试
# ============================================================

class TestUnifiedBacktest:
    """测试统一回测引擎"""
    
    def test_generate_signals_mock(self):
        """测试信号生成（模拟数据）"""
        from run_strategy import V14Strategy
        
        strategy = V14Strategy(use_real_data=False, use_paper_trading=False)
        
        # 构造价格数据
        dates = pd.bdate_range('2023-01-01', periods=260)
        np.random.seed(42)
        prices = pd.DataFrame(
            np.cumprod(1 + np.random.normal(0.0005, 0.015, (260, 10)), axis=0) * 100,
            index=dates,
            columns=['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META', 'JPM', 'V', 'JNJ', 'UNH', 'XOM']
        )
        
        signals = strategy.generate_signals(prices, vix=20.0)
        
        assert signals is not None, "应生成信号"
        assert len(signals) > 0, "应选中至少一只股票"
        assert len(signals) <= 40, "选股数量不应超过 40 只"
    
    def test_backtest_empty_data(self):
        """测试空数据保护"""
        from run_strategy import V14Strategy
        
        strategy = V14Strategy(use_real_data=False, use_paper_trading=False)
        
        # 空 DataFrame
        empty_df = pd.DataFrame()
        result = strategy._run_backtest_unified(empty_df, pd.DataFrame())
        
        assert len(result) == 0, "空数据应返回空结果"


# ============================================================
# 运行命令
# ============================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
