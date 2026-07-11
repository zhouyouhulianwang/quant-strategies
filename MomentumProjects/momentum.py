"""
momentum.py - Momentum Engine Module
Multi-period momentum calculation with adaptive scoring.
"""
from AlgorithmImports import *
import config


class MomentumCalculator:
    """Multi-period momentum engine with weighted scoring."""
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.rsi_indicators = {}
        self.ma_indicators = {}
        self.atr_indicators = {}
        self.scores = {}
        self.trend_scores = {}
    
    def initialize_indicators(self, tickers, universe_manager):
        """Initialize RSI, MA, ATR indicators for all symbols."""
        for ticker in tickers:
            symbol = universe_manager.get_symbol(ticker)
            if symbol is None:
                continue
            
            try:
                self.rsi_indicators[symbol] = self.algo.RSI(symbol, config.RSI_PERIOD)
                self.ma_indicators[symbol] = self.algo.SMA(symbol, config.TREND_MA_PERIOD)
                self.atr_indicators[symbol] = self.algo.ATR(symbol, config.RISK_PARITY_ATR_PERIOD)
            except Exception as e:
                self.algo.Log("[Momentum] ERROR initializing indicators for %s: %s" % (ticker, str(e)))
        
        self.algo.Log("[Momentum] Initialized indicators for %d symbols" % len(self.rsi_indicators))
    
    def calculate_momentum_scores(self, tickers, universe_manager):
        """Calculate momentum scores for all tickers."""
        scores = {}
        
        for ticker in tickers:
            symbol = universe_manager.get_symbol(ticker)
            if symbol is None:
                continue
            
            try:
                score = self._calculate_single_score(ticker, symbol)
                if score is not None:
                    scores[ticker] = score
            except Exception as e:
                self.algo.Log("[Momentum] ERROR calculating score for %s: %s" % (ticker, str(e)))
        
        self.scores = scores
        return scores
    
    def _calculate_single_score(self, ticker, symbol):
        """Calculate momentum score for a single ticker."""
        max_period = max(config.MOMENTUM_PERIODS.values()) + 5
        history = self.algo.History(symbol, max_period, Resolution.DAILY)
        
        if history.empty or len(history) < max(config.MOMENTUM_PERIODS.values()):
            return None
        
        history = history.sort_index()
        closes = history["close"].values
        
        if len(closes) < 2:
            return None
        
        current_price = closes[-1]
        
        momentum_scores = {}
        for period_name, period_days in config.MOMENTUM_PERIODS.items():
            if len(closes) > period_days:
                past_price = closes[-period_days - 1] if len(closes) > period_days else closes[0]
                ret = (current_price / past_price - 1) * 100
                weight = config.MOMENTUM_WEIGHTS[period_name]
                momentum_scores[period_name] = ret * weight
        
        if not momentum_scores:
            return None
        
        base_score = sum(momentum_scores.values())
        
        rsi_score = 0
        if symbol in self.rsi_indicators:
            rsi = self.rsi_indicators[symbol].Current.Value
            if rsi > 70:
                rsi_score = -5
            elif rsi < 30:
                rsi_score = +5
        
        trend_score = 0
        if config.USE_TREND_FILTER and symbol in self.ma_indicators:
            ma = self.ma_indicators[symbol].Current.Value
            self.trend_scores[ticker] = current_price > ma
            if current_price > ma:
                trend_score = +3
            else:
                trend_score = -5
        
        final_score = base_score + rsi_score + trend_score
        return round(final_score, 3)
    
    def get_top_tickers(self, tickers, n=None):
        """Get top N tickers by momentum score."""
        if n is None:
            n = config.TOP_N_STOCKS
        
        scored = []
        for t in tickers:
            if t in self.scores:
                scored.append((t, self.scores[t]))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]
    
    def get_rsi(self, ticker, universe_manager):
        """Get current RSI for a ticker."""
        symbol = universe_manager.get_symbol(ticker)
        if symbol and symbol in self.rsi_indicators:
            return self.rsi_indicators[symbol].Current.Value
        return None
    
    def get_atr(self, ticker, universe_manager):
        """Get current ATR for a ticker."""
        symbol = universe_manager.get_symbol(ticker)
        if symbol and symbol in self.atr_indicators:
            return self.atr_indicators[symbol].Current.Value
        return None
    
    def is_above_trend(self, ticker):
        """Check if ticker is above 200MA."""
        return self.trend_scores.get(ticker, False)
    
    def get_score(self, ticker):
        """Get cached score for a ticker."""
        return self.scores.get(ticker)
