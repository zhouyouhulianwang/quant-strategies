# LocalQuant 策略模板系统 v3.1

**目标**: 提供常用量化策略模板，用户可直接使用或二次开发  
**时间**: 2026-07-13  
**状态**: 设计中

---

## 1. 策略模板列表

| 模板名称 | 类型 | 核心逻辑 | 适用场景 | 复杂度 |
|----------|------|----------|----------|--------|
| **DualThrust** | 突破 | 开盘价 + 前日区间 | 趋势启动 | ⭐⭐ |
| **RBreaker** | 反转 | 日内支撑/阻力 | 日内交易 | ⭐⭐⭐ |
| **Aberration** | 趋势 | Bollinger + 均线 | 中长期趋势 | ⭐⭐ |
| **PairTrading** | 套利 | 协整 + 价差回归 | 低风险 | ⭐⭐⭐ |
| **GridTrading** | 网格 | 固定间距买卖 | 震荡市 | ⭐ |
| **HFTScalping** | 高频 | 盘口价差 | 高流动性 | ⭐⭐⭐⭐ |
| **CTA** | 趋势 | 多周期均线 | 大宗商品 | ⭐⭐ |
| **Alpha** | 多因子 | 价值+动量+质量 | 股票多空 | ⭐⭐⭐⭐ |

---

## 2. 模板接口规范

所有模板必须继承 `BaseStrategy`，实现以下方法：

```python
class StrategyTemplate(BaseStrategy):
    def __init__(self, symbols, **params):
        super().__init__()
        self.symbols = symbols
        # 参数设置
        
    def on_data(self, data):
        # 主逻辑
        pass
    
    def get_parameters(self):
        # 返回可调参数
        return {}
    
    def get_description(self):
        # 返回策略描述
        return ""
```

---

## 3. 实现计划

1. **DualThrust** - 日内突破策略
2. **GridTrading** - 网格交易策略  
3. **PairTrading** - 配对交易策略
4. **Aberration** - 布林带趋势策略
5. **Alpha** - 多因子选股策略

---

*设计完成，开始实现*
