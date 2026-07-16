

---

# 修复状态（2026-07-16 更新）

## P0 严重缺陷

| # | 缺陷 | 状态 | 修复提交 |
|---|------|------|----------|
| 1 | 实盘调仓不检查市场开盘时间 | ✅ 已修复 | `afa9450` |
| 2 | 实盘信号使用延迟收盘数据 | ✅ 已修复（增加 `live_mode` 与 EOD 日志说明） | `afa9450` |
| 3 | 紧急平仓不检查市场状态 | ✅ 已修复 | `afa9450` |

## P1 高风险缺陷

| # | 缺陷 | 状态 | 修复文件 |
|---|------|------|----------|
| 4 | 日内回撤基准从不重置 | ✅ 已修复 | `intraday_monitor.py` |
| 5 | 无 API 速率限制 | ✅ 已修复 | `rate_limiter.py`, `alpaca_executor.py` |
| 6 | 部分成交回滚不完整 | ✅ 已修复 | `order_manager.py` |
| 7 | 目标仓位总和可能超现金 | ✅ 已修复 | `weight_allocation.py`, `run_strategy.py`, `alpaca_executor.py`, `order_manager.py` |
| 8 | 无实时组合级止损 | ✅ 已修复 | `intraday_monitor.py` |

## P2 / P3 缺陷

待后续处理：结构化日志接入、配置凭证验证、交易通知告警、公司行为处理、价格缓存优化、线程优雅关闭、版本追踪等。

---

*修复人: Qs*  
*仓库: https://github.com/zhouyouhulianwang/quant-strategies*
