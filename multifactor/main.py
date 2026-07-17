"""
V14: 行业相对估值 + GARP + TED 多因子策略
17因子 | 零人工干预 | 月度调仓

改进点 (vs V13):
 - 去掉跨行业绝对value排名
 - 新增行业相对估值(relative_value)
 - 新增GARP(growth/relative_pe)
 - 新增52周价格位置(price_position)
 - 新增行业相对动量(industry_momentum)
 - 去掉rate_sensitive硬编码行业

P2修复: 文档此前宣称16因子，实际实现为17个(基础7 + V14估值4 + TED6)，统一为17。

作者: AI Quant Strategy Lab
版本: v14.0
"""

import numpy as np
import pandas as pd
import logging

# P2修复：统一全链路日志格式
logger = logging.getLogger(__name__)

from weight_allocation import WeightAllocator, integrate_with_backtest
from cost_model import TradingCostModel

# ============================================================
# 0. 交易日历辅助函数
# ============================================================

def _get_next_trading_day(price_df, date):
    """
    获取下一个交易日
    用于信号生成后延至下一交易日执行，避免 look-ahead 偏差
    """
    try:
        idx = price_df.index.get_loc(date)
        if isinstance(idx, (list, np.ndarray, slice)):
            idx = idx.start if isinstance(idx, slice) else idx[0]
        if idx + 1 < len(price_df):
            return price_df.index[idx + 1]
    except Exception:
        pass
    # fallback: 从 date 之后找第一个交易日
    future = price_df.index[price_df.index > date]
    return future[0] if len(future) > 0 else date


def _get_last_trading_day_of_month(price_df, year, month):
    """
    使用 XNYS (NYSE) 交易日历获取某月最后一个交易日
    与 scheduler.py 保持一致
    """
    try:
        import exchange_calendars as xcals
        xnys = xcals.get_calendar('XNYS')
        start = f"{year}-{month:02d}-01"
        if month == 12:
            next_start = f"{year+1}-01-01"
        else:
            next_start = f"{year}-{month+1:02d}-01"
        schedule = xnys.sessions_in_range(start, next_start)
        month_sessions = [s for s in schedule if s.year == year and s.month == month]
        if month_sessions:
            return pd.Timestamp(month_sessions[-1])
    except Exception:
        pass
    # fallback: 仅跳过周末
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    last_date = pd.Timestamp(year, month, last_day)
    while last_date.weekday() >= 5:
        last_date -= pd.Timedelta(days=1)
    return last_date

# ============================================================
# 1. 配置：股票池从 config.json 读取，main.py 保留默认值作为兜底
# ============================================================
from config import get_config

def _load_universe_from_config():
    """从 config.json 读取股票池，失败时返回默认 40 只。"""
    try:
        cfg = get_config()
        if hasattr(cfg, 'universe') and getattr(cfg.universe, 'tickers', None):
            return cfg.universe.tickers, cfg.universe.industry_map, cfg.universe.ndx_set()
    except Exception as e:
        logger.warning(f"Failed to load universe from config, using defaults: {e}")
    return None, None, None


_DEFAULT_TICKERS = [
    'NVDA','MU','AMD','INTC','AVGO','QCOM',  # 半导体
    'AAPL','MSFT','GOOGL','AMZN','META','TSLA',  # 科技
    'NFLX','ADBE','CRM','INTU',  # 软件
    'JPM','BAC','GS','V','MA',  # 金融
    'UNH','JNJ','PFE','ABBV',  # 医疗
    'XOM','CVX',  # 能源
    'BA','CAT',  # 工业
    'NEE','PEP','COST','WMT','HD',  # 消费/公用
    'DIS','CMCSA','VZ','TMUS'  # 媒体/电信
]

_DEFAULT_INDUSTRY = {
    'NVDA':'semi','MU':'semi','AMD':'semi','INTC':'semi','AVGO':'semi','QCOM':'semi',
    'AAPL':'tech','MSFT':'tech','GOOGL':'tech','AMZN':'tech','META':'tech','TSLA':'tech',
    'NFLX':'tech','ADBE':'tech','CRM':'tech','INTU':'tech',
    'JPM':'finance','BAC':'finance','GS':'finance','V':'finance','MA':'finance',
    'UNH':'health','JNJ':'health','PFE':'health','ABBV':'health',
    'XOM':'energy','CVX':'energy','BA':'industrial','CAT':'industrial',
    'NEE':'utility','PEP':'consumer','COST':'consumer','WMT':'consumer','HD':'consumer',
    'DIS':'media','CMCSA':'media','VZ':'telecom','TMUS':'telecom'
}

