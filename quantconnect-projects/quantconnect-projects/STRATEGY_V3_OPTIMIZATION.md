# AdaptiveMomentumStrategy v3.0 优化说明

## 优化概览

基于 strategy_final_qc.py v2.4 进行全面优化，版本号升级为 v3.0。

---

## 一、代码结构优化

| 项目 | v2.4 | v3.0 | 说明 |
|------|------|------|------|
| 类型注解 | ❌ 无 | ✅ 完整 | 添加函数参数和返回值类型提示 |
| 文档字符串 | ❌ 无 | ✅ 完整 | 每个核心函数都有docstring |
| 代码组织 | 混乱 | 模块化 | 辅助方法、核心策略、数据事件分离 |
| 变量命名 | 缩写 | 全名 | 如 `lbs` → `lookback_periods`，`sl_pct` → `stop_loss_pct` |
| 注释 | 少量 | 详细 | 每个逻辑块都有中文注释 |

---

## 二、核心策略增强

### 1. 动量计算优化
- **v2.4**: 简单加权平均
- **v3.0**: 
  - 保持多期限动量（1d/1w/2w/1m/3m/6m）
  - 自适应权重根据波动率和VIX动态调整
  - 新增估值水平判断（高/中/低）影响权重分配

### 2. 行业轮动优化
- **v2.4**: 基础行业轮动，硬编码股票池
- **v3.0**:
  - `_BuildSectorMap()` 方法封装行业映射
  - 动态计算行业动量
  - 保留 `Other` 行业确保未映射股票也能入选
  - 可通过 `sector_rotation_enabled` 开关控制

### 3. 调仓频率优化
- **v2.4**: 基于VIX和估值的简单频率调整
- **v3.0**:
  - 更精细的调仓频率逻辑
  - `pause_weeks` 防止过度暂停
  - 参数化配置更灵活

---

## 三、风险管理增强（重点）

### 1. 多层止损体系

| 功能 | v2.4 | v3.0 | 说明 |
|------|------|------|------|
| 固定止损 | ✅ 15% | ✅ 15% | 保持不变 |
| 追踪止损 | ❌ 无 | ✅ 20% | 从最高价回撤20%触发 |
| 最大回撤保护 | ❌ 无 | ✅ 25% | 回撤超25%清仓转安全资产 |
| 回撤后行为 | ❌ 无 | ✅ 自动转仓 | 自动买入TLT/GLD避险 |

### 2. 波动率缩放（新增）
- **功能**: 根据个股波动率动态调整仓位大小
- **目标**: 控制组合年化波动率在15%左右
- **范围**: 缩放因子限制在 0.5-2.0 之间
- **开关**: `volatility_scaling` 可启用/禁用

### 3. 仓位管理优化

| 参数 | v2.4 | v3.0 | 说明 |
|------|------|------|------|
| 单票最大仓位 | 15% | 15% | 保持不变 |
| 单票最小仓位 | ❌ 无 | 2% | 避免过度分散 |
| 总仓位上限 | 80% | 80% | 保持不变 |
| 总仓位下限 | ❌ 无 | 20% | 防止空仓踏空 |
| 调仓阈值 | ❌ 无 | 10% | 偏差>10%才调仓，减少摩擦 |

---

## 四、信号过滤增强（新增）

### 1. 趋势过滤（200日均线）
- **功能**: 只买入价格高于200日均线的股票
- **目的**: 避免在下降趋势中接飞刀
- **开关**: `trend_filter_enabled`

### 2. RSI过滤
- **功能**: 过滤RSI > 70的极度超买股票
- **目的**: 避免买入短期过热股票
- **开关**: `rsi_filter_enabled`
- **参数**: RSI周期14，超买阈值70

---

## 五、执行优化

### 1. 指标预计算
- **v2.4**: 每次调仓时计算历史数据
- **v3.0**: 初始化时预创建RSI和SMA指标
  - `rsi_indicators` 字典缓存RSI
  - `sma_indicators` 字典缓存SMA

### 2. 数据访问优化
- 使用 `self.Securities[symbol].Price` 替代 `self.portfolio[symbol].price`
- 使用大驼峰命名规范（QuantConnect标准）

### 3. 调仓逻辑优化
- 添加 `min_position_pct` 避免过度分散
- 调仓阈值10%减少不必要的交易
- 成本基准和追踪止损价自动管理

---

## 六、参数对比表

