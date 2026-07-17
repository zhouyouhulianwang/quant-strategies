# 量化交易系统审计报告：框架、风控、数据与回测

**审计对象：** `/home/pc/.openclaw/workspace/multifactor`  
**审计时间：** 2026-07-17  
**审计性质：** 只读审计，不修改任何源文件  
**覆盖范围：** 框架设计、代码质量、数据一致性、风控逻辑、日志/告警、配置管理、运维能力、回测引擎

---

## 1. 执行摘要

本次审计从 8 个维度对 `multifactor` 量化交易系统进行了只读检查。系统已实现 Pydantic 配置验证、Alpaca 纸交易执行、基本风控与盘中监控、Parquet 缓存与备份加密等能力，但框架与风控层存在**可能直接造成亏损或异常交易**的 P0 级缺陷，数据层与回测层存在**模型偏差与一致性风险**的 P1 级缺陷。

| 等级 | 定义 | 数量 | 代表问题 |
|------|------|------|----------|
| **P0** | 可能立即造成亏损、资金风险或异常交易 | 9 | 交易自动恢复、初始化崩溃、配置与示例不一致、前向填充造成的前视偏差等 |
| **P1** | 显著风险或可靠性问题 | 18 | 数据源隔离不足、风控漏判/误判、日志重复、配置未自动重载、回测成本模型不一致等 |
| **P2** | 工程债务与可维护性问题 | 12 | 代码重复、模块耦合、文档不一致、缺少 Heartbeat 等 |

**总体建议：** 在投入实盘或扩大资金规模前，必须优先修复 P0 级缺陷；P1 级缺陷应在 1-2 个迭代周期内完成修复；P2 级缺陷纳入技术债持续消化。

---

## 2. 框架设计 / 生命周期

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| F-01 | `strategies/v14.py:__init__`（`else` 分支） | 当 `self.config is None` 时，`else` 分支仍访问 `self.config.trading.use_limit_orders` 等字段，会抛出 `AttributeError`，导致策略初始化直接崩溃。 | P0 | 在 `else` 分支中仅使用默认参数，避免访问 `self.config`；或将配置缺失作为硬错误提前返回。 |
| F-02 | `strategies/v14.py:__init__` | 数据、执行、风控、权重、配置等模块在 `__init__` 中一次性实例化，耦合度过高；任一模块失败（如风控初始化异常）会导致整个策略无法启动。 | P0 | 引入依赖注入与延迟初始化（lazy init），将各模块生命周期解耦；提供 `init_data()`、`init_executor()`、`init_risk()` 等独立方法。 |
| F-03 | `strategies/v14.py` + `risk_monitor.py` | `RiskMonitor.check_vix_level` 在 VIX < 25 时自动将 `trading_halted = False`，盘中监控也会调用同一方法，可能在市场波动后**自动恢复交易**，无需人工确认。 | P0 | 交易暂停后应进入“锁定”状态，必须显式调用 `resume_trading()` 并经过二次确认才能恢复；VIX 回落仅用于解除警报，不自动恢复交易。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| F-04 | `strategies/v14.py` 模块顶部 | 使用大量 `try/except ImportError` 容错导入，缺失核心模块时仅记录 warning，可能掩盖生产环境依赖缺失。 | P1 | 对数据、执行、风控等核心依赖使用强制导入；仅对可视化、告警等可选模块允许容错。 |
| F-05 | `strategies/base.py` | `BaseStrategy` 接口过于单薄，没有定义状态快照、事件总线、错误恢复、运行模式（paper/live/backtest）等通用契约。 | P1 | 扩展基类，增加 `on_start`、`on_stop`、`on_error`、`get_state`、`load_state` 等钩子；强制子类实现状态序列化。 |
| F-06 | `strategies/v14.py` | `backtest_result` 是单一可变属性，多次回测会被覆盖，且与 `get_backtest_result()` 形成隐式状态。 | P1 | 使用带时间戳/ID 的结果对象，或返回不可变结果；移除全局可变状态。 |
| F-07 | `main.py` | 模块加载时调用 `_load_universe_from_config()` 并修改全局 `TICKERS`、`INDUSTRY`、`NDX_SET`，产生导入副作用，单测难以隔离。 | P1 | 将股票池封装为配置对象，通过参数传递；避免在模块顶层修改全局变量。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| F-08 | `strategies/v14.py` 与 `main.py` | `generate_signals` 与 `run_v14` 中存在大量重复的信号生成与选股逻辑，维护成本高。 | P2 | 将选股逻辑抽出到独立模块，回测与实盘共用同一 `SignalGenerator`。 |
| F-09 | 多个模块 | 混合使用中文/英文注释与日志，国际化与可读性较差。 | P2 | 统一使用英文日志与注释；中文保留在文档或本地化文件中。 |

