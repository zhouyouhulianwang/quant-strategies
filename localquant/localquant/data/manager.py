"""数据管理器 - 统一数据获取接口"""
import pandas as pd
from typing import Optional, List
from datetime import datetime, timedelta
from localquant.data import ParquetCache
from localquant.sources import YahooFinanceSource
from localquant.sources.ccxt import CCXTSource
from localquant.sources.akshare import AKShareSource
import logging

logger = logging.getLogger(__name__)

class DataManager:
    """统一数据管理器"""
    
    def __init__(self, cache_dir: str = './data_cache'):
        self.cache = ParquetCache(cache_dir)
        self.sources = {
            'yahoo': YahooFinanceSource(),
            'ccxt': CCXTSource(exchange='binance'),
            'akshare': AKShareSource()
        }
    
    def get_data(self, symbol: str, 
                 start: Optional[datetime] = None,
                 end: Optional[datetime] = None,
                 interval: str = '1d',
                 source: str = 'yahoo',
                 asset_type: str = 'stocks',
                 auto_update: bool = True) -> pd.DataFrame:
        """
        获取数据（自动缓存）
        """
        if end is None:
            end = datetime.now()
        if start is None:
            start = end - timedelta(days=365*5)
        
        # 获取数据
        cached = self.cache.read(symbol, interval, asset_type, start, end)
        
        if cached is not None and len(cached) > 0:
            # 检查是否需要更新
            if auto_update:
                last_date = self.cache.get_last_date(symbol, interval, asset_type)
                # 使用标准化时区无关比较
                end_cmp = pd.Timestamp(end)
                if last_date is not None:
                    last_cmp = pd.Timestamp(last_date).tz_localize(None) if last_date.tz else pd.Timestamp(last_date)
                    end_cmp_naive = end_cmp.tz_localize(None) if end_cmp.tz else end_cmp
                    if last_cmp < end_cmp_naive - timedelta(days=2):
                        logger.info(f"Cache stale for {symbol}, updating...")
                        new_data = self._fetch_from_source(symbol, last_date, end, interval, source)
                        if new_data is not None and len(new_data) > 0:
                            # 合并前统一时区
                            if cached.index.tz is not None and new_data.index.tz is None:
                                new_data.index = new_data.index.tz_localize(cached.index.tz)
                            elif cached.index.tz is None and new_data.index.tz is not None:
                                new_data.index = new_data.index.tz_localize(None)
                            
                            cached = pd.concat([cached, new_data])
                            cached = cached[~cached.index.duplicated(keep='last')]
                            self.cache.write(symbol, interval, cached, asset_type)
            
            return self._filter_date(cached, start, end)
        
        # 从数据源获取
        if auto_update:
            data = self._fetch_from_source(symbol, start, end, interval, source)
            if data is not None and len(data) > 0:
                self.cache.write(symbol, interval, data, asset_type)
                return self._filter_date(data, start, end)
        
        return pd.DataFrame()
    
    def get_multi_data(self, symbols: List[str], 
                       start: Optional[datetime] = None,
                       end: Optional[datetime] = None,
                       interval: str = '1d',
                       source: str = 'yahoo') -> pd.DataFrame:
        """获取多标的数据，返回 MultiIndex DataFrame"""
        all_data = {}
        
        for symbol in symbols:
            df = self.get_data(symbol, start, end, interval, source)
            if df is not None and len(df) > 0:
                all_data[symbol] = df
        
        if not all_data:
            return pd.DataFrame()
        
        # 合并为多索引 DataFrame
        dfs = []
        for symbol, df in all_data.items():
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    dfs.append(pd.DataFrame({(col, symbol): df[col]}))
        
        if dfs:
            combined = pd.concat(dfs, axis=1)
            combined.columns = pd.MultiIndex.from_tuples(combined.columns)
            return combined.sort_index()
        
        return pd.DataFrame()
    
    def _fetch_from_source(self, symbol: str, start: datetime, end: datetime,
                          interval: str, source: str) -> Optional[pd.DataFrame]:
        """从数据源获取数据"""
        src = self.sources.get(source)
        if src is None:
            logger.error(f"Unknown source: {source}")
            return None
        
        return src.fetch(symbol, start, end, interval)
    
    def _filter_date(self, df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
        """过滤日期范围"""
        if df.index.name is None:
            df.index.name = 'date'
        
        # 处理时区 - 确保比较时区一致
        idx = df.index
        if idx.tz is not None:
            start = pd.Timestamp(start).tz_localize(idx.tz) if pd.Timestamp(start).tz is None else pd.Timestamp(start).tz_convert(idx.tz)
            end = pd.Timestamp(end).tz_localize(idx.tz) if pd.Timestamp(end).tz is None else pd.Timestamp(end).tz_convert(idx.tz)
        
        mask = pd.Series(True, index=df.index)
        if start:
            mask = mask & (df.index >= start)
        if end:
            mask = mask & (df.index <= end)
        
        return df[mask]
