from AlgorithmImports import *
from typing import Dict, List, Optional
from collections import defaultdict


class CombinedStrategy(QCAlgorithm):
    """
    組合策略：AdaptiveMomentum + VIX恐慌反轉
    
    策略1: 行業動量選股（核心持倉，70%資金）
    策略2: VIX恐慌反轉（擇時交易，30%資金）
    
    當VIX恐慌信號觸發時，動量策略減倉避險，VIX策略抄底。
    """

    def initialize(self):
        # ========== BASIC CONFIGURATION ==========
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2026, 7, 10)
        self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        self.settings.daily_precise_end_time = False
        self.settings.free_portfolio_value_percentage = 0.05

        # ========== STRATEGY ALLOCATION ==========
        self.momentum_alloc = 0.70  # 動量策略資金占比
        self.vix_alloc = 0.30       # VIX策略資金占比
        self.vix_override = False   # VIX恐慌時是否接管動量倉位

        # ========== MOMENTUM PARAMETERS ==========
        self._init_momentum_params()
        
        # ========== VIX PARAMETERS ==========
        self._init_vix_params()

        # ========== UNIVERSE & SYMBOLS ==========
        self._init_momentum_universe()
        self._init_vix_symbols()

        # ========== STATE ==========
        self.position_entry_dates = {}
        self.vix_hold_long = False
        self.vix_entry_date = None
        self.vix_entry_prices = {}

    # ---------- MOMENTUM INIT ----------
    def _init_momentum_params(self):
        self.lookback_periods = {'1d': 1, '1w': 5, '2w': 10, '1m': 21, '3m': 63, '6m': 126}
        self.base_weights = {'1d': 0.1, '1w': 0.5, '2w': 1.0, '1m': 1.0, '3m': 0.7, '6m': 0.5}
        self.current_weights = self.base_weights.copy()
        
        self.rsi_overbought = 65
        self.rsi_oversold = 35
        self.rsi_adjustment_factor = 0.4
        self.rsi_period = 14
        
        self._initialize_vix()
        self.vix_pause_level = 30.0
        self.vix_boost_level = 18.0
        
        self.max_position_pct = 0.15
        self.min_position_pct = 0.0
        self.max_stocks = 10
        self.min_score = 0.0
        self.min_hold_days = 3
        self.max_total_exposure = 0.80
        self.min_total_exposure = 0.30
        self.current_total_exposure = self.min_total_exposure
        
        self.buy_candidates = []
        self.sell_candidates = []
        self.symbol_scores = {}
        self.symbol_rsi = {}
        self.vix_value = 0.0
        self.vix_direction = "normal"
        self.last_rebalance_date = None
        self.rsi_threshold = 50

    def _initialize_vix(self):
        self.vix_ticker = "VIX"
        vix_symbol = self.add_data(CBOE, self.vix_ticker, Resolution.DAILY)
        self.vix_symbol = vix_symbol.symbol
        self.vix_history = None

    def _init_momentum_universe(self):
        self._load_strategy_config()
        self.us_tickers = list(self.sector_map.keys()) if hasattr(self, 'sector_map') else []
        self.tickers_initialized = False
        self.set_warm_up(130)
        self.schedule.on(self.date_rules.week_start("SPY"), self.time_rules.after_market_open("SPY", 30), self._rebalance)
        self.schedule.on(self.date_rules.every_day("SPY"), self.time_rules.after_market_open("SPY", 30), self._check_stops_and_trailing)

    def _load_strategy_config(self):
        try:
            import strategy_config
            self.sector_map = strategy_config.strategy_config.get("sector_map", {})
            self.lookback_periods = strategy_config.strategy_config.get("lookback_periods", self.lookback_periods)
            self.base_weights = strategy_config.strategy_config.get("base_weights", self.base_weights)
        except:
            self.sector_map = {}

    # ---------- VIX INIT ----------
    def _init_vix_params(self):
        self.vix_thresh = 20
        self.vix_rsi_period = 14
        self.vix_rsi_oversold = 30
        self.vix_rsi_overbought = 70
        self.vix_take_profit = 0.02
        self.vix_stop_loss = -0.02
        self.vix_max_hold_days = 5

    def _init_vix_symbols(self):
        self.vix_spx = self.add_equity("SPY", Resolution.DAILY).symbol
        self.vix_dji = self.add_equity("DIA", Resolution.DAILY).symbol
        self.vix_ndx = self.add_equity("QQQ", Resolution.DAILY).symbol
        self.vix_vxx = self.add_equity("VXX", Resolution.DAILY).symbol
        self.vix_symbols = {"SPX": self.vix_spx, "DJI": self.vix_dji, "NDX": self.vix_ndx}
        self.vix_rsi_indicator = self.rsi(self.vix_spx, self.vix_rsi_period, MovingAverageType.SIMPLE)

    # ---------- ON DATA ----------
    def on_data(self, data):
        self._update_momentum_state(data)
        self._run_vix_strategy(data)

    def _update_momentum_state(self, data):
        if not self.tickers_initialized:
            return
        self._update_vix_state()
        self._update_rsi_threshold()
        for ticker in self.us_tickers:
            symbol = self.symbol(ticker)
            if symbol in data.bars:
                self.symbol_rsi[symbol] = self.rsi(symbol, self.rsi_period).current.value
        self.vix_value = self._get_vix_value()
        self.vix_direction = self._get_vix_direction(self.vix_value)
        self._update_weights_from_vix()

    def _update_vix_state(self):
        if self.vix_history is None or not self.vix_history:
            self.vix_history = self.history(self.vix_symbol, 20, Resolution.DAILY)
        if self.vix_history.empty:
            return
        latest = self.vix_history.iloc[-1]
        if isinstance(latest, pd.Series):
            self.vix_value = latest['close'] if 'close' in latest else latest.iloc[-1]
        else:
            self.vix_value = latest
        self.vix_history = self.vix_history.iloc[-1:]

    def _get_vix_value(self):
        return self.vix_value

    def _get_vix_direction(self, vix_value):
        if vix_value > self.vix_pause_level:
            return "high"
        elif vix_value < self.vix_boost_level:
            return "low"
        return "normal"

    def _update_rsi_threshold(self):
        if self.vix_value > self.vix_pause_level:
            self.rsi_threshold = max(40, 50 - (self.vix_value - self.vix_pause_level) * 0.5)
        elif self.vix_value < self.vix_boost_level:
            self.rsi_threshold = min(60, 50 + (self.vix_boost_level - self.vix_value) * 0.3)
        else:
            self.rsi_threshold = 50

    def _update_weights_from_vix(self):
        if self.vix_direction == "high":
            for period in self.current_weights:
                self.current_weights[period] = self.base_weights[period] * 0.5
        elif self.vix_direction == "low":
            for period in self.current_weights:
                self.current_weights[period] = self.base_weights[period] * 1.2
        else:
            self.current_weights = self.base_weights.copy()

    # ---------- VIX STRATEGY ----------
    def _run_vix_strategy(self, data):
        if not data.contains_key(self.vix_spx):
            return
        
        # 檢查止盈止損
        if self.vix_hold_long and self.vix_entry_date:
            hold_days = (self.time.date() - self.vix_entry_date).days
            for sym_name, sym in self.vix_symbols.items():
                if not self.portfolio[sym].invested:
                    continue
                entry_price = self.vix_entry_prices.get(sym_name, 0)
                if entry_price <= 0:
                    continue
                current_price = self.securities[sym].close
                pnl = (current_price - entry_price) / entry_price
                if pnl >= self.vix_take_profit or pnl <= self.vix_stop_loss or hold_days >= self.vix_max_hold_days:
                    self.liquidate(sym)
            if not any(self.portfolio[s].invested for s in self.vix_symbols.values()):
                self.vix_hold_long = False
                self.vix_entry_date = None
                self.vix_entry_prices = {}

        vix_sec = self.securities[self.vix_vxx]
        vix_high = vix_sec.high
        vix_close = vix_sec.close
        
        if vix_high <= self.vix_thresh:
            return
        
        rsi_val = self.vix_rsi_indicator.current.value if self.vix_rsi_indicator.is_ready else 50
        rsi_group = "Oversold" if rsi_val < self.vix_rsi_oversold else ("Overbought" if rsi_val > self.vix_rsi_overbought else "Neutral")
        vix_type = "A" if vix_close >= self.vix_thresh else "B"

        # VIX恐慌信號：接管動量倉位
        if rsi_group == "Oversold":
            # 減倉動量策略
            self._reduce_momentum_positions(0.5)
            # 開倉VIX抄底
            if not any(self.portfolio[s].invested for s in self.vix_symbols.values()):
                weight = (0.5 if vix_type == "A" else 0.25) / len(self.vix_symbols)
                for sym_name, sym in self.vix_symbols.items():
                    self.set_holdings(sym, weight * self.vix_alloc / self.momentum_alloc)
                    self.vix_entry_prices[sym_name] = self.securities[sym].close
                self.vix_hold_long = True
                self.vix_entry_date = self.time.date()
            return

        if rsi_group == "Overbought":
            # 平倉VIX，恢復動量
            for sym in self.vix_symbols.values():
                self.liquidate(sym)
            self.vix_hold_long = False
            self.vix_entry_prices = {}
            self.vix_entry_date = None
            # 恢復動量倉位
            self._restore_momentum_positions()
            return

    def _reduce_momentum_positions(self, reduction_pct):
        for symbol in self.portfolio.keys():
            if symbol in self.vix_symbols.values():
                continue
            if self.portfolio[symbol].invested:
                current_holdings = self.portfolio[symbol].holdings_quantity
                target = current_holdings * (1 - reduction_pct)
                self.set_holdings(symbol, target / self.portfolio.total_portfolio_value)

    def _restore_momentum_positions(self):
        self._rebalance()

    # ---------- MOMENTUM REBALANCE ----------
    def _rebalance(self):
        if self.vix_hold_long:
            return
        self._score_and_rank()
        self._execute_sells()
        self._execute_buys()
        self.last_rebalance_date = self.time.date()

    def _score_and_rank(self):
        # ... (same as v3.2)
        pass

    def _execute_sells(self):
        # ... (same as v3.2)
        pass

    def _execute_buys(self):
        # ... (same as v3.2)
        pass

    def _check_stops_and_trailing(self):
        # ... (same as v3.2)
        pass

    def on_end_of_algorithm(self):
        self.log("組合策略回測完成")
