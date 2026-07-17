"""
Data Source Module - Yahoo Finance 真实数据接入
支持历史价格数据、VIX、市场指标获取
"""

import logging

# P2修复：统一全链路日志格式
from logging_config import setup_logging
setup_logging()
logger = logging.getLogger('data_source')

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import pickle

# 引入统一缓存模块
from cache import (
    is_cache_valid,
    load_parquet_cache,
    save_parquet_cache,
    get_cache_metadata,
    CACHE_VERSION as _CACHE_VERSION,
)

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'data_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# 缓存版本号，用于兼容旧缓存和元数据校验
CACHE_VERSION = _CACHE_VERSION
# 缓存默认 TTL（7 天）
CACHE_TTL_DAYS = 7
# 价格数据 TTL（向后兼容别名）
PRICE_TTL_DAYS = CACHE_TTL_DAYS
# 市场指标数据 TTL（向后兼容别名）
MARKET_TTL_DAYS = CACHE_TTL_DAYS


def _get_cache_path(symbol, source='Yahoo', adjustment='adjusted'):
    """按 symbol+source+adjustment 缓存完整历史，文件名包含来源和复权标志"""
    safe_source = source.replace('/', '_').replace(' ', '_')
    safe_adjustment = adjustment.replace('/', '_').replace(' ', '_')
    return os.path.join(CACHE_DIR, f"{symbol}_{safe_source}_{safe_adjustment}.parquet")


def _get_pickle_path(symbol):
    """旧版 pickle 缓存路径（仅用于一次性迁移）"""
    return os.path.join(CACHE_DIR, f"{symbol}.pkl")


def _decode_metadata(meta_dict):
    """将 pyarrow 字节型 metadata 解码为字符串字典（委托 cache.py）"""
    from cache import _decode_metadata as _cache_decode
    return _cache_decode(meta_dict)


def _is_cache_valid(cache_path, ttl_days=CACHE_TTL_DAYS):
    """检查 parquet 缓存是否有效（版本号 + TTL，委托 cache.py）"""
    return is_cache_valid(cache_path, ttl_days=ttl_days, version=CACHE_VERSION)


def _verify_cache_metadata(cache_path, expected_source=None, expected_adjustment=None):
    """读取缓存元数据并校验 source/adjustment，不匹配时记录警告"""
    try:
        metadata = get_cache_metadata(cache_path)
        actual_source = metadata.get('source')
        actual_adjustment = metadata.get('adjustment')
        if expected_source and actual_source and str(actual_source) != str(expected_source):
            logger.warning(
                "[PIT] Cache source mismatch for %s: expected %s, got %s",
                cache_path, expected_source, actual_source
            )
        if expected_adjustment and actual_adjustment and str(actual_adjustment) != str(expected_adjustment):
            logger.warning(
                "[PIT] Cache adjustment mismatch for %s: expected %s, got %s",
                cache_path, expected_adjustment, actual_adjustment
            )
        downloaded_at = metadata.get('downloaded_at')
        if downloaded_at:
            logger.debug("[PIT] Cache %s downloaded_at=%s", cache_path, downloaded_at)
    except Exception as e:
        logger.debug("[PIT] Failed to verify cache metadata %s: %s", cache_path, e)


def _load_cache(cache_path, expected_source=None, expected_adjustment=None):
    """从 parquet 缓存中读取数据对象，单列表自动还原为 Series（委托 cache.py）"""
    _verify_cache_metadata(cache_path, expected_source, expected_adjustment)
    return load_parquet_cache(cache_path, ttl_days=CACHE_TTL_DAYS, version=CACHE_VERSION)


def _save_cache(cache_path, data, source='Yahoo', adjustment='adjusted'):
    """保存数据及元数据到 parquet 缓存，写入失败不抛异常（委托 cache.py）"""
    metadata = {
        'source': source,
        'adjustment': adjustment,
        'download_time': datetime.now().isoformat(),
    }
    return save_parquet_cache(data, cache_path, metadata=metadata, version=CACHE_VERSION)


