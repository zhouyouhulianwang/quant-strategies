# MultiFactor V14 风控/数据/调度/配置/日志链路审计报告（子任务）

**审计日期:** 2026-07-17  
**审计范围:** /home/pc/.openclaw/workspace/multifactor 的风险监控、数据管道、调度器、配置管理、日志与运维模块  
**审计重点:** 验证 AUDIT_REPORT_V2.md 中 High/Medium 项是否已修复，并发现新的设计/运行缺陷  
**方法:** 静态代码分析 + 模块级测试运行（65 passed）+ 量化交易最佳实践对比

---

## 执行摘要

本审计未重复 AUDIT_REPORT_V2.md 的 H1（config.json 凭证风险）和 H2（回测/实盘信号路径不一致），而是对 **风控、数据、调度、配置、日志、运维** 六个链路进行深度检查。

结论：
- **Critical:** 0 个（未发现立即导致资金损失或合规灾难的缺陷）
- **High:** 5 个（实盘前必须处理，涉及风控失效、数据 PIT 正确性、 emergency liquidation 失败、配置泄露风险）
- **Medium:** 12 个（影响稳定性、一致性和可维护性）
- **Low:** 10 个（改进项）

---

## 🔴 High 缺陷（实盘前必须处理）

### H1. `config.json` 仍被 Git 追踪，凭证泄露风险未消除

**文件/位置:** `config.json`, `.gitignore`, `config.example.json`  
**状态:** 验证为未修复（与 V2 H1 一致，但本次从 git 状态确认）

- `.gitignore` 中未包含 `config.json`，因此 `config.json` 已被 Git 追踪。
- `config.py` 中的 `V14StrategyConfig` 仍然允许 `alpaca_api_key` / `alpaca_api_secret` 从 `config.json` 读取（`field_validator` 只在值为空时回退环境变量）。
- 风险：用户可能直接将真实 Key/Secret 写入 `config.json` 并提交，导致历史泄露。

**修复建议:**
1. 立即在 `.gitignore` 中添加 `config.json`。
2. 从 Git 历史中移除已提交的 `config.json`（`git rm --cached config.json`）。
3. 在 `config.py` 中拒绝从 `config.json` 读取 `alpaca_api_key` / `alpaca_api_secret`，强制仅通过环境变量或运行时显式传入。
4. 添加 CI 检查（如 `git-secrets`）阻止包含 `PK`/`SK` 的提交。

---

### H2. RiskMonitor 的 `check_drawdown` / `check_daily_loss` 触发告警但不暂停交易

**文件/位置:** `risk_monitor.py:check_drawdown()`, `risk_monitor.py:check_daily_loss()`  
**影响:**
- `check_drawdown` 检测到回撤超过 `max_drawdown_limit` 时仅触发 `_trigger_alert('DRAWDOWN', ...)`，未设置 `self.trading_halted = True`。
- `check_daily_loss` 检测到日亏损超过 `daily_loss_limit` 时仅触发告警，未设置 `self.trading_halted = True`。
- 后果：最大回撤和日亏损限制仅用于记录，无法真正阻止交易。盘中监控或策略层可能继续提交新订单，扩大亏损。

**修复建议:**
1. 在 `check_drawdown` 和 `check_daily_loss` 触发阈值时，立即设置 `self.trading_halted = True`。
2. 区分临时暂停与永久暂停：日亏损可每日重置，累计回撤需人工确认或更严格的恢复条件。
3. 所有风险检查统一到一个入口 `check_all_risk()`，确保状态一致。

---

### H3. `risk_monitor.py` 的 `risk_level` 和 `trading_halted` 缺乏线程安全保护

**文件/位置:** `risk_monitor.py:RiskMonitor.__init__()`, `check_vix_level()`, `check_drawdown()`  
**影响:**
- `RiskMonitor` 的 `risk_level` 和 `trading_halted` 是普通的类属性，没有锁保护。
- `IntradayMonitor` 在子线程中通过 `self.trading_halted = value` 设置，同时写入 `self.risk_monitor.trading_halted = value`；策略主线程在 `live_trade()` 和 `run_live_rebalance()` 中读取 `risk_monitor.trading_halted`。
- 在 CPU 指令交错时，可能出现子线程已设置 `trading_halted=True`，但主线程读取到旧值 `False`，从而继续提交订单。

