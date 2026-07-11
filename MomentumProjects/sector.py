"""
sector.py - Sector Rotation Module
Industry momentum ranking and filtering.
"""
from AlgorithmImports import *
import config


class SectorFilter:
    """Sector rotation filter based on industry momentum."""
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.sector_symbols = {}
        self.sector_momentum = {}
        self.top_sectors = []
    
    def initialize(self):
        """Initialize sector ETF symbols."""
        if not config.USE_SECTOR_ROTATION:
            self.algo.Log("[Sector] Sector rotation disabled")
            return
        
        for sector, etf in config.SECTOR_ETFS.items():
            try:
                symbol = self.algo.AddEquity(etf, Resolution.DAILY).Symbol
                self.sector_symbols[sector] = symbol
            except Exception as e:
                self.algo.Log("[Sector] ERROR adding %s: %s" % (etf, str(e)))
        
        self.algo.Log("[Sector] Loaded %d sector ETFs" % len(self.sector_symbols))
    
    def update_sector_momentum(self):
        """Calculate momentum for each sector ETF."""
        if not config.USE_SECTOR_ROTATION:
            return
        
        self.sector_momentum = {}
        
        for sector, symbol in self.sector_symbols.items():
            try:
                history = self.algo.History(symbol, config.SECTOR_MOMENTUM_PERIOD + 5, Resolution.DAILY)
                if history.empty or len(history) < config.SECTOR_MOMENTUM_PERIOD:
                    continue
                
                history = history.sort_index()
                closes = history["close"].values
                
                if len(closes) >= 2:
                    ret = (closes[-1] / closes[0] - 1) * 100
                    self.sector_momentum[sector] = round(ret, 2)
            except Exception as e:
                self.algo.Log("[Sector] ERROR calculating momentum for %s: %s" % (sector, str(e)))
        
        sorted_sectors = sorted(self.sector_momentum.items(), key=lambda x: x[1], reverse=True)
        self.top_sectors = [s[0] for s in sorted_sectors[:config.TOP_N_SECTORS]]
        
        self.algo.Log("[Sector] Top %d sectors: %s" % (config.TOP_N_SECTORS, str(self.top_sectors)))
        for sector, momentum in sorted_sectors[:config.TOP_N_SECTORS]:
            self.algo.Log("  %s: %.2f%%" % (sector, momentum))
    
    def filter_by_sector(self, tickers, universe_manager):
        """Filter tickers to only those in top sectors."""
        if not config.USE_SECTOR_ROTATION or not self.top_sectors:
            return tickers
        
        filtered = []
        for ticker in tickers:
            sector = universe_manager.get_sector(ticker)
            if sector in self.top_sectors:
                filtered.append(ticker)
        
        self.algo.Log("[Sector] Filtered %d -> %d stocks in top sectors" % (len(tickers), len(filtered)))
        return filtered
    
    def get_sector_momentum(self, sector):
        """Get momentum score for a sector."""
        return self.sector_momentum.get(sector)
    
    def get_top_sectors(self):
        """Get current top sectors."""
        return list(self.top_sectors)
    
    def is_top_sector(self, sector):
        """Check if sector is in top N."""
        return sector in self.top_sectors