---

## 3. 数据一致性与 PIT（Point-in-Time）

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| D-01 | `data_source.py:_align_and_clean` / `quantconnect_data.py:_align_and_clean` / `polygon_data.py:get_prices` | 对缺失价格按标的进行 `ffill()` 前向填充。若股票长期停牌或已退市，后续日期会被填充为旧价格，导致**幸存者偏差与隐式前视**。 | P0 | 前向填充必须限制最大填充天数（如 5 个交易日），并对退市/停牌标的进行标记与剔除；引入 `valid_trading_mask`。 |
| D-02 | `quantconnect_data.py:prepare_backtest_data_qc` | 名义上以 QuantConnect 为主数据源，但首先调用 `data_source.filter_universe_for_corporate_actions`，后者依赖 **Yahoo Finance** 的 1 个月历史数据判断退市，跨源一致性差。 | P0 | 让主数据源自身提供退市/公司行为信息；Yahoo 仅作为 fallback；建立统一的公司行为事件表。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| D-03 | `data_source.py` / `quantconnect_data.py` / `polygon_data.py` | 三个数据源模块都定义了各自的 `_get_cache_path`、`_is_cache_valid`、`_load_cache`、`_save_cache` 等缓存函数，共享同一 `data_cache` 目录，但没有全局缓存锁或注册表。 | P1 | 将缓存基础设施集中到 `cache.py`，各数据源仅提供 source/endpoint 适配；增加文件锁或按进程缓存目录避免并发写冲突。 |
| D-04 | 多个数据源 | 所有缓存统一使用 7 天 TTL。对于盘中/日频数据，7 天缓存会导致使用 stale 数据；对于长期历史数据，7 天又过短。 | P1 | 按数据类型设置 TTL（盘中 1 天、日终 1 天、历史 EOD 7 天）；提供强制刷新参数。 |
| D-05 | `main.py:compute_factors_v14` | `relative_value` 与 `garp` 因子使用 `(1 + ret.mean())^252 - 1` 作为“收益率代理”，再取倒数作为 PE 代理。该指标本质是价格动量，并非真实盈利收益率，模型存在**误设风险**。 | P1 | 引入真实基本面数据（如季度 EPS、Book Value）或明确将该因子重命名为“价格收益动量”；若使用价格代理，需在文档中充分披露。 |
| D-06 | `data_source.py:get_corporate_actions` | 注释说明会获取“并购”标志，但实现中 `merger` 始终为 0，未从 `ticker.info` 真正读取。 | P1 | 实现并购/退市事件的真正检测，或移除该字段并改用更可靠的数据源。 |
| D-07 | `main.py:compute_factors_v14` | `momentum_consistency` 被定义为过去 20 日正收益比例，与“动量一致性”名称不符，且未对行业或波动率中性化。 | P1 | 重命名或改用波动率调整后收益序列的一致性度量。 |
| D-08 | `quantconnect_data.py` / `polygon_data.py` | VIX 使用 `unadjusted` 标志，但股票价格使用 `adjusted`，两者混用可能在复权对齐时产生偏差。 | P1 | VIX 作为指数无需复权，但需在元数据中显式标记；建立统一的 adjustment 规范。 |
| D-09 | `quantconnect_data.py:HybridQCDataSource.get_prices` | 缓存命中时直接按日期切片，但未验证切片是否包含请求区间的全部日期，可能返回不完整数据。 | P1 | 在缓存命中后检查请求区间是否被完整覆盖，否则触发增量更新。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| D-10 | `data_source.py` / `quantconnect_data.py` / `polygon_data.py` | `_normalize_index`、`_compute_rsi_wilder`、`_yahoo_end_inclusive` 等函数在三个文件中重复定义。 | P2 | 抽取到公共工具模块 `data_utils.py` 或 `cache.py` 的子模块。 |
| D-11 | `data_source.py` | `_verify_cache_metadata` 仅在元数据不匹配时记录 warning，不会使缓存失效。 | P2 | 当 source/adjustment 不匹配时，应视为缓存失效并重新下载。 |

