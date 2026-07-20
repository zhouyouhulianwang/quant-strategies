# V14 MultiFactor 实盘前最终检查清单

> 本清单用于在首次接入 Alpaca Paper/Live 前逐项验证。完成项前打 `x`，未完成项需确认后再启动实盘。

---

## 1. 数据与回测验证

- [ ] **长期回测通过**：`python3 run_strategy.py --backtest --start 2020-01-01 --end 2024-12-31 --real-data` 无报错。
- [ ] **Walk-forward OOS 通过**：`python3 walk_forward_test.py --start 2020-01-01 --end 2024-12-31 --train-years 2 --test-months 6` 结果在预期区间。
- [ ] **数据新鲜度**：QuantConnect / Lean 数据路径可用，最新日线数据距当前不超过 1 个交易日。
- [ ] **数据覆盖度**：`TICKERS` 列表中所有标的在目标回测区间内均有足够历史数据。

---

## 2. 环境、密钥与配置

- [ ] **API Key 来源**：`ALPACA_API_KEY`、`ALPACA_API_SECRET` 已从环境变量读取，未硬编码在 `config.json` 中。
- [ ] **config.json 未进 Git**：`git status` 显示 `config.json` 为 untracked 或 `.gitignore` 已生效。
- [ ] **Base URL 匹配**：
  - Paper 模式：`https://paper-api.alpaca.markets`
  - Live 模式：`https://api.alpaca.markets`
- [ ] **Python 环境**：`alpaca-py` 已安装且版本与策略兼容（当前 v1.0.227+）。
- [ ] **时区正确**：服务器时区为 `America/New_York`，`tmux` / cron 环境 `TZ` 已设置。

---

## 3. Alpaca 账户与权限

- [ ] **账户状态 ACTIVE**：`get_account()` 返回 `status == 'ACTIVE'`，无 `trading_blocked` 或 `trade_suspended_by_user`。
- [ ] **账户类型确认**：明确是 `MARGIN` 还是 `CASH`。若为 MARGIN 且权益 < $25k，需启用 PDT 检查。
- [ ] **PDT 规则**：`enable_pdt=True` 时，`pdt_tracker` 已同步券商 `daytrade_count`。
- [ ] **购买力**：`buying_power` / `cash` 足以覆盖目标调仓。
- [ ] **API 权限**：数据订阅包含 `TICKERS` 列表中的全部标的（IEX/SIP）。

---

## 4. 风控与交易开关

- [ ] **回撤限制**：`max_drawdown` 阈值已根据风险承受能力设定（默认 15%）。
- [ ] **日亏损限制**：`daily_loss` 阈值已确认（默认 3%）。
- [ ] **VIX 暂停阈值**：`vix_pause_level` 已确认（默认 35）。
- [ ] **单仓/行业限制**：`max_position_pct` 与 `max_sector_pct` 符合策略要求。
- [ ] **Kill Switch 就绪**：`data/kill_switch` 文件或环境变量 `MULTIFACTOR_KILL_SWITCH=1` 可立即暂停交易。
- [ ] **RiskMonitor 状态持久化**：`data/risk_state.json` 存在，权限为 600。
- [ ] **未成交订单检查**：`live_trade` 中已检查 `open_orders`，避免重复调仓。

---

## 5. 订单与执行

- [ ] **订单类型**：实盘默认使用 `limit` 或 `market`，已确认并与回测成本模型一致。
- [ ] **订单幂等性**：`client_order_id` 格式为 `v14-{session}-{symbol}-{side}-{qty}`，可复现。
- [ ] **最小下单金额**：`submit_order` 已过滤 <$1 的碎股/迷你订单。
- [ ] **流动性检查**：`min_liquidity_ratio` 已设置，避免冲击成本过大。
- [ ] **Atomic 预检查**：`rebalance_portfolio` 的 `atomic_check=True` 已启用。
- [ ] **回滚机制**：调仓失败时 `enable_rollback=True` 可重新买入已卖出标的。

---

## 6. 监控、告警与日志

- [ ] **日志目录**：`logs/`、`orders/`、`alerts/`、`charts/` 存在且未失控增长。
- [ ] **告警通道**：`alert_manager` 已配置（如 Telegram/邮件），可接收 `HALT` / `DRAWDOWN` / `KILL_SWITCH` 告警。
- [ ] **Intraday Monitor**：如启用，确认监控频率和持仓同步正常。
- [ ] **备份脚本**：`python3 backup_state.py` 运行成功，备份文件权限 600。

---

## 7. Paper 预演

- [ ] **Paper 模式 Dry Run**：`python3 run_strategy.py --paper --confirm-live` 至少成功运行一次完整调仓。
- [ ] **订单核对**：Paper 交易订单与策略目标持仓一致，无异常 symbol 或数量。
- [ ] **资金曲线记录**：Paper 运行期间每日记录 `portfolio_value` 与 `cash`。
- [ ] **无重复/遗漏订单**：`orders/` 下当日订单无重复 `client_order_id`。

---

## 8. Live 启动确认（仅首次实盘）

- [ ] **已确认 `--confirm-live`**：命令行显式传入 `--live --confirm-live`。
- [ ] **已核对资金规模**：初始资金与策略目标仓位一致。
- [ ] **已关闭测试/调试代码**：无 `if True:` 强制调仓、无 mock 数据 fallback。
- [ ] **已通知相关人员**：紧急联系人、止损决策人已知悉。
- [ ] **已确认 kill switch 操作人**：可物理访问服务器或能远程设置环境变量。

---

## 签名

- [ ] 检查人：____________
- [ ] 检查日期：____________
- [ ] 版本/commit：____________
- [ ] 是否允许启动实盘：是 / 否

---

> 提示：每次修改配置或风控参数后，重新运行 `python3 backup_state.py` 并更新本清单。