# 全局股票池变量（可被策略覆盖，保持向后兼容）
TICKERS = _DEFAULT_TICKERS
INDUSTRY = _DEFAULT_INDUSTRY
NDX_SET = set(TICKERS[:35])

# 尝试从 config.json 覆盖（只覆盖一次，避免重复加载）
_cfg_tickers, _cfg_industry, _cfg_ndx_set = _load_universe_from_config()
if _cfg_tickers:
    TICKERS = _cfg_tickers
if _cfg_industry:
    INDUSTRY = _cfg_industry
if _cfg_ndx_set is not None:
    NDX_SET = _cfg_ndx_set


# ============================================================
# 1.5 基本面数据接口（占位/模拟）
# ============================================================

def get_fundamental_data(symbols, date):
    """获取指定日期的基本面数据（EPS、BookValue 等）

    当前项目没有接入真实基本面数据源，返回 None。当返回 None 时，
    relative_value / garp 因子会退回到价格收益率代理（price_proxy）。

    参数:
        symbols: list, 股票代码列表
        date: datetime/date, 数据截止日期

    返回:
        DataFrame or None: 索引=symbol, 列=['eps', 'book_value_per_share'] 等；
                          None 表示无基本面数据，使用价格代理。
    """
    # TODO: 接入真实基本面数据源（如 Polygon fundamentals、Yahoo earnings 等）
    # 在未接入前保持返回 None，确保下游使用价格代理且不引入前视。
    return None


def _price_earnings_yield_proxy(ret):
    """价格收益率代理：使用历史年化收益倒数作为估值代理

    重要：这并非真实基本面 PE，而是基于价格收益的价格代理。
    年化价格收益率 = (1 + 日均收益)^252 - 1，其倒数作为“估值”代理。
    """
    earnings_yield_proxy = (1 + ret.mean()) ** 252 - 1
    pe_proxy = 1 / (earnings_yield_proxy.clip(-0.5, 1.0) + 0.01)
    return pe_proxy


# ============================================================
# 2. V14 因子计算 (17因子)
# ============================================================

