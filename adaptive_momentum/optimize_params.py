#!/usr/bin/env python3
"""
AdaptiveMomentumV3_1 参数优化器
测试不同参数组合的回测表现
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json

def generate_price_data(tickers, start_date, end_date, initial_price=100):
    """生成模拟价格数据"""
    dates = pd.date_range(start=start_date, end=end_date, freq='B')
    data = {}
    for ticker in tickers:
        trend = np.random.choice([-0.0002, 0.0002, 0.0005, 0.001])
        returns = np.random.normal(trend, 0.015, len(dates))
        for i in range(5, len(returns)):
            if returns[i-1] > 0 and returns[i-2] > 0:
                returns[i] += 0.001
            elif returns[i-1] < 0 and returns[i-2] < 0:
                returns[i] -= 0.001
        prices = initial_price * np.exp(np.cumsum(returns))
        data[ticker] = pd.Series(prices, index=dates)
    return data

def calculate_momentum_score(prices, lookback_periods, weights):
    """计算动量评分"""
    scores = {}
    for period_name, days in lookback_periods.items():
        if len(prices) > days:
            ret = (prices.iloc[-1] / prices.iloc[-days-1]) - 1
            scores[period_name] = ret * weights[period_name]
    return sum(scores.values())

def run_backtest(tickers, price_data, params):
    """运行回测"""
    initial_cash = 100000
    cash = initial_cash
    positions = {}
    portfolio_values = []
    dates = list(price_data[tickers[0]].index)
    rebalance_dates = [d for d in dates if d.day == 1]
    
    for i, date in enumerate(dates):
        if i < 63:
            portfolio_values.append((date, cash))
            continue
        
        if date in rebalance_dates or i == 63:
            scores = {}
            for ticker in tickers:
                prices = price_data[ticker]
                score = calculate_momentum_score(prices.iloc[:i+1], params['lookback'], params['weights'])
                scores[ticker] = score
            
            for ticker in list(positions.keys()):
                price = price_data[ticker].iloc[i]
                cash += positions[ticker] * price
                del positions[ticker]
            
            top_tickers = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:params['max_stocks']]
            
            if top_tickers and cash > 0:
                positive_tickers = [(t, s) for t, s in top_tickers if s > 0]
                if positive_tickers:
                    position_value = min(cash * params['max_position_pct'], cash / len(positive_tickers))
                    for ticker, score in positive_tickers:
                        price = price_data[ticker].iloc[i]
                        if price > 0:
                            shares = int(position_value / price)
                            if shares > 0 and cash >= shares * price:
                                positions[ticker] = shares
                                cash -= shares * price
        
        total_value = cash
        for ticker, shares in positions.items():
            total_value += shares * price_data[ticker].iloc[i]
        portfolio_values.append((date, total_value))
    
    df = pd.DataFrame(portfolio_values, columns=['date', 'value'])
    final_value = df['value'].iloc[-1]
    total_return = (final_value / initial_cash - 1) * 100
    
    peak = df['value'].expanding().max()
    drawdown = (df['value'] - peak) / peak
    max_drawdown = drawdown.min() * 100
    
    trading_days = len(df)
    annual_return = ((final_value / initial_cash) ** (252 / trading_days) - 1) * 100
    
    return {
        'total_return': total_return,
        'max_drawdown': max_drawdown,
        'annual_return': annual_return,
        'final_value': final_value
    }

def optimize_params():
    """参数优化"""
    print("=" * 70)
    print("AdaptiveMomentumV3_1 参数优化")
    print("=" * 70)
    
    # 加载股票池
    try:
        with open('strategy_config.json', 'r') as f:
            config = json.load(f)
        tickers = list(config['sector_map'].keys())[:30]
    except:
        tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'JPM', 'JNJ', 'V',
                   'WMT', 'PG', 'MA', 'UNH', 'HD', 'BAC', 'ABBV', 'PFE', 'KO', 'PEP']
    
    # 生成数据
    print("生成模拟数据...")
    price_data = generate_price_data(tickers, '2020-01-01', '2020-12-31')
    
    # 参数组合
    param_grid = []
    for max_stocks in [3, 5, 7, 10]:
        for max_position_pct in [0.05, 0.10, 0.15, 0.20]:
            for lookback_weeks in [4, 5, 6]:
                for lookback_months in [21, 30]:
                    params = {
                        'max_stocks': max_stocks,
                        'max_position_pct': max_position_pct,
                        'lookback': {
                            '1w': lookback_weeks,
                            '2w': lookback_weeks * 2,
                            '1m': lookback_months,
                            '3m': lookback_months * 3
                        },
                        'weights': {
                            '1w': 0.5,
                            '2w': 1.0,
                            '1m': 1.0,
                            '3m': 0.7
                        }
                    }
                    param_grid.append(params)
    
    print(f"测试 {len(param_grid)} 组参数...")
    
    results = []
    for i, params in enumerate(param_grid):
        result = run_backtest(tickers, price_data, params)
        result['params'] = params
        results.append(result)
        
        if (i + 1) % 10 == 0:
            print(f"  已完成 {i+1}/{len(param_grid)}")
    
    # 按收益排序
    results.sort(key=lambda x: x['total_return'], reverse=True)
    
    print("\n" + "=" * 70)
    print("Top 10 参数组合")
    print("=" * 70)
    print(f"{'排名':<4} {'收益':<8} {'回撤':<8} {'年化':<8} {'持仓':<6} {'仓位':<6}")
    print("-" * 70)
    
    for i, r in enumerate(results[:10], 1):
        p = r['params']
        print(f"{i:<4} {r['total_return']:>+7.2f}% {r['max_drawdown']:>7.2f}% {r['annual_return']:>+7.2f}% {p['max_stocks']:>5} {p['max_position_pct']*100:>5.0f}%")
    
    # 最优参数
    best = results[0]
    print("\n" + "=" * 70)
    print("最优参数:")
    print("=" * 70)
    print(f"最大持仓数: {best['params']['max_stocks']}")
    print(f"最大仓位: {best['params']['max_position_pct']*100:.0f}%")
    print(f"回望周期: 1w={best['params']['lookback']['1w']}, 1m={best['params']['lookback']['1m']}")
    print(f"预期收益: {best['total_return']:+.2f}%")
    print(f"最大回撤: {best['max_drawdown']:.2f}%")
    print(f"年化收益: {best['annual_return']:+.2f}%")
    
    return best

if __name__ == '__main__':
    optimize_params()
