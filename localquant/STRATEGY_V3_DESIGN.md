# 多策略框架设计文档 v3.0

**目标**: 建立多策略体系，覆盖牛/熊/震荡市  
**时间**: 2026-07-13  
**执行**: Qs

---

## 1. 策略分类矩阵

| 策略类型 | 适用市场 | 核心逻辑 | 预期夏普 | 最大回撤 |
|----------|----------|----------|----------|----------|
| **防御型** | 熊市/震荡 | AdaptiveMomentumV3 | 0.0-0.5 | < -8% |
| **牛市增强** | 牛市 | 高Beta动量+杠杆ETF | > 1.0 | -15% |
| **趋势跟踪** | 牛/熊趋势 | 均线突破+动量 | 0.5-0.8 | -10% |
| **均值回归** | 震荡市 | RSI超买超卖+Bollinger | 0.3-0.6 | -5% |
| **波动率** | 高波动 | VIX择时+期权策略 | 0.4-0.7 | -8% |
| **多因子** | 全天候 | 价值+质量+动量 | 0.6-1.0 | -10% |

---

## 2. 策略设计

### 2.1 牛市增强策略 (BullMomentum)
**目标**: 在牛市中跑赢 SPY
**核心逻辑**:
1. 筛选过去 1-3 个月涨幅最高的 10 只科技股
2. 使用杠杆 ETF (TQQQ/SOXL) 增强收益
3. 加入 SPY 动量过滤：SPY>SMA20 才入场
4. 快速止盈：10% 收益自动止盈再平衡

**参数**:
- top_n: 10 (选股数量)
- momentum_lookback: 20-60 天
- spy_filter: True (SPY 动量过滤)
- profit_target: 0.10 (止盈目标)
- max_position_pct: 0.15

### 2.2 趋势跟踪策略 (TrendFollowing)
**目标**: 捕捉大趋势
**核心逻辑**:
1. 价格 > SMA50 = 多头
2. 价格 < SMA50 = 空头/空仓
3. 加入 MACD 确认
4. ATR 仓位管理

**参数**:
- fast_ma: 20
- slow_ma: 50
- signal_ma: 12, 26, 9 (MACD)
- atr_period: 14
- risk_per_trade: 0.02 (2% 风险)

### 2.3 均值回归策略 (MeanReversion)
**目标**: 震荡市盈利
**核心逻辑**:
1. RSI < 30 → 买入
2. RSI > 70 → 卖出
3. 价格触及 Bollinger 下轨 → 买入
4. 价格触及 Bollinger 上轨 → 卖出
5. 持仓时间限制：5 天未回归则平仓

**参数**:
- rsi_period: 14
- rsi_oversold: 30
- rsi_overbought: 70
- bb_period: 20
- bb_std: 2.0
- max_hold_days: 5

### 2.4 多因子策略 (MultiFactor)
**目标**: 全天候稳健收益
**核心逻辑**:
1. 价值因子：低 P/E, 低 P/B
2. 质量因子：高 ROE, 稳定盈利
3. 动量因子：近期强势
4. 每个因子选 top 20，取交集

---

## 3. 策略切换机制

### 3.1 市场状态识别
```python
def detect_market_regime(prices, spy_prices):
    """识别市场状态"""
    spy_return_20d = spy_prices.pct_change(20).iloc[-1]
    spy_return_60d = spy_prices.pct_change(60).iloc[-1]
    vix_level = get_vix()
    
    if spy_return_20d > 0.05 and vix_level < 20:
        return "bull"  # 牛市
    elif spy_return_20d < -0.05 or vix_level > 25:
        return "bear"  # 熊市
    else:
        return "sideways"  # 震荡
```

### 3.2 动态策略切换
```python
STRATEGY_MAP = {
    "bull": "BullMomentum",
    "bear": "AdaptiveMomentumV3", 
    "sideways": "MeanReversion"
}
```

---

## 4. 执行计划

| 时间 | 任务 | 优先级 |
|------|------|--------|
| T+0 | 实现 BullMomentum 策略 | P0 |
| T+15min | 实现 TrendFollowing 策略 | P0 |
| T+30min | 实现 MeanReversion 策略 | P1 |
| T+45min | 实现多策略切换机制 | P1 |
| T+60min | 回测对比所有策略 | P1 |
| T+75min | 输出最终策略矩阵 | P2 |

---

*开始执行*
