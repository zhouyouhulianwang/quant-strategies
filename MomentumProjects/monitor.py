"""
monitor.py - Daily Monitor Module

Daily monitoring of positions, risk, and logging.
"""
from AlgorithmImports import *
from typing import Dict, List, Optional
import config


class Monitor:
    """
    Daily monitoring and logging system.
    
    Features:
    - Daily position check
    - Risk status logging
    - Performance tracking
    - Alert generation
    """
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.daily_log = []
        self.performance_history = []
    
    def schedule_monitoring(self, monitor_callback):
        """
        Schedule daily monitoring.
        
        Args:
            monitor_callback: Function to call for daily monitoring
        """
        self.algo.Schedule.On(
            self.algo.DateRules.EveryDay(),
            self.algo.TimeRules.AfterMarketOpen('SPY', config.MONITOR_TIME_MINUTES_AFTER_OPEN),
            monitor_callback
        )
        self.algo.Log(f"[Monitor] Daily monitoring scheduled: {config.MONITOR_TIME_MINUTES_AFTER_OPEN}min after open")
    
    def daily_check(self, universe_manager, risk_manager, execution_engine):
        """
        Perform daily monitoring check.
        
        Args:
            universe_manager: UniverseManager instance
            risk_manager: RiskManager instance
            execution_engine: ExecutionEngine instance
        """
        self.algo.Log(f"\n{'='*50}")
        self.algo.Log(f"[Monitor] Daily Check: {self.algo.Time.date()}")
        self.algo.Log(f"{'='*50}")
        
        # Portfolio summary
        equity = self.algo.Portfolio.TotalPortfolioValue
        cash = self.algo.Portfolio.Cash
        self.algo.Log(f"Equity: ${equity:,.0f} | Cash: ${cash:,.0f} ({cash/equity:.1%})")
        
        # Risk summary
        risk_summary = risk_manager.get_risk_summary()
        self.algo.Log(risk_summary)
        
        # Position summary
        pos_summary = execution_engine.get_position_summary(universe_manager)
        self.algo.Log(pos_summary)
        
        # Check for any risk alerts
        self._check_alerts(risk_manager)
        
        self.algo.Log(f"{'='*50}\n")
    
    def _check_alerts(self, risk_manager):
        """Check for risk alerts and log them."""
        alerts = []
        
        # VIX alert
        vix_limit = risk_manager.get_vix_position_limit()
        if vix_limit < 1.0:
            alerts.append(f"VIX elevated: position limit {vix_limit:.0%}")
        
        # Trend alert
        if config.USE_MARKET_TREND_FILTER and not risk_manager.check_market_trend():
            alerts.append(f"Market below {config.MARKET_TREND_MA}MA")
        
        # Drawdown alert
        if risk_manager.check_drawdown():
            alerts.append(f"DRAWDOWN PROTECTION ACTIVE")
        
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
    
    def get_performance_summary(self) -> str:
        """Get performance summary."""
        if not self.performance_history:
            return "No performance data"
        
        start = self.performance_history[0]['equity']
        current = self.performance_history[-1]['equity']
        total_return = (current / start - 1) * 100 if start > 0 else 0
        
        lines = [
            "\n=== PERFORMANCE SUMMARY ===",
            f"Start Equity: ${start:,.0f}",
            f"End Equity: ${current:,.0f}",
            f"Total Return: {total_return:.2f}%",
            f"Days Tracked: {len(self.performance_history)}",
        ]
        
        return "\n".join(lines)
    
    def log_trade(self, action: str, ticker: str, quantity: float, price: float, reason: str = ""):
        """Log a trade execution."""
        self.algo.Log(f"[TRADE] {action} {ticker} {quantity:.0f} @ {price:.2f} {reason}")
    
    def log_signal(self, signal_type: str, details: str):
        """Log a signal event."""
        self.algo.Log(f"[SIGNAL] {signal_type}: {details}")
