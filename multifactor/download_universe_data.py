"""
批量下载并缓存股票池历史数据

优先回填缺失标的，使用 Yahoo Finance 批量接口（yfinance.download）,
按 symbol 写入统一的 parquet 缓存，后续 HybridQCDataSource 可直接命中。

用法：
    python3 download_universe_data.py --start 2020-01-01 --end 2026-07-20 --max-symbols 100
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import List, Set

import pandas as pd

# 使用 quantconnect_data 中已有的 DataCache 和常量
from quantconnect_data import HybridQCDataSource, cache
from data_utils import _normalize_index

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

UNIVERSE_FILES = [
    'data/sp500_tickers.json',
    'data/ndx100_tickers.json',
]


def load_universe() -> List[str]:
    """加载股票池（去重、大写）"""
    tickers: Set[str] = set()
    for path in UNIVERSE_FILES:
        if not os.path.exists(path):
            logger.warning(f"股票池文件不存在: {path}")
            continue
        with open(path, 'r', encoding='utf-8') as f:
            tickers.update(json.load(f))
    return sorted(t.upper().strip() for t in tickers if t.strip())


def _get_cached_symbols(tickers: List[str], start: str, end: str, resolution: str = 'daily') -> Set[str]:
    """检查哪些 symbol 已有有效缓存"""
    cached = set()
    for symbol in tickers:
        path = cache.get_path(symbol, source='Yahoo', adjustment='adjusted', frequency=resolution)
        if cache.is_valid(path, ttl_days=cache.frequency_ttl(resolution)):
            cached.add(symbol)
    return cached


def _chunked(items: List[str], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def download_and_cache(
    tickers: List[str],
    start: str,
    end: str,
    resolution: str = 'daily',
    chunk_size: int = 100,
    sleep_between_chunks: float = 1.0,
):
    """
    批量下载 yfinance 数据并按 symbol 缓存。

    返回:
        dict: {symbol: records_count}
    """
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError("yfinance 未安装") from e

    results = {}
    total = len(tickers)

    for idx, chunk in enumerate(_chunked(tickers, chunk_size), start=1):
        logger.info(f"🌍 下载第 {idx}/{len(tickers)//chunk_size + 1} 批: {len(chunk)} 只标的")
        try:
            # group_by='ticker' 得到 MultiIndex columns: (Ticker, Field)
            df = yf.download(
                chunk,
                start=start,
                end=end,
                group_by='ticker',
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as e:
            logger.error(f"第 {idx} 批下载失败: {e}")
            continue

        if df is None or df.empty:
            logger.warning(f"第 {idx} 批返回空数据")
            continue

        # yfinance 单只返回时不是 MultiIndex，需要特殊处理
        multi_index = isinstance(df.columns, pd.MultiIndex)

        for symbol in chunk:
            try:
                if multi_index:
                    if symbol not in df.columns.get_level_values(0):
                        continue
                    close = df[symbol]['Close']
                else:
                    # 单只返回
                    close = df['Close']

                close = close.dropna()
                if close.empty:
                    continue

                close = _normalize_index(close)
                cache_path = cache.get_path(
                    symbol, source='Yahoo', adjustment='adjusted', frequency=resolution
                )
                cache.save(
                    cache_path, close,
                    metadata={'source': 'Yahoo', 'adjustment': 'adjusted'}
                )
                results[symbol] = len(close)
                logger.info(f"  ✅ {symbol}: {len(close)} 条记录已缓存")
            except Exception as e:
                logger.warning(f"  ⚠️ {symbol} 缓存失败: {e}")

        if sleep_between_chunks > 0 and idx < len(tickers) // chunk_size + 1:
            time.sleep(sleep_between_chunks)

    return results


def main():
    parser = argparse.ArgumentParser(description='批量下载股票池历史数据并缓存')
    parser.add_argument('--start', default='2020-01-01', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', default=datetime.now().strftime('%Y-%m-%d'), help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--max-symbols', type=int, default=0, help='最大下载标的数，0 表示全部')
    parser.add_argument('--skip-cached', action='store_true', help='跳过已有缓存的标的')
    parser.add_argument('--chunk-size', type=int, default=100, help='Yahoo 分批大小')
    parser.add_argument('--sleep', type=float, default=1.0, help='批次间隔（秒）')
    args = parser.parse_args()

    universe = load_universe()
    if args.max_symbols > 0:
        universe = universe[:args.max_symbols]

    logger.info(f"股票池总数: {len(universe)}，日期范围: {args.start} ~ {args.end}")

    if args.skip_cached:
        cached = _get_cached_symbols(universe, args.start, args.end)
        logger.info(f"已有缓存: {len(cached)} 只，跳过")
        universe = [t for t in universe if t not in cached]

    if not universe:
        logger.info("没有需要下载的标的")
        return

    t0 = time.time()
    results = download_and_cache(
        universe, args.start, args.end,
        chunk_size=args.chunk_size, sleep_between_chunks=args.sleep
    )
    elapsed = time.time() - t0

    logger.info(f"{'='*60}")
    logger.info(f"下载完成: {len(results)}/{len(universe)} 只")
    logger.info(f"耗时: {elapsed:.1f}s，平均每只: {elapsed/max(len(results),1):.2f}s")
    logger.info(f"{'='*60}")


if __name__ == '__main__':
    main()
