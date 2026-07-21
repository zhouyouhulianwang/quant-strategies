# 多策略组合架构审查报告

**审查对象**: `strategies/portfolio.py`、`run_multi_strategy.py` 及其依赖（子策略、`weight_allocation.py`、`main.run_v14`、`quantconnect_data.py`、`risk_monitor.py`）
**审查日期**: 2026-07-21

---

## 一、架构总览

- `StrategyPortfolio` 持有 N 个 `(name, strategy, weight)` 三元组，权重归一化到和为 1。
- 回测：`run_individual_backtests()` 串行调用每个子策略的 `run_backtest()`，再把各 NAV 曲线按权重加权求和。
- 实盘：`generate_signals(total_value)` 按 `weight * total_value` 给每个子策略分配资金 → 各子策略独立选股+约束 → 简单加总同名标的 → 组合级行业约束 + 波动率 overlay。
- 子策略（Momentum/Value/Quality/Growth）结构高度同构：`_prepare_data()`（QC 数据）→ `compute_factors_v14()` → 自有 `_score()` → `WeightAllocator` → 行业约束 + vol target。

整体设计方向合理（统一因子框架、组合层 overlay、优雅降级），但存在 **多处正确性 bug 和严重的重复计算问题**。

---

## 二、严重问题（P0/P1，正确性风险）

### P0-1. 组合回测 NAV 曲线口径不一致 —— 加权聚合结果失真（核心 bug）

`portfolio.py::run_backtest` 把各子策略 NAV 曲线加权求和，但两条曲线的口径完全不同：

- **V14 (`main.run_v14`)**: `nav_after_cost` 已 **除以 initial_capital 归一化**（起点 = 1.0），且记录在每个 rebalance 日。
- **Momentum/Value/Quality/Growth (`_simple_backtest`)**: `nav` 是 **绝对美元金额**（起点 = 1,000,000），且 NAV 是 **调仓前重估** 的。

后果：`0.3 * 1.0 + 0.7 * 1_000_000` 这样的混合加权，组合 NAV 完全被未归一化的策略主导，V14 的贡献被压到 ~0。**组合回测绩效数字是错的。**

另外 `nav` 在 Momentum 系里记录的是"调仓前"的 NAV（用 next_d 价格重估旧持仓后再记录），首次记录时 `positions` 为空所以 nav=1M，基准尚可，但严格说这是 next_d 开盘前口径，与 V14 的 post-cost 口径仍有细微错位。

**修复**：聚合前统一归一化：

```python
# portfolio.py::run_backtest, nav_curves 构建处
nav_col = 'nav_after_cost' if 'nav_after_cost' in result.columns else 'nav'
df = result[['date', nav_col]].copy()
s = df.set_index(pd.to_datetime(df['date']))[nav_col]
s = s[~s.index.duplicated(keep='last')]
s = s / s.iloc[0]          # ← 统一归一化到 1.0 起点
nav_curves.append(s.rename(name))
```

更彻底的做法：在 `base.py` 中定义回测结果契约（`date` + 归一化 `nav_after_cost`），让 4 个同构子策略直接复用 `main.run_v14` 引擎（见优化建议 O-1）。

### P0-2. 子策略月度回测的"现金全额重置"逻辑错误

Momentum/Value/Quality/Growth 的 `run_backtest`：

```python
cash = nav
positions = {}
for s, v in signals.items():
    qty = int(v / prices[s])
    ...
```

- 每次调仓**强制清仓重建**，无视新旧持仓重叠 → 换手率高估、且**完全没有交易成本**（无佣金/滑点），与 V14 的真实成本模型口径不一致，导致子策略绩效系统性偏乐观，权重分配决策被误导。
- `total_target <= nav` 不满足时（如 vol target 压缩后恰好 > nav 的边角情况，或信号总金额因 int() 取整后异常）**整月不交易且无日志**。

**修复**：见 O-1 —— 让子策略复用 `main.run_v14`，或至少引入增量调仓 + `cost_model` 成本。

### P0-3. `generate_signals` 在 live 模式下重复下载 5 次相同数据

`portfolio.generate_signals()` 不传 `price_df` 给子策略 → 每个子策略 `generate_signals()` 内部各自调用 `_prepare_data(now-400d, now)` → **同一批 TICKERS 的 QC/Yahoo 数据被加载 5 次**（磁盘缓存能挡住一部分，但仍有 5 次缓存校验 + DataFrame 拼接 + 因子计算 `compute_factors_v14` ×5，因子结果 100% 相同）。

