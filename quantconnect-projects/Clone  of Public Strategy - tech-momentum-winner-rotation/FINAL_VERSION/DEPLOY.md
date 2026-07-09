# 自适应多维度动量策略 - 部署文档

## 📋 策略概览

- **策略名称**: Adaptive Momentum Strategy V6
- **版本**: 最终版 (2026-07-08)
- **文件位置**: `FINAL_VERSION/main.py`
- **代码大小**: 41,671 bytes

---

## 📊 回测表现

### 核心周期 (2022-01-01 ~ 2025-06-01)

| 指标 | 结果 |
|------|------|
| **总收益** | **+307.14%** |
| **年化收益** | **50.89%** |
| **夏普比率** | **0.962** |
| **最大回撤** | **48.6%** |
| **胜率** | **80%** |
| **盈亏比** | **2.44** |
| **交易次数** | **294次** |
| **总手续费** | **$58.86** |

### 多周期验证

| 周期 | 市场环境 | 总收益 | 年化 | 夏普 | 最大回撤 |
|------|----------|--------|------|------|----------|
| **2018-2022** | 熊市+震荡 | **+265.44%** | 38.24% | 0.825 | 51.9% |
| **2022-2025** | 熊市+反弹 | **+307.14%** | 50.89% | 0.962 | 48.6% |
| **2020-2025** | 牛熊完整 | **+2,073.39%** | 76.57% | 1.353 | 55.0% |

---

## 🔧 部署步骤

### 方式1: QuantConnect 云端部署（推荐）

**前置条件:**
- QuantConnect 付费账户 ($10/月)
- Lean CLI 已安装

**步骤:**

```bash
# 1. 登录 QuantConnect
lean login

# 2. 推送项目到云端
lean cloud push --project "Clone  of Public Strategy - tech-momentum-winner-rotation"

# 3. 编译验证
lean cloud backtest "Clone  of Public Strategy - tech-momentum-winner-rotation"

# 4. 查看回测结果（确认+307%）
```

**注意**: 文件大小 41,671 bytes，需在 QuantConnect 32KB 限制内。如需精简，可移除日志和注释。

---

### 方式2: 本地部署 + 券商实盘

**支持的券商:**
- Interactive Brokers (推荐)
- Alpaca (免费)
- Charles Schwab

**步骤 (以 Interactive Brokers 为例):**

```bash
# 1. 申请 IB API
# 在 IB 账户管理中生成 API Key

# 2. 配置 Lean CLI
lean live deploy \
  --brokerage "InteractiveBrokers" \
  --ib-user-name "YOUR_USERNAME" \
  --ib-account "YOUR_ACCOUNT" \
  --ib-password "YOUR_PASSWORD" \
  --ib-trading-mode "paper"  # 先测试模拟盘

# 3. 验证连接
# 检查日志确认数据流正常

# 4. 切换实盘（确认无误后）
lean live deploy \
  --brokerage "InteractiveBrokers" \
  ... \
  --ib-trading-mode "live"
```

---

## ⚙️ 策略参数

### 基础设置
```python
初始资金: $100,000
回测周期: 2022-01-01 ~ 2025-06-01
 markets: 美股（纯美股模式）
数据分辨率: 日级
```

### 动量参数
```python
回看周期: 1日, 5日, 10日, 21日, 63日, 126日
基础权重: 0.1, 0.5, 1.0, 1.0, 1.0, 1.0
```

### 仓位管理
```python
单票最大仓位: 15%
持仓数量: 10只
止损比例: 15%
全局仓位缩放: 由VIX控制（高VIX时50%）
```

### 风控参数
```python
VIX阈值: 30
高波动阈值: 2.5%日波动率
行业轮动: 启用，选Top 3行业
估值过滤: 启用，权重30%
调仓频率: 2周
```

---

## 📁 文件结构

```
Clone  of Public Strategy - tech-momentum-winner-rotation/
├── main.py (41,671 bytes - 策略代码)
├── FINAL_VERSION/
│   ├── main.py (备份代码)
│   ├── STRATEGY_REPORT.md (策略报告)
│   └── DEPLOY.md (本文档)
├── backups/
│   └── 2026-07-08_13-04-00/
│       ├── main.py
│       └── README.md
├── data/
│   ├── equity/
│   │   └── usa/
│   │       └── daily/ (628 ZIP files)
│   └── valuation/
│       └── valuation_data.json
└── backtests/ (历史回测结果)
```

---

## ⚠️ 风险提示

1. **过往表现不代表未来收益**
   - +307% 是历史回测结果
   - 实盘可能有滑点、延迟等影响

2. **最大回撤 48.6%**
   - 需要较强心理素质
   - 建议只用可承受损失的资金

3. **交易频率较高**
   - 294次交易 / 3.5年
   - 确保券商支持频繁交易

4. **数据质量**
   - 使用免费 Yahoo Finance 数据
   - 实盘建议使用付费数据

---

## 🚀 实盘建议

### 第一步: 模拟盘测试 (1-3个月)
- 使用 Paper Trading 账户
- 验证策略在实盘环境中的稳定性
- 检查滑点和执行质量

### 第二步: 小资金实盘 ($1,000-$5,000)
- 测试实际交易成本
- 验证券商 API 稳定性
- 确认订单执行无误

### 第三步: 逐步加仓
- 确认策略稳定运行3个月后
- 逐步增加资金至目标仓位
- 持续监控策略表现

---

## 📞 技术支持

**QuantConnect 文档:**
- https://www.quantconnect.com/docs/

**Lean CLI 文档:**
- https://www.lean.io/docs/lean-cli/

**社区论坛:**
- https://www.quantconnect.com/forum/

---

## 📝 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| V1 | - | 基础单股动量 |
| V2 | - | 10%仓位分散 |
| V3 | - | 30%仓位集中 |
| V4 | - | 57只股全市场 |
| V5 | - | 双市场（US+HK） |
| **V6** | **2026-07-08** | **纯美股+7层风控（最终版）** |

---

*生成时间: 2026-07-08 14:53 UTC*
*策略文件: main.py (41,671 bytes)*
