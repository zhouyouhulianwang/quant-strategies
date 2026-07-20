"""
交易统一撮合模型：
- 在回测和 paper/live 中共享整数截断、spread、成本假设。
- 在 live 订单校验中复用同一套参数。
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional, Tuple
import logging

try:
    from slippage_model import (
        estimate_slippage_bps,
        apply_slippage_to_price,
        DEFAULT_IMPACT_BPS,
        DEFAULT_VOL_COEFF,
        DEFAULT_MAX_PARTICIPATION,
    )
    SLIPPAGE_MODEL_AVAILABLE = True
except ImportError:
    SLIPPAGE_MODEL_AVAILABLE = False
    DEFAULT_IMPACT_BPS = 50.0
    DEFAULT_VOL_COEFF = 0.1
    DEFAULT_MAX_PARTICIPATION = 1.0

logger = logging.getLogger(__name__)


class ExecutionParameters:
    """统一执行参数：回测与 live 共享成本/冲击/spread 假设。

    参数：
        spread_bps: 双边 bid-ask spread，默认 5 bps（0.05%）
        cost_per_turnover: 佣金 + 冲击，每单位 turnover 默认 20 bps
        slippage_bps: 额外滑点，默认 0（已合并到 cost_per_turnover）
        use_fractional_shares: 是否允许小数股（Alpaca 支持），默认 False（与回测一致）
        min_notional: 最小订单名义金额，默认 1.0
        slippage_model: 滑点模型，'fixed'（默认，保持旧行为）或 'volume'（成交量感知）
        impact_bps: 市场冲击系数（基点），仅 slippage_model='volume' 时生效
        vol_impact_coeff: 波动率滑点系数，仅 slippage_model='volume' 时生效
        default_adv: 默认日均成交额（美元），用于缺 ADV 数据时的保守估算
        max_participation: 参与率上限（截断），防止极端 ADV 导致滑点爆炸
    """

    def __init__(
        self,
        spread_bps: float = 5.0,
        cost_per_turnover: float = 0.002,
        slippage_bps: float = 0.0,
        use_fractional_shares: bool = False,
        min_notional: float = 1.0,
        slippage_model: str = 'fixed',
        impact_bps: float = DEFAULT_IMPACT_BPS,
        vol_impact_coeff: float = DEFAULT_VOL_COEFF,
        default_adv: float = 0.0,
        max_participation: float = DEFAULT_MAX_PARTICIPATION,
    ):
        self.spread_bps = spread_bps
        self.cost_per_turnover = cost_per_turnover
        self.slippage_bps = slippage_bps
        self.use_fractional_shares = use_fractional_shares
        self.min_notional = min_notional
        self.slippage_model = slippage_model
        self.impact_bps = impact_bps
        self.vol_impact_coeff = vol_impact_coeff
        self.default_adv = default_adv
        self.max_participation = max_participation

    @property
    def total_cost_per_turnover(self) -> float:
        """总交易成本 = 佣金/冲击 + spread + 滑点。"""
        return self.cost_per_turnover + (self.spread_bps + self.slippage_bps) / 10000.0

    def effective_price(self, mid_price: float, side: str) -> float:
        """根据买卖方向，应用 half-spread 得到执行价格。

        买入：mid + half_spread
        卖出：mid - half_spread
        """
        if mid_price <= 0:
            return mid_price
        half_spread = (self.spread_bps / 10000.0) / 2.0
        if side == 'buy':
            return mid_price * (1 + half_spread)
        elif side == 'sell':
            return mid_price * (1 - half_spread)
        return mid_price

    def calculate_qty(self, target_value: float, price: float, symbol: Optional[str] = None) -> int:
        """按目标金额和价格计算股数，默认整数截断。"""
        if price <= 0 or target_value <= 0:
            return 0
        if self.use_fractional_shares:
            qty = Decimal(str(target_value)) / Decimal(str(price))
            return float(qty.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP))
        qty = int(target_value / price)
        return qty

    def estimate_fill(self, mid_price: float, side: str, qty: int,
                      adv: Optional[float] = None,
                      volatility: float = 0.0) -> Tuple[float, float]:
        """模拟订单成交：返回执行均价和交易费用。

        参数:
            mid_price: 中间价
            side: 'buy' 或 'sell'
            qty: 股数
            adv: 可选，该标的日均成交额（美元）；slippage_model='volume' 时使用
            volatility: 可选，年化波动率；slippage_model='volume' 时使用

        返回：
            (filled_avg_price, total_cost)
        """
        if qty <= 0 or mid_price <= 0:
            return mid_price, 0.0

        if self.slippage_model == 'volume' and SLIPPAGE_MODEL_AVAILABLE:
            return self._estimate_fill_volume(mid_price, side, qty, adv, volatility)

        price = self.effective_price(mid_price, side)
        notional = price * qty
        total_cost = notional * self.total_cost_per_turnover
        return price, total_cost

    def _estimate_fill_volume(self, mid_price: float, side: str, qty: int,
                              adv: Optional[float],
                              volatility: float) -> Tuple[float, float]:
        """成交量感知滑点模型的成交估算。

        成本构成：
            - 执行价按 volume 滑点模型调整（spread/2 + vol + sqrt(参与率) 冲击）
            - 交易费用仍按 cost_per_turnover（佣金）计，避免与旧假设重复计 spread
        """
        notional_mid = mid_price * qty
        eff_adv = adv if (adv and adv > 0) else (self.default_adv or 0.0)

        slip_bps = estimate_slippage_bps(
            side=side,
            notional=notional_mid,
            adv=eff_adv,
            volatility=volatility,
            spread_bps=self.spread_bps,
            impact_bps=self.impact_bps,
            vol_coeff=self.vol_impact_coeff,
            max_participation=self.max_participation,
        )
        price = apply_slippage_to_price(mid_price, side, slip_bps)
        notional = price * qty
        # 佣金部分沿用 cost_per_turnover；spread 已包含在滑点价格中
        total_cost = notional * (self.cost_per_turnover + self.slippage_bps / 10000.0)
        return price, total_cost

    def validate_order(self, target_value: float, price: float, side: str) -> Tuple[bool, str]:
        """校验订单是否满足最小名义金额等规则。"""
        if price <= 0:
            return False, 'price_invalid'
        qty = self.calculate_qty(target_value, price)
        if qty <= 0:
            return False, 'qty_zero'
        notional = self.effective_price(price, side) * qty
        if notional < self.min_notional:
            return False, f'notional_too_small:{notional:.2f}'
        return True, 'ok'


# 默认实例（可被 alpaca_executor.py / cost_model.py / v14.py 共用）
default_execution_params = ExecutionParameters()


def from_config(config) -> ExecutionParameters:
    """从 V14StrategyConfig 创建执行参数。"""
    if config is None:
        return ExecutionParameters()

    spread_bps = 5.0
    cost_per_turnover = 0.002
    use_fractional_shares = False
    min_notional = 1.0
    slippage_model = 'fixed'
    impact_bps = DEFAULT_IMPACT_BPS
    vol_impact_coeff = DEFAULT_VOL_COEFF
    default_adv = 0.0
    max_participation = DEFAULT_MAX_PARTICIPATION

    if hasattr(config, 'trading'):
        trading = config.trading
        spread_bps = getattr(trading, 'spread_bps', spread_bps)
        cost_per_turnover = getattr(trading, 'cost_per_turnover', cost_per_turnover)
        use_fractional_shares = getattr(trading, 'use_fractional_shares', use_fractional_shares)
        min_notional = getattr(trading, 'min_notional', min_notional)
        slippage_model = getattr(trading, 'slippage_model', slippage_model)
        impact_bps = getattr(trading, 'impact_bps', impact_bps)
        vol_impact_coeff = getattr(trading, 'vol_impact_coeff', vol_impact_coeff)
        default_adv = getattr(trading, 'default_adv', default_adv)
        max_participation = getattr(trading, 'max_participation', max_participation)

    return ExecutionParameters(
        spread_bps=spread_bps,
        cost_per_turnover=cost_per_turnover,
        use_fractional_shares=use_fractional_shares,
        min_notional=min_notional,
        slippage_model=slippage_model,
        impact_bps=impact_bps,
        vol_impact_coeff=vol_impact_coeff,
        default_adv=default_adv,
        max_participation=max_participation,
    )


if __name__ == '__main__':
    params = ExecutionParameters()
    print(params.effective_price(150.0, 'buy'))
    print(params.effective_price(150.0, 'sell'))
    print(params.calculate_qty(20000.0, 150.0))
    print(params.estimate_fill(150.0, 'buy', 133))
