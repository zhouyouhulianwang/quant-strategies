# Alpaca 纸交易 / 实盘执行路径审计报告

**审计对象：** `/home/pc/.openclaw/workspace/multifactor`  
**审计日期：** 2026-07-17  
**审计范围：** `alpaca_executor.py`、`order_manager.py`、`pdt_tracker.py`、`run_strategy.py`、`strategies/v14.py`、`risk_monitor.py`、`intraday_monitor.py`、`config.py` / `config.json`  
**审计结论：** 项目已经具备相对完善的 live 二次确认、PDT 检查、限价保护、风控触发等基础能力，但在 **风控与执行器联动、PDT 状态同步、订单生命周期管理、CLI 纸交易路径** 等关键位置仍存在可造成亏损或资金风险的问题。

---

## 1. 执行摘要

本次审计采用只读静态分析，重点审查 Alpaca 纸交易与实盘切换、订单提交、风控联动、PDT 追踪、日志与配置安全。发现的主要风险点如下：

- **P0（立即资金风险）7 项**：风控监控器未与执行器正确关联，风险触发后无法阻止在途订单；部分成交补单逻辑可能重复下单；`base_url` 与 `paper` 标志不一致可能导致“以为是纸交易，实则实盘”；`AlpacaExecutor` 直接调仓路径不检查 `trading_halted`；PDT 追踪器把未知建仓日期的持仓默认当作今日建仓，导致错判 day trade。
- **P1（显著风险 / 可靠性）13 项**：订单提交网络/API 失败后无重试、PDT 券商 daytrade_count 未在每次调仓刷新、紧急平仓与失败兜底路径未记录 PDT、CLI 的 `--paper` 实际上不会进行纸交易、配置解析失败时静默回退到默认值等。
- **P2（工程债务 / 可维护性）8 项**：订单全生命周期日志不完整、缺少订单状态机、VIX 备用数据源用 yfinance、PDT 交易日历回退到 7 个自然日等。

---

## 2. 现有控制措施（值得保留）

| 控制点 | 说明 |
|--------|------|
| Live 二次确认 | `AlpacaPaperExecutor.__init__` 在非 paper 模式下默认要求终端输入 `LIVE`，并支持 `ALPACA_LIVE_CONFIRMED=1` 环境变量用于非交互环境。 |
| API Key 来源 | 优先读取环境变量 `ALPACA_API_KEY` / `ALPACA_API_SECRET`，`config.json` 中不保留真实密钥。 |
| Base URL 校验 | `config.py` 与 `alpaca_executor.py` 均校验 base_url 只能是 Alpaca 官方域名。 |
| PDT 检查 | `alpaca_executor.py` 的 `submit_order` 已覆盖 buy / sell 两侧，且低于 $25k 权益时进行限制。 |
| 购买力检查 | 下单前预留 5% 缓冲检查 `buying_power`（保证金账户）或 `cash`（现金账户）。 |
| 限价保护 | 高波动或 `use_limit_orders=True` 时自动把市价单转为限价单，并动态计算偏移。 |
| 速率限制 | 可选 `RateLimitedAPI` 包装 Alpaca 客户端，限制 200 请求/分钟。 |
| 结构化日志 | `json_logger.py` + `logging_config.py` 支持 JSON 结构化日志，记录订单、风控、组合快照。 |
| 收盘前保护 | `V14Strategy.run_live_rebalance` 在收盘前 15 分钟（默认）拒绝新调仓。 |
| 幂等 client_order_id | 使用 `v14-{session}-{symbol}-{side}-{qty}` 作为 client_order_id，避免重复下单。 |

---

## 3. 缺陷清单

### 3.1 P0 — 可能立即造成亏损 / 资金风险

#### P0-1：V14Strategy 中风控监控器未与执行器关联，风险触发后无法阻止在途订单

- **位置：** `strategies/v14.py`，`__init__` 方法（约第 183–195 行）
- **具体问题：**
  ```python
  if self.use_paper_trading:
      ...
      self.executor = AlpacaExecutor(**executor_kwargs)
      if self.risk_monitor:
          self.executor.set_risk_monitor(self.risk_monitor)   # 此时 self.risk_monitor 为 None
  ```
  执行器在 `self.risk_monitor` 尚未创建之前就被初始化，因此 `set_risk_monitor` 永远不会被调用。`AlpacaPaperExecutor.submit_order` 中检查 `self.risk_monitor.trading_halted` 的代码失效，风险触发后已启动的调仓或直接在执行器上的订单仍可继续提交。
