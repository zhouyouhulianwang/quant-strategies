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

logger = logging.getLogger('quantconnect_data')

# Lean 数据目录
LEAN_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data', 'lean')
os.makedirs(LEAN_DATA_DIR, exist_ok=True)

# QuantConnect 数据映射
QC_MARKET = 'usa'
QC_SECURITY_TYPE = 'equity'


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
            logger.info(f"✅ QuantConnect 数据源已初始化: {data_dir}")
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
            
            # 解析日期
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            df.sort_index(inplace=True)
            
            # 重命名列
            df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }, inplace=True)
            
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
        # 从 .env 读取
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.startswith('#'):
                        key, value = line.strip().split('=', 1)
                        os.environ[key] = value
        
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.api_secret = api_secret or os.getenv('ALPACA_API_SECRET')
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
        获取历史 K 线
        
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
        
        data = self._request(endpoint, params)
        
        if not data or 'bars' not in data:
            return None
        
        df = pd.DataFrame(data['bars'])
        df['t'] = pd.to_datetime(df['t'])
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
        获取价格数据
        
        优先级: QuantConnect → Alpaca → Yahoo Finance
        """
        price_df = pd.DataFrame()
        missing_symbols = []
        
        # 1. 尝试 QuantConnect
        if self.qc.available:
            price_df = self.qc.get_price_data(
                symbols, start_date, end_date, resolution, auto_download=True
            )
            
            # 找出缺失的标的
            for s in symbols:
                if s not in price_df.columns or price_df[s].isna().all():
                    missing_symbols.append(s)
        else:
            missing_symbols = symbols.copy()
        
        # 2. 回退到 Alpaca
        if missing_symbols and self.alpaca.available:
            logger.info(f"📡 {len(missing_symbols)} 只标的回退到 Alpaca")
            
            for symbol in missing_symbols:
                try:
                    timeframe = '1Day' if resolution == 'daily' else '1Hour'
                    df = self.alpaca.get_bars(symbol, start_date, end_date, timeframe)
                    
                    if df is not None and len(df) > 0:
                        price_df[symbol] = df['Close']
                        logger.info(f"[Alpaca] {symbol}: {len(df)} 条")
                    else:
                        # 3. 回退到 Yahoo
                        if self._yahoo_available:
                            self._fetch_from_yahoo(symbol, start_date, end_date, price_df)
                            
                except Exception as e:
                    logger.error(f"获取 {symbol} 失败: {e}")
                    # 最终回退 Yahoo
                    if self._yahoo_available:
                        self._fetch_from_yahoo(symbol, start_date, end_date, price_df)
        
        # 如果 QC 不可用，全部走 Alpaca
        elif not self.qc.available and self.alpaca.available:
            logger.info("📡 QuantConnect 不可用，使用 Alpaca 数据源")
            for symbol in symbols:
                try:
                    df = self.alpaca.get_bars(symbol, start_date, end_date, '1Day')
                    if df is not None and len(df) > 0:
                        price_df[symbol] = df['Close']
                except Exception as e:
                    logger.error(f"Alpaca 获取 {symbol} 失败: {e}")
        
        return price_df.dropna(how='all')
    
    def _fetch_from_yahoo(self, symbol: str, start: str, end: str, 
                          price_df: pd.DataFrame):
        """从 Yahoo Finance 获取（最终回退）"""
        try:
            import yfinance as yf
            data = yf.Ticker(symbol).history(start=start, end=end)
            if len(data) > 0:
                price_df[symbol] = data['Close']
                logger.info(f"[Yahoo] {symbol}: {len(data)} 条")
        except Exception as e:
            logger.error(f"Yahoo 获取 {symbol} 失败: {e}")
    
    def get_vix(self) -> Optional[float]:
        """
        获取 VIX
        
        优先级: QuantConnect → Yahoo Finance
        (Alpaca 不提供 VIX 数据)
        """
        # 1. 尝试 QuantConnect
        if self.qc.available:
            # VIX 在 QC 中的代码
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
    
    def get_market_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取市场数据 (VIX + RSI proxy)
        
        参数:
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'
        
        返回:
            DataFrame: 列=['VIX', 'RSI'], 索引=日期
        """
        # VIX
        vix_data = None
        
        # 尝试 QuantConnect
        if self.qc.available:
            vix_data = self.qc.get_vix_data(start_date, end_date)
        
        # 回退 Yahoo
        if vix_data is None and self._yahoo_available:
            try:
                import yfinance as yf
                vix = yf.Ticker('^VIX').history(start=start_date, end=end_date)['Close']
                vix_data = vix
            except Exception:
                pass
        
        # SPY RSI 作为市场 RSI 代理
        spy_rsi = None
        if self._yahoo_available:
            try:
                import yfinance as yf
                spy = yf.Ticker('SPY').history(start=start_date, end=end_date)['Close']
                delta = spy.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                spy_rsi = 100 - (100 / (1 + rs))
            except Exception:
                pass
        
        # 合并
        market_df = pd.DataFrame(index=vix_data.index if vix_data is not None else pd.DatetimeIndex([]))
        
        if vix_data is not None:
            market_df['VIX'] = vix_data
        
        if spy_rsi is not None:
            market_df['RSI'] = spy_rsi
        
        return market_df.dropna()


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
    print(f"\n{'='*60}")
    print(f"准备回测数据 (QuantConnect 优先)")
    print(f"{'='*60}")
    print(f"期间: {start_date} ~ {end_date}")
    
    source = HybridQCDataSource()
    
    # 获取价格数据
    price_df = source.get_prices(tickers, start_date, end_date, resolution)
    
    # 获取市场数据
    market_df = source.get_market_data(start_date, end_date)
    
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
    
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    # 使用混合数据源
    source = HybridQCDataSource()
    
    # 测试价格获取
    prices = source.get_prices(['AAPL', 'MSFT'], start, end)
    print(f"\n价格数据:\n{prices.tail()}")
    
    # 测试 VIX
    vix = source.get_vix()
    print(f"\n当前 VIX: {vix}")
    
    # 测试实时价格
    price = source.get_current_price('AAPL')
    print(f"\nAAPL 实时价格: ${price}")
