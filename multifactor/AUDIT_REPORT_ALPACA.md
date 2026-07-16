# Alpaca 模拟/实盘执行审计报告

**审计时间:** 2026-07-16  
**审计对象:** `multifactor/` V14 策略 Alpaca Paper Trading 执行链路  
**审计维度:** 框架、代码、逻辑、风控、日志、配置

---

## 严重缺陷 (P0)

### 1. 实盘调仓不检查市场开盘时间

**文件:** `run_strategy.py` → `run_live_rebalance()`

**问题:**  在提交订单前没有调用 `market_is_open()` 检查。Alpaca 在市场收盘时仍会接受订单（状态为 `accepted`），但直到次日开盘才会执行。这会导致：
- 用当日收盘信号执行次日开盘价
- 在长假/周末前下单，持仓暴露于隔夜风险
- 紧急平仓在市场关闭时无法生效

**建议:**
```python
def run_live_rebalance(self):
    if not self.executor.market_is_open():
        logger.warning("市场已收盘，跳过本次调仓")
        return
    ...
```

**影响:** 高 — 可能导致非预期执行时机和隔夜风险。

---

### 2. 实盘信号使用延迟收盘数据而非实时价格

**文件:** `run_strategy.py` → `generate_signals(price_df=None, vix=None)`

**问题:**  当 `price_df=None` 时，使用 `prepare_backtest_data_qc()` 或 `prepare_backtest_data()` 获取历史日线数据。这意味着实盘调仓基于**昨日收盘价**计算信号，而 Alpaca 执行时使用**当前实时价格**。在市场高波动或隔夜跳空时，目标仓位与实际成交价可能严重偏离。

**建议:**
- 实盘路径应使用 Alpaca 实时 latest_trade/quote 构建当前价格快照
- 或至少使用 Alpaca `get_bars()` 获取最新数据
- 区分 `generate_signals_backtest()` 和 `generate_signals_live()`

**影响:** 高 — 信号与执行价格不一致，尤其在波动市。

---

### 3. 紧急平仓在市场关闭时无法执行

**文件:** `intraday_monitor.py` → `_emergency_liquidation()`

**问题:**  盘中监控触发紧急平仓时直接调用 `executor.liquidate_all()`，没有检查市场是否开盘。如果 VIX 飙升或个股暴跌发生在盘前/盘后或周末，订单会被接受但挂起到开盘，无法起到保护作用。

**建议:**
```python
def _emergency_liquidation(self, reason):
    if not self.executor.market_is_open():
        # 发送告警，等待开盘；或改用扩展交易
        logger.critical("市场已收盘，紧急平仓订单将在开盘时执行")
    ...
```

**影响:** 高 — 风控失效。

---

## 高风险缺陷 (P1)

### 4. 日内回撤基准从不重置

**文件:** `intraday_monitor.py`

**问题:**  `daily_high_nav` 仅在首次检查时初始化，后续即使跨越多天也不会重置。这导致：
- 第 2 天及以后的回撤计算基准是历史最高点，而不是当日开盘
- 永远无法触发 `max_intraday_dd=10%` 的盘中止损

**建议:** 在 `_monitor_loop` 中检测日期变化，每日开盘时调用 `reset_daily_high()`。

**影响:** 高 — 盘中止损永久失效。

---

### 5. 无 API 速率限制保护

**文件:** `alpaca_executor.py`, `order_manager.py`

**问题:**  Alpaca 免费账户限制约 200 请求/分钟。当前代码在以下场景可能超限：
- 38 只股票再平衡 × 多个 API 调用（价格、下单、订单状态轮询）
- 盘中监控每 60 秒获取账户 + 持仓 + VIX
- 订单状态轮询每 5 秒一次

**建议:** 引入 Token Bucket 或简单计数器，对 Alpaca API 调用做限速和重试。

**影响:** 高 — 可能导致 429 错误、临时封禁或交易失败。

---

### 6. 部分成交后的回滚逻辑不完整

**文件:** `order_manager.py` → `RebalanceManager.rebalance()`

**问题:**  `failed_buy` 仅在订单状态为 `rejected`/`TIMEOUT`/`ERROR` 时触发。对于 `partially_filled` 的买入订单，策略不会回滚，但目标仓位未达成。同时，回滚买回数量使用 `sell_result.get('filled_qty')`，但 CSV 日志中可能缺失该字段。

**影响:** 中-高 — 部分失败会导致组合状态偏离目标。

---

### 7. 目标仓位总和可能超过账户价值

**文件:** `run_strategy.py` → `generate_signals()`

