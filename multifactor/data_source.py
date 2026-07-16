"""
Data Source Module - Yahoo Finance 真实数据接入
支持历史价格数据、VIX、市场指标获取
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import pickle

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'data_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def get_cache_path(symbol, start, end):
    """获取缓存文件路径"""
    return os.path.join(CACHE_DIR, f"{symbol}_{start}_{end}.pkl")


def fetch_yahoo_data(symbols, start_date, end_date, use_cache=True):
    """
    从 Yahoo Finance 获取历史价格数据
    
    参数:
        symbols: list, 股票代码列表 (如 ['AAPL', 'MSFT'])
        start_date: str, 开始日期 'YYYY-MM-DD'
        end_date: str, 结束日期 'YYYY-MM-DD'
        use_cache: bool, 是否使用缓存
    
    返回:
        DataFrame: 索引=日期, 列=股票代码, 值=收盘价
    """
    price_df = pd.DataFrame()
    
    for symbol in symbols:
        cache_path = get_cache_path(symbol, start_date, end_date)
        
        # 检查缓存
        if use_cache and os.path.exists(cache_path):
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            print(f"[缓存] {symbol}: {len(data)} 条记录")
        else:
            print(f"[下载] {symbol}...", end=' ')
            try:
                ticker = yf.Ticker(symbol)
                data = ticker.history(start=start_date, end=end_date)['Close']
                print(f"{len(data)} 条记录")
                
                # 保存缓存
                if use_cache:
                    with open(cache_path, 'wb') as f:
                        pickle.dump(data, f)
            except Exception as e:
                print(f"失败: {e}")
                continue
        
        price_df[symbol] = data
    
    return price_df.dropna(how='all')


def fetch_vix_data(start_date, end_date, use_cache=True):
    """
    获取 VIX 数据 (^VIX)
    
    参数:
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
        use_cache: bool
    
    返回:
        Series: VIX 日线数据
    """
    cache_path = get_cache_path('VIX', start_date, end_date)
    
    if use_cache and os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            vix = pickle.load(f)
        print(f"[缓存] VIX: {len(vix)} 条记录")
    else:
        print("[下载] VIX...", end=' ')
        try:
            vix = yf.Ticker('^VIX').history(start=start_date, end=end_date)['Close']
            print(f"{len(vix)} 条记录")
            
            if use_cache:
                with open(cache_path, 'wb') as f:
                    pickle.dump(vix, f)
        except Exception as e:
            print(f"失败: {e}")
            return None
    
    return vix


def fetch_market_data(start_date, end_date, use_cache=True):
    """
    获取市场数据 (VIX + RSI 代理)
    
    参数:
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
    
    返回:
        DataFrame: 列=['VIX', 'RSI'], 索引=日期
    """
    vix = fetch_vix_data(start_date, end_date, use_cache)
    
    if vix is None:
        return None
    
    # 使用 SPY 的 RSI 作为市场 RSI 代理
    cache_path = get_cache_path('SPY_RSI', start_date, end_date)
    
    if use_cache and os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            spy = pickle.load(f)
    else:
        print("[下载] SPY (用于 RSI)...", end=' ')
        spy = yf.Ticker('SPY').history(start=start_date, end=end_date)['Close']
        print(f"{len(spy)} 条记录")
        
        if use_cache:
            with open(cache_path, 'wb') as f:
                pickle.dump(spy, f)
    
    # 计算 RSI
    delta = spy.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    # 合并数据
    market_df = pd.DataFrame({
        'VIX': vix,
        'RSI': rsi
    }).dropna()
    
    return market_df


def prepare_backtest_data(tickers, start_date, end_date, use_cache=True):
    """
    准备回测所需的所有数据
    
    参数:
        tickers: list, 股票代码列表
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
    
    返回:
        tuple: (price_df, market_df)
    """
    print(f"\n{'='*60}")
    print(f"准备回测数据: {start_date} ~ {end_date}")
    print(f"{'='*60}")
    
    # 获取价格数据
    price_df = fetch_yahoo_data(tickers, start_date, end_date, use_cache)
    
    # 获取市场数据
    market_df = fetch_market_data(start_date, end_date, use_cache)
    
    # 对齐日期
    common_dates = price_df.index.intersection(market_df.index)
    price_df = price_df.loc[common_dates]
    market_df = market_df.loc[common_dates]
    
    print(f"\n[完成] 价格数据: {len(price_df)} 个交易日")
    print(f"[完成] 市场数据: {len(market_df)} 个交易日")
    print(f"[完成] 股票数量: {len(price_df.columns)}")
    
    return price_df, market_df


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    from main import TICKERS
    
    # 准备最近5年的数据
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')
    
    price_df, market_df = prepare_backtest_data(TICKERS, start, end)
    
    print(f"\n数据预览:")
    print(f"价格数据前5行:\n{price_df.head()}")
    print(f"\nVIX 前5行:\n{market_df['VIX'].head()}")