---

## 4. 风控逻辑

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| R-01 | `risk_monitor.py:check_vix_level` | VIX 从高位回落到 < 25 时，自动将 `trading_halted = False`。若系统因其他原因（日亏损、回撤）已暂停，此行为可能覆盖其他风控状态。 | P0 | 将 VIX 恢复与交易暂停解耦；交易恢复必须显式确认并检查所有风险维度。 |
| R-02 | `intraday_monitor.py:auto_resume_if_safe` / `check_recovery` | 盘中监控提供自动恢复交易逻辑，可能在紧急平仓后尚未人工确认时重新开仓。 | P0 | 删除自动恢复逻辑；恢复交易需人工或显式自动化审批流程。 |
| R-03 | `intraday_monitor.py:_emergency_liquidation` / `_liquidate_symbol` | `_pending_liquidation_reason` 是单一字符串，新的强平事件会覆盖旧原因，且失败重试时可能丢失中间状态。 | P0 | 使用待处理强平队列（FIFO），记录每个触发原因、时间、重试次数；持久化到磁盘防止进程重启丢失。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| R-04 | `risk_monitor.py` | 交易暂停后没有“锁定/冷却”机制，VIX 在阈值附近波动时可能反复暂停与恢复。 | P1 | 增加暂停锁（latch）与最小暂停时长（如 1 个交易日或 4 小时），并记录人工恢复审计日志。 |
| R-05 | `risk_monitor.py` | `nav_history`、`alerts_history` 在内存中截断到 1000 条，但无持久化；进程重启后历史丢失。 | P1 | 将 NAV 历史与告警历史写入时序数据库或本地持久化文件，便于回撤复核。 |
| R-06 | `risk_monitor.py:check_position_limits` | 行业集中度检查使用 `main.INDUSTRY`，但 `INDUSTRY` 可能已被配置覆盖，存在版本不一致风险。 | P1 | 风控模块应显式接收 industry_map 参数，而非依赖全局变量。 |
| R-07 | `intraday_monitor.py:_check_intraday_drawdown` | `daily_high_nav` 在子类 `V14IntradayMonitor` 中额外维护，但 `IntradayMonitor` 本身也有 `daily_high_nav`，存在重复与潜在不一致。 | P1 | 统一日内高点与累计高点的维护逻辑，避免子类与父类状态分叉。 |
| R-08 | `risk_monitor.py` | `check_concentration_risk` 仅触发告警，不会暂停交易。 | P1 | 将集中度超限与仓位限制纳入同一决策链，达到阈值时也应暂停或限制新增买入。 |
| R-09 | `intraday_monitor.py:_check_single_stocks` | 单只股票跌幅基于 `avg_entry_price` 与 `current_price`，未考虑分红除权，可能在分红后误触发。 | P1 | 使用复权后的成本价或引入除权调整。 |
| R-10 | `strategies/v14.py` | `live_trade` 中 `daily_return` 计算使用 `_last_live_portfolio_value`，但该值只在调仓时更新，**无法反映日内真实回撤**。 | P1 | 将日内监控的 daily_high_nav 与 portfolio_value 实时同步到策略层，或统一由 RiskMonitor 维护。 |
| R-11 | `risk_monitor.py` | 配置中的 `max_intraday_dd` 被映射到 `daily_loss_limit`，但 `max_drawdown_limit`（累计回撤）在 RiskMonitor 中默认硬编码为 0.15，未从配置读取。 | P1 | 在 `V14Strategy.__init__` 中显式将 `config.risk.max_intraday_dd` 同时映射到 `daily_loss_limit` 与 `max_drawdown_limit`，或增加独立配置项。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| R-12 | `risk_monitor.py:check_concentration_risk` | HHI 阈值 0.15 为硬编码，未说明依据。 | P2 | 将阈值参数化并纳入配置验证。 |
| R-13 | `intraday_monitor.py` | 监控线程默认以 `daemon=True` 运行，主进程异常退出时可能无法完成紧急平仓或告警。 | P2 | 在独立进程/服务模式下使用 `daemon=False`，并注册优雅退出钩子。 |

---