- **风险等级：** P0
- **修复建议：** 先创建 `self.risk_monitor`，再创建 `self.executor`，并在创建后显式调用 `self.executor.set_risk_monitor(self.risk_monitor)`。或者把 `trading_halted` 状态移到一个可被两个对象共同访问的独立开关。

#### P0-2：AlpacaExecutor.rebalance_portfolio 不检查 `trading_halted`

- **位置：** `alpaca_executor.py`，`AlpacaExecutor.rebalance_portfolio`（约第 1340 行起）
- **具体问题：** 该直接调仓入口只在 `AlpacaPaperExecutor` 中检查 `risk_monitor.trading_halted`，但包装器自身没有统一检查。若 `V14Strategy` 的 `ORDER_MGR_AVAILABLE` 为 False，或外部代码直接调用 `AlpacaExecutor.rebalance_portfolio`，风控暂停状态会被绕过。
- **风险等级：** P0
- **修复建议：** 在 `AlpacaExecutor.rebalance_portfolio` 开头增加统一的 `trading_halted` 检查，并返回统一的状态码。

#### P0-3：部分成交后补单未先撤销原订单，可能导致重复成交 / 超配

- **位置：** `order_manager.py`，`submit_and_wait` 方法（约第 260–300 行）
- **具体问题：** 当订单状态为 `partially_filled` 时，`submit_and_wait` 直接调用 `_place_makeup_order` 对剩余数量发起新订单，但**没有取消原订单**。如果原订单仍是 DAY 限价单并继续成交，则系统会持有超过目标数量的仓位。
- **风险等级：** P0
- **修复建议：** 在发起补单前，先调用 `self.executor.cancel_order(order_id)` 并确认原订单状态为 `canceled` / `expired` / `filled` 后再补单。或者默认使用 `TimeInForce.IOC` 以避免挂单。

#### P0-4：`base_url` 与 `paper` 标志不一致可导致误用实盘

- **位置：** `alpaca_executor.py`，`AlpacaPaperExecutor.__init__`（约第 330 行附近）
- **具体问题：** 代码校验 `base_url` 只能是两个官方域名之一，但实际创建 SDK 客户端时只传 `paper=True/False`，**没有把 `base_url` 传给 `TradingClient`**。因此：
  - 配置 `base_url=https://api.alpaca.markets` 但 `paper=True` → SDK 仍然连接纸交易接口；
  - 配置 `base_url=https://paper-api.alpaca.markets` 但 `paper=False` → SDK 仍然连接实盘接口。
  这会导致操作者以为自己在纸交易，实际却下了真实资金订单。
- **风险等级：** P0
- **修复建议：** 强制 `paper` 与 `base_url` 一致：
  - `paper=True` 时 `base_url` 必须是 `https://paper-api.alpaca.markets`；
  - `paper=False` 时 `base_url` 必须是 `https://api.alpaca.markets`。
  或者直接让 SDK 使用 `base_url` 覆盖（如 SDK 支持 `url_override`）。

#### P0-5：PDT 追踪器把未知建仓日期的持仓默认记为“今日建仓”，导致大量误判 day trade

- **位置：** `pdt_tracker.py`，`sync_positions` 方法（约第 180–210 行）
- **具体问题：**
  ```python
  entry_date = pos.get('entry_date') or today
  ```
  Alpaca 的 `Position` 对象不提供 `entry_date`，因此所有同步进来的持仓都会被标记为今天买入。随后若当天卖出这些持仓，系统会误判为 day trade，迅速消耗掉 3 次额度，导致后续合法开仓被错误阻止。
- **风险等级：** P0（会导致误停交易 / 误触发紧急平仓逻辑）
- **修复建议：** 对于没有 `entry_date` 的持仓，不要默认设为今天；应标记为未知/历史持仓，卖出时不计入 day trade，或从 Alpaca 成交记录（`get_orders` / `get_portfolio_history`）反向推断真实建仓日期。

#### P0-6：紧急平仓 / 强平后 PDT 记录基于错误日期的持仓，放大 P0-5 影响

- **位置：** `alpaca_executor.py`，`liquidate_all` 方法（约第 1120–1145 行）
- **具体问题：** `liquidate_all` 在调用 `close_all_positions()` 后，使用本地缓存的持仓列表调用 `pdt_tracker.record_fill('sell', ...)`。由于持仓的 `entry_date` 已被 `sync_positions` 错误设为今天，这会把所有卖出记录为 day trade，进一步耗尽 PDT 额度，并可能触发错误的交易暂停。
- **风险等级：** P0
- **修复建议：** 同 P0-5；同时在 `liquidate_all` 中应从券商订单/成交确认获取真实成交记录，而不是基于本地缓存持仓推断。

