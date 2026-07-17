# MultiFactor V14 缺陷修复报告

**报告日期:** 2026-07-16  
**修复人:** Qs  
**仓库:** https://github.com/zhouyouhulianwang/quant-strategies  
**涉及目录:** `multifactor/`

---

## 摘要

本报告记录 MultiFactor V14 策略在 2026-07-16 针对 Alpaca 执行链路、PDT/风控、订单管理、配置验证与工程化缺陷的修复工作。修复范围以 `AUDIT_REPORT_ALPACA.md` 与 `AUDIT_REPORT.md` 中剩余的 P0/P1 缺陷为主，同时包含部分 P2 改进。当前代码状态通过 35 个 pytest 测试与 1 份 mock end-to-end 测试验证，未引入破坏性变更。

---

## 审计范围与方法

### 审计范围
- 执行链路：`alpaca_executor.py`、`order_manager.py`、`pdt_tracker.py`
- 策略封装与回测：`run_strategy.py`、`main.py`
- 风控与监控：`risk_monitor.py`、`intraday_monitor.py`
- 配置与调度：`config.py`、`scheduler.py`
- 工程与测试：`test_suite.py`、`.gitignore`、`.env.example`、`README.md`

### 审计方法
- 静态代码审查（安全、逻辑、竞态、异常处理）
- 运行时 mock 验证（不连接真实 Alpaca API）
- `pytest` 单元测试与集成测试（共 35 项）
- `mock_end_to_end_test.py` 端到端流程验证
- Git 历史核对（`git log` / `git status`）

---

## 修复概览

### P0 — 严重缺陷（实盘前必须修复）

| # | 问题 | 修复方式 | 涉及文件 |
|---|------|----------|----------|
| P0-1 | PDT 在下单时记录，未按真实成交判断 | 重写 `PDTTracker`，基于 FIFO lot 与 `record_fill()`，仅在成交（filled）时判定 day trade | `pdt_tracker.py` |
| P0-2 | PDT 状态未区分 paper/live 账户 | `PDTTracker` 按 `account_id + paper` 分文件存储，默认路径 `data/pdt_{account_id}.json` | `pdt_tracker.py`, `alpaca_executor.py` |
| P0-3 | 无持仓/现金对账 | 新增 `AlpacaPaperExecutor.reconcile(expected_cash, expected_positions)`，对比本地与券商持仓/现金差异 | `alpaca_executor.py` |
| P0-4 | live 模式无二次确认 | `AlpacaPaperExecutor.__init__` 增加 `require_live_confirmation`，非 paper 模式下要求输入 `LIVE` 才能继续；支持 `ALPACA_LIVE_CONFIRMED=1` 环境变量用于非交互环境 | `alpaca_executor.py` |
| P0-5 | 订单超时无撤单 | `OrderManager.submit_and_wait` 超时时调用 `executor.cancel_order(order_id)`，然后返回 `TIMEOUT` | `order_manager.py` |
| P0-6 | 订单幂等性不足 | 引入 `rebalance_session` + `client_order_id` 格式 `v14-{session}-{symbol}-{side}-{qty}`，并提供 `_find_order_by_client_id` 去重 | `alpaca_executor.py` |
| P0-7 | 卖出侧未做 PDT 检查 | `_check_pdt` 覆盖 `buy` 与 `sell`，`record_fill` 与 `can_open_position` 处理双向 day trade | `alpaca_executor.py`, `pdt_tracker.py` |
| P0-8 | 非 mock 模式下 SDK 未安装时静默降级 | 未安装 `alpaca-py` 且非 `mock=True` 时直接抛出 `RuntimeError`，禁止无感知 fallback | `alpaca_executor.py` |
| P0-9 | 清仓前未缓存持仓，导致 PDT 无法记录平仓 | `liquidate_all` 先缓存 `positions` 再调用 `close_all_positions`，随后按缓存记录 `record_fill(..., 'sell', ...)` | `alpaca_executor.py` |

### P1 — 高风险缺陷（实盘后可能亏损或稳定性问题）

