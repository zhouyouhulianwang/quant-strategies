# LocalQuant 架构设计文档

**版本**: v1.0.0  
**日期**: 2026-07-13  
**作者**: Qs (AI Assistant)  
**目标**: 构建一个可媲美 QuantConnect 的本地化量化交易平台

---

## 1. 设计哲学

### 1.1 核心原则

- **Performance First**: 回测速度必须接近 Backtrader/Zipline 水平
- **QuantConnect Compatible**: 策略代码应可无缝迁移
- **Production Ready**: 实盘交易与回测引擎使用同一套核心逻辑
- **Modular**: 每个模块可独立替换（数据源、执行引擎、风控等）
- **Observable**: 每一步操作可审计、可回溯

### 1.2 技术选型理由

| 组件 | 选择 | 理由 |
|------|------|------|
| **语言** | Python 3.12+ | 量化生态最成熟，兼容 QC |
| **数据处理** | Pandas + Polars | Pandas 兼容，Polars 加速大数据量 |
| **存储** | Parquet + SQLite | Parquet 压缩率高读取快，SQLite 轻量 |
| **回测** | 自研事件驱动 | 完全控制，避免 Backtrader 的黑盒 |
| **可视化** | Plotly + Streamlit | Plotly 静态报告，Streamlit 交互调试 |
| **API** | FastAPI | 高性能，异步，自动生成文档 |
| **任务调度** | APScheduler | 轻量，适合单机量化任务 |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        API Layer                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  REST API   │  │  WebSocket  │  │   Web Dashboard     │  │
│  │  (FastAPI)  │  │  (实时推送)  │  │   (Streamlit)      │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                    Application Layer                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Strategy   │  │  Backtest   │  │   Live Trading      │  │
│  │  Manager    │  │   Engine    │  │      Engine         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Portfolio  │  │  Risk Mgr   │  │  Execution Mgr      │  │
│  │  Manager    │  │             │  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                    Core Engine Layer                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Event      │  │  Order      │  │   Position          │  │
│  │  System     │  │  Matching   │  │   Tracker           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Slippage   │  │  Commission │  │  Benchmark          │  │
│  │  Model      │  │   Model     │  │  Calculator         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│                      Data Layer                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Yahoo      │  │  CCXT       │  │   Local Cache       │  │
│  │  Finance    │  │ (Crypto)    │  │   (Parquet/SQLite)  │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  AKShare    │  │  IBKR API   │  │   Data Pipeline     │  │
│  │  (A股)      │  │  (实盘)     │  │   (ETL/清洗)        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
DataManager (数据源抽象)
    ├── YahooFinanceSource
    ├── CCXTSource
    ├── AKShareSource
    └── ParquetCache

BacktestEngine (回测核心)
    ├── EventQueue (事件队列)
    ├── Portfolio (投资组合)
    ├── Broker (经纪商模拟)
    ├── SlippageModel (滑点模型)
    └── CommissionModel (手续费模型)

Strategy (策略框架)
    ├── BaseStrategy (策略基类)
    ├── IndicatorLib (指标库)
    └── Context (策略上下文)

RiskManager (风险管理)
    ├── PositionLimit (仓位限制)
    ├── DrawdownGuard (回撤保护)
    ├── StopLossRule (止损规则)
    └── SectorLimit (板块限制)

LiveEngine (实盘引擎)
    ├── IBKRClient (盈透接口)
    ├── FutuClient (富途接口)
    ├── BinanceClient (币安接口)
    └── OrderRouter (订单路由)
```

---

## 3. 核心模块设计

### 3.1 回测引擎 (BacktestEngine)

**设计模式**: 事件驱动 (Event-Driven) + 状态机

**核心流程**:

```
1. 初始化阶段
   ├── 加载数据 (DataManager)
   ├── 初始化策略 (Strategy.initialize)
   ├── 设置日期范围
   └── 预热指标 (WarmUp)

