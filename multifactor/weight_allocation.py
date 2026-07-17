"""
权重分配策略 - 支持等权、市值加权、风险平价
"""

import numpy as np
import pandas as pd
import logging

# P2修复：统一全链路日志格式
logger = logging.getLogger(__name__)


class WeightAllocator:
    """权重分配器"""
    
    def __init__(self, method='equal', risk_budget=None):
        """
        初始化权重分配器
        
        参数:
            method: str, 'equal' | 'risk_parity' | 'min_variance' | 'momentum_weighted'
            risk_budget: dict, 风险预算 {symbol: weight}
        """
        self.method = method
        self.risk_budget = risk_budget
    
    def allocate(self, selected_symbols, price_df=None, target_value=None) -> dict:
        """
        分配权重

        参数:
            selected_symbols: list, 选中的股票列表
            price_df: DataFrame, 历史价格数据 (用于风险计算)
            target_value: float, 总目标金额

        返回:
            dict: {symbol: target_value} 或 {symbol: weight}
        """
        if not selected_symbols:
            return {}

        if self.method == 'equal':
            weights = self._equal_weight(selected_symbols)
        elif self.method == 'risk_parity':
            weights = self._risk_parity_weight(selected_symbols, price_df)
        elif self.method == 'min_variance':
            weights = self._min_variance_weight(selected_symbols, price_df)
        elif self.method == 'momentum_weighted':
            weights = self._momentum_weighted(selected_symbols, price_df)
        else:
            weights = self._equal_weight(selected_symbols)

        # 转换为金额
        if target_value:
            return {s: target_value * w for s, w in weights.items()}

        return weights
    
    def _equal_weight(self, symbols):
        """等权分配"""
        n = len(symbols)
        return {s: 1.0 / n for s in symbols}
    
    def _risk_parity_weight(self, symbols, price_df):
        """
        风险平价分配 - 每只标的风险贡献相等

        公式: w_i ∝ 1/σ_i
        """
        if price_df is None or len(price_df) < 20:
            logger.warning("价格数据不足，回退到等权")
            return self._equal_weight(symbols)

        available = list(set(symbols) & set(price_df.columns))
        if len(available) == 0:
            return self._equal_weight(symbols)

        # 计算波动率
        returns = price_df[available].pct_change().dropna()

        if len(returns) < 20:
            return self._equal_weight(symbols)

        # 年化波动率
        vols = returns.std() * np.sqrt(252)

        # 风险平价权重: 反比于波动率
        inv_vols = 1.0 / vols.replace(0, np.inf)
        weights = inv_vols / inv_vols.sum()

        # 归一化
        weights = weights / weights.sum()

        result = {}
        for s in symbols:
            if s in weights.index:
                result[s] = weights[s]
            else:
                result[s] = 0.0

        # 重新归一化（缺失 symbol 权重为 0，避免 KeyError）
        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}
        else:
            result = self._equal_weight(symbols)

        return result
    
    def _min_variance_weight(self, symbols, price_df):
        """
        最小方差组合 - 组合波动率最小

        简化版: 仅使用对角线（方差），忽略协方差
        """
        if price_df is None or len(price_df) < 20:
            return self._equal_weight(symbols)

        available = list(set(symbols) & set(price_df.columns))
        if len(available) == 0:
            return self._equal_weight(symbols)

        returns = price_df[available].pct_change().dropna()

        if len(returns) < 20:
            return self._equal_weight(symbols)

        # 使用方差的倒数作为权重
        variances = returns.var()
        inv_var = 1.0 / variances.replace(0, np.inf)
        weights = inv_var / inv_var.sum()

        result = {}
        for s in symbols:
            if s in weights.index:
                result[s] = weights[s]
            else:
                result[s] = 0.0

        # 归一化（缺失 symbol 权重为 0，避免 KeyError）
        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}
        else:
            result = self._equal_weight(symbols)

        return result
    
    def _momentum_weighted(self, symbols, price_df):
        """
        动量加权 - 近期表现好的权重更高
        
        公式: w_i ∝ max(0, momentum_i)
        """
        if price_df is None or len(price_df) < 60:
            return self._equal_weight(symbols)
        
        available = list(set(symbols) & set(price_df.columns))
        
        if len(available) == 0:
            return self._equal_weight(symbols)
        
        # 计算60日动量
        momentum = price_df[available].iloc[-1] / price_df[available].iloc[-60] - 1
        
        # 只取正的动量
        positive_mom = momentum[momentum > 0]
        
        if len(positive_mom) == 0:
            return self._equal_weight(symbols)
        
        # 动量加权
        weights = positive_mom / positive_mom.sum()
        
        result = {}
        for s in symbols:
            if s in weights.index:
                result[s] = weights[s]
            else:
                result[s] = 0.0
        
        # 归一化
        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}
        
        return result


