# QuantConnect 云端回测指南

## 1. 项目设置

### 1.1 创建新项目
1. 登录 [QuantConnect](https://www.quantconnect.com)
2. 点击 **Create New Algorithm**
3. 选择 **Python** 语言

### 1.2 上传文件
将以下文件上传到项目：

```
📁 项目根目录
├── 📄 main.py                    # 策略主文件 (strategy_final_qc_v3_1.py)
└── 📄 stock_pools.json           # 股票池配置文件
```

**上传方式：**
- 方式1：直接复制粘贴代码到编辑器
- 方式2：使用 Lean CLI 推送
  ```bash
  lean cloud push --project "My Project"
  ```

---

## 2. 云端配置调整

### 2.1 股票池配置
在云端，`stock_pools.json` 可以直接读取：

```python
# 策略内已自动处理路径
self.stock_pool_file = "stock_pools.json"  # 云端项目根目录
self.stock_pool_source = "combined"        # 可选: sp500, nasdaq100, combined
```

### 2.2 VIX指数
云端自动使用VIX指数（数据完整）：
```python
# 代码已自动处理
vix_sym = self.AddIndex("VIX", Resolution.DAILY).Symbol
```

### 2.3 数据分辨率
云端支持更细粒度数据（可选）：
```python
# 如需更精确的入场/出场，可改为 Minute
Resolution.DAILY   # 当前配置
Resolution.MINUTE  # 更高精度（回测更慢）
```

---

## 3. 回测参数设置

### 3.1 基本设置
```python
self.SetStartDate(2020, 1, 1)    # 开始日期
self.SetEndDate(2026, 6, 30)     # 结束日期
self.SetCash(100000)              # 初始资金
```

### 3.2 推荐测试场景

| 场景 | 开始日期 | 结束日期 | 说明 |
|------|----------|----------|------|
 牛市测试 | 2020-01-01 | 2021-12-31 | 疫情后牛市 |
| 熊市测试 | 2022-01-01 | 2022-12-31 | 加息熊市 |
| 完整周期 | 2020-01-01 | 2024-12-31 | 完整牛熊 |
| 最新数据 | 2020-01-01 | 2026-06-30 | 包含最新 |

---

## 4. 关键参数调优

### 4.1 股票池选择
```python
self.stock_pool_source = "combined"   # 混合池（推荐）
# 或
self.stock_pool_source = "sp500"      # 仅标普500（更稳健）
# 或
self.stock_pool_source = "nasdaq100"  # 仅纳指100（更高波动）
```

### 4.2 仓位管理
```python
self.max_position_pct = 0.10    # 单票最大10%（保守）
# 或
self.max_position_pct = 0.15    # 单票最大15%（激进）

self.max_total_exposure = 0.50  # 总仓位上限50%
# 或
self.max_total_exposure = 0.80  # 总仓位上限80%（牛市）
```

### 4.3 回撤控制
```python
self.stop_loss_pct = 0.08       # 固定止损8%
self.trailing_stop_pct = 0.10   # 追踪止损10%
self.max_drawdown_pct = 0.15    # 最大回撤保护15%
```

---

## 5. 回测步骤

### 5.1 点击回测
1. 在 QuantConnect 编辑器中点击 **Backtest** 按钮
2. 等待回测完成（通常需要 5-15 分钟）

### 5.2 查看结果
回测完成后查看：
- **总收益率**
- **夏普比率**
- **最大回撤**
- **胜率**
- **交易次数**

### 5.3 优化建议
如果结果不理想，可以调整：
1. 股票池（sp500/nasdaq100/combined）
2. 仓位限制（10%-15%）
3. 止损参数（5%-10%）
4. 调仓频率（1-4周）

---

## 6. 常见问题

### Q1: VIX数据不可用？
**A:** 云端自动使用VIX指数，如仍有问题，代码会自动回退到VIXY。

### Q2: 股票池文件读取失败？
**A:** 确保 `stock_pools.json` 已上传到项目根目录，或使用硬编码列表。

### Q3: 回测太慢？
**A:** 
- 减少股票数量（选sp500而非combined）
- 使用 `Resolution.DAILY` 而非 Minute
- 缩短回测时间范围

### Q4: 交易费用过高？
**A:** 调整调仓频率：
```python
self.base_rebalance_freq = 4  # 改为每4周调仓一次
```

---

## 7. 部署到实盘

### 7.1 准备工作
1. 确保回测结果满意（夏普 > 1.0，回撤 < 40%）
2. 在 Interactive Brokers 开设账户
3. 连接 QuantConnect 到 IB

### 7.2 启动实盘
1. 在 QuantConnect 点击 **Live**
2. 选择 **Interactive Brokers**
3. 输入 IB 账户凭证
4. 设置初始资金
5. 启动实盘交易

---

## 8. 监控和维护

### 8.1 每日检查
- 查看持仓和盈亏
- 检查是否有止损触发
- 确认VIX水平和市场状态

### 8.2 每周调整
- 查看调仓日志
- 检查行业集中度
- 确认股票池是否需要更新

### 8.3 每月回顾
- 分析策略表现
- 对比基准指数（SPY/QQQ）
- 调整参数（如需要）

---

## 9. 联系支持

如有问题：
- QuantConnect 论坛: https://www.quantconnect.com/forum
- GitHub Issues: https://github.com/zhouyouhulianwang/quant-strategies/issues

---

**最后更新:** 2026-07-10
**版本:** v3.1
