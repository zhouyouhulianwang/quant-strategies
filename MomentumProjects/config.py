"""
config.py - Momentum Strategy Configuration
All strategy parameters centralized here.
"""

# ============ BASIC SETTINGS ============
START_DATE = (2020, 1, 1)
END_DATE = (2026, 6, 30)
INITIAL_CASH = 100000

# ============ UNIVERSE SETTINGS ============
MIN_PRICE = 10.0
MIN_AVG_VOLUME = 10000000
UNIVERSE_SIZE = 500

# ============ MOMENTUM ENGINE ============
MOMENTUM_PERIODS = {
    '1m': 21,
    '3m': 63,
    '6m': 126,
    '12m': 252,
}
MOMENTUM_WEIGHTS = {
    '1m': 0.10,
    '3m': 0.30,
    '6m': 0.30,
    '12m': 0.30,
}

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

USE_TREND_FILTER = True
TREND_MA_PERIOD = 200

# ============ SECTOR ROTATION ============
USE_SECTOR_ROTATION = True
SECTOR_ETFS = {
    'Technology': 'XLK',
    'Healthcare': 'XLV',
    'Financial': 'XLF',
    'Energy': 'XLE',
    'Industrial': 'XLI',
    'Consumer': 'XLY',
    'Consumer_Defensive': 'XLP',
    'Communication': 'XLC',
    'Utilities': 'XLU',
    'RealEstate': 'XLRE',
}
SECTOR_MOMENTUM_PERIOD = 63
TOP_N_SECTORS = 5

# ============ PORTFOLIO CONSTRUCTION ============
TOP_N_STOCKS = 20
POSITION_WEIGHT_METHOD = 'equal'
RISK_PARITY_ATR_PERIOD = 20
MAX_SECTOR_PCT = 0.30

# ============ RISK MANAGER ============
VIX_LEVELS = {
    'normal': (0, 20),
    'elevated': (20, 25),
    'high': (25, 30),
    'extreme': (30, 35),
    'panic': (35, 100),
}
VIX_POSITION_PCT = {
    'normal': 1.0,
    'elevated': 0.8,
    'high': 0.6,
    'extreme': 0.4,
    'panic': 0.2,
}

STOP_LOSS_PCT = 0.08
TAKE_PROFIT_PCT = 0.20
TAKE_PROFIT_PARTIAL = 0.5
USE_TRAILING_STOP = True
TRAILING_STOP_PCT = 0.10

USE_MARKET_TREND_FILTER = True
MARKET_TREND_SYMBOL = 'SPY'
MARKET_TREND_MA = 200

MAX_DRAWDOWN_PCT = 0.15

# ============ EXECUTION ============
REBALANCE_FREQUENCY = 'weekly'
REBALANCE_DAY = 0
REBALANCE_MINUTES_AFTER_OPEN = 35

MAX_POSITION_PCT = 0.05
MIN_POSITION_PCT = 0.0
CASH_BUFFER_PCT = 0.05

# ============ MONITOR ============
MONITOR_TIME_MINUTES_AFTER_OPEN = 30

# ============ SECTOR MAP ============
SECTOR_MAP = {
    'AAPL': 'Technology', 'MSFT': 'Technology', 'GOOGL': 'Technology',
    'AMZN': 'Technology', 'META': 'Technology', 'NVDA': 'Technology',
    'TSLA': 'Consumer', 'JPM': 'Financial', 'V': 'Financial',
    'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'XOM': 'Energy',
    'CVX': 'Energy', 'PG': 'Consumer_Defensive', 'KO': 'Consumer_Defensive',
    'HD': 'Consumer', 'WMT': 'Consumer_Defensive', 'BAC': 'Financial',
    'MA': 'Financial', 'PFE': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PEP': 'Consumer_Defensive', 'COST': 'Consumer',
    'TMO': 'Healthcare', 'AVGO': 'Technology', 'DIS': 'Communication',
    'ADBE': 'Technology', 'CRM': 'Technology', 'ACN': 'Technology',
    'VZ': 'Communication', 'NFLX': 'Communication', 'CMCSA': 'Communication',
    'INTC': 'Technology', 'AMD': 'Technology', 'PYPL': 'Financial',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'ABT': 'Healthcare',
    'C': 'Financial', 'GS': 'Financial', 'WFC': 'Financial',
    'MS': 'Financial', 'BA': 'Industrial', 'GE': 'Industrial',
    'HON': 'Industrial', 'RTX': 'Industrial', 'UPS': 'Industrial',
    'CAT': 'Industrial', 'LMT': 'Industrial', 'DE': 'Industrial',
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities',
    'D': 'Utilities', 'AEP': 'Utilities', 'EXC': 'Utilities',
    'OXY': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'MPC': 'Energy', 'VLO': 'Energy',
    'PSX': 'Energy', 'KMI': 'Energy', 'WMB': 'Energy',
    'PLD': 'RealEstate', 'AMT': 'RealEstate', 'CCI': 'RealEstate',
    'EQIX': 'RealEstate', 'O': 'RealEstate', 'SPG': 'RealEstate',
}
