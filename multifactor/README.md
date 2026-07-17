# MultiFactor V14 策略项目

**V14: 行业相对估值 + GARP + TED 多因子策略**

- **17因子** | **零人工干预** | **月度调仓**
- 支持真实数据回测、Alpaca Paper Trading 模拟实盘
- 包含可视化、参数优化、风险监控完整模块

---

## 快速开始

### 1. 安装依赖

```bash
cd multifactor
pip install -r requirements.txt
```

### 2. 配置 API (可选)

```bash
cp .env.example .env
# 编辑 .env 填入你的 Alpaca API Key
```

### 3. 运行回测

```bash
# 使用模拟数据
python run_strategy.py --backtest

# 使用真实数据（Yahoo Finance）
python run_strategy.py --backtest --real-data

# 指定日期范围
python run_strategy.py --backtest --real-data --start 2020-01-01 --end 2024-12-31
```

### 4. 运行实盘（Paper Trading）

```bash
python run_strategy.py --live --paper
```

---

## 项目结构

```
multifactor/
├── README.md                    # 本文件
├── main.py                      # V14 策略核心（因子计算、回测引擎）
├── run_strategy.py              # 策略完整封装（整合所有模块）
├── data_source.py               # 真实数据获取（Yahoo Finance）
├── alpaca_executor.py           # Alpaca Paper Trading 执行
├── visualization.py             # 回测可视化（NAV、回撤、热力图）
├── optimization.py              # 参数优化（网格搜索、滚动窗口）
├── risk_monitor.py              # 风险监控（回撤、仓位、VIX、告警）
├── order_manager.py             # 🆕 订单管理（成交确认、状态跟踪）
├── cost_model.py                # 🆕 交易成本模型（佣金/滑点）
├── scheduler.py                 # 🆕 定时调度（月末自动调仓）
├── polygon_data.py              # 🆕 Polygon.io 实时数据源
├── retry_utils.py               # 🆕 API 重试机制（指数退避）
├── weight_allocation.py         # 🆕 权重分配（等权/风险平价/动量加权）
├── intraday_monitor.py          # 🆕 盘中监控（VIX/回撤/紧急平仓）
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
├── data_cache/                  # 数据缓存目录
├── charts/                      # 图表输出目录
├── alerts/                      # 风险告警记录
├── orders/                      # 🆕 订单记录
└── optimization/                # 优化结果
```

---

## 核心模块

### 1. 数据获取 (`data_source.py`)

```python
from data_source import prepare_backtest_data
from main import TICKERS

# 获取真实数据
price_df, market_df = prepare_backtest_data(
    TICKERS, 
    start_date='2020-01-01',
    end_date='2024-12-31',
    use_cache=True  # 启用缓存加速
)
```

**特性：**
- 自动从 Yahoo Finance 下载历史价格
- VIX 数据获取
- 智能缓存机制（避免重复下载）
- 自动日期对齐

### 2. 策略核心 (`main.py`)

**V14: 17因子计算**

| 类别 | 数量 | 因子 |
|------|------|------|
| 基础因子 | 7 | growth, quality, momentum, lowvol, rsi_mr, ma_trend, technical |
| V14估值因子 | 4 | relative_value, garp, price_position, industry_momentum |
| TED早期识别 | 6 | vol_contraction, base_breakout, rel_strength_accel, price_accel, momentum_consistency, low_base_score |

**核心函数：**
- `compute_factors_v14()` - 17因子计算
- `v14_composite_score()` - 综合评分（VIX动态权重）
- `v14_scale()` - 仓位管理
- `run_v14()` - 回测引擎

### 3. 可视化 (`visualization.py`)

```python
from visualization import generate_full_report

# 生成完整报告（含所有图表）
generate_full_report(result_df, save_dir='./my_report')
```

**生成图表：**
- NAV 曲线对比
- 回撤分析
- 月度收益热力图
- VIX-仓位散点图
- 持仓分布饼图

### 4. Alpaca 实盘 (`alpaca_executor.py`)

```python
from alpaca_executor import V14AlpacaExecutor

# 初始化
executor = V14AlpacaExecutor()

# 再平衡组合
target_positions = {'AAPL': 20000, 'MSFT': 20000, 'NVDA': 20000}
executor.rebalance_portfolio(target_positions)

# 查询状态
account = executor.get_account()
positions = executor.get_positions()
```

**支持功能：**
- 自动下单（市价/限价）
- 持仓查询
- 组合再平衡
- 一键平仓
- 市场状态检查

### 5. 风险监控 (`risk_monitor.py`)

```python
from risk_monitor import RiskMonitor

# 初始化
monitor = RiskMonitor(
    max_drawdown_limit=0.15,  # 15% 回撤限制
    max_position_pct=0.20,    # 20% 单仓上限
    vix_pause_level=35.0      # VIX>35 暂停交易
)

# 风险检查
monitor.check_drawdown(current_nav)
monitor.check_vix_level(current_vix)
monitor.check_position_limits(positions, portfolio_value)
```

**监控指标：**
- 最大回撤监控
- 仓位集中度检查
- 行业集中度限制
- VIX 风险等级
- 日亏损限制
- 自动交易暂停

### 6. 参数优化 (`optimization.py`)