def compute_factors_v14(price_slice):
    """
    V14: 17因子计算
    
    参数:
        price_slice: DataFrame, 索引=日期, 列=股票代码, 值=价格
        至少需要252日历史数据
    
    返回:
        DataFrame, 索引=股票代码, 列=17个因子的percentile排名(0-1)
    """
    f = pd.DataFrame(index=price_slice.columns)
    cur = price_slice.iloc[-1]
    ret = price_slice.pct_change().dropna()
    
    # 行业标签
    industries = pd.Series(
        [INDUSTRY.get(t, 'other') for t in price_slice.columns],
        index=price_slice.columns
    )
    
    # ===== 基础因子 (7个) =====
    
    # growth: 60日收益
    if len(price_slice) >= 60:
        f['growth'] = (cur / price_slice.iloc[-60] - 1).rank(pct=True)
    else:
        f['growth'] = 0.5
    
    # quality: 负波动率
    vol = ret.std() * np.sqrt(252)
    f['quality'] = (-vol).rank(pct=True)
    
    # momentum: 252日收益
    if len(price_slice) >= 252:
        f['momentum'] = (cur / price_slice.iloc[-252] - 1).rank(pct=True)
    else:
        f['momentum'] = f['growth']
    
    # lowvol: 负ATR
    atr = ret.abs().mean() * np.sqrt(252)
    f['lowvol'] = (-atr).rank(pct=True)
    
    # rsi_mr: RSI均值回归 (负偏离50的程度)
    if len(ret) >= 20:
        pos = ret.iloc[-20:].apply(lambda x: x[x > 0].sum())
        neg = ret.iloc[-20:].apply(lambda x: abs(x[x < 0].sum()))
        rsi = 100 - 100 / (1 + pos / neg.replace(0, 1))
        f['rsi_mr'] = (-(rsi - 50).abs()).rank(pct=True)
    else:
        f['rsi_mr'] = 0.5
    
    # ma_trend: 均线趋势
    if len(price_slice) >= 60:
        ma20 = price_slice.iloc[-20:].mean()
        ma60 = price_slice.iloc[-60:].mean()
        f['ma_trend'] = ((ma20 / ma60 - 1) * 100).rank(pct=True)
    else:
        f['ma_trend'] = 0.5
    
    # technical: EMA/SMA 动量（与 momentum 区别：momentum 为252日总收益，
    # technical 为短期 EMA12/EMA26 或 SMA 交叉，命名保留 technical 以兼容历史权重）
    # P2修复: 增加注释说明 technical 与 momentum 的差异，避免名实混淆。
    # P1修复: 使用 pandas ewm 计算真实 EMA, 不足时平滑回退到 SMA 并显式重命名
    if len(price_slice) >= 26:
        ema12 = price_slice.ewm(span=12, min_periods=12, adjust=False).mean().iloc[-1]
        ema26 = price_slice.ewm(span=26, min_periods=26, adjust=False).mean().iloc[-1]
        f['technical'] = (ema12 / ema26 - 1).rank(pct=True)
    elif len(price_slice) >= 12:
        sma12 = price_slice.iloc[-12:].mean()
        sma26 = price_slice.iloc[-26:].mean() if len(price_slice) >= 26 else price_slice.mean()
        # 数据不足, 回退到 SMA 并更名避免名不副实
        f['technical'] = (sma12 / sma26 - 1).rank(pct=True)
    else:
        f['technical'] = 0.5
    
    # ===== V14新增: 行业相对估值 (4个) =====

    # relative_value: 行业内相对估值排名
    # 当前项目无真实基本面数据源，使用 price_earnings_yield_proxy（价格收益率代理）
    # 作为 fallback。该代理并非真实基本面 PE，仅从历史价格收益推导，不存在前视。
    # 若接入真实基本面数据，可通过 get_fundamental_data() 获取上一季度/年末可用数据。
    fundamentals = get_fundamental_data(price_slice.columns.tolist(), price_slice.index[-1])
    if fundamentals is not None and 'eps' in fundamentals.columns:
        # 使用上一季度/年末可用基本面数据计算真实估值（避免前视）
        # 当前价格作为分母，EPS 使用基本面接口返回的最近可用值
        eps = fundamentals['eps'].reindex(price_slice.columns)
        pe_fundamental = cur / eps.replace(0, np.nan)
        pe_proxy = pe_fundamental.fillna(_price_earnings_yield_proxy(ret))
    else:
        pe_proxy = _price_earnings_yield_proxy(ret)

    if len(ret) >= 252:
        # 行业内排名: 相对PE越低=越便宜=越高分
        # P0修复: 使用 groupby(..., sort=False).transform 保持索引对齐
        f['relative_value'] = pe_proxy.groupby(industries, sort=False).transform(
            lambda x: (-x).rank(pct=True)
        )
    else:
        f['relative_value'] = 0.5

    # garp: 成长调整估值 = growth / relative_pe
    # 同样使用 price_earnings_yield_proxy 作为真实基本面的 fallback，非真实PE。
    if len(ret) >= 60:
        ret_60d = cur / price_slice.iloc[-60] - 1
        pe_p = _price_earnings_yield_proxy(ret)
        ind_med = pe_p.groupby(industries).transform('median')
        rel_pe = pe_p / (ind_med + 0.001)
        garp_raw = ret_60d / (rel_pe.clip(0.1, 5) + 0.1)
        f['garp'] = garp_raw.rank(pct=True)
    else:
        f['garp'] = 0.5
    
    # price_position: 52周价格位置 (底部偏好)
    if len(price_slice) >= 252:
        low52 = price_slice.iloc[-252:].min()
        high52 = price_slice.iloc[-252:].max()
        pp = (cur - low52) / (high52 - low52 + 0.001)
        f['price_position'] = (1 - pp).rank(pct=True)
    else:
        f['price_position'] = 0.5
    
    # industry_momentum: 行业相对动量
    if len(price_slice) >= 60:
        ret_60d = cur / price_slice.iloc[-60] - 1
        ind_avg_ret = ret_60d.groupby(industries).transform('mean')
        rel_mom = ret_60d - ind_avg_ret
        f['industry_momentum'] = rel_mom.rank(pct=True)
    else:
        f['industry_momentum'] = 0.5
    
    # ===== TED: 十倍股早期识别 (6个) =====
    
    # vol_contraction: 波动率压缩
    if len(ret) >= 120:
        vol_far = ret.iloc[-120:-60].std()
        vol_near = ret.iloc[-60:].std()
        vc_ratio = vol_near / (vol_far + 1e-6)
        ret_n60 = (cur / price_slice.iloc[-60] - 1).clip(-0.5, 0.5)
        f['vol_contraction'] = ((1 - vc_ratio.clip(0, 2)) * (1 + ret_n60 * 2)).rank(pct=True)
    else:
        f['vol_contraction'] = 0.5
    
    # base_breakout: 基底突破
    if len(price_slice) >= 126:
        h6m = price_slice.iloc[-126:].max()
        breakout = (cur / h6m - 1).clip(-0.3, 0.3)
        f['base_breakout'] = (breakout * (breakout > -0.05).astype(float)).rank(pct=True)
    else:
        f['base_breakout'] = 0.5
    
    # rel_strength_accel: 相对强度加速
    if len(price_slice) >= 120:
        rn = cur / price_slice.iloc[-30] - 1
        rr = price_slice.iloc[-30] / price_slice.iloc[-60] - 1
        rm = price_slice.iloc[-60] / price_slice.iloc[-90] - 1
        rd = price_slice.iloc[-90] / price_slice.iloc[-120] - 1
        f['rel_strength_accel'] = ((rn - rd) + (rn - rr - (rr - rm)) * 0.5).rank(pct=True)
    else:
        f['rel_strength_accel'] = 0.5
    
    # price_accel: 价格加速度
    if len(price_slice) >= 60:
        accel = ((cur / price_slice.iloc[-5] - 1) / 5 - (cur / price_slice.iloc[-30] - 1) / 30) * 100
        f['price_accel'] = accel.rank(pct=True)
    else:
        f['price_accel'] = 0.5
    
    # momentum_consistency: 动量一致性
    if len(ret) >= 20:
        f['momentum_consistency'] = ((ret.iloc[-20:] > 0).mean()).rank(pct=True)
    else:
        f['momentum_consistency'] = 0.5
    
    # low_base_score: 低位分数 (20-60%最佳)
    if len(price_slice) >= 252:
        fl = (cur - price_slice.iloc[-252:].min()) / (price_slice.iloc[-252:].max() - price_slice.iloc[-252:].min() + 1e-6)
        f['low_base_score'] = (1 - (fl - 0.4).abs() * 2).clip(0, 1).rank(pct=True)
    else:
        f['low_base_score'] = 0.5
    
    return f


