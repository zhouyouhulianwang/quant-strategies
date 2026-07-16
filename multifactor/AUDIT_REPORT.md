# MultiFactor V14 全面审查报告
## 运行 Alpaca 模拟/实盘缺陷清单

**审查日期:** 2026-07-16  
**审查范围:** multifactor/ + adaptive_momentum/ + AdaptiveMomentumV3_1/  
**审查维度:** 安全、框架、代码、逻辑、风控、日志、配置

---

## 🔴 严重缺陷（实盘前必须修复）

### 1. API Key 泄露（安全灾难）

**问题:** Alpaca API Key 和 Secret 硬编码在 7 个文件中，并已上传到 GitHub。

```
AdaptiveMomentumV3_1/.env
AdaptiveMomentumV3_1/check_status.py
AdaptiveMomentumV3_1/test_positions.py
AdaptiveMomentumV3_1/test_orders.py
adaptive_momentum/check_status.py
adaptive_momentum/test_positions.py
adaptive_momentum/test_orders.py
```

**风险:** 任何人克隆仓库即可控制你的 Paper Trading 账户。

**修复:**
```bash
# 1. 立即在 Alpaca 后台删除旧 Key
# 2. 重写 Git 历史删除敏感信息
cd /home/pc/.openclaw/workspace
git filter-repo --path-glob "*/check_status.py" --path-glob "*/test_*.py" --path-glob "*/.env" --invert-paths
# 或使用 BFG Repo-Cleaner
# 3. 强制推送
git push origin --force --all
```

### 2. 资金计算使用 int() 截断（盈亏失真）

**位置:** `alpaca_executor.py:274`, `order_manager.py:228`, `cost_model.py:131`

```python
target_qty = int(target_value / current_price)  # 截断小数！
```

**后果:**
- NVDA @$400，目标 $20,000 → 应买 50 股（精确）
- AAPL @$150.75，目标 $20,000 → 截断后 132 股 = $19,899，漏买 $101
- 40 只股票累计误差可达数千美元
- Alpaca 支持小数股（fractional shares），`int()` 完全浪费此功能

**修复:**
```python
# Alpaca 支持小数股（需 account 开通）
target_qty = round(target_value / current_price, 4)  # 保留4位小数
```

### 3. 没有订单幂等性保障（重复下单风险）

**位置:** `alpaca_executor.py`, `order_manager.py`

**问题:** 如果脚本在调仓过程中崩溃重启，会重新生成相同的买入信号，导致重复下单。

**后果:** 系统故障恢复后可能双倍建仓，瞬间突破仓位限制。

**修复:**
```python
import uuid

# 每次调仓生成唯一 session_id
rebalance_session = uuid.uuid4().hex[:8]

# 下单时附加 client_order_id
order = api.submit_order(
    symbol=symbol, qty=qty, side=side,
    client_order_id=f"v14-{rebalance_session}-{symbol}"
)

# 重启时先查询未完成订单，避免重复
existing = api.list_orders(status='open')
```

### 4. 50 处裸 except Exception（异常静默）

**位置:** 整个代码库

**问题:** `except Exception as e` 捕获所有异常，包括 `KeyboardInterrupt`、`SystemExit`、内存错误等。

**后果:**
- 用户按 Ctrl+C 无法停止程序
- 风控异常被吞掉，继续执行交易
- 网络断开、磁盘满等系统错误被当作普通 API 错误处理

**修复:**
```python
# 不要捕获所有异常
try:
    result = api_call()
except ConnectionError as e:
    logger.error(f"网络错误: {e}")
    raise  # 向上传播
except ValueError as e:
    logger.error(f"参数错误: {e}")
    return None
# 不要写 except Exception，除非在最顶层统一处理
```

### 5. 回测和实盘信号生成共用同一函数（数据泄露）

**位置:** `main.py:compute_factors_v14()`

**问题:** 回测使用 `price_slice.iloc[-252:]`，实盘也用 `price_df.iloc[-252:]`。但实盘调用时 `price_df` 可能包含"未来数据"（如果数据源有问题）。

