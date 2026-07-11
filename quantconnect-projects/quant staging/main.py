"""
AdaptiveMomentumStrategy v3.2
Professional quantitative trading strategy with sector rotation and risk management.

Key Features:
- Multi-period momentum scoring with adaptive weights
- Sector rotation filtering
- Limit order execution (reduces slippage vs market orders)
- Intraday order scheduling (avoids open/close auction volatility)
- Layered risk management (stop-loss, trailing stop, drawdown protection)
- Dynamic position sizing based on market regime
"""
from AlgorithmImports import *
from typing import Dict, List, Optional


class AdaptiveMomentumStrategy(QCAlgorithm):
    """
    Adaptive momentum strategy with professional execution optimization.
    
    Execution Improvements (v3.2):
    - Limit orders instead of market orders to reduce slippage
    - Intraday execution window (10:30 AM - 3:30 PM) to avoid open/close volatility
    - Order timeout and cancellation logic
    - Simplified and cleaned codebase
    """
    
    def Initialize(self):
        # === Basic Settings ===
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2026, 6, 30)
        self.SetCash(100000)
        self.SetBrokerageModel(
            BrokerageName.INTERACTIVE_BROKERS_BROKERAGE,
            AccountType.MARGIN
        )
        
        self.Settings.DailyPreciseEndTime = False
        self.Settings.FreePortfolioValuePercentage = 0.05
        
        # === Momentum Parameters ===
        self.lookback_periods = {
            '1d': 1, '1w': 5, '2w': 10,
            '1m': 21, '3m': 63, '6m': 126
        }
        self.base_weights = {
            '1d': 0.1, '1w': 0.5, '2w': 1.0,
            '1m': 1.0, '3m': 0.7, '6m': 0.5
        }
        self.current_weights = self.base_weights.copy()
        
        # === RSI Parameters ===
        self.rsi_overbought = 65
        self.rsi_oversold = 35
        self.rsi_adjustment_factor = 0.4
        self.rsi_period = 14
        
        # === VIX Parameters ===
        self._InitializeVIX()
        self.vix_pause_level = 30.0
        self.vix_boost_level = 18.0
        
        # === Position Management ===
        self.max_position_pct = 0.15
        self.min_position_pct = 0.0
        self.max_stocks = 10
        self.min_score = 0.0
        self.min_hold_days = 3
        self.max_total_exposure = 0.80
        self.min_total_exposure = 0.30
        self.current_total_exposure = self.min_total_exposure
        self.max_sector_pct = 0.50
        
        # === Execution Parameters (v3.2) ===
        self.use_limit_orders = True
        self.limit_order_offset_pct = 0.001  # 0.1% offset from current price
        self.order_timeout_minutes = 30
        self.execution_start_minutes = 30  # 10:00 AM
        self.execution_end_minutes = 390   # 3:30 PM
        self.pending_orders = {}  # Track pending limit orders
        
        # === Risk Management ===
        self.stop_loss_pct = 0.08
        self.trailing_stop_enabled = True
        self.trailing_stop_pct = 0.10
        self.drawdown_trigger_level = 0.10
        self.drawdown_severe_level = 0.15
        self.drawdown_extreme_level = 0.20
        self.high_water_mark = 0
        self.drawdown_protection_triggered = False
        
        # === Market Regime ===
        self.market_bear_mode = False
        self.bear_mode_confirm_days = 3
        self.bear_mode_counter = 0
        
        # === Sector Rotation ===
        self.sector_rotation_enabled = True
        self.n_top_sectors = 3
        self.sector_lookback = 30
        self.sector_map = self._BuildSectorMap()
        
        # === Rebalancing ===
        self.rebalance_frequency = "weekly"
        self.base_rebalance_freq = 2
        self.min_rebalance_freq = 1
        self.max_rebalance_freq = 8
        self.week_counter = 0
        self.current_rebalance_freq = self.base_rebalance_freq
        self.pause_weeks = 0
        self.max_pause_weeks = 4
        self.valuation_extreme = 0.8
        
        # === Data Structures ===
        self.position_entry_date = {}
        self.cost_basis = {}
        self.position_high = {}
        self.liquid_stocks = set()
        self.liquid_stocks_initialized = False
        
        # === Symbols ===
        self.us_tickers = list(self.sector_map.keys())
        self.safe_tickers = ["TLT", "GLD"]
        self.safe_symbols = {}
        self.symbols = {}
        self.ticker_list = []
        
        # === Indicators ===
        self.rsi_indicators = {}
        self.sma_indicators = {}
        
        # === Initialize ===
        self._InitializeSymbols()
        self.SetSecurityInitializer(self.CustomSecurityInitializer)
        
        # === Scheduling (v3.2: Intraday execution window) ===
        # Stop-loss check at 10:00 AM
        self.Schedule.On(
            self.DateRules.EveryDay("SPY"),
            self.TimeRules.AfterMarketOpen("SPY", 30),
            self.CheckStopLoss
        )
        
        # Drawdown check at 10:05 AM
        self.Schedule.On(
            self.DateRules.EveryDay("SPY"),
            self.TimeRules.AfterMarketOpen("SPY", 35),
            self.CheckMaxDrawdown
        )
        
        # Rebalancing at 10:30 AM (intraday, not at open)
        self.SetRebalanceSchedule()
        
        # === WarmUp ===
        warmup_days = max(self.lookback_periods['6m'], self.sector_lookback) + 200 + 20
        self.SetWarmUp(timedelta(days=warmup_days))
        
        self.Log(f"Strategy initialized. WarmUp: {warmup_days} days")
    
    def _InitializeVIX(self):
        """Initialize VIX data source."""
        vix_available = False
        try:
            vix_sym = self.AddIndex("VIX", Resolution.DAILY).Symbol
            if self.Securities[vix_sym].Price > 0:
                self.vix_symbol = vix_sym
                vix_available = True
                self.Log("Using VIX index")
        except:
            pass
        
        if not vix_available:
            self.vix_symbol = self.AddEquity("VIXY", Resolution.DAILY).Symbol
            self.Log("VIX unavailable, using VIXY")
    
    def _BuildSectorMap(self) -> Dict[str, str]:
        """Load sector mapping from strategy_config.py"""
        try:
            from strategy_config import SECTOR_MAP
            self.Log(f"Loaded sector map: {len(SECTOR_MAP)} stocks")
            return SECTOR_MAP
        except Exception as e:
            self.Log(f"Failed to load strategy_config.py: {e}")
        
        # Fallback for local backtesting
        import json, os, inspect
        algorithm_dir = os.path.dirname(os.path.abspath(inspect.getfile(self.__class__)))
        paths = [
            os.path.join(algorithm_dir, "strategy_config.json"),
            "strategy_config.json",
            "/home/pc/.openclaw/workspace/quantconnect-projects/strategy_config.json",
        ]
        for path in paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        config = json.load(f)
                        if 'sector_map' in config:
                            sector_map = config['sector_map']
                            self.Log(f"Loaded from {path}: {len(sector_map)} stocks")
                            return sector_map
                except Exception as e:
                    self.Log(f"JSON load failed: {e}")
        
        self.Log("ERROR: Cannot load sector map")
        return {}
    
    def _InitializeSymbols(self):
        """Initialize all equity symbols."""
        success_count = 0
        failed_tickers = []
        
        for ticker in self.us_tickers:
            try:
                symbol = self.AddEquity(ticker, Resolution.DAILY).Symbol
                self.symbols[ticker] = symbol
                self.ticker_list.append(ticker)
                success_count += 1
                
                if ticker not in self.safe_tickers:
                    self.rsi_indicators[symbol] = self.RSI(symbol, self.rsi_period)
                    self.sma_indicators[symbol] = self.SMA(symbol, 200)
            except Exception as e:
                failed_tickers.append(ticker)
                self.Log(f"ERROR adding {ticker}: {e}")
        
        self.Log(f"[COVERAGE] Loaded: {success_count}/{len(self.us_tickers)} stocks")
        if failed_tickers:
            self.Log(f"[COVERAGE] Failed: {', '.join(failed_tickers[:20])}")
        
        for ticker in self.safe_tickers:
            try:
                self.safe_symbols[ticker] = self.AddEquity(ticker, Resolution.DAILY).Symbol
            except Exception as e:
                self.Log(f"ERROR adding safe asset {ticker}: {e}")
    
    def CustomSecurityInitializer(self, security):
        """Custom slippage model."""
        security.SetSlippageModel(ConstantSlippageModel(0.001))
    
    def _UpdateLiquidityFilter(self):
        """Update liquid stocks list based on volume."""
        self.liquid_stocks = set()
        min_volume = 5000000 if self.market_bear_mode else 10000000
        
        for ticker, symbol in self.symbols.items():
            try:
                security = self.Securities[symbol]
                if security.Price >= 5.0:
                    history = self.History(symbol, 20, Resolution.DAILY)
                    if not history.empty and len(history) >= 10:
                        avg_volume = history['volume'].mean()
                        if avg_volume >= min_volume:
                            self.liquid_stocks.add(ticker)
            except:
                pass
        
        self.Log(f"Liquidity filter: {len(self.liquid_stocks)}/{len(self.symbols)} stocks")
    
    def _IsLiquid(self, ticker: str) -> bool:
        """Check if stock is liquid."""
        return ticker in self.liquid_stocks or ticker in self.safe_tickers
    
    def _CanSell(self, symbol: Symbol) -> bool:
        """Check minimum holding period."""
        if symbol not in self.position_entry_date:
            return True
        hold_days = (self.Time - self.position_entry_date[symbol]).days
        return hold_days >= self.min_hold_days
    
    def _RecordBuyDate(self, symbol: Symbol):
        """Record buy date for position."""
        if self.Portfolio[symbol].Invested and symbol not in self.position_entry_date:
            self.position_entry_date[symbol] = self.Time
    
    def GetTickerName(self, symbol: Symbol) -> str:
        """Get ticker name from symbol."""
        for name, sym in self.symbols.items():
            if sym == symbol:
                return name
        for name, sym in self.safe_symbols.items():
            if sym == symbol:
                return name
        return str(symbol)
    
    # ==================== SCHEDULING ====================
    
    def SetRebalanceSchedule(self):
        """Set rebalancing schedule with intraday execution."""
        if self.rebalance_frequency == "weekly":
            self.Schedule.On(
                self.DateRules.Every(DayOfWeek.MONDAY),
                self.TimeRules.AfterMarketOpen("SPY", self.execution_start_minutes),
                self.WeeklyUpdate
            )
            self.Log(f"Rebalance: Every Monday at {self.execution_start_minutes} mins after open")
        elif self.rebalance_frequency == "monthly":
            self.Schedule.On(
                self.DateRules.MonthStart("SPY"),
                self.TimeRules.AfterMarketOpen("SPY", self.execution_start_minutes),
                self.MonthlyRebalance
            )
    
    def MonthlyRebalance(self):
        """Monthly rebalancing entry."""
        current_month = self.Time.month
        if current_month not in getattr(self, 'rebalance_months', list(range(1, 13))):
            return
        
        self.Log(f"Monthly rebalance: month={current_month}")
        self.CheckMarketState()
        self.RebalanceUS()
    
    def WeeklyUpdate(self):
        """Weekly update entry."""
        self.week_counter += 1
        self.AdjustRebalanceFrequency()
        self.CheckMarketState()
        
        if self.week_counter % self.current_rebalance_freq == 1:
            self.RebalanceUS()
    
    def AdjustRebalanceFrequency(self):
        """Dynamically adjust rebalance frequency based on VIX."""
        try:
            vix_price = self.Securities[self.vix_symbol].Price
            if vix_price <= 0:
                vix_price = 25
            
            # Simplified valuation check
            is_extreme = False
            try:
                spy = self.symbols.get("SPY")
                if spy:
                    hist = self.History(spy, 63, Resolution.DAILY)
                    if not hist.empty and len(hist) >= 63:
                        ret = (hist['close'].iloc[-1] / hist['close'].iloc[0]) - 1
                        val = max(0, min(1, 0.5 + ret * 2))
                        is_extreme = val > self.valuation_extreme or val < (1 - self.valuation_extreme)
            except:
                pass
            
            if vix_price > self.vix_pause_level or is_extreme:
                self.current_rebalance_freq = min(self.current_rebalance_freq + 1, self.max_rebalance_freq)
                self.pause_weeks += 1
            elif vix_price < self.vix_boost_level and not is_extreme:
                self.current_rebalance_freq = max(self.current_rebalance_freq - 1, self.min_rebalance_freq)
                self.pause_weeks = 0
            else:
                self.current_rebalance_freq = self.base_rebalance_freq
                self.pause_weeks = 0
            
            if self.pause_weeks >= self.max_pause_weeks:
                self.current_rebalance_freq = self.base_rebalance_freq
                self.pause_weeks = 0
                
        except Exception as e:
            self.Log(f"ERROR in AdjustRebalanceFrequency: {e}")
            self.current_rebalance_freq = self.base_rebalance_freq
    
    # ==================== MARKET REGIME ====================
    
    def CheckMarketState(self):
        """Check if SPY is above 50-day SMA."""
        try:
            spy = self.symbols.get("SPY")
            if not spy:
                return
            
            sma50 = self.SMA(spy, 50)
            if not sma50 or not sma50.IsReady:
                return
            
            current = self.Securities[spy].Price
            sma_val = sma50.Current.Value
            
            is_below = current < sma_val
            
            if is_below:
                self.bear_mode_counter += 1
            else:
                self.bear_mode_counter = 0
            
            was_bear = self.market_bear_mode
            self.market_bear_mode = self.bear_mode_counter >= self.bear_mode_confirm_days
            
            if self.market_bear_mode:
                self.current_total_exposure = self.min_total_exposure
            else:
                dev = (current - sma_val) / sma_val if sma_val > 0 else 0
                if dev > 0.05:
                    self.current_total_exposure = self.max_total_exposure
                elif dev > 0.02:
                    self.current_total_exposure = 0.60
                else:
                    self.current_total_exposure = 0.45
            
            if self.market_bear_mode and not was_bear:
                self.Log(f"[ALERT] Bear market: SPY={current:.2f} < 50SMA={sma_val:.2f}")
                self.Liquidate()
                for sym in self.safe_symbols.values():
                    self.SetHoldings(sym, 0.5 / len(self.safe_symbols))
            elif not self.market_bear_mode and was_bear:
                self.Log(f"[ALERT] Bull market resumed: SPY={current:.2f} > 50SMA={sma_val:.2f}")
                for sym in self.safe_symbols.values():
                    if self.Portfolio[sym].Invested:
                        self.Liquidate(sym)
                        
        except Exception as e:
            self.Log(f"ERROR in CheckMarketState: {e}")
    
    # ==================== CORE STRATEGY ====================
    
    def CalculateMomentumScore(self, symbol: Symbol, ticker: str) -> Optional[Dict]:
        """Calculate momentum score with RSI adjustment."""
        try:
            hist = self.History(symbol, self.lookback_periods['6m'] + 20, Resolution.DAILY)
            if hist.empty or len(hist) < self.lookback_periods['6m']:
                return None
            
            closes = hist['close']
            price = closes.iloc[-1]
            
            returns = {}
            for period, days in self.lookback_periods.items():
                if len(closes) >= days:
                    returns[period] = (price - closes.iloc[-days]) / closes.iloc[-days]
                else:
                    returns[period] = 0
            
            base_score = sum(returns[p] * self.current_weights[p] for p in returns)
            
            # RSI adjustment
            rsi_adj_score = base_score
            if symbol in self.rsi_indicators:
                rsi = self.rsi_indicators[symbol]
                if rsi.IsReady:
                    rsi_val = rsi.Current.Value
                    if rsi_val > self.rsi_overbought:
                        rsi_adj_score = base_score * self.rsi_adjustment_factor
                    elif rsi_val < self.rsi_oversold and base_score > 0:
                        rsi_adj_score = base_score * (2.0 - self.rsi_adjustment_factor)
            
            return {
                'symbol': symbol,
                'ticker': ticker,
                'score': rsi_adj_score,
                'base_score': base_score,
                'current_price': price
            }
            
        except Exception as e:
            self.Log(f"ERROR calculating momentum for {ticker}: {e}")
            return None
    
    def GetSectorMomentum(self) -> List[str]:
        """Get top sectors by momentum."""
        sector_returns = {}
        
        for ticker, sector in self.sector_map.items():
            if ticker in self.symbols:
                try:
                    hist = self.History(self.symbols[ticker], self.sector_lookback + 5, Resolution.DAILY)
                    if not hist.empty and len(hist) >= self.sector_lookback:
                        ret = (hist['close'].iloc[-1] - hist['close'].iloc[0]) / hist['close'].iloc[0]
                        sector_returns.setdefault(sector, []).append(ret)
                except:
                    pass
        
        sector_momentum = {s: sum(r)/len(r) for s, r in sector_returns.items() if r}
        sorted_sectors = sorted(sector_momentum.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_sectors[:self.n_top_sectors]]
    
    def LimitSectorConcentration(self, targets: Dict[Symbol, float]) -> Dict[Symbol, float]:
        """Limit sector concentration."""
        if not self.sector_rotation_enabled:
            return targets
        
        sector_weights = {}
        for symbol, weight in targets.items():
            ticker = self.GetTickerName(symbol)
            sector = self.sector_map.get(ticker, 'Other')
            sector_weights[sector] = sector_weights.get(sector, 0) + weight
        
        adjusted = targets.copy()
        for sector, total in sector_weights.items():
            if total > self.max_sector_pct:
                scale = self.max_sector_pct / total
                for symbol in list(adjusted.keys()):
                    ticker = self.GetTickerName(symbol)
                    if self.sector_map.get(ticker, 'Other') == sector:
                        adjusted[symbol] *= scale
        
        return adjusted
    
    def RebalanceUS(self):
        """Rebalance US equity positions."""
        if self.IsWarmingUp:
            return
        
        if self.market_bear_mode:
            self.Log("Bear mode: skipping equity rebalance")
            return
        
        if not self.liquid_stocks_initialized:
            self._UpdateLiquidityFilter()
            self.liquid_stocks_initialized = True
        
        if self.week_counter % 4 == 0:
            self._UpdateLiquidityFilter()
        
        # Get sector filter
        if self.sector_rotation_enabled:
            top_sectors = self.GetSectorMomentum()
            if not top_sectors:
                self.Log("No sector momentum data")
            if 'Other' not in top_sectors:
                top_sectors.append('Other')
            
            us_symbols = {}
            for ticker, symbol in self.symbols.items():
                if ticker in self.us_tickers and self._IsLiquid(ticker):
                    sector = self.sector_map.get(ticker, 'Other')
                    if sector in top_sectors or ticker in ['SPY', 'QQQ', 'TLT', 'GLD']:
                        us_symbols[ticker] = symbol
        else:
            us_symbols = {k: v for k, v in self.symbols.items()
                         if k in self.us_tickers and self._IsLiquid(k)}
        
        self.RebalanceMarket(us_symbols, "US")
    
    def RebalanceMarket(self, market_symbols: Dict[str, Symbol], market_name: str):
        """Execute rebalancing with limit orders."""
        
        # Calculate momentum scores
        scores = {}
        for ticker, symbol in market_symbols.items():
            result = self.CalculateMomentumScore(symbol, ticker)
            if result and result['score'] > self.min_score:
                scores[ticker] = result
        
        if not scores:
            self.Log(f"{market_name}: No valid momentum scores")
            return
        
        # Select top stocks
        sorted_scores = sorted(scores.items(), key=lambda x: x[1]['score'], reverse=True)
        top_stocks = sorted_scores[:self.max_stocks]
        
        # Calculate target weights
        total_score = sum(d['score'] for _, d in top_stocks)
        targets = {}
        
        for ticker, data in top_stocks:
            weight = data['score'] / total_score if total_score > 0 else 0
            targets[data['symbol']] = weight
        
        # Limit position size
        max_w = max(targets.values()) if targets else 0
        if max_w > self.max_position_pct:
            scale = self.max_position_pct / max_w
            for sym in targets:
                targets[sym] *= scale
        
        # Remove small positions
        targets = {s: w for s, w in targets.items() if w >= self.min_position_pct}
        
        # Limit total exposure
        total_w = sum(targets.values())
        if total_w > self.current_total_exposure:
            scale = self.current_total_exposure / total_w
            for sym in targets:
                targets[sym] *= scale
        
        # Limit sector concentration
        targets = self.LimitSectorConcentration(targets)
        
        # Log allocation
        final_w = sum(targets.values())
        top5 = sorted(targets.items(), key=lambda x: x[1], reverse=True)[:5]
        top5_str = ", ".join([f"{self.GetTickerName(s)}:{w*100:.1f}%" for s, w in top5])
        self.Log(f"[{self.Time.date}] {market_name}: {len(targets)} stocks, total={final_w*100:.1f}%, top5={top5_str}")
        
        # Sell positions not in targets
        for symbol in list(self.cost_basis.keys()):
            ticker = self.GetTickerName(symbol)
            if ticker not in [self.GetTickerName(s) for s in targets.keys()] and ticker in market_symbols:
                if self.Portfolio[symbol].Invested and self._CanSell(symbol):
                    self._ExecuteLiquidation(symbol)
        
        # Execute orders with limit orders (v3.2)
        for symbol, target in targets.items():
            current_w = (self.Portfolio[symbol].HoldingsValue / self.Portfolio.TotalPortfolioValue
                        if self.Portfolio.TotalPortfolioValue > 0 else 0)
            
            if current_w == 0 or abs(current_w - target) > 0.10:
                self._PlaceOrder(symbol, target)
    
    def _PlaceOrder(self, symbol: Symbol, target_weight: float):
        """Place order with limit order optimization (v3.2)."""
        ticker = self.GetTickerName(symbol)
        current_price = self.Securities[symbol].Price
        
        if current_price <= 0:
            return
        
        portfolio_value = self.Portfolio.TotalPortfolioValue
        target_value = portfolio_value * target_weight
        current_value = self.Portfolio[symbol].HoldingsValue
        delta_value = target_value - current_value
        
        if abs(delta_value) < 100:  # Minimum $100 trade
            return
        
        quantity = int(delta_value / current_price)
        
        if quantity == 0:
            return
        
        if self.use_limit_orders:
            # Use limit order with small offset
            if quantity > 0:  # Buy
                limit_price = current_price * (1 + self.limit_order_offset_pct)
            else:  # Sell
                limit_price = current_price * (1 - self.limit_order_offset_pct)
            
            ticket = self.LimitOrder(symbol, quantity, limit_price)
            self.pending_orders[ticket.OrderId] = {
                'symbol': symbol,
                'target_weight': target_weight,
                'placed_time': self.Time
            }
            self.Log(f"Limit order placed: {ticker} {quantity:+d} @ ${limit_price:.2f}")
        else:
            self.MarketOrder(symbol, quantity)
            self.Log(f"Market order: {ticker} {quantity:+d}")
        
        # Record position data
        if quantity > 0:
            self._RecordBuyDate(symbol)
        
        if self.Portfolio[symbol].Invested:
            if symbol not in self.cost_basis:
                self.cost_basis[symbol] = self.Portfolio[symbol].AveragePrice
            if symbol not in self.position_high:
                self.position_high[symbol] = current_price
    
    def _ExecuteLiquidation(self, symbol: Symbol):
        """Liquidate position and clean up state."""
        ticker = self.GetTickerName(symbol)
        
        if self.use_limit_orders:
            current_price = self.Securities[symbol].Price
            quantity = -self.Portfolio[symbol].Quantity
            if quantity != 0:
                limit_price = current_price * (1 - self.limit_order_offset_pct)
                self.LimitOrder(symbol, quantity, limit_price)
                self.Log(f"Limit liquidation: {ticker} {quantity:+d} @ ${limit_price:.2f}")
        else:
            self.Liquidate(symbol)
        
        self.cost_basis.pop(symbol, None)
        self.position_high.pop(symbol, None)
        self.position_entry_date.pop(symbol, None)
    
    # ==================== RISK MANAGEMENT ====================
    
    def CheckStopLoss(self):
        """Check stop-loss and trailing stop."""
        if self.IsWarmingUp:
            return
        
        spy = self.symbols.get("SPY")
        if not spy or not self.Securities.ContainsKey(spy) or not self.Securities[spy].IsMarketOpen:
            return
        
        # Fixed stop-loss
        for symbol, cost in list(self.cost_basis.items()):
            if not self.Portfolio[symbol].Invested:
                continue
            
            price = self.Portfolio[symbol].Price
            if not self._CanSell(symbol):
                continue
            
            if cost > 0 and (price - cost) / cost < -self.stop_loss_pct:
                self._ExecuteLiquidation(symbol)
                self.Log(f"Stop-loss: {self.GetTickerName(symbol)} @ ${price:.2f}")
        
        # Trailing stop
        if self.trailing_stop_enabled:
            for symbol in list(self.position_high.keys()):
                if not self.Portfolio[symbol].Invested:
                    continue
                
                price = self.Portfolio[symbol].Price
                if price > self.position_high[symbol]:
                    self.position_high[symbol] = price
                
                high = self.position_high[symbol]
                if high > 0 and (price - high) / high < -self.trailing_stop_pct:
                    if self._CanSell(symbol):
                        self._ExecuteLiquidation(symbol)
                        self.Log(f"Trailing stop: {self.GetTickerName(symbol)} @ ${price:.2f}")
    
    def CheckMaxDrawdown(self):
        """Check maximum drawdown protection."""
        if self.IsWarmingUp:
            return
        
        spy = self.symbols.get("SPY")
        if not spy or not self.Securities.ContainsKey(spy) or not self.Securities[spy].IsMarketOpen:
            return
        
        current_value = self.Portfolio.TotalPortfolioValue
        
        if current_value > self.high_water_mark:
            self.high_water_mark = current_value
            if self.drawdown_protection_triggered and current_value >= self.high_water_mark * 0.95:
                self.Log(f"Drawdown recovered: ${current_value:,.2f}")
                self.drawdown_protection_triggered = False
        
        if self.high_water_mark <= 0:
            return
        
        drawdown = (current_value - self.high_water_mark) / self.high_water_mark
        
        if drawdown < -self.drawdown_extreme_level:
            if self.drawdown_protection_triggered != "extreme":
                self._ExecuteDrawdownProtection("extreme", drawdown)
        elif drawdown < -self.drawdown_severe_level:
            if self.drawdown_protection_triggered not in ["severe", "extreme"]:
                self._ExecuteDrawdownProtection("severe", drawdown)
        elif drawdown < -self.drawdown_trigger_level:
            if not self.drawdown_protection_triggered:
                self._ExecuteDrawdownProtection("triggered", drawdown)
                for sym in self.safe_symbols.values():
                    self.SetHoldings(sym, 0.5 / len(self.safe_symbols))
        elif drawdown > -0.05 and self.drawdown_protection_triggered:
            self.Log(f"Drawdown recovered: {drawdown:.2%}")
            self.drawdown_protection_triggered = False
    
    def _ExecuteDrawdownProtection(self, level: str, drawdown: float):
        """Execute drawdown protection."""
        self.Log(f"[{'CRITICAL' if level=='extreme' else 'WARNING'}] "
                 f"Drawdown protection ({level}): {drawdown:.2%}")
        self.Liquidate()
        self.drawdown_protection_triggered = level
        self.current_rebalance_freq = self.max_rebalance_freq
        self.pause_weeks = 0
    
    # ==================== ORDER EVENTS ====================
    
    def OnOrderEvent(self, orderEvent):
        """Handle order events - track limit order status (v3.2)."""
        if orderEvent.Status == OrderStatus.Filled:
            # Remove from pending orders
            self.pending_orders.pop(orderEvent.OrderId, None)
            
            # Record buy date for new positions
            if orderEvent.FillQuantity > 0:
                self._RecordBuyDate(orderEvent.Symbol)
                if orderEvent.Symbol not in self.cost_basis:
                    self.cost_basis[orderEvent.Symbol] = orderEvent.FillPrice
                if orderEvent.Symbol not in self.position_high:
                    self.position_high[orderEvent.Symbol] = orderEvent.FillPrice
        
        elif orderEvent.Status == OrderStatus.Canceled:
            self.pending_orders.pop(orderEvent.OrderId, None)
    
    def OnData(self, data):
        """Handle data updates - check for expired limit orders (v3.2)."""
        # Cancel stale limit orders
        current_time = self.Time
        expired_orders = []
        
        for order_id, order_info in list(self.pending_orders.items()):
            elapsed = (current_time - order_info['placed_time']).total_seconds() / 60
            if elapsed > self.order_timeout_minutes:
                expired_orders.append(order_id)
        
        for order_id in expired_orders:
            self.Transactions.CancelOrder(order_id)
            self.pending_orders.pop(order_id, None)
            self.Log(f"Cancelled stale limit order: {order_id}")
    
    def OnEndOfAlgorithm(self):
        """Algorithm end summary."""
        total_return = (self.Portfolio.TotalPortfolioValue - 100000) / 100000
        self.Log("=" * 50)
        self.Log(f"Strategy completed")
        self.Log(f"Total return: {total_return:.2%}")
        self.Log(f"Final equity: ${self.Portfolio.TotalPortfolioValue:,.2f}")
        self.Log("=" * 50)
