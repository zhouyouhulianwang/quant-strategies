# 执行与风控模块审查报告

**审查日期**: 2026-07-21
**审查范围**: `/home/pc/.openclaw/workspace/multifactor`
**重点文件**: `alpaca_executor.py` (2054 行), `order_manager.py` (965 行), `risk_monitor.py` (622 行)，关联文件 `pdt_tracker.py`、`intraday_monitor.py`、`strategies/v14.py`、`strategies/portfolio.py`、`run_multi_strategy.py`
**账户状态假设**: 当前持有 31 个 V14 仓位，组合价值 ~$98,370（paper）

---

## 0. 执行摘要

三大模块整体工程质量较高：历史审计（V2 报告）中识别的 P0/P1 缺陷（base_url 校验、幂等 client_order_id、PDT 双侧检查、熔断调 halt_trading、购买力预检、收盘保护二次检查、until datetime 分页、PDT 多次往返计数、补单冲突取消等）**在当前代码中均已修复**。

但针对"31 仓位 / $98k 切换到多策略组合"这一具体场景，仍存在 **3 个高优先级风险**：

| # | 等级 | 问题 |
|---|------|------|
| A | **高** | 多策略切换将产生 ~31 笔卖出 + N 笔买入的同日大批量调仓；$98,370 equity < $25k 的 PDT 豁免线**不适用**（>25k），但若 equity 跌穿 $25k，单日 31+ 笔 round-trip 会立即触发 PDT 锁仓 |
| B | **高** | `StrategyPortfolio._execute_live_trades` 走 `RebalanceManager.rebalance`（无 atomic_precheck、无流动性检查、无批量 PDT 预估算），而单策略 V14 走 `AlpacaExecutor.rebalance_portfolio`（有完整 precheck）。**多策略路径的风控保护反而弱于单策略** |
| C | **高** | `RiskMonitor.check_drawdown` 的峰值基于**进程内存中**的 `nav_history`（重启即重置）；多策略首次调仓若与旧 V14 持仓市值存在基准差，可能在切换当日被误判为大幅回撤并触发 halt+强平 |

其余中低优先级问题见 §4/§5。

---

## 1. 模块逐一审查

### 1.1 `alpaca_executor.py`

**优点（已落实的安全机制）**

- **凭证/端点强校验**（`__init__` ~L460-485）：`paper` 与 `base_url` 必须严格匹配且仅允许两个官方域名；SDK 缺失时非 mock 模式直接 `RuntimeError` 而非静默 mock。
- **Live 二次确认**：交互式 `input("Enter 'LIVE'")`，非交互环境默认拒绝，可用 `ALPACA_LIVE_CONFIRMED=1` 显式跳过。
- **订单幂等**：`client_order_id = v14-{session}-{symbol}-{side}-{qty}`（L1006），`_find_order_by_client_id` 去重；session 按日期生成，跨日不冲突。
- **PDT 双向检查**（`_check_pdt` L677）：账户信息不可用时**默认拒绝**（fail-closed）；买入/卖出都过 PDT。
- **资金预检**（`_check_account_funds` L696）：买单带 5% buffer；cash 账户用 cash，margin 用 buying_power。
- **市价单保护**（`_get_protected_order_type` L800）：高 ATR/宽 spread 时自动转限价单，限价偏移封顶 2%，spread 异常封顶 2%；`_round_to_tick` 按价格段选 tick（<$1 用 0.0001，否则 0.01）。
- **连续拒单熔断**（`_maybe_halt_on_rejections` L854）：≥5 次连续拒单 → `risk_monitor.halt_trading()`（带告警+持久化），成功后重置计数。
- **kill switch / trading_halted 双重门**：`submit_order`（L989-999）与 `rebalance_portfolio`（L1720-1730）都检查；紧急平仓通过 `force=True` 显式绕过。
- **`rebalance_portfolio` 完整 precheck**（L1901 `_atomic_precheck`）：市场开市 → 账户 ACTIVE/未冻结 → 总买入额 ≤ (cash+sell_release)×1.05 → 流动性（qty ≤ 2×avg_quote_size）；外加批量 PDT 预估算（`check_orders_pdt_limit`）。
- **回滚**：买入失败时 `_rollback_sells` 买回已卖出仓位。
- **对账**（`reconcile` L1470）：现金 + 持仓逐项对比，broker/local 双向 missing 检测。
- **价格获取 fail-closed**（`_get_current_price` L1570）：无数据源时 raise，不再兜底 100；5 分钟缓存。

