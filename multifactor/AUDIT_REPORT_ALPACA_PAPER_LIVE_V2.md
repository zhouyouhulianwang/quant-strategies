# Alpaca 纸交易 / 实盘执行路径审计报告 V2

**审计日期**: 2026-07-17  
**审计范围**: `/home/pc/.openclaw/workspace/multifactor`  
**重点文件**: `run_strategy.py`, `paper_smoke_test.py`, `alpaca_executor.py`, `order_manager.py`, `pdt_tracker.py`, `risk_monitor.py`, `config.py`, `strategies/v14.py`  
**审计方式**: 只读代码审计 + 关键路径本地复现（未修改任何源文件）  

## 1. 总体结论

本轮审计发现：

| 等级 | 数量 | 说明 |
|------|------|------|
| P0   | 1    | 会实际导致误下实盘单或交易被错误判定为失败 |
| P1   | 8    | 会导致状态不一致、合规风险、配置与执行脱节、测试不可信 |
| P2   | 5    | 体验/日志/边缘行为问题，需改进但无直接资金风险 |
| **合计** | **14** | |

`config.json` 解析失败时 **fail-fast 机制已正确生效**（见第 7 节）。但 `alpaca_base_url` 配置项在执行路径中被忽略，仍存在配置与执行脱节的问题。

---

## 2. P0 缺陷（实际资金/操作风险）

### P0-1 `paper_smoke_test.py` 下单后把 `dict` 当 SDK 对象访问，导致脚本在实盘单已提交后崩溃并误导用户重试

**位置**: `paper_smoke_test.py`

**代码**:  
```python
order = executor.submit_order(
    symbol=symbol,
    qty=qty,
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    time_in_force=TimeInForce.DAY,
)
print(f"  Order submitted: {order.id} status={order.status}")
```

**问题**: `AlpacaExecutor.submit_order` 内部调用 `AlpacaPaperExecutor.submit_order`，后者返回的是经过 `_order_to_dict()` 转换后的 **字典**（含 `id`/`status` 等键），而不是 Alpaca SDK 的 Order 对象。因此 `order.id` / `order.status` 会触发 `AttributeError`。

**实际风险**: 该 `print` 位于 `try ... except Exception` 块内，异常会被捕获并输出为 `"Order submission failed: 'dict' object has no attribute 'id'`。此时 **订单已经真实提交到 Alpaca**，但脚本返回 `1` 让操作者以为下单失败。操作者很可能再次运行脚本，从而 **重复下实盘单**，造成意外资金暴露和交易成本。若 `--qty` 不是 1 股，重复订单风险更高。

**本地复现**:  
```bash
python3 -c "from alpaca_executor import AlpacaExecutor; e=AlpacaExecutor('k','s',paper=True,mock=True); o=e.submit_order('SPY',1,'buy'); print(type(o)); print(o.id)"
# 输出: <class 'dict'>  + AttributeError
```

**修复建议**: 将 `order.id` / `order.status` 改为 `order.get('id')` / `order.get('status')`，并在 `print` 前检查返回是否非空。

---

## 3. P1 缺陷（高优先级）

### P1-1 `paper_smoke_test.py` 计算了 live base_url 却未传入执行器，导致端点切换不可靠

**位置**: `paper_smoke_test.py`  

```python
if args.live:
    paper = False
    base_url = "https://api.alpaca.markets"
...
executor = AlpacaExecutor(
    api_key=api_key,
    api_secret=secret_key,
    paper=paper,
    risk_monitor=None,  # 未传 base_url
)
```

**问题**: `base_url` 被计算出来但没有传给 `AlpacaExecutor`。`AlpacaPaperExecutor` 实际使用的 `base_url` 来自 `ALPACA_BASE_URL` 环境变量或 `.env`。如果用户环境为日常 paper 交易设置了 `ALPACA_BASE_URL=https://paper-api.alpaca.markets`，运行 `paper_smoke_test.py --live --confirm-live` 会在执行器初始化时因 `paper=False` 与 `base_url=paper` 不匹配而直接 `ValueError` 退出；反之，若环境为 live，运行 `--paper` 也会失败。测试脚本无法在不修改环境变量的情况下可靠切换纸/实盘端点。

**风险**: 无法独立验证实盘连通性，测试结论不可信；在紧急排查时可能因环境配置问题掩盖真实连接故障。

**修复建议**: 将 `base_url=base_url` 显式传入 `AlpacaExecutor`。

---

### P1-2 `OrderManager` 状态机在部分成交+补单后留下“原订单已取消”的 stale 状态

**位置**: `order_manager.py` 的 `OrderManager._place_makeup_with_cancel` 与 `submit_and_wait`

**问题**: 当原订单部分成交后，`_place_makeup_with_cancel` 会先把原订单状态强制迁移为 `CANCELLED`：

