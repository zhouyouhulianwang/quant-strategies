"""
实时数据源模块 - Polygon.io 替代 Yahoo Finance
提供更快速、更可靠的市场数据
"""

import os
import logging
import time
import urllib.parse as urlparse
from datetime import datetime, timedelta
from typing import Optional, List

import pandas as pd
import numpy as np

# P2修复：统一全链路日志格式

logger = logging.getLogger(__name__)

# P0修复：最大前向填充交易日数（默认 5 日），防止停牌/退市股票无限制前向填充导致前视偏差
MAX_FFILL_DAYS = int(os.getenv('MULTIFACTOR_MAX_FFILL_DAYS', 5))

# Polygon API Key
POLYGON_API_KEY = os.getenv('POLYGON_API_KEY')


def _normalize_index(data):
    """将时区感知索引统一为 naive 日期，保证多源数据对齐"""
    if data is None or len(data) == 0:
        return data
    if hasattr(data.index, 'tz') and data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    return data


def _limited_ffill(df, max_days=MAX_FFILL_DAYS, active=None):
    """
    P0修复：受限前向填充，超过 max_days 的缺失值保持 NaN。

    参数:
        df: DataFrame/Series
        max_days: int, 最大前向填充天数（交易日）
        active: 可选，dict/Series/DataFrame，标记标的是否仍活跃；
                若提供，退市/不活跃日期后不再填充。
    """
    if df is None or df.empty:
        return df
    filled = df.ffill(limit=max_days)
    if active is not None:
        try:
            if isinstance(active, pd.DataFrame) and filled.shape == active.shape:
                filled = filled.where(active)
            elif isinstance(active, dict):
                for symbol, is_active in active.items():
                    if symbol in filled.columns and not is_active:
                        filled[symbol] = np.nan
        except Exception as e:
            logger.warning("[PIT] active/delisted marker handling failed: %s", e)
    return filled