2. 回测循环
   ├── 获取下一个 Bar 数据
   ├── 生成 MarketDataEvent
   ├── 策略 on_data() 处理
   ├── 策略生成 SignalEvent
   ├── 信号转换为 OrderEvent
   ├── 经纪商 execute_order()
   ├── 生成 FillEvent
   ├── 更新 Portfolio
   ├── 检查 RiskManager
   └── 记录 Analytics

3. 收尾阶段
   ├── 生成回测报告
   ├── 计算绩效指标
   ├── 输出交易明细
   └── 释放资源
```

**关键类设计**:

```python
class BacktestEngine:
    # 状态机
    state: EngineState = EngineState.INITIALIZED
    
    # 核心组件
    data_handler: DataHandler
    strategy: BaseStrategy
    portfolio: Portfolio
    broker: SimulatedBroker
    risk_manager: RiskManager
    
    # 事件系统
    event_queue: deque[Event]
    event_handlers: dict[EventType, list[Callable]]
    
    # 运行控制
    current_datetime: datetime
    current_prices: dict[str, float]
    
    def run(self) -> BacktestResult:
        # 主循环，事件驱动
        pass
    
    def place_order(self, order: OrderEvent) -> None:
        # 订单进入队列
        pass
    
    def _process_events(self) -> None:
        # 处理所有待处理事件
        pass
```

**性能优化**:
- 使用 `numba` 加速循环计算
- 批量处理订单（减少 DataFrame 操作）
- 预加载数据到内存（避免磁盘 I/O）
- 使用 `polars` 处理大数据量

### 3.2 数据管理 (DataManager)

**设计模式**: 仓储模式 (Repository Pattern) + 缓存策略

**数据流**:

```
用户请求数据
    │
    ├── 检查本地缓存 (Parquet)
    │   ├── 缓存命中 → 直接返回
    │   └── 缓存未命中 → 请求数据源
    │
    ├── 请求数据源
    │   ├── Yahoo Finance (美股)
    │   ├── CCXT (加密货币)
    │   └── AKShare (A股)
    │
    ├── 数据清洗
    │   ├── 处理缺失值
    │   ├── 复权调整
    │   └── 异常值检测
    │
    ├── 写入缓存
    │   └── Parquet 格式存储
    │
    └── 返回数据
```

**缓存策略**:
- **TTL 缓存**: 日线数据 1 天更新，分钟数据 1 小时更新
- **增量更新**: 只下载新增数据，合并到现有文件
- **分层存储**: 热数据（最近 1 年）在内存，冷数据在磁盘

### 3.3 策略框架 (Strategy Framework)

**设计目标**: 兼容 QuantConnect，同时支持更灵活的 Python 风格

**接口设计**:

```python
class BaseStrategy(ABC):
    """策略基类 - 兼容 QuantConnect 风格"""
    
    # 策略配置
    name: str = "BaseStrategy"
    symbols: list[str] = []
    
    # 运行时上下文（由引擎注入）
    context: StrategyContext
    _engine: BacktestEngine
    
    # 生命周期方法
    @abstractmethod
    def initialize(self) -> None:
        """初始化 - 设置参数、订阅数据、创建指标"""
        pass
    
    @abstractmethod
    def on_data(self, data: MarketDataEvent) -> None:
        """每个数据 bar 触发 - 核心逻辑"""
        pass
    
    def on_order_event(self, event: OrderEvent) -> None:
        """订单状态更新回调"""
        pass
    
    def on_fill(self, event: FillEvent) -> None:
        """成交回调"""
        pass
    
    # 交易方法
    def buy(self, symbol: str, quantity: int) -> None:
        """买入"""
        self._engine.place_order(symbol, quantity, OrderSide.BUY)
    
    def sell(self, symbol: str, quantity: int) -> None:
        """卖出"""
        self._engine.place_order(symbol, quantity, OrderSide.SELL)
    
    def target_percent(self, symbol: str, target_pct: float) -> None:
        """设置目标仓位百分比"""
        pass
    
    def liquidate(self, symbol: str) -> None:
        """清仓"""
        pass
    
    # 数据访问方法
    def get_history(self, symbol: str, field: str, lookback: int) -> pd.Series:
        """获取历史数据"""
        pass
    
    def get_price(self, symbol: str, field: str = 'close') -> float:
        """获取当前价格"""
        pass
