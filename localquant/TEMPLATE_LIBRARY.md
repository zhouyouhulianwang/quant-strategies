# LocalQuant 策略模板库 v3.1

**生成时间**: 2026-07-13 02:00 UTC  
**状态**: ✅ 完成

---

## 📚 策略模板总览

LocalQuant 现在提供 **9 个策略模板**，覆盖不同市场状态和交易风格：

### 🛡️ 防御型策略

| 策略 | 夏普 | 收益 | 回撤 | 适用市场 |
|------|------|------|------|----------|
| **AdaptiveMomentumV3** | -0.03 | +2.8% | -4.6% | 🐻 熊市 |
| **SMA Cross** | 0.38 | +1.1% | -2.0% | 📊 任意 |

### 🚀 进攻型策略

| 策略 | 夏普 | 收益 | 回撤 | 适用市场 |
|------|------|------|------|----------|
| **BullMomentum** | **1.97** | **+62.7%** | -14.5% | 🐂 牛市 |
| **TrendFollowing** | 1.35 | +22.5% | -9.4% | 🔄 趋势 |

### 📐 量化模板（新增）

| 策略 | 类型 | 复杂度 | 适用场景 |
|------|------|--------|----------|
| **Dual Thrust** | 突破型 | ⭐⭐ | 期货日内交易 |
| **Grid Trading** | 震荡型 | ⭐ | 加密货币/外汇 |
| **Pair Trading** | 套利型 | ⭐⭐⭐ | 低风险统计套利 |
| **Alpha Factor** | 多因子 | ⭐⭐⭐⭐ | 股票多头组合 |

---

## 📁 文件位置

```
strategies/
├── adaptive_momentum_v3.py    # 防御型动量
├── bull_momentum.py           # 牛市增强
├── trend_following.py         # 趋势跟踪
├── sma_cross.py               # 简单交叉
├── minute_momentum.py         # 分钟级
├── multi_momentum.py          # 多周期
├── strategy_rotator.py        # 策略切换器
└── templates/                 # 策略模板库
    ├── __init__.py            # 模板索引
    ├── dual_thrust.py         # Dual Thrust突破
    ├── grid_trading.py        # 网格交易
    ├── pair_trading.py        # 配对套利
    └── alpha_factor.py        # 多因子Alpha
```

---

## 🚀 快速使用

### 方式1: 命令行
```bash
cd /home/pc/.openclaw/workspace/localquant

# 查看所有策略
python3 -c "from strategies.templates import list_strategies; list_strategies()"

# 使用模板回测
python3 -c "
from strategies.templates import get_strategy
from localquant.core.engine import BacktestEngine

Strategy = get_strategy('bull_momentum')
strategy = Strategy(symbols=['AAPL', 'MSFT', 'NVDA'])

engine = BacktestEngine()
engine.set_strategy(strategy)
results = engine.run()
"
```

### 方式2: API
```bash
# 查看策略列表
curl http://localhost:8000/strategies

# 创建回测任务
curl -X POST http://localhost:8000/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_name": "bull_momentum",
    "symbols": ["AAPL", "MSFT", "NVDA"],
    "start_date": "2023-01-01",
    "end_date": "2024-12-31",
    "strategy_params": {"top_n": 5, "profit_target": 0.10}
  }'
```

### 方式3: Dashboard
```bash
streamlit run web/dashboard_v2.py
# 在界面中选择策略、配置参数、提交回测
```

---

## 🎯 策略选择指南

### 按风险偏好

| 风险偏好 | 推荐策略 | 预期收益 | 预期回撤 |
|----------|----------|----------|----------|
| 保守型 | AdaptiveMomentum + 国债 | +3-8% | -5% |
| 稳健型 | TrendFollowing | +15-25% | -10% |
| 激进型 | BullMomentum | +40-60% | -15% |
| 量化型 | Alpha Factor | +10-20% | -8% |

### 按市场状态

| 市场状态 | 推荐策略 | 理由 |
|----------|----------|------|
| 🐂 牛市 | BullMomentum | 动量效应最强 |
| 🐻 熊市 | AdaptiveMomentum | 防御性配置 |
| 🔄 趋势 | TrendFollowing | 跟随趋势 |
| 〰️ 震荡 | Grid Trading | 低买高卖 |
| 📊 任意 | Alpha Factor | 多因子分散 |

### 按资产类别

| 资产 | 推荐策略 |
|------|----------|
| 美股 | Alpha Factor, BullMomentum |
| 期货 | Dual Thrust, TrendFollowing |
| 加密货币 | Grid Trading, BullMomentum |
| ETF | Pair Trading, SMA Cross |

---

## ⚙️ 策略参数调优

每个策略都提供 `get_parameters()` 方法：

```python
from strategies.templates import get_strategy

Strategy = get_strategy('bull_momentum')
strategy = Strategy(symbols=['AAPL', 'MSFT'])

# 查看可调参数
params = strategy.get_parameters()
print(params)
# {
#   'top_n': {'value': 10, 'min': 3, 'max': 50, 'type': 'int'},
#   'profit_target': {'value': 0.1, 'min': 0.05, 'max': 0.3, 'type': 'float'}
# }
```

---

## 🔧 自定义策略模板

基于模板快速开发新策略：

```python
from strategies.templates import get_strategy

class MyStrategy(get_strategy('sma_cross')):
    """继承并扩展SMA策略"""
    
    def __init__(self, symbols, **kwargs):
        super().__init__(symbols, **kwargs)
        # 添加自定义参数
        self.my_param = kwargs.get('my_param', 0.5)
    
    def on_data(self, data):
        # 扩展逻辑
        super().on_data(data)
        # 添加自定义逻辑
        pass
```

---

## 📊 系统状态

| 组件 | 状态 | 地址 |
|------|------|------|
| API 后端 | ✅ | http://localhost:8000 |
| Dashboard | ✅ | http://localhost:8501 |
| 策略模板 | ✅ 9个 | - |
| 数据库 | ✅ | SQLite |

---

*策略模板库 v3.1 - LocalQuant*
