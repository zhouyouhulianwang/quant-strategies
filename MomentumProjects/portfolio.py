"""
portfolio.py - Portfolio Construction Module
Position sizing and sector limits.
"""
from AlgorithmImports import *
import config


class PositionBuilder:
    """Portfolio construction with position sizing and sector limits."""
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.target_positions = {}
        self.current_positions = {}
    
    def calculate_weights(self, selected_tickers, universe_manager, sector_filter):
        """Calculate target weights for selected tickers."""
        if not selected_tickers:
            return {}
        
        n = len(selected_tickers)
        
        if config.POSITION_WEIGHT_METHOD == 'equal':
            weights = self._equal_weights(selected_tickers)
        elif config.POSITION_WEIGHT_METHOD == 'risk_parity':
            weights = self._risk_parity_weights(selected_tickers, universe_manager)
        else:
            weights = self._equal_weights(selected_tickers)
        
        weights = self._apply_sector_limits(weights, universe_manager, sector_filter)
        
        total_weight = sum(weights.values())
        if total_weight > 0:
            scale = (1.0 - config.CASH_BUFFER_PCT) / total_weight
            weights = {t: w * scale for t, w in weights.items()}
        
        self.target_positions = weights
        return weights
    
    def _equal_weights(self, selected_tickers):
        """Equal weight allocation."""
        n = len(selected_tickers)
        weight = 1.0 / n if n > 0 else 0
        return {ticker: weight for ticker, _ in selected_tickers}
    
    def _risk_parity_weights(self, selected_tickers, universe_manager):
        """Risk parity allocation based on ATR."""
        inv_atrs = {}
        for ticker, _ in selected_tickers:
            symbol = universe_manager.get_symbol(ticker)
            if symbol is None:
                continue
            
            try:
                history = self.algo.History(symbol, config.RISK_PARITY_ATR_PERIOD + 5, Resolution.DAILY)
                if not history.empty and len(history) >= 5:
                    highs = history['high'].values
                    lows = history['low'].values
                    closes = history['close'].values
                    
                    trs = []
                    for i in range(1, len(closes)):
                        tr = max(highs[i] - lows[i], 
                                abs(highs[i] - closes[i-1]),
                                abs(lows[i] - closes[i-1]))
                        trs.append(tr)
                    
                    if trs:
                        atr = sum(trs) / len(trs)
                        if atr > 0:
                            inv_atrs[ticker] = 1.0 / atr
            except:
                pass
        
        if not inv_atrs:
            return self._equal_weights(selected_tickers)
        
        total_inv = sum(inv_atrs.values())
        weights = {ticker: inv_atrs.get(ticker, 0) / total_inv for ticker, _ in selected_tickers}
        
        return weights
    
    def _apply_sector_limits(self, weights, universe_manager, sector_filter):
        """Apply sector concentration limits."""
        sector_weights = {}
        for ticker, weight in weights.items():
            sector = universe_manager.get_sector(ticker)
            if sector not in sector_weights:
                sector_weights[sector] = []
            sector_weights[sector].append((ticker, weight))
        
        adjusted_weights = {}
        for sector, tickers_weights in sector_weights.items():
            sector_total = sum(w for _, w in tickers_weights)
            
            if sector_total > config.MAX_SECTOR_PCT:
                scale = config.MAX_SECTOR_PCT / sector_total
                for ticker, weight in tickers_weights:
                    adjusted_weights[ticker] = weight * scale
            else:
                for ticker, weight in tickers_weights:
                    adjusted_weights[ticker] = weight
        
        return adjusted_weights
    
    def get_target_weight(self, ticker):
        """Get target weight for a ticker."""
        return self.target_positions.get(ticker, 0.0)
    
    def get_total_target_exposure(self):
        """Get total target exposure."""
        return sum(self.target_positions.values())
    
    def get_sector_exposure(self, sector, universe_manager):
        """Get total exposure for a sector."""
        total = 0.0
        for ticker, weight in self.target_positions.items():
            if universe_manager.get_sector(ticker) == sector:
                total += weight
        return total