```

**指标库设计**:

```python
class IndicatorLibrary:
    """技术指标库 - 支持向量化计算"""
    
    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()
    
    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        # 使用向量化计算，避免循环
        pass
    
    @staticmethod
    def macd(series: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
        pass
    
    @staticmethod
    def bollinger_bands(series: pd.Series, period: int, std_dev: float) -> pd.DataFrame:
        pass
```

### 3.4 风险管理 (RiskManager)

**设计模式**: 责任链模式 (Chain of Responsibility)

**风控规则链**:

```python
class RiskManager:
    rules: list[RiskRule]
    
    def check(self, portfolio: Portfolio, order: OrderEvent) -> RiskResult:
        for rule in self.rules:
            result = rule.check(portfolio, order)
            if not result.passed:
                return result
        return RiskResult(passed=True)

class RiskRule(ABC):
    @abstractmethod
    def check(self, portfolio: Portfolio, order: OrderEvent) -> RiskResult:
        pass

class MaxPositionSizeRule(RiskRule):
    """单标的最大仓位限制"""
    max_pct: float  # 如 0.15 = 15%
    
class MaxDrawdownRule(RiskRule):
    """最大回撤限制"""
    max_drawdown: float  # 如 0.15 = 15%
    
class StopLossRule(RiskRule):
    """止损规则"""
    stop_pct: float  # 如 0.08 = 8%
    
class TrailingStopRule(RiskRule):
    """移动止损规则"""
    trail_pct: float  # 如 0.10 = 10%
    
class SectorConcentrationRule(RiskRule):
    """板块集中度限制"""
    max_sector_pct: float  # 如 0.50 = 50%
    
class LiquidityRule(RiskRule):
    """流动性检查"""
    min_volume: int  # 最小成交量
```

### 3.5 投资组合 (Portfolio)

**核心职责**:
- 持仓管理（数量、成本、市值）
- 现金流管理
- 已实现/未实现盈亏计算
- 权益曲线记录

```python
class Position:
    symbol: str
    quantity: int
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float

class Portfolio:
    cash: float
    positions: dict[str, Position]
    history: list[PortfolioSnapshot]
    
    @property
    def total_value(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())
    
    @property
    def total_return(self) -> float:
        return (self.total_value / self.initial_cash - 1) * 100
    
    def execute_order(self, order: FillEvent) -> None:
        """执行订单，更新持仓"""
        pass
    
    def update_market(self, prices: dict[str, float]) -> None:
        """更新市场价格，计算市值"""
        pass
```

### 3.6 执行引擎 (Execution Engine)

**模拟经纪商**:

```python
class SimulatedBroker:
    """模拟经纪商 - 处理订单执行"""
    
    slippage_model: SlippageModel
    commission_model: CommissionModel
    
    def execute_order(self, order: OrderEvent, market_price: float) -> FillEvent:
        # 1. 应用滑点
        fill_price = self.slippage_model.apply(order, market_price)
        
        # 2. 计算手续费
        commission = self.commission_model.calculate(order, fill_price)
        
        # 3. 生成成交事件
        return FillEvent(
            symbol=order.symbol,
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
            timestamp=order.timestamp
        )

class SlippageModel(ABC):
    @abstractmethod
    def apply(self, order: OrderEvent, price: float) -> float:
        pass

class FixedSlippage(SlippageModel):
    """固定滑点"""
    slip_pct: float = 0.001  # 0.1%
    
class PercentageSlippage(SlippageModel):
    """百分比滑点（基于成交量）"""
    pass

class CommissionModel(ABC):
    @abstractmethod
    def calculate(self, order: OrderEvent, price: float) -> float:
        pass

class FixedCommission(CommissionModel):
    """固定费率"""
    rate: float = 0.001  # 0.1%
    min_commission: float = 1.0
```

---

## 4. 性能优化

### 4.1 回测速度优化

| 优化点 | 方案 | 预期提升 |
|--------|------|----------|
| 数据加载 | 预加载到内存，使用 Parquet | 10x |
| 循环计算 | Numba JIT 加速 | 5-10x |
| 大数据量 | Polars 替代 Pandas | 3-5x |
| 多策略 | 多进程并行回测 | 线性扩展 |
| 向量化 | 批量处理订单 | 2-3x |

### 4.2 内存优化

- 数据流式处理（不一次性加载全部数据）
- 使用 `gc.collect()` 管理内存
- 大 DataFrame 使用 `chunk` 处理

---

## 5. 测试策略

### 5.1 测试金字塔

```
        /\
       /  \
      / E2E\      (端到端回测测试)
     /--------\   
    /  Integration\ (集成测试：数据+引擎+策略)
   /----------------\
  /    Unit Tests    \ (单元测试：指标、事件、订单)
 /----------------------\
```

### 5.2 关键测试用例

1. **数据测试**: 验证数据完整性、复权正确性
2. **引擎测试**: 验证事件顺序、订单执行、资金计算
3. **策略测试**: 验证信号生成、参数敏感性
4. **风控测试**: 验证止损触发、仓位限制
5. **回归测试**: 与 QuantConnect 结果对比

---

## 6. 部署方案

### 6.1 本地开发模式

```bash
# 安装
pip install localquant

# 运行回测
localquant backtest --strategy my_strategy.py --symbols AAPL,MSFT --start 2020-01-01

# 启动 Web 界面
localquant dashboard
```

### 6.2 Docker 部署

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "localquant.web"]
```

### 6.3 实盘部署

- **云服务器**: AWS/GCP/Azure (低延迟靠近交易所)
- **本地服务器**: 树莓派/小型服务器（适合低频策略）
- **容器编排**: Docker Compose / Kubernetes

---

## 7. 开发路线图

### Phase 1: MVP (已完成 ✅)
- [x] 核心回测引擎
- [x] 数据管理 (Yahoo Finance)
- [x] 策略框架
- [x] 基础指标库
- [x] 绩效分析

### Phase 2: 策略验证 (已完成 ✅)
- [x] 适配 QuantConnect 策略
- [x] 参数优化框架
- [x] 可视化图表
- [x] Streamlit Dashboard

### Phase 3: 核心完善 (当前)
- [ ] 多数据源集成 (CCXT, AKShare)
- [ ] 分钟级回测支持
- [ ] 更丰富的指标库
- [ ] 参数优化遗传算法
- [ ] 完整测试覆盖

### Phase 4: 生产化
- [ ] 实盘交易接口 (IBKR, 富途, 币安)
- [ ] 实时数据流处理
- [ ] 监控与告警系统
- [ ] Docker 部署
- [ ] 文档完善

### Phase 5: 高级功能
- [ ] 机器学习策略
- [ ] 期权回测
- [ ] 多因子模型
- [ ] 风险归因分析
- [ ] 社区策略市场

---

## 8. 附录

### 8.1 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块 | 小写 + 下划线 | `backtest_engine.py` |
| 类 | 大驼峰 | `BacktestEngine` |
| 函数 | 小写 + 下划线 | `run_backtest()` |
| 常量 | 大写 + 下划线 | `MAX_POSITION_PCT` |
| 配置 | YAML/JSON | `config.yaml` |

### 8.2 日志规范

```python
import logging

logger = logging.getLogger(__name__)

# 日志级别
logger.debug("详细调试信息")
logger.info("策略初始化完成")
logger.warning("数据缺失，使用默认值")
logger.error("订单执行失败")
logger.critical("连接中断，停止交易")
```

### 8.3 错误处理

```python
from enum import Enum

class ErrorCode(Enum):
    DATA_NOT_FOUND = 1001
    ORDER_REJECTED = 2001
    RISK_LIMIT_HIT = 3001
    BROKER_DISCONNECTED = 4001

class LocalQuantError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        self.message = message
```

---

*本文档是 LocalQuant 的权威技术参考，所有开发应遵循此文档规范。*