| 参数 | v2.4 | v3.0 | 变化 |
|------|------|------|------|
| `lookback_periods` | `lbs` | 全名 | 重构 |
| `base_weights` | `base_w` | 全名 | 重构 |
| `current_weights` | `cur_w` | 全名 | 重构 |
| `volatility_lookback` | `vol_lookback` | 全名 | 重构 |
| `volatility_high` | `vol_high` | 全名 | 重构 |
| `volatility_low` | `vol_low` | 全名 | 重构 |
| `vix_threshold` | `vix_th` | 全名 | 重构 |
| `max_position_pct` | `max_pos` | 全名 | 重构 |
| `max_stocks` | `n_stocks` | 全名 | 重构 |
| `stop_loss_pct` | `sl_pct` | 全名 | 重构 |
| `sector_rotation_enabled` | `sec_rot` | 全名 | 重构 |
| `n_top_sectors` | `n_sectors` | 全名 | 重构 |
| `sector_lookback` | `sec_lookback` | 全名 | 重构 |
| `base_rebalance_freq` | `base_freq` | 全名 | 重构 |
| `min_rebalance_freq` | `min_freq` | 全名 | 重构 |
| `max_rebalance_freq` | `max_freq` | 全名 | 重构 |
| `current_rebalance_freq` | `cur_freq` | 全名 | 重构 |
| `pause_weeks` | `pause_weeks` | 保持不变 | - |
| `max_pause_weeks` | `max_pause` | 全名 | 重构 |
| `valuation_extreme` | `val_extreme` | 全名 | 重构 |
| **新增** `min_position_pct` | 无 | 2% | 新增 |
| **新增** `max_total_exposure` | 无 | 80% | 新增（明确化） |
| **新增** `min_total_exposure` | 无 | 20% | 新增 |
| **新增** `trailing_stop_enabled` | 无 | True | 新增 |
| **新增** `trailing_stop_pct` | 无 | 20% | 新增 |
| **新增** `max_drawdown_pct` | 无 | 25% | 新增 |
| **新增** `trend_filter_enabled` | 无 | True | 新增 |
| **新增** `trend_lookback` | 无 | 200 | 新增 |
| **新增** `rsi_filter_enabled` | 无 | True | 新增 |
| **新增** `rsi_period` | 无 | 14 | 新增 |
| **新增** `rsi_overbought` | 无 | 70 | 新增 |
| **新增** `rsi_oversold` | 无 | 30 | 新增 |
| **新增** `volatility_scaling` | 无 | True | 新增 |
| **新增** `target_volatility` | 无 | 0.15 | 新增 |

---

## 七、新增方法列表

| 方法名 | 说明 | 用途 |
|--------|------|------|
| `_BuildSectorMap()` | 构建行业映射 | 代码组织 |
| `_GetUSStockPool()` | 获取股票池 | 代码组织 |
| `_InitializeSymbols()` | 初始化股票 | 代码组织 |
| `CheckTrendFilter()` | 趋势过滤 | 信号增强 |
| `CheckRSIFilter()` | RSI过滤 | 信号增强 |
| `CalculateVolatilityScaling()` | 波动率缩放 | 风险管理 |
| `CheckMaxDrawdown()` | 最大回撤保护 | 风险管理 |
| `GetTickerName()` | 获取Ticker名 | 工具方法（增强） |

---

## 八、使用建议

### 1. 回测参数调优
建议对以下参数进行敏感性分析：
- `target_volatility`: 0.10 - 0.20
- `trailing_stop_pct`: 0.15 - 0.30
- `max_drawdown_pct`: 0.20 - 0.30
- `rsi_overbought`: 65 - 75
- `trend_lookback`: 150 - 250

### 2. 开关组合测试
| 场景 | trend_filter | rsi_filter | vol_scaling | trailing_stop |
|------|------------|------------|-------------|---------------|
| 保守 | ✅ | ✅ | ✅ | ✅ |
| 平衡 | ✅ | ❌ | ✅ | ✅ |
| 激进 | ❌ | ❌ | ❌ | ❌ |
| 纯动量 | ❌ | ❌ | ❌ | ✅（仅固定止损） |

### 3. 实盘注意事项
- 确保IB账户有足够资金覆盖保证金
- 注意高波动率缩放可能降低仓位导致资金利用率不足
- 回撤保护触发后会清仓，需手动观察恢复信号

---

## 九、文件位置

- **v2.4**: `strategy_final_qc.py`（基准版本）
- **v3.0**: `strategy_final_qc_v3.py`（优化版本）

---

## 十、后续优化方向

1. **机器学习增强**: 用XGBoost/LightGBM预测动量持续性
2. **多因子融合**: 加入质量、价值、低波动因子
3. **动态股票池**: 根据流动性、市值动态筛选
4. **期权对冲**: 用VIX期权或SPY put保护尾部风险
5. **跨市场轮动**: 加入新兴市场、商品等资产类别

---

*优化完成时间: 2026-07-10*
*优化者: Qs ⚡*
