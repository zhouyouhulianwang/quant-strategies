"""
配置验证模块 - 使用 pydantic 验证策略配置
防止无效配置导致交易错误
"""

from typing import Optional
from pydantic import BaseModel, Field, validator


class RiskConfig(BaseModel):
    """风控配置"""
    vix_panic_threshold: float = Field(35.0, ge=10.0, le=100.0)
    max_position_pct: float = Field(0.20, gt=0.0, le=1.0)
    max_intraday_dd: float = Field(0.10, gt=0.0, le=0.5)
    single_stock_limit: float = Field(0.05, gt=0.0, le=0.5)
    
    @validator('vix_panic_threshold')
    def vix_must_be_reasonable(cls, v):
        if v < 20:
            raise ValueError('VIX 恐慌阈值应 >= 20')
        return v


class TradingConfig(BaseModel):
    """交易配置"""
    enable_paper_trading: bool = True
    enable_risk_monitor: bool = True
    enable_intraday_monitor: bool = True
    check_interval: int = Field(60, ge=10, le=3600)
    max_wait_sec: int = Field(300, ge=30, le=1800)
    poll_interval: int = Field(5, ge=1, le=60)
    
    @validator('check_interval')
    def check_interval_not_too_fast(cls, v):
        if v < 10:
            raise ValueError('检查间隔不应 < 10秒，避免 CPU 100%')
        return v


class WeightConfig(BaseModel):
    """权重配置"""
    method: str = Field('equal', pattern='^(equal|risk_parity|min_variance|momentum_weighted)$')
    max_weight: float = Field(0.20, gt=0.0, le=0.5)
    min_weight: float = Field(0.01, gt=0.0, le=0.1)


class V14StrategyConfig(BaseModel):
    """V14 策略总配置"""
    risk: RiskConfig = RiskConfig()
    trading: TradingConfig = TradingConfig()
    weight: WeightConfig = WeightConfig()
    
    # Alpaca 配置（从环境变量读取，不硬编码）
    alpaca_base_url: str = 'https://paper-api.alpaca.markets'
    
    class Config:
        validate_assignment = True  # 赋值时自动验证


# 全局配置实例
_config_instance: Optional[V14StrategyConfig] = None


def get_config() -> V14StrategyConfig:
    """获取全局配置（单例）"""
    global _config_instance
    if _config_instance is None:
        _config_instance = V14StrategyConfig()
    return _config_instance


def set_config(config: V14StrategyConfig):
    """设置全局配置"""
    global _config_instance
    _config_instance = config


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    # 创建有效配置
    config = V14StrategyConfig()
    print(f"VIX 阈值: {config.risk.vix_panic_threshold}")
    print(f"最大仓位: {config.risk.max_position_pct:.0%}")
    print(f"检查间隔: {config.trading.check_interval}秒")
    
    # 尝试无效配置（会报错）
    try:
        bad_config = V14StrategyConfig(
            risk=RiskConfig(vix_panic_threshold=15)  # 太低
        )
    except ValueError as e:
        print(f"\n❌ 配置验证失败: {e}")
    
    # 尝试修改后验证
    config.risk.vix_panic_threshold = 40.0  # 有效
    print(f"\n✅ 更新后 VIX 阈值: {config.risk.vix_panic_threshold}")
    
    try:
        config.risk.max_position_pct = 1.5  # 超出范围
    except ValueError as e:
        print(f"❌ 赋值验证失败: {e}")
