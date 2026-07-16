#!/usr/bin/env python3
"""
AdaptiveMomentumV3_1 回测模拟器
简化版回测，不依赖 QuantConnect/Lean
"""
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 模拟股票数据
np.random.seed(42)

def generate_price_data(tickers, start_date, end_date, initial_price=100):
    """生成模拟价格数据 - 带趋势和动量"""
    dates = pd.date_range(start=start_date, end=end_date, freq='B')
    data = {}
    
    for ticker in tickers:
        # 生成带趋势的价格
        trend = np.random.choice([-0.0002, 0.0002, 0.0005, 0.001])  # 随机趋势
        returns = np.random.normal(trend, 0.015, len(dates))
        
        # 添加动量效应（连续涨跌）
        for i in range(5, len(returns)):
            if returns[i-1] > 0 and returns[i-2] > 0:
                returns[i] += 0.001  # 上涨动量
            elif returns[i-1] < 0 and returns[i-2] < 0:
                returns[i] -= 0.001  # 下跌动量
        
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

def run_simple_backtest():
    """运行简化回测"""
    print("=" * 60)
    print("AdaptiveMomentumV3_1 简化回测")
    print("=" * 60)
    
    # 加载配置
    try:
        with open('strategy_config.json', 'r') as f:
            config = json.load(f)
        tickers = list(config['sector_map'].keys())[:50]  # 取前50只
        print(f"股票池: {len(tickers)} 只")
    except:
        tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'JPM', 'JNJ', 'V',
                   'WMT', 'PG', 'MA', 'UNH', 'HD', 'BAC', 'ABBV', 'PFE', 'KO', 'PEP']
        print(f"使用默认股票池: {len(tickers)} 只")
    
    # 参数
    lookback_periods = {'1w': 5, '2w': 10, '1m': 21, '3m': 63}
    weights = {'1w': 0.5, '2w': 1.0, '1m': 1.0, '3m': 0.7}
    initial_cash = 100000
    max_position_pct = 0.10
    max_stocks = 5
    
    # 生成数据
    print("\n生成模拟数据...")
    start_date = '2020-01-01'
    end_date = '2020-12-31'
    price_data = generate_price_data(tickers, start_date, end_date)
    
    # 回测循环
    print("运行回测...")
    cash = initial_cash
    positions = {}  # ticker -> shares
    portfolio_values = []
    
    dates = list(price_data[tickers[0]].index)
    rebalance_dates = [d for d in dates if d.day == 1]  # 每月1日
    
    for i, date in enumerate(dates):
        if i < 63:  # warmup
            portfolio_values.append((date, cash))
            continue
        
        # 再平衡
        if date in rebalance_dates or i == 63:
            # 计算动量评分
            scores = {}
            for ticker in tickers:
                prices = price_data[ticker]
                score = calculate_momentum_score(prices.iloc[:i+1], lookback_periods, weights)
                scores[ticker] = score
            
            # 清仓
            for ticker in list(positions.keys()):
                price = price_data[ticker].iloc[i]
                cash += positions[ticker] * price
                del positions[ticker]
            
            # 选择 top N
            top_tickers = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:max_stocks]
            
            # 买入新仓位
            if top_tickers and cash > 0:
                # 只选正动量的
                positive_tickers = [(t, s) for t, s in top_tickers if s > 0]
                if positive_tickers:
                    position_value = min(cash * max_position_pct, cash / len(positive_tickers))
                    for ticker, score in positive_tickers:
                        price = price_data[ticker].iloc[i]
                        if price > 0:
                            shares = int(position_value / price)
                            if shares > 0 and cash >= shares * price:
                                positions[ticker] = shares
                                cash -= shares * price
        
        # 计算组合价值
        total_value = cash
        for ticker, shares in positions.items():
            total_value += shares * price_data[ticker].iloc[i]
        portfolio_values.append((date, total_value))
    
    # 结果统计
    df = pd.DataFrame(portfolio_values, columns=['date', 'value'])
    final_value = df['value'].iloc[-1]
    total_return = (final_value / initial_cash - 1) * 100
    
    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    print(f"初始资金: ${initial_cash:,.2f}")
    print(f"最终资金: ${final_value:,.2f}")
    print(f"总收益率: {total_return:.2f}%")
    print(f"最大持仓: {max_stocks} 只")
    print(f"最大仓位: {max_position_pct*100:.0f}%")
    
    # 计算最大回撤
    peak = df['value'].expanding().max()
    drawdown = (df['value'] - peak) / peak
    max_drawdown = drawdown.min() * 100
    print(f"最大回撤: {max_drawdown:.2f}%")
    
    # 年化收益
    trading_days = len(df)
    if trading_days > 0:
        annual_return = ((final_value / initial_cash) ** (252 / trading_days) - 1) * 100
        print(f"年化收益: {annual_return:.2f}%")
    
    # 保存结果
    df.to_csv('backtest_results.csv', index=False)
    print(f"\n结果已保存到 backtest_results.csv")
    
    # 显示持仓
    if positions:
        print(f"\n最终持仓:")
        for ticker, shares in positions.items():
            price = price_data[ticker].iloc[-1]
            print(f"  {ticker}: {shares} 股, 价值 ${shares*price:,.2f}")

if __name__ == '__main__':
    run_simple_backtest()
