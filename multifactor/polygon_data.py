"""
实时数据源模块 - Polygon.io 替代 Yahoo Finance
提供更快速、更可靠的市场数据
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List

logger = logging.getLogger('polygon_data')

# Polygon API Key
POLYGON_API_KEY = os.getenv('POLYGON_API_KEY')


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
    
    def get_daily_bars(self, symbol, start_date, end_date):
        """
        获取日线数据
        
        参数:
            symbol: str
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'
        
        返回:
            DataFrame: 日线数据
        """
        if not self.available:
            return None
        
        try:
            # 使用 REST API
            import requests
            
            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}"
            params = {'apiKey': self.api_key}
            
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if data.get('results'):
                import pandas as pd
                
                df = pd.DataFrame(data['results'])
                df['t'] = pd.to_datetime(df['t'], unit='ms')
                df.set_index('t', inplace=True)
                df.rename(columns={
                    'o': 'Open',
                    'h': 'High',
                    'l': 'Low',
                    'c': 'Close',
                    'v': 'Volume'
                }, inplace=True)
                
                return df
            
        except Exception as e:
            logger.error(f"Polygon 获取 {symbol} 数据失败: {e}")
        
        return None
    
    def get_last_trade(self, symbol):
        """
        获取最新成交价
        
        参数:
            symbol: str
        
        返回:
            float: 最新价格
        """
        if not self.available:
            return None
        
        try:
            import requests
            
            url = f"https://api.polygon.io/v2/last/trade/{symbol}"
            params = {'apiKey': self.api_key}
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('results'):
                return float(data['results']['p'])
            
        except Exception as e:
            logger.error(f"Polygon 获取 {symbol} 最新价失败: {e}")
        
        return None
    
    def get_vix(self):
        """
        获取 VIX 数据
        
        注意: Polygon 的 VIX 代码可能是 I:VIX
        """
        if not self.available:
            return None
        
        try:
            # VIX 在 Polygon 的代码
            return self.get_last_trade('I:VIX')
        except Exception as e:
            logger.error(f"Polygon 获取 VIX 失败: {e}")
        
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
        获取价格数据
        
        参数:
            symbols: list, 股票代码列表
            start_date: str
            end_date: str
            prefer_realtime: bool, 优先使用实时数据源
        
        返回:
            DataFrame: 价格数据
        """
        import pandas as pd
        
        price_df = pd.DataFrame()
        
        for symbol in symbols:
            # 尝试 Polygon
            if prefer_realtime and self.polygon.available:
                data = self.polygon.get_daily_bars(symbol, start_date, end_date)
                if data is not None:
                    price_df[symbol] = data['Close']
                    logger.info(f"[Polygon] {symbol}: {len(data)} 条")
                    continue
            
            # 回退 Yahoo Finance
            if self._yahoo_available:
                try:
                    import yfinance as yf
                    data = yf.Ticker(symbol).history(start=start_date, end=end_date)
                    price_df[symbol] = data['Close']
                    logger.info(f"[Yahoo] {symbol}: {len(data)} 条")
                except Exception as e:
                    logger.error(f"获取 {symbol} 失败: {e}")
        
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
# 使用示例
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
    
    prices = source.get_prices(['AAPL', 'MSFT'], start, end)
    print(f"\n历史数据:\n{prices.tail()}")
    
    # 获取 VIX
    vix = source.get_vix()
    print(f"\nVIX: {vix}")
