# MultiFactor V14 全面审计报告 V2

**审计日期:** 2026-07-17  
**审计范围:** /home/pc/.openclaw/workspace/multifactor  
**审计重点:** Alpaca 模拟/实盘执行链路缺陷  
**审计维度:** 框架架构、代码质量、逻辑正确性、风控、日志、配置管理、安全合规、运维就绪性

---

## 执行摘要

本次审计基于当前最新代码（已包含上一轮 Critical/High 修复：整数截断、spread、风控同步、PDT 同步、结构化日志、缓存统一、公司行为、熔断恢复、配置化股票池、config.json 纳入版本控制等）。

结论：未发现新的 **Critical** 缺陷；存在 **2 个 High** 缺陷和若干 **Medium/Low** 改进项。上一轮审计中的 Critical/High 问题已基本修复，当前系统处于“可进入 Alpaca Paper 测试，但上线前需处理 High 项”的状态。

---

## 🔴 High 缺陷（实盘前必须处理）

### H1. `config.json` 纳入版本控制后存在凭证泄露风险

**文件/位置:** `config.json`, `config.py`, `.gitignore`  
**影响:**
- `config.json` 现在被 Git 追踪，其中 `alpaca_api_key` / `alpaca_api_secret` 字段是必填的（`config.py` 校验非空）。
- 虽然当前文件内是空字符串，但用户后续可能直接在 `config.json` 里填入真实 Key 并提交，导致历史泄露。
- 已提交的 `config.json` 包含环境相关设置（如 `rebalance_frequency: daily`），不同环境需要不同值时容易冲突。

**修复建议:**
1. 将 API Key/Secret 从 `config.json` 的必填校验中移除，改为仅通过环境变量注入。
2. 在 `.gitignore` 中保留 `config.json`，提供 `config.example.json` 作为模板（已实现但需恢复忽略）。
3. 若用户坚持追踪 `config.json`，则增加 CI 检查（如 `git-secrets`）阻止任何包含 `PK`/`SK` 的提交。

---

### H2. 回测与实盘信号生成对 `generate_signals` 的使用仍不一致

**文件/位置:** `strategies/v14.py:generate_signals()`, `strategies/v14.py:run_live_rebalance()`  
**影响:**
- 回测：`generate_signals(price_df, vix)` 使用 252 日历史收盘价切片。
- 实盘：`run_live_rebalance()` 调用 `generate_signals(live_mode=True)` 但不传 `price_df`，内部会重新下载 400 日数据，可能失败或延迟。
- 实盘路径与回测路径的数据来源、切片长度、错误处理均不同，存在信号不一致风险。

**修复建议:**
1. 在 `run_live_rebalance` 中显式构造与回测相同的 `price_df`（长度、来源一致）后再调用 `generate_signals`。
2. 增加 PIT（Point-in-Time）数据校验：实盘信号只能使用已收盘数据，不能使用盘中实时价格影响选股。
3. 对回测和实盘共用同一个 `SignalGenerator` 类，并记录版本号。

---

## 🟠 Medium 缺陷（建议修复）

### M1. 订单管理对部分成交和超时的回滚不完整

**文件/位置:** `order_manager.py:RebalanceManager.rebalance()`  
**影响:**
- 部分成交时优先“补单”而非回滚，但补单逻辑未完整实现，超时时只是撤销订单。
- 买入失败后尝试卖出已买入仓位来回滚，但卖出也可能失败，导致组合偏离目标。
- 没有记录每个调仓会话的“目标状态”，无法精确回滚到原始组合。

**修复建议:**
1. 使用 `start_rebalance_session()` 生成会话 ID，并记录调仓前持仓快照。
2. 买入阶段失败时，按目标权重与实际成交权重的差额进行反向交易，而不是全部卖出。
3. 对回滚失败发送 Critical 告警并暂停后续交易。

---

### M2. `intraday_monitor` 默认 daemon 线程可能在实盘过程中退出

**文件/位置:** `intraday_monitor.py:start(daemon=True)`  
**影响:**
- daemon 线程在主线程结束时会被强制终止，可能导致收盘前未完成的紧急平仓逻辑被中断。
- 虽然非 daemon 是可选参数，但默认行为不安全。

