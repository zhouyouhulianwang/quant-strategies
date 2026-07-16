# LocalQuant - 本地量化交易平台规划

> 目标：构建一个类似 QuantConnect 的本地化量化交易框架，支持回测、策略开发、绩效分析，并可对接实盘。

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    LocalQuant Platform                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Web UI    │  │   CLI Tool  │  │   Jupyter Notebook  │  │
│  │  (Streamlit)│  │  (Click)    │  │   (分析 & 研究)      │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         └─────────────────┴────────────────────┘             │
│                            │                                 │
│  ┌─────────────────────────┴─────────────────────────────┐   │
│  │              Core Engine (Python)                      │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐  │   │
│  │  │  Data   │ │ Backtest│ │  Live   │ │  Portfolio  │  │   │
│  │  │ Manager │ │ Engine  │ │ Trading │ │   Manager   │  │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────────┘  │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐  │   │
│  │  │ Strategy│ │  Risk   │ │Execution│ │  Analytics  │  │   │
│  │  │ Framework│ │ Manager │ │ Engine  │ │   Engine    │  │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────────┘  │   │
│  └────────────────────────────────────────────────────────┘   │
│                            │                                 │
│  ┌─────────────────────────┴─────────────────────────────┐   │
│  │              Data Layer                                │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐  │   │
│  │  │  Local  │ │  Yahoo  │ │  CCXT   │ │ QuantConnect│  │   │
│  │  │  Cache  │ │ Finance │ │(Crypto) │ │   (Backup)  │  │   │
│  │  │ (Parquet)│ │         │ │         │ │             │  │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────────┘  │   │
│  └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、技术选型

| 模块 | 技术方案 | 理由 |
|------|----------|------|
| **核心引擎** | Python 3.12 + Pandas/NumPy | 生态成熟，与 QC 策略兼容 |
| **数据处理** | Parquet + SQLite/PostgreSQL | 高效存储，便于查询 |
| **回测引擎** | 自研 + Backtrader (参考) | 灵活可控，学习成本低 |
| **数据获取** | yfinance, CCXT, akshare | 免费数据源覆盖美股/A股/加密货币 |
| **可视化** | Streamlit / Gradio | 快速搭建，交互友好 |
| **API 接口** | FastAPI | 高性能，自动生成文档 |
| **任务调度** | APScheduler / Celery | 定时任务，策略执行 |
| **实盘交易** | IBKR API / 富途 / CCXT | 多券商支持 |

---

## 三、核心模块设计

### 3.1 数据管理模块 (Data Manager)

```python
# 功能：
# - 多数据源统一接口
# - 本地缓存与更新
# - 数据质量检查

class DataManager:
    def __init__(self, cache_dir='./data_cache'):
        self.cache = ParquetCache(cache_dir)
        self.sources = {
            'yahoo': YahooFinanceSource(),
            'ccxt': CCXTSource(),
            'akshare': AkShareSource()
        }
    
    def get_data(self, symbol, start, end, interval='1d'):
        # 1. 查本地缓存
        # 2. 缓存未命中则请求数据源
        # 3. 存储到本地并返回
        pass
    
    def update_cache(self, symbols):
        # 批量更新数据缓存
        pass
```

### 3.2 回测引擎 (Backtest Engine)

```python
# 设计要点：
# - 事件驱动架构 (Event-Driven)
# - 支持多标的、多策略同时回测
# - 滑点、手续费、市场冲击模型

class BacktestEngine:
    def __init__(self, initial_cash=100000):
        self.portfolio = Portfolio(initial_cash)
        self.broker = SimulatedBroker()
        self.analytics = AnalyticsEngine()
    
    def run(self, strategy, data):
        # 按时间顺序处理每个 bar
        for timestamp, bar in data.iterrows():
            # 1. 更新持仓市值
            # 2. 调用 strategy.on_data()
            # 3. 处理订单
            # 4. 记录绩效
            pass
    
    def get_results(self):
        # 返回回测报告
        return {
            'returns': [...],
            'trades': [...],
            'metrics': {...}
        }
```

### 3.3 策略框架 (Strategy Framework)

```python
# 兼容 QuantConnect 风格，同时支持更灵活的写法

class BaseStrategy:
    def __init__(self):
        self.symbols = []
        self.indicators = {}
    
    def initialize(self):
        """初始化，设置参数、订阅数据"""
        pass
    
    def on_data(self, data):
        """每个数据 bar 触发"""
        pass
    
    def on_order_event(self, order):
        """订单状态更新"""
        pass
    
    def should_rebalance(self, timestamp):
        """判断是否需要再平衡"""
        pass

# 使用示例
class MyMomentumStrategy(BaseStrategy):
    def initialize(self):
        self.lookback = 20
        self.symbols = ['AAPL', 'MSFT']
    
    def on_data(self, data):
        for symbol in self.symbols:
            if self.is_above_ma(symbol, data, 200):
                self.buy(symbol, 0.1)
```

### 3.4 风险管理模块 (Risk Manager)