**修复**（组合层加载一次、注入各策略）：

```python
# portfolio.py::generate_signals 开头
if live_mode or True:
    price_df, market_df = self._load_shared_data()   # 调 prepare_backtest_data_qc 一次
    vix = float(market_df['VIX'].iloc[-1]) if market_df is not None else None
...
signals = strategy.generate_signals(price_df=price_df, vix=vix, capital=alloc, live_mode=live_mode)
```

顺带修复了"各策略数据快照时刻可能不一致"的隐患（盘中运行时 5 次下载可能跨越 EOD 数据更新点）。

### P1-4. 行业约束在组合层面是"半失效"状态

`portfolio.generate_signals` 中：

```python
weights = apply_sector_constraints(weights, INDUSTRY, max_sector_pct=0.30)
```

但 `INDUSTRY` 来自 `from main import INDUSTRY`，若 `main.py` 导入失败则 `INDUSTRY = {}`，`apply_sector_constraints` 内 `sectors.get(s, 'other')` 把**所有股票归入 'other' 一个行业** → 组合会被压到 30% 单行业上限（即全组合砍到 30%）或触发 redistribute 死循环式迭代。**静默失败，无任何告警。**

此外组合层 `max_sector_pct=0.30` 是**硬编码**，没走 `config.risk.max_sector_pct`；子策略内部也各自做了一次 30% 行业约束，同一约束被执行 2 次（子策略内 1 次 + 组合层 1 次），第二次是多余的（子策略交集加总后行业占比只可能更分散，除非多策略集中押同一行业——那时组合层才真正有用，但硬编码值使其与配置脱节）。

**修复**：
- `INDUSTRY` 为空时 `logger.warning` 并跳过约束，而不是静默套 30% 到 'other'；
- 组合层约束参数从 `self.config.risk.max_sector_pct` 读取；
- 子策略内的行业约束可保留（单策略层面控制），但组合层应用配置值。

### P1-5. 波动率 overlay 被 `_get_common_price_df()` 永久禁用

```python
def _get_common_price_df(self):
    ...
    return None   # 两条路径都返回 None
```

`apply_volatility_target` 的组合级 overlay **从未执行**。若采纳 O-3（共享 price_df），此问题自然解决：直接把共享的 `price_df` 传入。

### P1-6. 组合级风控覆盖不足

- `run_live_rebalance` 中 `check_concentration_risk(positions, portfolio_value)` 检查的是**当前持仓**（调仓前），而非 **target_positions**（调仓后）。目标持仓本身违反集中度时无法提前拦截。
- 回测路径 `enable_risk_monitor` 完全没用到（RiskMonitor 只在 live 路径出现），组合回测没有回撤熔断/杠杆检查。
- `_build_risk_kwargs` 中 `hasattr(risk_config, 'max_intraday_dd') and not hasattr(risk_config, 'daily_loss_limit')` 逻辑：config 的 RiskConfig 两个字段都没有 `daily_loss_limit`（用的是 `max_intraday_dd`），getattr 链先给 `daily_loss_limit` 设了默认值 0.03，然后才检查 —— 实际上 `not hasattr(...)` 对 pydantic 模型恒为 False（字段都定义了），所以 `max_intraday_dd` **永远不会生效**，配置里的日内回撤限制被静默忽略。

**修复**：

```python
# _build_risk_kwargs
daily_loss = getattr(risk_config, 'daily_loss_limit', None)
if daily_loss is None:
    daily_loss = getattr(risk_config, 'max_intraday_dd', 0.03)
kwargs['daily_loss_limit'] = daily_loss
```

并在执行前对 target_positions 做预检：

```python
# run_live_rebalance, 执行前
if self.risk_monitor:
    ok = self.risk_monitor.check_concentration_risk(
        [{'symbol': s, 'market_value': v} for s, v in target_positions.items()],
        portfolio_value)
    if self.risk_monitor.trading_halted: return
```

### P1-7. `generate_signals` 的 TypeError 兜底会吞掉真实 bug

```python
except TypeError as e:
    # 兼容旧版 generate_signals 不接受 capital 参数
    signals = strategy.generate_signals(live_mode=live_mode)
```

如果子策略 `generate_signals` **内部**抛 TypeError（例如 None 参与算术），会被误判为"旧签名"，再无 capital 地调一次（可能再次数据下载），掩盖原始异常。所有 5 个现有策略都已接受 `capital`，此兼容层应删除，或至少 `inspect.signature` 判断而不是靠异常捕获。

---

## 三、数据加载 / 重复计算问题