def _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted'):
    """将旧版 pickle 缓存一次性迁移为 parquet，失败不抛异常"""
    pickle_path = _get_pickle_path(symbol)
    parquet_path = _get_cache_path(symbol, source=source, adjustment=adjustment)

    if not os.path.exists(pickle_path) or os.path.exists(parquet_path):
        return False

    try:
        with open(pickle_path, 'rb') as f:
            payload = pickle.load(f)

        data = payload.get('data') if isinstance(payload, dict) else payload
        if data is None or (hasattr(data, '__len__') and len(data) == 0):
            return False

        if _save_cache(parquet_path, data, source=source, adjustment=adjustment):
            print(f"[迁移] {symbol}: pickle → parquet")
            return True
    except Exception as e:
        print(f"[警告] 迁移 {symbol} pickle 缓存失败: {e}")

    return False


def _normalize_index(data):
    """将时区感知索引统一为 naive 日期，保证多源数据对齐"""
    if data is None or len(data) == 0:
        return data
    if hasattr(data.index, 'tz') and data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    return data


def _compute_rsi_wilder(prices, window=14):
    """
    使用 Wilder 平滑（指数移动平均 alpha=1/window）计算 RSI
    """
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def _yahoo_end_inclusive(end_date):
    """
    Yahoo Finance 的 history(start=..., end=...) 为右开区间，
    不包含 end 当天。返回 end + 1 日，使结果包含 end_date。
    """
    return (pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')


def _fetch_yahoo_series(symbol, full_history=True):
    """从 Yahoo Finance 获取单标的序列数据，失败返回 None"""
    try:
        ticker = yf.Ticker(symbol)
        if full_history:
            data = ticker.history(period='max')['Close']
        else:
            data = ticker.history(period='5d')['Close']
        return data
    except Exception as e:
        logger.error("Failed to fetch %s: %s", symbol, e)
        return None


def get_corporate_actions(symbols, start, end):
    """
    获取公司行为数据（拆股、分红、并购），并记录事件警告

    参数:
        symbols: list, 股票代码列表
        start: str, 'YYYY-MM-DD'
        end: str, 'YYYY-MM-DD'

    返回:
        DataFrame: 索引=(date, symbol), 列=['split', 'dividend', 'merger']
                 split 为拆股比例（如 1:2 拆股为 2.0），无事件为 1.0
                 dividend 为每股分红金额，无为 0.0
                 merger 为并购标志（1 表示并购，0 表示无）
    """
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    records = []

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            actions = ticker.actions
            if actions is None or actions.empty:
                continue

            actions = actions.copy()
            actions.index = pd.to_datetime(actions.index)
            if hasattr(actions.index, 'tz') and actions.index.tz is not None:
                actions.index = actions.index.tz_localize(None)

            actions = actions[(actions.index >= start_dt) & (actions.index <= end_dt)]

            for date, row in actions.iterrows():
                split = float(row.get('Stock Splits', 0.0)) if row.get('Stock Splits', 0.0) != 0 else 1.0
                dividend = float(row.get('Dividends', 0.0)) if pd.notna(row.get('Dividends', 0.0)) else 0.0
                # Yahoo actions 没有直接并购字段，此处尝试从 info 获取退市/并购提示
                merger = 0
                records.append({
                    'date': date,
                    'symbol': symbol,
                    'split': split,
                    'dividend': dividend,
                    'merger': merger,
                })
                # PIT/公司行为告警：记录警告
                if split != 1.0:
                    logger.warning("[CORP_ACTION] %s split on %s: ratio=%s", symbol, date, split)
                if dividend > 0:
                    logger.warning("[CORP_ACTION] %s dividend on %s: amount=%.4f", symbol, date, dividend)
        except Exception as e:
            logger.warning("[CORP_ACTION] Failed to get corporate actions for %s: %s", symbol, e)
            continue

    if not records:
        return pd.DataFrame(
            columns=['split', 'dividend', 'merger'],
            index=pd.MultiIndex.from_arrays([[], []], names=['date', 'symbol'])
        )

    df = pd.DataFrame(records)
    df.set_index(['date', 'symbol'], inplace=True)
    df = df.sort_index()
    return df


def get_delisted_symbols(symbols, start=None, end=None):
    """
    检测可能已退市的 symbols（近 1 个月无交易数据），并从股票池中移除

    参数:
        symbols: list, 股票代码列表
        start: str, 'YYYY-MM-DD'（保留参数，未使用）
        end: str, 'YYYY-MM-DD'（保留参数，未使用）

    返回:
        set: 已退市或无法获取数据的 symbol 集合
    """
    delisted = set()
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='1mo')
            if hist is None or hist.empty:
                logger.warning("[CORP_ACTION] %s appears delisted or has no recent data", symbol)
                delisted.add(symbol)
        except Exception as e:
            logger.warning("[CORP_ACTION] %s delisting check failed: %s", symbol, e)
            delisted.add(symbol)
    return delisted