```python
class RiskManager:
    def __init__(self):
        self.rules = []
    
    def add_rule(self, rule):
        """添加风控规则"""
        self.rules.append(rule)
    
    def check(self, portfolio, order):
        """检查订单是否通过风控"""
        for rule in self.rules:
            if not rule.check(portfolio, order):
                return False, rule.name
        return True, "PASS"

# 内置规则
class MaxPositionSize(RiskRule):
    """单标的最大仓位限制"""
    pass

class MaxDrawdown(RiskRule):
    """最大回撤限制"""
    pass

class StopLoss(RiskRule):
    """止损规则"""
    pass
```

### 3.5 绩效分析 (Analytics)

```python
class AnalyticsEngine:
    def calculate_metrics(self, returns):
        return {
            'total_return': self.total_return(returns),
            'cagr': self.cagr(returns),
            'sharpe_ratio': self.sharpe(returns),
            'sortino_ratio': self.sortino(returns),
            'max_drawdown': self.max_drawdown(returns),
            'calmar_ratio': self.calmar(returns),
            'win_rate': self.win_rate(returns),
            'profit_factor': self.profit_factor(returns)
        }
    
    def generate_report(self, backtest_result):
        # 生成 HTML / PDF 报告
        pass
```

---

## 四、项目结构

```
localquant/
├── localquant/                  # 核心包
│   ├── __init__.py
│   ├── core/                    # 核心引擎
│   │   ├── __init__.py
│   │   ├── engine.py            # 回测引擎
│   │   ├── portfolio.py         # 投资组合
│   │   ├── broker.py            # 经纪商模拟
│   │   └── events.py            # 事件系统
│   ├── data/                    # 数据模块
│   │   ├── __init__.py
│   │   ├── manager.py           # 数据管理器
│   │   ├── sources/             # 数据源
│   │   │   ├── base.py
│   │   │   ├── yahoo.py
│   │   │   ├── ccxt.py
│   │   │   └── akshare.py
│   │   └── cache.py             # 缓存实现
│   ├── strategy/                # 策略框架
│   │   ├── __init__.py
│   │   ├── base.py              # 策略基类
│   │   ├── context.py           # 策略上下文
│   │   └── indicators.py        # 指标库
│   ├── risk/                    # 风险管理
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── rules.py
│   ├── execution/               # 执行引擎
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── simulators.py        # 模拟执行
│   ├── analytics/               # 绩效分析
│   │   ├── __init__.py
│   │   ├── metrics.py
│   │   ├── reports.py
│   │   └── plots.py
│   ├── live/                    # 实盘交易
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── ibkr.py              # Interactive Brokers
│   │   ├── futu.py              # 富途
│   │   └── binance.py           # 币安
│   └── utils/                   # 工具函数
│       ├── __init__.py
│       ├── helpers.py
│       └── config.py
├── strategies/                  # 策略存放目录
│   ├── __init__.py
│   ├── momentum.py              # 动量策略
│   └── template.py              # 策略模板
├── notebooks/                   # Jupyter 分析
│   ├── backtest_analysis.ipynb
│   └── data_exploration.ipynb
├── web/                         # Web 界面 (Streamlit)
│   ├── app.py                   # 主应用
│   ├── pages/
│   │   ├── backtest.py          # 回测页面
│   │   ├── strategy.py          # 策略管理
│   │   ├── data.py              # 数据查看
│   │   └── analytics.py         # 绩效分析
├── data_cache/                  # 本地数据缓存
│   ├── stocks/
│   └── crypto/
├── config/                      # 配置文件
│   ├── default.yaml             # 默认配置
│   └── logging.yaml             # 日志配置
├── tests/                       # 测试
│   ├── unit/
│   └── integration/
├── scripts/                     # 脚本工具
│   ├── download_data.py         # 数据下载
│   ├── run_backtest.py          # 运行回测
│   └── live_trade.py            # 启动实盘
├── docs/                        # 文档
├── requirements.txt
├── setup.py
├── pyproject.toml
└── README.md
```

---

## 五、分阶段实施路线

### Phase 1: MVP (2-3周)
**目标：能跑通单个策略的回测**

- [ ] 搭建项目结构
- [ ] 实现基础数据获取 (yfinance)
- [ ] 实现简单回测引擎 (单标的、日线)
- [ ] 实现基础策略框架
- [ ] 实现核心绩效指标
- [ ] CLI 工具 (运行回测)

**验证标准：**
```bash
localquant backtest --strategy momentum --symbol AAPL --start 2020-01-01 --end 2023-01-01
```

### Phase 2: 核心功能完善 (3-4周)
**目标：支持多标的、多策略、完整风控**

- [ ] 多标的回测支持
- [ ] 数据缓存系统 (Parquet)
- [ ] 多数据源集成 (Yahoo, CCXT, AKShare)
- [ ] 完整风控系统 (止损、止盈、仓位限制)
- [ ] 滑点与手续费模型
- [ ] 绩效报告生成 (HTML/PDF)
- [ ] Streamlit Web 界面

**验证标准：**
- 能同时回测 100+ 标的
- 能复现 MomentumProjects 策略结果
- Web 界面可查看回测结果