**修复建议:**
1. 默认 `daemon=False`，并提供明确的 `stop()` / `join()` 调用。
2. 在 `run_strategy.py` 的 `finally` 块中确保监控线程正常退出。

---

### M3. `alpaca_data_download.py` 仍使用废弃的 `alpaca-trade-api` SDK

**文件/位置:** `alpaca_data_download.py`  
**影响:**
- 该脚本使用 `alpaca_trade_api.REST`，而项目主体使用新版 `alpaca-py`，两套 SDK 并存增加维护成本和依赖冲突风险。
- `alpaca-trade-api` 已停止维护，未来可能无法工作。

**修复建议:**
1. 将下载脚本迁移到 `alpaca-py` 的 `StockHistoricalDataClient`。
2. 统一使用 `data_source.py` 或 `cache.py` 中的数据获取接口。

---

### M4. 限价单动态偏移未实际使用 ATR / Spread

**文件/位置:** `alpaca_executor.py:get_dynamic_limit_offset()`, `alpaca_executor.py:_build_order_request()`  
**影响:**
- 函数签名支持 ATR 和 spread，但实际调用时两者均为 `None`，偏移始终退化为默认 `0.1%`。
- 对高价股（如 AVGO）和低价股使用相同偏移比例，可能无法成交或产生不必要滑点。

**修复建议:**
1. 在构建限价单时从数据源获取当前 ATR 和 quote spread，并传入 `get_dynamic_limit_offset`。
2. 在 `matching_engine.py` 的 `ExecutionParameters` 中加入默认 ATR/Spread 获取策略。

---

### M5. 公司行为处理仅覆盖拆股，未处理分红/并购

**文件/位置:** `alpaca_executor.py:sync_corporate_actions()`, `data_source.py:get_corporate_actions()`  
**影响:**
- 分红会导致价格跳空，但本地持仓和市场价值未调整，可能触发错误的风控或回撤计算。
- 并购退市股票若未及时处理，可能向 Alpaca 提交无法成交的订单。

**修复建议:**
1. 扩展 `get_corporate_actions` 返回分红和并购事件。
2. 在调仓前检查目标股票是否即将退市或停牌，并从股票池中移除。

---

### M6. `V14Strategy` 初始化顺序存在风险：风控器晚于执行器创建

**文件/位置:** `strategies/v14.py:__init__()`  
**影响:**
- 当前顺序：先创建 `AlpacaExecutor`，再创建 `RiskMonitor`，最后将风控器设置给执行器。
- 执行器在创建后到设置风控器之间的短暂窗口内，如果发生 API 调用，不会检查 `risk_monitor.trading_halted`。

**修复建议:**
1. 先创建 `RiskMonitor`，再创建 `AlpacaExecutor` 并立即调用 `set_risk_monitor`。
2. 或让 `AlpacaExecutor` 接受 `risk_monitor` 构造函数参数，避免空窗期。

---

### M7. 测试覆盖仍不足，缺少 Alpaca 执行链的集成测试

**文件/位置:** `test_suite.py`  
**影响:**
- 当前 65 个测试主要覆盖因子、配置、风控、PDT、订单管理，但没有针对 Alpaca 真实执行链的 mock 集成测试。
- 无法验证 `submit_order → get_order_status → record_fill → PDT update` 的完整链路。

**修复建议:**
1. 使用 `_FakeAlpacaClient` 编写端到端测试：下单、部分成交、超时、取消、回滚。
2. 增加测试验证 `trading_halted` 时拒绝订单。

---

## 🟡 Low 缺陷（改进项）

### L1. 日志中仍有中文/emoji 残留（非日志文本）

**文件/位置:** `scheduler.py`, `intraday_monitor.py` 注释及旧日志模板  
**影响:** 不影响功能，但结构化日志系统中混有中文字符，部分日志分析工具可能编码不一致。

**修复建议:** 将用户可见日志统一为英文，中文保留在注释和文档中。

---

### L2. `run_strategy.py` 的 `args.backtest or not args.live` 逻辑导致 `--live` 未指定时也会回测