def _compute_rsi_wilder(prices, window=14):
    """使用 Wilder 平滑（alpha=1/window）计算 RSI"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


# ============================================================
# Parquet 缓存基础设施（按 symbol 缓存完整历史，委托 cache.py）
# ============================================================
import os
from cache import (
    is_cache_valid,
    load_parquet_cache,
    save_parquet_cache,
    get_cache_metadata,
    CACHE_VERSION as _CACHE_VERSION,
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'data_cache')
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_VERSION = _CACHE_VERSION
CACHE_TTL_DAYS = 7


def _get_cache_path(symbol, source='Polygon', adjustment='adjusted'):
    """按 symbol+source+adjustment 缓存完整历史，文件名包含来源和复权标志"""
    safe_source = source.replace('/', '_').replace(' ', '_')
    safe_adjustment = adjustment.replace('/', '_').replace(' ', '_')
    return os.path.join(CACHE_DIR, f"{symbol}_{safe_source}_{safe_adjustment}.parquet")


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
    except Exception as e:
        logger.debug("[PIT] Failed to verify cache metadata %s: %s", cache_path, e)


def _load_cache(cache_path, expected_source=None, expected_adjustment=None):
    """从 parquet 缓存读取数据，单列表自动还原为 Series（委托 cache.py）"""
    _verify_cache_metadata(cache_path, expected_source, expected_adjustment)
    return load_parquet_cache(cache_path, ttl_days=CACHE_TTL_DAYS, version=CACHE_VERSION)


def _save_cache(cache_path, data, source='Polygon', adjustment='adjusted'):
    """保存数据及元数据到 parquet 缓存，失败不抛异常（委托 cache.py）"""
    metadata = {
        'source': source,
        'adjustment': adjustment,
        'download_time': datetime.now().isoformat(),
    }
    return save_parquet_cache(data, cache_path, metadata=metadata, version=CACHE_VERSION)


def _yahoo_end_inclusive(end_date):
    """Yahoo Finance 的 history end 为右开区间，返回 end + 1 日"""
    return (pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')


class PolygonDataSource:
    """Polygon.io 数据源"""

    def __init__(self, api_key=None):
        """
        初始化 Polygon 数据源

        参数:
            api_key: str, Polygon API Key
        """
        self.api_key = api_key or POLYGON_API_KEY

        if not self.api_key:
            logger.warning("⚠️ Polygon API Key 未设置")
            self.available = False
        else:
            self.available = True
            logger.info("✅ Polygon 数据源已初始化")

    def _ensure_api_key(self, url: str) -> str:
        """确保分页 URL 包含 apiKey"""
        if 'apiKey=' in url:
            return url
        sep = '&' if '?' in url else '?'
        return f"{url}{sep}apiKey={self.api_key}"

    def _request_with_retry(self, url: str, max_retries: int = 5, timeout: int = 30):
        """带指数退避的请求，处理 429/403 等限流/权限错误"""
        import requests

        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=timeout)

                # 限流：按 Retry-After 或指数退避等待
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 2 ** attempt))
                    logger.warning(f"Polygon 429 限流，等待 {retry_after}s 后重试 ({attempt+1}/{max_retries})")
                    time.sleep(retry_after)
                    continue

                # 权限错误：同样指数退避重试（可能为临时密钥校验失败）
                if response.status_code == 403:
                    logger.warning(f"Polygon 403 禁止访问，等待 {2 ** attempt}s 后重试 ({attempt+1}/{max_retries})")
                    time.sleep(2 ** attempt)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                logger.warning(f"Polygon 请求异常: {e}, 重试 {attempt+1}/{max_retries}")
                time.sleep(2 ** attempt)

        logger.error("Polygon 请求在最大重试次数后仍然失败")
        return None

    def get_daily_bars(self, symbol, start_date, end_date):
        """
        获取日线数据（自动处理分页、复权和 parquet 缓存）

        参数:
            symbol: str
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'

        返回:
            DataFrame: 日线数据
        """
        if not self.available:
            return None

        cache_path = _get_cache_path(symbol, source='Polygon', adjustment='adjusted')

        # 1. 优先读取 parquet 缓存并按日期切片
        if _is_cache_valid(cache_path, CACHE_TTL_DAYS):
            try:
                df = _load_cache(cache_path, expected_source='Polygon', expected_adjustment='adjusted')
                df = _normalize_index(df)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df.loc[start_date:end_date]
            except Exception as e:
                logger.warning(f"Failed to read {symbol} parquet cache: {e}")

        # 2. 缓存未命中：从 Polygon 下载完整历史并写入缓存
        try:
            import requests

            base_url = (
                f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/"
                f"{start_date}/{end_date}"
            )
            params = {'adjusted': 'true', 'apiKey': self.api_key}
            url = f"{base_url}?{urlparse.urlencode(params)}"

            all_results = []
            while url:
                data = self._request_with_retry(url)
                if not data or 'results' not in data:
                    break

                all_results.extend(data['results'])

                next_url = data.get('next_url')
                if next_url:
                    url = self._ensure_api_key(next_url)
                else:
                    url = None

            if not all_results:
                return None

            df = pd.DataFrame(all_results)
            df['t'] = pd.to_datetime(df['t'], unit='ms')
            df['t'] = df['t'].dt.tz_localize(None)
            df.set_index('t', inplace=True)
            df.rename(columns={
                'o': 'Open',
                'h': 'High',
                'l': 'Low',
                'c': 'Close',
                'v': 'Volume'
            }, inplace=True)

            # 写入 parquet 缓存（完整历史）
            _save_cache(cache_path, df, source='Polygon', adjustment='adjusted')
            return df

        except Exception as e:
            logger.error(f"Polygon failed to fetch {symbol}: {e}")

        return None

    def get_last_trade(self, symbol):
        """
        获取最新成交价（仅用于股票，不用于指数）

        参数:
            symbol: str

        返回:
            float: 最新价格
        """
        if not self.available:
            return None

        try:
            import requests

            url = self._ensure_api_key(
                f"https://api.polygon.io/v2/last/trade/{symbol}"
            )
            data = self._request_with_retry(url, max_retries=3)

            if data and data.get('results'):
                return float(data['results']['p'])

        except Exception as e:
            logger.error(f"Polygon 获取 {symbol} 最新价失败: {e}")

        return None

    def get_vix_data(self, start_date, end_date):
        """
        获取 VIX 历史数据

        Polygon 中 VIX 指数代码为 I:VIX，应使用 aggregates 接口
        """
        if not self.available:
            return None

        df = self.get_daily_bars('I:VIX', start_date, end_date)
        if df is not None and not df.empty and 'Close' in df.columns:
            return df['Close']

        return None

    def get_vix(self):
        """获取最新 VIX（使用 I:VIX 的 aggregates 数据）"""
        if not self.available:
            return None

        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        vix_series = self.get_vix_data(start, end)

        if vix_series is not None and len(vix_series) > 0:
            return float(vix_series.iloc[-1])

        return None


class HybridDataSource:
    """
    混合数据源 - 优先 Polygon，失败回退 Yahoo Finance
    """

    def __init__(self, polygon_key=None):
        """
        初始化混合数据源

        参数:
            polygon_key: str, Polygon API Key
        """
        self.polygon = PolygonDataSource(polygon_key)
        self._yahoo_available = False

        try:
            import yfinance as yf
            self._yahoo_available = True
        except ImportError:
            pass

        logger.info("✅ 混合数据源已初始化")

    def get_prices(self, symbols, start_date, end_date, prefer_realtime=True):
        """
        获取价格数据（按 symbol+source+adjustment 缓存完整历史，使用时按日期切片）

        参数:
            symbols: list, 股票代码列表
            start_date: str
            end_date: str
            prefer_realtime: bool, 优先使用实时数据源

        返回:
            DataFrame: 价格数据
        """
        price_df = pd.DataFrame()
        source_order = [
            ('Polygon', 'adjusted'),
            ('Yahoo', 'adjusted'),
        ]

        for symbol in symbols:
            data = None
            used_source = None

            # 1. 按优先级尝试 source-specific 缓存
            for source, adjustment in source_order:
                cache_path = _get_cache_path(symbol, source=source, adjustment=adjustment)
                if _is_cache_valid(cache_path, CACHE_TTL_DAYS):
                    try:
                        loaded = _load_cache(cache_path, expected_source=source, expected_adjustment=adjustment)
                        loaded = _normalize_index(loaded)
                        if isinstance(loaded, pd.DataFrame) and 'Close' in loaded.columns:
                            series = loaded['Close']
                        elif isinstance(loaded, pd.Series):
                            series = loaded
                        else:
                            series = None
                        if series is not None and len(series) > 0:
                            data = series
                            used_source = source
                            break
                    except Exception as e:
                        logger.warning(f"Cache read failed for {symbol} ({source}): {e}")

            # 2. 尝试 Polygon（已含 source-specific 缓存）
            if data is None and prefer_realtime and self.polygon.available:
                df = self.polygon.get_daily_bars(symbol, start_date, end_date)
                if df is not None and not df.empty and 'Close' in df.columns:
                    data = df['Close']
                    used_source = 'Polygon'

            # 3. 回退 Yahoo Finance，并缓存结果
            if data is None and self._yahoo_available:
                try:
                    import yfinance as yf
                    ydata = yf.Ticker(symbol).history(period='max')
                    ydata = _normalize_index(ydata)
                    if len(ydata) > 0:
                        yahoo_path = _get_cache_path(symbol, source='Yahoo', adjustment='adjusted')
                        _save_cache(yahoo_path, ydata, source='Yahoo', adjustment='adjusted')
                        data = ydata.loc[start_date:end_date, 'Close']
                        used_source = 'Yahoo'
                except Exception as e:
                    logger.error(f"Failed to fetch {symbol} from Yahoo: {e}")

            if data is not None and len(data) > 0:
                try:
                    price_df[symbol] = data.loc[start_date:end_date]
                    logger.info(f"[Cache/{used_source}] {symbol}: {len(price_df[symbol])} records")
                except Exception as e:
                    logger.warning(f"{symbol} date slice failed: {e}")

        # P0修复: 按标的受限前向填充，超过 max_days 的缺失值保持 NaN，后续因子/选股会剔除
        price_df = price_df.dropna(how='all', axis=1)
        price_df = _limited_ffill(price_df)
        return price_df.dropna(how='all')

    def get_current_price(self, symbol):
        """
        获取当前价格（实时）

        参数:
            symbol: str

        返回:
            float: 当前价格
        """
        # 优先 Polygon
        if self.polygon.available:
            price = self.polygon.get_last_trade(symbol)
            if price:
                return price

        # 回退 Yahoo
        if self._yahoo_available:
            try:
                import yfinance as yf
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1d", interval="1m")
                if len(hist) > 0:
                    return float(hist['Close'].iloc[-1])
            except Exception:
                pass

        return None

    def get_vix_data(self, start_date, end_date):
        """获取 VIX 历史数据（优先 source-specific parquet 缓存）"""
        polygon_path = _get_cache_path('VIX', source='Polygon', adjustment='unadjusted')
        yahoo_path = _get_cache_path('VIX', source='Yahoo', adjustment='unadjusted')

        # 1. 按优先级尝试 source-specific 缓存
        for cache_path, source in [(polygon_path, 'Polygon'), (yahoo_path, 'Yahoo')]:
            if _is_cache_valid(cache_path, CACHE_TTL_DAYS):
                try:
                    vix = _load_cache(cache_path, expected_source=source, expected_adjustment='unadjusted')
                    vix = _normalize_index(vix)
                    if isinstance(vix, pd.DataFrame) and 'Close' in vix.columns:
                        vix = vix['Close']
                    return vix.loc[start_date:end_date]
                except Exception as e:
                    logger.warning(f"VIX cache read failed ({source}): {e}")

        # 2. 尝试 Polygon
        if self.polygon.available:
            vix = self.polygon.get_vix_data(start_date, end_date)
            if vix is not None and len(vix) > 0:
                return _normalize_index(vix)

        # 3. 回退 Yahoo 并缓存
        if self._yahoo_available:
            try:
                import yfinance as yf
                vix = yf.Ticker('^VIX').history(period='max')['Close']
                vix = _normalize_index(vix)
                _save_cache(yahoo_path, vix, source='Yahoo', adjustment='unadjusted')
                return vix.loc[start_date:end_date]
            except Exception:
                pass

        return None

    def get_market_data(self, start_date, end_date):
        """
        获取市场数据 (VIX + RSI proxy)，按 symbol+source+adjustment 缓存完整历史

        返回:
            DataFrame: 列=['VIX', 'RSI'], 索引=日期
        """
        # VIX 数据（已含缓存）
        vix_data = self.get_vix_data(start_date, end_date)

        # SPY 数据用于计算 RSI 和基础日期
        spy_data = None
        polygon_path = _get_cache_path('SPY', source='Polygon', adjustment='adjusted')
        yahoo_path = _get_cache_path('SPY', source='Yahoo', adjustment='adjusted')

        # 优先读取 source-specific parquet 缓存
        for cache_path, source in [(polygon_path, 'Polygon'), (yahoo_path, 'Yahoo')]:
            if _is_cache_valid(cache_path, CACHE_TTL_DAYS):
                try:
                    spy_df = _load_cache(cache_path, expected_source=source, expected_adjustment='adjusted')
                    spy_df = _normalize_index(spy_df)
                    if isinstance(spy_df, pd.DataFrame) and 'Close' in spy_df.columns:
                        spy_data = spy_df['Close'].loc[start_date:end_date]
                    elif isinstance(spy_df, pd.Series):
                        spy_data = spy_df.loc[start_date:end_date]
                    if spy_data is not None and len(spy_data) > 0:
                        break
                except Exception as e:
                    logger.warning(f"SPY cache read failed ({source}): {e}")

        # 回退 Polygon
        if spy_data is None and self.polygon.available:
            spy_df = self.polygon.get_daily_bars('SPY', start_date, end_date)
            if spy_df is not None and not spy_df.empty and 'Close' in spy_df.columns:
                spy_data = spy_df['Close']

        # 回退 Yahoo 并缓存
        if spy_data is None and self._yahoo_available:
            try:
                import yfinance as yf
                spy = yf.Ticker('SPY').history(period='max')['Close']
                spy = _normalize_index(spy)
                _save_cache(yahoo_path, spy, source='Yahoo', adjustment='adjusted')
                spy_data = spy.loc[start_date:end_date]
            except Exception:
                pass

        if spy_data is None or spy_data.empty:
            return pd.DataFrame()

        base_index = spy_data.index
        market_df = pd.DataFrame(index=base_index)

        if vix_data is not None and not vix_data.empty:
            market_df['VIX'] = vix_data.reindex(base_index)

        spy_data = _normalize_index(spy_data)
        spy_rsi = _compute_rsi_wilder(spy_data)
        market_df['RSI'] = spy_rsi.reindex(base_index)

        # 显式处理缺失值
        market_df = market_df.dropna(how='all')
        return market_df

    def get_vix(self):
        """获取 VIX"""
        # 尝试 Polygon
        if self.polygon.available:
            vix = self.polygon.get_vix()
            if vix:
                return vix

        # 回退 Yahoo
        if self._yahoo_available:
            try:
                import yfinance as yf
                vix_data = yf.Ticker('^VIX').history(period="5d")
                if len(vix_data) > 0:
                    return float(vix_data['Close'].iloc[-1])
            except Exception:
                pass

        return None


# 全局数据源实例
data_source = HybridDataSource()


# ============================================================
# 使用示例 - 展示 parquet 缓存行为（按 symbol 缓存完整历史）
# ============================================================

if __name__ == '__main__':
    # 测试混合数据源
    source = HybridDataSource()

    # 获取实时价格
    price = source.get_current_price('AAPL')
    print(f"AAPL 实时价格: ${price}")

    # 获取历史数据
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    print("\n首次调用 get_prices（Polygon 下载并写入 parquet 缓存）")
    prices = source.get_prices(['AAPL', 'MSFT'], start, end)
    print(f"\n历史数据:\n{prices.tail()}")

    print("\n再次调用 get_prices（预期命中 parquet 缓存）")
    prices = source.get_prices(['AAPL', 'MSFT'], start, end)
    print(f"\n历史数据:\n{prices.tail()}")

    # 展示缓存文件元数据
    print("\n缓存文件元数据:")
    for symbol in ['AAPL', 'MSFT', 'SPY', 'VIX']:
        if symbol in ('VIX',):
            adj = 'unadjusted'
        else:
            adj = 'adjusted'
        cache_path = _get_cache_path(symbol, source='Polygon', adjustment=adj)
        if not os.path.exists(cache_path):
            cache_path = _get_cache_path(symbol, source='Yahoo', adjustment=adj)
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

    # 获取 VIX
    vix = source.get_vix()
    print(f"\nVIX: {vix}")

    # 获取市场数据
    market_df = source.get_market_data(start, end)
    print(f"\n市场数据:\n{market_df.tail()}")
