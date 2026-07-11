"""
momentum.py - Momentum Engine Module

Multi-period momentum calculation with adaptive scoring.
"""
from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional
import config


class MomentumEngine:
    """
    Multi-period momentum engine with weighted scoring.
    
    Features:
    - Multiple lookback periods (1m, 3m, 6m, 12m)
    - Weighted composite score
    - RSI trend confirmation
    - ATR for volatility sizing
    - Trend filter (200MA)
    """
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.rsi_indicators: Dict[Symbol, object] = {}
        self.ma_indicators: Dict[Symbol, object] = {}
        self.atr_indicators: Dict[Symbol, object] = {}
        self.scores: Dict[str, float] = {}  # ticker -> momentum score
        self.trend_scores: Dict[str, bool] = {}  # ticker -> above MA200
    
    def initialize_indicators(self, tickers: List[str], universe_manager):
        """
        Initialize RSI, MA, ATR indicators for all symbols.
        
        Args:
            tickers: List of tickers to initialize
            universe_manager: UniverseManager instance for symbol lookup
        """
        for ticker in tickers:
            symbol = universe_manager.get_symbol(ticker)
            if symbol is None:
                continue
            
            try:
                self.rsi_indicators[symbol] = self.algo.RSI(symbol, config.RSI_PERIOD)
                self.ma_indicators[symbol] = self.algo.SMA(symbol, config.TREND_MA_PERIOD)
                self.atr_indicators[symbol] = self.algo.ATR(symbol, config.RISK_PARITY_ATR_PERIOD)
            except Exception as e:
                self.algo.Log(f"[Momentum] ERROR initializing indicators for {ticker}: {e}")
        
        self.algo.Log(f"[Momentum] Initialized indicators for {len(self.rsi_indicators)} symbols")
    
    def calculate_momentum_scores(self, tickers: List[str], universe_manager) -> Dict[str, float]:
        """
        Calculate momentum scores for all tickers.
        
        Returns:
            Dict[ticker, score] - higher is better
        """
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
                self.algo.Log(f"[Momentum] ERROR calculating score for {ticker}: {e}")
        
        self.scores = scores
        return scores
    
    def _calculate_single_score(self, ticker: str, symbol: Symbol) -> Optional[float]:
        """
        Calculate momentum score for a single ticker.
        
        Score formula:
        weighted sum of period returns + RSI adjustment + trend bonus
        """
        # Get history
        max_period = max(config.MOMENTUM_PERIODS.values()) + 5
        history = self.algo.History(symbol, max_period, Resolution.DAILY)
        
        if history.empty or len(history) < max(config.MOMENTUM_PERIODS.values()):
            return None
        
        history = history.sort_index()
        closes = history['close'].values
        
        if len(closes) < 2:
            return None
        
        current_price = closes[-1]
        
        # Calculate period returns
        momentum_scores = {}
        for period_name, period_days in config.MOMENTUM_PERIODS.items():
            if len(closes) > period_days:
                past_price = closes[-period_days - 1] if len(closes) > period_days else closes[0]
                ret = (current_price / past_price - 1) * 100
                weight = config.MOMENTUM_WEIGHTS[period_name]
                momentum_scores[period_name] = ret * weight
        
        if not momentum_scores:
            return None
        
        # Base momentum score
        base_score = sum(momentum_scores.values())
        
        # RSI adjustment (penalize extreme overbought)
        rsi_score = 0
        if symbol in self.rsi_indicators:
            rsi = self.rsi_indicators[symbol].Current.Value
            if rsi > 70:
                rsi_score = -5  # Penalize overbought
            elif rsi < 30:
                rsi_score = +5  # Bonus for oversold (mean reversion potential)
        
        # Trend filter bonus
        trend_score = 0
        if config.USE_TREND_FILTER and symbol in self.ma_indicators:
            ma = self.ma_indicators[symbol].Current.Value
            self.trend_scores[ticker] = current_price > ma
            if current_price > ma:
                trend_score = +3  # Bonus for above trend
            else:
                trend_score = -5  # Penalty for below trend
        
        # Final score
        final_score = base_score + rsi_score + trend_score
        
        return round(final_score, 3)
    
    def get_top_tickers(self, tickers: List[str], n: int = config.TOP_N_STOCKS) -> List[Tuple[str, float]]:
        """
        Get top N tickers by momentum score.
        
        Returns:
            List of (ticker, score) tuples, sorted by score descending
        """
        # Filter tickers with scores
        scored = [(t, self.scores.get(t, -999)) for t in tickers if t in self.scores]
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return scored[:n]
    
    def get_rsi(self, ticker: str, universe_manager) -> Optional[float]:
        """Get current RSI for a ticker."""
        symbol = universe_manager.get_symbol(ticker)
        if symbol and symbol in self.rsi_indicators:
            return self.rsi_indicators[symbol].Current.Value
        return None
    
    def get_atr(self, ticker: str, universe_manager) -> Optional[float]:
        """Get current ATR for a ticker."""
        symbol = universe_manager.get_symbol(ticker)
        if symbol and symbol in self.atr_indicators:
            return self.atr_indicators[symbol].Current.Value
        return None
    
    def is_above_trend(self, ticker: str) -> bool:
        """Check if ticker is above 200MA."""
        return self.trend_scores.get(ticker, False)
    
    def get_score(self, ticker: str) -> Optional[float]:
        """Get cached score for a ticker."""
        return self.scores.get(ticker)
