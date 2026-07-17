# MultiFactor V14 量化交易系统综合审计报告（Paper / Live 专项）

**审计日期：** 2026-07-17  
**审计范围：** `/home/pc/.openclaw/workspace/multifactor` 全项目  
**重点：** Alpaca Paper / Live 交易执行缺陷、风控、数据、配置、运维链路  
**测试验证：** `python3 -m pytest test_suite.py -q` → **65 passed**  
**与 AUDIT_REPORT_V2.md 关系：** 本报告不重复 V2 已记录内容，但会标注 V2 中仍未完全修复的问题。

---

## 执行摘要

| 等级 | 数量 | 说明 |
|------|------|------|
| **Critical** | 0 | 未发现立即导致爆仓或合规灾难的单点缺陷 |
| **High** | 8 | 实盘前必须修复，涉及风控失效、紧急平仓、数据 PIT、保证金/PDT、凭证泄露 |
| **Medium** | 13 | 影响稳定性、一致性、合规性或运维 |
| **Low** | 10 | 改进项，建议逐步清理 |

**核心结论：** 当前代码在回测和 Paper 模拟环境下运行基本正常，但距离可无人值守运行的 Live 实盘仍有明显缺口。最大风险集中在 **“风控只告警不暂停”**、**“紧急平仓无兜底”**、**“多数据源缓存冲突导致 PIT 未来信息”**、**“账户保证金/PDT 检查缺失”** 四个环节。

---

## 与 AUDIT_REPORT_V2.md 的衔接说明

V2 中记录的两项 High 缺陷当前状态：

| V2 缺陷 | 当前状态 | 说明 |
|---------|----------|------|
| **H1 `config.json` 凭证泄露风险** | ⚠️ 未完全修复 | `config.json` 仍被 Git 追踪，`.gitignore` 未包含。 |
| **H2 回测/实盘信号路径不一致** | ⚠️ 部分修复 | 已共用 `generate_signals()`，但数据缓存键冲突和 PIT 问题仍导致路径不一致。 |

以下正文只列出新发现或验证为未修复的问题。

---

## 🔴 High 缺陷（实盘前必须修复）

### H1. `config.json` 仍被 Git 追踪，凭证泄露风险未消除

**文件/位置：** `config.json`, `.gitignore`, `config.py`  
**状态：** 验证为未修复（V2 H1 已记录，但当前仍存在）

**问题：**
- `.gitignore` 中未包含 `config.json`，因此 `config.json` 已被 Git 追踪。
- `config.py` 的 `V14StrategyConfig` 允许 `alpaca_api_key` / `alpaca_api_secret` 从 `config.json` 读取（`field_validator` 只在值为空时回退环境变量）。

**风险场景：**
用户将真实 Alpaca Key/Secret 写入 `config.json` 后提交，历史记录中永久保留凭证；GitHub 泄露扫描后可能被封号。

**修复建议：**
1. 立即在 `.gitignore` 中添加 `config.json`。
2. 从 Git 历史中移除已提交的 `config.json`：`git rm --cached config.json`。
3. 在 `config.py` 中拒绝从 `config.json` 读取 Alpaca 凭证，强制仅通过环境变量或运行时显式传入。
4. 添加 CI 检查（如 `git-secrets`）阻止包含 `PK`/`SK` 的提交。

---

### H2. `RiskMonitor` 的回撤/日亏损触发时只告警，不暂停交易

**文件/位置：** `risk_monitor.py:check_drawdown()`, `risk_monitor.py:check_daily_loss()`

**问题：**
- `check_drawdown()` 检测到回撤超过 `max_drawdown_limit` 时仅触发 `_trigger_alert('DRAWDOWN', ...)`，未设置 `self.trading_halted = True`。
- `check_daily_loss()` 检测到日亏损超过 `daily_loss_limit` 时同样只告警，不暂停交易。

**风险场景：**
最大回撤或日亏损限制仅用于记录日志；策略主线程和盘中监控仍可能继续下单，扩大亏损。

**修复建议：**
1. 触发阈值时立即设置 `self.trading_halted = True`。
2. 区分临时暂停（日亏损每日重置）与永久暂停（累计回撤需人工确认恢复）。
3. 所有风险检查统一到一个入口 `check_all_risk()`，确保状态一致。

