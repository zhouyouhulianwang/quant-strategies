# LocalQuant 🚀

本地量化交易平台 - 类似 QuantConnect 的本地化回测与交易框架

## 快速开始

```bash
cd /home/pc/.openclaw/workspace/localquant

# 1. 下载数据
python3 -c "
from localquant.data.manager import DataManager
from datetime import datetime
dm = DataManager()
dm.get_data('AAPL', datetime(2022,1,1), datetime(2024,12,31))
"

# 2. 运行回测
python3 scripts/test_mvp.py

# 3. 查看结果
cat data_cache/equity_curve.csv
cat data_cache/trades.csv
```

## 项目结构

```
localquant/
├── localquant/          # 核心包
│   ├── core/            # 回测引擎、投资组合、经纪商
│   ├── data/            # 数据管理、缓存
│   ├── sources/         # 数据源 (Yahoo, CCXT, etc.)
│   ├── strategy/        # 策略框架、指标库
│   ├── analytics/       # 绩效分析
│   └── utils/           # 工具函数
├── strategies/          # 策略目录
│   └── sma_cross.py     # SMA 交叉策略示例
├── scripts/             # 脚本工具
│   ├── test_mvp.py      # MVP 测试
│   └── cli.py           # CLI 工具 (TODO)
├── data_cache/          # 本地数据缓存
├── notebooks/           # Jupyter 分析
├── web/                 # Streamlit 界面 (TODO)
└── config/              # 配置文件
```

## 核心模块

### 数据管理 (Data Manager)
- 自动从 Yahoo Finance 获取数据
- Parquet 格式本地缓存
- 多数据源支持（可扩展）

### 回测引擎 (Backtest Engine)
- 事件驱动架构
- 支持滑点、手续费模型
- 支持日期范围过滤

### 策略框架 (Strategy Framework)
- 继承 `BaseStrategy` 实现自定义策略
- 内置技术指标库 (SMA, EMA, RSI, MACD, Bollinger, ATR)
- 兼容 QuantConnect 风格

### 绩效分析 (Analytics)
- 总收益率、CAGR、波动率
- 夏普比率、索提诺比率
- 最大回撤、Calmar 比率
- 交易统计（胜率、盈亏比等）

## 编写策略

```python
from localquant.strategy import BaseStrategy
from localquant.strategy.indicators import sma

class MyStrategy(BaseStrategy):
    def initialize(self):
        self.symbols = ['AAPL']
    
    def on_data(self, data):
        super().on_data(data)
        for symbol in self.symbols:
            history = self.context.get_history(symbol, 'close', 50)
            if len(history) < 50:
                continue
            
            short = sma(history, 20).iloc[-1]
            long = sma(history, 50).iloc[-1]
            
            if short > long:
                self.buy(symbol, 100)
            elif short < long:
                self.sell(symbol, 100)
```

## 运行回测

```python
from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from strategies.your_strategy import MyStrategy

dm = DataManager()
data = dm.get_data('AAPL', start, end)

engine = BacktestEngine(initial_cash=100000)
engine.set_data(data, symbol_name='AAPL')
engine.set_strategy(MyStrategy())

results = engine.run()
metrics = AnalyticsEngine.calculate_metrics(
    results['returns'], results['equity_curve'], 
    results['trades'], 100000
)
AnalyticsEngine.print_report(metrics)
```

## Phase 1 完成状态 ✅

- [x] 项目骨架
- [x] 数据获取与缓存 (yfinance + Parquet)
- [x] 事件驱动回测引擎
- [x] 策略框架与技术指标
- [x] 绩效分析模块
- [x] SMA 交叉策略示例
- [x] MVP 测试通过

## Phase 2 计划 (TODO)

- [ ] 多标的回测支持
- [ ] Web 界面 (Streamlit)
- [ ] 风险管理模块
- [ ] 更多数据源 (CCXT, akshare)
- [ ] CLI 工具完善
- [ ] 参数优化框架

## 依赖

```bash
pip install pandas numpy yfinance pyarrow click
```

## 与现有项目的整合

- `MomentumProjects/` 策略可适配到 LocalQuant
- `quantconnect-projects/` 可作为参考对比
- `lean.json` 的 QuantConnect 配置可作为数据源备份

---

*Created: 2026-07-12*
*Version: 0.1.0*
