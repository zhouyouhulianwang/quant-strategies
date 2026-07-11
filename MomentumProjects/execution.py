"""
execution.py - Execution Engine Module

Order execution with rebalance scheduling.
"""
from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional
import config


class ExecutionEngine:
    """
    Handles order execution and rebalancing.
    
    Features:
    - Scheduled weekly rebalancing
    - Market order execution
    - Partial sell handling
    - Position tracking
    """
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.pending_orders = []
        self.last_rebalance = None
    
    def schedule_rebalance(self, rebalance_callback):
        """
        Schedule regular rebalancing.
        
        Args:
            rebalance_callback: Function to call on rebalance day
        """
        if config.REBALANCE_FREQUENCY == 'weekly':
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            day_name = day_names[config.REBALANCE_DAY]
            
            self.algo.Schedule.On(
                self.algo.DateRules.WeekStart(day_name),
                self.algo.TimeRules.AfterMarketOpen('SPY', config.REBALANCE_MINUTES_AFTER_OPEN),
                rebalance_callback
            )
            self.algo.Log(f"[Execution] Weekly rebalance scheduled: {day_name} {config.REBALANCE_MINUTES_AFTER_OPEN}min after open")
        
        elif config.REBALANCE_FREQUENCY == 'monthly':
            self.algo.Schedule.On(
                self.algo.DateRules.MonthStart(),
                self.algo.TimeRules.AfterMarketOpen('SPY', config.REBALANCE_MINUTES_AFTER_OPEN),
                rebalance_callback
            )
            self.algo.Log("[Execution] Monthly rebalance scheduled")
    
    def execute_rebalance(self, target_weights: Dict[str, float], 
                         universe_manager, risk_manager):
        """
        Execute portfolio rebalance to target weights.
        
        Args:
            target_weights: Dict[ticker, weight] - target weights
            universe_manager: UniverseManager instance
            risk_manager: RiskManager instance
        """
        # Apply risk multiplier
        risk_mult = risk_manager.get_current_exposure_multiplier()
        adjusted_weights = {t: w * risk_mult for t, w in target_weights.items()}
        
        self.algo.Log(f"[Execution] Rebalancing {len(adjusted_weights)} positions (risk mult: {risk_mult:.2f})")
        
        # Sell positions not in target
        for ticker, symbol in universe_manager.symbols.items():
            if self.algo.Portfolio[symbol].Invested and ticker not in adjusted_weights:
                self.algo.Liquidate(symbol)
                self.algo.Log(f"[Execution] SELL {ticker} - removed from portfolio")
                risk_manager.record_exit(ticker)
        
        # Adjust positions to target weights
        for ticker, target_weight in adjusted_weights.items():
            symbol = universe_manager.get_symbol(ticker)
            if symbol is None:
                continue
            
            try:
                current_weight = self._get_current_weight(symbol)
                
                # Check if rebalance needed (threshold: 1% difference)
                if abs(current_weight - target_weight) < 0.01:
                    continue
                
                # Set target holding
                self.algo.SetHoldings(symbol, target_weight)
                self.algo.Log(f"[Execution] SET {ticker} to {target_weight:.2%} (was {current_weight:.2%})")
                
                # Record entry if new position
                if current_weight == 0 and target_weight > 0:
                    risk_manager.record_entry(ticker, self.algo.Securities[symbol].Close)
                
            except Exception as e:
                self.algo.Log(f"[Execution] ERROR setting {ticker}: {e}")
        
        self.last_rebalance = self.algo.Time
    
    def execute_partial_sell(self, ticker: str, symbol: Symbol, 
                            fraction: float = config.TAKE_PROFIT_PARTIAL):
        """
        Execute partial sell (take profit).
        
        Args:
            ticker: Ticker string
            symbol: Symbol object
            fraction: Fraction to sell (default 0.5 = 50%)
        """
        if not self.algo.Portfolio[symbol].Invested:
            return
        
        holdings = self.algo.Portfolio[symbol].Quantity
        sell_quantity = holdings * fraction
        
        if sell_quantity > 0:
            self.algo.MarketOrder(symbol, -sell_quantity)
            self.algo.Log(f"[Execution] PARTIAL SELL {ticker} {fraction:.0%} ({sell_quantity:.0f} shares)")
    
    def execute_full_exit(self, ticker: str, symbol: Symbol, reason: str, risk_manager):
        """
        Execute full position exit (stop loss, trailing stop, etc.).
        
        Args:
            ticker: Ticker string
            symbol: Symbol object
            reason: Exit reason for logging
            risk_manager: RiskManager instance
        """
        if not self.algo.Portfolio[symbol].Invested:
            return
        
        self.algo.Liquidate(symbol)
        self.algo.Log(f"[Execution] FULL EXIT {ticker} - {reason}")
        risk_manager.record_exit(ticker)
    
    def _get_current_weight(self, symbol: Symbol) -> float:
        """Get current portfolio weight of a symbol."""
        if not self.algo.Portfolio[symbol].Invested:
            return 0.0
        
        position_value = self.algo.Portfolio[symbol].HoldingsValue
        total_value = self.algo.Portfolio.TotalPortfolioValue
        
        if total_value > 0:
            return position_value / total_value
        return 0.0
    
    def get_last_rebalance(self) -> Optional[datetime]:
        """Get last rebalance time."""
        return self.last_rebalance
    
    def get_position_summary(self, universe_manager) -> str:
        """Get summary of current positions."""
        lines = ["\n=== POSITIONS ==="]
        
        invested = [(t, s) for t, s in universe_manager.symbols.items() 
                   if self.algo.Portfolio[s].Invested]
        
        if not invested:
            lines.append("No positions")
            return "\n".join(lines)
        
        total_value = self.algo.Portfolio.TotalPortfolioValue
        
        for ticker, symbol in invested:
            holding = self.algo.Portfolio[symbol]
            weight = holding.HoldingsValue / total_value if total_value > 0 else 0
            lines.append(f"  {ticker}: {weight:.2%} ({holding.Quantity:.0f} shares @ {holding.Price:.2f})")
        
        return "\n".join(lines)