| # | 问题 | 修复方式 | 涉及文件 |
|---|------|----------|----------|
| P1-1 | 订单超时时间不可配置 | `config.py` 中 `max_wait_sec` 默认 1800 秒，透传至 `run_strategy.py` → `RebalanceManager.rebalance` | `config.py`, `run_strategy.py`, `order_manager.py` |
| P1-2 | 订单部分成交未记录 PDT | `OrderManager` 在 `filled`/`partially_filled` 时调用 `executor.record_fill(symbol, side, filled_qty)` | `order_manager.py` |
| P1-3 | 无持仓同步机制 | `AlpacaPaperExecutor.sync_positions()` 将券商持仓同步到 `PDTTracker`，并同步券商 `daytrade_count` | `alpaca_executor.py`, `pdt_tracker.py` |
| P1-4 | 目标仓位总和可能超过组合价值 | `weight_allocation.normalize_target_positions` 按比例缩放；`RebalanceManager.rebalance` 与 `V14AlpacaExecutor.rebalance_portfolio` 均调用归一化 | `weight_allocation.py`, `run_strategy.py`, `alpaca_executor.py`, `order_manager.py` |
| P1-5 | 买入前未检查购买力 | `submit_order` 在 `buy` 侧检查 `notional > buying_power` 时拒绝 | `alpaca_executor.py` |
| P1-6 | 账户 API 失败时仍可能下单 | `_check_pdt` 在账户信息不可用时默认拒绝交易 | `alpaca_executor.py` |
| P1-7 | 同 symbol 同会话无法重复下单 | `client_order_id` 加入 `qty` 字段，避免数量变化时仍被去重 | `alpaca_executor.py` |
| P1-8 | 无实时组合级止损/集中度检查 | `run_strategy.py` 的 `V14IntradayMonitor` 补充 `check_daily_loss` 与 `check_concentration_risk` | `run_strategy.py` |
| P1-9 | 实时价格源仍回退 Yahoo Finance | `_get_current_price` 优先使用 Alpaca `StockLatestQuoteRequest`，无数据时显式 `RuntimeError`；mock 模式下保留默认价 | `alpaca_executor.py` |
| P1-10 | 无 API 速率限制 | `alpaca_executor.py` 初始化时用 `RateLimitedAPI` 包装 trading/data client（200/min） | `alpaca_executor.py`, `rate_limiter.py` |
| P1-11 | 废弃 pandas API | `main.py` 与 `run_strategy.py` 中 `fillna(method='ffill')` 替换为 `ffill()` | `main.py`, `run_strategy.py` |
| P1-12 | 月末调仓不考虑节假日 | `scheduler.py` 使用 `exchange_calendars` 的 XNYS 日历获取最后一个交易日，回退到仅跳过周末 | `scheduler.py` |
| P1-13 | 买入部分成交后直接全仓回滚 | `RebalanceManager.rebalance` 增加 `topup_on_partial`，优先补单；仅当补单后仍低于 `min_buy_fill_ratio` 才回滚 | `order_manager.py` |
| P1-14 | 无配置验证层 | 新增 `config.py`，使用 `pydantic` 对风控、交易、权重、API 凭证做校验，支持环境变量注入 | `config.py` |

### P2 — 中等风险/工程化改进

| # | 问题 | 修复方式 | 涉及文件 |
|---|------|----------|----------|
| P2-1 | 日志非结构化，无法审计 | 接入 `json_logger.py`，在 `OrderManager` 与 `RebalanceManager` 中输出 JSON 结构化日志 | `order_manager.py`, `alpaca_executor.py`, `json_logger.py` |
| P2-2 | 废弃 API 与 warning | 修复 `fillna` 废弃调用，清理 `intraday_monitor` 与 `visualization` 中已知 warning | `main.py`, `run_strategy.py`, `visualization.py`, `intraday_monitor.py` |
| P2-3 | `.gitignore` 未覆盖 PDT 文件 | 新增 `data/pdt_*.json` 与 `.last_rebalance.json` 排除 | `.gitignore` |
| P2-4 | 无端到端 mock 测试 | 新增 `mock_end_to_end_test.py`，模拟完整调仓、PDT 触发、紧急平仓 | `mock_end_to_end_test.py` |
| P2-5 | README 与项目说明滞后 | 更新 `README.md` 中模块描述与运行命令 | `README.md` |

