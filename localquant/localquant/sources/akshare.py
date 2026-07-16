"""AKShare A股数据源"""
import logging
from typing import Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

class AKShareSource:
    """AKShare A股数据获取"""
    
    def __init__(self):
        self.name = 'akshare'
    
    def fetch(self, symbol: str, start: datetime, end: datetime, 
              interval: str = '1d') -> Optional[pd.DataFrame]:
        """获取数据
        symbol: A股代码格式 '600519' (不带后缀)
        """
        try:
            import akshare as ak
            
            # 转换日期格式
            start_str = start.strftime('%Y%m%d')
            end_str = end.strftime('%Y%m%d')
            
            if interval == '1d':
                # 日线数据
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_str,
                    end_date=end_str,
                    adjust="qfq"  # 前复权
                )
            elif interval == '1wk':
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="weekly",
                    start_date=start_str,
                    end_date=end_str,
                    adjust="qfq"
                )
            elif interval == '1m':
                # 分钟数据
                df = ak.stock_zh_a_hist_min_em(
                    symbol=symbol,
                    start_date=start_str,
                    end_date=end_str,
                    adjust="qfq"
                )
            else:
                logger.warning(f"Unsupported interval for AKShare: {interval}")
                return None
            
            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return None
            
            # 标准化列名
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '振幅': 'amplitude',
                '涨跌幅': 'pct_change',
                '涨跌额': 'change',
                '换手率': 'turnover'
            })
            
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
            # 确保数值类型
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            logger.info(f"Fetched {len(df)} rows for {symbol} from AKShare")
            return df
            
        except ImportError:
            logger.error("akshare not installed. Run: pip install akshare")
            return None
        except Exception as e:
            logger.error(f"Error fetching {symbol} from AKShare: {e}")
            return None
    
    def fetch_index(self, symbol: str = 'sh000001', start: datetime = None, 
                   end: datetime = None) -> Optional[pd.DataFrame]:
        """获取指数数据"""
        try:
            import akshare as ak
            
            start_str = start.strftime('%Y%m%d') if start else None
            end_str = end.strftime('%Y%m%d') if end else None
            
            if symbol == 'sh000001':
                df = ak.index_zh_a_hist(symbol='000001', period='daily')
            elif symbol == 'sz399001':
                df = ak.index_zh_a_hist(symbol='399001', period='daily')
            else:
                df = ak.index_zh_a_hist(symbol=symbol, period='daily')
            
            if df.empty:
                return None
            
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume'
            })
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching index {symbol}: {e}")
            return None
