"""
sector.py - Sector Rotation Module

Industry momentum ranking and filtering.
"""
from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional
import config


class SectorRotation:
    """
    Sector rotation filter based on industry momentum.
    
    Features:
    - Calculate sector momentum from ETF returns
    - Rank sectors by performance
    - Filter stocks to top N sectors only
    """
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.sector_symbols: Dict[str, Symbol] = {}  # sector name -> Symbol
        self.sector_momentum: Dict[str, float] = {}    # sector name -> momentum score
        self.top_sectors: List[str] = []
    
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
                self.algo.Log(f"[Sector] ERROR adding {etf}: {e}")
        
        self.algo.Log(f"[Sector] Loaded {len(self.sector_symbols)} sector ETFs")
    
    def update_sector_momentum(self):
        """
        Calculate momentum for each sector ETF.
        Runs weekly before rebalance.
        """
        if not config.USE_SECTOR_ROTATION:
            return
        
        self.sector_momentum = {}
        
        for sector, symbol in self.sector_symbols.items():
            try:
                history = self.algo.History(symbol, config.SECTOR_MOMENTUM_PERIOD + 5, Resolution.DAILY)
                if history.empty or len(history) < config.SECTOR_MOMENTUM_PERIOD:
                    continue
                
                history = history.sort_index()
                closes = history['close'].values
                
                if len(closes) >= 2:
                    ret = (closes[-1] / closes[0] - 1) * 100
                    self.sector_momentum[sector] = round(ret, 2)
            except Exception as e:
                self.algo.Log(f"[Sector] ERROR calculating momentum for {sector}: {e}")
        
        # Sort sectors by momentum
        sorted_sectors = sorted(self.sector_momentum.items(), key=lambda x: x[1], reverse=True)
        self.top_sectors = [s[0] for s in sorted_sectors[:config.TOP_N_SECTORS]]
        
        self.algo.Log(f"[Sector] Top {config.TOP_N_SECTORS} sectors: {self.top_sectors}")
        for sector, momentum in sorted_sectors[:config.TOP_N_SECTORS]:
            self.algo.Log(f"  {sector}: {momentum:.2f}%")
    
    def filter_by_sector(self, tickers: List[str], universe_manager) -> List[str]:
        """
        Filter tickers to only those in top sectors.
        
        Args:
            tickers: List of tickers to filter
            universe_manager: UniverseManager instance
            
        Returns:
            Filtered list of tickers
        """
        if not config.USE_SECTOR_ROTATION or not self.top_sectors:
            return tickers
        
        filtered = []
        for ticker in tickers:
            sector = universe_manager.get_sector(ticker)
            if sector in self.top_sectors:
                filtered.append(ticker)
        
        self.algo.Log(f"[Sector] Filtered {len(tickers)} -> {len(filtered)} stocks in top sectors")
        return filtered
    
    def get_sector_momentum(self, sector: str) -> Optional[float]:
        """Get momentum score for a sector."""
        return self.sector_momentum.get(sector)
    
    def get_top_sectors(self) -> List[str]:
        """Get current top sectors."""
        return self.top_sectors.copy()
    
    def is_top_sector(self, sector: str) -> bool:
        """Check if sector is in top N."""
        return sector in self.top_sectors
