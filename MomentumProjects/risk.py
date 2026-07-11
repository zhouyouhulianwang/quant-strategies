"""
risk.py - Risk Manager Module
Comprehensive risk management with VIX, stops, drawdown, and trend filters.
"""
from AlgorithmImports import *
import config


class RiskController:
    """Multi-layer risk management system."""
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.vix_symbol = None
        self.market_symbol = None
        self.market_ma = None
        
        self.position_highs = {}
        self.position_entry = {}
        self.partial_sold = {}
        
        self.high_water_mark = 0
        self.drawdown_triggered = False
        self.drawdown_pause_days = 0
    
    def initialize(self):
        """Initialize risk indicators."""
        try:
            self.vix_symbol = self.algo.AddIndex('VIX', Resolution.DAILY).Symbol
            self.algo.Log("[Risk] VIX index loaded")
        except:
            self.vix_symbol = self.algo.AddEquity('VIXY', Resolution.DAILY).Symbol
            self.algo.Log("[Risk] VIXY fallback loaded")
        
        if config.USE_MARKET_TREND_FILTER:
            self.market_symbol = self.algo.AddEquity(config.MARKET_TREND_SYMBOL, Resolution.DAILY).Symbol
            self.market_ma = self.algo.SMA(self.market_symbol, config.MARKET_TREND_MA)
            self.algo.Log("[Risk] Market trend filter: %s %dMA" % (config.MARKET_TREND_SYMBOL, config.MARKET_TREND_MA))
    
    def get_vix_position_limit(self):
        """Get position limit based on VIX level."""
        if self.vix_symbol is None:
            return 1.0
        
        try:
            vix = self.algo.Securities[self.vix_symbol].Price
            if vix <= 0:
                return 1.0
            
            for level, (low, high) in config.VIX_LEVELS.items():
                if low <= vix < high:
                    return config.VIX_POSITION_PCT[level]
            
            return config.VIX_POSITION_PCT['panic']
        except:
            return 1.0
    
    def check_market_trend(self):
        """Check if market is above trend MA."""
        if not config.USE_MARKET_TREND_FILTER or self.market_symbol is None:
            return True
        
        try:
            price = self.algo.Securities[self.market_symbol].Price
            ma = self.market_ma.Current.Value if self.market_ma and self.market_ma.IsReady else 0
            return price > ma if ma > 0 else True
        except:
            return True
    
    def check_drawdown(self):
        """Check if drawdown exceeds limit."""
        current_equity = self.algo.Portfolio.TotalPortfolioValue
        
        if current_equity > self.high_water_mark:
            self.high_water_mark = current_equity
            self.drawdown_triggered = False
        
        if self.high_water_mark > 0:
            drawdown = (self.high_water_mark - current_equity) / self.high_water_mark
            
            if drawdown > config.MAX_DRAWDOWN_PCT:
                if not self.drawdown_triggered:
                    self.drawdown_triggered = True
                    self.algo.Log("[Risk] DRAWDOWN PROTECTION: %.2f%% > %.2f%%" % (drawdown * 100, config.MAX_DRAWDOWN_PCT * 100))
                return True
        else:
            self.high_water_mark = current_equity
        
        return False
    
    def check_stop_loss(self, ticker, symbol, universe_manager):
        """Check if position should be stopped out."""
        if not self.algo.Portfolio[symbol].Invested:
            return None
        
        current_price = self.algo.Securities[symbol].Close
        entry_price = self.position_entry.get(ticker)
        
        if entry_price is None or entry_price <= 0:
            return None
        
        pnl = (current_price - entry_price) / entry_price
        
        if ticker not in self.position_highs or current_price > self.position_highs[ticker]:
            self.position_highs[ticker] = current_price
        
        if pnl <= -config.STOP_LOSS_PCT:
            self._clear_position_tracking(ticker)
            return 'stop_loss'
        
        if pnl >= config.TAKE_PROFIT_PCT and not self.partial_sold.get(ticker, False):
            self.partial_sold[ticker] = True
            return 'take_profit_partial'
        
        if config.USE_TRAILING_STOP and ticker in self.position_highs:
            high = self.position_highs[ticker]
            if current_price < high * (1 - config.TRAILING_STOP_PCT):
                self._clear_position_tracking(ticker)
                return 'trailing_stop'
        
        return None
    
    def record_entry(self, ticker, price):
        """Record position entry for risk tracking."""
        self.position_entry[ticker] = price
        self.position_highs[ticker] = price
        self.partial_sold[ticker] = False
    
    def record_exit(self, ticker):
        """Clear position tracking."""
        self._clear_position_tracking(ticker)
    
    def _clear_position_tracking(self, ticker):
        """Clear all tracking for a ticker."""
        self.position_entry.pop(ticker, None)
        self.position_highs.pop(ticker, None)
        self.partial_sold.pop(ticker, None)
    
    def get_risk_summary(self):
        """Get summary of current risk status."""
        lines = ["\n=== RISK SUMMARY ==="]
        
        vix_limit = self.get_vix_position_limit()
        vix_price = 0
        if self.vix_symbol:
            try:
                vix_price = self.algo.Securities[self.vix_symbol].Price
            except:
                pass
        lines.append("VIX: %.1f -> Position limit: %.0f%%" % (vix_price, vix_limit * 100))
        
        if config.USE_MARKET_TREND_FILTER:
            trend_ok = self.check_market_trend()
            lines.append("Market trend: %s %dMA" % ('ABOVE' if trend_ok else 'BELOW', config.MARKET_TREND_MA))
        
        if self.high_water_mark > 0:
            current = self.algo.Portfolio.TotalPortfolioValue
            dd = (self.high_water_mark - current) / self.high_water_mark
            lines.append("Drawdown: %.2f%% (HWM: %d)" % (dd * 100, int(self.high_water_mark)))
        
        lines.append("Tracked positions: %d" % len(self.position_entry))
        
        return "\n".join(lines)
    
    def get_current_exposure_multiplier(self):
        """Get combined exposure multiplier from all risk filters."""
        vix_mult = self.get_vix_position_limit()
        trend_mult = 1.0 if self.check_market_trend() else 0.5
        dd_mult = 0.0 if self.check_drawdown() else 1.0
        
        combined = min(vix_mult, trend_mult, dd_mult)
        return combined
