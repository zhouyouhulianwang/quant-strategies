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
        协方差风险平价 - 使用完整协方差矩阵，使每只标的风险贡献相等

        优化目标: w_i * (Σw)_i 对所有 i 近似相等
        这里采用迭代法求解，避免引入 scipy 等重依赖。
        """
        if price_df is None or len(price_df) < 40:
            logger.warning("价格数据不足，回退到等权")
            return self._equal_weight(symbols)

        available = list(set(symbols) & set(price_df.columns))
        if len(available) == 0:
            return self._equal_weight(symbols)

        returns = price_df[available].pct_change().dropna()

        if len(returns) < 40:
            return self._equal_weight(symbols)

        # 年化协方差矩阵，ridge 正则化保证正定性
        cov = returns.cov().values * 252
        ridge = 1e-6
        cov = cov + np.eye(cov.shape[0]) * ridge
        idx = pd.Index(available)

        # 初始权重：逆波动率
        vols = np.sqrt(np.diag(cov))
        inv_vols = 1.0 / np.where(vols == 0, np.inf, vols)
        w = inv_vols / inv_vols.sum()

        # 迭代求解风险平价
        for _ in range(100):
            portfolio_var = float(w.T @ cov @ w)
            if portfolio_var <= 0:
                break
            sigma = np.sqrt(portfolio_var)
            mrc = (cov @ w) / sigma
            rc = w * mrc
            rc_mean = rc.mean()
            if rc_mean <= 0:
                break
            w_new = w * (rc_mean / rc)
            w_new = w_new / w_new.sum()
            if np.max(np.abs(w_new - w)) < 1e-8:
                break
            w = w_new

        weights = pd.Series(w, index=idx)
        weights = weights / weights.sum()

        result = {}
        for s in symbols:
            result[s] = weights.get(s, 0.0)

        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}
        else:
            result = self._equal_weight(symbols)

        return result
    
    def _inverse_vol_risk_parity_weight(self, symbols, price_df):
        """
        简化风险平价 - 反比于波动率（保留作为 fallback/对比基准）
        """
        if price_df is None or len(price_df) < 20:
            logger.warning("价格数据不足，回退到等权")
            return self._equal_weight(symbols)

        available = list(set(symbols) & set(price_df.columns))
        if len(available) == 0:
            return self._equal_weight(symbols)

        returns = price_df[available].pct_change().dropna()
        if len(returns) < 20:
            return self._equal_weight(symbols)

        vols = returns.std() * np.sqrt(252)
        inv_vols = 1.0 / vols.replace(0, np.inf)
        weights = inv_vols / inv_vols.sum()
        weights = weights / weights.sum()

        result = {s: weights.get(s, 0.0) for s in symbols}
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


def apply_volatility_target(target_positions, price_df, target_vol=0.20, lookback=60):
    """对目标持仓应用目标波动率控制（专业量化系统的常见风控 overlay）。

    计算选中标的在 lookback 窗口内的协方差矩阵，并估计组合年化波动率。
    若估计波动率高于 target_vol，则按比例压缩所有持仓，使组合波动率
    回落至目标水平；否则保持不变。

    参数:
        target_positions: dict, {symbol: target_value}
        price_df: DataFrame, 历史价格数据
        target_vol: float, 目标年化波动率（默认 20%）
        lookback: int, 计算协方差的历史交易日长度（默认 60）

    返回:
        dict, 缩放后的目标持仓
    """
    if not target_positions or price_df is None or price_df.empty:
        return target_positions

    symbols = [s for s in target_positions if s in price_df.columns]
    if len(symbols) < 2:
        return target_positions

    total = sum(target_positions.values())
    if total <= 0:
        return target_positions

    weights = pd.Series({s: target_positions[s] / total for s in symbols})
    returns = price_df[symbols].iloc[-lookback:].pct_change().dropna()
    if len(returns) < 20:
        return target_positions

    cov = returns.cov() * 252
    # 使用样本协方差；若矩阵奇异，使用 Ledoit-Wolf 收缩或伪逆
    try:
        port_var = weights.T @ cov @ weights
    except Exception:
        return target_positions

    if port_var <= 0 or np.isnan(port_var):
        return target_positions

    port_vol = np.sqrt(port_var)
    if port_vol <= target_vol:
        return target_positions

    scale = target_vol / port_vol
    scaled = {s: v * scale for s, v in target_positions.items()}
    logger.info(f"[VOL_TARGET] 估计组合波动率 {port_vol:.2%} > 目标 {target_vol:.2%}, "
                f"整体缩放至 {scale:.2%}")
    return scaled


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


def apply_sector_constraints(weights, sectors, max_sector_pct=0.30, max_iter=20):
    """应用行业（板块）权重约束，将超配行业的权重按比例分配给低配行业。

    参数:
        weights: dict, {symbol: weight} 原始权重（未归一化亦可，内部会归一化）
        sectors: dict, {symbol: sector} 标的到行业的映射（通常使用 main.INDUSTRY）
        max_sector_pct: float, 单个行业最大权重占比（默认 30%）
        max_iter: int, 迭代上限（防止不收敛时死循环）

    返回:
        dict: 约束后的权重（已归一化）
    """
    if not weights:
        return {}

    # 归一化输入权重
    total = sum(weights.values())
    if total <= 0:
        return {}
    constrained = {k: v / total for k, v in weights.items()}

    for _ in range(max_iter):
        # 计算当前行业权重
        sector_weights = {}
        for s, w in constrained.items():
            sec = sectors.get(s, 'other')
            sector_weights[sec] = sector_weights.get(sec, 0.0) + w

        # 检查是否有行业超限
        overweight = {sec: w for sec, w in sector_weights.items() if w > max_sector_pct}
        if not overweight:
            break

        # 收集低配行业（可用于吸收超额权重）
        underweight_secs = [sec for sec in sector_weights if sector_weights[sec] < max_sector_pct]
        if not underweight_secs:
            # 所有行业都已达到或超过上限，无法进一步分配，直接截断
            break

        # 计算超额总量与低配行业可用空间
        excess_total = sum(sector_weights[sec] - max_sector_pct for sec in overweight)
        underweight_space = {sec: max_sector_pct - sector_weights[sec] for sec in underweight_secs}
        total_space = sum(underweight_space.values())

        if total_space <= 0:
            break

        # 按比例将超额权重分配给低配行业
        new_weights = constrained.copy()
        for sec in overweight:
            excess = sector_weights[sec] - max_sector_pct
            scale = max_sector_pct / sector_weights[sec]
            for s in constrained:
                if sectors.get(s, 'other') == sec:
                    new_weights[s] = constrained[s] * scale

        # 将释放出的权重按比例分配给低配行业内的标的
        for sec in underweight_secs:
            add_pct = excess_total * (underweight_space[sec] / total_space)
            # 在该行业内按标的原权重比例分配
            sector_symbols = [s for s in constrained if sectors.get(s, 'other') == sec]
            if not sector_symbols:
                continue
            sector_total = sum(constrained[s] for s in sector_symbols)
            if sector_total <= 0:
                # 若该行业原权重为 0，则等权分配
                for s in sector_symbols:
                    new_weights[s] = new_weights.get(s, 0.0) + add_pct / len(sector_symbols)
            else:
                for s in sector_symbols:
                    new_weights[s] = constrained[s] + add_pct * (constrained[s] / sector_total)

        # 归一化并检查收敛
        new_total = sum(new_weights.values())
        if new_total <= 0:
            break
        new_weights = {k: v / new_total for k, v in new_weights.items()}
        if all(abs(new_weights.get(k, 0) - constrained.get(k, 0)) < 1e-6 for k in new_weights):
            constrained = new_weights
            break
        constrained = new_weights

    return constrained


def apply_factor_exposure_caps(weights, factor_exposures, factor_caps=None):
    """对组合因子暴露进行上限约束（可选）。

    计算组合在 17 个因子上的加权平均暴露，若某因子超过上限，则按比例
    降低该因子上暴露较高的标的权重，并将释放的权重分配给暴露较低的标的。

    参数:
        weights: dict, {symbol: weight} 当前权重（未归一化亦可）
        factor_exposures: DataFrame, 索引=symbol, 列=17个因子（通常为 percentile 0-1）
        factor_caps: dict or None, {factor_name: max_weighted_avg_exposure}
            若为 None，则不进行任何约束（no-op）。

    返回:
        dict: 约束后的权重（已归一化）
    """
    if not weights or factor_exposures is None or factor_caps is None:
        return weights

    # 归一化输入
    total = sum(weights.values())
    if total <= 0:
        return weights
    w = pd.Series(weights).div(total)

    # 对齐因子数据与权重标的
    common = w.index.intersection(factor_exposures.index)
    if len(common) == 0:
        return weights

    w = w.loc[common]
    exposures = factor_exposures.loc[common]

    # 计算当前组合因子暴露
    port_exposure = (w.values[:, None] * exposures.values).sum(axis=0)
    port_exposure = pd.Series(port_exposure, index=exposures.columns)

    # 找出超限因子
    violations = {}
    for factor, cap in factor_caps.items():
        if factor not in port_exposure.index:
            continue
        if port_exposure[factor] > cap:
            violations[factor] = port_exposure[factor] - cap

    if not violations:
        return weights

    # 对每个超限因子，降低高暴露标的权重，分配给低暴露标的
    adjusted = w.copy()
    for factor, excess in violations.items():
        if factor not in exposures.columns:
            continue
        exp = exposures[factor]
        # 高暴露组（高于当前组合暴露）与低暴露组
        high_mask = exp > port_exposure[factor]
        low_mask = exp <= port_exposure[factor]
        if not high_mask.any() or not low_mask.any():
            continue

        high_total = adjusted[high_mask].sum()
        low_total = adjusted[low_mask].sum()
        if high_total <= 0 or low_total <= 0:
            continue

        # 高暴露组按暴露比例削减
        high_reduction = min(excess, high_total * 0.5)  # 单次最多削减一半，防止震荡
        high_weights = adjusted[high_mask]
        reduction_share = high_weights * (exp[high_mask] / exp[high_mask].sum())
        reduction_share = reduction_share / reduction_share.sum() * high_reduction

        adjusted[high_mask] = high_weights - reduction_share
        # 分配给低暴露组（按反向暴露比例，即暴露越低分得越多）
        low_inv = 1.0 / (exp[low_mask] + 1e-6)
        low_share = low_inv / low_inv.sum() * high_reduction
        adjusted[low_mask] = adjusted[low_mask] + low_share

    # 清理负权重并归一化
    adjusted = adjusted.clip(lower=0.0)
    adj_total = adjusted.sum()
    if adj_total <= 0:
        return weights
    adjusted = adjusted / adj_total

    return adjusted.to_dict()


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
                            sectors=None, max_sector_pct=0.30,
                            factor_exposures=None, factor_caps=None,
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

    # 行业集中度约束：使用 main.INDUSTRY 映射（若未提供则尝试导入）
    if sectors is None:
        try:
            from main import INDUSTRY
            sectors = INDUSTRY
        except ImportError:
            sectors = {}
    if sectors:
        weights = apply_sector_constraints(weights, sectors, max_sector_pct=max_sector_pct)

    # 因子暴露约束（可选，默认 no-op）
    if factor_exposures is not None and factor_caps is not None:
        weights = apply_factor_exposure_caps(weights, factor_exposures, factor_caps)

    result = {s: total_equity * w for s, w in weights.items()}
    result = normalize_target_positions(result, total_equity, min_position_value=0)

    # P1专业优化: 目标波动率 overlay —— 若组合估计波动率高于目标，则整体降仓
    if result:
        hist_slice = price_df.loc[:exec_date]
        result = apply_volatility_target(result, hist_slice, target_vol=0.20, lookback=60)

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