| 问题 | 位置 | 影响 |
|---|---|---|
| 5 策略各自 `_prepare_data` 加载同一 TICKERS 全集 | portfolio live 路径 | 5× IO/缓存校验/拼接（P0-3） |
| `compute_factors_v14` 被调用 5 次（输入完全相同） | 各子策略 generate_signals | CPU 重复，因子计算是热点 |
| `get_signals(date)` 又独立加载一次数据 | 各子策略 | 组合回测若改用 get_signals 会放大 N 倍 |
| `run_backtest` 各策略重复加载全历史 | portfolio backtest | 4×~5× 相同 price_df 下载（缓存缓解但仍有重复校验） |

**建议**: 引入共享数据上下文：

```python
class DataContext:
    def __init__(self, tickers, start, end):
        self.price_df, self.market_df = prepare_backtest_data_qc(tickers, start, end)
        self._factor_cache = {}   # key: asof_date -> factors df
    def factors_at(self, date):
        if date not in self._factor_cache:
            self._factor_cache[date] = compute_factors_v14(self.price_df.loc[:date].iloc[-252:])
        return self._factor_cache[date]
```

组合回测时 `DataContext` 加载一次，5 个策略共用；因子按 rebalance 日缓存，5 策略 × M 个月的因子计算从 5M 次降到 M 次。

---

## 四、NAV 曲线对齐问题

`run_backtest` 聚合用 `pd.concat(nav_curves, axis=1).ffill().dropna()`：

1. **`dropna()` 砍掉头部交集之前的所有行** —— 各策略回测起点都是各自 price_df 的第 252 个交易日之后，理论上接近，但 QC 数据可用性差异（退市股剔除、缓存覆盖差异）会导致起点错位；错位部分被静默丢弃，回测期悄悄缩短。应至少 log 各曲线首尾日期与交集区间。
2. **调仓频率不一致**：V14 用 XNYS 月末最后交易日，Momentum 系用"每月最后一个有数据的日期"，多数情况一致，但遇到月末数据缺口会错位 1 天 → ffill 用陈旧值参与当日加权。影响小，但归一化修复后建议对权重加和做断言：`aligned.notna().all(axis=1)`。
3. `dropna()` 之后，若某策略回测失败返回空 df，该策略权重实际被剔除，但 `weights_series` 是按 `aligned.columns` 过滤的，**剩余权重没有重新归一化到 1** —— 组合 NAV 缩水。应 `weights_series /= weights_series.sum()` 或显式报错。

---

## 五、CLI / 流程问题（run_multi_strategy.py）

1. **`--individual` + `--backtest` 同时给定时 `--backtest` 先执行组合回测（内部已跑过 individual），随后又跑一次 `run_individual_backtests` → 全部回测执行两遍**。main() 中两个 `if` 是顺序判断而非互斥分支。`--individual` 与 `--backtest` 在 argparse 里已互斥（同一 mutually_exclusive_group），所以目前不会触发，但若有人改动 group 就会双跑。建议加防御性注释或 elif。
2. **策略实例化用 if/elif 链**（5 个分支），新增策略要改两处。建议注册表：

```python
STRATEGY_REGISTRY = {
    'MultiFactorStrategy': MultiFactorStrategy,
    'MomentumStrategy': MomentumStrategy,
    'ValueStrategy': ValueStrategy,
    'QualityStrategy': QualityStrategy,
    'GrowthStrategy': GrowthStrategy,
}
cls = STRATEGY_REGISTRY.get(class_name)
if cls is None: raise ValueError(...)
strategies.append((name, cls(**params), weight))
```

3. **`use_real_data` 决策分散**：`--real-data/--no-real-data` 与 backtest 默认 True、paper 默认 False 的规则藏在 main() 中段，且 paper/live 默认 mock 数据对新手是个坑（纸面交易用假数据生成信号）。建议 paper 模式默认 True 或在日志里显著提示。
4. `build_portfolio` 注释说"后续可通过 config.json 的 strategies 字段配置"，但 `config.py` 的 `V14StrategyConfig` 没有 `strategies` 字段 → `hasattr(config, 'strategies')` 恒 False，**配置化路径是死代码**。要么补 schema，要么删注释。
5. `--enable-risk-monitor` 设 `default=True` 又是 `store_true`，加上 `--disable-risk-monitor` 双开关，逻辑正确但啰嗦；用 `argparse.BooleanOptionalAction`（Py3.9+）一行解决。

---

## 六、其他中低优先级问题

