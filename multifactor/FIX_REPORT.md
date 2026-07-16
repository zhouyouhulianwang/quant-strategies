---

# 🆕 P0/P1 缺陷修复（Alpaca 执行链路 & PDT/风控）

**修复日期:** 2026-07-16  
**范围:** `multifactor/AUDIT_REPORT_ALPACA.md` 中剩余 P0/P1 缺陷（不含 API Key 与小数股）  
**用户要求:**
- API Key 已自行处理，无需修复
- 小数股保持 `int()` 截断，不改为 fractional
- 其余问题可修复，订单等待超时时间已设置为最大 1800 秒

## ✅ P0 修复

| # | 缺陷 | 修复内容 | 文件 |
|---|------|----------|------|
| P0-1 | PDT 在提交时记录 | 重写 `PDTTracker`：基于 FIFO lot 记录，仅在成交（filled）时判定 day trade | `pdt_tracker.py` |
| P0-2 | PDT 状态未区分 paper/live | `PDTTracker` 按 `account_id` + `paper` 参数分文件存储（`data/pdt_{account_id}.json`） | `pdt_tracker.py`, `alpaca_executor.py` |
| P0-3 | 无持仓/现金对账 | 新增 `AlpacaPaperExecutor.reconcile(expected_cash, expected_positions)`，对比本地与券商持仓/现金差异 | `alpaca_executor.py` |
| P0-4 | live 模式无二次确认 | `AlpacaPaperExecutor.__init__` 增加 `require_live_confirmation`；非 paper 模式下要求输入 `LIVE` 才能继续 | `alpaca_executor.py` |
| P0-5 | 订单超时无撤单 | `OrderManager.submit_and_wait` 超时时调用 `executor.cancel_order(order_id)`，然后返回 `TIMEOUT` | `order_manager.py` |

## ✅ P1 修复

| # | 缺陷 | 修复内容 | 文件 |
|---|------|----------|------|
| P1-9 | 订单超时时间不可配置 | `config.py` 中 `max_wait_sec` 默认设为 1800（最大），并透传至 `run_strategy.py` → `RebalanceManager.rebalance` | `config.py`, `run_strategy.py`, `order_manager.py` |
| P1-10 | 订单部分成交未记录 PDT | `OrderManager` 在 `filled`/`partially_filled` 时调用 `executor.record_fill(symbol, side, filled_qty)` | `order_manager.py` |
| P1-11 | 无持仓同步机制 | `AlpacaPaperExecutor.sync_positions()` 将券商持仓同步到 `PDTTracker` | `alpaca_executor.py` |
| P1-12 | `.gitignore` 未覆盖新 PDT 文件 | 更新 `.gitignore` 排除 `data/pdt_*.json` | `.gitignore` |

## ✅ 新增文件

- `multifactor/pdt_tracker.py` — 重写后的 PDT 追踪器（FIFO lot、成交驱动、按账户分文件）

## ✅ 修改文件

- `multifactor/alpaca_executor.py` — live 确认、PDT 按账户初始化、record_fill、sync_positions、cancel_order、reconcile
- `multifactor/order_manager.py` — 超时撤单、成交记录 PDT、超时可透传
- `multifactor/run_strategy.py` — 将 `max_wait_sec` / `poll_interval` 从配置传给 `RebalanceManager`
- `multifactor/config.py` — `max_wait_sec` 默认 1800 秒
- `multifactor/.gitignore` — 排除 `data/pdt_*.json`
- `multifactor/test_suite.py` — 新增 PDT、OrderManager、Reconciliation 测试

## ✅ 新增/更新测试

- `test_pdt_records_on_fill` — PDT 仅在成交时记录
- `test_pdt_blocks_after_three_day_trades` — 3 次 day trade 后阻止开仓
- `test_pdt_cash_account_not_restricted` — 现金账户不受限
- `test_pdt_state_file_separate_by_account` — paper/live 状态文件隔离
- `test_order_manager_timeout_cancel` — 超时时撤销订单
- `test_order_manager_records_fill` — 成交时记录 PDT
- `test_reconcile_consistent` / `test_reconcile_cash_mismatch` / `test_reconcile_position_mismatch` — 对账一致/差异

## 验证结果

```bash
cd multifactor
source .venv/bin/activate
python3 -m pytest test_suite.py -v
# 35 passed, 0 warnings
```

## ⚠️ 仍保留的决策（按用户要求）

- **小数股**: 保持 `int()` 截断，不启用 fractional trading
- **API Key**: 用户已自行轮换，未在代码中修改

## ⚠️ 未在本次修复的剩余问题

- 实时行情仍依赖 `yfinance`（`alpaca_executor._get_current_price` 回退到 Yahoo），限价单在实盘中价格源不够实时；建议后续接入 Alpaca 实时报价或 websocket
- 独立风控进程仍为单进程运行，未拆分为独立服务
- 未实现部分成交后自动补单（当前仅记录 PDT 和超时撤单）

---

*修复人: Qs*  
*仓库: https://github.com/zhouyouhulianwang/quant-strategies*