**遗留问题**

| # | 等级 | 位置 | 问题 |
|---|------|------|------|
| E1 | 中 | L296-316 `_FakeAlpacaClient.submit_order` | fake client **任何订单立即 filled**，无部分成交/拒单模拟。mock 测试无法覆盖 OrderManager 的补单/超时路径，paper 切换前必须用真实 paper API 做端到端演练 |
| E2 | 中 | L1351 `liquidate_all` 兜底路径 | 逐个 `submit_order(..., force=True)` 强平，**绕过了 PDT 检查**（`_record_pdt=False` 但 `_check_pdt` 仍会被调用——force 只绕过 trading_halted，不绕过 PDT；但紧急强平若触发 PDT 拒单，残余仓位可能留在账上）。`_confirm_liquidation` 重试 3 次后发告警，可接受，但需人工兜底预案 |
| E3 | 低 | L1003 session 按 `YYYYMMDD` | 同一天内若上午调仓失败、下午重跑，相同 symbol+side+qty 的订单会被幂等去重——**这是特性**，但若上午订单已被取消（canceled），`_find_order_by_client_id` 仍会命中并返回已取消订单，导致下午实际不再下单。需确认 `_find_order_by_client_id` 是否过滤 canceled 状态（当前代码未过滤 status） |
| E4 | 低 | `_get_spread`/`_get_atr` 用 `DataFeed.IEX` | IEX 免费 feed 覆盖/深度有限，对流动性检查和 spread 估算可能偏乐观；live 建议确认订阅级别 |

### 1.2 `order_manager.py`

**优点**

- **完整状态机**（L57-77）：7 状态 + 合法转换表，非法转换记 warning + metadata 审计，不会静默覆盖。
- **结构化日志**：关键转换写 JSON logger，CSV 订单日志按日落盘。
- **补单安全**（`_place_makeup_with_cancel` L203）：先撤原单 → 确认 canceled/expired/filled → 才下补单；`max_makeup_depth=1` 防递归失控。
- **组合结果合并**（`_merge_makeup_status`）：原单 canceled 不再强行迁移回 FILLED，组合状态写入 metadata（`composite_status`），规避了 V2 报告的 stale-state 问题。
- **重试策略正确**（L340-370）：仅网络/瞬态错误（rate limit/gateway/timeout/503/504）指数退避 3 次；API 业务拒单（PDT、资金）与 ValueError 直接返回 FAILED 不重试。
- **超时处理**：超时 → 撤单 → 复查实际成交 → 部分成交则走补单合并路径。
- **`RebalanceManager.rebalance`**：归一化目标 → 先卖后买 → **总购买力预检**（L770-790，超出直接 abort+回滚）→ 逐笔二次预检 → topup 前 `_cancel_open_orders_for_symbol`（解决 V2 报告的双补单冲突）→ 失败回滚（买回已卖、卖出已买/撤单）。

**遗留问题**

| # | 等级 | 位置 | 问题 |
|---|------|------|------|
| O1 | **高** | `RebalanceManager.rebalance` 全函数 | **无 atomic precheck、无流动性检查、无批量 PDT 预估算**。多策略 `StrategyPortfolio` 走的就是这条路径（见 §2-B）。而 `AlpacaExecutor.rebalance_portfolio` 有完整 precheck。两条调仓路径保护等级不一致 |
| O2 | 中 | 回滚路径（L860-900） | 回滚用 `self.executor.submit_order(...)` **不等待成交确认**（非 submit_and_wait），回滚单本身的成败未知；若回滚也失败，只记 log。切换日前应准备人工干预 runbook |
| O3 | 中 | `submit_and_wait` 轮询间隔默认 5s、`max_wait_sec` 默认 300s | 31 个卖出 + ~30 个买入串行执行，最差情况 60+ 笔 × 数秒 ≈ 5-10 分钟。收盘保护（15:45 ET cutoff）前必须预留足够时间；建议调仓日 10:00 ET 后尽早执行 |
| O4 | 低 | `_log_order` CSV 字段固定 8 列 | `filled_avg_price` 等之外的信息（client_order_id、reason）不入 CSV，审计依赖 JSON logger；确保 json_logger 落盘配置正确 |

### 1.3 `risk_monitor.py`

**优点**

