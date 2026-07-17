"""
配置验证模块 - 使用 pydantic 验证策略配置
防止无效配置导致交易错误
"""

from typing import Optional
import os
import json
from pydantic import BaseModel, Field, field_validator, ConfigDict


class RiskConfig(BaseModel):
    """风控配置"""
    vix_panic_threshold: float = Field(35.0, ge=10.0, le=100.0)
    max_position_pct: float = Field(0.20, gt=0.0, le=1.0)
    max_intraday_dd: float = Field(0.10, gt=0.0, le=0.5)
    single_stock_limit: float = Field(0.05, gt=0.0, le=0.5)
    
    @field_validator('vix_panic_threshold', mode='before')
    @classmethod
    def _load_vix_threshold_from_env(cls, v):
        """允许 VIX_PANIC_THRESHOLD 环境变量覆盖配置（环境变量优先）"""
        env = os.environ.get('VIX_PANIC_THRESHOLD')
        if env is not None:
            try:
                return float(env)
            except ValueError:
                raise ValueError(f"VIX_PANIC_THRESHOLD 必须是数值: {env}")
        return v
    
    @field_validator('max_position_pct', mode='before')
    @classmethod
    def _load_max_position_pct_from_env(cls, v):
        """允许 MAX_POSITION_PCT 环境变量覆盖配置（环境变量优先）"""
        env = os.environ.get('MAX_POSITION_PCT')
        if env is not None:
            try:
                return float(env)
            except ValueError:
                raise ValueError(f"MAX_POSITION_PCT 必须是数值: {env}")
        return v
    
    @field_validator('max_intraday_dd', mode='before')
    @classmethod
    def _load_max_drawdown_limit_from_env(cls, v):
        """允许 MAX_DRAWDOWN_LIMIT 环境变量覆盖配置（环境变量优先）"""
        env = os.environ.get('MAX_DRAWDOWN_LIMIT')
        if env is not None:
            try:
                return float(env)
            except ValueError:
                raise ValueError(f"MAX_DRAWDOWN_LIMIT 必须是数值: {env}")
        return v
    
    @field_validator('vix_panic_threshold')
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
    max_wait_sec: int = Field(1800, ge=30, le=1800)
    poll_interval: int = Field(5, ge=1, le=60)
    # P1 修复：收盘前 N 分钟拒绝启动新调仓
    market_close_cutoff_minutes: int = Field(15, ge=0, le=240)
    
    # PDT 检查配置
    enable_pdt_check: bool = True
    pdt_min_equity: float = Field(25000.0, ge=0)
    
    # 限价单配置
    use_limit_orders: bool = False
    limit_order_offset_pct: float = Field(0.001, ge=0.0001, le=0.05)
    
    # 调仓频率（通过项目下的 config.json 配置，不依赖环境变量）
    # monthly/bimonthly/quarterly/weekly 参考 QC 风格：在允许月份的首个交易日开盘后 30 分钟执行
    # daily 为每个交易日收盘后执行
    rebalance_frequency: str = Field('monthly', pattern='^(monthly|bimonthly|quarterly|weekly|daily)$')
    
    @field_validator('rebalance_frequency')
    @classmethod
    def rebalance_frequency_must_be_valid(cls, v):
        """调仓频率必须是 monthly / bimonthly / quarterly / weekly / daily 之一"""
        if v not in ('monthly', 'bimonthly', 'quarterly', 'weekly', 'daily'):
            raise ValueError("rebalance_frequency 必须是 'monthly' / 'bimonthly' / 'quarterly' / 'weekly' / 'daily'")
        return v
    
    @field_validator('market_close_cutoff_minutes')
    def cutoff_reasonable(cls, v):
        if v < 0 or v > 240:
            raise ValueError('收盘前保护时间应在 0-240 分钟之间')
        return v
    
    @field_validator('check_interval')
    def check_interval_not_too_fast(cls, v):
        if v < 10:
            raise ValueError('检查间隔不应 < 10秒，避免 CPU 100%')
        return v
    
    @field_validator('limit_order_offset_pct')
    def limit_offset_reasonable(cls, v):
        if v > 0.05:
            raise ValueError('限价单偏移比例不应 > 5%')
        return v


class WeightConfig(BaseModel):
    """权重配置"""
    method: str = Field('equal', pattern='^(equal|risk_parity|min_variance|momentum_weighted)$')
    max_weight: float = Field(0.20, gt=0.0, le=0.5)
    min_weight: float = Field(0.01, gt=0.0, le=0.1)