**问题:**  `target_positions` 是各股票目标金额，但没有校验总和是否 <= 账户价值。在极端情况下（如 VIX 低时选股多 + 等权分配），加上购买整数股向上取整，可能超出可用现金。

**建议:** 在 `generate_signals()` 后增加 `normalize_total_exposure()` 函数，确保总敞口 <= 100% 现金。

**影响:** 中 — 可能导致买入失败或强制融资。

---

### 8. 无实时组合级止损

**文件:** `run_strategy.py`, `risk_monitor.py`

**问题:**  `check_drawdown()` 仅在调用时执行，实盘调仓只检查一次 VIX，没有持续监控组合累计回撤。如果月度调仓之间出现大幅下跌，策略不会止损。

**建议:** 启动定时任务（如 cron 或独立线程）每日收盘后检查回撤，或在盘中监控中增加基于组合价值的止损。

**影响:** 高 — 缺少趋势保护。

---

## 中风险缺陷 (P2)

### 9. 结构化日志未接入主链路

**文件:** `json_logger.py` 存在但未被使用

**问题:**  所有交易、风控、订单事件仍使用普通文本日志。这导致：
- 难以做日志聚合和审计
- 无法快速检索某个订单的完整生命周期

**建议:** 在 `order_manager.py`、`alpaca_executor.py`、`risk_monitor.py` 中替换关键日志为 `json_logger`。

**影响:** 中 — 运维和审计困难。

---

### 10. 配置验证未包含 Alpaca 凭证检查

**文件:** `config.py`

**问题:**  `V14StrategyConfig` 没有验证 `ALPACA_API_KEY` 和 `ALPACA_API_SECRET` 是否设置。这会导致实盘运行到执行阶段才报错。

**建议:** 增加运行时验证：
```python
def validate_alpaca_credentials(self):
    if not os.getenv('ALPACA_API_KEY'):
        raise ValueError('ALPACA_API_KEY 未设置')
```

**影响:** 中 — 配置错误发现延迟。

---

### 11. 无交易通知/告警机制

**文件:** `risk_monitor.py` 有 AlertManager，但 `order_manager.py` 未使用

**问题:**  订单失败、成交、风控触发等事件不会主动通知用户（Telegram/邮件）。用户可能错过关键交易事件。

**建议:** 在 `OrderManager._log_order()` 和 `RiskMonitor._trigger_alert()` 中调用告警通道。

**影响:** 中 — 关键事件延迟发现。

---

### 12. 公司行为处理缺失

**文件:** 持仓管理相关代码

**问题:**  股票拆分、合股、分红再投资等公司行为会导致 Alpaca 持仓数量与本地记录不一致。当前代码没有同步机制处理。

**建议:** 每次调仓前从 Alpaca 重新拉取持仓（当前已做），但需记录公司行为事件以便审计。

**影响:** 低-中。

---

## 低风险/优化项 (P3)

### 13. 价格缓存 5 分钟可能过时

**文件:** `alpaca_executor.py` → `_get_current_price()`

**问题:**  在高波动市场，5 分钟缓存可能导致价格偏差。

**建议:** 降低缓存时间到 30-60 秒，或取消缓存改用实时报价。

---

### 14. 无优雅关闭 intraday_monitor 线程

**文件:** `intraday_monitor.py` → `stop()`

**问题:**  `stop()` 使用 `join(timeout=5)`，但如果线程被阻塞，可能无法完全停止。

**建议:** 使用 `threading.Event()` 代替布尔标志，确保可中断。

---

### 15. 缺少交易版本追踪

**文件:** 订单日志

**问题:**  CSV 订单日志中没有记录策略版本或 Git commit hash，无法追溯哪次代码变更导致某笔交易。

**建议:** 在订单日志中增加 `strategy_version` 和 `git_commit` 字段。

---

## 总结

| 优先级 | 数量 | 关键问题 |
|--------|------|----------|
| P0 | 3 | 市场时间检查、实时数据、紧急平仓 |
| P1 | 5 | 日内回撤、速率限制、部分成交、仓位超限、组合止损 |
| P2 | 4 | 结构化日志、凭证验证、告警、公司行为 |
| P3 | 3 | 缓存、线程关闭、版本追踪 |

**建议优先修复顺序:** P0 → P1 → P2 → P3

**当前实盘风险:** 虽然代码层面已实现订单幂等性、Atomic 预检查和风控框架，但实盘执行时存在**延迟数据驱动交易**、**无市场时间保护**和**盘中风控失效**等严重问题，建议在修复前不要运行真实资金交易。
