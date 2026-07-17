"""
Data Source Module - Yahoo Finance 真实数据接入
支持历史价格数据、VIX、市场指标获取
"""

import logging
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pickle

# P2修复：统一全链路日志格式
logger = logging.getLogger(__name__)

# P0修复：最大前向填充交易日数（默认 5 日），防止停牌/退市股票无限制前向填充导致前视偏差
# 实际定义在 data_utils 中，从 data_utils 导入后已在 data_source 命名空间可用。

# 引入统一缓存模块
from cache import (
    is_cache_valid,
    load_parquet_cache,
    save_parquet_cache,
    get_cache_metadata,
    CACHE_VERSION as _CACHE_VERSION,
)
from data_utils import (
    _normalize_index,
    _limited_ffill,
    _compute_rsi_wilder,
    MAX_FFILL_DAYS,
)

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'data_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# 缓存版本号，用于兼容旧缓存和元数据校验
CACHE_VERSION = _CACHE_VERSION
# 缓存默认 TTL（7 天），可通过 MULTIFACTOR_CACHE_TTL_DAYS 环境变量覆盖
CACHE_TTL_DAYS = int(os.getenv('MULTIFACTOR_CACHE_TTL_DAYS', 7))
# 价格数据 TTL（向后兼容别名）
PRICE_TTL_DAYS = CACHE_TTL_DAYS
# 市场指标数据 TTL（向后兼容别名）
MARKET_TTL_DAYS = CACHE_TTL_DAYS


