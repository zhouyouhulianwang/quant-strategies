"""
config.py - Momentum Strategy Configuration

All strategy parameters centralized here.
"""

# ============ BASIC SETTINGS ============
START_DATE = (2020, 1, 1)
END_DATE = (2026, 6, 30)
INITIAL_CASH = 100000

# ============ UNIVERSE SETTINGS ============
MIN_PRICE = 10.0           # Minimum stock price
MIN_MARKET_CAP_BILLIONS = 2.0  # Minimum market cap in billions
MIN_AVG_VOLUME = 10_000_000   # Minimum average daily volume
UNIVERSE_SIZE = 500        # Target universe size (top by volume)

# ============ MOMENTUM ENGINE ============
MOMENTUM_PERIODS = {
    '1m': 21,      # 1 month
    '3m': 63,      # 3 months
    '6m': 126,     # 6 months
    '12m': 252,    # 12 months
}
MOMENTUM_WEIGHTS = {
    '1m': 0.10,
    '3m': 0.30,
    '6m': 0.30,
    '12m': 0.30,
}

# RSI Settings
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Trend Filter
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
SECTOR_MOMENTUM_PERIOD = 63  # 3 months for sector ranking
TOP_N_SECTORS = 5

# ============ PORTFOLIO CONSTRUCTION ============
TOP_N_STOCKS = 20          # Number of stocks to hold
POSITION_WEIGHT_METHOD = 'equal'  # 'equal' or 'risk_parity'

# Risk Parity Settings (if enabled)
RISK_PARITY_ATR_PERIOD = 20

# Sector Limits
MAX_SECTOR_PCT = 0.30      # Max 30% in one sector

# ============ RISK MANAGER ============
# VIX Control (Progressive)
VIX_LEVELS = {
    'normal': (0, 20),      # 100% position
    'elevated': (20, 25),   # 80% position
    'high': (25, 30),       # 60% position
    'extreme': (30, 35),    # 40% position
    'panic': (35, 100),     # 20% position
}
VIX_POSITION_PCT = {
    'normal': 1.0,
    'elevated': 0.8,
    'high': 0.6,
    'extreme': 0.4,
    'panic': 0.2,
}

# Stop Loss
STOP_LOSS_PCT = 0.08       # 8% stop loss

# Take Profit
TAKE_PROFIT_PCT = 0.20     # 20% take profit
TAKE_PROFIT_PARTIAL = 0.5  # Sell 50% at take profit

# Trailing Stop
USE_TRAILING_STOP = True
TRAILING_STOP_PCT = 0.10   # 10% trailing stop from peak

# Market Trend Filter
USE_MARKET_TREND_FILTER = True
MARKET_TREND_SYMBOL = 'SPY'
MARKET_TREND_MA = 200

# Maximum Drawdown
MAX_DRAWDOWN_PCT = 0.15    # 15% max drawdown

# ============ EXECUTION ============
REBALANCE_FREQUENCY = 'weekly'  # 'weekly' or 'monthly'
REBALANCE_DAY = 0  # 0 = Monday, 1 = Tuesday, etc.
REBALANCE_MINUTES_AFTER_OPEN = 35  # 9:35 AM

# Position Limits
MAX_POSITION_PCT = 0.05    # Max 5% per stock (for 20 stocks = 100%)
MIN_POSITION_PCT = 0.0

# Cash Buffer
CASH_BUFFER_PCT = 0.05     # Keep 5% cash

# ============ MONITOR ============
MONITOR_TIME_MINUTES_AFTER_OPEN = 30  # 9:30 AM
LOG_LEVEL = 'INFO'

# ============ SECTOR MAP (US Large Cap) ============
# Simplified sector mapping - will be loaded from strategy_config.py if available
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