- **`get_status()` 返回的 positions 是 Alpaca 原始对象列表**，logger.info 直接打印可能不可序列化/超长；且 `status` 命令在 mock 模式下仍会尝试 `executor.get_account()`（executor 为 None 时跳过，OK）。
- `run_live_rebalance` 里 `self.executor.start_rebalance_session() if hasattr(...) else None` —— 表达式语句风格，建议正常 if。
- **`generate_signals` 中聚合后 `normalize_target_positions(target_positions, total_value)` 只在超配时缩放**；若各子策略自身用了 vol target 压缩（如都压到 80%），组合总仓位会系统性 < total_value，剩余资金闲置且无提示。应 log 资金利用率，或可选地 scale-up 到目标敞口。
- 同名标的加总后，**单标的集中度上限（max_position_pct）在组合层未检查**——两个策略各买 15% AAPL，加总 30% 直接超限。组合层应加 per-symbol cap。
- `_print_portfolio_performance` 组合层面用推断的 `periods_per_year`，但子策略绩效打印里硬编码 `np.sqrt(252)`（月度数据用 252 年化 → 波动率/Sharpe 严重失真）。统一用同一推断函数。
- 子策略 `_generate_mock_data` 各自实现（momentum seed=43），重复代码 ~30 行 ×4；抽到共享 helper。
- `apply_sector_constraints` 本身实现正确（迭代 redistribute），但当某行业只有 1 只股票时，超额权重会全部压给这一只 → 可能变相制造单票集中；与 per-symbol cap 联动缺失。

---

## 七、优化建议汇总（按优先级）

| # | 优先级 | 建议 | 预期收益 |
|---|---|---|---|
| O-0 | P0 | 聚合前归一化所有 NAV 曲线（P0-1 一行修复） | 组合回测绩效从"错误"变"可用" |
| O-1 | P0 | 4 个同构子策略的回测引擎替换为 `main.run_v14`（或抽 `BaseFactorStrategy` 共享回测循环 + 真实成本） | 消除 P0-2；子策略绩效可比；代码 -400 行 |
| O-2 | P0 | 组合层加载一次 price_df/market_df 并注入所有子策略（P0-3） | live 数据加载 5×→1×；消除快照不一致 |
| O-3 | P1 | 共享 `DataContext` + 因子按日缓存 | 回测因子计算 5M→M 次，5 倍加速 |
| O-4 | P1 | 组合层行业/单票约束参数走 config；INDUSTRY 为空时告警跳过；修复 daily_loss_limit 取值链 | 风控配置真正生效 |
| O-5 | P1 | 启用组合级 vol target（用共享 price_df）；对 target_positions 做执行前风控预检 | 风控覆盖调仓后状态 |
| O-6 | P1 | 修复权重未重归一化 + dropna 静默缩窗；打印各曲线日期范围 | 聚合健壮性 |
| O-7 | P2 | 策略类注册表、删除 TypeError 兜底、删除死代码 strategies 配置注释 | 可维护性 |
| O-8 | P2 | 统一绩效年化函数；资金利用率日志；单票组合级 cap | 报告准确性与资金效率 |

### 关键代码片段（O-1 重构方向）

```python
# strategies/factor_base.py (新增)
class FactorSubStrategy(BaseStrategy):
    """共享数据 + 共享回测引擎的子策略基类，子类只需实现 _score()"""
    factor_weight_method = 'equal'
    def _score(self, factors): raise NotImplementedError

    def run_backtest(self, start_date=None, end_date=None, data_ctx=None, **kw):
        ctx = data_ctx or DataContext(TICKERS, start_date, end_date)
        return run_v14(ctx.price_df, ctx.market_df, NDX_SET,
                       score_fn=self._score,          # run_v14 需加 score_fn 参数
                       weight_method=self.factor_weight_method,
                       initial_capital=1_000_000.0)
```

`main.run_v14` 目前内嵌 `v14_composite_score`，加一个可选 `score_fn=None` 注入点即可被全部子策略复用，同时继承 XNYS 日历、真实成本、vol 滑点模型。

---

## 八、结论

架构骨架（组合层 overlay + 子策略独立信号 + 优雅降级）是合理的，但当前实现中 **组合回测的绩效数字因 NAV 口径混合而不可信（P0-1）**，子策略回测无成本且全仓重置（P0-2），live 路径重复加载数据 5 次（P0-3）。建议按 O-0 → O-1 → O-2 顺序修复：O-0 是一行热修，O-1/O-2 是结构性重构，完成后组合层与子策略层的回测-实盘一致性、性能、可维护性都会显著提升。