class DataCache:
    """统一的 parquet 数据缓存封装

    为所有数据源（Yahoo、QuantConnect、Polygon 等）提供一致的缓存路径、
    TTL、元数据校验与并发安全写入接口。缓存键包含数据源标识、调整方式、
    股票代码、频率与日期范围，避免不同来源/调整后的数据冲突。
    """

    def __init__(self, cache_dir=None, default_ttl_days=None, version=None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.default_ttl_days = int(default_ttl_days or CACHE_TTL_DAYS)
        self.version = version if version is not None else CACHE_VERSION
        os.makedirs(self.cache_dir, exist_ok=True)

    def frequency_ttl(self, frequency):
        """按数据频率返回建议 TTL（天）

        分钟/小时数据更新频繁，使用较短 TTL；日/月数据使用较长 TTL。
        """
        freq = str(frequency or 'daily').lower()
        if 'min' in freq:
            return max(1, self.default_ttl_days // 7) or 1
        elif 'hour' in freq:
            return max(1, self.default_ttl_days // 3) or 1
        elif 'day' in freq or 'daily' in freq:
            return self.default_ttl_days
        elif 'week' in freq or 'month' in freq:
            return min(30, self.default_ttl_days * 4)
        else:
            return self.default_ttl_days

    def get_path(self, symbol, source, adjustment='adjusted', start=None, end=None, frequency='daily'):
        """生成缓存文件路径，键包含 source/adjustment/symbol/frequency/date-range"""
        safe_symbol = str(symbol).replace('/', '_').replace(' ', '_')
        safe_source = str(source).replace('/', '_').replace(' ', '_')
        safe_adjustment = str(adjustment).replace('/', '_').replace(' ', '_')
        date_part = f"_{start}_{end}" if start and end else ""
        freq_part = f"_{frequency}" if frequency else ""
        return os.path.join(
            self.cache_dir,
            f"{safe_symbol}_{safe_source}_{safe_adjustment}{freq_part}{date_part}.parquet"
        )

    def is_valid(self, path, ttl_days=None, version=None):
        """检查缓存是否有效（版本 + TTL）"""
        if ttl_days is None:
            ttl_days = self.default_ttl_days
        return is_cache_valid(path, ttl_days=ttl_days, version=version or self.version)

    def verify_metadata(self, path, expected=None):
        """校验缓存元数据是否匹配预期（source/adjustment 等）"""
        expected = expected or {}
        try:
            metadata = get_cache_metadata(path)
            for key, expected_val in expected.items():
                if not expected_val:
                    continue
                actual = metadata.get(key)
                if actual and str(actual) != str(expected_val):
                    logger.warning(
                        "[PIT] Cache %s mismatch for %s: expected %s, got %s",
                        key, path, expected_val, actual
                    )
        except Exception as e:
            logger.debug("[PIT] Failed to verify cache metadata %s: %s", path, e)

    def get_metadata(self, path):
        """读取 parquet 缓存元数据"""
        return get_cache_metadata(path)

    def load(self, path, expected=None, ttl_days=None, version=None):
        """从缓存读取数据，读取前校验元数据"""
        self.verify_metadata(path, expected)
        if ttl_days is None:
            ttl_days = self.default_ttl_days
        return load_parquet_cache(path, ttl_days=ttl_days, version=version or self.version)

    def save(self, path, data, metadata=None, ttl_days=None, version=None):
        """保存数据到 parquet 缓存，使用临时文件 + 原子重命名，fcntl 保证并发安全

        参数:
            path: str, 目标缓存路径
            data: DataFrame / Series
            metadata: dict, 自定义元数据（如 source, adjustment）
            ttl_days: int, 可选 TTL（仅用于校验，不写入）
            version: Any, 版本号

        返回:
            bool: 保存是否成功
        """
        if data is None or (hasattr(data, '__len__') and len(data) == 0):
            return False

        try:
            import fcntl
            has_fcntl = True
        except ImportError:
            has_fcntl = False

        dir_name = os.path.dirname(path) or '.'
        os.makedirs(dir_name, exist_ok=True)
        tmp_path = f"{path}.tmp.{os.getpid()}"
        lock_path = f"{path}.lock"

        lock_file = None
        try:
            if has_fcntl:
                lock_file = open(lock_path, 'w')
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            cache_metadata = {
                'cache_version': str(version if version is not None else self.version),
                'download_time': datetime.now().isoformat(),
            }
            if metadata:
                cache_metadata.update(metadata)

            ok = save_parquet_cache(
                data, tmp_path, metadata=cache_metadata,
                version=version or self.version
            )
            if not ok:
                return False

            # 原子重命名，避免并发读到半写入文件
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            logger.warning("[DataCache] Failed to save cache %s: %s", path, e)
            return False
        finally:
            if lock_file:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()
                except Exception:
                    pass
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


# 全局 DataCache 实例（向后兼容）
cache = DataCache()

# P2 修复：VIX 备用数据源超时（秒），默认 10 秒
VIX_FALLBACK_TIMEOUT = int(os.getenv('MULTIFACTOR_VIX_TIMEOUT', 10))

# 可选 VIX 数据源：优先使用 QuantConnect / Polygon，最后回退 Yahoo
try:
    from quantconnect_data import QuantConnectDataSource
    QC_AVAILABLE = True
except ImportError:
    QC_AVAILABLE = False

try:
    from polygon_data import PolygonDataSource, HybridDataSource
    POLYGON_AVAILABLE = True
except ImportError:
    POLYGON_AVAILABLE = False


def _fetch_vix_yahoo(symbol='^VIX', full_history=True, timeout=VIX_FALLBACK_TIMEOUT):
    """P2 修复：从 Yahoo 获取 VIX，带超时控制"""
    try:
        import signal
        from contextlib import contextmanager

        @contextmanager
        def _timeout_ctx(seconds):
            def _handler(signum, frame):
                raise TimeoutError(f"yfinance fetch timeout after {seconds}s")
            if hasattr(signal, 'SIGALRM'):
                old = signal.signal(signal.SIGALRM, _handler)
                signal.alarm(seconds)
                try:
                    yield
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old)
            else:
                yield

        with _timeout_ctx(timeout):
            ticker = yf.Ticker(symbol)
            if full_history:
                data = ticker.history(period='max')['Close']
            else:
                data = ticker.history(period='5d')['Close']
            return data
    except TimeoutError as e:
        logger.warning("VIX yfinance timeout: %s", e)
        return None
    except Exception as e:
        logger.warning("VIX yfinance fetch failed: %s", e)
        return None


def _fetch_vix_quantconnect(start_date, end_date):
    """P2 修复：尝试从 QuantConnect 获取 VIX"""
    if not QC_AVAILABLE:
        return None
    try:
        qc = QuantConnectDataSource()
        vix = qc.get_vix_data(start_date, end_date)
        if vix is not None and len(vix) > 0:
            logger.info("[VIX] QuantConnect source returned %d records", len(vix))
            return vix
    except Exception as e:
        logger.warning("VIX QuantConnect fetch failed: %s", e)
    return None


def _fetch_vix_polygon(start_date, end_date):
    """P2 修复：尝试从 Polygon 获取 VIX"""
    if not POLYGON_AVAILABLE:
        return None
    try:
        source = HybridDataSource()
        vix = source.get_vix_data(start_date, end_date)
        if vix is not None and len(vix) > 0:
            logger.info("[VIX] Polygon source returned %d records", len(vix))
            return vix
    except Exception as e:
        logger.warning("VIX Polygon fetch failed: %s", e)
    return None


def _fetch_vix_from_cache(sources, start_date, end_date, use_cache):
    """P2 修复：按优先级尝试各数据源缓存"""
    for source, cache_path in sources:
        if use_cache and not os.path.exists(cache_path):
            _migrate_pickle_to_parquet('VIX', source=source, adjustment='unadjusted')
        if use_cache and cache.is_valid(cache_path):
            try:
                vix = cache.load(cache_path, expected={'source': source, 'adjustment': 'unadjusted'})
                if vix is not None and len(vix) > 0:
                    logger.info("[Cache] VIX (%s): %d records", source, len(vix))
                    return source, vix
            except Exception as e:
                logger.warning("[Cache] VIX %s cache read failed: %s, will try other sources", source, e)
    return None, None


def _save_vix_to_cache(source, vix, adjustment='unadjusted'):
    """P2 修复：保存 VIX 到对应 source 缓存"""
    cache_path = cache.get_path('VIX', source=source, adjustment=adjustment, frequency='daily')
    try:
        cache.save(cache_path, vix, metadata={'source': source, 'adjustment': adjustment})
    except Exception as e:
        logger.debug("Failed to save VIX cache for %s: %s", source, e)




def _get_pickle_path(symbol):
    """旧版 pickle 缓存路径（仅用于一次性迁移）"""
    return os.path.join(CACHE_DIR, f"{symbol}.pkl")


def _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted'):
    """将旧版 pickle 缓存一次性迁移为 parquet，失败不抛异常"""
    pickle_path = _get_pickle_path(symbol)
    parquet_path = cache.get_path(symbol, source=source, adjustment=adjustment, frequency='daily')

    if not os.path.exists(pickle_path) or os.path.exists(parquet_path):
        return False

    try:
        with open(pickle_path, 'rb') as f:
            payload = pickle.load(f)

        data = payload.get('data') if isinstance(payload, dict) else payload
        if data is None or (hasattr(data, '__len__') and len(data) == 0):
            return False

        if cache.save(parquet_path, data, metadata={'source': source, 'adjustment': adjustment}):
            print(f"[迁移] {symbol}: pickle → parquet")
            return True
    except Exception as e:
        print(f"[警告] 迁移 {symbol} pickle 缓存失败: {e}")

    return False




def _yahoo_end_inclusive(end_date):
    """
    Yahoo Finance 的 history(start=..., end=...) 为右开区间，
    不包含 end 当天。返回 end + 1 日，使结果包含 end_date。
    """
    return (pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')


def _fetch_yahoo_series(symbol, full_history=True):
    """从 Yahoo Finance 获取单标的序列数据，失败返回 None"""
    try:
        import yfinance as yf
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
            import yfinance as yf
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
    检测可能已退市的 symbols（近 1 个月无交易数据或数据严重过期），并从股票池中移除

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
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='1mo')

            # 1. 完全无数据 → 视为退市/不可获取
            if hist is None or hist.empty:
                logger.warning("[CORP_ACTION] %s appears delisted or has no recent data", symbol)
                delisted.add(symbol)
                continue

            # 2. 收盘价全为 NaN → 数据无效（可能是退市后 yfinance 仍返回空表）
            close = hist.get('Close') if isinstance(hist, pd.DataFrame) else hist
            if close is not None and close.isna().all():
                logger.warning("[CORP_ACTION] %s has all-NaN close prices, treating as delisted", symbol)
                delisted.add(symbol)
                continue

            # 3. 最近交易日距离现在过久（>30 个自然日）→ 可能已经停牌/退市
            last_date = hist.index[-1]
            if hasattr(last_date, 'tz') and last_date.tz is not None:
                last_date = last_date.tz_localize(None)
            days_since_last_trade = (pd.Timestamp.now() - pd.Timestamp(last_date)).days
            if days_since_last_trade > 30:
                logger.warning(
                    "[CORP_ACTION] %s last trade was %d days ago, marking as delisted/inactive",
                    symbol, days_since_last_trade,
                )
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
        cache_path = cache.get_path(symbol, source='Yahoo', adjustment='adjusted', frequency='daily')

        # 向后兼容：迁移旧 pickle 缓存
        if use_cache and not os.path.exists(cache_path):
            _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted')

        # 检查缓存
        if use_cache and cache.is_valid(cache_path):
            try:
                data = cache.load(cache_path, expected={'source': 'Yahoo', 'adjustment': 'adjusted'})
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
                    cache.save(cache_path, data, metadata={'source': 'Yahoo', 'adjustment': 'adjusted'})
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

    P2 修复：
    - 优先使用 QuantConnect / Polygon 数据
    - 最后回退到 Yahoo，并增加超时和错误处理
    - 所有源失败时返回 None，不传播错误值

    参数:
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
        use_cache: bool

    返回:
        Series: VIX 日线数据，失败返回 None
    """
    sources = [
        ('QuantConnect', cache.get_path('VIX', source='QuantConnect', adjustment='unadjusted', frequency='daily')),
        ('Polygon', cache.get_path('VIX', source='Polygon', adjustment='unadjusted', frequency='daily')),
        ('Yahoo', cache.get_path('VIX', source='Yahoo', adjustment='unadjusted', frequency='daily')),
    ]

    # 1. 按优先级尝试各数据源缓存
    source, vix = _fetch_vix_from_cache(sources, start_date, end_date, use_cache)
    if vix is not None and len(vix) > 0:
        return _normalize_index(vix).loc[start_date:end_date]

    # 2. 实时下载：QuantConnect -> Polygon -> Yahoo
    vix = _fetch_vix_quantconnect(start_date, end_date)
    if vix is not None and len(vix) > 0:
        if use_cache:
            _save_vix_to_cache('QuantConnect', vix)
        return _normalize_index(vix).loc[start_date:end_date]

    vix = _fetch_vix_polygon(start_date, end_date)
    if vix is not None and len(vix) > 0:
        if use_cache:
            _save_vix_to_cache('Polygon', vix)
        return _normalize_index(vix).loc[start_date:end_date]

    logger.info("[Download] VIX from Yahoo (last fallback)...")
    vix = _fetch_vix_yahoo('^VIX', full_history=True)
    if vix is not None and len(vix) > 0:
        logger.info("[Download] VIX: %d records", len(vix))
        if use_cache:
            _save_vix_to_cache('Yahoo', vix)
        return _normalize_index(vix).loc[start_date:end_date]

    logger.error("[Download] VIX failed: all sources unavailable")
    return None


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
    cache_path = cache.get_path(symbol, source='Yahoo', adjustment='adjusted', frequency='daily')

    # 向后兼容
    if use_cache and not os.path.exists(cache_path):
        _migrate_pickle_to_parquet(symbol, source='Yahoo', adjustment='adjusted')

    if use_cache and cache.is_valid(cache_path):
        try:
            spy = cache.load(cache_path, expected={'source': 'Yahoo', 'adjustment': 'adjusted'})
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
                cache.save(cache_path, spy, metadata={'source': 'Yahoo', 'adjustment': 'adjusted'})
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

    # P0修复: 按标的受限前向填充，保留交易日行；市场数据缺失行直接删除
    price_df = _limited_ffill(price_df)
    market_df = _limited_ffill(market_df).dropna()

    common_dates = price_df.index.intersection(market_df.index)
    price_df = price_df.loc[common_dates]
    market_df = market_df.loc[common_dates]

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
        cache_path = cache.get_path(symbol, source='Yahoo', adjustment='adjusted', frequency='daily')
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
