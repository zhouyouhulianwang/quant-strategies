"""
MomentumStrategy - Modular Momentum Strategy (Single File Version)
All modules integrated into one file for QuantConnect compatibility.
"""
from AlgorithmImports import *

# ============ CONFIGURATION ============
START_DATE = (2020, 1, 1)
END_DATE = (2026, 6, 30)
INITIAL_CASH = 100000

MIN_PRICE = 10.0
MIN_AVG_VOLUME = 10000000

MOMENTUM_PERIODS = {'1m': 21, '3m': 63, '6m': 126, '12m': 252}
MOMENTUM_WEIGHTS = {'1m': 0.10, '3m': 0.30, '6m': 0.30, '12m': 0.30}

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
USE_TREND_FILTER = True
TREND_MA_PERIOD = 200

USE_SECTOR_ROTATION = True
SECTOR_ETFS = {
    'Technology': 'XLK', 'Healthcare': 'XLV', 'Financial': 'XLF',
    'Energy': 'XLE', 'Industrial': 'XLI', 'Consumer': 'XLY',
    'Consumer_Defensive': 'XLP', 'Communication': 'XLC',
    'Utilities': 'XLU', 'RealEstate': 'XLRE',
}
SECTOR_MOMENTUM_PERIOD = 63
TOP_N_SECTORS = 5

TOP_N_STOCKS = 20
POSITION_WEIGHT_METHOD = 'equal'
MAX_SECTOR_PCT = 0.30

VIX_LEVELS = {
    'normal': (0, 20), 'elevated': (20, 25), 'high': (25, 30),
    'extreme': (30, 35), 'panic': (35, 100),
}
VIX_POSITION_PCT = {
    'normal': 1.0, 'elevated': 0.8, 'high': 0.6,
    'extreme': 0.4, 'panic': 0.2,
}

STOP_LOSS_PCT = 0.08
TAKE_PROFIT_PCT = 0.20
TAKE_PROFIT_PARTIAL = 0.5
USE_TRAILING_STOP = True
TRAILING_STOP_PCT = 0.10

USE_MARKET_TREND_FILTER = True
MARKET_TREND_SYMBOL = 'SPY'
MARKET_TREND_MA = 200
MAX_DRAWDOWN_PCT = 0.15

REBALANCE_FREQUENCY = 'weekly'
REBALANCE_DAY = 0
REBALANCE_MINUTES_AFTER_OPEN = 35
CASH_BUFFER_PCT = 0.05
MONITOR_TIME_MINUTES_AFTER_OPEN = 30

SECTOR_MAP = {
    'AAPL': 'Technology', 'MSFT': 'Technology', 'GOOGL': 'Technology',
    'AMZN': 'Technology', 'META': 'Technology', 'NVDA': 'Technology',
    'TSLA': 'Consumer', 'JPM': 'Financial', 'V': 'Financial',
    'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'XOM': 'Energy',
    'CVX': 'Energy', 'PG': 'Consumer_Defensive', 'KO': 'Consumer_Defensive',
    'HD': 'Consumer', 'WMT': 'Consumer_Defensive', 'BAC': 'Financial',
    'MA': 'Financial', 'PFE': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PEP': 'Consumer_Defensive', 'COST': 'Consumer',
    'TMO': 'Healthcare', 'AVGO': 'Technology', 'DIS': 'Communication',
    'ADBE': 'Technology', 'CRM': 'Technology', 'ACN': 'Technology',
    'VZ': 'Communication', 'NFLX': 'Communication', 'CMCSA': 'Communication',
    'INTC': 'Technology', 'AMD': 'Technology', 'PYPL': 'Financial',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'ABT': 'Healthcare',
    'C': 'Financial', 'GS': 'Financial', 'WFC': 'Financial',
    'MS': 'Financial', 'BA': 'Industrial', 'GE': 'Industrial',
    'HON': 'Industrial', 'RTX': 'Industrial', 'UPS': 'Industrial',
    'CAT': 'Industrial', 'LMT': 'Industrial', 'DE': 'Industrial',
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities',
    'D': 'Utilities', 'AEP': 'Utilities', 'EXC': 'Utilities',
    'OXY': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'MPC': 'Energy', 'VLO': 'Energy',
    'PSX': 'Energy', 'KMI': 'Energy', 'WMB': 'Energy',
    'PLD': 'RealEstate', 'AMT': 'RealEstate', 'CCI': 'RealEstate',
    'EQIX': 'RealEstate', 'O': 'RealEstate', 'SPG': 'RealEstate',
}