---

### H3. `RiskMonitor` 的 `risk_level` / `trading_halted` 缺乏线程安全保护

**文件/位置：** `risk_monitor.py:RiskMonitor.__init__()`, `check_vix_level()`, `check_drawdown()`, `intraday_monitor.py`

**问题：**
- `risk_level` 和 `trading_halted` 是普通类属性，没有锁保护。
- `IntradayMonitor` 在子线程中写入 `self.risk_monitor.trading_halted`，主线程在 `live_trade()` / `run_live_rebalance()` 中读取。

**风险场景：**
CPU 指令交错时，子线程已设置 `trading_halted=True`，但主线程读取到旧值 `False`，继续提交订单，导致风控失效。

**修复建议：**
1. 为 `RiskMonitor` 添加 `threading.Lock()` 或 `threading.Event()`，将 `trading_halted` 封装为 property。
2. 所有写入操作（VIX、回撤、日亏损、恢复）都通过锁保护。
3. 统一状态来源：仅 `RiskMonitor` 持有 `trading_halted`，`IntradayMonitor` 和 `AlpacaExecutor` 通过 property 读取/写入。

---

### H4. 紧急平仓（emergency liquidation）失败后无确认、无重试、无兜底

**文件/位置：** `intraday_monitor.py:_emergency_liquidation()`, `_liquidate_symbol()`

**问题：**
- `_emergency_liquidation()` 调用 `self.executor.liquidate_all()` 提交市价单后，仅记录日志，不等待成交确认、不检查是否成功。
- 如果网络中断、API 限流、订单被拒绝或市场突然关闭，平仓可能失败，但系统仍认为已触发保护并持续保持 `trading_halted=True`（不再交易，但也不尝试重新平仓）。

**风险场景：**
在大幅波动行情中，未成交的平仓意味着组合继续暴露，风险敞口等同于未触发保护。

**修复建议：**
1. `liquidate_all()` 返回后轮询持仓，确认所有目标仓位已平。
2. 对失败的股票进入重试队列，使用限价单或智能订单路由（如收盘前用 MOC）。
3. 增加“保护失败”告警升级（短信/电话 webhook），人工介入。
4. 在 `trading_halted=True` 后，下一次监控循环仍检查持仓是否非空，非空则重新尝试平仓。

---

### H5. 多数据源缓存键冲突，回测/实盘缺乏 Point-in-Time（PIT）保证

**文件/位置：** `data_source.py`, `quantconnect_data.py`, `polygon_data.py`, `strategies/v14.py:generate_signals()`

**问题：**
- 三个数据源都使用 `_get_cache_path(symbol)` 生成 `{CACHE_DIR}/{symbol}.parquet`，缓存文件会被不同数据源覆盖。
- 复权逻辑不一致：Yahoo 默认调整后收盘价；QuantConnect 优先使用 `adjusted_close`；Polygon 使用 `adjusted=true`。
- 实盘 `generate_signals(live_mode=True)` 重新下载 400 日数据，而回测使用切片 252 日；两者不仅长度不同，还可能因为缓存命中导致数据来源不同。
- 没有 PIT 检查：缓存中可能包含未来才发生的公司行为调整（如拆股、分红），实盘用这些价格计算信号会引入未来信息。

**风险场景：**
回测在 QC 数据上跑出高收益，实盘使用 Polygon 缓存数据触发不同信号，导致回测与实盘绩效不可比；PIT 错误会导致信号含有未来信息，实盘亏损。

**修复建议：**
1. 缓存键按 `source+symbol+adjustment` 隔离，例如 `{symbol}_{source}_{adjustment}.parquet`。
2. 在 `generate_signals` 的 live 路径和回测路径中，强制使用同一数据源和同一复权方法。
3. 实盘信号生成只能使用前一日收盘（EOD）数据，不能用盘中实时价格；增加断言或日志记录最新可用数据日期。
4. 对 `get_corporate_actions()` 的拆股/分红/并购事件在信号生成前进行 PIT 校验和剔除退市股票。