def filter_universe_for_corporate_actions(symbols, start=None, end=None):
    """
    从股票池中移除已退市 symbols，并返回过滤后的列表及公司行为数据

    参数:
        symbols: list, 股票代码列表
        start: str, 'YYYY-MM-DD'（可选，用于公司行为查询）
        end: str, 'YYYY-MM-DD'（可选，用于公司行为查询）

    返回:
        tuple: (filtered_symbols, corporate_actions_df)
    """
    if start is None:
        start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')
    delisted = get_delisted_symbols(symbols, start, end)
    filtered = [s for s in symbols if s not in delisted]
    if delisted:
        logger.warning("[CORP_ACTION] Removed %d delisted symbols from universe: %s", len(delisted), sorted(delisted))
    actions = get_corporate_actions(filtered, start, end)
    return filtered, actions




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
        cache_path = _get_cache_path(symbol, source='Yahoo', adjustment='adjusted')

        # 向后兼容：迁移旧 pickle 缓存
        if use_cache and not os.path.exists(cache_path):
            _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted')

        # 检查缓存
        if use_cache and _is_cache_valid(cache_path, CACHE_TTL_DAYS):
            try:
                data = _load_cache(cache_path, expected_source='Yahoo', expected_adjustment='adjusted')
                logger.info(f"[Cache] {symbol}: {len(data)} records")
            except Exception as e:
                logger.warning(f"[Cache] Failed to read {symbol} cache: {e}, will re-download")
                data = None
        else:
            data = None

        # 缓存未命中或失效：下载完整历史并写入缓存
        if data is None:
            logger.info(f"[Download] {symbol}...")
            data = _fetch_yahoo_series(symbol, full_history=True)
            if data is not None and len(data) > 0:
                logger.info(f"{len(data)} records")
                if use_cache:
                    _save_cache(cache_path, data, source='Yahoo', adjustment='adjusted')
            else:
                continue

        # 使用 loc 按请求的日期范围切片
        if data is not None and len(data) > 0:
            data = _normalize_index(data)
            try:
                data = data.loc[start_date:end_date]
            except Exception as e:
                logger.warning(f"[Date slice] {symbol} date slice failed: {e}")
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
    symbol = 'VIX'
    cache_path = _get_cache_path(symbol, source='Yahoo', adjustment='unadjusted')

    # 向后兼容
    if use_cache and not os.path.exists(cache_path):
        _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='unadjusted')

    if use_cache and _is_cache_valid(cache_path, CACHE_TTL_DAYS):
        try:
            vix = _load_cache(cache_path, expected_source='Yahoo', expected_adjustment='unadjusted')
            logger.info(f"[Cache] VIX: {len(vix)} records")
        except Exception as e:
            logger.warning(f"[Cache] VIX cache read failed: {e}, will re-download")
            vix = None
    else:
        vix = None

    if vix is None:
        logger.info("[Download] VIX...")
        vix = _fetch_yahoo_series('^VIX', full_history=True)
        if vix is not None and len(vix) > 0:
            logger.info(f"{len(vix)} records")
            if use_cache:
                _save_cache(cache_path, vix, source='Yahoo', adjustment='unadjusted')
        else:
            logger.error("[Download] VIX failed")
            return None

    if vix is None or len(vix) == 0:
        return None

    vix = _normalize_index(vix)
    return vix.loc[start_date:end_date]


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
    symbol = 'SPY_RSI'
    cache_path = _get_cache_path(symbol, source='Yahoo', adjustment='adjusted')

    # 向后兼容
    if use_cache and not os.path.exists(cache_path):
        _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted')

    if use_cache and _is_cache_valid(cache_path, CACHE_TTL_DAYS):
        try:
            spy = _load_cache(cache_path, expected_source='Yahoo', expected_adjustment='adjusted')
        except Exception as e:
            logger.warning(f"[Cache] SPY cache read failed: {e}, will re-download")
            spy = None
    else:
        spy = None

    if spy is None:
        logger.info("[Download] SPY (for RSI)...")
        spy = _fetch_yahoo_series('SPY', full_history=True)
        if spy is not None and len(spy) > 0:
            logger.info(f"{len(spy)} records")
            if use_cache:
                _save_cache(cache_path, spy, source='Yahoo', adjustment='adjusted')
        else:
            logger.error("[Download] SPY failed")
            return None

    if spy is None or len(spy) == 0:
        return None

    spy = _normalize_index(spy)

    # 计算 Wilder RSI
    rsi = _compute_rsi_wilder(spy)

    # 按请求日期切片
    vix = vix.loc[start_date:end_date]
    rsi = rsi.loc[start_date:end_date]
    rsi = _normalize_index(rsi)

    # 合并数据并显式丢弃缺失值
    market_df = pd.DataFrame({
        'VIX': vix,
        'RSI': rsi
    }).dropna()

    return market_df