class MomentumStrategy(QCAlgorithm):
    """Modular Momentum Strategy - All modules integrated."""
    
    def Initialize(self):
        self.SetStartDate(*START_DATE)
        self.SetEndDate(*END_DATE)
        self.SetCash(INITIAL_CASH)
        self.SetBrokerageModel(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        self.Settings.DailyPreciseEndTime = False
        self.Settings.FreePortfolioValuePercentage = CASH_BUFFER_PCT
        
        # Universe state
        self.universe_symbols = {}
        self.universe_sectors = {}
        self.liquid_tickers = set()
        
        # Momentum state
        self.rsi_indicators = {}
        self.ma_indicators = {}
        self.momentum_scores = {}
        
        # Sector state
        self.sector_symbols = {}
        self.sector_momentum = {}
        self.top_sectors = []
        
        # Portfolio state
        self.target_positions = {}
        
        # Risk state
        self.vix_symbol = None
        self.market_symbol = None
        self.market_ma = None
        self.position_highs = {}
        self.position_entry = {}
        self.partial_sold = {}
        self.high_water_mark = 0
        self.drawdown_triggered = False
        
        # Monitor state
        self.performance_history = []
        
        # Initialize
        self._init_universe()
        self._init_sectors()
        self._init_risk()
        self._init_schedule()
        
        max_period = max(MOMENTUM_PERIODS.values()) + TREND_MA_PERIOD + 20
        self.SetWarmUp(max_period)
        self.Log("[Strategy] Initialized. Warmup: %d days" % max_period)
    
    # ============ UNIVERSE ============
    def _init_universe(self, tickers=None):
        if tickers is None:
            tickers = list(SECTOR_MAP.keys())
        
        self.Log("[Universe] Initializing with %d tickers" % len(tickers))
        for ticker in tickers:
            try:
                symbol = self.AddEquity(ticker, Resolution.DAILY).Symbol
                self.universe_symbols[ticker] = symbol
                self.universe_sectors[ticker] = SECTOR_MAP.get(ticker, 'Unknown')
            except Exception as e:
                self.Log("[Universe] ERROR adding %s: %s" % (ticker, str(e)))
        
        self.Log("[Universe] Loaded %d symbols" % len(self.universe_symbols))
    
    def _update_liquidity(self):
        self.liquid_tickers = set()
        for ticker, symbol in self.universe_symbols.items():
            try:
                security = self.Securities[symbol]
                if security.Price < MIN_PRICE:
                    continue
                history = self.History(symbol, 20, Resolution.DAILY)
                if not history.empty and len(history) >= 10:
                    if history['volume'].mean() >= MIN_AVG_VOLUME:
                        self.liquid_tickers.add(ticker)
            except:
                pass
        self.Log("[Universe] Liquid stocks: %d/%d" % (len(self.liquid_tickers), len(self.universe_symbols)))
    
    # ============ SECTOR ============
    def _init_sectors(self):
        if not USE_SECTOR_ROTATION:
            return
        for sector, etf in SECTOR_ETFS.items():
            try:
                self.sector_symbols[sector] = self.AddEquity(etf, Resolution.DAILY).Symbol
            except Exception as e:
                self.Log("[Sector] ERROR adding %s: %s" % (etf, str(e)))
    
    def _update_sector_momentum(self):
        if not USE_SECTOR_ROTATION:
            return
        self.sector_momentum = {}
        for sector, symbol in self.sector_symbols.items():
            try:
                history = self.History(symbol, SECTOR_MOMENTUM_PERIOD + 5, Resolution.DAILY)
                if not history.empty and len(history) >= SECTOR_MOMENTUM_PERIOD:
                    history = history.sort_index()
                    closes = history['close'].values
                    if len(closes) >= 2:
                        self.sector_momentum[sector] = round((closes[-1] / closes[0] - 1) * 100, 2)
            except:
                pass
        
        sorted_sectors = sorted(self.sector_momentum.items(), key=lambda x: x[1], reverse=True)
        self.top_sectors = [s[0] for s in sorted_sectors[:TOP_N_SECTORS]]
        self.Log("[Sector] Top sectors: %s" % str(self.top_sectors))
    
    # ============ RISK ============
    def _init_risk(self):
        try:
            self.vix_symbol = self.AddIndex('VIX', Resolution.DAILY).Symbol
        except:
            self.vix_symbol = self.AddEquity('VIXY', Resolution.DAILY).Symbol
        
        if USE_MARKET_TREND_FILTER:
            self.market_symbol = self.AddEquity(MARKET_TREND_SYMBOL, Resolution.DAILY).Symbol
            self.market_ma = self.SMA(self.market_symbol, MARKET_TREND_MA)
    
    def _get_vix_limit(self):
        if self.vix_symbol is None:
            return 1.0
        try:
            vix = self.Securities[self.vix_symbol].Price
            if vix <= 0:
                return 1.0
            for level, (low, high) in VIX_LEVELS.items():
                if low <= vix < high:
                    return VIX_POSITION_PCT[level]
            return VIX_POSITION_PCT['panic']
        except:
            return 1.0
    
    def _check_market_trend(self):
        if not USE_MARKET_TREND_FILTER or self.market_symbol is None:
            return True
        try:
            price = self.Securities[self.market_symbol].Price
            ma = self.market_ma.Current.Value if self.market_ma and self.market_ma.IsReady else 0
            return price > ma if ma > 0 else True
        except:
            return True
    
    def _check_drawdown(self):
        current = self.Portfolio.TotalPortfolioValue
        if current > self.high_water_mark:
            self.high_water_mark = current
            self.drawdown_triggered = False
        if self.high_water_mark > 0:
            dd = (self.high_water_mark - current) / self.high_water_mark
            if dd > MAX_DRAWDOWN_PCT:
                if not self.drawdown_triggered:
                    self.drawdown_triggered = True
                    self.Log("[Risk] DRAWDOWN PROTECTION: %.2f%%" % (dd * 100))
                return True
        else:
            self.high_water_mark = current
        return False
    
    def _check_stop_loss(self, ticker, symbol):
        if not self.Portfolio[symbol].Invested:
            return None
        current_price = self.Securities[symbol].Close
        entry_price = self.position_entry.get(ticker)
        if entry_price is None or entry_price <= 0:
            return None
        pnl = (current_price - entry_price) / entry_price
        
        if ticker not in self.position_highs or current_price > self.position_highs[ticker]:
            self.position_highs[ticker] = current_price
        
        if pnl <= -STOP_LOSS_PCT:
            self._clear_tracking(ticker)
            return 'stop_loss'
        if pnl >= TAKE_PROFIT_PCT and not self.partial_sold.get(ticker, False):
            self.partial_sold[ticker] = True
            return 'take_profit_partial'
        if USE_TRAILING_STOP and ticker in self.position_highs:
            high = self.position_highs[ticker]
            if current_price < high * (1 - TRAILING_STOP_PCT):
                self._clear_tracking(ticker)
                return 'trailing_stop'
        return None
    
    def _clear_tracking(self, ticker):
        self.position_entry.pop(ticker, None)
        self.position_highs.pop(ticker, None)
        self.partial_sold.pop(ticker, None)
    
    # ============ MOMENTUM ============
    def _calc_momentum(self, tickers):
        self.momentum_scores = {}
        max_period = max(MOMENTUM_PERIODS.values()) + 5
        
        for ticker in tickers:
            symbol = self.universe_symbols.get(ticker)
            if symbol is None:
                continue
            
            # Initialize indicators if needed
            if symbol not in self.rsi_indicators:
                try:
                    self.rsi_indicators[symbol] = self.RSI(symbol, RSI_PERIOD)
                    self.ma_indicators[symbol] = self.SMA(symbol, TREND_MA_PERIOD)
                except:
                    pass
            
            try:
                history = self.History(symbol, max_period, Resolution.DAILY)
                if history.empty or len(history) < max(MOMENTUM_PERIODS.values()):
                    continue
                history = history.sort_index()
                closes = history['close'].values
                if len(closes) < 2:
                    continue
                
                current_price = closes[-1]
                momentum_scores = {}
                for period_name, period_days in MOMENTUM_PERIODS.items():
                    if len(closes) > period_days:
                        past_price = closes[-period_days - 1] if len(closes) > period_days else closes[0]
                        ret = (current_price / past_price - 1) * 100
                        weight = MOMENTUM_WEIGHTS[period_name]
                        momentum_scores[period_name] = ret * weight
                
                if not momentum_scores:
                    continue
                
                base_score = sum(momentum_scores.values())
                
                rsi_score = 0
                if symbol in self.rsi_indicators:
                    rsi = self.rsi_indicators[symbol].Current.Value
                    if rsi > 70: rsi_score = -5
                    elif rsi < 30: rsi_score = +5
                
                trend_score = 0
                if USE_TREND_FILTER and symbol in self.ma_indicators:
                    ma = self.ma_indicators[symbol].Current.Value
                    if ma > 0:
                        if current_price > ma: trend_score = +3
                        else: trend_score = -5
                
                self.momentum_scores[ticker] = round(base_score + rsi_score + trend_score, 3)
            except:
                pass
    
    def _get_top_tickers(self, tickers, n):
        scored = [(t, self.momentum_scores.get(t, -999)) for t in tickers if t in self.momentum_scores]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]
    
    # ============ PORTFOLIO ============
    def _calc_weights(self, selected_tickers):
        if not selected_tickers:
            return {}
        n = len(selected_tickers)
        weight = 1.0 / n if n > 0 else 0
        weights = {ticker: weight for ticker, _ in selected_tickers}
        
        # Apply sector limits
        sector_weights = {}
        for ticker, w in weights.items():
            sector = self.universe_sectors.get(ticker, 'Unknown')
            if sector not in sector_weights:
                sector_weights[sector] = []
            sector_weights[sector].append((ticker, w))
        
        adjusted = {}
        for sector, tickers_weights in sector_weights.items():
            sector_total = sum(w for _, w in tickers_weights)
            if sector_total > MAX_SECTOR_PCT:
                scale = MAX_SECTOR_PCT / sector_total
                for ticker, w in tickers_weights:
                    adjusted[ticker] = w * scale
            else:
                for ticker, w in tickers_weights:
                    adjusted[ticker] = w
        
        # Normalize
        total = sum(adjusted.values())
        if total > 0:
            scale = (1.0 - CASH_BUFFER_PCT) / total
            adjusted = {t: w * scale for t, w in adjusted.items()}
        
        return adjusted
    
    # ============ EXECUTION ============
    def _execute_rebalance(self, target_weights):
        risk_mult = min(self._get_vix_limit(), 1.0 if self._check_market_trend() else 0.5, 0.0 if self._check_drawdown() else 1.0)
        adjusted_weights = {t: w * risk_mult for t, w in target_weights.items()}
        
        self.Log("[Execution] Rebalancing %d positions (risk mult: %.2f)" % (len(adjusted_weights), risk_mult))
        
        # Sell removed positions
        for ticker, symbol in self.universe_symbols.items():
            if self.Portfolio[symbol].Invested and ticker not in adjusted_weights:
                self.Liquidate(symbol)
                self.Log("[Execution] SELL %s - removed" % ticker)
                self._clear_tracking(ticker)
        
        # Adjust positions
        for ticker, target_weight in adjusted_weights.items():
            symbol = self.universe_symbols.get(ticker)
            if symbol is None:
                continue
            try:
                current_weight = self._get_current_weight(symbol)
                if abs(current_weight - target_weight) < 0.01:
                    continue
                self.SetHoldings(symbol, target_weight)
                self.Log("[Execution] SET %s to %.2f%%" % (ticker, target_weight * 100))
                if current_weight == 0 and target_weight > 0:
                    self.position_entry[ticker] = self.Securities[symbol].Close
                    self.position_highs[ticker] = self.Securities[symbol].Close
                    self.partial_sold[ticker] = False
            except Exception as e:
                self.Log("[Execution] ERROR %s: %s" % (ticker, str(e)))
    
    def _get_current_weight(self, symbol):
        if not self.Portfolio[symbol].Invested:
            return 0.0
        position_value = self.Portfolio[symbol].HoldingsValue
        total_value = self.Portfolio.TotalPortfolioValue
        return position_value / total_value if total_value > 0 else 0.0
    
    # ============ SCHEDULE ============
    def _init_schedule(self):
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_name = day_names[REBALANCE_DAY]
        
        self.Schedule.On(
            self.DateRules.WeekStart(day_name),
            self.TimeRules.AfterMarketOpen('SPY', REBALANCE_MINUTES_AFTER_OPEN),
            self.WeeklyRebalance
        )
        self.Log("[Execution] Weekly rebalance: %s %dmin after open" % (day_name, REBALANCE_MINUTES_AFTER_OPEN))
        
        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.AfterMarketOpen('SPY', MONITOR_TIME_MINUTES_AFTER_OPEN),
            self.DailyMonitor
        )
        self.Log("[Monitor] Daily monitoring: %dmin after open" % MONITOR_TIME_MINUTES_AFTER_OPEN)
    
    # ============ REBALANCE ============
    def WeeklyRebalance(self):
        self.Log("\n" + "="*60)
        self.Log("[Rebalance] Starting: %s" % str(self.Time.date()))
        self.Log("="*60)
        
        if self._check_drawdown():
            self.Log("[Rebalance] SKIPPED - Drawdown protection")
            return
        
        self._update_liquidity()
        self._update_sector_momentum()
        
        liquid_tickers = list(self.liquid_tickers)
        if len(liquid_tickers) < TOP_N_STOCKS * 2:
            self.Log("[Rebalance] WARNING - Only %d liquid stocks" % len(liquid_tickers))
        
        self._calc_momentum(liquid_tickers)
        top_tickers = self._get_top_tickers(liquid_tickers, n=TOP_N_STOCKS * 2)
        
        self.Log("[Rebalance] Top momentum: %s" % str([t[0] for t in top_tickers[:10]]))
        
        # Sector filter
        if USE_SECTOR_ROTATION and self.top_sectors:
            filtered = [t for t in top_tickers if self.universe_sectors.get(t[0], 'Unknown') in self.top_sectors]
            top_tickers = filtered[:TOP_N_STOCKS]
        else:
            top_tickers = top_tickers[:TOP_N_STOCKS]
        
        self.Log("[Rebalance] Final selection: %s" % str([t[0] for t in top_tickers]))
        
        target_weights = self._calc_weights(top_tickers)
        self._execute_rebalance(target_weights)
        
        self.Log("[Rebalance] Complete")
    
    # ============ DAILY MONITOR ============
    def DailyMonitor(self):
        equity = self.Portfolio.TotalPortfolioValue
        cash = self.Portfolio.Cash
        self.Log("\n[Monitor] %s | Equity: $%d | Cash: $%d" % (str(self.Time.date()), int(equity), int(cash)))
        
        # Check stops
        for ticker in list(self.liquid_tickers):
            symbol = self.universe_symbols.get(ticker)
            if symbol is None or not self.Portfolio[symbol].Invested:
                continue
            
            exit_signal = self._check_stop_loss(ticker, symbol)
            if exit_signal == 'stop_loss':
                self.Liquidate(symbol)
                self.Log("[Monitor] STOP LOSS %s" % ticker)
            elif exit_signal == 'take_profit_partial':
                holdings = self.Portfolio[symbol].Quantity
                sell_qty = holdings * TAKE_PROFIT_PARTIAL
                if sell_qty > 0:
                    self.MarketOrder(symbol, -sell_qty)
                    self.Log("[Monitor] TAKE PROFIT %s %.0f%%" % (ticker, TAKE_PROFIT_PARTIAL * 100))
            elif exit_signal == 'trailing_stop':
                self.Liquidate(symbol)
                self.Log("[Monitor] TRAILING STOP %s" % ticker)
        
        self.performance_history.append({'date': self.Time.date(), 'equity': equity})
    
    def OnData(self, data):
        pass
    
    def OnEndOfAlgorithm(self):
        self.Log("\n" + "="*60)
        self.Log("[Strategy] Complete")
        if self.performance_history:
            start = self.performance_history[0]['equity']
            current = self.performance_history[-1]['equity']
            ret = (current / start - 1) * 100 if start > 0 else 0
            self.Log("Total Return: %.2f%% (%d days)" % (ret, len(self.performance_history)))
        self.Log("="*60)
