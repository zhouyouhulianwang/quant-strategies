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
import pyarrow as pa
import pyarrow.parquet as pq

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'data_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# 缓存版本号，用于兼容旧缓存和元数据校验
CACHE_VERSION = 1
# 缓存默认 TTL（7 天）
CACHE_TTL_DAYS = 7
# 价格数据 TTL（向后兼容别名）
PRICE_TTL_DAYS = CACHE_TTL_DAYS
# 市场指标数据 TTL（向后兼容别名）
MARKET_TTL_DAYS = CACHE_TTL_DAYS


def _get_cache_path(symbol):
    """按 symbol 缓存完整历史，文件名统一为 {symbol}.parquet"""
    return os.path.join(CACHE_DIR, f"{symbol}.parquet")


def _get_pickle_path(symbol):
    """旧版 pickle 缓存路径（仅用于一次性迁移）"""
    return os.path.join(CACHE_DIR, f"{symbol}.pkl")


def _decode_metadata(meta_dict):
    """将 pyarrow 字节型 metadata 解码为字符串字典"""
    if not meta_dict:
        return {}
    result = {}
    for k, v in meta_dict.items():
        if k == b'ARROW:schema' or k == b'pandas':
            continue
        key = k.decode('utf-8') if isinstance(k, bytes) else k
        val = v.decode('utf-8') if isinstance(v, bytes) else v
        result[key] = val
    return result


def _is_cache_valid(cache_path, ttl_days=CACHE_TTL_DAYS):
    """检查 parquet 缓存是否有效（版本号 + TTL）"""
    if not os.path.exists(cache_path):
        return False

    try:
        meta = pq.read_metadata(cache_path)
        metadata = _decode_metadata(meta.metadata)

        if metadata.get('cache_version') != str(CACHE_VERSION):
            return False

        downloaded_at = datetime.fromisoformat(metadata.get('downloaded_at'))
        if datetime.now() - downloaded_at > timedelta(days=ttl_days):
            return False

        return True
    except Exception:
        return False


def _load_cache(cache_path):
    """从 parquet 缓存中读取数据对象，单列表自动还原为 Series"""
    try:
        df = pd.read_parquet(cache_path)
        if isinstance(df, pd.DataFrame) and len(df.columns) == 1:
            return df.iloc[:, 0]
        return df
    except Exception as e:
        print(f"[警告] 读取 parquet 缓存失败 {cache_path}: {e}")
        return None


def _save_cache(cache_path, data, source='Yahoo', adjustment='adjusted'):
    """保存数据及元数据到 parquet 缓存，写入失败不抛异常"""
    try:
        if data is None or (hasattr(data, '__len__') and len(data) == 0):
            return False

        # 统一转换为 DataFrame，保留索引
        if isinstance(data, pd.Series):
            df = data.to_frame(name=data.name or 'value')
        else:
            df = data.copy()

        if df.index.name is None:
            df.index.name = 'date'

        # 丢弃索引为 NaT 的无效行，避免 parquet 写入失败
        df = df[df.index.notna()]
        if len(df) == 0:
            return False

        table = pa.Table.from_pandas(df)
        existing_metadata = table.schema.metadata or {}
        cache_metadata = {
            'cache_version': str(CACHE_VERSION),
            'downloaded_at': datetime.now().isoformat(),
            'source': source,
            'adjustment': adjustment,
        }
        new_metadata = {
            **existing_metadata,
            **{k.encode('utf-8'): v.encode('utf-8') for k, v in cache_metadata.items()}
        }
        table = table.replace_schema_metadata(new_metadata)
        pq.write_table(table, cache_path)
        return True
    except Exception as e:
        print(f"[警告] 保存 parquet 缓存失败 {cache_path}: {e}")
        return False


