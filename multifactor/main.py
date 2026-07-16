"""
V14: 行业相对估值 + GARP + TED 多因子策略
16因子 | 零人工干预 | 月度调仓

改进点 (vs V13):
 - 去掉跨行业绝对value排名
 - 新增行业相对估值(relative_value)
 - 新增GARP(growth/relative_pe)
 - 新增52周价格位置(price_position)
 - 新增行业相对动量(industry_momentum)
 - 去掉rate_sensitive硬编码行业

作者: AI Quant Strategy Lab
版本: v14.0
"""

import numpy as np
import pandas as pd

# ============================================================
# 1. 配置
# ============================================================

# 股票池 (示例: 40只)
TICKERS = [
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

# 行业映射
INDUSTRY = {
    'NVDA':'semi','MU':'semi','AMD':'semi','INTC':'semi','AVGO':'semi','QCOM':'semi',
    'AAPL':'tech','MSFT':'tech','GOOGL':'tech','AMZN':'tech','META':'tech','TSLA':'tech',
    'NFLX':'tech','ADBE':'tech','CRM':'tech','INTU':'tech',
    'JPM':'finance','BAC':'finance','GS':'finance','V':'finance','MA':'finance',
    'UNH':'health','JNJ':'health','PFE':'health','ABBV':'health',
    'XOM':'energy','CVX':'energy','BA':'industrial','CAT':'industrial',
    'NEE':'utility','PEP':'consumer','COST':'consumer','WMT':'consumer','HD':'consumer',
    'DIS':'media','CMCSA':'media','VZ':'telecom','TMUS':'telecom'
}

# NDX集合 (前35只)
NDX_SET = set(TICKERS[:35])


# ============================================================
# 2. V14 因子计算 (16因子)
# ============================================================

def compute_factors_v14(price_slice):
    """
    V14: 16因子计算
    
    参数:
        price_slice: DataFrame, 索引=日期, 列=股票代码, 值=价格
        至少需要252日历史数据
    
    返回:
        DataFrame, 索引=股票代码, 列=16个因子的percentile排名(0-1)
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
    
    # technical: EMA动量
    if len(price_slice) >= 26:
        ema12 = price_slice.iloc[-12:].mean()
        ema26 = price_slice.iloc[-26:].mean()
        f['technical'] = (ema12 / ema26 - 1).rank(pct=True)
    else:
        f['technical'] = 0.5
    
    # ===== V14新增: 行业相对估值 (4个) =====
    
    # relative_value: 行业内相对PE排名
    # PE代理 = 1/(年化收益+eps), 在行业内排名
    if len(ret) >= 252:
        ret_annual = (1 + ret.mean()) ** 252 - 1
        pe_proxy = 1 / (ret_annual.clip(-0.5, 1.0) + 0.01)
        # 行业内排名: 相对PE越低=越便宜=越高分
        f['relative_value'] = pe_proxy.groupby(industries).apply(
            lambda x: (-x).rank(pct=True)
        ).values
    else:
        f['relative_value'] = 0.5
    
    # garp: 成长调整估值 = growth / relative_pe
    if len(ret) >= 60:
        ret_60d = cur / price_slice.iloc[-60] - 1
        ret_annual_garp = (1 + ret.mean()) ** 252 - 1
        pe_p = 1 / (ret_annual_garp.clip(-0.5, 1.0) + 0.01)
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
        factors: DataFrame, 16因子percentile
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
    
    base_score = pd.Series(0.0, index=factors.index)
    for name in base_w:
        w = base_w[name] + crisis_shift[name] * vix_norm
        base_score += factors[name].fillna(0.5) * w
    
    # V14估值因子 (4因子)
    v14_w = {
        'relative_value': 0.10, 'garp': 0.12,
        'price_position': 0.08, 'industry_momentum': 0.06
    }
    v14_score = pd.Series(0.0, index=factors.index)
    for name in v14_w:
        v14_score += factors[name].fillna(0.5) * v14_w[name]
    
    # TED早期识别 (6因子)
    ted_w = {
        'vol_contraction': 0.10, 'base_breakout': 0.12,
        'rel_strength_accel': 0.15, 'price_accel': 0.08,
        'momentum_consistency': 0.06, 'low_base_score': 0.08
    }
    ted_score = pd.Series(0.0, index=factors.index)
    for name in ted_w:
        ted_score += factors[name].fillna(0.5) * ted_w[name]
    
    # 权重分配 (随VIX连续变化)
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

def run_v14(price_df, market_df, ndx_set):
    """
    V14回测引擎
    
    参数:
        price_df: DataFrame, 日频价格数据 (索引=日期, 列=股票代码)
        market_df: DataFrame, 市场数据 (VIX, RSI), 索引=日期
        ndx_set: set, NDX股票代码集合
    
    返回:
        DataFrame, 回测结果 (date, nav, sc, n, ndx_ratio)
    """
    # 月末调仓日
    monthly = price_df.groupby([price_df.index.year, price_df.index.month]).tail(1).index
    monthly = monthly[monthly >= price_df.index[252]]  # 252日预热
    
    nav = 1.0
    prev_holdings = []
    records = []
    
    for i in range(1, len(monthly)):
        prev_d, curr_d = monthly[i-1], monthly[i]
        vix_v = market_df.loc[prev_d, 'VIX']
        sc = v14_scale(vix_v)
        
        # PIT因子计算 (只用prev_d及之前数据)
        pos = price_df.index.get_loc(prev_d)
        price_slice = price_df.iloc[max(0, pos - 252):pos + 1]
        
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
        
        # 收益计算
        if prev_holdings:
            p_start = price_df.loc[prev_d, prev_holdings].values
            p_end = price_df.loc[curr_d, prev_holdings].values
            mr = np.mean(p_end / p_start - 1) * (sc / 100)
        else:
            mr = 0
        
        nav *= (1 + mr)
        
        records.append({
            'date': curr_d,
            'nav': nav,
            'mr': mr,
            'vix': vix_v,
            'sc': sc,
            'n': len(selected),
            'ndx_ratio': ndx_ratio,
        })
        prev_holdings = selected
    
    return pd.DataFrame(records)


# ============================================================
# 6. 使用示例
# ============================================================

if __name__ == '__main__':
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
    
    # 执行回测
    print("执行 V14 回测...")
    result = run_v14(price_df, market_df, NDX_SET)
    
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
    print(f"\nV14 因子数: 16 (基础7 + V14估值4 + TED6)")
    print(f"V14 人工干预: 0")
    print(f"V14 MWH模块: 已去除")