```python
from optimization import grid_search_weights, walk_forward_optimization

# 网格搜索
results = grid_search_weights(
    compute_factors_v14,
    v14_composite_score,
    price_df, market_df, NDX_SET,
    n_trials=100
)

# 滚动窗口验证
results = walk_forward_optimization(
    price_df, market_df, run_v14,
    train_size=252*2,  # 2年训练
    test_size=252,      # 1年测试
    n_splits=5
)
```

### 7. 订单管理 (`order_manager.py`)

```python
from order_manager import RebalanceManager

# 初始化
manager = RebalanceManager(executor)

# 执行再平衡（带成交确认）
results = manager.rebalance(
    target_positions={'AAPL': 20000, 'MSFT': 20000},
    confirm_fills=True  # 等待成交确认
)
```

**特性：**
- 订单状态轮询（5秒间隔，最多300秒）
- 成交/部分成交/被拒/超时处理
- CSV 订单日志
- 自动记录每笔交易

### 8. 成本模型 (`cost_model.py`)

```python
from cost_model import TradingCostModel

# 初始化
model = TradingCostModel(
    commission_per_share=0.005,  # $0.005/股
    slippage_bps=10,             # 10 bps 滑点
)

# 计算单笔成本
cost = model.calculate_cost('AAPL', 100, 150.0)
print(f"总成本: ${cost['total_cost']:.2f}")

# 估算组合调仓成本
portfolio_cost = model.estimate_portfolio_cost(target_positions, current_positions)
```

### 9. 定时调度 (`scheduler.py`)

```python
from scheduler import RebalanceScheduler, run_scheduler_loop

# 自动调仓调度
scheduler = RebalanceScheduler(strategy)

# 检查是否到期
if scheduler.should_rebalance():
    strategy.run_live_rebalance()

# 运行调度循环（阻塞模式）
run_scheduler_loop(strategy, check_interval=3600)  # 每小时检查
```

**特性：**
- 月末最后一个交易日自动触发
- 支持 cron 调用
- 执行历史记录

### 10. 实时数据 (`polygon_data.py`)

```python
from polygon_data import HybridDataSource

# 初始化（优先 Polygon，失败回退 Yahoo）
source = HybridDataSource(polygon_key='YOUR_KEY')

# 获取实时价格
price = source.get_current_price('AAPL')

# 获取历史数据
prices = source.get_prices(['AAPL', 'MSFT'], '2024-01-01', '2024-12-31')
```

**特性：**
- Polygon.io 实时数据（需 API Key）
- 自动回退 Yahoo Finance
- VIX 数据获取

---

## 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 最大持仓 | 10-40只 | VIX动态调整 |
| NDX 比例 | 15%-60% | 因子驱动 |
| 仓位管理 | 65%-100% | VIX=15→100%, VIX=55→65% |
| 调仓频率 | 月度 | 月末调仓 |
| 预热期 | 252日 | 1年历史数据 |
| 单仓上限 | 20% | 风险限制 |
| 回撤限制 | 15% | 风险告警 |

## 股票池

40只美股，覆盖10个行业：
- 半导体 (6只): NVDA, MU, AMD, INTC, AVGO, QCOM
- 科技 (10只): AAPL, MSFT, GOOGL, AMZN, META, TSLA, NFLX, ADBE, CRM, INTU
- 金融 (5只): JPM, BAC, GS, V, MA
- 医疗 (4只): UNH, JNJ, PFE, ABBV
- 能源 (2只): XOM, CVX
- 工业 (2只): BA, CAT
- 消费/公用 (5只): NEE, PEP, COST, WMT, HD
- 媒体/电信 (4只): DIS, CMCSA, VZ, TMUS

---

## 使用示例

### 完整回测流程

```python
from run_strategy import V14Strategy

# 初始化策略
strategy = V14Strategy(
    use_real_data=True,      # 使用真实数据
    use_paper_trading=False, # 不连接 Alpaca
    enable_risk_monitor=True # 启用风控
)

# 运行回测
result = strategy.run_backtest(
    start_date='2020-01-01',
    end_date='2024-12-31'
)

# 检查风险
strategy.check_risk(
    nav=result['nav'].iloc[-1],
    vix=25.0
)
```

### 实盘交易流程（全自动）

```python
from run_strategy import V14Strategy

# 初始化（启用 Paper Trading）
strategy = V14Strategy(
    use_real_data=True,
    use_paper_trading=True,  # 连接 Alpaca
    enable_risk_monitor=True
)

# 全自动再平衡（获取数据→计算信号→风控检查→下单）
strategy.run_live_rebalance()

# 或手动执行带成交确认
target_positions = strategy.generate_signals()
strategy.live_trade(target_positions, confirm_fills=True)

# 检查风险
strategy.check_risk()
```

### 定时自动调仓

```bash
# 方式1: 运行调度循环
python scheduler.py

# 方式2: 添加到 cron（每月最后一个交易日 15:30 执行）
30 15 * * * cd /path/to/multifactor && python -c "from scheduler import run_once; run_once()"
```

---

## 风险提示

⚠️ **重要提示：**
- 本策略仅供研究和学习使用
- 回测结果不代表未来表现
- 实盘交易前请充分测试
- 使用 Paper Trading 验证至少3-6个月
- 投资有风险，入市需谨慎

---

## 版本历史

- **v14.0** (2024) - 初始版本，17因子，行业相对估值
- **v14.1** (未来) - 接入更多数据源，机器学习增强

## 作者

AI Quant Strategy Lab

---

**许可证:** MIT
