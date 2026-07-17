"""
参数优化模块 - 超参数搜索和策略优化
支持网格搜索、随机搜索、因子权重优化
"""

import numpy as np
import pandas as pd
from itertools import product
from datetime import datetime
import json
import os
import inspect
import logging

# P2修复：统一全链路日志格式
from logging_config import setup_logging
setup_logging()

logger = logging.getLogger('optimization')

# 结果保存目录
OPT_DIR = os.path.join(os.path.dirname(__file__), 'optimization')
os.makedirs(OPT_DIR, exist_ok=True)


def _build_run_fn_kwargs(run_fn, params):
    """
    P1修复: 根据 run_fn 的签名，只透传它实际接受的参数。
    这样既能将 vix_low/vix_high 等参数传给支持它们的 run_fn，
    又能在 run_fn 不兼容时优雅回退，避免 TypeError。
    """
    try:
        sig = inspect.signature(run_fn)
    except (ValueError, TypeError):
        return {}

    accepts_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    kwargs = {}
    for k, v in params.items():
        if k in sig.parameters or accepts_var_keyword:
            kwargs[k] = v
    return kwargs


def _infer_frequency(nav_series):
    """根据索引推断 NAV 频率（年化期数）"""
    if not isinstance(nav_series.index, pd.DatetimeIndex):
        return 252
    try:
        freq = pd.infer_freq(nav_series.index)
    except Exception:
        freq = None
    if freq is None:
        return 252
    freq = freq.upper()
    if 'M' in freq:
        return 12
    if any(x in freq for x in ('D', 'B', 'W', 'C')):
        return 252
    return 252


def calculate_metrics(nav_series, risk_free_rate=0.02, frequency=None):
    """
    计算策略绩效指标

    参数:
        nav_series: Series, NAV 序列
        risk_free_rate: float, 无风险利率
        frequency: str, 频率 'M' 月度 / 'D' 日度，None 则自动检测

    返回:
        dict: 各项指标
    """
    returns = nav_series.pct_change().dropna()

    if len(returns) == 0 or returns.std() == 0:
        return {'sharpe': 0, 'cagr': 0, 'maxdd': 0, 'volatility': 0, 'calmar': 0}

    # 年化
    if frequency is None:
        periods = _infer_frequency(nav_series)
    else:
        freq = str(frequency).upper()
        if freq in ('M', 'MONTH', 'MONTHLY', 'BM', 'BME', 'MS'):
            periods = 12
        elif freq in ('D', 'DAY', 'DAILY', 'B', 'C'):
            periods = 252
        else:
            periods = _infer_frequency(nav_series)

    years = len(returns) / periods
    cagr = (nav_series.iloc[-1] / nav_series.iloc[0]) ** (1/years) - 1
    volatility = returns.std() * np.sqrt(periods)
    sharpe = (cagr - risk_free_rate) / volatility if volatility > 0 else 0

    # 最大回撤
    running_max = nav_series.cummax()
    drawdown = (nav_series / running_max - 1)
    maxdd = drawdown.min()

    # Calmar 比率
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0

    # 胜率
    win_rate = (returns > 0).mean()

    # 盈亏比
    avg_gain = returns[returns > 0].mean()
    avg_loss = abs(returns[returns < 0].mean())
    profit_factor = avg_gain / avg_loss if avg_loss > 0 else 0

    return {
        'cagr': cagr,
        'sharpe': sharpe,
        'maxdd': maxdd,
        'volatility': volatility,
        'calmar': calmar,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'final_nav': nav_series.iloc[-1],
    }