```python
if cancel_ok:
    current_state = self.order_states.get(order_id)
    if current_state != OrderState.TIMEOUT:
        self._transition(order_id, OrderState.CANCELLED, ...)
```

随后对剩余数量下补单。若补单成交使整体数量满足，合并后的状态为 `filled`，但代码尝试把原订单状态再次迁移到 `FILLED` 时，因为 `_VALID_TRANSITIONS` 中 `CANCELLED -> FILLED` 是非法转换，状态机 **拒绝更新**，并只在 metadata 中记录一次非法转换。最终原订单状态停留在 `CANCELLED`，与真实持仓/成交结果不一致。

**风险**: 任何依赖 `order_states` 做后续判断或报告的逻辑（如回滚、审计、风控）都会基于错误状态；`/data` 与日志中的状态与券商真实订单不一致，增加对账和事故排查难度。

**修复建议**: 补单合并成功后，要么更新为“组合订单”状态、要么单独维护母订单/子订单状态，避免对不可再迁移的终态订单做反向迁移。

---

### P1-3 `PDTTracker` 对同一标的同一天的多次日内回转只计一次，可能低估 day trade 次数

**位置**: `pdt_tracker.py` 的 `PDTTracker._record_day_trade`

**代码**:  
```python
key = (today_str, symbol)
existing = {(dt['date'], dt['symbol']) for dt in self.day_trade_history}
if key not in existing:
    self.day_trade_history.append({...})
```

**问题**: 去重键是 `(date, symbol)`，而不是按每次开仓/平仓配对计数。因此，同一天对同一标的做两次完整往返（例如 buy→sell→buy→sell）只被记为 1 次 day trade。

**本地复现**:  
```python
tracker = PDTTracker(enabled=True, paper=True, account_id='multi')
tracker.record_fill('AAPL','buy',10); tracker.record_fill('AAPL','sell',10)
tracker.record_fill('AAPL','buy',10); tracker.record_fill('AAPL','sell',10)
print(tracker.day_trade_history)  # 仅 1 条记录
```

**风险**: 在保证金账户权益低于 $25,000 时，可能突破 FINRA 的 3 日 day trade 限制，导致券商施加 90 天交易限制或账户限制。虽然本策略调仓频率不高，但补单、回滚或异常重试可能在同一天产生多次往返，触发该风险。

**修复建议**: 按实际成交配对记录 day trade，或者保守地按 `symbol+date` 的次数累加并取上限。

---

### P1-4 `RebalanceManager` 可能同时触发内部补单和顶层补单，导致同标的多个活跃订单

**位置**: `order_manager.py` 的 `OrderManager.submit_and_wait` 与 `RebalanceManager.rebalance`

**问题**: `OrderManager.submit_and_wait` 在部分成交时已经会取消原单并下补单（`max_makeup_depth=1`）。而 `RebalanceManager.rebalance` 在 `topup_on_partial=True` 且 `fill_ratio < min_buy_fill_ratio` 时，会再次调用 `OrderManager.submit_and_wait` 下第二笔补单。原单已在第一次补单时被取消，但第一次补单本身可能仍然处于 `partially_filled` 状态。第二次补单会针对剩余数量重新下单，却**不会取消**第一次补单，导致同一标的同一方向同时存在两个未完全成交订单。

**风险**: 竞态下可能产生超目标成交（overfill），使组合暴露、现金使用超出预期，或在价格不利时被动加仓。

**修复建议**: 在 `RebalanceManager` 做 topup 前，显式检查/取消尚未完结的同类补单，或把 `max_makeup_depth` 与顶层 topup 逻辑统一。

---

### P1-5 `run_strategy.py` / `V14Strategy` 忽略 `config.json` 中的 `alpaca_base_url`

**位置**: `run_strategy.py`、`strategies/v14.py` 的 `V14Strategy.__init__`

**问题**: `V14Strategy` 初始化执行器时只传了 `paper` 布尔值，没有使用 `self.config.alpaca_base_url`：

```python
self.executor = AlpacaExecutor(
    paper=paper,
    enable_pdt=...,
    pdt_min_equity=...,
    use_limit_orders=...,
    limit_order_offset_pct=...,
)
```

`AlpacaPaperExecutor` 实际读取的是 `ALPACA_BASE_URL` 环境变量或 `.env`，`config.json` 里的 `alpaca_base_url` 被完全忽略。

**风险**: 配置与执行行为不一致。运维人员修改 `config.json` 的 base_url 后期望切换端点，但程序仍按环境变量或 CLI 标志运行，易产生“配置改了却无效”的误判，甚至误将实盘请求发到纸交易地址或反之。