**更深层问题:** `run_v14()` 回测引擎在实盘完全没有对应物，回测验证的是一套代码，实盘运行的是另一套代码，两者没有一致性校验。

**修复:** 将信号生成分装为独立模块，回测和实盘共用同一 `generate_signals()` 函数，并添加 PIT（Point-in-Time）数据校验。

---

## 🟠 高风险缺陷（实盘后可能亏损）

### 6. 盘中监控和主线程竞态条件

**位置:** `intraday_monitor.py`

**问题:** 监控线程和主交易线程独立运行，没有锁机制。

**场景:**
1. 监控线程检测到 VIX=36，触发 `trading_halted = True`
2. 几乎同时，主线程检查 `trading_halted`（此时仍为 False）
3. 主线程提交买入订单
4. 监控线程执行 `liquidate_all()`，平掉刚买入的仓位
5. 结果：高买低卖，产生实质亏损 + 双倍交易成本

**修复:** 使用 `threading.Lock()` 或 `threading.Event()` 同步状态。

### 7. 调仓没有 Atomic 保障（部分成交风险）

**位置:** `alpaca_executor.py:rebalance_portfolio()`

**问题:** 先卖出 AAPL、MSFT... 再买入 NVDA... 中间任何一步失败，组合就处于"半成品"状态。

**场景:**
1. 卖出 10 只股票成功，释放现金
2. 买入第 3 只股票时 API 限流
3. 结果：70% 现金闲置，30% 持仓，完全偏离策略目标

**修复:**
```python
# 方案A: 预检查（所有订单都确认可执行后再统一提交）
# 方案B: 失败回滚（部分失败时撤销已成交订单）
# 方案C: 两阶段调仓（先只卖出/只买入到目标，不混合）
```

### 8. 没有流动性检查

**位置:** 全代码库

**问题:** 对 `GOOGL`、`AVGO` 等高价股和 `QCOM`、`MU` 等相对低价股使用相同的下单逻辑。

**场景:** 组合价值 $1M，目标单仓 $50K。AVGO @$1,800 → 27 股（没问题）。但如果某天单仓目标 $200K，AVGO 仍只有 111 股，但 `get_latest_trade()` 可能只是最后一笔成交价，实际挂市价单可能以 $1,820 成交。

**更危险场景:** 持仓中包含小盘股（当前股票池全是大盘，但如果未来扩展），市价单可能产生严重滑点。

**修复:** 检查 `quote.bid_size` / `quote.ask_size`，确保市场深度足够。

### 9. 没有 Decimal 精度处理

**位置:** 全代码库

**问题:** 所有资金计算使用 `float`，存在浮点误差累积。

```python
# 浮点误差的例子
>>> 0.1 + 0.2 == 0.3
False
>>> 0.1 + 0.2
0.30000000000000004
```

**后果:** 长期运行后，报告的 NAV 和实际账户现金可能出现偏差，风控计算基于错误数据。

**修复:** 对资金类变量使用 `Decimal`。

### 10. 月末调仓不考虑交易日历

**位置:** `scheduler.py:61`

```python
last_date = datetime(year, month, last_day).date()
while last_date.weekday() >= 5:  # 只跳过周末
    last_date -= timedelta(days=1)
```

**问题:** 没有处理节假日。如果月末是感恩节（周四），周五也是假日，代码会回退到周三，但周三可能也不是交易日（感恩节前一天提前收盘）。

**后果:** 在假日调仓，订单会被拒绝或延迟到下一个交易日，错过最佳执行时机。

**修复:** 使用 `pandas_market_calendars` 或 `exchange_calendars` 库。

---

## 🟡 中等风险缺陷（影响稳定性和可维护性）

### 11. 废弃的 pandas API

**位置:** `main.py:407`, `run_strategy.py:495`

```python
price_df = price_df.replace(0, np.nan).fillna(method='ffill')
```

`fillna(method='ffill')` 已在 pandas 2.0 中废弃，会报警告，未来版本将报错。

**修复:** `price_df.ffill()`

### 12. 没有配置验证层

**位置:** 全代码库

**问题:** 所有配置都是"信任输入"：
- `max_position_pct` 可以是负数或大于 1
- `vix_emergency_level` 可以是字符串
- `check_interval` 可以是 0（导致 CPU 100%）

