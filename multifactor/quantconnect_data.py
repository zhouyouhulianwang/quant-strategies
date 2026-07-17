"""
QuantConnect 数据源模块 - 通过 Lean CLI 获取数据
支持 Lean 本地数据格式读取，自动下载缺失数据
如果 QuantConnect 不可用，回退到 Alpaca Market Data API
"""

import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import subprocess
import zipfile
import io

# P2修复：统一全链路日志格式
from logging_config import setup_logging
setup_logging()

logger = logging.getLogger('quantconnect_data')

# Lean 数据目录
LEAN_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'lean')
os.makedirs(LEAN_DATA_DIR, exist_ok=True)

# QuantConnect 数据映射
QC_MARKET = 'usa'
QC_SECURITY_TYPE = 'equity'


def _normalize_index(data):
    """将时区感知索引统一为 naive 日期，保证多源数据对齐"""
    if data is None or len(data) == 0:
        return data
    if hasattr(data.index, 'tz') and data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    return data


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


def _yahoo_end_inclusive(end_date):
    """Yahoo Finance 的 history end 为右开区间，返回 end + 1 日"""
    return (pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')


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


def _get_cache_path(symbol, source='QuantConnect', adjustment='adjusted'):
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


def _save_cache(cache_path, data, source='QuantConnect', adjustment='adjusted'):
    """保存数据及元数据到 parquet 缓存，失败不抛异常（委托 cache.py）"""
    metadata = {
        'source': source,
        'adjustment': adjustment,
        'download_time': datetime.now().isoformat(),
    }
    return save_parquet_cache(data, cache_path, metadata=metadata, version=CACHE_VERSION)


class QuantConnectDataSource:
    """QuantConnect 数据源 - 通过 Lean CLI"""

    def __init__(self, data_dir=None):
        """
        初始化 QC 数据源

        参数:
            data_dir: str, Lean 数据目录
        """
        self.data_dir = data_dir or LEAN_DATA_DIR
        self.available = self._check_lean_available()

        if self.available:
            logger.info(f"✅ QuantConnect 数据源已初始化: {self.data_dir}")
        else:
            logger.warning("⚠️ Lean CLI 数据不可用")

    def _check_lean_available(self) -> bool:
        """检查 Lean CLI 是否可用"""
        try:
            result = subprocess.run(
                ['lean', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_data_path(self, symbol: str, resolution='daily') -> str:
        """
        获取 Lean 数据文件路径

        Lean 数据结构:
        data/equity/usa/daily/{SYMBOL}.zip
        """
        symbol_upper = symbol.upper()
        return os.path.join(
            self.data_dir,
            QC_SECURITY_TYPE,
            QC_MARKET,
            resolution,
            f"{symbol_upper}.zip"
        )

    def _download_via_lean(self, symbol: str, resolution='daily',
                           start_date=None, end_date=None) -> bool:
        """
        使用 lean data download 下载数据

        参数:
            symbol: str
            resolution: str, daily/hour/minute
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'

        返回:
            bool: 是否成功
        """
        if not self.available:
            return False

        try:
            logger.info(f"📥 通过 Lean CLI 下载 {symbol} {resolution} 数据...")

            # 构建 lean 命令
            cmd = [
                'lean', 'data', 'download',
                '--dataset', 'QuantConnect',
                '--data-type', 'Trade',
                '--resolution', resolution,
                '--ticker', symbol.upper(),
                '--market', QC_MARKET,
            ]

            if start_date:
                cmd.extend(['--start-date', start_date])
            if end_date:
                cmd.extend(['--end-date', end_date])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                logger.info(f"✅ {symbol} 数据下载成功")
                return True
            else:
                logger.warning(f"⚠️ {symbol} 数据下载失败: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"⏱️ {symbol} 数据下载超时")
            return False
        except Exception as e:
            logger.error(f"❌ {symbol} 数据下载错误: {e}")
            return False

    def _read_lean_data(self, symbol: str, resolution='daily') -> Optional[pd.DataFrame]:
        """
        读取 Lean 格式数据

        Lean CSV 格式:
        date,open,high,low,close,volume

        返回:
            DataFrame: 列=['Open','High','Low','Close','Volume'], 索引=日期
        """
        data_path = self._get_data_path(symbol, resolution)

        if not os.path.exists(data_path):
            return None

        try:
            # 读取 zip 文件中的 CSV
            with zipfile.ZipFile(data_path, 'r') as z:
                # Lean 数据文件名格式: {SYMBOL}.csv
                csv_name = f"{symbol.upper()}.csv"
                if csv_name not in z.namelist():
                    # 尝试其他命名
                    for name in z.namelist():
                        if name.endswith('.csv'):
                            csv_name = name
                            break

                with z.open(csv_name) as f:
                    df = pd.read_csv(
                        f,
                        header=None,
                        names=['date', 'open', 'high', 'low', 'close', 'volume']
                    )

            # 明确解析 Lean 日期格式（YYYYMMDD）
            df['date'] = pd.to_datetime(df['date'].astype(str), format='%Y%m%d', errors='coerce')
            df = df.dropna(subset=['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)

            # 重命名列
            df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'volume': 'Volume'
            }, inplace=True)

            # 优先使用调整后的收盘价（如果存在），否则使用 close
            if 'adjusted_close' in df.columns:
                df['Close'] = df['adjusted_close']
            else:
                df['Close'] = df['close']

            return df

        except Exception as e:
            logger.error(f"读取 {symbol} Lean 数据失败: {e}")
            return None

    def get_price_data(self, symbols: List[str], start_date: str, end_date: str,
                       resolution='daily', auto_download=True) -> pd.DataFrame:
        """
        获取价格数据（QuantConnect 为主数据源）

        参数:
            symbols: list, 股票代码列表
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'
            resolution: str, 'daily' | 'hour' | 'minute'
            auto_download: bool, 自动下载缺失数据

        返回:
            DataFrame: 索引=日期, 列=股票代码, 值=收盘价
        """
        price_df = pd.DataFrame()

        for symbol in symbols:
            # 1. 尝试读取本地 Lean 数据
            df = self._read_lean_data(symbol, resolution)

            # 2. 如果缺失且允许自动下载，尝试下载
            if df is None and auto_download and self.available:
                if self._download_via_lean(symbol, resolution, start_date, end_date):
                    df = self._read_lean_data(symbol, resolution)

            # 3. 检查数据是否满足日期范围
            if df is not None:
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df.index >= start_dt) & (df.index <= end_dt)]

                if len(df) > 0:
                    price_df[symbol] = df['Close']
                    logger.info(f"[QC] {symbol}: {len(df)} 条记录")
                else:
                    logger.warning(f"[QC] {symbol} 数据日期范围不匹配")
            else:
                logger.warning(f"[QC] {symbol} 数据不可用")

        return price_df.dropna(how='all')

    def get_vix_data(self, start_date: str, end_date: str) -> Optional[pd.Series]:
        """
        获取 VIX 数据

        QuantConnect 中 VIX 的代码通常是 "VIX"
        """
        # VIX 在 QuantConnect 中作为指数
        vix_df = self.get_price_data(
            ['VIX'], start_date, end_date, auto_download=False
        )

        if 'VIX' in vix_df.columns and len(vix_df) > 0:
            return vix_df['VIX']

        return None


class AlpacaMarketData:
    """Alpaca Market Data API - 作为 QuantConnect 的 fallback"""

    def __init__(self, api_key=None, api_secret=None):
        """
        初始化 Alpaca Market Data

        参数:
            api_key: str
            api_secret: str
        """
        # 使用 dotenv_values 读取 .env，不污染全局环境变量
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        env_values = {}
        if os.path.exists(env_path):
            try:
                from dotenv import dotenv_values
                env_values = dotenv_values(env_path) or {}
            except Exception as e:
                logger.warning(f"读取 .env 失败: {e}")

        self.api_key = (
            api_key
            or env_values.get('ALPACA_API_KEY')
            or os.getenv('ALPACA_API_KEY')
        )
        self.api_secret = (
            api_secret
            or env_values.get('ALPACA_API_SECRET')
            or os.getenv('ALPACA_API_SECRET')
        )
        self.base_url = 'https://data.alpaca.markets'

        if not self.api_key or not self.api_secret:
            logger.warning("⚠️ Alpaca Market Data API Key 未设置")
            self.available = False
        else:
            self.available = True
            logger.info("✅ Alpaca Market Data 已初始化")

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """发送请求到 Alpaca Data API"""
        import requests

        headers = {
            'APCA-API-KEY-ID': self.api_key,
            'APCA-API-SECRET-KEY': self.api_secret
        }

        url = f"{self.base_url}/v2/{endpoint}"

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Alpaca API 请求失败: {e}")
            return {}

    def get_bars(self, symbol: str, start: str, end: str,
                 timeframe='1Day') -> Optional[pd.DataFrame]:
        """
        获取历史 K 线（自动处理 next_page_token 分页）

        参数:
            symbol: str
            start: str, 'YYYY-MM-DD'
            end: str, 'YYYY-MM-DD'
            timeframe: str, '1Min' | '1Hour' | '1Day'

        返回:
            DataFrame
        """
        if not self.available:
            return None

        # 调整日期格式
        start_iso = f"{start}T00:00:00Z"
        end_iso = f"{end}T23:59:59Z"

        endpoint = f"stocks/{symbol.upper()}/bars"
        params = {
            'start': start_iso,
            'end': end_iso,
            'timeframe': timeframe,
            'limit': 10000,
            'adjustment': 'all'
        }

        all_bars = []
        while True:
            data = self._request(endpoint, params)
            if not data or 'bars' not in data:
                break

            all_bars.extend(data['bars'])

            next_token = data.get('next_page_token')
            if not next_token:
                break

            # 继续分页
            params = {
                'start': start_iso,
                'end': end_iso,
                'timeframe': timeframe,
                'limit': 10000,
                'adjustment': 'all',
                'page_token': next_token,
            }

        if not all_bars:
            return None

        df = pd.DataFrame(all_bars)
        df['t'] = pd.to_datetime(df['t'])
        df['t'] = df['t'].dt.tz_localize(None)
        df.set_index('t', inplace=True)
        df.rename(columns={
            'o': 'Open', 'h': 'High', 'l': 'Low',
            'c': 'Close', 'v': 'Volume', 'n': 'TradeCount', 'vw': 'VWAP'
        }, inplace=True)

        return df

    def get_latest_trade(self, symbol: str) -> Optional[float]:
        """获取最新成交价"""
        if not self.available:
            return None

        data = self._request(f"stocks/{symbol.upper()}/trades/latest")

        if data and 'trade' in data:
            return float(data['trade']['p'])

        return None

    def get_latest_quote(self, symbol: str) -> Optional[dict]:
        """获取最新报价"""
        if not self.available:
            return None

        data = self._request(f"stocks/{symbol.upper()}/quotes/latest")

        if data and 'quote' in data:
            return {
                'bid': float(data['quote']['bp']),
                'ask': float(data['quote']['ap']),
                'bid_size': int(data['quote']['bs']),
                'ask_size': int(data['quote']['as']),
            }

        return None


class HybridQCDataSource:
    """
    混合数据源: QuantConnect → Alpaca → Yahoo Finance
    优先使用 QuantConnect/Lean 数据
    """

    def __init__(self, alpaca_key=None, alpaca_secret=None):
        """
        初始化混合数据源

        参数:
            alpaca_key: str, Alpaca API Key (fallback)
            alpaca_secret: str, Alpaca API Secret
        """
        self.qc = QuantConnectDataSource()
        self.alpaca = AlpacaMarketData(alpaca_key, alpaca_secret)

        # Yahoo Finance 作为最终 fallback
        self._yahoo_available = False
        try:
            import yfinance as yf
            self._yahoo_available = True
        except ImportError:
            pass

        logger.info("✅ 混合数据源已初始化 (QC → Alpaca → Yahoo)")

    def get_prices(self, symbols: List[str], start_date: str, end_date: str,
                   resolution='daily') -> pd.DataFrame:
        """
        获取价格数据（按 symbol+source+adjustment 缓存完整历史，使用时按日期切片）

        优先级: QuantConnect → Alpaca → Yahoo Finance
        """
        price_df = pd.DataFrame()
        source_order = [
            ('QuantConnect', 'adjusted'),
            ('Alpaca', 'adjusted'),
            ('Yahoo', 'adjusted'),
        ]

        for symbol in symbols:
            data = None
            used_source = None
            used_path = None

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
                            used_path = cache_path
                            break
                    except Exception as e:
                        logger.warning(f"Cache read failed for {symbol} ({source}): {e}")

            # 2. 缓存未命中：按优先级获取完整历史
            if data is None:
                full_series, source = self._fetch_single_symbol_full(symbol, start_date, end_date, resolution)
                if full_series is not None and len(full_series) > 0:
                    used_source = source
                    used_path = _get_cache_path(symbol, source=source, adjustment='adjusted')
                    # 保存完整历史到 source-specific parquet
                    _save_cache(used_path, full_series, source=source, adjustment='adjusted')
                    data = full_series

            if data is not None and len(data) > 0:
                try:
                    series = data.loc[start_date:end_date]
                    price_df[symbol] = series
                    logger.info(f"[Cache/{used_source}] {symbol}: {len(series)} records")
                except Exception as e:
                    logger.warning(f"{symbol} date slice failed: {e}")

        # P1修复: 按标的前向填充，不要按行 dropna(how='any') 删整行，避免幸存者偏差
        price_df = price_df.dropna(how='all', axis=1)
        price_df = price_df.ffill()
        return price_df.dropna(how='all')

    def _fetch_single_symbol_full(self, symbol: str, start_date: str, end_date: str,
                                  resolution='daily'):
        """获取单标的完整历史，返回 (series, source)，失败返回 (None, None)"""
        # 1. QuantConnect（Lean 本地文件包含完整历史）
        if self.qc.available:
            try:
                df = self.qc._read_lean_data(symbol, resolution)
                if df is None and self.qc.available:
                    self.qc._download_via_lean(symbol, resolution, start_date, end_date)
                    df = self.qc._read_lean_data(symbol, resolution)
                if df is not None and 'Close' in df.columns:
                    return _normalize_index(df['Close']), 'QuantConnect'
            except Exception as e:
                logger.warning(f"QC 获取 {symbol} 失败: {e}")

        # 2. Alpaca（回退）
        if self.alpaca.available:
            try:
                timeframe = '1Day' if resolution == 'daily' else '1Hour'
                df = self.alpaca.get_bars(symbol, start_date, end_date, timeframe)
                if df is not None and len(df) > 0 and 'Close' in df.columns:
                    return _normalize_index(df['Close']), 'Alpaca'
            except Exception as e:
                logger.warning(f"Alpaca 获取 {symbol} 失败: {e}")

        # 3. Yahoo Finance（最终回退）
        if self._yahoo_available:
            try:
                import yfinance as yf
                data = yf.Ticker(symbol).history(period='max')['Close']
                data = _normalize_index(data)
                return data, 'Yahoo'
            except Exception as e:
                logger.warning(f"Yahoo 获取 {symbol} 失败: {e}")

        return None, None


    def get_vix(self) -> Optional[float]:
        """
        获取 VIX

        优先级: QuantConnect → Yahoo Finance
        (Alpaca 不提供 VIX 数据)
        """
        # 1. 尝试 QuantConnect
        if self.qc.available:
            vix_series = self.qc.get_vix_data(
                (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )
            if vix_series is not None and len(vix_series) > 0:
                return float(vix_series.iloc[-1])

        # 2. 回退到 Yahoo
        if self._yahoo_available:
            try:
                import yfinance as yf
                vix_data = yf.Ticker('^VIX').history(period='5d')
                if len(vix_data) > 0:
                    return float(vix_data['Close'].iloc[-1])
            except Exception:
                pass

        return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取实时价格

        优先级: Alpaca → Yahoo
        """
        # Alpaca 实时数据最快
        if self.alpaca.available:
            price = self.alpaca.get_latest_trade(symbol)
            if price:
                return price

        # 回退 Yahoo
        if self._yahoo_available:
            try:
                import yfinance as yf
                hist = yf.Ticker(symbol).history(period='1d', interval='1m')
                if len(hist) > 0:
                    return float(hist['Close'].iloc[-1])
            except Exception:
                pass

        return None

    def get_market_data(self, start_date: str, end_date: str,
                        resolution='daily') -> pd.DataFrame:
        """
        获取市场数据 (VIX + RSI proxy)，按 symbol 缓存完整历史

        参数:
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'
            resolution: str, 'daily' | 'hour'

        返回:
            DataFrame: 列=['VIX', 'RSI'], 索引=日期
        """
        # VIX 与 SPY 均优先使用 parquet 缓存
        vix_data = self._get_vix_cached(start_date, end_date)
        spy_full = self._get_spy_cached(start_date, end_date, resolution)

        if spy_full is None or len(spy_full) == 0:
            return pd.DataFrame()

        base_index = spy_full.index
        market_df = pd.DataFrame(index=base_index)

        if vix_data is not None and len(vix_data) > 0:
            market_df['VIX'] = vix_data.reindex(base_index)

        spy_rsi = _compute_rsi_wilder(spy_full)
        market_df['RSI'] = spy_rsi.reindex(base_index)

        market_df = market_df.dropna(how='all')
        return market_df

    def _get_vix_cached(self, start_date: str, end_date: str):
        """获取 VIX 数据（优先 source-specific parquet 缓存）"""
        # VIX 可能来自 QuantConnect 或 Yahoo，均使用 unadjusted
        qc_path = _get_cache_path('VIX', source='QuantConnect', adjustment='unadjusted')
        yahoo_path = _get_cache_path('VIX', source='Yahoo', adjustment='unadjusted')

        for cache_path, source in [(qc_path, 'QuantConnect'), (yahoo_path, 'Yahoo')]:
            if _is_cache_valid(cache_path, CACHE_TTL_DAYS):
                try:
                    vix = _load_cache(cache_path, expected_source=source, expected_adjustment='unadjusted')
                    vix = _normalize_index(vix)
                    return vix.loc[start_date:end_date]
                except Exception as e:
                    logger.warning(f"VIX cache read failed ({source}): {e}")

        # 尝试 QuantConnect
        if self.qc.available:
            try:
                vix = self.qc.get_vix_data(start_date, end_date)
                if vix is not None and len(vix) > 0:
                    _save_cache(qc_path, vix, source='QuantConnect', adjustment='unadjusted')
                    return _normalize_index(vix.loc[start_date:end_date])
            except Exception as e:
                logger.warning(f"QC VIX fetch failed: {e}")

        # 回退 Yahoo
        if self._yahoo_available:
            try:
                import yfinance as yf
                vix = yf.Ticker('^VIX').history(period='max')['Close']
                vix = _normalize_index(vix)
                _save_cache(yahoo_path, vix, source='Yahoo', adjustment='unadjusted')
                return vix.loc[start_date:end_date]
            except Exception as e:
                logger.warning(f"Yahoo VIX fetch failed: {e}")

        return None

    def _get_spy_cached(self, start_date: str, end_date: str, resolution: str):
        """获取 SPY 完整历史（优先 source-specific parquet 缓存）"""
        qc_path = _get_cache_path('SPY', source='QuantConnect', adjustment='adjusted')
        yahoo_path = _get_cache_path('SPY', source='Yahoo', adjustment='adjusted')

        for cache_path, source in [(qc_path, 'QuantConnect'), (yahoo_path, 'Yahoo')]:
            if _is_cache_valid(cache_path, CACHE_TTL_DAYS):
                try:
                    spy = _load_cache(cache_path, expected_source=source, expected_adjustment='adjusted')
                    spy = _normalize_index(spy)
                    return spy.loc[start_date:end_date]
                except Exception as e:
                    logger.warning(f"SPY cache read failed ({source}): {e}")

        # 尝试 QuantConnect
        if self.qc.available:
            try:
                df = self.qc._read_lean_data('SPY', resolution)
                if df is None and self.qc.available:
                    self.qc._download_via_lean('SPY', resolution, start_date, end_date)
                    df = self.qc._read_lean_data('SPY', resolution)
                if df is not None and 'Close' in df.columns:
                    spy = _normalize_index(df['Close'])
                    _save_cache(qc_path, spy, source='QuantConnect', adjustment='adjusted')
                    return spy.loc[start_date:end_date]
            except Exception as e:
                logger.warning(f"QC SPY fetch failed: {e}")

        # 回退 Yahoo
        if self._yahoo_available:
            try:
                import yfinance as yf
                spy = yf.Ticker('SPY').history(period='max')['Close']
                spy = _normalize_index(spy)
                _save_cache(yahoo_path, spy, source='Yahoo', adjustment='adjusted')
                return spy.loc[start_date:end_date]
            except Exception as e:
                logger.warning(f"Yahoo SPY fetch failed: {e}")

        return None



def _align_and_clean(price_df, market_df):
    """取交易日交集并显式处理缺失值；P1修复: 按标的前向填充，避免按行 dropna 产生幸存者偏差"""
    if price_df is None or market_df is None:
        return price_df, market_df

    if len(price_df) == 0 or len(market_df) == 0:
        return price_df, market_df

    common_dates = price_df.index.intersection(market_df.index)
    price_df = price_df.reindex(common_dates)
    market_df = market_df.reindex(common_dates)

    price_df = price_df.dropna(how='all', axis=1)
    market_df = market_df.dropna(how='all')

    common_dates = price_df.index.intersection(market_df.index)
    price_df = price_df.loc[common_dates]
    market_df = market_df.loc[common_dates]

    # P1修复: 按标的前向填充，不要按行 dropna(how='any')
    price_df = price_df.ffill()
    market_df = market_df.ffill()

    return price_df, market_df


def prepare_backtest_data_qc(tickers, start_date, end_date, resolution='daily'):
    """
    准备回测数据（QuantConnect 优先）

    参数:
        tickers: list, 股票代码
        start_date: str, 'YYYY-MM-DD'
        end_date: str, 'YYYY-MM-DD'
        resolution: str, 'daily' | 'hour'

    返回:
        tuple: (price_df, market_df)
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Preparing backtest data (QuantConnect priority)")
    logger.info(f"{'='*60}")
    logger.info(f"Period: {start_date} ~ {end_date}")

    # PIT/公司行为：移除退市股票
    try:
        from data_source import filter_universe_for_corporate_actions
        filtered_tickers, corp_actions = filter_universe_for_corporate_actions(
            tickers, start_date, end_date
        )
        if len(filtered_tickers) < len(tickers):
            logger.warning(
                "[PIT] Universe reduced from %d to %d after corporate-action filtering",
                len(tickers), len(filtered_tickers)
            )
        tickers = filtered_tickers
    except Exception as e:
        logger.warning(f"[PIT] Could not filter universe for corporate actions: {e}")

    source = HybridQCDataSource()

    # 获取价格数据
    price_df = source.get_prices(tickers, start_date, end_date, resolution)

    # 获取市场数据
    market_df = source.get_market_data(start_date, end_date, resolution)

    # 对齐日期并处理缺失值
    price_df, market_df = _align_and_clean(price_df, market_df)

    logger.info(f"\n[Done] Price data: {len(price_df)} trading days")
    logger.info(f"[Done] Market data: {len(market_df)} trading days")
    logger.info(f"[Done] Stock count: {len(price_df.columns)}")

    return price_df, market_df


# ============================================================
# 使用示例 - 展示 parquet 缓存行为（按 symbol 缓存完整历史）
# ============================================================

if __name__ == '__main__':
    from main import TICKERS

    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    # 使用混合数据源
    source = HybridQCDataSource()

    # 首次调用：下载并缓存为 parquet
    print("\n首次调用 get_prices（预期下载并写入 parquet 缓存）")
    prices = source.get_prices(['AAPL', 'MSFT'], start, end)
    print(f"\n价格数据:\n{prices.tail()}")

    # 再次调用：命中 parquet 缓存
    print("\n再次调用 get_prices（预期命中 parquet 缓存）")
    prices = source.get_prices(['AAPL', 'MSFT'], start, end)
    print(f"\n价格数据:\n{prices.tail()}")

    # 展示缓存文件元数据
    print("\n缓存文件元数据:")
    for symbol in ['AAPL', 'MSFT', 'SPY', 'VIX']:
        if symbol in ('VIX',):
            adj = 'unadjusted'
        else:
            adj = 'adjusted'
        cache_path = _get_cache_path(symbol, source='QuantConnect', adjustment=adj)
        if not os.path.exists(cache_path):
            # 可能是 Yahoo 回退缓存
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

    # 测试市场数据（VIX + RSI）
    print("\n测试市场数据（含缓存 VIX 与 SPY）")
    market_df = source.get_market_data(start, end)
    print(f"\n市场数据:\n{market_df.tail()}")

    # 测试 VIX
    vix = source.get_vix()
    print(f"\n当前 VIX: {vix}")

    # 测试实时价格
    price = source.get_current_price('AAPL')
    print(f"\nAAPL 实时价格: ${price}")