---

### H6. Live 实盘路径缺少账户级保证金/权益检查

**文件/位置：** `alpaca_executor.py:submit_order()`, `order_manager.py:submit_and_wait()`, `run_strategy.py:run_live_rebalance()`

**问题：**
- `AlpacaExecutor` 在提交订单前未检查账户可用现金、购买力（buying power）或保证金状态。
- `OrderManager` 不验证下单后是否会导致超额交易（over-trading）或保证金不足。
- 只有 `PDTTracker` 的日交易限制，缺少账户权益检查。

**风险场景：**
在资金不足或保证金调用（margin call）情况下仍提交买单，订单被 Alpaca 拒绝；高频拒绝可能触发风控或账户限制；极端情况下可能导致透支。

**修复建议：**
1. 在 `submit_order()` 之前调用 `get_account()` 检查 `buying_power` / `cash` / `equity`。
2. 对买单增加 `qty * price <= available_cash` 的预检查，并留出缓冲（如 5%）应对滑点和价格变动。
3. 在 `OrderManager` 中捕获 Alpaca 的 `InsufficientMarginError` / `InsufficientBuyingPowerError`，触发 `trading_halted` 或暂停该标的。

---

### H7. 市价单在波动行情中无价格保护

**文件/位置：** `alpaca_executor.py:submit_order()`, `order_manager.py:submit_and_wait()`, `matching_engine.py`

**问题：**
- 默认使用 `order_type='market'` 提交市价单，未在剧烈波动时转换为保护性限价单（bracket/limit）或增加最大可接受价格偏移。
- `matching_engine.py` 的成本模型假设滑点固定，但实盘市价单在波动时可能以极端价格成交。

**风险场景：**
开盘缺口、闪崩、停牌复牌时，市价单以远高于/低于预期的价格成交，造成单笔巨额亏损。

**修复建议：**
1. 在波动率升高（VIX > 阈值、或标的 ATR 放大）时，将市价单改为限价单，并设置相对 last price 的最大偏移（如 ±1%）。
2. 对 `limit` 单使用 `bracket` 或 `take_profit` / `stop_loss` 附加单。
3. 在 `matching_engine.py` 中根据实时 spread/ATR 动态调整滑点假设，而不是固定 10 bps。

---

### H8. `AlpacaExecutor` 默认未启用 PDT 追踪

**文件/位置：** `alpaca_executor.py:AlpacaExecutor.__init__()`, `order_manager.py:submit_and_wait()`

**问题：**
- `AlpacaExecutor` 的 `enable_pdt` 默认可能为 `False`（取决于调用路径），导致在低于 25k 的保证金账户中无日交易保护。
- `OrderManager` 在提交订单前不调用 `pdt_tracker.can_open_position()`。

**风险场景：**
小资金账户在 5 个交易日内完成 3 次以上 day trade 后，Alpaca 禁止开仓；若本地未拦截，会连续提交订单并被拒绝，可能触发账户限制。

**修复建议：**
1. 默认启用 PDT 追踪。
2. 在 `OrderManager.submit_and_wait()` 的开仓路径前调用 `pdt_tracker.can_open_position()`，被拒绝时返回明确状态。
3. 从 Alpaca 账户读取 `daytrade_count` 作为权威值，本地计数仅用于预估。

---

## 🟠 Medium 缺陷（影响稳定性、一致性或合规）

### M1. `OrderManager` 未处理部分成交

**文件/位置：** `order_manager.py:submit_and_wait()`

**问题：**
- 只等待订单最终状态（`filled`/`canceled`/`rejected`），不处理 `partially_filled` 状态。
- 如果订单被部分成交后取消，系统未记录剩余未成交数量，也不会触发补单。

**风险场景：**
调仓目标为 100 股，只成交 50 股并被取消，系统仍认为目标已达成，导致实际持仓偏离目标权重。

**修复建议：**
1. 处理 `partially_filled` 状态，记录 `filled_qty` / `remaining_qty`。
2. 在订单超时或取消后，根据未成交差额决定是否补单或调整目标。
3. 对补单次数和总金额设限，避免无限循环。

---