#### P0-7：紧急平仓与主交易线程存在竞态，风控触发后仍可能继续下单

- **位置：** `intraday_monitor.py`，`_emergency_liquidation`（约第 260–310 行）
- **具体问题：** 监控线程设置 `self.trading_halted = True` 后调用 `liquidate_all`。但主调仓线程正在执行 `RebalanceManager.rebalance` 时，两者没有共享的原子锁。可能出现监控线程正在平仓的同时，主线程仍在提交新的买入订单，造成“一边平仓一边加仓”。
- **风险等级：** P0
- **修复建议：** 在 `AlpacaPaperExecutor.submit_order` 内部使用一个线程安全的 `trading_halted` 标志；或者使用 `threading.Event` / `RLock`，确保任何下单请求在风险触发后立即可见并拒绝。

---

### 3.2 P1 — 显著风险或可靠性问题

#### P1-1：订单提交失败（网络 / API 错误）后没有重试机制

- **位置：** `order_manager.py`，`submit_and_wait`（约第 140–220 行）
- **具体问题：** 如果 `executor.submit_order` 返回 `None`（网络抖动、Alpaca 短暂 5xx、连接超时），`OrderManager` 直接返回 `{'status': 'FAILED'}`，没有重试。在市场快速波动或开盘时，这可能导致整个调仓只完成一部分，留下非目标暴露。
- **风险等级：** P1
- **修复建议：** 增加指数退避重试（最多 3 次），对 `APIError`、`RequestException`、`ConnectionError`、`Timeout` 进行重试；对明确拒绝（如 `insufficient_buying_power`）则立即失败。

#### P1-2：券商 daytrade_count 未在每次调仓前刷新

- **位置：** `strategies/v14.py`，`run_live_rebalance`（约第 765–780 行）
- **具体问题：** 每次调仓前调用 `self.executor.sync_positions()` 仅同步持仓，没有同步 Alpaca 返回的 `daytrade_count`。`pdt_tracker.sync_positions` 支持 `broker_daytrade_count` 参数，但调用方未传入。因此如果用户通过其他客户端或手动交易产生了 day trade，本地计数会滞后。
- **风险等级：** P1
- **修复建议：** 在 `run_live_rebalance` 中先获取账户信息，把 `account.get('daytrade_count')` 传入 `sync_positions`。

#### P1-3：`liquidate_all` 失败兜底路径未记录 PDT

- **位置：** `alpaca_executor.py`，`liquidate_all`（约第 1130–1145 行）
- **具体问题：** 当 `close_all_positions()` 抛出异常时，代码回退到逐个 `submit_order` 卖出。但这些 `submit_order` 调用本身不会自动触发 `record_fill`，因此 `pdt_tracker` 不会更新，留下 PDT 状态与真实成交不一致。
- **风险等级：** P1
- **修复建议：** 在兜底路径中，对每个成功卖出的订单显式调用 `self.record_fill(symbol, 'sell', filled_qty)`。

#### P1-4：`submit_order` 自身不记录 PDT，直接调用时状态会漂移

- **位置：** `alpaca_executor.py`，`submit_order`（约第 700–850 行）
- **具体问题：** 只有在 `OrderManager` 或 `AlpacaExecutor.rebalance_portfolio` 中才会调用 `record_fill`。如果策略或脚本直接调用 `AlpacaPaperExecutor.submit_order`，PDT 追踪器不会更新，可能超额 day trade。
- **风险等级：** P1
- **修复建议：** 在 `submit_order` 返回成功且订单状态为 `filled`/`partially_filled` 时，自动调用 `record_fill`；或确保所有入口都经过 `OrderManager`。

#### P1-5：买入失败后回滚直接卖出已买入仓位，可能立即实现亏损

- **位置：** `order_manager.py`，`RebalanceManager.rebalance`（约第 380–420 行）
- **具体问题：** 当后续买入失败触发 rollback 时，会立即以市价单卖出已买入的仓位。这不是把“组合恢复到调仓前”，而是把已实现亏损固定下来。在极端滑点下，一次失败的调仓可能造成显著损失。
- **风险等级：** P1
- **修复建议：** 定义更明确的回滚策略：要么保留部分已成交头寸并继续监控，要么只撤销未成交订单，避免在不利价位强平。需要结合风控规则而不是机械卖出。

