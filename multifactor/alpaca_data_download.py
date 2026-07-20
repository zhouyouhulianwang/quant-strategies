"""
Alpaca Market Data 历史数据下载器（新版 alpaca-py）
使用 Alpaca Paper Trading 账户免费获取历史日线数据

免费限制: 200 requests/minute
"""

import os
import time
import logging
from typing import List, Optional

import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data import Adjustment

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'alpaca')
os.makedirs(DATA_DIR, exist_ok=True)


def _get_alpaca_credentials(api_key: Optional[str] = None, api_secret: Optional[str] = None):
    """从环境变量或参数获取 API 凭证"""
    key = api_key or os.getenv('ALPACA_API_KEY')
    secret = api_secret or os.getenv('ALPACA_API_SECRET')
    if not key or not secret:
        raise ValueError("请提供 Alpaca API Key 和 Secret，或设置环境变量 ALPACA_API_KEY / ALPACA_API_SECRET")
    return key, secret


def _bars_to_dataframe(bars) -> pd.DataFrame:
    """将 alpaca-py BarsSet 转换为项目统一的 DataFrame"""
    df = bars.df.copy()
    if df.empty:
        return df

    # 索引是 timezone-aware 的 UTC 时间，转为 naive 日期
    df.index = df.index.tz_localize(None)
    df = df.reset_index()

    # 统一列名
    rename_map = {
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume',
        'trade_count': 'trade_count',
        'vwap': 'vwap',
    }
    df = df.rename(columns={c: rename_map.get(c, c) for c in df.columns})

    # 确保核心列存在
    core_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in core_cols:
        if col not in df.columns:
            df[col] = float('nan')

    return df


class AlpacaDataDownloader:
    """基于 alpaca-py 的批量历史数据下载器"""

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        key, secret = _get_alpaca_credentials(api_key, api_secret)
        self.client = StockHistoricalDataClient(key, secret)
        self.data_dir = DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)

    def download(self, tickers: List[str], start_date: str, end_date: str) -> dict:
        """
        批量下载日线数据并保存为 CSV

        参数:
            tickers: 股票代码列表
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'

        返回:
            dict: {ticker: DataFrame}
        """
        if not tickers:
            return {}

        # Alpaca 的 end 为右闭，与 Yahoo 不同；直接按 end_date 23:59 即可覆盖到当日
        request = StockBarsRequest(
            symbol_or_symbols=[t.upper().strip() for t in tickers if t.strip()],
            timeframe=TimeFrame.Day,
            start=pd.Timestamp(start_date).tz_localize('America/New_York').tz_convert('UTC'),
            end=pd.Timestamp(end_date + ' 23:59:59').tz_localize('America/New_York').tz_convert('UTC'),
            adjustment=Adjustment.ALL,
            limit=10000,
        )

        logger.info(f"📥 批量下载 {len(tickers)} 只标的 {start_date} ~ {end_date} ...")
        bars = self.client.get_stock_bars(request)

        if bars is None or bars.df is None or bars.df.empty:
            logger.warning("⚠️ 未返回任何数据")
            return {}

        results = {}
        df = bars.df

        # bars.df 对多只是 MultiIndex: (timestamp, symbol)
        if isinstance(df.index, pd.MultiIndex):
            for symbol in df.index.get_level_values('symbol').unique():
                try:
                    symbol_df = df.loc[symbol].reset_index()
                except KeyError:
                    continue
                symbol_df = _bars_to_dataframe(symbol_df.set_index('timestamp'))
                if symbol_df.empty:
                    continue
                results[symbol] = self._save(symbol, symbol_df)
        else:
            # 单只返回
            symbol = df.index.get_level_values('symbol')[0] if 'symbol' in df.index.names else tickers[0]
            symbol_df = _bars_to_dataframe(df)
            if not symbol_df.empty:
                results[symbol] = self._save(symbol, symbol_df)

        logger.info(f"✅ 下载完成: {len(results)}/{len(tickers)} 只")
        return results

    def _save(self, ticker: str, df: pd.DataFrame) -> pd.DataFrame:
        """保存到 CSV 并返回 DataFrame"""
        filepath = os.path.join(self.data_dir, f"{ticker.upper()}.csv")
        df.to_csv(filepath, index=False)
        logger.info(f"   已保存: {ticker} ({len(df)} 条)")
        return df


# ============================================================
# 兼容旧版 API 的函数式接口
# ============================================================

def download_alpaca_data(ticker: str, start_date: str, end_date: str,
                         api_key: Optional[str] = None, api_secret: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    下载单只标的日线数据（兼容旧版接口）
    """
    downloader = AlpacaDataDownloader(api_key, api_secret)
    results = downloader.download([ticker], start_date, end_date)
    return results.get(ticker.upper())


def download_all(tickers: List[str], start_date: str, end_date: str,
                 sleep_sec: float = 0.5, batch_size: int = 40) -> dict:
    """
    批量下载所有股票数据，分批调用以遵守 200 requests/minute 限制

    参数:
        tickers: list, 股票代码列表
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
        sleep_sec: float, 批次间隔（秒）
        batch_size: int, 每批标的数（Alpaca 建议单请求不超过 40-100 只）

    返回:
        dict: {ticker: DataFrame}
    """
    downloader = AlpacaDataDownloader()
    results = {}

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        logger.info(f"\n[{i + 1}/{len(tickers)}] 下载 {len(batch)} 只: {batch[:5]}...")
        batch_results = downloader.download(batch, start_date, end_date)
        results.update(batch_results)

        if sleep_sec > 0 and i + batch_size < len(tickers):
            time.sleep(sleep_sec)

    return results


def load_cached_data(tickers: List[str], data_dir: str = DATA_DIR) -> dict:
    """
    加载已下载的缓存数据

    返回:
        dict: {ticker: DataFrame}
    """
    results = {}

    for ticker in tickers:
        filepath = os.path.join(data_dir, f"{ticker.upper()}.csv")

        if os.path.exists(filepath):
            df = pd.read_csv(filepath, parse_dates=['timestamp'])
            results[ticker] = df
            logger.info(f"✅ {ticker}: 从缓存加载 {len(df)} 条")
        else:
            logger.warning(f"⚠️ {ticker}: 缓存不存在")

    return results


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    from main import TICKERS

    start = '2020-01-01'
    end = '2024-12-31'

    logger.info(f"{'='*60}")
    logger.info(f"Alpaca 历史数据下载（alpaca-py）")
    logger.info(f"{'='*60}")
    logger.info(f"股票: {len(TICKERS)} 只")
    logger.info(f"期间: {start} ~ {end}")
    logger.info(f"保存: {DATA_DIR}")

    results = download_all(TICKERS, start, end, sleep_sec=0.5, batch_size=40)

    logger.info(f"\n{'='*60}")
    logger.info(f"下载完成: {len(results)}/{len(TICKERS)} 只")
    logger.info(f"{'='*60}")

    for ticker, df in results.items():
        logger.info(f"  {ticker}: {len(df)} 个交易日")