### M2. 多个模块中存在大量 `except Exception` 捕获，可能静默系统异常

**文件/位置：** `intraday_monitor.py:_monitor_loop()`, `quantconnect_data.py`, `polygon_data.py`, `data_source.py`, `strategies/v14.py` 等

**问题：**
- 监控线程、数据获取、策略主循环中广泛使用 `except Exception as e`，会吞掉 `KeyboardInterrupt`、`SystemExit`、内存错误等不应被忽略的系统异常。

**风险场景：**
- Ctrl+C 无法退出程序。
- OOM 时继续运行，导致系统不稳定。

**修复建议：**
- 仅捕获预期的业务异常（`ConnectionError`, `Timeout`, `APIError`, `ValueError`）。
- 顶层入口保留 `except Exception` 仅用于崩溃日志和优雅退出，其他地方不应使用裸 `except Exception`。

---

### M3. PDT 追踪使用 `date.today()` 基于本地机器时区，而非市场交易日边界（ET）

**文件/位置：** `pdt_tracker.py:_reset_if_new_day()`, `record_fill()`, `can_open_position()`

**问题：**
- PDT 日交易计数使用 `date.today()`，受服务器本地时区影响。

**风险场景：**
- 美东时间收盘后，若服务器在西部时区或 UTC，`date.today()` 可能早于美东收盘日期，导致跨日判断错误。
- 错误阻止或允许交易，违反 PDT 规则。

**修复建议：**
- 统一使用美东时区（ET）的日期作为交易日边界：`datetime.now(ZoneInfo('America/New_York')).date()`。
- 所有 `date.today()` 调用替换为带时区版本的工具函数。

---

### M4. PDT 滚动计数使用 7 个自然日近似 5 个交易日，节假日期间不准确

**文件/位置：** `pdt_tracker.py:_rolling_count()`

**问题：**
- 使用 `cutoff = today - timedelta(days=7)` 近似 5 个交易日。

**风险场景：**
- 感恩节、圣诞、元旦等长假期间，7 个自然日可能只覆盖 3-4 个交易日，导致计数偏保守；也可能覆盖 6 个交易日而偏激进。

**修复建议：**
- 使用 `exchange_calendars` 的 XNYS 日历计算真正的 5 个交易日前日期。
- 或直接读取 Alpaca 返回的 `daytrade_count` 作为权威值。

---

### M5. 撮合引擎参数未与配置联动

**文件/位置：** `matching_engine.py:ExecutionParameters.__init__()`, `config.py`

**问题：**
- `ExecutionParameters` 的滑点、冲击成本、最小持仓、小数股等参数使用硬编码默认值。
- `config.py` 的 `TradingConfig` 中没有对应字段，导致 `from_config()` 永远取默认值。

**风险场景：**
- 回测成本假设与实盘不一致，回测绩效不可信。
- 参数调整需要改代码，无法通过配置热更新。

**修复建议：**
- 在 `TradingConfig` 中暴露 `slippage_bps`, `market_impact_bps`, `min_position_value`, `use_fractional_shares` 等字段。
- `ExecutionParameters.from_config()` 读取这些字段。

---

### M6. `matching_engine.py` 默认禁用小数股

**文件/位置：** `matching_engine.py:ExecutionParameters.__init__()`, `config.py`

**问题：**
- `ExecutionParameters` 默认 `use_fractional_shares=False`。
- `config.py` 的 `TradingConfig` 中没有 `use_fractional_shares` 字段。
- 回测 `build_portfolio` 使用 `int(target_value / price)` 截断；live 的 `RebalanceManager._calculate_qty` 也使用 `int(Decimal)` 截断（虽然有 `_qty_residuals` 补偿，但只在 `alpaca_executor` 中）。

**风险场景：**
- 组合资金利用率低，回测与 live 资金利用率不一致。
- 无法充分利用 Alpaca 小数股能力。

**修复建议：**
- 在 `TradingConfig` 中增加 `use_fractional_shares: bool` 配置项。
- 回测引擎和 live 下单统一使用 `Decimal` 精度或启用小数股，确保资金利用率一致。

---

### M7. 限价单动态偏移未使用 ATR/Spread