def _align_and_clean(price_df, market_df):
    """
    取价格数据与市场数据的交易日交集，并显式处理缺失值。
    P1修复: 改为按标的前向填充并删除无数据的列，不要按行 dropna(how='any') 删整行，
    否则只要一只股票某日缺失就丢弃整个交易日，会产生幸存者偏差。
    调仓时由策略层跳过该标的（main.py 已按 next_d 有效价格过滤）。
    """
    if price_df is None or market_df is None:
        return price_df, market_df

    if len(price_df) == 0 or len(market_df) == 0:
        return price_df, market_df

    # 取交易日交集
    common_dates = price_df.index.intersection(market_df.index)
    price_df = price_df.reindex(common_dates)
    market_df = market_df.reindex(common_dates)

    # 显式处理缺失值：丢弃完全没有数据的列（标的退市/无数据）
    price_df = price_df.dropna(how='all', axis=1)
    # 丢弃市场数据完全缺失的行
    market_df = market_df.dropna(how='all')

    # 再次对齐
    common_dates = price_df.index.intersection(market_df.index)
    price_df = price_df.loc[common_dates]
    market_df = market_df.loc[common_dates]

    # P1修复: 按标的前向填充，保留交易日行，避免幸存者偏差
    price_df = price_df.ffill()
    market_df = market_df.ffill()

    return price_df, market_df


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
    logger.info(f"\n{'='*60}")
    logger.info(f"Preparing backtest data: {start_date} ~ {end_date}")
    logger.info(f"{'='*60}")

    # PIT/公司行为：先移除退市股票，再获取数据
    filtered_tickers, corp_actions = filter_universe_for_corporate_actions(
        tickers, start_date, end_date
    )
    if len(filtered_tickers) < len(tickers):
        logger.warning(
            "[PIT] Universe reduced from %d to %d after corporate-action filtering",
            len(tickers), len(filtered_tickers)
        )

    # 获取价格数据
    price_df = fetch_yahoo_data(filtered_tickers, start_date, end_date, use_cache)

    # 获取市场数据
    market_df = fetch_market_data(start_date, end_date, use_cache)

    # 对齐日期并处理缺失值
    price_df, market_df = _align_and_clean(price_df, market_df)

    logger.info(f"\n[Done] Price data: {len(price_df)} trading days")
    logger.info(f"[Done] Market data: {len(market_df)} trading days")
    logger.info(f"[Done] Stock count: {len(price_df.columns)}")

    return price_df, market_df


# ============================================================
# 使用示例 - 展示 parquet 缓存、TTL 与向后兼容行为
# ============================================================

if __name__ == '__main__':
    from main import TICKERS

    # 准备最近5年的数据
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')

    print("\n首次运行：下载并缓存为 parquet")
    price_df, market_df = prepare_backtest_data(TICKERS, start, end)

    print("\n再次运行：应命中 parquet 缓存")
    price_df, market_df = prepare_backtest_data(TICKERS, start, end)

    print(f"\n数据预览:")
    print(f"价格数据前5行:\n{price_df.head()}")
    print(f"\nVIX 前5行:\n{market_df['VIX'].head()}")

    # 展示缓存文件信息
    print(f"\n缓存文件示例:")
    for symbol in TICKERS[:2] + ['VIX', 'SPY_RSI']:
        cache_path = _get_cache_path(symbol, source='Yahoo', adjustment='adjusted')
        if os.path.exists(cache_path):
            try:
                metadata = get_cache_metadata(cache_path)
                print(f"  {os.path.basename(cache_path)}: "
                      f"source={metadata.get('source')}, "
                      f"adjustment={metadata.get('adjustment')}, "
                      f"downloaded_at={metadata.get('downloaded_at')}, "
                      f"version={metadata.get('cache_version')}")
            except Exception as e:
                print(f"  {os.path.basename(cache_path)}: 读取元数据失败 {e}")
