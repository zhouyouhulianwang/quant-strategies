"""
universe.py - Universe Manager Module

Manages stock universe selection, filtering, and sector classification.
"""
from AlgorithmImports import *
from typing import Dict, List, Set, Optional
import config


class UniverseManager:
    """
    Manages the stock universe with liquidity and quality filters.
    
    Features:
    - Price filter (min $10)
    - Volume filter (min avg daily volume)
    - Market cap filter (if available)
    - Sector classification
    - Liquidity ranking
    """
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.symbols: Dict[str, Symbol] = {}  # ticker -> Symbol
        self.sectors: Dict[str, str] = {}     # ticker -> sector name
        self.liquid_tickers: Set[str] = set()  # passing liquidity filter
        self.universe_initialized = False
    
    def initialize(self, tickers: List[str] = None):
        """
        Initialize universe with stock list.
        
        Args:
            tickers: Optional list of tickers. If None, uses SECTOR_MAP keys.
        """
        if tickers is None:
            tickers = list(config.SECTOR_MAP.keys())
        
        self.algo.Log(f"[Universe] Initializing with {len(tickers)} tickers")
        
        # Add all equities
        for ticker in tickers:
            try:
                symbol = self.algo.AddEquity(ticker, Resolution.DAILY).Symbol
                self.symbols[ticker] = symbol
                self.sectors[ticker] = config.SECTOR_MAP.get(ticker, 'Unknown')
            except Exception as e:
                self.algo.Log(f"[Universe] ERROR adding {ticker}: {e}")
        
        self.algo.Log(f"[Universe] Loaded {len(self.symbols)} symbols")
        self.universe_initialized = True
        
        # Initial liquidity filter after warmup
        self.algo.Schedule.On(
            self.algo.DateRules.EveryDay(),
            self.algo.TimeRules.AfterMarketOpen('SPY', 5),
            self.update_liquidity_filter
        )
    
    def update_liquidity_filter(self):
        """
        Update liquid stocks based on volume and price criteria.
        Runs daily after market open.
        """
        self.liquid_tickers = set()
        min_volume = config.MIN_AVG_VOLUME
        
        for ticker, symbol in self.symbols.items():
            try:
                security = self.algo.Securities[symbol]
                
                # Price filter
                if security.Price < config.MIN_PRICE:
                    continue
                
                # Volume filter (20-day average)
                history = self.algo.History(symbol, 20, Resolution.DAILY)
                if not history.empty and len(history) >= 10:
                    avg_volume = history['volume'].mean()
                    if avg_volume >= min_volume:
                        self.liquid_tickers.add(ticker)
            except:
                pass
        
        self.algo.Log(f"[Universe] Liquid stocks: {len(self.liquid_tickers)}/{len(self.symbols)}")
    
    def get_liquid_universe(self) -> List[str]:
        """Get list of tickers passing liquidity filter."""
        return list(self.liquid_tickers)
    
    def get_sector(self, ticker: str) -> str:
        """Get sector for a ticker."""
        return self.sectors.get(ticker, 'Unknown')
    
    def get_symbols_by_sector(self, sector: str) -> List[str]:
        """Get all tickers in a sector."""
        return [t for t, s in self.sectors.items() if s == sector and t in self.liquid_tickers]
    
    def get_all_sectors(self) -> List[str]:
        """Get list of all sectors in universe."""
        return list(set(self.sectors.values()))
    
    def is_liquid(self, ticker: str) -> bool:
        """Check if ticker passes liquidity filter."""
        return ticker in self.liquid_tickers
    
    def get_symbol(self, ticker: str) -> Optional[Symbol]:
        """Get Symbol object for ticker."""
        return self.symbols.get(ticker)
    
    def get_ticker(self, symbol: Symbol) -> Optional[str]:
        """Get ticker string from Symbol object."""
        for ticker, sym in self.symbols.items():
            if sym == symbol:
                return ticker
        return None
    
    def get_universe_size(self) -> int:
        """Get current universe size."""
        return len(self.liquid_tickers)