---

## 文件修改清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `mock_end_to_end_test.py` | 端到端 mock 测试：完整调仓、PDT 触发、紧急平仓，不连接真实 API |

### 主要修改文件

| 文件 | 主要修改 |
|------|----------|
| `alpaca_executor.py` | live 二次确认；按账户初始化 PDT；`record_fill` / `sync_positions` / `cancel_order` / `reconcile`；订单幂等 `client_order_id`；买入购买力检查；卖出侧 PDT；限价单；Atomic 预检查；速率限制包装；`Decimal` 精度补偿；显式价格源错误 |
| `order_manager.py` | 超时撤单；`filled`/`partially_filled` 记录 PDT；结构化日志；`min_buy_fill_ratio` 补单逻辑；回滚机制 |
| `pdt_tracker.py` | 基于 FIFO lot 的成交驱动 day trade 判定；按账户分文件；`sync_positions` 同步券商 daytrade_count；现金账户豁免；先卖后买场景 |
| `config.py` | 使用 pydantic 的配置验证；`max_wait_sec=1800` 默认值；环境变量注入 API 凭证；base_url 白名单校验 |
| `run_strategy.py` | 将 `max_wait_sec` / `poll_interval` 传给 `RebalanceManager`；移除 Yahoo Finance 兜底；VIX/集中度/日亏损补充检查；统一配置读取 |
| `scheduler.py` | 使用 `exchange_calendars` 处理交易日历；`.last_rebalance.json` 持久化；收盘后 16:30 ET 触发 |
| `intraday_monitor.py` | 线程状态同步修复；紧急平仓前检查市场状态；回撤基准重置 |
| `risk_monitor.py` | 组合级止损、VIX 等级、仓位限制、日亏损检查 |
| `weight_allocation.py` | `normalize_target_positions` 归一化；权重约束 |
| `main.py` | 废弃 pandas API 替换；`fillna(method='ffill')` → `ffill()` |
| `visualization.py` | 热力图边界检查 |
| `data_source.py` | 移除默认回退逻辑；错误处理增强 |
| `polygon_data.py` | 错误处理与回退清理 |
| `quantconnect_data.py` | 真实数据准备逻辑增强 |
| `cost_model.py` | 成本计算精度与边界处理 |
| `optimization.py` | 优化报告与错误处理 |
| `test_suite.py` | 新增 PDT、OrderManager、Reconciliation 测试；配置验证测试；速率限制测试；调度器测试 |
| `.gitignore` | 排除 `data/pdt_*.json`、`.last_rebalance.json` 等运行时文件 |
| `README.md` | 更新模块描述与运行命令 |

---

## 测试验证

### pytest 单元测试

```bash
cd multifactor
source .venv/bin/activate
python3 -m pytest test_suite.py -v
```

**结果:** `35 passed, 0 warnings`

测试覆盖：

| 测试类 | 用例数 | 说明 |
|--------|--------|------|
| `TestFactorComputation` | 4 | 因子计算结构、评分范围、VIX 缩放、因子方向性 |
| `TestRiskControl` | 4 | VIX 恐慌、回撤限制、仓位限制、风险等级转换 |
| `TestConfigValidation` | 4 | 有效配置、无效 VIX 阈值、无效仓位比例、赋值验证 |
| `TestOrderIdempotency` | 3 | `client_order_id` 格式、会话隔离、去重方法 |
| `TestWeightAllocation` | 4 | 等权、风险平价、权重上限、目标持仓归一化 |
| `TestScheduler` | 2 | 月末交易日计算、重复调仓判断 |
| `TestExecutor` | 3 | mock 模式、V14 包装器、速率限制器 |
| `TestUnifiedBacktest` | 2 | 模拟信号生成、空数据保护 |
| `TestPDTTracker` | 4 | 成交驱动记录、3 次 day trade 拦截、现金账户豁免、账户隔离 |
| `TestOrderManager` | 2 | 超时撤单、成交记录 PDT |
| `TestReconciliation` | 3 | 对账一致、现金差异、持仓差异 |
| **合计** | **35** | |