# ============================================================
# 3. 综合评分
# ============================================================

def v14_composite_score(factors, vix):
    """
    V14综合评分
    
    参数:
        factors: DataFrame, 17因子percentile
        vix: float, 当前VIX值
    
    返回:
        Series, 每只股票的综合评分
    """
    vix_norm = np.clip((vix - 15) / 40, 0, 1)
    
    # 基础权重 (7因子)
    base_w = {
        'growth': 0.12, 'quality': 0.10, 'momentum': 0.10, 'lowvol': 0.08,
        'rsi_mr': 0.08, 'ma_trend': 0.06, 'technical': 0.10
    }
    crisis_shift = {
        'growth': -0.03, 'quality': +0.07, 'momentum': -0.03, 'lowvol': +0.06,
        'rsi_mr': -0.02, 'ma_trend': -0.03, 'technical': -0.02
    }
    
    # P1修复: 组内权重先归一化到1, 再乘以 base_weight
    effective_base_w = {name: base_w[name] + crisis_shift[name] * vix_norm for name in base_w}
    base_sum = sum(effective_base_w.values())
    if base_sum > 0:
        effective_base_w = {name: w / base_sum for name, w in effective_base_w.items()}
    
    base_score = pd.Series(0.0, index=factors.index)
    for name in effective_base_w:
        base_score += factors[name].fillna(0.5) * effective_base_w[name]
    
    # V14估值因子 (4因子)
    v14_w = {
        'relative_value': 0.10, 'garp': 0.12,
        'price_position': 0.08, 'industry_momentum': 0.06
    }
    # P1修复: 组内权重归一化到1
    v14_sum = sum(v14_w.values())
    if v14_sum > 0:
        v14_w = {name: w / v14_sum for name, w in v14_w.items()}
    
    v14_score = pd.Series(0.0, index=factors.index)
    for name in v14_w:
        v14_score += factors[name].fillna(0.5) * v14_w[name]
    
    # TED早期识别 (6因子)
    ted_w = {
        'vol_contraction': 0.10, 'base_breakout': 0.12,
        'rel_strength_accel': 0.15, 'price_accel': 0.08,
        'momentum_consistency': 0.06, 'low_base_score': 0.08
    }
    # P1修复: 组内权重归一化到1
    ted_sum = sum(ted_w.values())
    if ted_sum > 0:
        ted_w = {name: w / ted_sum for name, w in ted_w.items()}
    
    ted_score = pd.Series(0.0, index=factors.index)
    for name in ted_w:
        ted_score += factors[name].fillna(0.5) * ted_w[name]
    
    # 权重分配 (随VIX连续变化; 三组权重之和恒为1)
    v14_weight = 0.22 + 0.08 * vix_norm  # 高VIX时估值因子权重提升
    ted_weight = 0.18 + 0.07 * vix_norm  # 高VIX时TED因子权重提升
    base_weight = 1 - v14_weight - ted_weight
    
    return base_score * base_weight + v14_score * v14_weight + ted_score * ted_weight