**修复建议:**
1. 为 `RiskMonitor` 添加 `threading.Lock()` 或 `threading.Event()`，封装 `trading_halted` 为 property。
2. 所有写入操作（VIX、回撤、日亏损、恢复）都通过锁保护。
3. 避免在 `IntradayMonitor` 和 `RiskMonitor` 之间维护两个 `trading_halted` 状态；统一由 `RiskMonitor` 拥有。

---

### H4. 紧急平仓（emergency liquidation）失败后无重试/无兜底，组合继续暴露风险

**文件/位置:** `intraday_monitor.py:_emergency_liquidation()`, `_liquidate_symbol()`  
**影响:**
- `_emergency_liquidation` 调用 `self.executor.liquidate_all()` 提交市价单后，仅记录日志，不等待成交确认、不检查是否成功。
- 如果网络中断、API 限流、订单被拒绝或市场突然关闭，平仓可能失败，但系统仍认为已触发保护并持续保持 `trading_halted=True`（不再交易，但也不尝试重新平仓）。
- 在大幅波动行情中，未成交的平仓意味着组合继续暴露，风险敞口等同于未触发保护。

**修复建议:**
1. `liquidate_all()` 返回后应轮询持仓，确认所有目标仓位已平。
2. 对失败的股票进入重试队列，使用限价单或智能订单路由（如收盘前用 MOC）。
3. 增加“保护失败”告警升级（短信/电话 webhook），人工介入。
4. 在 `trading_halted=True` 后，下一次监控循环仍检查持仓是否非空，非空则重新尝试平仓。

---

### H5. 数据管道缺乏 Point-in-Time（PIT）保证，回测与实盘可能使用不同调整后的价格

**文件/位置:** `data_source.py`, `quantconnect_data.py`, `polygon_data.py`, `strategies/v14.py:generate_signals()`  
**影响:**
- 多个数据源使用不同复权逻辑：Yahoo 默认返回调整后收盘价；QuantConnect 的 `_read_lean_data` 优先使用 `adjusted_close`（若存在），否则使用原始 `close`；Polygon 使用 `adjusted=true`。
- 缓存文件使用统一路径 `{CACHE_DIR}/{symbol}.parquet`，不同数据源可能互相覆盖同一缓存文件，但 metadata 不同，导致后续读取时不知道数据来源和调整方式。
- 实盘 `generate_signals(live_mode=True)` 重新下载 400 日数据，而回测使用切片 252 日；两者不仅长度不同，还可能因为缓存命中导致数据来源不同（例如 QC 回测命中缓存，实盘调用时缓存被 Polygon 覆盖）。
- 没有 PIT 检查：当前缓存中可能包含未来才发生的公司行为调整（如拆股、分红），实盘用这些价格计算信号会引入未来信息。

**修复建议:**
1. 缓存键按 `source+symbol+adjustment` 隔离，避免不同数据源互相覆盖。
2. 在 `generate_signals` 的 live 路径和回测路径中，强制使用同一数据源和同一复权方法。
3. 实盘信号生成只能使用前一日收盘（EOD）数据，不能用盘中实时价格；在 `generate_signals(live_mode=True)` 中增加断言或日志记录最新可用数据日期。
4. 对 `get_corporate_actions` 的拆股/分红/并购事件在信号生成前进行 PIT 校验和剔除退市股票。

---

## 🟠 Medium 缺陷（影响稳定性与一致性）

### M1. 多个模块中存在大量 `except Exception` 捕获，可能静默 KeyboardInterrupt / SystemExit

**文件/位置:** `intraday_monitor.py:_monitor_loop()`, `quantconnect_data.py`, `polygon_data.py`, `data_source.py`, `strategies/v14.py` 等
**影响:** 监控线程、数据获取、策略主循环中广泛使用 `except Exception as e`，会吞掉 `KeyboardInterrupt`、`SystemExit`、内存错误等不应被忽略的系统异常，导致程序无法通过 Ctrl+C 正常退出，或在 OOM 时继续运行。

**修复建议:**
- 仅捕获预期的业务异常（如 `ConnectionError`, `Timeout`, `APIError`, `ValueError`）。
- 顶层入口保留 `except Exception` 仅用于崩溃日志和优雅退出，其他地方不应使用裸 `except Exception`。

---

### M2. PDT 追踪使用 `date.today()` 基于本地机器时区，而非市场交易日边界（ET）

**文件/位置:** `pdt_tracker.py:_reset_if_new_day()`, `record_fill()`, `can_open_position()`  
**影响:**
- 美东时间下午 4:00 收盘后，若服务器在西部时区或 UTC，`date.today()` 可能早于美东收盘日期，导致跨日判断错误。
- 服务器时区漂移可能导致 day trade 计数跨日边界不准，进而错误阻止或允许交易。