def grid_search_weights(factors_fn, composite_fn, price_df, market_df, ndx_set,
                        weight_ranges=None, n_trials=100, cost_model=None, weight_allocator=None):
    """
    网格搜索因子权重

    参数:
        factors_fn: function, 计算因子的函数
        composite_fn: function, 综合评分函数
        price_df: DataFrame, 价格数据
        market_df: DataFrame, 市场数据
        ndx_set: set, NDX股票
        weight_ranges: dict, 权重搜索范围
        n_trials: int, 搜索次数
        cost_model: TradingCostModel, 交易成本模型（可选）
        weight_allocator: WeightAllocator, 权重分配器（可选）

    返回:
        DataFrame: 最优参数组合
    """
    if weight_ranges is None:
        # 默认搜索基础权重
        weight_ranges = {
            'growth': [0.08, 0.12, 0.16],
            'quality': [0.06, 0.10, 0.14],
            'momentum': [0.06, 0.10, 0.14],
            'lowvol': [0.04, 0.08, 0.12],
            'v14_weight': [0.18, 0.22, 0.26],
            'ted_weight': [0.14, 0.18, 0.22],
        }

    print(f"\n{'='*60}")
    print(f"网格搜索参数优化")
    print(f"{'='*60}")
    print(f"搜索空间: {len(list(product(*weight_ranges.values())))} 种组合")
    print(f"实际尝试: {n_trials} 次\n")

    # Walk-forward 分割：训练期与评估期不重叠
    if len(price_df) < 252 + 60:
        raise ValueError("价格数据不足，至少需要 252+60 个交易日")
    if price_df.columns.duplicated().any():
        price_df = price_df.loc[:, ~price_df.columns.duplicated()].copy()

    split_idx = max(int(len(price_df) * 0.7), 252)
    split_date = price_df.index[split_idx]
    train_price = price_df.iloc[:split_idx + 1]
    test_price = price_df.iloc[split_idx:]
    train_market = market_df.loc[:split_date]
    try:
        vix_v = float(train_market['VIX'].iloc[-1])
    except Exception:
        vix_v = 20.0

    results = []

    # 随机采样
    for i in range(n_trials):
        # 随机生成权重
        params = {k: np.random.choice(v) for k, v in weight_ranges.items()}

        # 归一化
        base_sum = (params.get('growth', 0) + params.get('quality', 0) +
                    params.get('momentum', 0) + params.get('lowvol', 0))
        if base_sum > 0:
            params['growth'] /= base_sum
            params['quality'] /= base_sum
            params['momentum'] /= base_sum
            params['lowvol'] /= base_sum

        total_weight = params.get('v14_weight', 0) + params.get('ted_weight', 0)
        if total_weight > 0.5:
            params['v14_weight'] = params.get('v14_weight', 0) * 0.5 / total_weight
            params['ted_weight'] = params.get('ted_weight', 0) * 0.5 / total_weight

        try:
            # 训练期计算因子（只用 split_date 之前数据）
            factors = factors_fn(train_price)

            # 自定义评分
            score = pd.Series(0.0, index=factors.index)
            for name in ['growth', 'quality', 'momentum', 'lowvol']:
                if name in factors.columns:
                    score += factors[name].fillna(0.5) * params[name]

            # 选股
            selected = score.dropna().nlargest(10).index.tolist()
            if len(selected) == 0:
                continue

            # 权重分配
            if weight_allocator is not None:
                weights = weight_allocator.allocate(selected, price_df=train_price, target_value=1.0)
            else:
                weights = {s: 1.0 / len(selected) for s in selected}

            weights = pd.Series(weights)
            if weights.sum() <= 0:
                continue
            weights = weights / weights.sum()

            # 评估期收益（split_date 之后，与训练期无重叠）
            common = test_price.columns.intersection(weights.index)
            if len(common) == 0:
                continue
            weights = weights[common]
            test_prices = test_price[common]
            port_returns = (test_prices.pct_change().fillna(0) * weights.values).sum(axis=1)

            # 交易成本
            if cost_model is not None:
                total_value = 1_000_000.0
                target_positions = {s: total_value * w for s, w in weights.items()}
                current_prices = test_prices.iloc[0].to_dict()
                if hasattr(cost_model, 'calculate_rebalance_cost'):
                    cost_info = cost_model.calculate_rebalance_cost(target_positions, {}, current_prices)
                    cost_pct = cost_info.get('cost_pct', 0)
                else:
                    cost_info = cost_model.estimate_portfolio_cost(target_positions, {})
                    cost_pct = cost_info['total_cost'] / total_value if total_value > 0 else 0
                port_returns.iloc[0] -= cost_pct

            nav = (1 + port_returns).cumprod()
            nav = pd.concat([pd.Series([1.0], index=[test_price.index[0]]), nav])

            metrics = calculate_metrics(nav)
            metrics.update({
                'params': dict(params),
                'sharpe_proxy': metrics['sharpe'],
                'future_return': (nav.iloc[-1] / nav.iloc[0]) - 1,
            })
            results.append(metrics)
        except Exception as e:
            continue

        if (i + 1) % 20 == 0:
            print(f"进度: {i+1}/{n_trials}")

    # 排序并返回最优
    results_df = pd.DataFrame(results)
    if len(results_df) > 0:
        results_df = results_df.sort_values('sharpe_proxy', ascending=False)

        print(f"\n{'='*60}")
        print(f"最优参数 (Top 5)")
        print(f"{'='*60}")
        for idx, row in results_df.head().iterrows():
            print(f"\n排名 {idx+1}:")
            print(f"  Sharpe Proxy: {row['sharpe_proxy']:.3f}")
            print(f"  CAGR: {row.get('cagr', 0):.2%}")
            print(f"  MaxDD: {row.get('maxdd', 0):.2%}")
            print(f"  参数: {row['params']}")

    return results_df