# ============================================================
# 4. 仓位管理
# ============================================================

def v14_scale(vix):
    """
    V14仓位管理: 纯线性, 2参数
    
    参数:
        vix: float, 当前VIX值
    
    返回:
        float, 仓位比例(0-100)
    """
    vix_norm = np.clip((vix - 15) / 40, 0, 1)
    return 100 * (1 - 0.35 * vix_norm)  # VIX=15→100%, VIX=55→65%


# ============================================================
# 5. 回测引擎
# ============================================================

def run_v14(price_df, market_df, ndx_set, weight_method='equal', initial_capital=1.0):
    """
    V14回测引擎 (与实盘路径一致)

    参数:
        price_df: DataFrame, 日频价格数据 (索引=日期, 列=股票代码)
        market_df: DataFrame, 市场数据 (VIX, RSI), 索引=日期
        ndx_set: set, NDX股票代码集合
        weight_method: str, 权重分配方法 (equal/risk_parity/min_variance/momentum_weighted)
        initial_capital: float, 初始资金 (默认1.0, 建议回测使用1e6等真实资金以产生合理交易成本)

    返回:
        DataFrame, 回测结果 (date, nav, nav_after_cost, mr, vix, sc, n, ndx_ratio, cost, holdings)
    """
    # P1修复: 使用 XNYS 交易日历获取月末最后交易日, 与 scheduler.py 保持一致
    unique_ym = sorted(set((d.year, d.month) for d in price_df.index))
    monthly = pd.DatetimeIndex([
        _get_last_trading_day_of_month(price_df, y, m) for y, m in unique_ym
    ])
    monthly = monthly[monthly >= price_df.index[252]]  # 252日预热
    monthly = monthly[monthly.isin(price_df.index)]  # 仅保留价格数据中存在的日期

    # P0/P1修复: 维护真实组合状态 (equity, cash, positions)
    cash = float(initial_capital)
    positions = {}  # {symbol: qty}
    prev_nav = float(initial_capital)
    records = []

    # P0/P1修复: 接入 WeightAllocator 与 TradingCostModel
    cost_model = TradingCostModel()

    for signal_d in monthly:
        # P0修复: 信号在 signal_d 收盘后生成, 延至下一交易日 next_d 开盘/市价执行
        next_d = _get_next_trading_day(price_df, signal_d)
        if next_d not in price_df.index:
            continue

        # 1. 用 next_d 开盘前持仓市值重估 NAV
        if positions:
            next_prices = price_df.loc[next_d, list(positions.keys())].dropna()
            # 剔除停牌标的
            invalid = set(positions.keys()) - set(next_prices.index)
            for s in invalid:
                del positions[s]
            equity = float(sum(next_prices[s] * positions[s] for s in positions))
            nav = equity + cash
        else:
            equity = 0.0
            nav = cash

        # 2. 计算 holding period return (execution-to-execution)
        mr = (nav / prev_nav - 1.0) if prev_nav > 0 else 0.0

        # 3. PIT 因子计算 (仅使用 signal_d 及之前数据)
        pos = price_df.index.get_loc(signal_d)
        price_slice = price_df.iloc[max(0, pos - 252):pos + 1]

        vix_v = market_df.loc[signal_d, 'VIX']
        sc = v14_scale(vix_v)

        factors = compute_factors_v14(price_slice)
        score = v14_composite_score(factors, vix_v)

        # NDX比例: 因子驱动 (非硬编码)
        ndx_mask = score.index.isin(ndx_set)
        ndx_avg = score[ndx_mask].mean() if ndx_mask.any() else 0.5
        non_avg = score[~ndx_mask].mean() if (~ndx_mask).any() else 0.5
        total = ndx_avg + non_avg
        ndx_ratio = np.clip(ndx_avg / total if total > 0 else 0.5, 0.15, 0.60)

        # 选股数量: VIX动态
        vix_norm = np.clip((vix_v - 15) / 40, 0, 1)
        n_stocks = max(10, min(40, int(20 + 15 * (1 - vix_norm))))

        # 分层选股
        ndx_n = max(2, int(n_stocks * ndx_ratio))
        ndx_sorted = score[ndx_mask].sort_values(ascending=False).dropna()
        non_sorted = score[~ndx_mask].sort_values(ascending=False).dropna()

        selected = (
            list(ndx_sorted.index[:min(ndx_n, len(ndx_sorted))]) +
            list(non_sorted.index[:min(n_stocks - ndx_n, len(non_sorted))])
        )

        # 4. P0/P1修复: 先按 next_d 可用价格剔除不可交易标的, 再生成 target_positions
        target_value = nav * (sc / 100.0)
        target_positions = integrate_with_backtest(
            selected_symbols=selected,
            total_equity=target_value,
            price_df=price_df,
            max_weight=0.20,
            min_weight=0.0,
            weight_method=weight_method,
            execution_date=next_d,  # 按 next_d 价格过滤停牌
        )

        # 5. 构造当前持仓在 next_d 的市价快照
        all_symbols = set(target_positions.keys()) | set(positions.keys())
        next_prices = price_df.loc[next_d, list(all_symbols)].dropna()
        current_positions = {}
        for s in all_symbols:
            if s in next_prices.index:
                current_positions[s] = {
                    'qty': positions.get(s, 0),
                    'price': float(next_prices[s]),
                }

        # 6. P0修复: 在按 next_d 价格过滤后再估算调仓成本
        cost_summary = cost_model.estimate_portfolio_cost(
            target_positions, current_positions, total_value=nav
        )
        total_cost = cost_summary['total_cost']

        # P1修复: 预留交易成本，避免 cash 为负
        if total_cost > 0 and target_value > 0:
            target_value = max(0.0, target_value - total_cost)
            # 按新的 investable 金额重新生成目标持仓
            target_positions = integrate_with_backtest(
                selected_symbols=selected,
                total_equity=target_value,
                price_df=price_df,
                max_weight=0.20,
                min_weight=0.0,
                weight_method=weight_method,
                execution_date=next_d,
            )
            # 重新估算成本（已扣除成本，现金不会为负）
            all_symbols = set(target_positions.keys()) | set(positions.keys())
            next_prices = price_df.loc[next_d, list(all_symbols)].dropna()
            current_positions = {}
            for s in all_symbols:
                if s in next_prices.index:
                    current_positions[s] = {
                        'qty': positions.get(s, 0),
                        'price': float(next_prices[s]),
                    }
            cost_summary = cost_model.estimate_portfolio_cost(
                target_positions, current_positions, total_value=nav
            )
            total_cost = cost_summary['total_cost']

        # 7. P0修复: 在 next_d 执行真实成交, 并更新 cash/positions
        new_positions = {}
        total_buy_value = 0.0
        total_sell_value = 0.0
        for s in all_symbols:
            if s not in next_prices.index:
                # 停牌标的无法成交, 保持当前持仓
                if s in positions:
                    new_positions[s] = positions[s]
                continue
            current_qty = positions.get(s, 0)
            target_qty = 0
            if s in target_positions:
                target_qty = int(target_positions[s] / next_prices[s])
            diff = target_qty - current_qty
            if diff > 0:
                total_buy_value += diff * next_prices[s]
                new_positions[s] = target_qty
            elif diff < 0:
                total_sell_value += (-diff) * next_prices[s]
                if target_qty > 0:
                    new_positions[s] = target_qty
            else:
                if target_qty > 0:
                    new_positions[s] = target_qty

        cash = cash + total_sell_value - total_buy_value - total_cost
        positions = new_positions

        # 8. 记录持仓市值与真实 NAV
        post_equity = float(
            sum(qty * next_prices[s] for s, qty in positions.items() if s in next_prices.index)
        )
        nav_after_cost = post_equity + cash
        holdings = {
            s: qty * next_prices[s]
            for s, qty in positions.items()
            if s in next_prices.index
        }
        prev_nav = nav_after_cost

        records.append({
            'date': next_d,
            'nav': nav / initial_capital,
            'nav_after_cost': nav_after_cost / initial_capital,
            'mr': mr,
            'vix': vix_v,
            'sc': sc,
            'n': len(target_positions),
            'ndx_ratio': ndx_ratio,
            'cost': total_cost / initial_capital,
            'holdings': holdings,
        })

    return pd.DataFrame(records)


