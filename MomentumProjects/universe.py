"""
universe.py - Universe Manager Module
Manages stock universe selection, filtering, and sector classification.
"""
from AlgorithmImports import *
import config


class StockUniverse:
    """Manages the stock universe with liquidity and quality filters."""
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.symbols = {}
        self.sectors = {}
        self.liquid_tickers = set()
        self.universe_initialized = False
    
    def initialize(self, tickers=None):
        """Initialize universe with stock list."""
        if tickers is None:
            tickers = list(config.SECTOR_MAP.keys())
        
        self.algo.Log("[Universe] Initializing with %d tickers" % len(tickers))
        
        for ticker in tickers:
            try:
                symbol = self.algo.AddEquity(ticker, Resolution.DAILY).Symbol
                self.symbols[ticker] = symbol
                self.sectors[ticker] = config.SECTOR_MAP.get(ticker, 'Unknown')
            except Exception as e:
                self.algo.Log("[Universe] ERROR adding %s: %s" % (ticker, str(e)))
        
        self.algo.Log("[Universe] Loaded %d symbols" % len(self.symbols))
        self.universe_initialized = True
        
        self.algo.Schedule.On(
            self.algo.DateRules.EveryDay(),
            self.algo.TimeRules.AfterMarketOpen('SPY', 5),
            self.update_liquidity_filter
        )
    
    def update_liquidity_filter(self):
        """Update liquid stocks based on volume and price."""
        self.liquid_tickers = set()
        min_volume = config.MIN_AVG_VOLUME
        
        for ticker, symbol in self.symbols.items():
            try:
                security = self.algo.Securities[symbol]
                if security.Price < config.MIN_PRICE:
                    continue
                
                history = self.algo.History(symbol, 20, Resolution.DAILY)
                if not history.empty and len(history) >= 10:
                    avg_vol = history['volume'].mean()
                    if avg_vol >= min_volume:
                        self.liquid_tickers.add(ticker)
            except:
                pass
        
        self.algo.Log("[Universe] Liquid stocks: %d/%d" % (len(self.liquid_tickers), len(self.symbols)))
    
    def get_liquid_universe(self):
        """Get list of tickers passing liquidity filter."""
        return list(self.liquid_tickers)
    
    def get_sector(self, ticker):
        """Get sector for a ticker."""
        return self.sectors.get(ticker, 'Unknown')
    
    def get_symbols_by_sector(self, sector):
        """Get all tickers in a sector."""
        result = []
        for t, s in self.sectors.items():
            if s == sector and t in self.liquid_tickers:
                result.append(t)
        return result
    
    def get_all_sectors(self):
        """Get list of all sectors in universe."""
        return list(set(self.sectors.values()))
    
    def is_liquid(self, ticker):
        """Check if ticker passes liquidity filter."""
        return ticker in self.liquid_tickers
    
    def get_symbol(self, ticker):
        """Get Symbol object for ticker."""
        return self.symbols.get(ticker)
    
    def get_ticker(self, symbol):
        """Get ticker string from Symbol object."""
        for ticker, sym in self.symbols.items():
            if sym == symbol:
                return ticker
        return None
    
    def get_universe_size(self):
        """Get current universe size."""
        return len(self.liquid_tickers)