**修复建议:**
- 统一使用美东时区（ET）的日期作为交易日边界：`datetime.now(ZoneInfo('America/New_York')).date()`。
- 所有 `date.today()` 调用替换为带时区版本的工具函数。

---

### M3. PDT 滚动计数使用 7 个自然日近似 5 个交易日，节假日期间不准确

**文件/位置:** `pdt_tracker.py:_rolling_count()`  
**影响:** 使用 `cutoff = today - timedelta(days=7)` 近似 5 个交易日。感恩节、圣诞、元旦等长假期间，7 个自然日可能只覆盖 3-4 个交易日，导致计数偏保守；也可能覆盖 6 个交易日而偏激进。与 Alpaca 的滚动 5 个交易日不一致。

**修复建议:**
- 使用 `exchange_calendars` 的 XNYS 日历计算真正的 5 个交易日前日期。
- 或直接读取 Alpaca 返回的 `daytrade_count` 作为权威值，本地计数仅用于预估。

---

### M4. `matching_engine.py` 默认禁用小数股，但代码中宣称 Alpaca 已支持

**文件/位置:** `matching_engine.py:ExecutionParameters.__init__()`, `config.py`  
**影响:**
- `ExecutionParameters` 默认 `use_fractional_shares=False`。
- `config.py` 的 `TradingConfig` 中没有 `use_fractional_shares` 字段，导致 `from_config()` 永远取默认值 False。
- 回测 `build_portfolio` 使用 `int(target_value / price)` 截断；live 的 `RebalanceManager._calculate_qty` 也使用 `int(Decimal)` 截断（虽然有 `_qty_residuals` 补偿，但只在 `alpaca_executor` 中）。
- 结果：组合资金利用率和回测/live 一致性仍受影响，无法充分利用 Alpaca 小数股能力。

**修复建议:**
- 在 `TradingConfig` 中增加 `use_fractional_shares: bool` 配置项。
- 回测引擎和 live 下单统一使用 `Decimal` 精度或启用小数股，确保资金利用率一致。

---

### M5. `alert_manager.py` 的文件写入无并发保护，可能损坏告警日志

**文件/位置:** `alert_manager.py:_write_alert()`  
**影响:**
- `_write_alert` 使用 `open(self.alert_file, 'a')` 直接追加 JSON 行。如果 `IntradayMonitor` 监控线程和主线程同时触发告警，文件写入可能交错，产生损坏的 JSON 行。
- 没有告警去重/节流，同一风险事件（如 VIX 高）每个检查周期都会写入一条记录，可能短时间内产生大量重复告警。

**修复建议:**
- 使用 `threading.Lock()` 保护文件写入。
- 增加告警去重（基于 type + symbol + 时间窗口），避免同一事件重复告警。
- 考虑使用结构化日志或数据库替代行追加 JSON 文件。

---

### M6. `backup_state.py` 会备份可能包含凭证的 `config.json`

**文件/位置:** `backup_state.py:PROTECTED_FILES`  
**影响:**
- 备份脚本将 `config.json` 列为受保护文件，但如果用户将真实 API Key 写入 `config.json`（参考 H1），备份目录也会包含凭证。
- 备份目录 `backups/` 默认权限为 700，但未阻止用户复制或泄露。

**修复建议:**
- 备份前对 `config.json` 进行清洗，确保其中不包含 `alpaca_api_key` / `alpaca_api_secret` 真实值；若包含，则使用 `config.example.json` 替换或提示用户。
- 对 `config.json` 备份文件也强制设置 600 权限并校验内容。

---

### M7. 数据源缓存键冲突导致回测/实盘数据不一致

**文件/位置:** `data_source.py`, `quantconnect_data.py`, `polygon_data.py`  
**影响:**
- 三个数据源都使用 `_get_cache_path(symbol)` 生成 `{CACHE_DIR}/{symbol}.parquet`，缓存文件会被不同数据源覆盖。
- 例如，回测使用 QuantConnect 缓存，实盘使用 Polygon 缓存，两者复权方法不同，但文件路径相同，导致实盘可能读取到回测的复权数据，或反之。

**修复建议:**
- 缓存文件名按 `source` 和 `adjustment` 隔离，例如 `{symbol}_{source}_{adjustment}.parquet`。
- 在缓存 metadata 中记录 source、adjustment、下载时间，读取时校验。

---