**修复:** 使用 `pydantic` 或 `dataclasses` 做配置校验。

### 13. 日志非结构化，无法审计

**位置:** 全代码库

**问题:** 日志是纯文本，格式不统一，无法被日志分析系统解析。

```
2024-01-01 10:00:00 - INFO - 账户现金: $1000000.00
2024-01-01 10:00:01 - WARNING - ⚠️ 订单超时
```

**修复:** 使用 JSON 结构化日志：
```json
{"timestamp": "2024-01-01T10:00:00Z", "event": "account_snapshot", "cash": 1000000.00, "nav": 1000000.00}
{"timestamp": "2024-01-01T10:00:01Z", "event": "order_timeout", "symbol": "AAPL", "qty": 100, "side": "buy"}
```

### 14. 没有测试套件

**问题:** 0 个单元测试，0 个集成测试。

**后果:** 任何代码修改都可能破坏现有功能，无法安全迭代。

**修复:** 至少添加：
- `test_factors.py` - 验证 16 因子计算正确性
- `test_risk.py` - 验证风控触发逻辑
- `test_executor.py` - 用 mock 验证下单逻辑

### 15. Git 仓库中仍有历史泄露

**问题:** 即使删除了硬编码文件，Git 历史记录中仍然可以找到这些 Key。

**修复:** 使用 BFG Repo-Cleaner 或 `git filter-repo` 重写历史。

---

## 📋 修复优先级矩阵

| # | 缺陷 | 安全 | 资金风险 | 稳定性 | 修复难度 | 优先级 |
|---|------|------|----------|--------|----------|--------|
| 1 | API Key 泄露 | 🔴 | - | - | 低 | **P0** |
| 2 | int() 截断 | - | 🔴 | - | 低 | **P0** |
| 3 | 无订单幂等性 | - | 🔴 | - | 中 | **P0** |
| 4 | 裸 except | - | 🟠 | 🔴 | 中 | **P0** |
| 5 | 回测/实盘不一致 | - | 🔴 | - | 高 | **P0** |
| 6 | 线程竞态 | - | 🔴 | 🔴 | 中 | **P1** |
| 7 | 非 Atomic 调仓 | - | 🔴 | - | 高 | **P1** |
| 8 | 无流动性检查 | - | 🟠 | - | 中 | **P1** |
| 9 | float 资金 | - | 🟠 | - | 中 | **P1** |
| 10 | 无交易日历 | - | 🟡 | - | 低 | **P2** |
| 11 | 废弃 API | - | - | 🟡 | 低 | **P2** |
| 12 | 无配置验证 | - | - | 🟡 | 中 | **P2** |
| 13 | 非结构化日志 | - | - | 🟡 | 中 | **P2** |
| 14 | 无测试 | - | - | 🟡 | 高 | **P3** |
| 15 | Git 历史泄露 | 🔴 | - | - | 中 | **P0** |

---

## 🛠️ 建议修复路线图

### Phase 1: 安全止血（今天完成）
1. 在 Alpaca 后台删除已泄露的 API Key
2. 生成新的 Key，写入 `.env`，**不要提交到 Git**
3. 使用 `git filter-repo` 清除历史中的敏感信息
4. 强制推送重写后的仓库

### Phase 2: 核心逻辑修复（本周）
1. 统一使用 `generate_signals()` 桥接回测和实盘
2. 添加 `Decimal` 资金计算
3. 修复 `int()` 截断为小数股支持
4. 添加订单幂等性（client_order_id + 去重）

### Phase 3: 风控加固（下周）
1. 线程锁同步 `trading_halted` 状态
2. 添加调仓原子性保障（预检查或回滚）
3. 集成 `exchange_calendars` 处理交易日历
4. 添加流动性检查（quote size 校验）

### Phase 4: 工程化（后续）
1. 添加 pytest 测试套件
2. 日志改为 JSON 结构化
3. 配置层添加 pydantic 校验
4. 废弃 API 升级

---

*审查人: Qs*  
*方法: 静态代码分析 + 运行时检查 + 量化交易最佳实践对比*
