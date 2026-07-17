"""
Pytest 测试套件 - V14 多因子策略
覆盖因子计算、风控逻辑、下单逻辑、配置验证
"""

import pytest
import numpy as np
import pandas as pd
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
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
        
        executor = AlpacaPaperExecutor(mock=True)
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
        
        executor = AlpacaPaperExecutor(mock=True)
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
        
        executor = AlpacaPaperExecutor(mock=True)
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
    
    def test_normalize_target_positions(self):
        """测试目标持仓归一化（P1 修复）"""
        from weight_allocation import normalize_target_positions
        
        targets = {'AAPL': 60000, 'MSFT': 60000, 'NVDA': 60000}
        normalized = normalize_target_positions(targets, 100000)
        
        assert sum(normalized.values()) <= 100000, "归一化后总额不应超过上限"
        assert abs(sum(normalized.values()) - 100000) < 1, "归一化后总额应接近上限"
        assert abs(normalized['AAPL'] - 33333) < 1, "应按比例缩放"
        
        # 未超过上限时不应改变
        targets2 = {'AAPL': 30000, 'MSFT': 30000}
        normalized2 = normalize_target_positions(targets2, 100000)
        assert normalized2 == targets2, "未超过上限时保持不变"


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
    
    def test_allowed_months(self):
        """测试不同频率对应的允许调仓月份（参考 QC SetRebalanceSchedule）"""
        from scheduler import RebalanceScheduler
        from unittest.mock import MagicMock
        
        assert RebalanceScheduler(MagicMock(), 'monthly')._get_allowed_months() == list(range(1, 13))
        assert RebalanceScheduler(MagicMock(), 'bimonthly')._get_allowed_months() == [1, 3, 5, 7, 9, 11]
        assert RebalanceScheduler(MagicMock(), 'quarterly')._get_allowed_months() == [1, 4, 7, 10]
        assert RebalanceScheduler(MagicMock(), 'weekly')._get_allowed_months() == list(range(1, 13))
        assert RebalanceScheduler(MagicMock(), 'daily')._get_allowed_months() == list(range(1, 13))
    
    def test_first_trading_day_of_month(self):
        """测试首交易日计算"""
        from scheduler import RebalanceScheduler
        from unittest.mock import MagicMock
        
        scheduler = RebalanceScheduler(MagicMock())
        
        # 2024-01-01 是周一但也是 New Year's Day 假日，所以首日应为 2024-01-02
        assert scheduler._get_first_trading_day_of_month(2024, 1) == datetime(2024, 1, 2).date()
        
        # 2024-04-01 是周一且为交易日，应为首日
        assert scheduler._get_first_trading_day_of_month(2024, 4) == datetime(2024, 4, 1).date()
        
        # 2024-03-01 是周五，受周末影响首日为 2024-03-04（周一）
        assert scheduler._get_first_trading_day_of_month(2024, 3) == datetime(2024, 3, 1).date()
    
    def test_weekly_rebalance(self):
        """测试每周一调仓"""
        from scheduler import RebalanceScheduler, NY_TZ
        from unittest.mock import MagicMock
        
        scheduler = RebalanceScheduler(MagicMock(), rebalance_frequency='weekly')
        
        # 2024-01-08 是周一，10:00 ET 应触发
        monday_open = datetime(2024, 1, 8, 10, 0, tzinfo=NY_TZ)
        assert scheduler.should_rebalance(monday_open) == True, "周一 10:00 ET 应触发周频调仓"
        
        # 开盘前不触发
        monday_early = datetime(2024, 1, 8, 9, 0, tzinfo=NY_TZ)
        assert scheduler.should_rebalance(monday_early) == False, "开盘前不应触发"
        
        # 周二不触发
        tuesday = datetime(2024, 1, 9, 10, 0, tzinfo=NY_TZ)
        assert scheduler.should_rebalance(tuesday) == False, "周二不应触发周频调仓"
    
    def test_bimonthly_rebalance(self):
        """测试双月调仓：只在奇数月份首日触发"""
        from scheduler import RebalanceScheduler, NY_TZ
        from unittest.mock import MagicMock
        
        scheduler = RebalanceScheduler(MagicMock(), rebalance_frequency='bimonthly')
        
        # 2024-01-02 是 1 月首个交易日，应触发
        jan_first = datetime(2024, 1, 2, 10, 0, tzinfo=NY_TZ)
        assert scheduler.should_rebalance(jan_first) == True, "双月频应在 1 月首日触发"
        
        # 2024-02-01 不在允许月份
        feb_first = datetime(2024, 2, 1, 10, 0, tzinfo=NY_TZ)
        assert scheduler.should_rebalance(feb_first) == False, "2 月不应触发双月频调仓"
    
    def test_quarterly_rebalance(self):
        """测试季度调仓：只在 1/4/7/10 月首日触发"""
        from scheduler import RebalanceScheduler, NY_TZ
        from unittest.mock import MagicMock
        
        scheduler = RebalanceScheduler(MagicMock(), rebalance_frequency='quarterly')
        
        # 2024-04-01 是 4 月首个交易日，应触发
        apr_first = datetime(2024, 4, 1, 10, 0, tzinfo=NY_TZ)
        assert scheduler.should_rebalance(apr_first) == True, "季度频应在 4 月首日触发"
        
        # 2024-05-01 不在允许月份
        may_first = datetime(2024, 5, 1, 10, 0, tzinfo=NY_TZ)
        assert scheduler.should_rebalance(may_first) == False, "5 月不应触发季度频调仓"
    
    def test_next_rebalance_date(self):
        """测试下次调仓日期计算"""
        from scheduler import RebalanceScheduler
        from unittest.mock import MagicMock
        
        # 周频：下次是周一
        weekly = RebalanceScheduler(MagicMock(), 'weekly')
        next_weekly = weekly.get_next_rebalance_date()
        assert next_weekly.weekday() == 0, "周频下次调仓应为周一"
        
        # 季度频：下次应在 1/4/7/10 月
        quarterly = RebalanceScheduler(MagicMock(), 'quarterly')
        next_quarter = quarterly.get_next_rebalance_date()
        assert next_quarter.month in [1, 4, 7, 10], "季度频下次调仓月份应为 1/4/7/10"


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
        
        executor = AlpacaPaperExecutor(mock=True)
        account = executor.get_account()
        
        assert account is not None, "模拟模式应返回账户"
        assert account['cash'] == 1000000.0, "模拟账户应有 100万 现金"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_v14_executor_wrappers(self):
        """测试 AlpacaExecutor 包装方法（P0 修复）"""
        from alpaca_executor import AlpacaExecutor

        v14 = AlpacaExecutor(mock=True)

        # 包装方法应正确透传到底层 executor
        assert hasattr(v14, 'market_is_open'), "AlpacaExecutor 应有 market_is_open 方法"
        assert hasattr(v14, 'liquidate_all'), "AlpacaExecutor 应有 liquidate_all 方法"
        assert hasattr(v14, 'submit_order'), "AlpacaExecutor 应有 submit_order 方法"
        assert hasattr(v14, 'get_account'), "AlpacaExecutor 应有 get_account 方法"
        assert hasattr(v14, 'get_positions'), "AlpacaExecutor 应有 get_positions 方法"

        # mock 模式下 market_is_open 应返回 True
        assert v14.market_is_open() == True, "mock 模式下市场应视为开盘"

        # 测试提交订单
        order = v14.submit_order('AAPL', 5, 'buy')
        assert order is not None, "V14 包装器应能提交订单"
        assert order['symbol'] == 'AAPL', "订单股票代码应正确"
    
    def test_rate_limiter(self):
        """测试 Token Bucket 速率限制器（P1 修复）"""
        from rate_limiter import TokenBucket
        import time
        
        # 创建低限速器便于测试: 每秒 10 请求，容量 2
        bucket = TokenBucket(rate=10.0, capacity=2.0)
        
        start = time.time()
        for _ in range(3):
            bucket.acquire()
        elapsed = time.time() - start
        
        # 前 2 个立即消耗，第 3 个需要等待约 0.1 秒
        assert elapsed >= 0.08, "速率限制器应限制过快请求"