**修复建议**: 将 `self.config.alpaca_base_url` 显式传入 `AlpacaExecutor`，并在 `run_strategy.py` 中让 `--paper`/`--live` 与配置冲突时 fail-fast。

---

### P1-6 连续拒绝熔断直接修改 `trading_halted`，缺失 `halt_trading()` 的日志、告警和持久化

**位置**: `alpaca_executor.py` 的 `AlpacaPaperExecutor._maybe_halt_on_rejections`

**代码**:  
```python
if self.risk_monitor is not None:
    try:
        self.risk_monitor.trading_halted = True
    except Exception as e:
        ...
self._send_alert('risk_triggered', 'CIRCUIT_BREAKER', ...)
```

**问题**: 没有调用 `RiskMonitor.halt_trading()`，而是直接给属性赋值。`halt_trading()` 会记录 `halt_reason`/`halt_time`、触发告警、并将状态持久化到 `data/risk_state.json`。直接赋值只改了内存状态。

**风险**: 进程重启后 `RiskMonitor` 会从 `risk_state.json` 重新加载 `trading_halted=False`，熔断失效，可能继续下原本应被阻止的订单。同时缺少 `halt_reason` 和持久化，导致运维无法判断为何暂停交易。

**修复建议**: 使用 `self.risk_monitor.halt_trading(...)` 而不是直接赋值。

---

### P1-7 `RebalanceManager` 未在调仓前做总购买力预检查，可能导致部分成交后留下非目标组合

**位置**: `order_manager.py` 的 `RebalanceManager.rebalance`

**问题**: `RebalanceManager.rebalance` 在卖出阶段完成后，逐个买入标的时只检查单笔 `qty * current_price > buying_power`，未像 `AlpacaExecutor.rebalance_portfolio._atomic_precheck` 那样汇总所有买入金额并与可用购买力（含卖出释放资金）比较。一旦总买入金额超过 buying power，后面的买单会被券商拒单或 `OrderManager` 标记为 FAILED。

**风险**: 调仓结果不完整：部分标的已卖出，后续买入失败，组合偏离目标权重；若 `enable_rollback=True`，还会触发回滚，产生额外交易和成本。

**修复建议**: 在循环买入前执行一次总资金预检查，或在 `V14Strategy.live_trade` 调用前使用 `AlpacaExecutor.rebalance_portfolio` 的 Atomic 预检查。

---

### P1-8 `V14Strategy.run_live_rebalance` 仅在调仓开始前检查一次收盘保护

**位置**: `strategies/v14.py` 的 `V14Strategy.run_live_rebalance`

**问题**: 收盘保护只在进入函数时检查一次，随后执行 `generate_signals()`、公司行为同步、PDT 同步、风险检查，最后进入 `live_trade()`。若信号生成或数据请求耗时较长，后续订单可能落在收盘保护时间之后。

**风险**: 在临近收盘时提交市价/限价订单，可能以不利价格成交或无法成交，且与策略 EOD 调仓初衷相违背。

**修复建议**: 在 `live_trade` 内部下单前再次检查收盘保护，或在 `RebalanceManager` 循环中每次下单前检查。

---

## 4. P2 缺陷（改进项）

### P2-1 `paper_smoke_test.py` 存在冗余确认链

`--confirm-live` 标志 + `input("Type 'yes' to proceed")` + `AlpacaPaperExecutor._confirm_live_mode` 的 `input("Enter 'LIVE' to confirm")` 三重确认。对于 CI 自动化极不友好，且 `AlpacaExecutor` 并未收到 `require_live_confirmation=False`，导致非交互环境必须额外设置 `ALPACA_LIVE_CONFIRMED=1`。

### P2-2 `run_strategy.py` 在解析参数前执行 `cleanup_runtime_files`

`main()` 先调用 `cleanup_runtime_files()` 再调用 `parser.parse_args(argv)`。因此即使运行 `python run_strategy.py --help`，也会触发对 `orders/alerts/charts` 目录的清理，行为与帮助预期不符。

### P2-3 `run_strategy.py` 的 `--real-data` 标志未实际生效

```python
parser.add_argument('--real-data', action='store_true', help='Use real data')
```
`args.real_data` 在后续代码中从未被读取。`use_real_data` 固定为 `True`（mock 时改为 `False`），用户传递该标志不会产生任何效果，属于误导性选项。

### P2-4 `OrderManager.submit_and_wait` 对非网络拒绝也会重试 3 次

当 `executor.submit_order` 因 PDT、资金不足、风控暂停等原因返回 `None` 时，`submit_and_wait` 会再重试两次。这些不是瞬态网络错误，重试不会提高成功率，只会增加延迟和 API 调用次数。

### P2-5 `AlpacaPaperExecutor.get_all_orders` 分页使用字符串 `until`

