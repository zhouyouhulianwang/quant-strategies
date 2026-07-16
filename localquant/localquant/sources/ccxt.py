"""CCXT 加密货币数据源"""
import logging
from typing import Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

class CCXTSource:
    """CCXT 加密货币数据获取"""
    
    def __init__(self, exchange='binance'):
        self.name = 'ccxt'
        self.exchange_name = exchange
        self._exchange = None
    
    def _get_exchange(self):
        """延迟初始化交易所"""
        if self._exchange is None:
            try:
                import ccxt
                self._exchange = getattr(ccxt, self.exchange_name)()
                logger.info(f"Initialized CCXT exchange: {self.exchange_name}")
            except ImportError:
                logger.error("ccxt not installed. Run: pip install ccxt")
                return None
        return self._exchange
    
    def fetch(self, symbol: str, start: datetime, end: datetime, 
              interval: str = '1d') -> Optional[pd.DataFrame]:
        """获取数据
        symbol: 交易对格式 'BTC/USDT'
        """
        exchange = self._get_exchange()
        if exchange is None:
            return None
        
        try:
            # 转换时间间隔为 CCXT 格式
            timeframe = self._convert_interval(interval)
            
            # 获取数据
            since = int(start.timestamp() * 1000)
            
            all_ohlcv = []
            while since < int(end.timestamp() * 1000):
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                
                if len(ohlcv) < 1000:
                    break
            
            if not all_ohlcv:
                logger.warning(f"No data returned for {symbol}")
                return None
            
            # 转换为 DataFrame
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('date', inplace=True)
            df = df.drop(columns=['timestamp'])
            
            # 过滤日期范围
            df = df[(df.index >= start) & (df.index <= end)]
            
            logger.info(f"Fetched {len(df)} rows for {symbol} from {self.exchange_name}")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching {symbol} from {self.exchange_name}: {e}")
            return None
    
    def _convert_interval(self, interval: str) -> str:
        """转换间隔为 CCXT 格式"""
        mapping = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '1h': '1h',
            '4h': '4h',
            '1d': '1d',
            '1w': '1w',
            '1M': '1M'
        }
        return mapping.get(interval, '1d')