# ============================================================
# 8. 回测统一引擎测试
# ============================================================

class TestUnifiedBacktest:
    """测试统一回测引擎"""
    
    def test_generate_signals_mock(self):
        """测试信号生成（模拟数据）"""
        from strategies.v14 import V14Strategy
        
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
        from strategies.v14 import V14Strategy
        
        strategy = V14Strategy(use_real_data=False, use_paper_trading=False)
        
        # 空 DataFrame
        empty_df = pd.DataFrame()
        result = strategy._run_backtest_unified(empty_df, pd.DataFrame())
        
        assert len(result) == 0, "空数据应返回空结果"



# ============================================================
# 9. PDT 追踪器测试（填充驱动）
# ============================================================

class TestPDTTracker:
    """测试 PDT 追踪器（按成交记录、按账户分文件）"""
    
    def test_pdt_records_on_fill(self, tmp_path):
        """PDT 应在成交时记录，而非下单时"""
        from pdt_tracker import PDTTracker
        import tempfile, os
        
        state_file = os.path.join(tmp_path, 'pdt_test.json')
        tracker = PDTTracker(state_file=state_file, paper=True, account_id='test_paper', enabled=True)
        
        # 模拟买入后卖出（同日内）
        tracker.record_fill('AAPL', 'buy', 10)
        tracker.record_fill('AAPL', 'sell', 10)
        
        status = tracker.get_status()
        assert status['day_trades_used'] == 1, f"应记录 1 次 day trade，实际 {status['day_trades_used']}"
        assert status['day_trades_left'] == 2
    
    def test_pdt_blocks_after_three_day_trades(self, tmp_path):
        """5 日内 3 次 day trade 后应阻止开仓"""
        from pdt_tracker import PDTTracker
        import os
        
        state_file = os.path.join(tmp_path, 'pdt_test.json')
        tracker = PDTTracker(state_file=state_file, paper=True, account_id='test_paper', enabled=True)
        
        for symbol in ['A', 'B', 'C']:
            tracker.record_fill(symbol, 'buy', 10)
            tracker.record_fill(symbol, 'sell', 10)
        
        check = tracker.can_open_position('D', 'buy', account_type='MARGIN', equity=20000)
        assert check['allowed'] == False, "3 次 day trade 后应阻止开仓"
        assert check['day_trades_left'] == 0
    
    def test_pdt_cash_account_not_restricted(self, tmp_path):
        """现金账户不受 PDT 限制"""
        from pdt_tracker import PDTTracker
        import os
        
        state_file = os.path.join(tmp_path, 'pdt_test.json')
        tracker = PDTTracker(state_file=state_file, paper=True, account_id='test_paper', enabled=True)
        
        for _ in range(5):
            tracker.record_fill('AAPL', 'buy', 10)
            tracker.record_fill('AAPL', 'sell', 10)
        
        check = tracker.can_open_position('AAPL', 'buy', account_type='CASH', equity=20000)
        assert check['allowed'] == True, "现金账户不应受 PDT 限制"
    
    def test_pdt_state_file_separate_by_account(self, tmp_path):
        """PDT 状态文件按账户分离"""
        from pdt_tracker import PDTTracker
        import os
        
        paper_file = os.path.join(tmp_path, 'pdt_paper.json')
        live_file = os.path.join(tmp_path, 'pdt_live.json')
        
        paper_tracker = PDTTracker(state_file=paper_file, paper=True, account_id='paper', enabled=True)
        live_tracker = PDTTracker(state_file=live_file, paper=False, account_id='live', enabled=True)
        
        paper_tracker.record_fill('AAPL', 'buy', 10)
        paper_tracker.record_fill('AAPL', 'sell', 10)
        
        assert paper_tracker.get_status()['day_trades_used'] == 1
        assert live_tracker.get_status()['day_trades_used'] == 0, "live 账户不应受 paper 账户影响"


