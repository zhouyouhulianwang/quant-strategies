"""Yahoo Finance 数据源"""
import logging
from typing import Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

class YahooFinanceSource:
    """Yahoo Finance 数据获取"""
    
    def __init__(self):
        self.name = 'yahoo'
    
    def fetch(self, symbol: str, start: datetime, end: datetime, 
              interval: str = '1d') -> Optional[pd.DataFrame]:
        """获取数据"""
        try:
            import yfinance as yf
            
            # 转换 interval
            yf_interval = self._convert_interval(interval)
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval=yf_interval)
            
            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return None
            
            # 标准化列名
            df = self._standardize(df)
            
            logger.info(f"Fetched {len(df)} rows for {symbol} from Yahoo Finance")
            return df
            
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
            return None
        except Exception as e:
            logger.error(f"Error fetching {symbol} from Yahoo Finance: {e}")
            return None
    
    def _convert_interval(self, interval: str) -> str:
        """转换间隔为 Yahoo Finance 格式"""
        mapping = {
            '1d': '1d',
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '1h': '1h',
            '1wk': '1wk',
            '1mo': '1mo'
        }
        return mapping.get(interval, '1d')
    
    def _standardize(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名"""
        df = df.copy()
        df.columns = [c.lower().replace(' ', '_') for c in df.columns]
        
        # 确保必需的列存在
        required = ['open', 'high', 'low', 'close', 'volume']
        for col in required:
            if col not in df.columns:
                logger.warning(f"Missing column: {col}")
        
        # 处理 dividends, stock_splits
        if 'dividends' in df.columns:
            df = df.drop(columns=['dividends'])
        if 'stock_splits' in df.columns:
            df = df.drop(columns=['stock_splits'])
        
        return df