def optimize_vix_thresholds(price_df, market_df, run_fn, 
                            vix_low_range=(12, 20), 
                            vix_high_range=(25, 40),
                            n_points=10):
    """
    优化 VIX 阈值参数
    
    参数:
        price_df: DataFrame, 价格数据
        market_df: DataFrame, 市场数据
        run_fn: function, 回测函数
        vix_low_range: tuple, 低VIX范围
        vix_high_range: tuple, 高VIX范围
        n_points: int, 采样点数
    
    返回:
        DataFrame: 最优阈值组合
    """
    print(f"\n{'='*60}")
    print(f"VIX 阈值优化")
    print(f"{'='*60}")
    
    vix_low_values = np.linspace(vix_low_range[0], vix_low_range[1], n_points)
    vix_high_values = np.linspace(vix_high_range[0], vix_high_range[1], n_points)
    
    results = []
    total = len(vix_low_values) * len(vix_high_values)
    count = 0
    
    for vix_low in vix_low_values:
        for vix_high in vix_high_values:
            if vix_high <= vix_low:
                continue
            
            count += 1
            
            # P1修复: 将 vix_low / vix_high 透传给 run_fn
            # run_fn 必须接受这两个参数才能真正优化；
            # 若不支持，通过 _build_run_fn_kwargs 回退到默认参数并打印警告。
            try:
                kwargs = _build_run_fn_kwargs(run_fn, {'vix_low': vix_low, 'vix_high': vix_high})
                if 'vix_low' not in kwargs or 'vix_high' not in kwargs:
                    logger.warning(f"run_fn {run_fn} 不接受 vix_low/vix_high 参数，VIX 阈值优化无效")
                result = run_fn(price_df, market_df, set(price_df.columns[:35]), **kwargs)
                nav = result['nav']
                metrics = calculate_metrics(nav, frequency='M')
                
                results.append({
                    'vix_low': vix_low,
                    'vix_high': vix_high,
                    **metrics
                })
                
            except Exception as e:
                continue
            
            if count % 10 == 0:
                print(f"进度: {count}/{total}")
    
    results_df = pd.DataFrame(results)
    if len(results_df) > 0:
        results_df = results_df.sort_values('sharpe', ascending=False)
        
        print(f"\n{'='*60}")
        print(f"最优 VIX 阈值 (Top 5)")
        print(f"{'='*60}")
        print(results_df[['vix_low', 'vix_high', 'sharpe', 'cagr', 'maxdd']].head().to_string(index=False))
    
    return results_df