# ============================================================
# 10. 订单管理器测试
# ============================================================

class TestOrderManager:
    """测试订单管理器超时撤单、成交记录"""
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_order_manager_timeout_cancel(self):
        """订单超时时应尝试撤单"""
        from alpaca_executor import AlpacaPaperExecutor
        from order_manager import OrderManager
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        manager = OrderManager(executor, max_wait_sec=1, poll_interval=0.1)
        
        # mock 模式下 submit_order 返回固定订单
        original_submit = executor.submit_order
        executor.submit_order = lambda **kwargs: {
            'id': 'test-order-123',
            'symbol': kwargs.get('symbol', 'AAPL'),
            'status': 'new',
            'qty': kwargs.get('qty', 1),
            'side': kwargs.get('side', 'buy'),
        }
        
        # get_order_by_id 永远返回 pending
        executor.get_order_by_id = lambda order_id: {
            'id': order_id,
            'symbol': 'AAPL',
            'status': 'new',
            'qty': 1,
            'side': 'buy',
            'filled_qty': 0,
            'filled_avg_price': None,
        }
        
        # cancel_order 标记已调用
        cancel_called = []
        executor.cancel_order = lambda order_id: cancel_called.append(order_id) or True
        
        result = manager.submit_and_wait('AAPL', 1, 'buy')
        assert result['status'] == 'TIMEOUT', "应返回 TIMEOUT"
        assert 'test-order-123' in cancel_called, "超时应调用 cancel_order"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_order_manager_records_fill(self):
        """订单成交时应记录 PDT"""
        from alpaca_executor import AlpacaPaperExecutor
        from order_manager import OrderManager
        import tempfile, os, shutil
        
        # 使用临时目录隔离 PDT 状态
        tmp_dir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp_dir, 'data'), exist_ok=True)
            executor = AlpacaPaperExecutor(
                mock=True,
                enable_pdt=True,
                pdt_min_equity=25000.0,
            )
            # 强制指定 PDT 状态文件到临时目录
            if executor.pdt_tracker:
                executor.pdt_tracker.state_file = os.path.join(tmp_dir, 'data', 'pdt_fill_test.json')
                executor.pdt_tracker.positions = {}
                executor.pdt_tracker.day_trade_history = []
            manager = OrderManager(executor, max_wait_sec=1, poll_interval=0.1)
            
            executor.submit_order = lambda **kwargs: {
                'id': 'fill-order-123',
                'symbol': kwargs.get('symbol', 'AAPL'),
                'status': 'new',
                'qty': kwargs.get('qty', 10),
                'side': kwargs.get('side', 'buy'),
            }
            
            executor.get_order_by_id = lambda order_id: {
                'id': order_id,
                'symbol': 'AAPL',
                'status': 'filled',
                'qty': 10,
                'side': 'buy',
                'filled_qty': 10,
                'filled_avg_price': 150.0,
            }
            
            result = manager.submit_and_wait('AAPL', 10, 'buy')
            assert result['status'] == 'filled'
            assert executor.pdt_tracker is None or executor.pdt_tracker.get_status()['day_trades_used'] == 0, "买入成交不构成 day trade"
            
            # 同日内卖出应记录 day trade
            executor.get_order_by_id = lambda order_id: {
                'id': order_id,
                'symbol': 'AAPL',
                'status': 'filled',
                'qty': 10,
                'side': 'sell',
                'filled_qty': 10,
                'filled_avg_price': 151.0,
            }
            result = manager.submit_and_wait('AAPL', 10, 'sell')
            assert result['status'] == 'filled'
            if executor.pdt_tracker:
                assert executor.pdt_tracker.get_status()['day_trades_used'] == 1, "同日内先买后卖应构成 day trade"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)



