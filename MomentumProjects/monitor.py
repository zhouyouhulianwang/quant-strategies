"""
monitor.py - Daily Monitor Module
Daily monitoring of positions, risk, and logging.
"""
from AlgorithmImports import *
import config


class DailyMonitor:
    """Daily monitoring and logging system."""
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.daily_log = []
        self.performance_history = []
    
    def schedule_monitoring(self, monitor_callback):
        """Schedule daily monitoring."""
        self.algo.Schedule.On(
            self.algo.DateRules.EveryDay(),
            self.algo.TimeRules.AfterMarketOpen('SPY', config.MONITOR_TIME_MINUTES_AFTER_OPEN),
            monitor_callback
        )
        self.algo.Log("[Monitor] Daily monitoring scheduled: %dmin after open" % config.MONITOR_TIME_MINUTES_AFTER_OPEN)
    
    def daily_check(self, universe_manager, risk_controller, order_executor):
        """Perform daily monitoring check."""
        self.algo.Log("\n" + "="*50)
        self.algo.Log("[Monitor] Daily Check: %s" % str(self.algo.Time.date()))
        self.algo.Log("="*50)
        
        equity = self.algo.Portfolio.TotalPortfolioValue
        cash = self.algo.Portfolio.Cash
        if equity > 0:
            self.algo.Log("Equity: $%d | Cash: $%d (%.1f%%)" % (int(equity), int(cash), cash/equity*100))
        else:
            self.algo.Log("Equity: $%d | Cash: $%d" % (int(equity), int(cash)))
        
        risk_summary = risk_controller.get_risk_summary()
        self.algo.Log(risk_summary)
        
        pos_summary = order_executor.get_position_summary(universe_manager)
        self.algo.Log(pos_summary)
        
        self._check_alerts(risk_controller)
        
        self.algo.Log("="*50 + "\n")
    
    def _check_alerts(self, risk_controller):
        """Check for risk alerts and log them."""
        alerts = []
        
        vix_limit = risk_controller.get_vix_position_limit()
        if vix_limit < 1.0:
            alerts.append("VIX elevated: position limit %.0f%%" % (vix_limit * 100))
        
        if config.USE_MARKET_TREND_FILTER and not risk_controller.check_market_trend():
            alerts.append("Market below %dMA" % config.MARKET_TREND_MA)
        
        if risk_controller.check_drawdown():
            alerts.append("DRAWDOWN PROTECTION ACTIVE")
        
        if alerts:
            self.algo.Log("[ALERTS] " + " | ".join(alerts))
        
        return alerts
    
    def record_performance(self):
        """Record daily performance metrics."""
        equity = self.algo.Portfolio.TotalPortfolioValue
        self.performance_history.append({
            'date': self.algo.Time.date(),
            'equity': equity,
        })
    
    def get_performance_summary(self):
        """Get performance summary."""
        if not self.performance_history:
            return "No performance data"
        
        start = self.performance_history[0]['equity']
        current = self.performance_history[-1]['equity']
        total_return = (current / start - 1) * 100 if start > 0 else 0
        
        lines = [
            "\n=== PERFORMANCE SUMMARY ===",
            "Start Equity: $%d" % int(start),
            "End Equity: $%d" % int(current),
            "Total Return: %.2f%%" % total_return,
            "Days Tracked: %d" % len(self.performance_history),
        ]
        
        return "\n".join(lines)
    
    def log_trade(self, action, ticker, quantity, price, reason=""):
        """Log a trade execution."""
        self.algo.Log("[TRADE] %s %s %.0f @ %.2f %s" % (action, ticker, quantity, price, reason))
    
    def log_signal(self, signal_type, details):
        """Log a signal event."""
        self.algo.Log("[SIGNAL] %s: %s" % (signal_type, details))
