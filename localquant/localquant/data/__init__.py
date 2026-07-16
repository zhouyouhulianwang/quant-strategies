"""数据管理器 - 统一数据获取与缓存"""
import os
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ParquetCache:
    """Parquet 本地缓存"""
    
    def __init__(self, cache_dir: str = './data_cache'):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_path(self, symbol: str, interval: str, asset_type: str = 'stocks') -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / asset_type / interval / f"{symbol.upper()}.parquet"
    
    def exists(self, symbol: str, interval: str, asset_type: str = 'stocks') -> bool:
        """检查缓存是否存在"""
        return self._get_path(symbol, interval, asset_type).exists()
    
    def read(self, symbol: str, interval: str, asset_type: str = 'stocks',
             start: Optional[datetime] = None, end: Optional[datetime] = None) -> Optional[pd.DataFrame]:
        """读取缓存数据"""
        path = self._get_path(symbol, interval, asset_type)
        if not path.exists():
            return None
        
        try:
            df = pd.read_parquet(path)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
            elif df.index.name is None or df.index.name == 'index':
                df.index = pd.to_datetime(df.index)
                df.index.name = 'date'
            
            # 处理时区一致性问题
            if df.index.tz is not None and start is not None:
                start = pd.Timestamp(start).tz_localize(df.index.tz) if pd.Timestamp(start).tz is None else pd.Timestamp(start).tz_convert(df.index.tz)
            if df.index.tz is not None and end is not None:
                end = pd.Timestamp(end).tz_localize(df.index.tz) if pd.Timestamp(end).tz is None else pd.Timestamp(end).tz_convert(df.index.tz)
            
            if start:
                df = df[df.index >= start]
            if end:
                df = df[df.index <= end]
            
            return df
        except Exception as e:
            logger.error(f"Error reading cache for {symbol}: {e}")
            return None
    
    def write(self, symbol: str, interval: str, data: pd.DataFrame, 
              asset_type: str = 'stocks'):
        """写入缓存"""
        path = self._get_path(symbol, interval, asset_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 确保索引是日期类型
        df = data.copy()
        if df.index.name is None:
            df.index.name = 'date'
        
        df.to_parquet(path)
        logger.info(f"Cached {symbol} to {path}")
    
    def get_last_date(self, symbol: str, interval: str, asset_type: str = 'stocks') -> Optional[datetime]:
        """获取缓存数据的最后日期"""
        df = self.read(symbol, interval, asset_type)
        if df is not None and len(df) > 0:
            return df.index[-1]
        return None
