"""
成交量感知滑点 / 市场冲击模型

基于 Almgren 风格的平方根冲击模型估算单笔交易滑点：

    slippage_bps = half_spread_bps
                 + vol_coeff * daily_volatility * 10000
                 + impact_bps * sqrt(participation)

其中：
    - half_spread_bps: 单边 spread（双边 spread 的一半）
    - daily_volatility: 年化波动率 / sqrt(252)
    - participation: 交易名义金额 / 日均成交额 (ADV)
    - impact_bps: 冲击系数（基点），参与率 100% 时的冲击成本

滑点方向：
    - 买入: 执行价 = mid * (1 + slippage)
    - 卖出: 执行价 = mid * (1 - slippage)

默认参数偏保守，旨在对典型大盘股组合（参与率 <1%）产生与现有
固定 cost_per_turnover 假设同量级的成本，避免回测结果剧烈变化。
"""

import logging
import math

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252

# 默认冲击系数：参与率 100% 时冲击 50 bps
DEFAULT_IMPACT_BPS = 50.0
# 波动率滑点系数：每单位日波动率贡献的滑点比例
DEFAULT_VOL_COEFF = 0.1
# 参与率上限，防止极端小额 ADV 导致滑点爆炸
DEFAULT_MAX_PARTICIPATION = 1.0


def estimate_slippage_bps(
    side: str,
    notional: float,
    adv: float,
    volatility: float = 0.0,
    spread_bps: float = 5.0,
    impact_bps: float = DEFAULT_IMPACT_BPS,
    vol_coeff: float = DEFAULT_VOL_COEFF,
    max_participation: float = DEFAULT_MAX_PARTICIPATION,
) -> float:
    """
    估算单笔交易的滑点（基点，bps）。

    参数:
        side: 'buy' 或 'sell'（方向影响符号，不影响量级）
        notional: 交易名义金额（美元）
        adv: 该标的日均成交额（美元）；<=0 时退化为 spread+vol 部分
        volatility: 年化波动率（如 0.25 表示 25%）；<=0 时忽略波动项
        spread_bps: 双边 bid-ask spread（基点），取一半作为单边成本
        impact_bps: 冲击系数（基点），参与率=100% 时的冲击成本
        vol_coeff: 波动率滑点系数
        max_participation: 参与率上限（截断，默认 1.0 = 100%）

    返回:
        float: 单边滑点（基点，>=0）
    """
    if notional <= 0:
        return 0.0

    # 1. 单边 spread 成本
    half_spread = max(spread_bps, 0.0) / 2.0

    # 2. 波动率项：年化波动率 -> 日波动率 -> bps
    vol_component = 0.0
    if volatility and volatility > 0:
        daily_vol = volatility / math.sqrt(TRADING_DAYS_PER_YEAR)
        vol_component = vol_coeff * daily_vol * 10000.0

    # 3. 市场冲击项：sqrt(参与率) 模型
    impact_component = 0.0
    if adv and adv > 0:
        participation = min(notional / adv, max_participation)
        impact_component = impact_bps * math.sqrt(participation)

    total = half_spread + vol_component + impact_component
    return total


def apply_slippage_to_price(mid_price: float, side: str, slippage_bps: float) -> float:
    """
    按滑点调整执行价格。

    买入：价格上调；卖出：价格下调。
    """
    if mid_price <= 0 or slippage_bps <= 0:
        return mid_price
    slip = slippage_bps / 10000.0
    if side == 'buy':
        return mid_price * (1 + slip)
    elif side == 'sell':
        return mid_price * (1 - slip)
    return mid_price