### mock end-to-end 测试

```bash
# 已在当前环境执行，无需真实 Alpaca 凭证
python3 mock_end_to_end_test.py
```

**结果:** 输出显示完整调仓 3 笔订单全部 `filled`；PDT 触发后再次买入被拦截；`liquidate_all` 平掉所有持仓；最终无异常退出。

```
============================================================
Mock 端到端测试：完整调仓
============================================================
订单数量: 3
  AAPL: filled
  MSFT: filled
  NVDA: filled

调仓后持仓数量: 0

账户权益: $1,000,000.00
现金: $1,000,000.00

============================================================
Mock 端到端测试：PDT 触发与紧急平仓
============================================================
PDT 拦截结果: {...}

紧急平仓后持仓数量: 0

============================================================
✅ Mock 端到端测试完成，无崩溃
============================================================
```

---

## 已知限制与后续 TODO

| 分类 | 说明 | 建议后续动作 |
|------|------|--------------|
| **Paper Trading 实测** | 当前所有交易测试均使用 mock 或 fake client，未连接真实 Alpaca API | 在纸交易账户上执行一次小额完整调仓，验证订单提交、成交、持仓同步、PDT 状态文件 |
| **缓存迁移** | 现有 `data_cache/` 为旧版 pickle 缓存，未统一迁移到 QuantConnect / Alpaca 数据源 | 清理过期缓存，建立统一缓存键与失效策略 |
| **风控文档** | 风险监控逻辑已完善，但操作手册未覆盖紧急平仓、VIX 暂停、日亏损等场景 | 编写 `RISK_RUNBOOK.md`，包含触发条件、人工介入流程、恢复交易步骤 |
| **实时行情** | 限价单价格源依赖 Alpaca LatestQuote；若 Alpaca 数据不可用则直接报错 | 评估是否需要 Polygon.io 二级 fallback，或增加行情源健康检查 |
| **部分成交补单** | 已实现部分成交补单，但未在真实 API 上验证 | Paper Trading 中刻意使用限价单制造部分成交场景，验证补单与回滚 |
| **独立风控进程** | 当前盘中监控为单线程运行，未拆分为独立服务 | 后续评估是否需要独立进程/容器运行风控，避免主交易线程阻塞 |
| **公司行为** | 拆股、分红、并购等公司行为未处理 | 增加公司行为事件监听与持仓调整 |
| **Git 历史清理** | 早期提交中可能仍包含其他目录（`adaptive_momentum/`、`AdaptiveMomentumV3_1/`）的敏感信息 | 已另行处理 API Key；如需彻底清理 Git 历史，使用 `git filter-repo` 或 BFG |
| **配置热加载** | 当前配置在进程启动时读取，运行中修改需重启 | 后续增加配置热加载或 SIGHUP 重载 |

---

## 安全说明

### 1. `.env` 删除与凭证存储

- 当前 `multifactor/` 目录下不存在 `.env` 文件，仅保留 `.env.example` 作为模板。
- 所有 Alpaca 凭证通过环境变量注入：
  - `ALPACA_API_KEY`
  - `ALPACA_API_SECRET`
  - `ALPACA_BASE_URL`
- `config.py` 使用 pydantic 校验凭证非空，避免空值静默运行。
- 日志中不打印任何 API Key / Secret 片段（包括 `alpaca_executor.py` 的 live 确认流程）。

### 2. 凭证轮换

- 用户已自行在 Alpaca 后台完成旧 Key 删除与新 Key 生成。
- 本修复未修改任何硬编码凭证，也未在代码中存储真实 Key。

### 3. 环境变量注入方式

**开发/测试：**

```bash
export ALPACA_API_KEY="PK_..."
export ALPACA_API_SECRET="SK_..."
export ALPACA_BASE_URL="https://paper-api.alpaca.markets"
```