def normalize_target_positions(target_positions, max_total_value, min_position_value=0):
    """
    归一化目标持仓，确保总金额不超过 max_total_value

    参数:
        target_positions: dict, {symbol: target_value}
        max_total_value: float, 最大总目标金额
        min_position_value: float, 最小持仓金额（归一化后保留）

    返回:
        dict: 归一化后的目标持仓
    """
    if not target_positions:
        return {}

    total = sum(target_positions.values())
    if total <= max_total_value:
        return target_positions

    # 按比例缩放
    scale = max_total_value / total
    scaled = {s: v * scale for s, v in target_positions.items()}

    # 如果缩放后低于最小持仓，则剔除并重新归一化
    if min_position_value > 0:
        filtered = {s: v for s, v in scaled.items() if v >= min_position_value}
        if filtered and sum(filtered.values()) > 0:
            return normalize_target_positions(filtered, max_total_value, 0)

    return scaled


def apply_weight_constraints(weights, min_weight=0.0, max_weight=0.20, max_iter=10):
    """
    应用权重约束

    参数:
        weights: dict, {symbol: weight}
        min_weight: float, 最小权重
        max_weight: float, 最大权重
        max_iter: int, 迭代裁剪次数

    返回:
        dict: 约束后的权重
    """
    constrained = weights.copy()

    for _ in range(max_iter):
        # 上限约束
        capped = {k: min(v, max_weight) for k, v in constrained.items()}
        # 下限约束
        floored = {k: max(v, min_weight) for k, v in capped.items()}

        total = sum(floored.values())
        if total <= 0:
            return weights

        normalized = {k: v / total for k, v in floored.items()}

        # 若已收敛则退出
        if all(abs(normalized[k] - constrained.get(k, 0)) < 1e-6 for k in normalized):
            constrained = normalized
            break

        constrained = normalized

    return constrained


def integrate_with_backtest(selected_symbols, total_equity, price_df,
                            max_weight=0.20, min_weight=0.0,
                            weight_method='equal', execution_date=None,
                            **allocator_kwargs):
    """
    与回测集成的目标持仓接口

    参数:
        selected_symbols: list, 选中的股票
        total_equity: float, 总可用资金
        price_df: DataFrame, 历史价格数据
        max_weight: float, 单标的最大权重
        min_weight: float, 单标的最小权重
        weight_method: str, 权重分配方法
        execution_date: 可选, 调仓执行日; 若提供则剔除该日无价格标的
        **allocator_kwargs: WeightAllocator 的其它参数

    返回:
        dict: {symbol: target_value}
    """
    if not selected_symbols or total_equity <= 0:
        return {}

    # P1修复: 根据 execution_date 剔除停牌/无价格标的
    if execution_date is None:
        exec_date = price_df.index[-1]
    else:
        exec_date = execution_date
        # 若 execution_date 不在 price_df 中, 回退到之后的第一个交易日
        if exec_date not in price_df.index:
            future = price_df.index[price_df.index >= exec_date]
            exec_date = future[0] if len(future) > 0 else price_df.index[-1]

    # 仅保留在 execution_date 有有效价格的标的
    unique_symbols = list(dict.fromkeys(selected_symbols))
    available_symbols = [
        s for s in unique_symbols
        if s in price_df.columns and pd.notna(price_df.at[exec_date, s])
    ]

    if not available_symbols:
        logger.warning(f"⚠️ {exec_date} 无可用价格，无法生成目标持仓")
        return {}

    allocator = WeightAllocator(method=weight_method, **allocator_kwargs)
    target_positions = allocator.allocate(available_symbols, price_df=price_df, target_value=total_equity)

    total = sum(target_positions.values())
    if total <= 0:
        return {}

    weights = {s: v / total for s, v in target_positions.items()}
    weights = apply_weight_constraints(weights, min_weight=min_weight, max_weight=max_weight)

    result = {s: total_equity * w for s, w in weights.items()}
    result = normalize_target_positions(result, total_equity, min_position_value=0)
    return result


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    import numpy as np
    
    symbols = ['AAPL', 'MSFT', 'NVDA', 'GOOGL']
    
    # 模拟价格数据
    np.random.seed(42)
    dates = pd.bdate_range('2024-01-01', periods=100)
    prices = pd.DataFrame(
        np.cumprod(1 + np.random.normal(0.001, 0.02, (100, 4)), axis=0),
        index=dates,
        columns=symbols
    )
    
    # 等权
    allocator = WeightAllocator('equal')
    weights = allocator.allocate(symbols, prices, target_value=100000)
    print("\n等权分配:")
    for s, v in weights.items():
        print(f"  {s}: ${v:,.0f}")
    
    # 风险平价
    allocator = WeightAllocator('risk_parity')
    weights = allocator.allocate(symbols, prices, target_value=100000)
    print("\n风险平价:")
    for s, v in weights.items():
        print(f"  {s}: ${v:,.0f}")
    
    # 动量加权
    allocator = WeightAllocator('momentum_weighted')
    weights = allocator.allocate(symbols, prices, target_value=100000)
    print("\n动量加权:")
    for s, v in weights.items():
        print(f"  {s}: ${v:,.0f}")
    
    # 归一化示例
    targets = {'AAPL': 60000, 'MSFT': 60000}
    normalized = normalize_target_positions(targets, 100000)
    print("\n归一化目标持仓:")
    for s, v in normalized.items():
        print(f"  {s}: ${v:,.0f}")
    print(f"  总计: ${sum(normalized.values()):,.0f}")