```python
current_until = oldest.get('submitted_at')  # 字符串
request = GetOrdersRequest(status=status_enum, limit=page_size, until=current_until)
```
`alpaca-py` 的 `GetOrdersRequest` 的 `until` 参数通常为 `datetime`。传入字符串可能在 SDK 版本差异下产生分页异常或失效，导致历史订单获取不完整。

---

## 5. 配置解析 fail-fast 检查

### 结论：已正确 fail-fast

`config.py` 的 `get_config()` 行为：

1. 如果 `config.json` 存在但 JSON 非法，立即抛出 `json.JSONDecodeError` 包装为 `ValueError`；
2. 如果 `config.json` 内容不满足 `V14StrategyConfig` 的校验规则（如 `vix_panic_threshold < 20`），`pydantic` 会抛出 `ValidationError`；
3. 环境变量 `ALPACA_BASE_URL` 若传入无效域名，同样触发 `ValidationError`。

**本地验证**: 将 `config.json` 临时替换为 `{"risk": {"vix_panic_threshold": 15}}` 后调用 `reload_config()`，程序立即抛出 `ValidationError: VIX 恐慌阈值应 >= 20`。因此配置解析失败时不会以错误配置继续运行交易，符合 fail-fast 要求。

**遗留问题**: 配置 fail-fast 虽生效，但 `alpaca_base_url` 配置项没有被执行路径使用（见 P1-5），配置与执行仍存在脱节。

---

## 6. 逐项检查摘要

| 检查项 | 结果 | 说明 |
|--------|------|------|
| `run_strategy.py` 模式互斥 | ✅ 基本正确 | 使用 `argparse` 互斥组，`--paper`/`--live`/`--backtest`/`--mock` 互斥，且 `--live` 强制要求 `--confirm-live` |
| `paper_smoke_test.py` --live 真走实盘 | ⚠️ 路径存在但实现有缺陷 | 计算了 live base_url 却未传给执行器；下单后把 dict 当对象访问导致崩溃 |
| `paper_smoke_test.py` 安全确认 | ✅ 有确认 | 需要 `--confirm-live` 标志 + 交互式 `yes` 确认；但缺少执行器层面的 `ALPACA_LIVE_CONFIRMED` 说明 |
| `AlpacaExecutor` 无 SDK/无 API key 安全降级 | ✅ 正确 | 未安装 `alpaca-py` 时 `run_strategy.py` 和 `paper_smoke_test.py` 都直接报错；无 API key 时 `AlpacaPaperExecutor` 也直接 `ValueError`，不会静默 mock |
| `order_manager.py` 订单提交/取消/重试/部分成交/状态机 | ⚠️ 部分正确 | 状态机在补单后产生 stale 状态；部分成交可能触发双重补单；非网络错误也会重试 |
| `pdt_tracker.py` 日计数与 5 日滚动窗口 | ⚠️ 滚动窗口正确，计数粒度不足 | 5 日滚动交易日历正确，但同一标的同天多次往返被去重为 1 次 |
| `RiskMonitor.trading_halted` 阻止订单 | ✅ 执行路径已接入 | `submit_order` 和 `rebalance_portfolio` 均检查 `trading_halted`；但熔断路径未调用 `halt_trading()` 持久化 |
| 配置解析失败 fail-fast | ✅ 正确 | 非法 JSON 或校验失败会立即抛出异常 |

---

## 7. 建议优先级修复清单

1. **P0-1** 立即修复 `paper_smoke_test.py` 的 `order.id` / `order.status` 访问方式，确保 live 测试不会误导用户重复下单。
2. **P1-1** 在 `paper_smoke_test.py` 中显式传入 `base_url`。
3. **P1-2** 修正 `OrderManager` 状态机，使补单成功后的组合状态能够正确反映为已成交。
4. **P1-3** 修正 `PDTTracker` 对多次同标同天往返的计数逻辑。
5. **P1-4** 统一 `OrderManager` 与 `RebalanceManager` 的补单逻辑，避免重复补单。
6. **P1-5** 让 `V14Strategy` / `run_strategy.py` 使用 `config.json` 中的 `alpaca_base_url`。
7. **P1-6** 将连续拒绝熔断改为调用 `RiskMonitor.halt_trading()`。
8. **P1-7** 在 `RebalanceManager` 或 `V14Strategy.live_trade` 中增加总购买力预检查。
9. **P1-8** 在 `live_trade` 下单前再次检查收盘保护。
10. 后续处理 P2 项（冗余确认、help 时清理、`--real-data` 失效、错误重试、`until` 类型）。

---

*报告生成路径*: `/home/pc/.openclaw/workspace/multifactor/AUDIT_REPORT_ALPACA_PAPER_LIVE_V2.md`  
*缺陷总数*: 14（P0: 1, P1: 8, P2: 5）
