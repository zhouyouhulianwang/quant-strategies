"""
配置验证模块 - 使用 pydantic 验证策略配置
防止无效配置导致交易错误
"""

from typing import Optional, Dict, List
import os
import json
from pydantic import BaseModel, Field, field_validator, ConfigDict


class UniverseConfig(BaseModel):
    """股票池配置
    
    type: 内置股票池类型 (default|sp500|ndx100|sp500_ndx100|custom)
    当 type 为 custom 时，使用 tickers / ndx_count / industry_map 自定义
    """
    type: str = Field('default', pattern='^(default|sp500|ndx100|sp500_ndx100|custom)$')
    cap: int = Field(0, ge=0)  # 限制股票池数量，0 表示不限制
    tickers: List[str] = Field(default_factory=list)
    ndx_count: int = Field(default=35, ge=0)
    industry_map: Dict[str, str] = Field(default_factory=dict)

    @field_validator('tickers')
    @classmethod
    def tickers_must_be_unique_and_uppercase(cls, v):
        if not v:
            return v
        cleaned = [str(s).strip().upper() for s in v if str(s).strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError('universe.tickers 中不能存在重复股票代码')
        return cleaned

    @field_validator('ndx_count')
    @classmethod
    def ndx_count_not_exceed_universe(cls, v, info):
        tickers = (info.data or {}).get('tickers', [])
        if v > len(tickers):
            raise ValueError(f'ndx_count ({v}) 不能超过股票池数量 ({len(tickers)})')
        return v

    def ndx_set(self) -> set:
        return set(self.tickers[:self.ndx_count])

class RiskConfig(BaseModel):
    """风控配置"""
    vix_panic_threshold: float = Field(35.0, ge=10.0, le=100.0)
    max_position_pct: float = Field(0.20, gt=0.0, le=1.0)
    max_intraday_dd: float = Field(0.10, gt=0.0, le=0.5)
    single_stock_limit: float = Field(0.05, gt=0.0, le=0.5)
    max_drawdown_limit: float = Field(0.15, gt=0.0, le=1.0)

    # ---- 风险 overlay（动态杠杆 / 回撤守卫 / 市场状态调整）----
    risk_overlay_enabled: bool = False
    target_vol: float = Field(0.20, gt=0.0, le=1.0)
    max_leverage: float = Field(1.5, gt=0.0, le=5.0)
    min_leverage: float = Field(0.5, gt=0.0, le=2.0)
    
    @field_validator('max_drawdown_limit', mode='before')
    @classmethod
    def _load_max_drawdown_limit_from_env(cls, v):
        """允许 MAX_DRAWDOWN_LIMIT 环境变量覆盖累计回撤阈值（环境变量优先）"""
        env = os.environ.get('MAX_DRAWDOWN_LIMIT')
        if env is not None:
            try:
                return float(env)
            except ValueError:
                raise ValueError(f"MAX_DRAWDOWN_LIMIT 必须是数值: {env}")
        return v
    
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
    def _load_max_intraday_dd_from_env(cls, v):
        """允许 MAX_INTRADAY_DD 环境变量覆盖配置（环境变量优先）"""
        env = os.environ.get('MAX_INTRADAY_DD')
        if env is not None:
            try:
                return float(env)
            except ValueError:
                raise ValueError(f"MAX_INTRADAY_DD 必须是数值: {env}")
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
    max_wait_sec: int = Field(120, ge=30, le=1800)
    poll_interval: int = Field(5, ge=1, le=60)
    # P1 修复：收盘前 N 分钟拒绝启动新调仓
    market_close_cutoff_minutes: int = Field(15, ge=0, le=240)
    
    # PDT 检查配置
    enable_pdt_check: bool = True
    pdt_min_equity: float = Field(25000.0, ge=0)
    
    # 限价单配置
    use_limit_orders: bool = False
    limit_order_offset_pct: float = Field(0.001, ge=0.0001, le=0.05)
    
    # P2 修复：调仓前持仓对账开关
    enable_reconcile: bool = False
    
    # 调仓频率（通过项目下的 config.json 配置，不依赖环境变量）
    # monthly/bimonthly/quarterly/weekly 参考 QC 风格：在允许月份的首个交易日开盘后 30 分钟执行
    # daily 为每个交易日收盘后执行
    rebalance_frequency: str = Field('monthly', pattern='^(monthly|bimonthly|quarterly|weekly|daily)$')
    
    # 最小持仓金额：低于此值的目标持仓会被剔除
    min_position_value: float = Field(0.0, ge=0.0)
    
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
    universe: UniverseConfig = UniverseConfig()

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
    
    # Alpaca 配置（从环境变量读取，不硬编码）
    alpaca_base_url: str = Field(
        default='https://paper-api.alpaca.markets',
        pattern=r'^https://(paper-)?api\.alpaca\.markets$'
    )
    
    @field_validator('alpaca_base_url')
    @classmethod
    def base_url_must_be_valid(cls, v):
        """P1 修复：base_url 必须是 Alpaca 官方域名，防止错误配置导致订单发往未知地址"""
        if not v.startswith('https://'):
            raise ValueError('alpaca_base_url 必须以 https:// 开头')
        if v not in ('https://paper-api.alpaca.markets', 'https://api.alpaca.markets'):
            raise ValueError('alpaca_base_url 必须是 https://paper-api.alpaca.markets 或 https://api.alpaca.markets')
        return v
    
    def get_api_credentials(self):
        """P1 修复：运行时优先从环境变量获取 API 凭证，config.json 不保留真实 Key/Secret"""
        key = os.environ.get('ALPACA_API_KEY') or self.alpaca_api_key
        secret = os.environ.get('ALPACA_API_SECRET') or self.alpaca_api_secret
        return key, secret
    
    def require_api_credentials(self):
        """P1 修复：需要连接真实 API 时调用，明确报错信息"""
        key, secret = self.get_api_credentials()
        if not key or not key.strip():
            raise ValueError('ALPACA_API_KEY 未设置，请通过环境变量或构造函数传入')
        if not secret or not secret.strip():
            raise ValueError('ALPACA_API_SECRET 未设置，请通过环境变量或构造函数传入')
        return key, secret


# 全局配置实例
_config_instance: Optional[V14StrategyConfig] = None


def get_config(config_path: Optional[str] = None) -> V14StrategyConfig:
    """获取全局配置（单例）
    优先读取项目根目录下的 config.json；不存在时使用默认配置。
    若 config.json 存在但读取或解析失败，立即抛出异常以 fail-fast，
    避免错误配置导致交易行为不一致。
    """
    global _config_instance
    if _config_instance is None or config_path is not None:
        config_path = config_path or os.path.join(os.path.dirname(__file__), 'config.json')
        kwargs = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    kwargs = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"config.json 解析失败 ({config_path}): {e}") from e
            except OSError as e:
                raise ValueError(f"config.json 读取失败 ({config_path}): {e}") from e
        # 环境变量覆盖 base_url
        if 'ALPACA_BASE_URL' in os.environ:
            kwargs['alpaca_base_url'] = os.environ['ALPACA_BASE_URL']
        _config_instance = V14StrategyConfig(**kwargs)
    return _config_instance


def reload_config(config_path: Optional[str] = None):
    """P1 修复：重新加载 config.json，使运行时配置变更生效"""
    global _config_instance
    _config_instance = None
    return get_config(config_path=config_path)


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