### Phase 3: 高级功能 (4-6周)
**目标：接近机构级量化平台**

- [ ] 分钟级/Tick 级回测
- [ ] 参数优化 (网格搜索、遗传算法)
- [ ] 多策略组合与资金分配
- [ ] 实时数据流处理
- [ ] 实盘交易接口 (至少一个券商)
- [ ] 风险归因分析
- [ ] 回测与实盘一致性校验

### Phase 4: 生产化 (持续)
**目标：稳定运行、易维护**

- [ ] 完整测试覆盖
- [ ] 文档完善
- [ ] Docker 部署
- [ ] 监控与告警
- [ ] 社区贡献指南

---

## 六、与现有项目的整合

### 6.1 复用 QuantConnect 策略

```python
# 创建一个适配器，将 QC 策略转换为 LocalQuant 策略
class QCStrategyAdapter(BaseStrategy):
    def __init__(self, qc_strategy_class):
        self.qc_strategy = qc_strategy_class()
    
    def initialize(self):
        # 映射 QC 的 Initialize
        self.qc_strategy.Initialize()
    
    def on_data(self, data):
        # 映射 QC 的 OnData
        self.qc_strategy.OnData(data)
```

### 6.2 数据共享

```
QuantConnect Lean CLI 数据 → 链接到 localquant/data_cache/
避免重复下载
```

### 6.3 策略库复用

```
已有的策略 (MomentumProjects, AdaptiveMomentumV3_1) 
    ↓
适配器转换
    ↓
LocalQuant 回测验证
    ↓
对比 QC 结果，确认一致性
```

---

## 七、技术细节

### 7.1 数据存储格式

```python
# 使用 Parquet 存储 OHLCV 数据
# 优势：压缩率高、读取快、兼容 Pandas

# 目录结构
data_cache/
  stocks/
    daily/
      AAPL.parquet      # 包含 2010-至今的日线数据
      MSFT.parquet
    minute/
      AAPL.parquet      # 分钟线数据 (按需下载)
  crypto/
    binance/
      BTC_USDT.parquet

# 数据格式 (DataFrame)
# | timestamp | open | high | low | close | volume | adj_close |
```

### 7.2 回测性能优化

```python
# 1. 向量化计算 (避免循环)
# 2. 预加载数据到内存
# 3. 使用 Numba / Cython 加速关键路径
# 4. 多进程并行回测多个策略

# 预期性能
# - 日线数据，100 标的，10 年：秒级完成
# - 分钟数据，100 标的，1 年：分钟级完成
```

### 7.3 与 Lean 的对比

| 功能 | QuantConnect Lean | LocalQuant |
|------|-------------------|------------|
| 数据 | 云端提供 | 本地获取/缓存 |
| 回测速度 | 受网络影响 | 本地计算，快 |
| 策略语言 | C#/Python | Python |
| 费用 | 免费/付费 | 完全免费 |
| 实盘 | 支持多种券商 | 需自行对接 |
| 社区 | 丰富 | 自建 |
| 定制性 | 受限 | 完全可控 |

---

## 八、开始实施

### 第一步：创建项目

```bash
# 创建目录
cd /home/pc/.openclaw/workspace
mkdir -p localquant && cd localquant

# 初始化 Python 项目
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install pandas numpy yfinance streamlit fastapi uvicorn click
pip install plotly pyarrow  # 可视化与 Parquet
```

### 第二步：实现数据获取

```bash
# 先实现最基础的功能：下载股票数据并缓存
python -c "
import yfinance as yf
data = yf.download('AAPL', start='2020-01-01', end='2024-01-01')
data.to_parquet('data_cache/stocks/daily/AAPL.parquet')
print('Downloaded', len(data), 'rows')
"
```

---

## 九、风险评估与建议

### 潜在挑战

1. **数据质量**：免费数据源 (Yahoo Finance) 可能有延迟或错误
   - 建议：多源交叉验证，重要决策用付费数据

2. **性能瓶颈**：Python 处理大规模数据可能慢
   - 建议：核心路径用 Numba/Cython，或考虑 Rust/Go 重写引擎

3. **实盘稳定性**：个人维护的系统可能不如商业平台稳定
   - 建议：完善的日志、监控、异常处理

### 建议优先级

1. **先做 Phase 1**：验证核心概念可行
2. **用已有策略测试**：MomentumProjects 作为第一个测试案例
3. **逐步替换**：先作为 QuantConnect 的补充，再逐步独立

---

## 十、下一步行动

**今天可以做的：**
- [ ] 创建项目骨架
- [ ] 实现数据下载脚本
- [ ] 跑通第一个简单回测

**本周目标：**
- [ ] Phase 1 MVP 完成
- [ ] 能用 CLI 运行回测
- [ ] 能生成基础绩效报告

**需要我帮你实现哪个部分？**
1. 创建完整项目结构
2. 实现核心回测引擎
3. 先做数据管理模块
4. 直接开始写代码

---

*规划完成时间：2026-07-12*
*版本：v0.1*