## 5. 日志 / 告警

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| L-01 | `logging_config.py` + 多数模块 | `setup_logging()` 在 `logging_config.py`、`v14.py`、`main.py`、`data_source.py` 等 10+ 模块的导入期被调用，导致根 logger 与 `json` logger 重复添加 Handler，日志重复输出。 | P0 | 禁止在模块导入时调用 `setup_logging()`；仅在入口文件（`run_strategy.py`、`main.py`）显式调用一次；使用 `logging.getLogger` 延迟获取 logger。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| L-02 | `json_logger.py:StructuredLogger.__init__` | 每次实例化都 `handlers.clear()` 并重新添加 Handler，与 `logging_config._configure_json_logger` 冲突。 | P1 | 移除 `StructuredLogger` 中的 Handler 清除逻辑；统一由 `logging_config` 配置。 |
| L-03 | `logging_config.py` | 文件 Handler 创建在默认 `logs/` 目录，未设置文件权限（默认 644），运行日志可能包含持仓与账户信息。 | P1 | 创建日志文件时设置 `chmod 600`；或将敏感日志写入 `multifactor.json.log` 并同样限制权限。 |
| L-04 | `logging_config.py:JSONFormatter.format` | `extra` 字段可以覆盖 `level`、`logger` 等标准键，可能被误用。 | P1 | 在 JSONFormatter 中显式保留标准键，extra 字段仅作为 `context` 子对象合并。 |
| L-05 | `alert_manager.py` | 告警去重窗口固定 60 秒，且仅基于 `category:message` 去重；不同类型风控事件可能共用相同 key。 | P1 | 去重 key 增加触发值、账户状态等维度；提供可配置去重窗口。 |
| L-06 | `risk_monitor.py:_trigger_alert` | 告警写入 `alerts/alerts_YYYYMMDD.json` 时无文件锁，多线程/进程可能损坏文件。 | P1 | 使用 `threading.Lock` 或追加到按 PID 分片的文件，避免并发写入冲突。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| L-07 | 全链路 | 缺少统一的 correlation/request ID，跨模块日志难以串联。 | P2 | 在关键事件（调仓、风控触发、订单）中注入 `run_id` 或 `session_id`。 |
| L-08 | `alert_manager.py` | 仅支持文件日志与控制台，未实现邮件/Slack/Telegram webhook。 | P2 | 提供 webhook 插件接口或至少预留可配置通道。 |

---

## 6. 配置管理

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| C-01 | `config.json` vs `config.example.json` | `rebalance_frequency` 在 `config.json` 中为 `daily`，在 `config.example.json` 中为 `monthly`，与 `config.py` 注释和 `main.py` 默认行为不一致。实际部署可能误用 `daily` 导致高频交易与成本激增。 | P0 | 统一为 `monthly`（策略文档明确为月度调仓），并增加运行时对频率变更的显式确认。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| C-02 | `config.py:V14StrategyConfig` | `alpaca_api_key` 与 `alpaca_api_secret` 虽可通过环境变量注入，但模型仍允许从 `config.json` 读取，且没有运行时报错或掩码处理。 | P1 | 禁止从 `config.json` 读取真实凭证；构造时若检测到非空凭证，记录警告并强制使用环境变量。 |
| C-03 | `config.py:get_config` | 全局单例缓存配置；`config.json` 修改后不会自动生效，V14Strategy 等模块也不调用 `reload_config()`。 | P1 | 增加文件监听（`watchdog` 或启动时校验 hash），或要求每次调仓前显式 `reload_config()`。 |
| C-04 | `config.py` | `local.json` 在 `config.json` 注释中被提及，但 `config.py` 未加载该文件。 | P1 | 在 `get_config()` 中合并 `local.json`（优先级高于 `config.json`），或删除注释引用。 |
| C-05 | `config.py:RiskConfig.vix_must_be_reasonable` | 字段声明 `ge=10.0`，但自定义校验器要求 `>= 20`。若环境变量设置 15 会冲突。 | P1 | 统一阈值逻辑，移除重复或矛盾的校验。 |
| C-06 | `config.json` | 缺少 `max_drawdown_limit` 配置项，`RiskMonitor` 的累计回撤阈值被硬编码为 0.15。 | P1 | 在 `RiskConfig` 中增加 `max_drawdown_limit` 并通过环境变量/配置可覆盖。 |
| C-07 | `config.py` | 配置验证失败时（如 `config.json` 损坏）使用默认配置并打印到 stdout，可能掩盖错误配置。 | P1 | 区分“使用默认配置”与“启动失败”；生产环境应明确失败。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| C-08 | `config.py` | 环境变量覆盖逻辑在多个 `field_validator` 中重复，可集中到一个后置校验器。 | P2 | 使用 `model_validator` 统一处理环境变量覆盖。 |