#### P1-6：`RebalanceManager.rebalance` 的 `confirm_fills=False` 会完全跳过订单管理保护

- **位置：** `order_manager.py`，`RebalanceManager.rebalance`（约第 270–310 行）
- **具体问题：** 当 `confirm_fills=False` 时，直接调用 `executor.submit_order` 而不经过 `submit_and_wait`。这跳过了超时撤单、部分成交补单、结构化日志等所有订单生命周期管理。虽然 `V14Strategy.live_trade` 默认 `True`，但如果被调用方覆盖，风险较大。
- **风险等级：** P1
- **修复建议：** 移除 `confirm_fills=False` 的代码路径，或至少在该路径下强制记录订单并启动后台监控线程跟踪成交。

#### P1-7：CLI `--paper` 实际上不会运行纸交易，而是运行回测

- **位置：** `run_strategy.py`（约第 50–95 行）
- **具体问题：**
  ```python
  if args.backtest or not args.live:
      result = strategy.run_backtest(...)
  ```
  当传入 `--paper` 时，`args.live=False`，因此进入回测分支，不会执行 `run_live_rebalance`。`--paper` 与 `--backtest` 在行为上没有区别。由于 `--paper` 和 `--live` 是互斥参数，用户无法通过 CLI 真正启动纸交易。
- **风险等级：** P1（功能性 / 操作风险）
- **修复建议：** 修改分支逻辑：
  - `--paper`：执行 `run_live_rebalance` 并传入 `paper=True`；
  - `--backtest`：仅执行回测；
  - `--live`：执行实盘再平衡。

#### P1-8：`paper_smoke_test.py` 的 `--live` 参数实际仍使用纸交易接口

- **位置：** `paper_smoke_test.py`（约第 58 行）
- **具体问题：**
  ```python
  paper = args.paper or True  # 恒为 True
  ```
  即使传入 `--live`，`paper` 也是 `True`，`AlpacaExecutor` 连接的是纸交易接口。脚本名称和文档中 `--live` 表示“下真实订单”，但代码中永远走纸交易，易造成测试与预期不符。
- **风险等级：** P1（误导性 / 测试覆盖缺失）
- **修复建议：** 使用 `paper = args.paper`，让 `--paper` 强制纸交易，不传 `--paper` 时按 `--live` 决定。同时 `--live` 需要额外确认与风险提示。

#### P1-9：`V14Strategy.__init__` 在 `config=None` 且启用纸交易时会崩溃

- **位置：** `strategies/v14.py`（约第 170–178 行）
- **具体问题：** `else` 分支中 `self.config` 为 None，但代码访问 `self.config.trading.use_limit_orders`，会抛出 `AttributeError`。虽然 `run_strategy.py` 会传 config，但其他入口或测试可能触发。
- **风险等级：** P1
- **修复建议：** 在 `else` 分支中使用默认值，而不是访问 `self.config`。

#### P1-10：价格缓存 5 分钟，在市场剧变时会导致限价单与资金检查失准

- **位置：** `alpaca_executor.py`，`_get_current_price`（约第 1200–1240 行）
- **具体问题：** 价格缓存有效期为 300 秒。高波动标的中，5 分钟前的价格可能偏差几个百分点，导致动态限价单价格偏离或购买力检查错误。
- **风险等级：** P1
- **修复建议：** 调仓/下单期间禁用缓存或缩短缓存到 10–30 秒；对限价单提供显式 `limit_price` 时避免覆盖用户意图。

#### P1-11：配置解析失败时静默回退到默认配置

- **位置：** `config.py`，`get_config()`（约第 180–200 行）
- **具体问题：**
  ```python
  except Exception as e:
      print(f"⚠️ 读取 config.json 失败，使用默认配置: {e}")
  ```
  `config.json` 损坏或 JSON 错误时，系统仍使用默认参数（如 `max_position_pct=0.20`、`vix_panic_threshold=35.0`）启动。如果默认值与生产意图不符，可能导致交易参数错误。
- **风险等级：** P1
- **修复建议：** 对配置解析错误应抛出异常并退出，而非静默回退。或在回退时把错误写入日志并触发告警。

#### P1-12：`.env` 加载器会把所有非注释键值对写入环境变量

