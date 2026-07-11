"""
main.py - Momentum Strategy Main Entry

Professional modular momentum strategy with:
- Universe Manager (stock pool filtering)
- Momentum Engine (multi-period scoring)
- Sector Rotation (industry filtering)
- Portfolio Manager (position sizing)
- Risk Manager (VIX, stops, drawdown)
- Execution Engine (order execution)
- Monitor (daily logging)
"""
from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional
import config
from universe import UniverseManager
from momentum import MomentumEngine
from sector import SectorRotation
from portfolio import PortfolioManager
from risk import RiskManager
from execution import ExecutionEngine
from monitor import Monitor


class MomentumStrategy(QCAlgorithm):
    """
    Modular Momentum Strategy - Professional Quantitative Trading System
    
    Architecture:
        Universe -> Momentum -> Sector Filter -> Portfolio -> Risk Check -> Execute
    """
    
    def Initialize(self):
        # ============ BASIC SETUP ============
        self.SetStartDate(*config.START_DATE)
        self.SetEndDate(*config.END_DATE)
        self.SetCash(config.INITIAL_CASH)
        self.SetBrokerageModel(
            BrokerageName.INTERACTIVE_BROKERS_BROKERAGE,
            AccountType.MARGIN
        )
        self.Settings.DailyPreciseEndTime = False
        self.Settings.FreePortfolioValuePercentage = config.CASH_BUFFER_PCT
        
        # ============ INITIALIZE MODULES ============
        self.universe = UniverseManager(self)
        self.momentum = MomentumEngine(self)
        self.sector = SectorRotation(self)
        self.portfolio = PortfolioManager(self)
        self.risk = RiskManager(self)
        self.execution = ExecutionEngine(self)
        self.monitor = Monitor(self)
        
        # ============ INITIALIZE UNIVERSE ============
        self.universe.initialize()
        
        # ============ INITIALIZE SECTOR ETFs ============
        self.sector.initialize()
        
        # ============ INITIALIZE RISK ============
        self.risk.initialize()
        
        # ============ SCHEDULE REBALANCE ============
        self.execution.schedule_rebalance(self.WeeklyRebalance)
        
        # ============ SCHEDULE DAILY MONITOR ============
        self.monitor.schedule_monitoring(self.DailyMonitor)
        
        # ============ WARMUP ============
        max_period = max(config.MOMENTUM_PERIODS.values()) + config.TREND_MA_PERIOD + 20
        self.SetWarmUp(timedelta(days=max_period))
        
        self.Log(f"[Strategy] Initialized. Warmup: {max_period} days")
    
    def WeeklyRebalance(self):
        """
        Weekly rebalancing - core strategy logic.
        """
        self.Log(f"\n{'='*60}")
        self.Log(f"[Rebalance] Starting weekly rebalance: {self.Time.date()}")
        self.Log(f"{'='*60}")
        
        # Step 1: Check if we should rebalance (risk checks)
        if self.risk.check_drawdown():
            self.Log("[Rebalance] SKIPPED - Drawdown protection active")
            return
        
        # Step 2: Update universe liquidity
        self.universe.update_liquid_filter()
        
        # Step 3: Update sector momentum
        self.sector.update_sector_momentum()
        
        # Step 4: Get liquid universe
        liquid_tickers = self.universe.get_liquid_universe()
        if len(liquid_tickers) < config.TOP_N_STOCKS * 2:
            self.Log(f"[Rebalance] WARNING - Only {len(liquid_tickers)} liquid stocks, need {config.TOP_N_STOCKS * 2}")
        
        # Step 5: Calculate momentum scores
        self.momentum.initialize_indicators(liquid_tickers, self.universe)
        scores = self.momentum.calculate_momentum_scores(liquid_tickers, self.universe)
        
        # Step 6: Get top N by momentum
        top_tickers = self.momentum.get_top_tickers(liquid_tickers, n=config.TOP_N_STOCKS * 2)
        self.Log(f"[Rebalance] Top momentum stocks: {[t[0] for t in top_tickers[:10]]}")
        
        # Step 7: Filter by sector rotation
        if config.USE_SECTOR_ROTATION:
            filtered_tickers = self.sector.filter_by_sector([t[0] for t in top_tickers], self.universe)
            top_tickers = [(t, s) for t, s in top_tickers if t in filtered_tickers][:config.TOP_N_STOCKS]
        else:
            top_tickers = top_tickers[:config.TOP_N_STOCKS]
        
        self.Log(f"[Rebalance] Final selection: {[t[0] for t in top_tickers]}")
        
        # Step 8: Calculate portfolio weights
        target_weights = self.portfolio.calculate_weights(top_tickers, self.universe, self.sector)
        
        # Step 9: Execute rebalance
        self.execution.execute_rebalance(target_weights, self.universe, self.risk)
        
        self.Log(f"[Rebalance] Complete. Target exposure: {self.portfolio.get_total_target_exposure():.2%}")
    
    def DailyMonitor(self):
        """
        Daily monitoring - check stops, alerts, logging.
        """
        # Daily check
        self.monitor.daily_check(self.universe, self.risk, self.execution)
        
        # Check stop losses for all positions
        for ticker in self.universe.get_liquid_universe():
            symbol = self.universe.get_symbol(ticker)
            if symbol is None:
                continue
            
            if not self.Portfolio[symbol].Invested:
                continue
            
            # Check stop loss / take profit / trailing stop
            exit_signal = self.risk.check_stop_loss(ticker, symbol, self.universe)
            
            if exit_signal == 'stop_loss':
                self.execution.execute_full_exit(ticker, symbol, 'STOP LOSS', self.risk)
                self.monitor.log_trade('SELL', ticker, self.Portfolio[symbol].Quantity, 
                                      self.Securities[symbol].Close, 'Stop Loss')
            
            elif exit_signal == 'take_profit_partial':
                self.execution.execute_partial_sell(ticker, symbol)
                self.monitor.log_trade('PARTIAL_SELL', ticker, 
                                      self.Portfolio[symbol].Quantity * config.TAKE_PROFIT_PARTIAL,
                                      self.Securities[symbol].Close, 'Take Profit')
            
            elif exit_signal == 'trailing_stop':
                self.execution.execute_full_exit(ticker, symbol, 'TRAILING STOP', self.risk)
                self.monitor.log_trade('SELL', ticker, self.Portfolio[symbol].Quantity,
                                      self.Securities[symbol].Close, 'Trailing Stop')
        
        # Record performance
        self.monitor.record_performance()
    
    def OnData(self, data):
        """
        OnData - minimal, only for emergency checks.
        Main logic is in scheduled events.
        """
        pass
    
    def OnEndOfAlgorithm(self):
        """
        End of algorithm - final reporting.
        """
        self.Log("\n" + "="*60)
        self.Log("[Strategy] Algorithm Complete")
        self.Log("="*60)
        
        # Performance summary
        self.Log(self.monitor.get_performance_summary())
        
        # Risk summary
        self.Log(self.risk.get_risk_summary())
        
        # Position summary
        self.Log(self.execution.get_position_summary(self.universe))
        
        self.Log("="*60)