**文件/位置:** `run_strategy.py:main`  
**影响:** 默认行为是回测，对未带参数的用户可能造成困惑；但这不是安全缺陷。

**修复建议:** 明确区分默认行为，或在没有参数时打印帮助信息并退出。

---

### L3. `backup_state.py` 未显式备份 `config.json`

**文件/位置:** `backup_state.py`  
**影响:** 现在 `config.json` 被追踪，但如果用户本地修改后未提交，备份脚本未包含它。

**修复建议:** 将 `config.json` 加入 `PROTECTED_FILES` 列表。

---

### L4. `ci.yml` 的定时回测可能消耗大量 CI 资源

**文件/位置:** `.github/workflows/ci.yml`  
**影响:** 每天 07:00 UTC 运行回测，如果数据下载耗时，可能超时或产生较长 GitHub Actions 账单。

**修复建议:**
1. 将定时回测改为每周一次，或仅在 data 目录缓存命中时运行。
2. 设置 timeout-minutes 避免长时间挂起。

---

### L5. `AlpacaExecutor` 仍是 `AlpacaPaperExecutor` 的薄包装

**文件/位置:** `alpaca_executor.py:AlpacaExecutor`  
**影响:** 重命名后，该类只是透传方法，未增加额外业务逻辑，存在不必要的抽象层。

**修复建议:** 将 `AlpacaPaperExecutor` 改名为 `AlpacaExecutor`，删除旧包装器，统一入口。

---

### L6. `get_config()` 单例在修改 `config.json` 后不会重新加载

**文件/位置:** `config.py:get_config()`  
**影响:** 程序运行期间修改 `config.json` 不会生效，需重启进程。

**修复建议:** 增加可选的 `reload()` 方法或文件修改时间戳检查。

---

## 上一轮缺陷修复状态确认

| 原缺陷 | 状态 | 说明 |
|--------|------|------|
| API Key 硬编码 | ✅ 已修复 | 已改为环境变量注入，历史泄露文件已清理 |
| int() 截断 | ✅ 已修复 | 回测按整数股 + cash 跟踪；live 使用 Decimal 精度 |
| 订单幂等性 | ✅ 已修复 | 使用 `client_order_id` 去重 |
| 裸 except Exception | ✅ 已修复 | 核心路径改为具体异常类型 |
| 回测/实盘信号不一致 | ⚠️ 部分修复 | 已共用 `generate_signals`，但数据构造路径仍不同（H2） |
| 线程竞态 | ✅ 已修复 | `trading_halted` 已加锁 |
| 非 Atomic 调仓 | ⚠️ 部分修复 | 已有预检查/回滚框架，但完整回滚逻辑仍需加强（M1） |
| 无流动性检查 | ⚠️ 部分修复 | 有 `min_notional` 检查，但无 quote size 深度检查 |
| float 资金 | ✅ 已修复 | 使用 Decimal 计算 |
| 无交易日历 | ✅ 已修复 | 使用 `exchange_calendars` |
| 废弃 pandas API | ✅ 已修复 | 已改为 `.ffill()` 等 |
| 配置验证 | ✅ 已修复 | 使用 pydantic |
| 非结构化日志 | ✅ 已修复 | 已接入结构化 JSON 日志 |
| 无测试 | ✅ 已修复 | 已有 65 个测试 |

---

## 结论与建议

- **Critical:** 0
- **High:** 2（H1 config.json 凭证风险；H2 回测/实盘信号路径不一致）
- **Medium:** 7
- **Low:** 6

**建议下一步：**
1. 处理 H1：决定 `config.json` 是否继续追踪，并增加凭证泄露防护。
2. 处理 H2：统一回测与实盘的数据准备路径，确保信号一致。
3. 处理 M1：完善部分成交/失败回滚机制，这是进入 paper 交易前的关键工程保障。
4. 处理 M7：补充 Alpaca 执行链的集成测试，再运行一轮 `--live --paper` 的 1 股 SPY 测试单。

---

*审计人: Qs*  
*方法: 静态代码分析 + 上一轮修复状态验证 + 量化交易最佳实践对比*