**文件/位置：** `alpaca_executor.py:submit_limit_order()` 或相关限价单逻辑

**问题：**
- 限价单价格偏移逻辑存在，但调用时 `atr` 和 `spread` 通常为 `None`，退回到固定偏移。

**风险场景：**
- 低流动性股票上固定偏移可能无法成交；高波动股票上固定偏移可能成交价格远离市场。

**修复建议：**
- 在下单前计算标的 ATR 和当前 spread，动态设置限价单偏移。
- 对无法获取 ATR/spread 的标的，使用默认保守偏移并记录日志。

---

### M8. 未对订单拒绝进行熔断

**文件/位置：** `alpaca_executor.py:submit_order()`, `order_manager.py:submit_and_wait()`

**问题：**
- 连续订单被拒绝（如价格错误、账户限制、市场关闭）时，系统没有熔断或暂停逻辑。

**风险场景：**
- 重复提交同一错误订单，可能触发 API 限流或账户风控。
- 错误订单消耗资金/PDT 次数。

**修复建议：**
- 记录连续拒绝次数，超过阈值时设置 `trading_halted` 并发送告警。
- 对特定错误码（如 `invalid_symbol`, `insufficient_buying_power`）增加分类处理。

---

### M9. `alert_manager.py` 文件写入无并发保护，无告警去重

**文件/位置：** `alert_manager.py:_write_alert()`

**问题：**
- `_write_alert` 使用 `open(self.alert_file, 'a')` 直接追加 JSON 行，无锁保护。
- 没有告警去重/节流，同一风险事件每个检查周期都会写入一条记录。

**风险场景：**
- 多线程同时写入导致 JSON 行损坏。
- VIX 高时每秒产生大量重复告警，磁盘和日志系统被淹没。

**修复建议：**
- 使用 `threading.Lock()` 保护文件写入。
- 增加告警去重（基于 `type + symbol + 时间窗口`）。
- 考虑使用结构化日志或数据库替代行追加 JSON 文件。

---

### M10. `scheduler.py` 的 `run_once` 硬编码使用 Paper Trading

**文件/位置：** `scheduler.py:run_once()`

**问题：**
- `run_once()` 用于 cron 调用，但内部固定 `use_paper_trading=True`。

**风险场景：**
- 用户配置为 live 模式并希望通过 cron 运行，`run_once()` 无法满足需求，可能导致误用或需要额外脚本。

**修复建议：**
- 让 `run_once` 读取环境变量或命令行参数（如 `USE_PAPER` / `LIVE_CONFIRMED`）来决定是否使用 paper。
- 或提供一个通用入口 `run_once(strategy)` 接受外部构造的策略实例。

---

### M11. 公司行为（分红/并购）获取后未实际应用于持仓或价格序列

**文件/位置：** `data_source.py:get_corporate_actions()`, `alpaca_executor.py:sync_corporate_actions()`

**问题：**
- `get_corporate_actions()` 返回分红、拆股、并购标记，但 `prepare_backtest_data` 和回测引擎中没有使用这些信息。
- `sync_corporate_actions()` 只处理拆股（split），不处理分红和并购。

**风险场景：**
- 分红会导致价格跳空，若不调整持仓成本或历史价格，回撤和收益计算会出现偏差。
- 并购退市股票若未从股票池移除，可能向 Alpaca 提交无效订单。

**修复建议：**
- 在回测中根据分红和拆股调整价格序列（PIT 调整）。
- 在实盘调仓前，检查目标股票是否即将退市或停牌，并从股票池中移除。
- 对并购事件发送告警并跳过相关标的。

---

### M12. `run_strategy.py` 默认行为仍是回测，CLI 参数设计容易造成误操作

**文件/位置：** `run_strategy.py:main()`

**问题：**
- `if args.backtest or not args.live:` 表示不带任何参数时默认执行回测。
- 没有互斥检查：`--backtest` 和 `--live` 同时存在时，先回测再 live，可能导致意外。

**风险场景：**
- 用户可能想运行 live 但忘记加 `--live`，结果只跑回测；或者想运行回测但误加 `--live`。

