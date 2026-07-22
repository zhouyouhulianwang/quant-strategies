"""
Regime-Aware Strategy Allocation - 市场状态感知的子策略权重分配

根据 risk_overlay.regime_detect() 输出的市场状态 (bull / bear / volatile / normal)，
动态调整多策略组合中各子策略的资金权重：

- normal  : 使用样本内最优基准权重 G40/S20/M15/V10/Q15 (Sharpe 1.336)
- bull    : 进攻性倾斜 —— 提高 sector_rotation（强趋势中贡献 CAGR），降低 quality
- bear    : 防守性倾斜 —— 降低 sector_rotation（震荡/熊市中严重拖累 Sharpe），
            提高 quality 与 value
- volatile: 同 bear，但 sector_rotation 压得更低

优化发现（见 OPTIMIZATION_ROADMAP.md）:
- sector_rotation 与 Sharpe 相关性 -0.92（>20% 时显著拖累），与 CAGR 相关性 +0.43
- 因此 regime-dependent allocation 是 OOS 稳健性的自然改进

特性:
- 权重恒归一化到 1.0，每个策略保留 min_weight（默认 5%）下限，避免因子归零
- 支持 regime 切换平滑（max single-step change），避免 whipsaw
- 纯函数 / 无副作用（平滑状态由实例持有，可显式 reset）

用法:
    from regime_allocator import RegimeAllocator

    allocator = RegimeAllocator()
    weights = allocator.allocate('bear', current_weights={
        'growth': 0.40, 'sector_rotation': 0.20, 'momentum': 0.15,
        'value': 0.10, 'quality': 0.15,
    })
    # -> sector_rotation 降到 10%，quality/value 提升，总和=1.0
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 样本内最优基准权重（Sharpe 视角）: G40/S20/M15/V10/Q15
DEFAULT_BASE_WEIGHTS: Dict[str, float] = {
    'growth': 0.40,
    'sector_rotation': 0.20,
    'momentum': 0.15,
    'value': 0.10,
    'quality': 0.15,
}

# 各市场状态下的目标权重（均已归一化，且每个策略 >= 5%）
REGIME_WEIGHT_TILTS: Dict[str, Dict[str, float]] = {
    # 基准：样本内最优 Sharpe 组合
    'normal': {
        'growth': 0.40,
        'sector_rotation': 0.20,
        'momentum': 0.15,
        'value': 0.10,
        'quality': 0.15,
    },
    # 牛市：sector_rotation 在强趋势中贡献 CAGR，提高到 30%；
    # quality（CAGR 拖累最强，corr=-0.84）降到 5% 下限
    'bull': {
        'growth': 0.40,
        'sector_rotation': 0.30,
        'momentum': 0.15,
        'value': 0.10,
        'quality': 0.05,
    },
    # 熊市：sector_rotation 是 Sharpe 最大拖累（corr=-0.92），降到 10%；
    # 防守性提高 quality（低波/高质量抗跌）和 value
    'bear': {
        'growth': 0.35,
        'sector_rotation': 0.10,
        'momentum': 0.15,
        'value': 0.15,
        'quality': 0.25,
    },
    # 高波动：sector_rotation 压到下限 5%，quality 提到最高 30%
    'volatile': {
        'growth': 0.30,
        'sector_rotation': 0.05,
        'momentum': 0.15,
        'value': 0.20,
        'quality': 0.30,
    },
}

VALID_REGIMES = tuple(REGIME_WEIGHT_TILTS.keys())


def normalize_weights(weights: Dict[str, float], min_weight: float = 0.0) -> Dict[str, float]:
    """
    归一化权重到总和 1.0，可选施加每策略下限并重新归一化（纯函数）。

    参数:
        weights: dict, {strategy_name: weight}，允许负数/NaN 输入（按 0 处理）
        min_weight: float, 每个策略的最小权重（0 表示不施加下限）

    返回:
        dict: 归一化后的权重；输入为空或全零时返回 {}
    """
    if not weights:
        return {}

    cleaned = {}
    for name, w in weights.items():
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = 0.0
        if w != w or w < 0:  # NaN 或负数按 0 处理
            w = 0.0
        cleaned[name] = w

    total = sum(cleaned.values())
    if total <= 0:
        # 全零输入：等权
        n = len(cleaned)
        return {k: 1.0 / n for k in cleaned}

    normalized = {k: v / total for k, v in cleaned.items()}

    if min_weight > 0:
        n = len(normalized)
        if min_weight * n > 1.0:
            logger.warning(f"[REGIME_ALLOC] min_weight={min_weight} infeasible for {n} strategies, ignoring")
            return normalized
        # 先把低于下限的提到下限，剩余权重在其余策略间按比例分配
        for _ in range(10):  # 迭代直到所有策略 >= min_weight
            below = {k for k, v in normalized.items() if v < min_weight - 1e-12}
            if not below:
                break
            deficit = sum(min_weight - normalized[k] for k in below)
            for k in below:
                normalized[k] = min_weight
            above = {k for k in normalized if k not in below}
            above_total = sum(normalized[k] for k in above)
            if above_total <= 0:
                break
            for k in above:
                normalized[k] = max(min_weight, normalized[k] - deficit * normalized[k] / above_total)
        total = sum(normalized.values())
        normalized = {k: v / total for k, v in normalized.items()}

    return normalized


class RegimeAllocator:
    """
    市场状态感知的子策略权重分配器。

    将 regime_detect() 的输出映射为一组目标权重，并通过
    max single-step change 平滑 regime 切换，避免频繁大幅调仓。

    Parameters
    ----------
    base_weights : dict, optional
        normal 状态下的基准权重。默认 DEFAULT_BASE_WEIGHTS (G40/S20/M15/V10/Q15)。
    min_weight : float
        每个策略的最小权重（默认 5%），避免任何因子被归零。
    max_step : float, optional
        单次 allocate() 调用中任一策略权重允许的最大变化幅度（绝对值）。
        None 或 <=0 表示不平滑。默认 0.10（每次最多变化 10 个百分点）。
    enabled : bool
        False 时 allocate() 原样返回归一化后的 current_weights。
    """

    def __init__(self,
                 base_weights: Optional[Dict[str, float]] = None,
                 min_weight: float = 0.05,
                 max_step: Optional[float] = 0.10,
                 enabled: bool = True):
        self.base_weights = normalize_weights(base_weights or DEFAULT_BASE_WEIGHTS,
                                              min_weight=min_weight)
        self.min_weight = min_weight
        self.max_step = max_step if (max_step and max_step > 0) else None
        self.enabled = enabled
        self.last_regime: Optional[str] = None
        self.last_weights: Optional[Dict[str, float]] = None

    # ------------------------------------------------------------------
    # 核心 API
    # ------------------------------------------------------------------

    def target_weights(self, regime: str) -> Dict[str, float]:
        """
        返回指定 regime 的目标权重（未平滑，纯函数性质）。

        未知 regime 回退到 base_weights（normal）并记录 warning。
        base_weights 中不存在的策略键会被忽略；缺失的策略用 base 权重补齐。
        """
        if regime not in REGIME_WEIGHT_TILTS:
            logger.warning(f"[REGIME_ALLOC] Unknown regime '{regime}', fallback to base weights")
            return dict(self.base_weights)

        tilt = REGIME_WEIGHT_TILTS[regime]
        target = dict(self.base_weights)
        target.update({k: v for k, v in tilt.items() if k in target})
        return normalize_weights(target, min_weight=self.min_weight)

    def allocate(self, regime: str, current_weights: Dict[str, float]) -> Dict[str, float]:
        """
        根据 regime 输出平滑后的组合权重。

        参数:
            regime: str, regime_detect() 的输出 ('bull'/'bear'/'volatile'/'normal')
            current_weights: dict, 当前子策略权重 {name: weight}

        返回:
            dict: 归一化后的目标权重（总和=1.0，每项 >= min_weight）
        """
        current = normalize_weights(current_weights, min_weight=self.min_weight)
        if not current:
            logger.warning("[REGIME_ALLOC] Empty current_weights, returning base weights")
            return dict(self.base_weights)

        if not self.enabled:
            self.last_regime = regime
            self.last_weights = current
            return current

        target = self.target_weights(regime)

        # 键对齐：current 里有而 target 没有的键，用 base 权重或 min_weight 补齐；
        # target 里有而 current 没有的键，以 min_weight 起步
        all_keys = set(current) | set(target)
        aligned_current, aligned_target = {}, {}
        for k in all_keys:
            aligned_target[k] = target.get(k, self.base_weights.get(k, self.min_weight))
            aligned_current[k] = current.get(k, self.min_weight)
        aligned_current = normalize_weights(aligned_current, min_weight=self.min_weight)
        aligned_target = normalize_weights(aligned_target, min_weight=self.min_weight)

        # 平滑：限制单步变化幅度
        if self.max_step is not None:
            smoothed = {}
            for k in all_keys:
                delta = aligned_target[k] - aligned_current[k]
                if abs(delta) > self.max_step:
                    delta = self.max_step if delta > 0 else -self.max_step
                smoothed[k] = aligned_current[k] + delta
            result = normalize_weights(smoothed, min_weight=self.min_weight)
            max_delta = max(abs(result[k] - aligned_current[k]) for k in all_keys)
            logger.info(f"[REGIME_ALLOC] regime={regime}, smoothing applied "
                        f"(max_step={self.max_step:.0%}, max actual change={max_delta:.1%})")
        else:
            result = aligned_target
            logger.info(f"[REGIME_ALLOC] regime={regime}, no smoothing")

        self.last_regime = regime
        self.last_weights = result
        logger.info(f"[REGIME_ALLOC] weights: "
                    + ", ".join(f"{k}={v:.0%}" for k, v in sorted(result.items())))
        return result

    def reset(self):
        """重置平滑状态（新的回测/会话开始时调用）。"""
        self.last_regime = None
        self.last_weights = None

    def __repr__(self) -> str:
        return (f"RegimeAllocator(min_weight={self.min_weight}, "
                f"max_step={self.max_step}, enabled={self.enabled})")


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    allocator = RegimeAllocator()
    current = dict(DEFAULT_BASE_WEIGHTS)

    print("=== Regime transition: normal -> bear -> volatile -> bull ===")
    for regime in ['normal', 'bear', 'volatile', 'bull', 'bull']:
        current = allocator.allocate(regime, current)
        print(f"{regime:>9}: " + ", ".join(f"{k}={v:.1%}" for k, v in sorted(current.items())))
        assert abs(sum(current.values()) - 1.0) < 1e-9
        assert all(v >= allocator.min_weight - 1e-9 for v in current.values())