- **位置：** `alpaca_executor.py`，`AlpacaPaperExecutor.__init__`（约第 250–270 行）
- **具体问题：** 代码读取 `.env` 文件并把所有 `KEY=VALUE` 写入 `os.environ`，不仅仅是 Alpaca 相关变量。这会把 Telegram token、数据库密码等意外扩散到整个进程环境。
- **风险等级：** P1（信息安全 / 范围蔓延）
- **修复建议：** 只加载以 `ALPACA_` 开头（或白名单）的变量，并在 `__init__` 完成后对 `ALPACA_API_SECRET` 等敏感变量不缓存或做最小化使用。

#### P1-13：调仓前对 `generate_signals` 重复调用，可能产生不一致信号

- **位置：** `strategies/v14.py`，`run_live_rebalance`（约第 765–780 行与第 780 行）
- **具体问题：** 代码先调用 `generate_signals(live_mode=True)` 获取股票列表以同步公司行为，然后再次调用 `generate_signals(live_mode=True)` 获取 `target_positions`。如果两次调用之间数据刷新或价格变化，两次信号可能不一致。
- **风险等级：** P1
- **修复建议：** 只调用一次 `generate_signals`，并把结果同时用于公司行为同步和目标持仓。

---

### 3.3 P2 — 工程债务 / 可维护性

#### P2-1：订单全生命周期日志不完整

- **位置：** `order_manager.py`、`alpaca_executor.py`
- **具体问题：** 当前结构化日志只记录最终状态（filled / partially_filled / timeout / rejected）。缺少：
  - 下单请求时的预期参数；
  - 每次轮询的订单状态变化；
  - 撤单请求与结果；
  - 补单与原始订单的关联；
  - 风控触发时刻的持仓快照。
- **风险等级：** P2
- **修复建议：** 引入订单状态机（`SUBMITTED → ACCEPTED → PARTIAL → FILLED / CANCELLED / REJECTED`），每个状态转换都写一条结构化日志，并携带 `client_order_id` 与 `parent_order_id`。

#### P2-2：缺少订单级别事件溯源 / 持久化

- **位置：** `order_manager.py`
- **具体问题：** 订单历史保存在 CSV 中，但 CSV 只记录最终状态。程序重启后无法恢复未完成订单或进行对账。
- **风险等级：** P2
- **修复建议：** 增加轻量级 SQLite / JSONL 订单事件存储，记录每次状态变更，重启后可续跑。

#### P2-3：`get_orders` 只返回前 100 条，无分页

- **位置：** `alpaca_executor.py`，`get_orders`（约第 1080–1100 行）
- **具体问题：**
  ```python
  request = GetOrdersRequest(status=status_enum, limit=100)
  ```
  在订单量大的交易日或长期运行后，可能遗漏历史订单，影响对账与 PDT 重建。
- **风险等级：** P2
- **修复建议：** 支持分页或按日期范围查询，并在外层循环拉取所有记录。

#### P2-4：盘中监控 VIX 备用数据源使用 yfinance

- **位置：** `intraday_monitor.py`，`_get_latest_vix`（约第 340–360 行）
- **具体问题：** 当 `polygon_data` 不可用时回退到 `yfinance`，其稳定性和延迟不适合生产风控触发。
- **风险等级：** P2
- **修复建议：** 增加多数据源优先级（Polygon → Alpaca 数据 API → 备用），并记录每个数据源的可用性与延迟。

#### P2-5：PDT 交易日历回退到 7 个自然日

- **位置：** `pdt_tracker.py`，`_rolling_count`（约第 150–170 行）
- **具体问题：** 未安装 `exchange_calendars` 时，使用 7 个自然日近似 5 个交易日。节假日多的情况下会多算或少算 day trade。
- **风险等级：** P2
- **修复建议：** 把 `exchange_calendars` 加入 `requirements.txt`，并在启动时检查；不可用时发出告警。

#### P2-6：`reconcile` 方法未在运行时被调用

- **位置：** `alpaca_executor.py`，`reconcile`（约第 1160–1220 行）
- **具体问题：** 该方法实现本地与券商持仓对账，但没有任何调度或入口调用它。本地 PDT 与真实持仓长期可能不一致。
- **风险等级：** P2
- **修复建议：** 在每次调仓前 / 盘后自动运行 `reconcile`，并在差异超过阈值时告警或暂停交易。

#### P2-7：没有远程 / 运维层面的 kill switch

