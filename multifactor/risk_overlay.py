"""
风险覆盖层 (Risk Overlay) - 专业级组合风控增强

提供三类互补的风控 overlay，独立于 RiskMonitor（实时熔断）使用：
1. regime_detect       : 市场状态分类 (bull / bear / volatile / normal)
2. dynamic_leverage    : 基于回撤 + 波动率目标 + 市场状态的动态杠杆
3. apply_drawdown_guard: NAV 序列回撤守卫（回撤超阈值时降低敞口）
4. correlation_stress_test: 相关性压力测试（危机情景下相关性矩阵骤升）

与现有模块的集成:
- strategies/portfolio.py: StrategyPortfolio.generate_signals() 可选启用 overlay
- weight_allocation.py: apply_risk_overlay_to_positions() 对目标持仓做敞口缩放
- risk_monitor.py: RiskOverlayAdvisor 将 RiskMonitor 的回撤/VIX 状态转换为杠杆建议

所有函数均为纯函数（无副作用），便于单元测试与回测复用。
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 合法的市场状态
REGIMES = ('bull', 'bear', 'volatile', 'normal')

# 各状态对应的杠杆乘数上限（动态杠杆在此范围内再按波动率/回撤调整）
REGIME_LEVERAGE_CAP = {
    'bull': 1.5,
    'normal': 1.25,
    'bear': 0.75,
    'volatile': 0.5,
}


def regime_detect(price_df: pd.DataFrame,
                  vix: Optional[float] = None,
                  short_window: int = 50,
                  long_window: int = 200,
                  vix_volatile_level: float = 30.0,
                  vix_elevated_level: float = 25.0) -> str:
    """
    市场状态分类: 'bull' / 'bear' / 'volatile' / 'normal'

    判定规则（按优先级）:
    1. VIX >= vix_volatile_level (30)            -> 'volatile'
    2. 等权市场指数: MA50 < MA200                -> 'bear'
    3. VIX >= vix_elevated_level (25)            -> 'volatile'
       （高波动环境下不允许 'bull'，防止 VIX 高企时的误判）
    4. 等权市场指数: 价格 > MA50 > MA200 且动量>0 -> 'bull'
    5. 其他                                       -> 'normal'

    参数:
        price_df: DataFrame, 历史价格 (index=日期, columns=标的)
        vix: float or None, 当前 VIX 水平；None 时忽略 VIX 规则
        short_window: int, 短期均线窗口 (默认 50)
        long_window: int, 长期均线窗口 (默认 200)
        vix_volatile_level: float, VIX 高波动阈值
        vix_elevated_level: float, VIX 偏高阈值

    返回:
        str: 'bull' | 'bear' | 'volatile' | 'normal'
    """
    # 防御性输入处理
    if vix is not None:
        try:
            vix = float(vix)
        except (TypeError, ValueError):
            logger.warning("[REGIME] Invalid VIX value: %s, ignoring VIX rules", vix)
            vix = None
        else:
            if np.isnan(vix):
                vix = None

    # 规则 1: VIX 恐慌
    if vix is not None and vix >= vix_volatile_level:
        logger.info(f"[REGIME] volatile (VIX={vix:.1f} >= {vix_volatile_level})")
        return 'volatile'

    # 市场趋势：等权平均所有可用标的，构建等权指数
    market_index = None
    if price_df is not None and not price_df.empty:
        min_len = min(short_window, long_window)
        if len(price_df) >= min_len:
            clean = price_df.dropna(axis=1, how='all')
            if not clean.empty:
                market_index = clean.mean(axis=1).dropna()

    if market_index is not None and len(market_index) >= max(short_window, 20):
        ma_short = market_index.rolling(short_window).mean().iloc[-1]
        # 长期均线数据不足时退化为使用全部可用数据
        if len(market_index) >= long_window:
            ma_long = market_index.rolling(long_window).mean().iloc[-1]
        else:
            ma_long = market_index.mean()

        if pd.notna(ma_short) and pd.notna(ma_long) and ma_long > 0:
            current = market_index.iloc[-1]
            # 规则 2: 死叉 -> bear
            if ma_short < ma_long:
                logger.info(f"[REGIME] bear (MA{short_window}={ma_short:.2f} < MA{long_window}={ma_long:.2f})")
                return 'bear'
            # 规则 3: VIX 偏高时不允许 bull（bear 已优先返回）
            if vix is not None and vix >= vix_elevated_level:
                logger.info(f"[REGIME] volatile (VIX={vix:.1f} >= {vix_elevated_level})")
                return 'volatile'
            # 规则 4: 多头排列 + 正动量 -> bull
            momentum = current / ma_long - 1
            if current > ma_short > ma_long and momentum > 0:
                logger.info(f"[REGIME] bull (price>MA{short_window}>MA{long_window}, mom={momentum:.1%})")
                return 'bull'
    elif vix is not None and vix >= vix_elevated_level:
        # 无价格数据时，VIX 偏高直接判 volatile
        logger.info(f"[REGIME] volatile (VIX={vix:.1f} >= {vix_elevated_level}, no price data)")
        return 'volatile'

    logger.info("[REGIME] normal")
    return 'normal'


def dynamic_leverage(current_drawdown: float,
                     target_vol: float,
                     realized_vol: float,
                     regime: str = 'normal',
                     max_leverage: float = 1.5,
                     min_leverage: float = 0.5,
                     dd_soft_limit: float = 0.10,
                     dd_hard_limit: float = 0.15) -> float:
    """
    动态杠杆乘数: 波动率目标 × 回撤缩放 × 市场状态上限。

    计算步骤:
    1. 波动率缩放: lev_vol = target_vol / realized_vol（realized_vol<=0 或 NaN 时取 1.0）
    2. 回撤缩放:
       - |dd| <= dd_soft_limit       : 1.0（不缩）
       - soft < |dd| < hard           : 线性从 1.0 缩到 0.5
       - |dd| >= dd_hard_limit        : min_leverage（保守下限）
    3. 状态上限: leverage <= REGIME_LEVERAGE_CAP[regime]
    4. 裁剪到 [min_leverage, max_leverage]

    参数:
        current_drawdown: float, 当前回撤（负数，如 -0.08 表示回撤 8%）
        target_vol: float, 目标年化波动率（如 0.20）
        realized_vol: float, 已实现年化波动率
        regime: str, regime_detect() 的输出
        max_leverage / min_leverage: float, 杠杆上下限
        dd_soft_limit: float, 回撤开始缩减仓位的阈值
        dd_hard_limit: float, 回撤强制降到下限的阈值

    返回:
        float: 杠杆乘数，范围 [min_leverage, max_leverage]
    """
    if regime not in REGIME_LEVERAGE_CAP:
        logger.warning(f"[LEVERAGE] Unknown regime '{regime}', fallback to 'normal'")
        regime = 'normal'

    # 1. 波动率缩放
    try:
        realized_vol = float(realized_vol)
    except (TypeError, ValueError):
        realized_vol = 0.0
    if realized_vol <= 0 or np.isnan(realized_vol) or target_vol <= 0:
        lev_vol = 1.0
    else:
        lev_vol = target_vol / realized_vol

    # 2. 回撤缩放
    try:
        dd = abs(float(current_drawdown))
    except (TypeError, ValueError):
        dd = 0.0
    if np.isnan(dd):
        dd = 0.0

    if dd <= dd_soft_limit:
        dd_scale = 1.0
    elif dd >= dd_hard_limit:
        dd_scale = 0.5
    else:
        # 线性插值: soft -> 1.0, hard -> 0.5
        frac = (dd - dd_soft_limit) / (dd_hard_limit - dd_soft_limit)
        dd_scale = 1.0 - 0.5 * frac

    leverage = lev_vol * dd_scale

    # 3. 状态上限
    leverage = min(leverage, REGIME_LEVERAGE_CAP[regime])

    # 4. 全局上下限
    leverage = float(np.clip(leverage, min_leverage, max_leverage))

    logger.info(f"[LEVERAGE] regime={regime}, dd={dd:.1%}, "
                f"vol_scale={lev_vol:.2f}, dd_scale={dd_scale:.2f} -> leverage={leverage:.2f}x")
    return leverage


def apply_drawdown_guard(nav_series: pd.Series,
                         max_dd: float = 0.15,
                         reduction_factor: float = 0.5) -> pd.Series:
    """
    回撤守卫: 回撤超过 max_dd 时将敞口降到 reduction_factor，回撤修复后恢复。

    逐日计算滚动回撤；当回撤触及 -max_dd 时进入“防守状态”，敞口乘数变为
    reduction_factor；当 NAV 回到高点的 (1 - max_dd/2) 之上时退出防守状态。

    参数:
        nav_series: pd.Series, NAV 序列（index=日期）
        max_dd: float, 触发防守的最大回撤阈值（默认 15%）
        reduction_factor: float, 防守状态下的敞口乘数（默认 0.5）

    返回:
        pd.Series: 与 nav_series 对齐的敞口乘数序列，取值在 [reduction_factor, 1.0]
    """
    if nav_series is None or len(nav_series) == 0:
        return pd.Series(dtype=float)

    nav = pd.Series(nav_series, dtype=float)
    peak = nav.cummax()
    drawdown = (nav - peak) / peak.replace(0, np.nan)

    exposure = pd.Series(1.0, index=nav.index)
    in_guard = False
    recovery_threshold = -max_dd / 2.0

    for i in range(len(nav)):
        dd = drawdown.iloc[i]
        if pd.isna(dd):
            continue
        if not in_guard and dd <= -max_dd:
            in_guard = True
        elif in_guard and dd >= recovery_threshold:
            in_guard = False
        if in_guard:
            exposure.iloc[i] = reduction_factor

    n_guard = int((exposure < 1.0).sum())
    if n_guard > 0:
        logger.info(f"[DD_GUARD] max_dd={max_dd:.0%} breached; "
                    f"{n_guard}/{len(nav)} periods at {reduction_factor:.0%} exposure")
    return exposure


def correlation_stress_test(weights: Dict[str, float],
                            price_df: pd.DataFrame,
                            stress_correlation: float = 0.9,
                            lookback: int = 60) -> Dict[str, float]:
    """
    相关性压力测试: 估计“危机情景”（所有相关性骤升到 stress_correlation）下的
    组合波动率放大倍数。

    步骤:
    1. 用 lookback 窗口估计正常协方差矩阵 Σ_normal，计算组合波动率 σ_normal
    2. 构造压力协方差: 保留各标的自身波动率，相关性全部设为 stress_correlation
    3. 压力波动率 σ_stress，输出 vol_multiplier = σ_stress / σ_normal

    参数:
        weights: dict, {symbol: weight}
        price_df: DataFrame, 历史价格
        stress_correlation: float, 危机情景下的统一相关性（默认 0.9）
        lookback: int, 估计正常协方差的窗口

    返回:
        dict: {
            'normal_vol': float, 正常情景组合年化波动率,
            'stress_vol': float, 压力情景组合年化波动率,
            'vol_multiplier': float, 波动率放大倍数,
            'suggested_scale': float, 建议敞口缩放 = min(1, 1/vol_multiplier),
        }
        数据不足时返回 {'suggested_scale': 1.0, ...NaN}
    """
    default_result = {
        'normal_vol': float('nan'),
        'stress_vol': float('nan'),
        'vol_multiplier': float('nan'),
        'suggested_scale': 1.0,
    }
    if not weights or price_df is None or price_df.empty:
        return default_result

    symbols = [s for s in weights if s in price_df.columns]
    if len(symbols) < 2:
        return default_result

    returns = price_df[symbols].iloc[-lookback:].pct_change().dropna()
    if len(returns) < 20:
        return default_result

    w = np.array([weights[s] for s in symbols], dtype=float)
    total_w = np.abs(w).sum()
    if total_w <= 0:
        return default_result
    w = w / total_w

    cov_normal = returns.cov().values * 252
    vols = np.sqrt(np.diag(cov_normal))
    if np.any(vols <= 0) or np.any(np.isnan(vols)):
        return default_result

    var_normal = float(w @ cov_normal @ w)
    if var_normal <= 0:
        return default_result

    # 压力协方差: 相同 vols, 相关性统一为 stress_correlation
    corr_stress = np.full((len(symbols), len(symbols)), stress_correlation)
    np.fill_diagonal(corr_stress, 1.0)
    cov_stress = np.outer(vols, vols) * corr_stress
    var_stress = float(w @ cov_stress @ w)

    normal_vol = np.sqrt(var_normal)
    stress_vol = np.sqrt(max(var_stress, 0.0))
    vol_multiplier = stress_vol / normal_vol if normal_vol > 0 else float('nan')
    suggested_scale = min(1.0, 1.0 / vol_multiplier) if vol_multiplier > 0 and not np.isnan(vol_multiplier) else 1.0

    logger.info(f"[CORR_STRESS] normal_vol={normal_vol:.1%}, stress_vol={stress_vol:.1%}, "
                f"multiplier={vol_multiplier:.2f}, suggested_scale={suggested_scale:.2f}")
    return {
        'normal_vol': normal_vol,
        'stress_vol': stress_vol,
        'vol_multiplier': vol_multiplier,
        'suggested_scale': suggested_scale,
    }


def apply_risk_overlay_to_positions(target_positions: Dict[str, float],
                                    leverage: float = 1.0,
                                    exposure_scale: float = 1.0) -> Dict[str, float]:
    """
    将杠杆乘数与敞口缩放应用到目标持仓金额上（纯缩放，不改相对权重）。

    参数:
        target_positions: dict, {symbol: target_value}
        leverage: float, dynamic_leverage() 的输出
        exposure_scale: float, apply_drawdown_guard() 当前时点取值
                        或 correlation_stress_test()['suggested_scale']

    返回:
        dict: 缩放后的 {symbol: target_value}
    """
    if not target_positions:
        return {}
    total_scale = leverage * exposure_scale
    if total_scale <= 0:
        logger.warning(f"[OVERLAY] Non-positive scale {total_scale}, returning empty positions")
        return {}
    scaled = {s: v * total_scale for s, v in target_positions.items()}
    logger.info(f"[OVERLAY] Applied leverage={leverage:.2f} x exposure={exposure_scale:.2f} "
                f"-> total_scale={total_scale:.2f}")
    return scaled


class RiskOverlayAdvisor:
    """
    组合级风控 overlay 顾问 —— 与 RiskMonitor 协同工作。

    RiskMonitor 负责“硬熔断”（暂停交易），RiskOverlayAdvisor 负责“软调整”
    （建议杠杆/敞口乘数）。两者互补：overlay 在熔断触发前逐步降风险。

    用法:
        advisor = RiskOverlayAdvisor(target_vol=0.20, max_dd=0.15)
        leverage, exposure = advisor.recommend(
            price_df=price_df,
            vix=current_vix,
            nav_series=portfolio_nav_series,
        )
        adjusted = apply_risk_overlay_to_positions(target_positions, leverage, exposure)
    """

    def __init__(self,
                 target_vol: float = 0.20,
                 max_dd: float = 0.15,
                 max_leverage: float = 1.5,
                 min_leverage: float = 0.5,
                 enabled: bool = True):
        self.target_vol = target_vol
        self.max_dd = max_dd
        self.max_leverage = max_leverage
        self.min_leverage = min_leverage
        self.enabled = enabled
        self.last_regime: Optional[str] = None
        self.last_leverage: float = 1.0
        self.last_exposure: float = 1.0

    def compute_current_drawdown(self, nav_series: pd.Series) -> float:
        """从 NAV 序列计算当前回撤（负数）。"""
        if nav_series is None or len(nav_series) == 0:
            return 0.0
        nav = pd.Series(nav_series, dtype=float)
        peak = nav.cummax().iloc[-1]
        if peak <= 0:
            return 0.0
        return float((nav.iloc[-1] - peak) / peak)

    def compute_realized_vol(self, price_df: pd.DataFrame, lookback: int = 60) -> float:
        """估计组合级已实现年化波动率（等权市场指数的收益率波动）。"""
        if price_df is None or price_df.empty or len(price_df) < 20:
            return 0.0
        market = price_df.mean(axis=1).dropna()
        if len(market) < 20:
            return 0.0
        rets = market.iloc[-lookback:].pct_change().dropna()
        if len(rets) < 10:
            return 0.0
        return float(rets.std() * np.sqrt(252))

    def recommend(self,
                  price_df: Optional[pd.DataFrame] = None,
                  vix: Optional[float] = None,
                  nav_series: Optional[pd.Series] = None) -> Tuple[float, float]:
        """
        输出 (leverage, exposure) 建议。

        参数:
            price_df: DataFrame, 用于 regime 检测与波动率估计
            vix: float or None, 当前 VIX
            nav_series: pd.Series, 组合 NAV 序列（用于回撤）

        返回:
            (leverage, exposure): 均为乘数；enabled=False 时恒为 (1.0, 1.0)
        """
        if not self.enabled:
            return 1.0, 1.0

        regime = regime_detect(price_df, vix) if price_df is not None else 'normal'
        realized_vol = self.compute_realized_vol(price_df) if price_df is not None else 0.0
        current_dd = self.compute_current_drawdown(nav_series)

        leverage = dynamic_leverage(
            current_drawdown=current_dd,
            target_vol=self.target_vol,
            realized_vol=realized_vol,
            regime=regime,
            max_leverage=self.max_leverage,
            min_leverage=self.min_leverage,
            dd_hard_limit=self.max_dd,
        )

        exposure = 1.0
        if nav_series is not None and len(nav_series) > 1:
            exposure_series = apply_drawdown_guard(nav_series, max_dd=self.max_dd)
            if len(exposure_series) > 0:
                exposure = float(exposure_series.iloc[-1])

        self.last_regime = regime
        self.last_leverage = leverage
        self.last_exposure = exposure
        logger.info(f"[OVERLAY_ADVISOR] regime={regime}, dd={current_dd:.1%}, "
                    f"realized_vol={realized_vol:.1%} -> leverage={leverage:.2f}, exposure={exposure:.2f}")
        return leverage, exposure


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    np.random.seed(42)
    dates = pd.bdate_range('2020-01-01', periods=300)
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.normal(0.0005, 0.02, (300, 4)), axis=0) * 100,
        index=dates,
        columns=['AAPL', 'MSFT', 'NVDA', 'GOOGL'],
    )

    print("Regime (bull market, low VIX):", regime_detect(prices, vix=15))
    print("Regime (panic VIX):", regime_detect(prices, vix=40))
    print("Regime (no VIX):", regime_detect(prices, vix=None))

    print("\nLeverage (normal, 8% dd):",
          dynamic_leverage(-0.08, target_vol=0.20, realized_vol=0.18, regime='normal'))
    print("Leverage (bear, 16% dd):",
          dynamic_leverage(-0.16, target_vol=0.20, realized_vol=0.30, regime='bear'))

    # 模拟一段带回撤的 NAV 序列
    nav = pd.Series([1.0, 1.1, 1.2, 1.0, 0.95, 0.98, 1.05, 1.15, 1.25], index=pd.bdate_range('2024-01-01', periods=9))
    guard = apply_drawdown_guard(nav, max_dd=0.15)
    print("\nDrawdown guard exposure:")
    print(pd.DataFrame({'nav': nav, 'exposure': guard}))

    weights = {'AAPL': 0.3, 'MSFT': 0.3, 'NVDA': 0.2, 'GOOGL': 0.2}
    print("\nCorrelation stress test:", correlation_stress_test(weights, prices))