---

## 7. 运维能力

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| O-01 | 项目根目录 | `HEARTBEAT.md` 不存在，系统缺少日常巡检清单与自检入口。 | P0 | 创建 `HEARTBEAT.md`，包含数据 freshness、风控状态、持仓对账、备份状态等检查项。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| O-02 | `scheduler.py` | 依赖 `exchange_calendars` 识别美股节假日；未安装时回退到仅跳过周末，会误在节假日调仓。 | P1 | 将 `exchange_calendars` 设为生产依赖；未安装时启动失败或明确告警。 |
| O-03 | `scheduler.py` | `.last_rebalance.json` 保存在项目根目录，无权限保护，且多实例部署时可能出现竞争。 | P1 | 将 last_run 文件写入受保护目录（如 `data/` 并 `chmod 600`），或迁移到数据库/redis。 |
| O-04 | `backup_state.py` | 备份脚本为手动工具，无 cron/systemd 定时调度，也无运行后校验。 | P1 | 提供 `systemd` timer 或 cron 示例；备份完成后校验文件哈希并记录。 |
| O-05 | `backup_state.py` | 默认不加密；若用户忘记 `--encrypt`，`.env` 与 `config.json` 以明文保存在备份中。 | P1 | 默认启用加密，或在没有加密时拒绝备份包含 secrets 的文件。 |
| O-06 | `alpaca_executor.py` | 初始化时读取 `.env` 并将所有键值注入 `os.environ`（含非 ALPACA 变量），可能泄露或覆盖已有环境变量。 | P1 | 仅读取必要配置项；使用 `python-dotenv` 的 `load_dotenv(override=False)` 替代手动解析。 |
| O-07 | `run_strategy.py` | 启动时调用 `cleanup_runtime_files()` 清理 30 天前的订单/告警/图表，但缺少“归档后删除”的确认与审计。 | P1 | 清理前先归档到受保护目录，并记录清理摘要。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| O-08 | `runtime_cleanup.py` | `_is_currently_in_use` 使用 1 小时修改时间作为启发式，可能误删正在写入的日志。 | P2 | 使用文件句柄检测（`lsof`/`fuser`）或按日志轮转规则识别活跃文件。 |
| O-09 | `backup_state.py` | 备份文件权限使用 `chmod 600/700`，但 `backup_root` 目录本身权限未强制设置。 | P2 | 在创建备份根目录时同步设置 `700` 权限。 |

---