- **位置：** 整体架构
- **具体问题：** 交易暂停依赖本地 `RiskMonitor.trading_halted`。如果进程被恶意/异常重启，或配置被外部修改，缺乏一个独立的远程开关（如 Redis 键、文件标记、外部 API）来强制停止交易。
- **风险等级：** P2
- **修复建议：** 增加一个可选的外部 kill switch 检查点，在每个调仓/订单前读取；如果标记为停止，则拒绝交易并告警。

#### P2-8：错误处理中对未捕获异常使用裸 `except Exception` 多处

- **位置：** `alpaca_executor.py`、`strategies/v14.py`、`intraday_monitor.py` 等多处
- **具体问题：** 如 `except Exception as e:` 吞掉异常，仅记录 warning，可能导致问题被掩盖。例如 `sync_corporate_actions` 失败、盘中监控补充检查失败等。
- **风险等级：** P2
- **修复建议：** 区分预期异常（网络超时）与意外异常（代码错误、权限问题），对意外异常应记录详细堆栈并触发告警。

---

## 4. 修复优先级列表

按“先止血、再修复可靠性、最后偿还技术债务”排序：

| 优先级 | 缺陷 | 建议修复动作 | 预计影响 |
|--------|------|--------------|----------|
| 1 | P0-1 / P0-2 / P0-7 | 把风控监控器正确关联到执行器；在 `submit_order` 和 `rebalance_portfolio` 入口使用线程安全的 `trading_halted` 检查；增加原子锁防止平仓与下单竞态。 | 避免风险触发后继续亏损 |
| 2 | P0-4 | 强制 `paper` 与 `base_url` 一致，或通过 `url_override` 让 base_url 真正生效。 | 消除纸/实盘误用风险 |
| 3 | P0-3 | 补单前必须取消原订单，并确认原订单状态。 | 防止重复下单、超配 |
| 4 | P0-5 / P0-6 | 修复 `sync_positions` 对未知 `entry_date` 的默认处理；从券商成交记录推断建仓日期；平仓时基于真实成交记录更新 PDT。 | 避免错误 day trade 计数 |
| 5 | P1-1 | 对订单提交增加指数退避重试（3 次）。 | 减少网络/API 偶发失败导致的不完整调仓 |
| 6 | P1-2 | 每次调仓前把 Alpaca `account.daytrade_count` 同步到 PDT tracker。 | 保证 PDT 限制与券商一致 |
| 7 | P1-3 / P1-4 | 在 `liquidate_all` 兜底路径和 `submit_order` 成功后统一调用 `record_fill`。 | 保持 PDT 状态同步 |
| 8 | P1-5 | 重新评估回滚策略，避免在不利价位机械卖出。 | 降低失败调仓的已实现亏损 |
| 9 | P1-7 | 修复 `run_strategy.py` 的 `--paper` 分支，使其真正执行纸交易调仓。 | 满足 CLI 功能预期 |
| 10 | P1-8 | 修复 `paper_smoke_test.py` 的 `--live` / `--paper` 逻辑。 | 保证烟测能覆盖真实场景 |
| 11 | P1-11 | 配置解析失败时退出而非静默回退。 | 防止错误参数交易 |
| 12 | P1-12 | `.env` 加载白名单化。 | 减少敏感信息泄露 |
| 13 | P2-1 / P2-2 | 建立订单状态机与事件日志存储。 | 提升可观测性与可恢复性 |
| 14 | P2-6 | 定期运行 `reconcile` 并告警。 | 保持本地与券商状态一致 |
| 15 | P2-4 / P2-5 / P2-7 | 替换 yfinance VIX 回退、引入交易日历、增加远程 kill switch。 | 长期稳健性 |

---

## 5. 验证清单（修复后建议执行）

1. **单元测试**：在 mock 模式下模拟风险触发，验证 `submit_order` 是否被阻止。
2. **PDT 测试**：构造跨日持仓，验证 `sync_positions` 不会把隔夜持仓误记为当日建仓。
3. **CLI 测试**：分别运行 `--backtest`、`--paper`、`--live`，确认三者进入不同分支。
4. **base_url 一致性测试**：故意传入 `paper=False` + `paper-api.alpaca.markets` 时，程序应在初始化阶段报错。
5. **部分成交测试**：模拟订单部分成交后仍保持 `open`，验证补单前原订单已被取消。
6. **网络异常测试**：模拟 Alpaca 3 次 5xx/超时，验证订单是否被重试。
7. **日志审计**：确认一条订单从提交、部分成交、撤单、补单到最终成交的全部状态都被结构化日志记录。

---

*报告结束。*