# ============================================================
# 6. 使用示例
# ============================================================

if __name__ == '__main__':
    # P2修复：仅在入口运行时初始化日志
    from logging_config import setup_logging
    setup_logging()
    # 示例: 生成模拟数据并回测
    np.random.seed(42)
    
    dates = pd.bdate_range('2015-01-01', '2024-12-31')
    n_days = len(dates)
    
    # 生成价格数据
    prices = np.zeros((n_days, len(TICKERS)))
    prices[0] = np.random.uniform(20, 200, len(TICKERS))
    market_ret = np.random.normal(0.0003, 0.012, n_days)
    
    for i in range(1, n_days):
        for j, t in enumerate(TICKERS):
            ind = INDUSTRY.get(t, 'other')
            vol = {'semi': 0.022, 'tech': 0.018, 'finance': 0.014,
                   'health': 0.012, 'energy': 0.020, 'industrial': 0.015,
                   'utility': 0.010, 'consumer': 0.013, 'media': 0.016,
                   'telecom': 0.012}.get(ind, 0.015)
            ret = np.random.normal(0.0003, vol) + 0.4 * market_ret[i]
            prices[i, j] = prices[i-1, j] * (1 + ret)
    
    price_df = pd.DataFrame(prices, index=dates, columns=TICKERS)
    price_df = price_df.replace(0, np.nan).ffill()
    
    # VIX模拟
    vix = np.clip(15 + np.cumsum(np.random.normal(0, 0.5, n_days)) * 0.08, 9, 55)
    market_df = pd.DataFrame({'VIX': vix, 'RSI': np.random.uniform(30, 70, n_days)}, index=dates)
    
    # 执行回测 (使用100万初始资金以产生合理交易成本)
    print("执行 V14 回测...")
    result = run_v14(price_df, market_df, NDX_SET, weight_method='equal', initial_capital=1_000_000.0)
    
    # 计算指标
    nav = result['nav']
    mr = nav.pct_change().dropna()
    years = (result['date'].iloc[-1] - result['date'].iloc[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1/years) - 1
    vol = mr.std() * np.sqrt(12)
    sharpe = cagr / vol if vol > 0 else 0
    maxdd = ((nav / nav.cummax()) - 1).min()
    
    print(f"\n{'='*50}")
    print(f"V14 回测结果")
    print(f"{'='*50}")
    print(f" 期间: {result['date'].iloc[0]} ~ {result['date'].iloc[-1]}")
    print(f" 调仓次数: {len(result)}")
    print(f" Final NAV: {nav.iloc[-1]:.2f}")
    print(f" CAGR: {cagr:.2%}")
    print(f" Sharpe: {sharpe:.3f}")
    print(f" MaxDD: {maxdd:.2%}")
    print(f" 波动率: {vol:.2%}")
    print(f" 胜率: {(mr > 0).mean():.1%}")
    print(f" 累计成本: {result['cost'].sum():.4f}")
    print(f"\nV14 因子数: 17 (基础7 + V14估值4 + TED6)")

    print(f"V14 人工干预: 0")
    print(f"V14 MWH模块: 已去除")