**systemd / cron：**

```bash
# /etc/systemd/system/v14-scheduler.service
[Service]
Environment="ALPACA_API_KEY=PK_..."
Environment="ALPACA_API_SECRET=SK_..."
Environment="ALPACA_BASE_URL=https://paper-api.alpaca.markets"
```

**Docker：**

```bash
docker run -e ALPACA_API_KEY="PK_..." -e ALPACA_API_SECRET="SK_..." v14-scheduler
```

### 4. Git 安全

- `.gitignore` 已排除：`.env`、`.venv/`、`data/pdt_*.json`、`.last_rebalance.json`、`orders/`、`alerts/`、`charts/` 等运行时文件。
- 建议提交前运行 `git status` 确认无敏感文件被误加入。

### 5. live 模式交互确认

- 非 paper 模式下，默认要求终端输入 `LIVE` 才能继续。
- 非交互环境（如 CI、systemd）可设置 `ALPACA_LIVE_CONFIRMED=1` 跳过输入，但仍会记录 `CRITICAL` 级别日志。

---

## 部署与运行指南

### 1. 运行回测

```bash
cd /home/pc/.openclaw/workspace/multifactor
source .venv/bin/activate

# 使用模拟数据（无需 API Key）
python3 run_strategy.py --backtest

# 使用真实数据（需 QuantConnect Lean CLI 或已配置数据源）
python3 run_strategy.py --backtest --real-data

# 指定日期范围
python3 run_strategy.py --backtest --real-data --start 2020-01-01 --end 2024-12-31
```

### 2. 设置 Alpaca 环境变量

```bash
export ALPACA_API_KEY="PK_xxxxxxxxxxxxxxxxxxxxxxxx"
export ALPACA_API_SECRET="SK_xxxxxxxxxxxxxxxxxxxxxxxx"
export ALPACA_BASE_URL="https://paper-api.alpaca.markets"  # paper
# export ALPACA_BASE_URL="https://api.alpaca.markets"      # live
```

或者创建 `.env` 文件（**不要提交到 Git**）：

```bash
cp .env.example .env
# 编辑 .env 填入真实凭证
```

### 3. 运行 Paper Trading 单次调仓

```bash
python3 run_strategy.py --live --paper
```

### 4. 启动 scheduler（定时月度调仓）

```bash
# 前台运行，每小时检查一次是否到月末交易日
python3 -c "from run_strategy import V14Strategy; from scheduler import run_scheduler_loop; s = V14Strategy(use_real_data=True, use_paper_trading=True); run_scheduler_loop(s, check_interval=3600)"
```

或使用 systemd 服务（示例）：

```ini
# /etc/systemd/system/multifactor-v14.service
[Unit]
Description=MultiFactor V14 Scheduler
After=network.target

[Service]
Type=simple
User=pc
WorkingDirectory=/home/pc/.openclaw/workspace/multifactor
Environment="ALPACA_API_KEY=PK_..."
Environment="ALPACA_API_SECRET=SK_..."
Environment="ALPACA_BASE_URL=https://paper-api.alpaca.markets"
ExecStart=/home/pc/.openclaw/workspace/multifactor/.venv/bin/python3 -c "from run_strategy import V14Strategy; from scheduler import run_scheduler_loop; s = V14Strategy(use_real_data=True, use_paper_trading=True); run_scheduler_loop(s, check_interval=3600)"
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

加载并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable multifactor-v14.service
sudo systemctl start multifactor-v14.service
sudo systemctl status multifactor-v14.service
```

### 5. 运行测试

```bash
# 单元测试
python3 -m pytest test_suite.py -v

# 端到端 mock 测试
python3 mock_end_to_end_test.py
```

---

## 附录：保留决策

| 决策 | 说明 |
|------|------|
| 小数股 | 保持 `int()` 截断，不启用 fractional trading（按用户要求） |
| API Key | 用户已自行轮换，未在代码中修改 |
| 交易标的 | 当前股票池仍为大盘科技股，未扩展小盘股 |

---

*报告生成时间: 2026-07-16 11:24 UTC*