### M8. `intraday_monitor.py` 的 VIX 获取使用延迟/收盘数据，可能错过实时飙升

**文件/位置:** `intraday_monitor.py:_get_latest_vix()`  
**影响:**
- 优先使用 `polygon_data.HybridDataSource().get_vix()`，但 `PolygonDataSource.get_vix()` 调用 `get_vix_data(start, end)`，返回的是日线历史数据的最后一个收盘价，不是实时 VIX 指数。
- 回退到 `yfinance.Ticker('^VIX').history(period='5d')` 同样是历史收盘数据。
- 在盘中，VIX 可能已经飙升，但系统仍在使用 15 分钟前（甚至更久）的收盘价，延迟触发紧急平仓。

**修复建议:**
- 接入实时 VIX 数据源（如 Polygon 的 `quotes/latest` 或延迟指数行情），明确标注数据延迟。
- 如果只能获取延迟 VIX，应在配置中说明并降低监控灵敏度。

---

### M9. `IntradayMonitor` 和 `RiskMonitor` 维护两个 `trading_halted` 状态，存在多个真相源

**文件/位置:** `intraday_monitor.py:trading_halted` property, `risk_monitor.py:trading_halted`  
**影响:**
- `IntradayMonitor` 有自己的 `_halted` 和锁，同时通过 setter 写入 `risk_monitor.trading_halted`。
- `AlpacaExecutor` 自己也有 `trading_halted`，并在 `submit_order` 中检查 `self.trading_halted or self.risk_monitor.trading_halted`。
- 恢复交易时，`IntradayMonitor.resume_trading()` 只修改自己的 `_halted` 和 `risk_monitor.trading_halted`，但不修改 `AlpacaExecutor.trading_halted`（除非通过 `risk_monitor` 引用）。
- 存在状态不一致风险：某个组件被手动设置 `trading_halted=True` 后，其他组件不知道。

**修复建议:**
- 使用单一真相源（Single Source of Truth）：由 `RiskMonitor` 持有 `trading_halted` 和锁。
- `IntradayMonitor` 和 `AlpacaExecutor` 都通过 `risk_monitor` 的 property 读写状态，不维护本地副本。
- 紧急停止入口统一为 `risk_monitor.halt_trading(reason)` 和 `risk_monitor.resume_trading()`。

---

### M10. `scheduler.py` 的 `run_once` 硬编码使用 Paper Trading，不能用于实盘

**文件/位置:** `scheduler.py:run_once()`  
**影响:**
- `run_once()` 用于 cron 调用，但内部固定 `use_paper_trading=True`。
- 如果用户配置为 live 模式并希望通过 cron 运行，`run_once()` 无法满足需求。

**修复建议:**
- 让 `run_once` 读取环境变量或命令行参数（如 `USE_PAPER` / `LIVE_CONFIRMED`）来决定是否使用 paper。
- 或提供一个通用入口 `run_once(strategy)` 接受外部构造的策略实例。

---

### M11. 公司行为（分红/并购）获取后未实际应用于持仓或价格序列

**文件/位置:** `data_source.py:get_corporate_actions()`, `alpaca_executor.py:sync_corporate_actions()`  
**影响:**
- `data_source.py` 的 `get_corporate_actions` 返回分红、拆股、并购标记，但 `prepare_backtest_data` 和回测引擎中没有使用这些信息。
- `alpaca_executor.py` 的 `sync_corporate_actions` 只处理拆股（split），不处理分红和并购。
- 分红会导致价格跳空，若不调整持仓成本或历史价格，回撤和收益计算会出现偏差；并购退市股票若未从股票池移除，可能向 Alpaca 提交无效订单。

**修复建议:**
- 在回测中根据分红和拆股调整价格序列（PIT 调整）。
- 在实盘调仓前，检查目标股票是否即将退市或停牌，并从股票池中移除。
- 对并购事件发送告警并跳过相关标的。

---

### M12. `run_strategy.py` 默认行为仍是回测，CLI 参数设计容易造成误操作

**文件/位置:** `run_strategy.py:main()`  
**影响:**
- `if args.backtest or not args.live:` 表示不带任何参数时默认执行回测。
- 用户可能想运行 live 但忘记加 `--live`，结果只跑回测；或者想运行回测但误加 `--live`。
- 没有互斥检查：`--backtest` 和 `--live` 同时存在时，先回测再 live，可能导致意外。

**修复建议:**
- 无参数时打印帮助并退出，强制用户显式选择 `--backtest` 或 `--live`。
- `--live` 必须显式携带 `--paper`（当前已强制），但应进一步要求 `--live` 不能和 `--backtest` 同时出现，或给出明确警告。