- **线程安全**：所有可变状态（`trading_halted`、`risk_level`、kill switch flag）走 lock 保护的 property。
- **持久化可靠**：`_atomic_write_json`（tmp + os.replace + 0o600）；启动时 `_load_state` 恢复 halt 状态、原因、max_dd。
- **远程 kill switch**：文件 `data/kill_switch` 或环境变量 `MULTIFACTOR_KILL_SWITCH=1`，触发后走 `halt_trading`（告警+持久化）。
- **VIX 不可用 fail-closed**：None/非法值仅 warning 跳过一次检查，不做错误决策；VIX 回落**不自动恢复**交易，必须显式 `resume_trading()`。
- **回撤/日亏触发即 halt**：`check_drawdown`、`check_daily_loss` 触发返回 True 并 halt（不是仅告警）。

**遗留问题**

| # | 等级 | 位置 | 问题 |
|---|------|------|------|
| R1 | **高** | `check_drawdown` L240 | 峰值来自**进程内** `nav_history`（cummax），持久化只存 `max_dd_seen` 但**不存峰值本身**。进程重启后 nav_history 清空，第一次 check 时 peak = 当前 NAV → 回撤从 0 重新计算。**多策略切换当日**：若切换前 paper 组合价值 $98,370，切换后首次 check 的 NAV 若因成交价/费用略低，不会误判；但若主进程先跑过 V14（缓存了高水位）再以新进程跑多策略，历史高水位丢失，回撤保护会出现空窗。建议：持久化 peak_nav 并在重启时恢复（`intraday_monitor.py` 已这么做，risk_monitor 没有） |
| R2 | 中 | `check_drawdown` 调用点 | `RiskMonitor.check_drawdown` 在 `v14.py live_trade` 中被调用（L770 附近），但 `StrategyPortfolio.run_live_rebalance` **不调用 check_drawdown / check_daily_loss**，只做 concentration 检查。多策略路径的风检覆盖弱于单策略 |
| R3 | 中 | `_calculate_sector_weights` | 行业映射 `from main import INDUSTRY`（38 只 V14 票）。多策略组合若引入 universe 之外的标的，全部落入 `'other'` 行业桶，sector 集中度检查失真 |
| R4 | 低 | `check_position_limits` | 只告警不 halt；单仓超限在切换期（卖出释放现金后再买入的间隙）可能瞬时触发，属预期噪音 |

---

## 2. 多策略切换过渡风险评估（31 仓位 / $98,370）

### 2.1 切换当日会发生什么

`run_multi_strategy.py --paper` → `StrategyPortfolio.run_live_rebalance()`：

1. kill switch / halted / market open / open orders 检查 ✅
2. `generate_signals(live_mode=True)`：5 个子策略各自选股 → 按 30/25/20/15/10 加权聚合 → 归一化 + sector 约束 + （`_get_common_price_df` 返回 None，**vol target overlay 实际不生效**，L380-395）
3. `_execute_live_trades` → `RebalanceManager.rebalance`：
   - **阶段 1：卖出所有不在新目标里的现有持仓**（31 只中大部分）
   - **阶段 2：买入/调整目标持仓**

### 2.2 具体风险

