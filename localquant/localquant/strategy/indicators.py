"""技术指标库"""
import pandas as pd
import numpy as np
from typing import Optional, Union

def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均线"""
    return series.rolling(window=period).mean()

def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均线"""
    return series.ewm(span=period, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI 相对强弱指标"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta.where(delta < 0, 0))
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD 指标"""
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    
    return pd.DataFrame({
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    })

def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """布林带"""
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    return pd.DataFrame({
        'upper': upper,
        'middle': middle,
        'lower': lower
    })

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR 平均真实波幅"""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def momentum(series: pd.Series, period: int = 10) -> pd.Series:
    """动量指标"""
    return series.pct_change(period)

def roc(series: pd.Series, period: int = 10) -> pd.Series:
    """变动率指标"""
    return (series - series.shift(period)) / series.shift(period) * 100

class IndicatorCalculator:
    """指标计算器 - 方便策略使用"""
    
    def __init__(self, df: pd.DataFrame):
        self.df = df
    
    def add_sma(self, period: int, column: str = 'close', name: Optional[str] = None):
        """添加 SMA 到数据框"""
        col_name = name or f'SMA_{period}'
        self.df[col_name] = sma(self.df[column], period)
        return self
    
    def add_ema(self, period: int, column: str = 'close', name: Optional[str] = None):
        """添加 EMA 到数据框"""
        col_name = name or f'EMA_{period}'
        self.df[col_name] = ema(self.df[column], period)
        return self
    
    def add_rsi(self, period: int = 14, column: str = 'close'):
        """添加 RSI"""
        self.df[f'RSI_{period}'] = rsi(self.df[column], period)
        return self
    
    def add_macd(self, fast: int = 12, slow: int = 26, signal: int = 9, column: str = 'close'):
        """添加 MACD"""
        macd_data = macd(self.df[column], fast, slow, signal)
        self.df['MACD'] = macd_data['macd']
        self.df['MACD_Signal'] = macd_data['signal']
        self.df['MACD_Hist'] = macd_data['histogram']
        return self
    
    def add_bollinger(self, period: int = 20, std_dev: float = 2.0, column: str = 'close'):
        """添加布林带"""
        bb = bollinger_bands(self.df[column], period, std_dev)
        self.df['BB_Upper'] = bb['upper']
        self.df['BB_Middle'] = bb['middle']
        self.df['BB_Lower'] = bb['lower']
        return self
    
    def get_data(self) -> pd.DataFrame:
        """获取添加了指标的数据"""
        return self.df