def _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted'):
    """将旧版 pickle 缓存一次性迁移为 parquet，失败不抛异常"""
    pickle_path = _get_pickle_path(symbol)
    parquet_path = _get_cache_path(symbol)

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
        print(f"失败: {e}")
        return None


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
        cache_path = _get_cache_path(symbol)

        # 向后兼容：迁移旧 pickle 缓存
        if use_cache and not os.path.exists(cache_path):
            _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted')

        # 检查缓存
        if use_cache and _is_cache_valid(cache_path, CACHE_TTL_DAYS):
            try:
                data = _load_cache(cache_path)
                print(f"[缓存] {symbol}: {len(data)} 条记录")
            except Exception as e:
                print(f"[警告] {symbol} 缓存读取失败: {e}，尝试重新下载")
                data = None
        else:
            data = None

        # 缓存未命中或失效：下载完整历史并写入缓存
        if data is None:
            print(f"[下载] {symbol}...", end=' ')
            data = _fetch_yahoo_series(symbol, full_history=True)
            if data is not None and len(data) > 0:
                print(f"{len(data)} 条记录")
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
                print(f"[警告] {symbol} 日期切片失败: {e}")
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
    cache_path = _get_cache_path(symbol)

    # 向后兼容
    if use_cache and not os.path.exists(cache_path):
        _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='unadjusted')

    if use_cache and _is_cache_valid(cache_path, CACHE_TTL_DAYS):
        try:
            vix = _load_cache(cache_path)
            print(f"[缓存] VIX: {len(vix)} 条记录")
        except Exception as e:
            print(f"[警告] VIX 缓存读取失败: {e}，尝试重新下载")
            vix = None
    else:
        vix = None

    if vix is None:
        print("[下载] VIX...", end=' ')
        vix = _fetch_yahoo_series('^VIX', full_history=True)
        if vix is not None and len(vix) > 0:
            print(f"{len(vix)} 条记录")
            if use_cache:
                _save_cache(cache_path, vix, source='Yahoo', adjustment='unadjusted')
        else:
            print("失败")
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
    cache_path = _get_cache_path(symbol)

    # 向后兼容
    if use_cache and not os.path.exists(cache_path):
        _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted')

    if use_cache and _is_cache_valid(cache_path, CACHE_TTL_DAYS):
        try:
            spy = _load_cache(cache_path)
        except Exception as e:
            print(f"[警告] SPY 缓存读取失败: {e}，尝试重新下载")
            spy = None
    else:
        spy = None

    if spy is None:
        print("[下载] SPY (用于 RSI)...", end=' ')
        spy = _fetch_yahoo_series('SPY', full_history=True)
        if spy is not None and len(spy) > 0:
            print(f"{len(spy)} 条记录")
            if use_cache:
                _save_cache(cache_path, spy, source='Yahoo', adjustment='adjusted')
        else:
            print("失败")
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
    print(f"\n{'='*60}")
    print(f"准备回测数据: {start_date} ~ {end_date}")
    print(f"{'='*60}")

    # 获取价格数据
    price_df = fetch_yahoo_data(tickers, start_date, end_date, use_cache)

    # 获取市场数据
    market_df = fetch_market_data(start_date, end_date, use_cache)

    # 对齐日期并处理缺失值
    price_df, market_df = _align_and_clean(price_df, market_df)

    print(f"\n[完成] 价格数据: {len(price_df)} 个交易日")
    print(f"[完成] 市场数据: {len(market_df)} 个交易日")
    print(f"[完成] 股票数量: {len(price_df.columns)}")

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
        cache_path = _get_cache_path(symbol)
        if os.path.exists(cache_path):
            try:
                meta = pq.read_metadata(cache_path)
                metadata = _decode_metadata(meta.metadata)
                print(f"  {os.path.basename(cache_path)}: "
                      f"source={metadata.get('source')}, "
                      f"adjustment={metadata.get('adjustment')}, "
                      f"downloaded_at={metadata.get('downloaded_at')}, "
                      f"version={metadata.get('cache_version')}")
            except Exception as e:
                print(f"  {os.path.basename(cache_path)}: 读取元数据失败 {e}")
