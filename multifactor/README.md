# MultiFactor Quantitative Trading System

**多策略组合量化交易系统** — 在 V14 17因子策略基础上，扩展为可配置的多策略组合架构。

- **核心策略**: V14 MultiFactor（17因子综合）
- **子策略**: Growth、Momentum、Value、Quality（独立选股、独立回测）
- **组合层**: 资本配置、聚合持仓、行业约束、波动率 overlay、统一风控
- **执行层**: Alpaca Paper/Live，原子预检、对账、风控熔断
- **零人工干预** | **月度调仓** | **真实数据回测优先**

---

## 快速开始

### 1. 安装依赖

```bash
cd multifactor
pip install -r requirements.txt
```

### 2. 配置 API (可选，用于实盘/数据)

```bash
cp .env.example .env
# 编辑 .env 填入 Alpaca API Key
```

### 3. 单策略回测（V14）

```bash
python run_strategy.py --backtest --real-data --start 2020-01-01 --end 2024-12-31
```

### 4. 多策略组合回测

```bash
# 使用真实数据（推荐）
python run_multi_strategy.py --backtest --real-data --start 2020-01-01 --end 2024-12-31

# 使用模拟数据快速验证架构
python run_multi_strategy.py --backtest --no-real-data --start 2020-01-01 --end 2024-12-31

# 各子策略独立回测
python run_multi_strategy.py --individual --backtest --real-data --start 2020-01-01 --end 2024-12-31
```

### 5. 多策略 Paper 调仓

```bash
python run_multi_strategy.py --paper --enable-risk-monitor
```

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                       StrategyPortfolio                      │
│  - 资金按权重分配给子策略                                    │
│  - 聚合目标持仓                                             │
│  - 行业/单票/波动率 overlay                                 │
│  - 统一风控 + Alpaca 执行                                   │
└──────────────┬──────────────────────────────────────────────┘
               │
    ┌──────────┼──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼          ▼
MultiFactor   Growth    Momentum    Value     Quality
(V14)          (趋势成长) (纯动量)  (估值)    (质量低波)
```

### 默认组合权重

| 策略 | 权重 | 说明 |
|------|------|------|
| MultiFactor (V14) | 30% | 17因子综合评分 |
| Growth | 25% | 收益/价格加速、行业相对强度 |
| Momentum | 20% | 趋势跟踪 |
| Value | 15% | 行业相对估值、GARP |
| Quality | 10% | 质量、低波动、趋势稳健 |

---

## 项目结构

```
multifactor/
├── README.md                    # 本文件
├── main.py                      # V14 因子计算与回测引擎
├── run_strategy.py              # V14 单策略入口
├── run_multi_strategy.py        # 多策略组合 CLI
├── strategies/
│   ├── base.py                  # 策略抽象基类
│   ├── factor_strategy.py       # 子策略共享基类
│   ├── v14.py                   # MultiFactorStrategy (V14)
│   ├── growth.py                # GrowthStrategy
│   ├── momentum.py              # MomentumStrategy
│   ├── value.py                 # ValueStrategy
│   ├── quality.py               # QualityStrategy
│   └── portfolio.py             # StrategyPortfolio 组合管理器
├── data_source.py               # 真实数据获取
├── quantconnect_data.py         # QuantConnect 数据接口
├── alpaca_executor.py           # Alpaca 执行器
├── order_manager.py             # 订单管理
├── cost_model.py                # 交易成本模型
├── risk_monitor.py              # 风险监控
├── weight_allocation.py         # 权重分配与约束
├── scheduler.py                 # 定时调度
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
├── config.example.json          # 配置示例
├── data_cache/                  # 数据缓存
├── charts/                      # 回测图表输出
├── logs/                        # 运行日志
├── orders/                      # 订单记录
├── alerts/                      # 风险告警
└── data/                        # 状态与风控数据
```

---

## 设计原则

1. **信号层与执行层分离**: 子策略只负责生成目标持仓，组合层负责资金分配、聚合、风控、执行。
2. **真实数据优先**: 回测默认使用 QuantConnect/Yahoo 真实数据，mock 仅用于架构验证。
3. **可配置**: 权重、因子、风控参数均走 `config.json`（被 git 忽略，用 `config.example.json` 为模板）。
4. **安全切换**: Paper 稳定运行至少一个完整调仓周期后，再按 `PRE_LIVE_CHECKLIST.md` 评估 live。

---

## 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 最大持仓 | 10-40只 | VIX 动态调整（V14） |
| 子策略 n_stocks | 15 | 各子策略选股数量 |
| 单仓上限 | 20% | 子策略与组合层双重检查 |
| 行业上限 | 30% | 组合层行业集中度 |
| 目标波动率 | 15% | 组合层 vol target overlay |
| 调仓频率 | 月度 | 月末交易日 |
| 预热期 | 252日 | 1 年历史数据 |
| 回撤限制 | 15% | 风险告警 |

---

## 风险提示

⚠️ **重要提示：**
- 本系统仅供研究和学习使用
- 回测结果不代表未来表现
- 实盘交易前请使用 Paper Trading 验证至少 3-6 个月
- 切换策略前请阅读 `AUDIT_EXEC_RISK_2026-07-21.md` 中的过渡建议
- 投资有风险，入市需谨慎

---

## 许可证

MIT