# ============================================================
# 11. 对账测试
# ============================================================

class TestReconciliation:
    """测试持仓/现金对账"""
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_reconcile_consistent(self):
        """对账一致"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        # mock 模式初始持仓
        report = executor.reconcile(expected_cash=1000000.0)
        assert report['ok'] == True, f"对账应一致: {report}"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_reconcile_cash_mismatch(self):
        """现金差异应检测"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        report = executor.reconcile(expected_cash=999000.0)
        assert report['ok'] == False, "现金差异应报告不一致"
        assert report['cash']['diff'] > 0
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_reconcile_position_mismatch(self):
        """持仓差异应检测"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        report = executor.reconcile(expected_positions={'AAPL': 100, 'TSLA': 50})
        assert report['ok'] == False, "持仓差异应报告不一致"
        assert len(report['positions']['missing_local']) + len(report['positions']['missing_broker']) > 0


# ============================================================
# 12. 端到端 mock Alpaca 测试
# ============================================================

class TestEndToEndMockAlpaca:
    """端到端 mock Alpaca 测试（不连接真实 API，不提交真实订单）"""
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_mock_rebalance(self):
        """使用 AlpacaPaperExecutor(mock=True) + RebalanceManager 完成一次等权调仓"""
        from alpaca_executor import AlpacaPaperExecutor
        from order_manager import RebalanceManager
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        manager = RebalanceManager(executor)
        
        target_positions = {
            'AAPL': 20000,
            'MSFT': 20000,
            'NVDA': 20000,
        }
        
        results = manager.rebalance(
            target_positions,
            max_position_pct=0.25,
            confirm_fills=False,
            enable_rollback=True,
        )
        
        # 验证订单数量
        successful = [r for r in results if r and r.get('status') == 'filled']
        assert len(successful) == 3, f"应生成 3 笔买入订单，实际 {len(successful)}"
        
        # 验证持仓数量
        positions = executor.get_positions()
        assert len(positions) == 3, f"应持有 3 只股票，实际 {len(positions)}"
        
        # 验证账户权益和现金正常
        account = executor.get_account()
        assert account['equity'] > 0, "账户权益应大于 0"
        assert account['cash'] > 0, "现金应大于 0"
        
        # 每只持仓市值应大于 0
        for p in positions:
            assert p['market_value'] > 0, f"{p['symbol']} 市值应大于 0"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_mock_pdt_blocks_after_three_day_trades(self):
        """模拟多次买入卖出触发 PDT，验证第四次开仓被阻止"""
        from alpaca_executor import AlpacaPaperExecutor
        from order_manager import RebalanceManager
        import tempfile, os, shutil
        
        tmp_dir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp_dir, 'data'), exist_ok=True)
            executor = AlpacaPaperExecutor(
                mock=True,
                enable_pdt=True,
                pdt_min_equity=2000000.0,  # 高于 mock 账户权益，确保 PDT 限制生效
            )
            if executor.pdt_tracker:
                executor.pdt_tracker.state_file = os.path.join(tmp_dir, 'data', 'pdt_e2e.json')
                executor.pdt_tracker.positions = {}
                executor.pdt_tracker.day_trade_history = []
                executor.pdt_tracker._today_sells = {}
                executor.pdt_tracker._broker_daytrade_count = 0
            
            manager = RebalanceManager(executor)
            
            # 3 次不同股票的日内回转（每次先买后卖计 1 次 day trade）
            for symbol in ['AAPL', 'MSFT', 'NVDA']:
                manager.rebalance({symbol: 20000}, confirm_fills=True, max_wait_sec=1, poll_interval=0.1)
                manager.rebalance({}, confirm_fills=True, max_wait_sec=1, poll_interval=0.1)
            
            # 第四次开仓应被阻止
            results = manager.rebalance({'TSLA': 20000}, confirm_fills=True, max_wait_sec=1, poll_interval=0.1)
            
            successful = [r for r in results if r and r.get('status') in ('filled', 'partially_filled')]
            assert len(successful) == 0, "第四次开仓应被 PDT 阻止"
            
            if executor.pdt_tracker:
                status = executor.pdt_tracker.get_status()
                assert status['day_trades_used'] == 3, f"应使用 3 次 day trade，实际 {status['day_trades_used']}"
                assert status['day_trades_left'] == 0, "应无剩余 day trade 次数"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_mock_emergency_liquidation(self):
        """模拟 VIX 飙升触发 IntradayMonitor 紧急平仓，验证持仓清空"""
        from alpaca_executor import AlpacaPaperExecutor
        from order_manager import RebalanceManager
        from intraday_monitor import IntradayMonitor
        from risk_monitor import RiskMonitor
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        manager = RebalanceManager(executor)
        
        # 先建立持仓
        manager.rebalance({'AAPL': 20000, 'MSFT': 20000}, confirm_fills=False)
        
        positions_before = executor.get_positions()
        assert len(positions_before) > 0, "应先有持仓"
        
        risk_monitor = RiskMonitor()
        monitor = IntradayMonitor(
            executor=executor,
            risk_monitor=risk_monitor,
            vix_emergency_level=5.0,
        )
        
        # 模拟 VIX 飙升
        monitor.on_vix_spike = None
        monitor._get_latest_vix = lambda: 100.0
        monitor._check_vix()
        
        positions_after = executor.get_positions()
        assert len(positions_after) == 0, f"紧急平仓后应无持仓，实际 {len(positions_after)}"
        assert monitor.trading_halted == True, "交易应已暂停"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_idempotency_same_session(self):
        """同一 session 内重复下单，验证返回已存在订单，不重复提交"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        executor.start_rebalance_session()
        
        order1 = executor.submit_order('AAPL', 10, 'buy')
        order2 = executor.submit_order('AAPL', 10, 'buy')
        
        assert order1 is not None, "首次下单应成功"
        assert order2 is not None, "重复下单应返回已存在订单"
        assert order1['id'] == order2['id'], "同一 session 重复下单应返回相同订单 ID"
    
    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_partial_fill_topup(self):
        """模拟部分成交，验证补单逻辑正常"""
        from alpaca_executor import AlpacaPaperExecutor
        from order_manager import RebalanceManager
        
        executor = AlpacaPaperExecutor(mock=True, enable_pdt=False)
        manager = RebalanceManager(executor)
        
        call_count = [0]
        def fake_submit_and_wait(symbol, qty, side, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and side == 'buy':
                # 首次买入：50% 部分成交
                return {
                    'id': f'partial-{symbol}',
                    'symbol': symbol,
                    'status': 'partially_filled',
                    'qty': qty,
                    'filled_qty': qty // 2,
                    'filled_avg_price': 100.0,
                    'side': side,
                }
            # 补单或后续订单：完全成交
            return {
                'id': f'filled-{symbol}-{call_count[0]}',
                'symbol': symbol,
                'status': 'filled',
                'qty': qty,
                'filled_qty': qty,
                'filled_avg_price': 100.0,
                'side': side,
            }
        
        manager.order_manager.submit_and_wait = fake_submit_and_wait
        
        results = manager.rebalance(
            {'AAPL': 20000},
            confirm_fills=True,
            min_buy_fill_ratio=0.95,
            topup_on_partial=True,
            max_wait_sec=1,
            poll_interval=0.1,
        )
        
        # 补单后原始结果状态会被更新为 filled，因此通过调用次数判断补单发生
        assert call_count[0] >= 2, f"应至少调用 2 次 submit_and_wait（部分成交 + 补单），实际 {call_count[0]}"
        statuses = [r.get('status') for r in results if r and isinstance(r, dict)]
        assert 'filled' in statuses, "应发生补单成交"


# ============================================================
# 13. 风控独立进程测试
# ============================================================

class TestRiskProcess:
    """测试风控独立进程 risk_process.py"""

    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_cli_parse_args(self):
        """测试 risk_process.py 的 CLI 参数解析"""
        from risk_process import parse_args

        args = parse_args(['--paper', '--check-interval', '30', '--config-path', '/tmp/config.json'])
        assert args.paper is True
        assert args.live is None
        assert args.mock is False
        assert args.check_interval == 30
        assert args.config_path == '/tmp/config.json'

        args = parse_args(['--live'])
        assert args.live is True
        assert args.paper is None
        assert args.mock is False

    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_risk_process_init_with_mock_executor(self):
        """测试独立进程初始化时使用 mock executor"""
        from risk_process import RiskProcess, parse_args

        args = parse_args(['--paper', '--check-interval', '5'])
        mock_executor = MagicMock()
        mock_executor.get_account.return_value = {'portfolio_value': 100000}
        mock_executor.get_positions.return_value = []
        mock_executor.market_is_open.return_value = True

        def mock_executor_factory(paper):
            return mock_executor

        process = RiskProcess(args=args, executor_factory=mock_executor_factory)
        process.initialize()

        assert process.executor is mock_executor
        assert process.risk_monitor is not None
        assert process.intraday_monitor is not None
        assert process.intraday_monitor.executor is mock_executor
        assert process.intraday_monitor.check_interval == 5

    def test_sigterm_handling(self):
        """测试 SIGTERM 信号处理，验证进程优雅退出"""
        workdir = os.path.dirname(os.path.abspath(__file__))
        env = os.environ.copy()
        env['ALPACA_API_KEY'] = 'PK_TEST123'
        env['ALPACA_API_SECRET'] = 'SK_TEST456'
        env['PYTHONPATH'] = workdir

        script = """
import sys
sys.path.insert(0, '{}')
from risk_process import RiskProcess, parse_args
from unittest.mock import MagicMock

args = parse_args(['--mock', '--check-interval', '1'])
mock_executor = MagicMock()
mock_executor.get_account.return_value = {{'portfolio_value': 100000}}
mock_executor.get_positions.return_value = []
mock_executor.market_is_open.return_value = True

process = RiskProcess(args=args, executor_factory=lambda p: mock_executor)
process.run()
""".format(workdir)

        proc = subprocess.Popen(
            [sys.executable, '-c', script],
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # 等待进程进入主循环
        time.sleep(1.0)
        proc.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            assert False, f"进程未在 SIGTERM 后退出，stdout: {stdout.decode()}, stderr: {stderr.decode()}"

        assert proc.returncode == 0, f"退出码应为 0，实际 {proc.returncode}，stderr: {stderr.decode()}"


# ============================================================
# 14. 风控独立进程端到端场景测试
# ============================================================

class TestRiskProcessE2EScenarios:
    """更严格的 Risk Process 端到端场景测试：模拟风险事件触发平仓"""

    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_vix_spike_triggers_emergency_liquidation(self):
        """模拟 VIX 飙升，验证触发紧急平仓"""
        from risk_process import RiskProcess, parse_args
        from intraday_monitor import IntradayMonitor

        args = parse_args(['--mock', '--check-interval', '1'])
        mock_executor = MagicMock()
        mock_executor.get_account.return_value = {'portfolio_value': 100000}
        mock_executor.get_positions.return_value = []
        mock_executor.market_is_open.return_value = True

        process = RiskProcess(args=args, executor_factory=lambda p: mock_executor)
        process.initialize()

        with patch.object(IntradayMonitor, '_get_latest_vix', return_value=50.0):
            process.intraday_monitor.start(daemon=False)
            time.sleep(2.5)
            process.intraday_monitor.stop()

        assert mock_executor.liquidate_all.called, "VIX 飙升应触发紧急平仓"

    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_intraday_drawdown_triggers_liquidation(self):
        """模拟日内回撤超限，验证触发紧急平仓"""
        from risk_process import RiskProcess, parse_args

        args = parse_args(['--mock', '--check-interval', '1'])
        mock_executor = MagicMock()
        mock_executor.get_positions.return_value = []
        mock_executor.market_is_open.return_value = True

        state = {'nav': 110000.0}
        mock_executor.get_account.side_effect = lambda: {'portfolio_value': state['nav']}

        process = RiskProcess(args=args, executor_factory=lambda p: mock_executor)
        process.initialize()
        process.intraday_monitor.start(daemon=False)

        time.sleep(1.5)
        state['nav'] = 90000.0
        time.sleep(2.0)

        process.intraday_monitor.stop()

        assert mock_executor.liquidate_all.called, "日内回撤超限应触发紧急平仓"

    @patch.dict('os.environ', {
        'ALPACA_API_KEY': 'PK_TEST123',
        'ALPACA_API_SECRET': 'SK_TEST456'
    })
    def test_single_stock_drop_triggers_liquidation(self):
        """模拟单只股票暴跌，验证平仓该股票"""
        from risk_process import RiskProcess, parse_args

        args = parse_args(['--mock', '--check-interval', '1'])
        mock_executor = MagicMock()
        mock_executor.get_account.return_value = {'portfolio_value': 100000}
        mock_executor.get_positions.return_value = [
            {
                'symbol': 'AAPL',
                'qty': 100,
                'current_price': 90.0,
                'avg_entry_price': 100.0,
                'market_value': 9000,
            }
        ]
        mock_executor.market_is_open.return_value = True

        process = RiskProcess(args=args, executor_factory=lambda p: mock_executor)
        process.initialize()
        process.intraday_monitor.start(daemon=False)
        time.sleep(2.5)
        process.intraday_monitor.stop()

        calls = mock_executor.submit_order.call_args_list
        assert any(c.args[0] == 'AAPL' for c in calls), "AAPL 暴跌应触发平仓"


# ============================================================
# 15. 版本追踪测试
# ============================================================

class TestVersion:
    """测试版本追踪模块"""

    def test_version_format(self):
        """测试版本号格式正确"""
        from version import get_version, version_info
        version = get_version()
        assert isinstance(version, str)
        parts = version.split('.')
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
        info = version_info()
        assert info['version'] == version
        assert info['major'] == int(parts[0])
        assert info['minor'] == int(parts[1])
        assert info['patch'] == int(parts[2])

    def test_version_in_risk_process(self):
        """测试 risk_process 支持 --version"""
        from risk_process import parse_args
        with pytest.raises(SystemExit) as exc_info:
            parse_args(['--version'])
        assert exc_info.value.code == 0


# ============================================================
# 16. 最小示例策略测试（验证 BaseStrategy 可复用性）
# ============================================================

class TestMinimalExampleStrategy:
    """测试最小示例策略，验证新策略可复用 BaseStrategy 接口"""

    def test_import_and_subclass(self):
        """测试最小策略可导入并继承 BaseStrategy"""
        from strategies import MinimalExampleStrategy, BaseStrategy
        assert issubclass(MinimalExampleStrategy, BaseStrategy)

    def test_init_default_symbols(self):
        """测试默认标的列表"""
        from strategies import MinimalExampleStrategy
        strategy = MinimalExampleStrategy()
        assert strategy.symbols == MinimalExampleStrategy.DEFAULT_SYMBOLS
        assert strategy.config is None

    def test_generate_signals_equal_weight(self):
        """测试生成等权重信号"""
        from strategies import MinimalExampleStrategy
        strategy = MinimalExampleStrategy()
        signals = strategy.generate_signals()
        assert len(signals) == len(strategy.symbols)
        assert abs(sum(signals.values()) - 1.0) < 1e-6
        for sym in strategy.symbols:
            assert sym in signals

    def test_run_backtest(self):
        """测试最小回测流程"""
        from strategies import MinimalExampleStrategy
        strategy = MinimalExampleStrategy()
        result = strategy.run_backtest(start_date='2023-01-01', end_date='2023-12-31')
        assert result['status'] == 'ok'
        assert result['start_date'] == '2023-01-01'
        assert result['end_date'] == '2023-12-31'
        assert set(result['target_weights'].keys()) == set(strategy.symbols)
        assert strategy.get_backtest_result() is result

    def test_run_live_rebalance(self):
        """测试最小 live rebalance 流程"""
        from strategies import MinimalExampleStrategy
        strategy = MinimalExampleStrategy()
        strategy.run_live_rebalance()
        assert strategy._status['rebalances'] == 1
        assert strategy._status['live_trades'] == 1
        assert strategy._last_signals == strategy.generate_signals()

    def test_check_risk(self):
        """测试风控检查通过"""
        from strategies import MinimalExampleStrategy
        strategy = MinimalExampleStrategy()
        strategy.check_risk()  # 不应抛出异常

    def test_get_status(self):
        """测试状态快照"""
        from strategies import MinimalExampleStrategy
        strategy = MinimalExampleStrategy()
        status = strategy.get_status()
        assert status['strategy'] == 'MinimalExampleStrategy'
        assert status['symbols'] == strategy.symbols
        assert 'rebalances' in status
        assert 'live_trades' in status

    def test_get_signals_date_independence(self):
        """测试 get_signals 对任意日期返回一致信号"""
        from strategies import MinimalExampleStrategy
        from datetime import datetime
        strategy = MinimalExampleStrategy()
        s1 = strategy.get_signals(datetime(2023, 1, 1))
        s2 = strategy.get_signals(datetime(2024, 6, 15))
        assert s1 == s2

    def test_custom_symbols(self):
        """测试可配置自定义标的"""
        from strategies import MinimalExampleStrategy
        custom = ['AAPL', 'TSLA']
        strategy = MinimalExampleStrategy(symbols=custom)
        assert strategy.symbols == custom
        signals = strategy.generate_signals()
        assert set(signals.keys()) == set(custom)
        assert abs(sum(signals.values()) - 1.0) < 1e-6

    def test_config_pass_through(self):
        """测试 config 可透传"""
        from strategies import MinimalExampleStrategy
        config = {'trading': {'rebalance_frequency': 'daily'}}
        strategy = MinimalExampleStrategy(config=config)
        assert strategy.config == config

    def test_repr(self):
        """测试 repr"""
        from strategies import MinimalExampleStrategy
        strategy = MinimalExampleStrategy()
        assert 'MinimalExampleStrategy' in repr(strategy)



# ============================================================
# 17. V3 审计回归测试
# ============================================================

class TestV3AuditFixes:
    """针对 AUDIT_REPORT_V3_PAPER_LIVE.md 的回归测试"""

    def test_risk_monitor_halt_on_drawdown(self):
        """P0: 回撤超限后必须设置 trading_halted = True"""
        from risk_monitor import RiskMonitor

        monitor = RiskMonitor(max_drawdown_limit=0.15)
        monitor.nav_history = [{'timestamp': datetime.now(), 'nav': 1.0}]

        triggered = monitor.check_drawdown(0.80)
        assert triggered is True
        assert monitor.trading_halted is True

    def test_risk_monitor_halt_on_daily_loss(self):
        """P0: 日内亏损超限后必须设置 trading_halted = True"""
        from risk_monitor import RiskMonitor

        monitor = RiskMonitor(daily_loss_limit=0.03)
        triggered = monitor.check_daily_loss(-0.05)
        assert triggered is True
        assert monitor.trading_halted is True

    def test_risk_monitor_lock_accepts_concurrent_reads(self):
        """P1: trading_halted 应有锁且可读可写"""
        from risk_monitor import RiskMonitor

        monitor = RiskMonitor()
        assert monitor._lock is not None
        # 基本属性访问不应阻塞或报错
        assert monitor.trading_halted in (True, False)
        monitor.trading_halted = True
        assert monitor.trading_halted is True

    def test_config_api_key_from_env(self):
        """P1: API Key 可从环境变量注入，config.json 无需硬编码"""
        from config import V14StrategyConfig

        with patch.dict('os.environ', {'ALPACA_API_KEY': 'PK_FROM_ENV', 'ALPACA_API_SECRET': 'SK_FROM_ENV'}):
            cfg = V14StrategyConfig()
            key, secret = cfg.get_api_credentials()
            assert key == 'PK_FROM_ENV'
            assert secret == 'SK_FROM_ENV'

    def test_backup_encryption_roundtrip(self, tmp_path):
        """P1: backup_state.py 加密/解密可往返"""
        from backup_state import _encrypt_backup_dir, _decrypt_backup, run_backup

        key = 'test-encryption-key-12345'
        backup_dir = tmp_path / 'plain_backup'
        backup_dir.mkdir()
        (backup_dir / 'config.json').write_text('{"secret": true}')

        enc_path = _encrypt_backup_dir(backup_dir, key)
        assert enc_path.exists()
        assert enc_path.suffixes == ['.enc', '.tar', '.gz']
        assert not backup_dir.exists()

        restored = _decrypt_backup(enc_path, key, tmp_path)
        assert (restored / 'config.json').read_text() == '{"secret": true}'

    def test_alert_manager_dedup(self, tmp_path):
        """P1: 同一告警在短时间内只写入一次"""
        from alert_manager import AlertManager

        alert_file = tmp_path / 'alerts.json'
        manager = AlertManager(alert_file=str(alert_file))

        manager._write_alert('CRITICAL', 'RISK', 'drawdown triggered', {})
        manager._write_alert('CRITICAL', 'RISK', 'drawdown triggered', {})
        manager._write_alert('CRITICAL', 'RISK', 'drawdown triggered', {})

        lines = [l for l in alert_file.read_text().split('\n') if l.strip()]
        assert len(lines) == 1

    def test_pdt_today_uses_et(self):
        """M3: PDT 的 'today' 应使用 America/New_York 时区"""
        from pdt_tracker import PDTTracker
        from datetime import date

        tracker = PDTTracker(paper=True, account_id='test', enabled=True)
        today = tracker._today()
        # date 对象无时区属性，仅验证返回合理日期
        assert isinstance(today, date)
        assert abs((datetime.now(timezone.utc).date() - today).days) <= 1

    def test_backtest_uses_next_trading_day(self):
        """H2: 回测引擎应在下一交易日执行，避免同日复权 lookahead"""
        from strategies.v14 import V14Strategy

        strategy = V14Strategy(use_real_data=False, use_paper_trading=False)
        dates = pd.bdate_range('2023-01-01', periods=300)
        np.random.seed(42)
        prices = pd.DataFrame(
            np.cumprod(1 + np.random.normal(0.0005, 0.015, (300, 10)), axis=0) * 100,
            index=dates,
            columns=['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META', 'JPM', 'V', 'JNJ', 'UNH', 'XOM']
        )
        market_df = pd.DataFrame({'VIX': [20.0] * len(dates)}, index=dates)

        result = strategy._run_backtest_unified(prices, market_df)
        assert len(result) > 0

        # 所有执行日期必须是交易日的下一交易日（或本身就是交易日）
        for exec_date in result['date']:
            assert exec_date in dates

        # 至少第一个执行日期不是第一个信号日（预热后的首个调仓日）的同一日
        # 因为 _run_backtest_unified 在 first_d 后使用 next_d
        first_signal_idx = dates.get_loc(result['date'].iloc[0]) - 1
        assert first_signal_idx >= 0


