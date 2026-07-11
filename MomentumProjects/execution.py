"""
execution.py - Execution Engine Module
Order execution with rebalance scheduling.
"""
from AlgorithmImports import *
import config


class OrderExecutor:
    """Handles order execution and rebalancing."""
    
    def __init__(self, algorithm):
        self.algo = algorithm
        self.pending_orders = []
        self.last_rebalance = None
    
    def schedule_rebalance(self, rebalance_callback):
        """Schedule regular rebalancing."""
        if config.REBALANCE_FREQUENCY == 'weekly':
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            day_name = day_names[config.REBALANCE_DAY]
            
            self.algo.Schedule.On(
                self.algo.DateRules.WeekStart(day_name),
                self.algo.TimeRules.AfterMarketOpen('SPY', config.REBALANCE_MINUTES_AFTER_OPEN),
                rebalance_callback
            )
            self.algo.Log("[Execution] Weekly rebalance scheduled: %s %dmin after open" % (day_name, config.REBALANCE_MINUTES_AFTER_OPEN))
        
        elif config.REBALANCE_FREQUENCY == 'monthly':
            self.algo.Schedule.On(
                self.algo.DateRules.MonthStart(),
                self.algo.TimeRules.AfterMarketOpen('SPY', config.REBALANCE_MINUTES_AFTER_OPEN),
                rebalance_callback
            )
            self.algo.Log("[Execution] Monthly rebalance scheduled")
    
    def execute_rebalance(self, target_weights, universe_manager, risk_controller):
        """Execute portfolio rebalance to target weights."""
        risk_mult = risk_controller.get_current_exposure_multiplier()
        adjusted_weights = {t: w * risk_mult for t, w in target_weights.items()}
        
        self.algo.Log("[Execution] Rebalancing %d positions (risk mult: %.2f)" % (len(adjusted_weights), risk_mult))
        
        for ticker, symbol in universe_manager.symbols.items():
            if self.algo.Portfolio[symbol].Invested and ticker not in adjusted_weights:
                self.algo.Liquidate(symbol)
                self.algo.Log("[Execution] SELL %s - removed from portfolio" % ticker)
                risk_controller.record_exit(ticker)
        
        for ticker, target_weight in adjusted_weights.items():
            symbol = universe_manager.get_symbol(ticker)
            if symbol is None:
                continue
            
            try:
                current_weight = self._get_current_weight(symbol)
                
                if abs(current_weight - target_weight) < 0.01:
                    continue
                
                self.algo.SetHoldings(symbol, target_weight)
                self.algo.Log("[Execution] SET %s to %.2f%% (was %.2f%%)" % (ticker, target_weight * 100, current_weight * 100))
                
                if current_weight == 0 and target_weight > 0:
                    risk_controller.record_entry(ticker, self.algo.Securities[symbol].Close)
                
            except Exception as e:
                self.algo.Log("[Execution] ERROR setting %s: %s" % (ticker, str(e)))
        
        self.last_rebalance = self.algo.Time
    
    def execute_partial_sell(self, ticker, symbol, fraction=None):
        """Execute partial sell (take profit)."""
        if fraction is None:
            fraction = config.TAKE_PROFIT_PARTIAL
        
        if not self.algo.Portfolio[symbol].Invested:
            return
        
        holdings = self.algo.Portfolio[symbol].Quantity
        sell_quantity = holdings * fraction
        
        if sell_quantity > 0:
            self.algo.MarketOrder(symbol, -sell_quantity)
            self.algo.Log("[Execution] PARTIAL SELL %s %.0f%% (%.0f shares)" % (ticker, fraction * 100, sell_quantity))
    
    def execute_full_exit(self, ticker, symbol, reason, risk_controller):
        """Execute full position exit."""
        if not self.algo.Portfolio[symbol].Invested:
            return
        
        self.algo.Liquidate(symbol)
        self.algo.Log("[Execution] FULL EXIT %s - %s" % (ticker, reason))
        risk_controller.record_exit(ticker)
    
    def _get_current_weight(self, symbol):
        """Get current portfolio weight of a symbol."""
        if not self.algo.Portfolio[symbol].Invested:
            return 0.0
        
        position_value = self.algo.Portfolio[symbol].HoldingsValue
        total_value = self.algo.Portfolio.TotalPortfolioValue
        
        if total_value > 0:
            return position_value / total_value
        return 0.0
    
    def get_last_rebalance(self):
        """Get last rebalance time."""
        return self.last_rebalance
    
    def get_position_summary(self, universe_manager):
        """Get summary of current positions."""
        lines = ["\n=== POSITIONS ==="]
        
        invested = []
        for t, s in universe_manager.symbols.items():
            if self.algo.Portfolio[s].Invested:
                invested.append((t, s))
        
        if not invested:
            lines.append("No positions")
            return "\n".join(lines)
        
        total_value = self.algo.Portfolio.TotalPortfolioValue
        
        for ticker, symbol in invested:
            holding = self.algo.Portfolio[symbol]
            weight = holding.HoldingsValue / total_value if total_value > 0 else 0
            lines.append("  %s: %.2f%% (%.0f shares @ %.2f)" % (ticker, weight * 100, holding.Quantity, holding.Price))
        
        return "\n".join(lines)
