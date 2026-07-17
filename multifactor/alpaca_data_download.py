"""
Alpaca Market Data 历史数据下载器
使用 Alpaca Paper Trading 账户免费获取历史日线数据

免费限制: 200 requests/minute
38 只股票约需 38 个请求，可以一次下载
"""

import os
import time
import pandas as pd
from datetime import datetime, timedelta
from alpaca_trade_api import REST, TimeFrame
import logging

# 设置日志（P2修复：统一使用 logging_config 的格式）
logger = logging.getLogger(__name__)

# 股票列表（从 main.py 导入，支持 config.json 配置化）
from main import TICKERS

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'alpaca')
os.makedirs(DATA_DIR, exist_ok=True)


def download_alpaca_data(ticker, start_date, end_date, api_key=None, api_secret=None):
    """
    从 Alpaca 下载历史日线数据
    
    参数:
        ticker: str, 股票代码
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
        api_key: str, Alpaca API Key (默认从环境变量)
        api_secret: str, Alpaca API Secret
    
    返回:
        DataFrame: 日线数据 (date, open, high, low, close, volume)
    """
    api_key = api_key or os.getenv('ALPACA_API_KEY')
    api_secret = api_secret or os.getenv('ALPACA_API_SECRET')
    
    if not api_key or not api_secret:
        raise ValueError("请提供 Alpaca API Key 和 Secret")
    
    api = REST(api_key, api_secret, 'https://paper-api.alpaca.markets')
    
    try:
        # 获取历史 bars（日线）
        bars = api.get_bars(
            ticker,
            TimeFrame.Day,
            start=start_date,
            end=end_date,
            adjustment='all'  # 考虑股票拆分和分红
        ).df
        
        if bars is None or len(bars) == 0:
            logger.warning(f"⚠️ {ticker}: 无数据")
            return None
        
        # 重置索引，将时间变为列
        bars = bars.reset_index()
        bars.rename(columns={
            'timestamp': 'date',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        }, inplace=True)
        
        logger.info(f"✅ {ticker}: {len(bars)} 个交易日 {bars['date'].min()} ~ {bars['date'].max()}")
        return bars
        
    except Exception as e:
        logger.error(f"❌ {ticker}: 下载失败 - {e}")
        return None


def download_all(tickers, start_date, end_date, sleep_sec=0.5):
    """
    批量下载所有股票数据
    
    参数:
        tickers: list, 股票代码列表
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
        sleep_sec: float, 请求间隔（避免限流）
    
    返回:
        dict: {ticker: DataFrame}
    """
    results = {}
    
    for i, ticker in enumerate(tickers):
        logger.info(f"\n[{i+1}/{len(tickers)}] 下载 {ticker}...")
        
        df = download_alpaca_data(ticker, start_date, end_date)
        
        if df is not None:
            # 保存到 CSV
            filepath = os.path.join(DATA_DIR, f"{ticker}.csv")
            df.to_csv(filepath, index=False)
            logger.info(f"   已保存: {filepath}")
            results[ticker] = df
        
        # 限流保护
        if sleep_sec > 0 and i < len(tickers) - 1:
            time.sleep(sleep_sec)
    
    return results


def load_cached_data(tickers, data_dir=DATA_DIR):
    """
    加载已下载的缓存数据
    
    返回:
        dict: {ticker: DataFrame}
    """
    results = {}
    
    for ticker in tickers:
        filepath = os.path.join(data_dir, f"{ticker}.csv")
        
        if os.path.exists(filepath):
            df = pd.read_csv(filepath, parse_dates=['date'])
            results[ticker] = df
            logger.info(f"✅ {ticker}: 从缓存加载 {len(df)} 条")
        else:
            logger.warning(f"⚠️ {ticker}: 缓存不存在")
    
    return results


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    # 下载 2020-2024 数据
    start = '2020-01-01'
    end = '2024-12-31'
    
    logger.info(f"{'='*60}")
    logger.info(f"Alpaca 历史数据下载")
    logger.info(f"{'='*60}")
    logger.info(f"股票: {len(TICKERS)} 只")
    logger.info(f"期间: {start} ~ {end}")
    logger.info(f"保存: {DATA_DIR}")
    
    results = download_all(TICKERS, start, end, sleep_sec=0.5)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"下载完成: {len(results)}/{len(TICKERS)} 只")
    logger.info(f"{'='*60}")
    
    # 统计
    for ticker, df in results.items():
        logger.info(f"  {ticker}: {len(df)} 个交易日")