**修复建议：**
- 无参数时打印帮助并退出，强制用户显式选择 `--backtest` 或 `--live`。
- `--live` 和 `--backtest` 互斥，同时存在时报错或给出明确警告。

---

### M13. 多个 `trading_halted` 状态源，存在单一真相源缺失

**文件/位置：** `intraday_monitor.py:trading_halted` property, `risk_monitor.py:trading_halted`, `alpaca_executor.py:trading_halted`

**问题：**
- `IntradayMonitor` 有自己的 `_halted` 和锁，同时通过 setter 写入 `risk_monitor.trading_halted`。
- `AlpacaExecutor` 自己也有 `trading_halted`，并在 `submit_order` 中检查 `self.trading_halted or self.risk_monitor.trading_halted`。
- 恢复交易时，`IntradayMonitor.resume_trading()` 只修改自己的 `_halted` 和 `risk_monitor.trading_halted`，但不修改 `AlpacaExecutor.trading_halted`（除非通过 `risk_monitor` 引用）。

**风险场景：**
- 状态不一致：某个组件被手动设置 `trading_halted=True` 后，其他组件不知道。

**修复建议：**
- 使用单一真相源（Single Source of Truth）：由 `RiskMonitor` 持有 `trading_halted` 和锁。
- `IntradayMonitor` 和 `AlpacaExecutor` 都通过 `risk_monitor` 的 property 读写状态，不维护本地副本。
- 紧急停止入口统一为 `risk_monitor.halt_trading(reason)` 和 `risk_monitor.resume_trading()`。

---

## 🟡 Low 缺陷（改进项）

### L1. `json_logger.py` 的 `'json'` logger 可能未写入文件

**文件/位置：** `json_logger.py:_ensure_json_logger()`, `logging_config.py:_configure_json_logger()`

**问题：**
- `_configure_json_logger` 只给 `'json'` logger 添加 `StreamHandler`，没有文件 Handler。
- 如果用户期望结构化事件被持久化到 `logs/multifactor.log`，实际上不会写入（因为 `propagate=False`）。

**修复建议：**
- 将 `'json'` logger 的 `propagate` 设为 True，或专门添加一个按日期轮转的 JSON 文件 Handler。

---

### L2. `JSONFormatter` 使用当前 UTC 时间而非 `record.created`

**文件/位置：** `logging_config.py:JSONFormatter.format()`

**问题：**
- `timestamp` 使用 `datetime.now(timezone.utc)`，而不是 LogRecord 的 `created` 字段。

**修复建议：**
- 使用 `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()`。

---

### L3. `risk_monitor.py` 的 `nav_history` 和 `alerts_history` 无限增长

**文件/位置：** `risk_monitor.py:__init__()`, `check_drawdown()`

**问题：**
- 长期运行的调度进程中，`nav_history` 和 `alerts_history` 会持续增长，最终消耗大量内存。

**修复建议：**
- 对 `nav_history` 保留最近 N 条（如 1000 条或最近 90 天）。
- 对 `alerts_history` 保留最近 30 天或固定数量，超过部分写入持久化文件后从内存中移除。

---

### L4. `intraday_monitor.py` 默认 `daemon=True` 可能中断紧急操作

**文件/位置：** `intraday_monitor.py:start()`

**问题：**
- 默认 `daemon=True` 意味着主线程退出时监控线程被强制终止，可能正在执行的紧急平仓或待处理平仓逻辑被中断。

**修复建议：**
- 默认 `daemon=False`，并在 `run_strategy.py` 的 `finally` 中调用 `monitor.stop()` 和 `monitor.join()`。

---

### L5. 日志中仍有中文和 emoji，部分日志分析工具可能编码不一致

**文件/位置：** `scheduler.py`, `quantconnect_data.py`, `polygon_data.py` 等

**问题：**
- 调度器、数据下载等模块使用中文日志和 emoji（如 `✅`, `📥`, `🕐`）。

**修复建议：**
- 用户可见/机器可解析的日志统一使用英文，中文保留在文档和注释中。

---

### L6. `backup_state.py` 的 `--encrypt` 是占位符，未实现真实加密

**文件/位置：** `backup_state.py:run_backup()`

