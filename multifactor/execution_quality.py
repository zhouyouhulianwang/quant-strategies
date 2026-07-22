"""
执行质量模块 - 市场冲击 / 滑点模型

提供 MarketImpactModel 类，根据订单规模、ADV（日均成交额）与 spread
估算市场冲击 / 滑点成本（以基点 bps 表示）。

支持的模型：
    - 'linear':      冲击 ∝ 参与率（participation = notional / ADV）
    - 'square_root': 冲击 ∝ sqrt(参与率)（Almgren 风格，业界最常用）

总滑点构成：
    slippage_bps = half_spread_bps + impact_bps * f(participation)

其中 half_spread_bps = spread_bps / 2（单边 spread 成本）。

设计说明：
    - 与 slippage_model.py（volume 感知滑点）互补：本模块聚焦
      冲击项的参数化与模型选择，可被 cost_model / matching_engine 复用。
    - 默认参数偏保守：参与率 100% 时 square_root 模型冲击约 50 bps，
      对大盘股（参与率 <1%）冲击约 5 bps。

用法示例:
    >>> model = MarketImpactModel(model_type='square_root', impact_bps=50.0)
    >>> slip = model.estimate_impact_bps(notional=100_000, adv=50_000_000, spread_bps=4.0)
    >>> exec_price = model.apply_impact_to_price(mid_price=150.0, side='buy', impact_bps=slip)
"""

import logging
import math

logger = logging.getLogger(__name__)

# 默认参数
DEFAULT_IMPACT_BPS = 50.0           # 参与率 100% 时的冲击成本（基点）
DEFAULT_MAX_PARTICIPATION = 1.0     # 参与率截断上限（100%）
SUPPORTED_MODELS = ('linear', 'square_root')


class MarketImpactModel:
    """
    市场冲击模型

    根据订单名义金额（notional）、日均成交额（ADV）与双边 spread
    估算单边滑点 / 冲击成本（基点 bps，>= 0）。

    参数:
        model_type: str, 'linear' 或 'square_root'
        impact_bps: float, 冲击系数（基点），参与率 100% 时的冲击成本
        max_participation: float, 参与率截断上限（默认 1.0，防止小 ADV 股票冲击爆炸）
    """

    def __init__(self,
                 model_type: str = 'square_root',
                 impact_bps: float = DEFAULT_IMPACT_BPS,
                 max_participation: float = DEFAULT_MAX_PARTICIPATION):
        if model_type not in SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported impact model: {model_type!r}; "
                f"supported: {SUPPORTED_MODELS}"
            )
        if impact_bps < 0:
            raise ValueError("impact_bps must be >= 0")
        if max_participation <= 0:
            raise ValueError("max_participation must be > 0")

        self.model_type = model_type
        self.impact_bps = float(impact_bps)
        self.max_participation = float(max_participation)

        logger.info(
            "✅ MarketImpactModel 初始化: model=%s, impact=%.1f bps, max_participation=%.2f",
            self.model_type, self.impact_bps, self.max_participation,
        )

    # ------------------------------------------------------------------
    # 核心估算
    # ------------------------------------------------------------------

    def _impact_component_bps(self, participation: float) -> float:
        """按模型类型计算冲击分量（不含 spread）"""
        if participation <= 0:
            return 0.0
        p = min(participation, self.max_participation)
        if self.model_type == 'linear':
            return self.impact_bps * p
        # square_root（默认）
        return self.impact_bps * math.sqrt(p)

    def estimate_impact_bps(self,
                            notional: float,
                            adv: float,
                            spread_bps: float = 5.0) -> float:
        """
        估算单边滑点 / 冲击成本（基点，>= 0）。

        参数:
            notional: float, 订单名义金额（美元）
            adv: float, 该标的日均成交额（美元）；<=0 时仅返回 spread 成本
            spread_bps: float, 双边 bid-ask spread（基点），取一半作为单边成本

        返回:
            float: 单边滑点（基点，>= 0）；notional <= 0 时返回 0
        """
        if notional is None or notional <= 0:
            return 0.0

        # 1. 单边 spread 成本
        half_spread = max(float(spread_bps or 0.0), 0.0) / 2.0

        # 2. 冲击分量
        impact = 0.0
        if adv and adv > 0:
            participation = notional / adv
            impact = self._impact_component_bps(participation)

        return half_spread + impact

    def estimate_impact_cost(self,
                             notional: float,
                             adv: float,
                             spread_bps: float = 5.0) -> float:
        """
        估算冲击 / 滑点的美元成本。

        返回:
            float: 成本（美元）= notional * slippage_bps / 10000
        """
        if notional is None or notional <= 0:
            return 0.0
        slip_bps = self.estimate_impact_bps(notional, adv, spread_bps)
        return notional * slip_bps / 10000.0

    @staticmethod
    def apply_impact_to_price(mid_price: float, side: str, impact_bps: float) -> float:
        """
        按滑点调整执行价格。

        买入：价格上调；卖出：价格下调。
        """
        if mid_price <= 0 or impact_bps <= 0:
            return mid_price
        slip = impact_bps / 10000.0
        if side == 'buy':
            return mid_price * (1 + slip)
        elif side == 'sell':
            return mid_price * (1 - slip)
        return mid_price

    def describe(self) -> dict:
        """返回模型参数摘要（用于日志 / 审计）"""
        return {
            'model_type': self.model_type,
            'impact_bps': self.impact_bps,
            'max_participation': self.max_participation,
        }


# ============================================================
# 便捷函数（与模块级 API 兼容）
# ============================================================

def estimate_market_impact_bps(notional: float,
                               adv: float,
                               spread_bps: float = 5.0,
                               model_type: str = 'square_root',
                               impact_bps: float = DEFAULT_IMPACT_BPS) -> float:
    """一次性估算滑点（内部创建 MarketImpactModel 实例）"""
    return MarketImpactModel(model_type=model_type, impact_bps=impact_bps).estimate_impact_bps(
        notional=notional, adv=adv, spread_bps=spread_bps,
    )


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    # 场景：买入 10 万美元的大盘股（ADV 5000 万，spread 4 bps）
    notional, adv, spread = 100_000, 50_000_000, 4.0

    for m in SUPPORTED_MODELS:
        model = MarketImpactModel(model_type=m)
        slip = model.estimate_impact_bps(notional, adv, spread)
        cost = model.estimate_impact_cost(notional, adv, spread)
        print(f"{m:12s}: slippage={slip:6.2f} bps, cost=${cost:,.2f} "
              f"(participation={notional/adv:.2%})")

    # 极端场景：小盘股，参与率 10%
    model = MarketImpactModel(model_type='square_root')
    slip = model.estimate_impact_bps(notional=1_000_000, adv=10_000_000, spread_bps=20.0)
    exec_px = model.apply_impact_to_price(25.0, 'buy', slip)
    print(f"\n小盘股买入 100万 (ADV 1000万): slippage={slip:.1f} bps, exec_px={exec_px:.4f} (mid=25.00)")