def walk_forward_optimization(price_df, market_df, run_fn, 
                              train_size=252*2, test_size=252,
                              n_splits=5, param_grid=None):
    """
    滚动窗口优化（前向验证）
    P1修复: 在训练窗口内真实搜索参数，再在测试窗口验证，实现真正的 walk-forward。
    
    参数:
        price_df: DataFrame, 完整价格数据
        market_df: DataFrame, 完整市场数据
        run_fn: function, 回测函数，需支持 (price_df, market_df, ndx_set, **params)
        train_size: int, 训练窗口大小
        test_size: int, 测试窗口大小
        n_splits: int, 分割次数
        param_grid: dict, 参数搜索空间（默认 VIX 阈值）
    
    返回:
        DataFrame: 各窗口结果
    """
    print(f"\n{'='*60}")
    print(f"滚动窗口优化 (Walk-Forward)")
    print(f"{'='*60}")
    
    if param_grid is None:
        # 默认优化 VIX 阈值
        param_grid = {
            'vix_low': [12, 15, 18],
            'vix_high': [25, 30, 35],
        }
    
    n = len(price_df)
    results = []
    
    for i in range(n_splits):
        train_end = train_size + i * test_size
        test_end = train_end + test_size
        
        if test_end > n:
            break
        
        train_price = price_df.iloc[:train_end]
        train_market = market_df.iloc[:train_end]
        test_price = price_df.iloc[train_end:test_end]
        test_market = market_df.iloc[train_end:test_end]
        
        print(f"\n窗口 {i+1}/{n_splits}:")
        print(f"  训练: {train_price.index[0]} ~ {train_price.index[-1]}")
        print(f"  测试: {test_price.index[0]} ~ {test_price.index[-1]}")
        
        # P1修复: 在训练期真实搜索参数
        best_params = None
        best_score = -np.inf
        param_names = list(param_grid.keys())
        all_combinations = list(product(*param_grid.values()))
        
        if not all_combinations:
            print("  参数空间为空，跳过")
            continue
        
        for values in all_combinations:
            params = dict(zip(param_names, values))
            try:
                kwargs = _build_run_fn_kwargs(run_fn, params)
                result = run_fn(train_price, train_market, set(train_price.columns[:35]), **kwargs)
                metrics = calculate_metrics(result['nav'], frequency='M')
                score = metrics['sharpe']
                if score > best_score:
                    best_score = score
                    best_params = params
            except Exception as e:
                continue
        
        # P1修复: 在测试期使用训练得到的最优参数验证
        if best_params is not None:
            try:
                kwargs = _build_run_fn_kwargs(run_fn, best_params)
                result = run_fn(test_price, test_market, set(test_price.columns[:35]), **kwargs)
                metrics = calculate_metrics(result['nav'], frequency='M')
                
                results.append({
                    'window': i+1,
                    'train_start': str(train_price.index[0]),
                    'test_start': str(test_price.index[0]),
                    'best_params': json.dumps(best_params),
                    **metrics
                })
                
                print(f"  训练最优参数: {best_params}")
                print(f"  测试期 Sharpe: {metrics['sharpe']:.3f}, CAGR: {metrics['cagr']:.2%}")
                
            except Exception as e:
                print(f"  测试错误: {e}")
        else:
            print("  未找到有效参数")
    
    return pd.DataFrame(results)


def save_optimization_report(results_df, filename=None):
    """保存优化报告"""
    if filename is None:
        filename = f"opt_report_{datetime.now():%Y%m%d_%H%M%S}.csv"
    
    filepath = os.path.join(OPT_DIR, filename)
    results_df.to_csv(filepath, index=False)
    print(f"✅ 优化报告已保存: {filepath}")
    return filepath


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    from main import compute_factors_v14, v14_composite_score, run_v14
    import numpy as np
    from cost_model import TradingCostModel
    from weight_allocation import WeightAllocator

    # 创建模拟数据
    np.random.seed(42)
    dates = pd.bdate_range('2020-01-01', '2023-12-31')
    n = len(dates)

    tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META'] * 8

    prices = np.cumprod(1 + np.random.normal(0.0005, 0.02, (n, len(tickers))), axis=0)
    price_df = pd.DataFrame(prices, index=dates, columns=tickers)

    vix = np.clip(15 + np.cumsum(np.random.normal(0, 0.5, n)) * 0.08, 9, 55)
    market_df = pd.DataFrame({'VIX': vix, 'RSI': np.random.uniform(30, 70, n)}, index=dates)

    # 运行简单优化
    print("运行参数优化示例...")
    results = grid_search_weights(
        compute_factors_v14,
        v14_composite_score,
        price_df, market_df, set(tickers[:4]),
        n_trials=20,
        cost_model=TradingCostModel(),
        weight_allocator=WeightAllocator('equal'),
    )

    if len(results) > 0:
        save_optimization_report(results)