**问题：**
- 备份可能包含 `.env` 和 PDT 状态文件等敏感信息，但 `--encrypt` 仅打印提示，未进行加密。

**修复建议：**
- 使用 `gpg` 或 `age` 实现真实加密，或默认使用 `age` 加密备份。
- 在未实现加密前，在文档中明确标注备份未加密，并限制备份目录权限。

---

### L7. `config.py` 的 `get_config()` 不支持运行时重载

**文件/位置：** `config.py:get_config()`

**问题：**
- 运行期间修改 `config.json` 不会生效，需要重启进程。

**修复建议：**
- 增加 `reload()` 方法，并提供基于文件修改时间戳的自动重载选项（可选，避免频繁读取）。

---

### L8. 调度器对 `daily` 频率触发时间的文档与实现不一致

**文件/位置：** `scheduler.py` 注释和 `should_rebalance()`

**问题：**
- 注释说 daily 在“每个交易日收盘后 16:30 ET 执行”，但实现中 daily 和 weekly/monthly 统一在 10:00 ET 触发（`REBALANCE_OPEN_TIME = time(10, 0)`）。

**修复建议：**
- 统一注释和实现；如果 daily 确实要在收盘后执行，单独处理 `REBALANCE_CLOSE_TIME` 逻辑。

---

### L9. 测试套件缺少对风控、调度、数据缓存的集成测试

**文件/位置：** `test_suite.py`

**问题：**
- 65 个测试全部通过，但覆盖范围集中在因子、配置、订单、PDT；缺少对 `IntradayMonitor` 线程安全、`RiskMonitor` 暂停交易、`scheduler` 交易日历、`data cache` 隔离的测试。

**修复建议：**
- 增加 `TestRiskMonitor` 验证 `check_drawdown` 和 `check_daily_loss` 设置 `trading_halted`。
- 增加 `TestIntradayMonitor` 使用 mock executor 验证紧急平仓和恢复。
- 增加 `TestScheduler` 验证节假日和月末首个交易日。
- 增加 `TestDataCache` 验证不同数据源缓存隔离。

---

### L10. 没有运行时健康检查/心跳机制

**文件/位置：** 全局架构

**问题：**
- 系统长期运行（如通过 `scheduler.py` 或 cron）时，没有外部健康检查或心跳来确认进程活着、监控线程未死、API 连接正常。
- 如果监控线程因异常退出（`daemon=True` 且主线程仍在运行），风险事件将无人处理。

**修复建议：**
- 增加 `healthcheck.py` 或 `heartbeat` 机制，定期写入心跳文件/日志，并可通过外部监控检查。
- 在监控线程异常退出时，主线程应检测并重启或告警。

---

## 建议下一步（按优先级）

| 优先级 | 事项 | 涉及缺陷 |
|--------|------|----------|
| **P0 安全止血** | 将 `config.json` 加入 `.gitignore` 并从 Git 历史清除 | H1 |
| **P0 风控生效** | 修复 `RiskMonitor` 的 `check_drawdown` / `check_daily_loss` 使其设置 `trading_halted=True` | H2 |
| **P0 线程安全** | 为 `trading_halted` 增加锁并统一各模块状态来源 | H3, M13 |
| **P0 数据一致** | 按数据源隔离缓存键，强制实盘/回测使用同一数据源和复权方法 | H5, M7 |
| **P1 平仓兜底** | 为 `IntradayMonitor._emergency_liquidation` 增加成交确认、失败重试和升级告警 | H4 |
| **P1 账户保护** | 在 Live 下单前增加保证金/权益检查，并处理订单拒绝 | H6, H8 |
| **P1 价格保护** | 市价单增加动态价格保护（限价单/偏移） | H7 |
| **P1 测试补强** | 增加风控、调度、数据缓存、执行链路的集成测试 | L9 |
| **P2 工程化** | 修复日志、告警并发、备份加密、默认 daemon、配置重载等 Low 项 | L1-L8, L10 |

---

*审计人：Qs + 两个并行子代理（Alpaca 执行链路、风控/数据/调度/日志）*  
*审计方法：静态代码分析 + 模块测试运行 + 量化交易最佳实践对比*