## 8. 回测引擎

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| B-01 | `strategies/v14.py:run_backtest` | 先调用 `_run_backtest_unified`（无成本），再调用 `apply_costs_to_backtest`（基于换手率估算成本）；而 `main.py:run_v14` 使用真实成交与 `TradingCostModel` 计算成本。两套引擎成本模型不一致，可能导致回测与实盘绩效差异。 | P0 | 统一回测引擎：全部使用 `main.py:run_v14` 的真实成交/现金/持仓模拟，并在 `V14Strategy` 中透传；移除 `apply_costs_to_backtest` 的二次估算。 |
| B-02 | `strategies/v14.py:_run_backtest_unified` vs `main.py:run_v14` | 调仓日期生成逻辑不同：V14Strategy 使用 `price_df.groupby(...).tail(1)`，main.py 使用 `exchange_calendars` 获取月末最后交易日。两者可能产生不同的调仓日。 | P0 | 统一使用 `scheduler.py` 或 `main.py` 的交易日历逻辑，确保回测与实盘调仓日一致。 |
| B-03 | `strategies/v14.py:_run_backtest_unified` | 初始信号在 `first_d` 生成，在 `first_exec_d` 执行，但 `first_exec_d` 可能等于 `first_d`（如果当天就是最后一天），此时仍使用当天收盘价执行，存在前视风险。 | P0 | 强制初始信号也延后到下一个交易日执行；或确保 `first_exec_d > first_d`。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| B-04 | `main.py:compute_factors_v14` | `relative_value` 与 `garp` 因子使用价格收益代理，不是真实基本面估值，可能产生与真实 GARP/价值因子不同的选股结果。 | P1 | 接入真实基本面数据（如 Alpaca/QuantConnect fundamentals）或重命名并注明为“价格收益代理”。 |
| B-05 | `cost_model.py:apply_costs_to_backtest` | 默认 `cost_per_turnover=0.002`（20 bps）对于月度调仓、多股票、市价单策略可能过于乐观。 | P1 | 进行参数敏感性分析；默认使用与 live 执行一致的成本参数（ Alpaca 佣金 + 滑点 + spread）。 |
| B-06 | `strategies/v14.py:_run_backtest_unified` | 使用 `price_df.index[252]` 作为预热截止日，但未校验实际交易日数量是否足够。 | P1 | 检查 `len(price_df) >= 252` 并确保为实际交易日而非日历日。 |
| B-07 | `main.py:run_v14` | `integrate_with_backtest` 在 `execution_date` 无价格时回退到之后第一个交易日，但成本估算仍使用 `next_d` 的价格，可能与实际执行日不一致。 | P1 | 统一使用执行日价格，若执行日无价格则跳过该次调仓并记录。 |
| B-08 | `main.py:run_v14` | `cost_model.estimate_portfolio_cost` 被调用两次（扣除成本前、后），若第二次计算成本过高，仍可能出现现金为负。 | P1 | 使用单次成本估算并预留现金缓冲；或在模拟成交后重新计算现金。 |
| B-09 | `main.py` 与 `strategies/v14.py` | 信号生成与选股逻辑在 `main.py` 和 `v14.py` 中重复，未来修改因子时容易遗漏。 | P1 | 将 `compute_factors_v14`、`v14_composite_score`、`v14_scale` 等核心逻辑移到 `strategies/v14_engine.py`，两处复用。 |
| B-10 | `main.py:run_v14` | `turnover` 计算在 `cost_model.apply_costs_to_backtest` 中基于权重变化，而 `main.py` 真实成交会产生实际换手率，两者可能不一致。 | P1 | 回测记录实际成交明细，按实际成交额计算成本，而非估算 turnover。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| B-11 | `main.py:run_v14` | 绩效计算（CAGR、Sharpe、MaxDD）在 `__main__` 和 `_print_performance` 中重复。 | P2 | 抽取到 `metrics.py` 模块。 |
| B-12 | `main.py` | 模拟数据生成与回测逻辑耦合，单测困难。 | P2 | 将模拟数据生成器独立为 `mock_data.py`。 |

---

## 9. 代码质量与执行安全

### P0

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| Q-01 | `strategies/v14.py:__init__`（重复） | 同 F-01：`else` 分支访问 `None` 配置导致崩溃。 | P0 | 同 F-01。 |

### P1

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| Q-02 | `alpaca_executor.py` | 在 `__init__` 中读取 `.env` 并注入环境变量，若 `.env` 包含 secrets，可能通过子进程或错误日志泄露。 | P1 | 使用 `dotenv_values` 读取但不注入环境变量；或禁止 `.env` 中存放真实凭证。 |
| Q-03 | `order_manager.py` | `_get_order_status` 直接访问 `self.executor.api`，如果 `trading_client` 被 `RateLimitedAPI` 包装，可能产生不一致。 | P1 | 统一通过 `executor.get_order_by_id` 方法访问，避免绕过包装器。 |
| Q-04 | `alpaca_executor.py` | `_confirm_live_mode` 依赖交互式输入，自动化部署时会被拒绝，但可通过 `ALPACA_LIVE_CONFIRMED=1` 绕过，存在误操作风险。 | P1 | 在 live 模式下要求写入“启动令牌”文件或双重环境变量确认，而非单一变量。 |
| Q-05 | `alpaca_executor.py` | ` AlpacaExecutor.rebalance_portfolio` 文件被截断（读取显示不完整），无法审计完整回滚与流动性检查逻辑。 | P1 | 检查文件完整性；补全被截断的代码并增加单测。 |

### P2

