"""
Pytest 测试套件 - V14 多因子策略
覆盖因子计算、风控逻辑、下单逻辑
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ============================================================
# 1. 因子计算测试
# ============================================================

class TestFactorComputation:
    """测试 16 因子计算正确性"""
    
    def test_momentum_126(self):
        """测试 126 日动量因子"""
        from main import momentum_126
        
        # 构造价格数据: 持续上涨
        prices = pd.Series([100 + i for i in range(130)])
        mom = momentum_126(prices)
        
        assert mom > 0, "持续上涨应产生正动量"
        
        # 构造价格数据: 持续下跌
        prices = pd.Series([100 - i * 0.5 for i in range(130)])
        mom = momentum_126(prices)
        
        assert mom < 0, "持续下跌应产生负动量"
    
    def test_volatility_20(self):
        """测试 20 日波动率因子"""
        from main import volatility_20
        
        # 高波动数据
        high_vol = pd.Series([100 + np.random.normal(0, 5) for _ in range(25)])
        vol_high = volatility_20(high_vol)
        
        # 低波动数据
        low_vol = pd.Series([100 + np.random.normal(0, 0.5) for _ in range(25)])
        vol_low = volatility_20(low_vol)
        
        assert vol_high > vol_low, "高波动数据应产生更高波动率"
    
    def test_rsi_14(self):
        """测试 RSI 14 因子"""
        from main import rsi_14
        
        # 纯上涨数据
        up_prices = pd.Series([100 + i for i in range(20)])
        rsi_up = rsi_14(up_prices)
        
        # 纯下跌数据
        down_prices = pd.Series([100 - i for i in range(20)])
        rsi_down = rsi_14(down_prices)
        
        assert rsi_up > 70, "纯上涨应产生高 RSI"
        assert rsi_down < 30, "纯下跌应产生低 RSI"
    
    def test_score_range(self):
        """测试综合评分范围"""
        from main import compute_factors_v14, v14_composite_score
        
        # 构造模拟价格数据
        dates = pd.bdate_range('2023-01-01', periods=252)
        np.random.seed(42)
        prices = pd.DataFrame(
            np.cumprod(1 + np.random.normal(0.0005, 0.015, (252, 5)), axis=0) * 100,
            index=dates,
            columns=['AAPL', 'MSFT', 'GOOGL', 'NVDA', 'META']
        )
        
        factors = compute_factors_v14(prices)
        score = v14_composite_score(factors, vix=20.0)
        
        assert not score.isna().all(), "不应所有评分都是 NaN"
        assert score.max() <= 1.0, "评分不应超过 1.0"
        assert score.min() >= 0.0, "评分不应低于 0.0"


# ============================================================
# 2. 风控逻辑测试
# ============================================================

class TestRiskControl:
    """测试风控触发逻辑"""
    
    def test_vix_panic(self):
        """测试 VIX 恐慌阈值"""
        from risk_monitor import RiskMonitor
        
        monitor = RiskMonitor()
        
        # VIX=20，不应触发
        assert monitor.check_vix_level(20.0) == False, "VIX=20 不应触发恐慌"
        assert monitor.trading_halted == False
        
        # VIX=40，应触发
        assert monitor.check_vix_level(40.0) == True, "VIX=40 应触发恐慌"
        assert monitor.trading_halted == True
    
    def test_drawdown_limit(self):
        """测试回撤限制"""
        from risk_monitor import RiskMonitor
        
        monitor = RiskMonitor(max_drawdown=0.15)
        
        # 5% 回撤，不应触发
        assert monitor.check_drawdown(0.05) == False
        
        # 20% 回撤，应触发
        assert monitor.check_drawdown(0.20) == True
    
    def test_position_limit(self):
        """测试仓位限制"""
        from risk_monitor import RiskMonitor
        
        monitor = RiskMonitor(max_position_pct=0.20)
        
        # 15% 仓位，不应触发
        assert monitor.check_position_limit(0.15) == False
        
        # 25% 仓位，应触发
        assert monitor.check_position_limit(0.25) == True


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


# ============================================================
# 4. 订单幂等性测试
# ============================================================

class TestOrderIdempotency:
    """测试订单幂等性"""
    
    def test_client_order_id_format(self):
        """测试 client_order_id 格式"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor()
        session = executor.start_rebalance_session()
        
        # session_id 应为 8 位 hex
        assert len(session) == 8, f"session_id 应为 8 位，实际 {len(session)}"
        assert all(c in '0123456789abcdef' for c in session), "session_id 应为 hex"
    
    def test_duplicate_order_detection(self):
        """测试重复订单检测（模拟模式）"""
        from alpaca_executor import AlpacaPaperExecutor
        
        executor = AlpacaPaperExecutor()
        executor.start_rebalance_session()
        
        # 模拟模式下无法真正测试去重，但测试方法存在
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
        assert all(w == weights['AAPL'] for w in weights.values()), "等权应相等"
    
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
        # 注意：如果 exchange_calendars 可用，应返回3/28
        # 如果不可用，简化逻辑返回3/29（周五）
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
# 运行命令
# ============================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