| 风险 | 分析 | 缓解 |
|------|------|------|
| **大批量同日 round-trip → PDT** | $98,370 > $25k，当前**不受 PDT 限制**（`can_open_position` equity ≥ 25k 直接放行）。但权益若因回撤跌穿 $25k，同日 30+ 笔买卖会被 PDTTracker 批量预估算拦截 → 调仓中途 abort，留下半切换组合 | 切换前确认 equity 离 $25k 有足够 buffer；监控 `pdt_tracker.get_status()` |
| **多策略路径风控弱（O1/R2）** | `RebalanceManager` 无 atomic precheck / 流动性检查 / 批量 PDT 预估算 / drawdown 检查。当前 31 仓位全是 V14 universe 大盘股，流动性风险低；但缺 drawdown 检查意味着切换当天的浮亏不会触发保护 | **短期**：切换改走 `AlpacaExecutor.rebalance_portfolio`（传入组合 target_positions），或在 `StrategyPortfolio._execute_live_trades` 里先调 `executor.rebalance_portfolio` 的 precheck 再交给 RebalanceManager。**长期**：把 atomic precheck 下沉到 RebalanceManager |
| **信号聚合层缺少最终市值校验** | 5 个子策略 signal 简单加总后归一化，单票权重理论上可达多策略重叠加和（如 NVDA 同时被 3 个策略选中）。`apply_sector_constraints` 只管行业不管单票；`RebalanceManager` 内 `target_value = min(target_value, portfolio_value * max_position_pct)`（20%）有单票兜底 ✅ | 可接受，但应验证聚合后 top1 权重 |
| **卖出现金到账时序** | 阶段 1 卖出是限价/市价单，`submit_and_wait` 等成交；现金释放后阶段 2 买入。若某只卖出部分成交+补单失败，回滚买回 —— 期间组合短暂偏离目标。Alpaca paper 即时成交，真实 live 中等成交时间更长 | 切换日预留 ≥1 小时窗口，10:00 ET 启动 |
| **回撤基准断裂（R1）** | 新进程启动 → nav_history 空 → 切换后第一次 check_drawdown 以当时 NAV 为峰。多策略路径甚至不调 check_drawdown（R2） | 切换前记录 $98,370 作为基准；考虑给 RiskMonitor 增加 peak 持久化 |
| **open orders 双跑保护** | `run_live_rebalance` 检查到 open orders 即 abort ✅。但若 V14 的 scheduler（cron/tmux）与多策略 scheduler 同时启用，可能重复调仓 | **切换前停用旧 V14 的调度入口**，只保留 `run_multi_strategy.py` 一个入口 |
| **行业映射失真（R3）** | 多策略若选出 V14 universe 外的票，sector 检查失效 | 切换首日人工核对目标清单的 sector 分布 |

### 2.3 结论：可以切换，但建议按 §5 的顺序做

---

## 3. 检查项完备性核对

| 检查项 | 状态 | 说明 |
|--------|------|------|
| **PDT** | ✅ 基本完善 | 双侧检查、FIFO lot、先卖后买缓存、批量预估算、broker count 同步、5 交易日 XNYS 滚动窗口、状态持久化 0o600。但**仅 `AlpacaExecutor.rebalance_portfolio` 路径做批量预估算**；`RebalanceManager` 只有单笔 `_check_pdt_can_open` |
| **风控开关** | ✅ 完善 | trading_halted 统一由 RiskMonitor 持有；executor/order_manager/portfolio/v14 所有下单入口均检查；halt 持久化；恢复必须显式 |
| **Kill switch** | ✅ 完善 | 文件 + 环境变量双通道；submit/rebalance/intraday 三层检查 |
| **订单类型** | ✅ 完善 | market/limit；高波动自动转限价；tick 规整；动态偏移（ATR/spread）；`use_limit_orders=true` 可全量限价（当前 config 为 false，live 建议开启） |
| **市场状态检查** | ✅ 完善 | `market_is_open`（clock API）在 run_live_rebalance、live_trade、atomic precheck、intraday liquidation 多处检查；收盘保护 cutoff（15:45 ET）进入和下单前双重检查 |
| **持仓对账** | ⚠️ 有工具、无定时执行 | `executor.reconcile()` 实现了 cash+position 双向对账，但**没有任何调度点自动调用**；建议每日开盘前或调仓后自动执行并告警 |
| **熔断** | ✅ 完善 | 连续 5 次拒单 → halt_trading + 告警 |
| **流动性检查** | ⚠️ 部分 | 仅 `rebalance_portfolio` precheck 有；RebalanceManager 无；`_check_liquidity` 失败时 assume-ok（fail-open） |
| **强平确认** | ✅ 完善 | `_confirm_liquidation` 3 次重试 + 残余逐票强平 + 失败告警 |
| **VIX** | ✅ 完善 | 紧急阈值强平 + risk level 分级；不可用 fail-closed；回落不自动恢复 |

---

## 4. 中低优先级问题汇总

1. **mock 覆盖不足（E1）**：fake client 全部立即成交，partial fill / timeout / 拒单路径只能靠真实 paper API 演练。
2. **回滚不确认成交（O2）**：rollback 单 submit 后不等结果。
3. **对账未调度（§3）**：reconcile 需纳入日常任务。
4. **sector map 局限（R3）**：INDUSTRY 只覆盖 V14 的 38 票。
5. **IEX feed（E4）**：spread/流动性/中间价都基于 IEX，live 前确认数据订阅。
6. **`_find_order_by_client_id` 不过滤状态（E3）**：同日重跑可能命中已取消订单而跳过重试。
7. **多策略 vol overlay 空转**：`_get_common_price_df` 恒返回 None，文档宣称的 15% vol target 在组合层不生效（单策略 V14 内部生效）。