| # | 位置 | 具体问题 | 风险等级 | 修复建议 |
|---|------|----------|----------|----------|
| Q-06 | 多个模块 | 大量 `try/except ImportError` 与条件导入使代码分支复杂。 | P2 | 明确依赖边界，使用依赖注入替代动态导入。 |
| Q-07 | 多个模块 | 混合使用 print 与 logger，部分错误处理仍使用 print。 | P2 | 统一使用 logger；print 仅用于 CLI 入口。 |

---

## 10. 修复优先级列表

按“风险 × 修复成本”排序，建议按以下顺序处理：

### 立即修复（P0，阻塞实盘）

1. **F-01 / Q-01**: 修复 `V14Strategy.__init__` 中 `else` 分支访问 `None` 配置导致崩溃的 bug。
2. **C-01**: 统一 `config.json` 与 `config.example.json` 的 `rebalance_frequency`，明确为 `monthly`。
3. **R-01 / R-02**: 移除 VIX 回落与盘中监控的自动恢复交易逻辑；交易恢复必须显式确认。
4. **R-03**: 将 `_pending_liquidation_reason` 改为持久化队列，防止原因丢失与进程重启丢失。
5. **B-01 / B-02**: 统一回测引擎与实盘调仓逻辑，使用单一 `run_v14` 引擎。
6. **D-01 / D-02**: 限制前向填充天数，并建立统一的公司行为/退市事件处理。
7. **L-01**: 移除模块导入期的 `setup_logging()` 调用，统一在入口文件配置日志。
8. **O-01**: 创建 `HEARTBEAT.md` 日常巡检清单。
9. **B-03**: 确保初始信号也延后到下一交易日执行。

### 高优先级（P1，1-2 周内）

10. **D-03 / D-04**: 统一缓存基础设施并设置差异化 TTL。
11. **D-05 / B-04**: 修正 `relative_value` / `garp` 因子模型，或明确披露其价格代理本质。
12. **R-04**: 增加交易暂停锁与最小暂停时长。
13. **R-05**: 持久化 NAV 与风控告警历史。
14. **R-06**: 风控模块显式接收 industry_map，避免依赖全局变量。
15. **R-11 / C-06**: 将累计回撤阈值纳入配置。
16. **L-02 / L-03 / L-04**: 修复 json_logger 与 logging_config 的 Handler 冲突，设置日志文件权限。
17. **C-02 / C-03**: 禁止 config.json 存储凭证，并实现配置热重载或启动校验。
18. **O-02 / O-03**: 将 `exchange_calendars` 设为强依赖，并保护 `.last_rebalance.json`。
19. **O-05**: 默认加密备份或拒绝明文备份 secrets。
20. **O-06**: 改用 `dotenv_values` 读取 `.env` 而不注入环境变量。
21. **B-05 / B-10**: 使用实际成交明细与 live 一致的成本参数进行回测。
22. **Q-02 / Q-04**: 加强 live 模式确认与 secrets 管理。
23. **B-09**: 抽取公共信号引擎，避免回测与实盘代码重复。
24. **Q-05**: 检查并修复 `alpaca_executor.py` 被截断的代码。

### 中优先级（P2，持续消化）

25. **F-08 / B-12**: 重构公共信号生成与模拟数据模块。
26. **D-10 / D-11**: 抽取公共数据工具函数，统一缓存失效策略。
27. **F-09 / Q-07**: 统一日志与注释语言，移除 print。
28. **L-07 / L-08**: 增加 correlation ID 与 webhook 告警通道。
29. **C-04 / C-08**: 加载 `local.json` 并简化环境变量覆盖逻辑。
30. **O-08 / O-09**: 改进运行时清理启发式与备份目录权限。
31. **R-12 / R-13**: 参数化集中度阈值并优化监控线程生命周期。
32. **B-11**: 抽取绩效指标模块。
33. **Q-06**: 简化条件导入，使用依赖注入。

---

## 11. 结论

`multifactor` 项目已具备从回测到纸交易的基本闭环能力，但在**交易自动恢复、初始化健壮性、配置一致性、数据前向填充、回测与实盘引擎统一**等方面存在可直接导致资金风险或绩效失真的 P0/P1 问题。建议在修复 P0 级缺陷前，限制实盘资金规模，仅用于纸交易验证；修复完成后，通过至少一次完整的 mock 端到端测试与历史回测交叉验证，再逐步升级。

---

*报告生成完毕：/home/pc/.openclaw/workspace/multifactor/AUDIT_REPORT_FRAMEWORK_RISK_DATA.md*