---

## 🟡 Low 缺陷（改进项）

### L1. `json_logger.py` 的 `'json'` logger 可能未写入文件，只输出到控制台

**文件/位置:** `json_logger.py:_ensure_json_logger()`, `logging_config.py:_configure_json_logger()`  
**影响:**
- `_configure_json_logger` 只给 `'json'` logger 添加 `StreamHandler`，没有文件 Handler。
- 如果用户期望结构化事件被持久化到 `logs/multifactor.log`，实际上不会写入（因为 `propagate=False`）。

**修复建议:**
- 将 `'json'` logger 的 `propagate` 设为 True，让它共享根 logger 的文件 Handler；或专门给 `'json'` logger 添加一个按日期轮转的 JSON 文件 Handler。

---

### L2. `JSONFormatter` 使用当前 UTC 时间而非 `record.created`，时间戳可能不一致

**文件/位置:** `logging_config.py:JSONFormatter.format()`  
**影响:**
- `timestamp` 使用 `datetime.now(timezone.utc)`，而不是 LogRecord 的 `created` 字段。
- 在日志量很大时，格式化时间可能晚于实际记录时间，导致排序/审计出现微小偏差。

**修复建议:**
- 使用 `datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()`。

---

### L3. `risk_monitor.py` 的 `nav_history` 和 `alerts_history` 无限增长

**文件/位置:** `risk_monitor.py:__init__()`, `check_drawdown()`  
**影响:**
- 长期运行的调度进程中，`nav_history` 和 `alerts_history` 会持续增长，最终消耗大量内存。

**修复建议:**
- 对 `nav_history` 保留最近 N 条（如 1000 条或最近 90 天）。
- 对 `alerts_history` 保留最近 30 天或固定数量，超过部分写入持久化文件后从内存中移除。

---

### L4. `intraday_monitor.py` 的 `daemon=True` 默认行为可能导致紧急操作被中断

**文件/位置:** `intraday_monitor.py:start()`  
**影响:**
- 默认 `daemon=True` 意味着主线程退出时监控线程被强制终止，可能正在执行的紧急平仓或待处理平仓逻辑被中断。
- 已在 V2 M2 中提及，但当前代码默认仍未改变。

**修复建议:**
- 默认 `daemon=False`，并在 `run_strategy.py` 的 `finally` 中调用 `monitor.stop()` 和 `monitor.join()`。

---

### L5. 日志中仍有中文和 emoji，部分日志分析工具可能编码不一致

**文件/位置:** `scheduler.py`, `quantconnect_data.py`, `polygon_data.py` 等  
**影响:**
- 调度器、数据下载等模块使用中文日志和 emoji（如 `✅`, `📥`, `🕐`）。
- 虽然功能正常，但非 ASCII 字符在某些日志聚合系统（如 Splunk、ELK）中可能索引不一致。

**修复建议:**
- 用户可见/机器可解析的日志统一使用英文，中文保留在文档和注释中。

---

### L6. `backup_state.py` 的 `--encrypt` 是占位符，未实现真实加密

**文件/位置:** `backup_state.py:run_backup()`  
**影响:**
- 备份可能包含 `.env` 和 PDT 状态文件等敏感信息，但 `--encrypt` 仅打印提示，未进行加密。

**修复建议:**
- 使用 `gpg` 或 `age` 实现真实加密，或默认使用 `age` 加密备份。
- 在未实现加密前，在文档中明确标注备份未加密，并限制备份目录权限。

---

### L7. `config.py` 的 `get_config()` 不支持运行时重载

**文件/位置:** `config.py:get_config()`  
**影响:**
- 运行期间修改 `config.json` 不会生效，需要重启进程。

**修复建议:**
- 增加 `reload()` 方法，并提供基于文件修改时间戳的自动重载选项（可选，避免频繁读取）。

---

### L8. 调度器对 `daily` 频率触发时间的文档与实现不一致

**文件/位置:** `scheduler.py` 注释和 `should_rebalance()`  
**影响:**
- 注释说 daily 在“每个交易日收盘后 16:30 ET 执行”，但实现中 daily 和 weekly/monthly 统一在 10:00 ET 触发（`REBALANCE_OPEN_TIME = time(10, 0)`）。
- 文档误导用户，尤其对 EOD 数据策略预期在收盘后执行。

**修复建议:**
- 统一注释和实现；如果 daily 确实要在收盘后执行，单独处理 `REBALANCE_CLOSE_TIME` 逻辑。

