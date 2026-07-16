

---

# 🆕 P1 高风险缺陷修复（Alpaca 执行链路）

**修复日期:** 2026-07-16  
**提交:** 待补充  
**范围:** `multifactor/AUDIT_REPORT_ALPACA.md` 中 5 个 P1 缺陷（1 个已在 P0 批次处理）

## ✅ P1 修复

| # | 缺陷 | 修复内容 | 文件 |
|---|------|----------|------|
| P1-4 | 日内回撤基准从不重置 | `_monitor_loop()` 每日开盘重置 `daily_high_nav` | `intraday_monitor.py` |
| P1-5 | 无 Alpaca API 速率限制 | 新增 `rate_limiter.py` Token Bucket + `RateLimitedAPI` 包装所有 Alpaca API 调用 | `rate_limiter.py`, `alpaca_executor.py` |
| P1-6 | 部分成交回滚不完整 | `RebalanceManager.rebalance()` 增加 `min_buy_fill_ratio` 参数，部分成交未达比例时触发回滚 | `order_manager.py` |
| P1-7 | 目标仓位总和可能超现金 | 新增 `normalize_target_positions()`，在 `generate_signals()`、`rebalance_portfolio()`、`rebalance()` 中归一化总敞口 | `weight_allocation.py`, `run_strategy.py`, `alpaca_executor.py`, `order_manager.py` |
| P1-8 | 无实时组合级止损 | `IntradayMonitor` 增加 `peak_nav` 累计高点跟踪和 `max_total_drawdown` 止损，月度调仓间也受保护 | `intraday_monitor.py` |

## ✅ 新增文件

- `multifactor/rate_limiter.py` — Token Bucket 速率限制器

## ✅ 新增/更新测试

- `test_normalize_target_positions` — 验证目标持仓归一化
- `test_rate_limiter` — 验证 Token Bucket 限速
- 更新 `test_v14_executor_wrappers` — 验证包装方法

## 验证结果

```bash
cd multifactor
python3 -m pytest test_suite.py -v
# 26 passed, 3 warnings
```

---

*修复人: Qs*  
*仓库: https://github.com/zhouyouhulianwang/quant-strategies*