class V14StrategyConfig(BaseModel):
    """V14 策略总配置"""
    model_config = ConfigDict(validate_assignment=True, extra='ignore')
    
    risk: RiskConfig = RiskConfig()
    trading: TradingConfig = TradingConfig()
    weight: WeightConfig = WeightConfig()
    
    # Alpaca API Key/Secret（从环境变量读取，不硬编码）
    # P1修复: 增加非空校验，但允许通过环境变量注入
    alpaca_api_key: str = Field(default='')
    alpaca_api_secret: str = Field(default='')
    
    @field_validator('alpaca_api_key', mode='before')
    @classmethod
    def _load_api_key_from_env(cls, v):
        """P1修复: 允许 ALPACA_API_KEY 环境变量注入"""
        if v is None or v == '':
            env_key = os.environ.get('ALPACA_API_KEY')
            if env_key:
                return env_key
        return v or ''
    
    @field_validator('alpaca_api_secret', mode='before')
    @classmethod
    def _load_api_secret_from_env(cls, v):
        """P1修复: 允许 ALPACA_API_SECRET 环境变量注入"""
        if v is None or v == '':
            env_secret = os.environ.get('ALPACA_API_SECRET')
            if env_secret:
                return env_secret
        return v or ''
    
    @field_validator('alpaca_api_key')
    @classmethod
    def api_key_must_be_set(cls, v):
        """P1修复: API Key 必须非空"""
        if not v or not v.strip():
            raise ValueError('ALPACA_API_KEY 不能为空，请通过环境变量或构造函数传入')
        return v
    
    @field_validator('alpaca_api_secret')
    @classmethod
    def api_secret_must_be_set(cls, v):
        """P1修复: API Secret 必须非空"""
        if not v or not v.strip():
            raise ValueError('ALPACA_API_SECRET 不能为空，请通过环境变量或构造函数传入')
        return v
    
    # Alpaca 配置（从环境变量读取，不硬编码）
    alpaca_base_url: str = Field(
        default='https://paper-api.alpaca.markets',
        pattern=r'^https://(paper-)?api\.alpaca\.markets$'
    )
    
    @field_validator('alpaca_base_url', mode='before')
    @classmethod
    def _load_base_url_from_env(cls, v):
        """P1 修复：允许 ALPACA_BASE_URL 环境变量覆盖配置，未设置时使用默认值"""
        env_url = os.environ.get('ALPACA_BASE_URL')
        if env_url:
            return env_url
        if v is None or v == '':
            return 'https://paper-api.alpaca.markets'
        return v
    
    @field_validator('alpaca_base_url')
    @classmethod
    def base_url_must_be_valid(cls, v):
        """P1 修复：base_url 必须是 Alpaca 官方域名，防止错误配置导致订单发往未知地址"""
        if not v.startswith('https://'):
            raise ValueError('alpaca_base_url 必须以 https:// 开头')
        if v not in ('https://paper-api.alpaca.markets', 'https://api.alpaca.markets'):
            raise ValueError('alpaca_base_url 必须是 https://paper-api.alpaca.markets 或 https://api.alpaca.markets')
        return v


# 全局配置实例
_config_instance: Optional[V14StrategyConfig] = None


def get_config() -> V14StrategyConfig:
    """获取全局配置（单例）
    优先读取项目根目录下的 config.json，不存在时使用默认配置
    """
    global _config_instance
    if _config_instance is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        kwargs = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    kwargs = json.load(f)
            except Exception as e:
                # 不抛异常，避免配置损坏导致服务无法启动
                print(f"⚠️ 读取 config.json 失败，使用默认配置: {e}")
        _config_instance = V14StrategyConfig(**kwargs)
    return _config_instance


def set_config(config: V14StrategyConfig):
    """设置全局配置"""
    global _config_instance
    _config_instance = config


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    # P1修复: 若环境变量未设置，演示配置验证失败；
    # 正常使用时请通过环境变量或构造函数传入真实凭证。
    try:
        # 创建有效配置
        config = V14StrategyConfig()
        print(f"VIX 阈值: {config.risk.vix_panic_threshold}")
        print(f"最大仓位: {config.risk.max_position_pct:.0%}")
        print(f"检查间隔: {config.trading.check_interval}秒")
        print(f"Alpaca Base URL: {config.alpaca_base_url}")
        if config.alpaca_api_key:
            print(f"Alpaca API Key: {config.alpaca_api_key[:4]}...")
    except ValueError as e:
        print(f"\n❌ 配置验证失败: {e}")
        print("   请设置 ALPACA_API_KEY 和 ALPACA_API_SECRET 环境变量，或传入真实凭证。")
    
    # 尝试无效配置（会报错）
    try:
        bad_config = V14StrategyConfig(
            risk=RiskConfig(vix_panic_threshold=15)  # 太低
        )
    except ValueError as e:
        print(f"\n❌ 配置验证失败: {e}")
    
    try:
        # 尝试修改后验证
        config = V14StrategyConfig(
            alpaca_api_key=os.environ.get('ALPACA_API_KEY', 'PK_EXAMPLE'),
            alpaca_api_secret=os.environ.get('ALPACA_API_SECRET', 'SK_EXAMPLE'),
        )
        config.risk.vix_panic_threshold = 40.0  # 有效
        print(f"\n✅ 更新后 VIX 阈值: {config.risk.vix_panic_threshold}")
        
        try:
            config.risk.max_position_pct = 1.5  # 超出范围
        except ValueError as e:
            print(f"❌ 赋值验证失败: {e}")
    except ValueError as e:
        print(f"\n❌ 配置验证失败: {e}")