---

### L9. 测试套件缺少对风控、调度、数据缓存的集成测试

**文件/位置:** `test_suite.py`  
**影响:**
- 65 个测试全部通过，但覆盖范围集中在因子、配置、订单、PDT；缺少对 `IntradayMonitor` 线程安全、`RiskMonitor` 暂停交易、`scheduler` 交易日历、`data cache` 隔离的测试。

**修复建议:**
- 增加 `TestRiskMonitor` 验证 `check_drawdown` 和 `check_daily_loss` 设置 `trading_halted`。
- 增加 `TestIntradayMonitor` 使用 mock executor 验证紧急平仓和恢复。
- 增加 `TestScheduler` 验证节假日和月末首个交易日。
- 增加 `TestDataCache` 验证不同数据源缓存隔离。

---

### L10. 没有运行时健康检查/心跳机制

**文件/位置:** 全局架构  
**影响:**
- 系统长期运行（如通过 `scheduler.py` 或 cron）时，没有外部健康检查或心跳来确认进程活着、监控线程未死、API 连接正常。
- 如果监控线程因异常退出（`daemon=True` 且主线程仍在运行），风险事件将无人处理。

**修复建议:**
- 增加 `healthcheck.py` 或 `heartbeat` 机制，定期写入心跳文件/日志，并可通过外部监控检查。
- 在监控线程异常退出时，主线程应检测并重启或告警。

---

## 上一轮（V2）缺陷修复状态验证

| V2 缺陷 | 状态 | 说明 |
|--------|------|------|
| H1 config.json 凭证风险 | ⚠️ 未完全修复 | config.json 仍被 Git 追踪，未加入 .gitignore |
| H2 回测/实盘信号路径不一致 | ⚠️ 部分修复 | 已共用 generate_signals，但数据缓存键冲突和 PIT 问题仍存在 |
| M1 订单回滚不完整 | ⚠️ 部分修复 | 补单/回滚框架存在，但回滚失败无升级告警，且不精确到目标权重差额 |
| M2 intraday_monitor daemon 默认 | ⚠️ 未修复 | 默认仍为 daemon=True |
| M3 废弃 alpaca-trade-api | 未在本范围 | 需单独检查 |
| M4 限价单动态偏移未用 ATR/Spread | 未修复 | 调用时 atr/spread 仍为 None |
| M5 公司行为仅拆股 | 未修复 | 分红/并购未处理 |
| M6 V14Strategy 初始化顺序 | 已修复 | 执行器创建后 set_risk_monitor 仍有空窗，但风险较低 |
| M7 缺少 Alpaca 执行链集成测试 | 未修复 | 测试未覆盖完整链路 |
| L1 中文/emoji 日志 | 未修复 | 多个模块仍使用 |
| L2 run_strategy 默认回测 | 未修复 | 无参数仍默认回测 |
| L3 backup_state 未备份 config.json | 已修复 | PROTECTED_FILES 包含 config.json |
| L4 ci.yml 定时回测 | 未在本范围 | 需检查 .github/workflows |
| L5 AlpacaExecutor 薄包装 | 已修复 | AlpacaPaperExecutor 已改名 AlpacaExecutor |
| L6 get_config 不支持重载 | 未修复 | 仍无 reload |

---

## 建议下一步（优先级）

1. **P0 - 安全止血：** 将 `config.json` 加入 `.gitignore` 并从 Git 历史清除（H1）。
2. **P0 - 风控真正生效：** 修复 `RiskMonitor` 的 `check_drawdown` 和 `check_daily_loss` 使其设置 `trading_halted=True`（H2）。
3. **P0 - 线程安全：** 为 `RiskMonitor` 的 `trading_halted` 添加锁，并统一各模块状态来源（H3、M9）。
4. **P1 - 紧急平仓兜底：** 为 `IntradayMonitor._emergency_liquidation` 增加成交确认、失败重试和升级告警（H4）。
5. **P1 - 数据 PIT 与缓存隔离：** 按数据源隔离缓存键，强制实盘/回测使用同一数据源和复权方法（H5、M7）。
6. **P1 - 测试补强：** 增加风控、调度、数据缓存的集成测试（L9）。
7. **P2 - 工程化清理：** 修复日志时区、告警并发写入、备份加密、默认 daemon 等 Low 项。

---

*审计人：风控/数据/调度子任务子代理*  
*方法：静态代码分析 + 测试运行 + 量化交易最佳实践对比*