---

## 5. Paper/Live 切换安全建议

### 5.1 多策略切换执行顺序（paper）

```text
D-1 (切换前一日)
  1. 停用旧 V14 调度（cron/tmux/scheduler.py 中指向 run_strategy.py 的任务）
  2. python3 generate_target_positions.py           # 旧 V14 目标（留档）
  3. python3 run_multi_strategy.py --paper --real-data
     的 generate_signals 部分单独 dry-run，导出多策略目标清单，人工核对：
     - 单票最高权重 ≤ 20%
     - sector 分布无异常集中
     - 目标总市值 / portfolio_value 在预期暴露区间
  4. 记录基准：portfolio_value=$98,370、31 个持仓快照、pdt get_status()

D-Day (切换日，建议 10:00-11:00 ET)
  5. 确认 equity > $25k 且 buffer 充足；确认无 open orders
  6. 首选路径：临时改 StrategyPortfolio._execute_live_trades 走
     executor.rebalance_portfolio(target_positions, atomic_check=True,
     enable_rollback=True) —— 拿到 precheck + 批量 PDT + 流动性检查
  7. 执行后：executor.reconcile() 对账；人工核对 orders/ 当日 CSV
  8. 观察 1 个完整交易日：intraday monitor、risk_state.json、告警通道

D+1 ~ D+5
  9. 每日对账 + drawdown 基准跟踪；确认 PDT day_trade_history 无意外累积
 10. 跑通一次完整的"下一个调仓周期"（月度）再考虑加大资金
```

### 5.2 Live 切换前置条件（在 paper 稳定后）

1. **完成 `PRE_LIVE_CHECKLIST.md` 全部 8 节**（目前多数项未打勾）。
2. **先修 O1/R2**：多策略路径补齐 atomic precheck + drawdown 检查（或统一走 `rebalance_portfolio`）。
3. **`use_limit_orders: true`**：当前 config 为 false，live 建议开启（offset 1%，代码会自动按 ATR/spread 收紧）。
4. **live 确认链**：`--live --confirm-live` + 交互输入 `LIVE`；无人值守环境用 `ALPACA_LIVE_CONFIRMED=1`（明确知悉风险）。
5. **独立风控进程**：按 `RISK_RUNBOOK.md` 部署 `risk_process.py`（systemd），与主交易进程隔离。
6. **kill switch 演练**：实际验证 `touch data/kill_switch` 后下单被拒 + 告警到达。
7. **回滚演练**：paper 上人为制造一次买入失败（如临时设极小 buying power），验证 rollback 买回路径。
8. **对账自动化**：每日 cron 调 `executor.reconcile()`，mismatch 时告警 + 暂停下次调仓。
9. **资金分批**：live 首期建议只用部分资金（如 $25-50k）跑 1-2 个月度调仓周期，且 $25k 附近时 PDT 保护会改变行为，需特别测试。
10. **旧持仓处理决策**：live 账户若是新账户无历史持仓则简单；若要把 paper 的 31 仓位"搬"到 live，本质是全新建仓，按 D-Day 流程一次性买入即可，避免分批造成信号漂移。

---

## 6. 优先修复清单（按 ROI 排序）

| 优先级 | 项 | 动作 |
|--------|-----|------|
| 1 | O1/R2 多策略路径风控弱 | `StrategyPortfolio._execute_live_trades` 改走 `rebalance_portfolio`，或将 atomic precheck/批量 PDT/drawdown 检查下沉到 `RebalanceManager` |
| 2 | R1 回撤峰值不持久化 | `RiskMonitor` 持久化 `peak_nav`，重启恢复（参照 `intraday_monitor` 的做法） |
| 3 | §3 对账未调度 | 加每日自动 reconcile + 告警 |
| 4 | E3 幂等命中已取消订单 | `_find_order_by_client_id` 过滤 `canceled/expired/failed` 状态 |
| 5 | O2 回滚不确认 | rollback 走 `submit_and_wait` 并记录结果 |
| 6 | R3 sector map | INDUSTRY 外标的显式归类或从 universe 数据源动态映射 |

---

*审查人：OpenClaw subagent · 只读代码审查，未修改任何源文件，未执行真实交易*
