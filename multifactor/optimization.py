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

# 结果保存目录
OPT_DIR = os.path.join(os.path.dirname(__file__), 'optimization')
os.makedirs(OPT_DIR, exist_ok=True)


def calculate_metrics(nav_series, risk_free_rate=0.02):
    """
    计算策略绩效指标
    
    参数:
        nav_series: Series, NAV 序列
        risk_free_rate: float, 无风险利率
    
    返回:
        dict: 各项指标
    """
    returns = nav_series.pct_change().dropna()
    
    if len(returns) == 0 or returns.std() == 0:
        return {'sharpe': 0, 'cagr': 0, 'maxdd': 0, 'volatility': 0, 'calmar': 0}
    
    # 年化
    years = len(returns) / 252
    cagr = (nav_series.iloc[-1] / nav_series.iloc[0]) ** (1/years) - 1
    volatility = returns.std() * np.sqrt(252)
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
                        weight_ranges=None, n_trials=100):
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
    
    results = []
    
    # 随机采样
    for i in range(n_trials):
        # 随机生成权重
        params = {k: np.random.choice(v) for k, v in weight_ranges.items()}
        
        # 归一化
        base_sum = params['growth'] + params['quality'] + params['momentum'] + params['lowvol']
        params['growth'] /= base_sum
        params['quality'] /= base_sum
        params['momentum'] /= base_sum
        params['lowvol'] /= base_sum
        
        total_weight = params['v14_weight'] + params['ted_weight']
        if total_weight > 0.5:
            params['v14_weight'] *= 0.5 / total_weight
            params['ted_weight'] *= 0.5 / total_weight
        
        # 运行回测 (简化版)
        # 这里需要修改 main.py 支持自定义权重
        # 简化处理：只计算因子分数
        
        try:
            # 计算期末因子
            factors = factors_fn(price_df.iloc[-252:])
            
            # 简化评分
            score = pd.Series(0.0, index=factors.index)
            for name in ['growth', 'quality', 'momentum', 'lowvol']:
                if name in factors.columns:
                    score += factors[name].fillna(0.5) * params[name]
            
            # 模拟收益 (简化)
            top_stocks = score.nlargest(10).index
            future_returns = price_df.iloc[-20:][top_stocks].pct_change().mean().mean()
            
            metrics = {
                'params': params,
                'future_return': future_returns,
                'sharpe_proxy': future_returns / 0.02  # 简化
            }
            
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
            
            # 修改全局参数（简化处理）
            # 实际应传入参数到回测函数
            
            try:
                result = run_fn(price_df, market_df, set(price_df.columns[:35]))
                nav = result['nav']
                metrics = calculate_metrics(nav)
                
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
                              n_splits=5):
    """
    滚动窗口优化（前向验证）
    
    参数:
        price_df: DataFrame, 完整价格数据
        market_df: DataFrame, 完整市场数据
        run_fn: function, 回测函数
        train_size: int, 训练窗口大小
        test_size: int, 测试窗口大小
        n_splits: int, 分割次数
    
    返回:
        list: 各窗口结果
    """
    print(f"\n{'='*60}")
    print(f"滚动窗口优化 (Walk-Forward)")
    print(f"{'='*60}")
    
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
        
        # 训练期优化参数
        # 简化：使用默认参数
        
        # 测试期验证
        try:
            result = run_fn(test_price, test_market, set(test_price.columns[:35]))
            metrics = calculate_metrics(result['nav'])
            
            results.append({
                'window': i+1,
                'train_start': str(train_price.index[0]),
                'test_start': str(test_price.index[0]),
                **metrics
            })
            
            print(f"  测试期 Sharpe: {metrics['sharpe']:.3f}, CAGR: {metrics['cagr']:.2%}")
            
        except Exception as e:
            print(f"  错误: {e}")
    
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
        n_trials=20
    )
    
    if len(results) > 0:
        save_optimization_report(results)
