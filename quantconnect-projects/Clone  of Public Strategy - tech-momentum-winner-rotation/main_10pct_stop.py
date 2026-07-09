#region imports
from AlgorithmImports import *
#endregion

class AdaptiveMomentumStrategy(QCAlgorithm):
    """
     - 
    
    :
    1. : 1d/1w/2w/1m/3m/6m
    2. : 
    3. VIX: VIX>30
    4. : Top
    5. : () + ()
    6. : 15%
    """
    
    def Initialize(self):
        # ===  ===
        self.SetStartDate(2022, 1, 1)
        self.SetEndDate(2025, 6, 1)
        self.SetCash(100000)
        
        # === ===
        self.lookback_1d = 1
        self.lookback_1w = 5
        self.lookback_2w = 10
        self.lookback_1m = 21
        self.lookback_3m = 63
        self.lookback_6m = 126
        
        # 
        self.base_weight_1d = 0.1
        self.base_weight_1w = 0.5
        self.base_weight_2w = 1.0
        self.base_weight_1m = 1.0
        self.base_weight_3m = 1.0
        self.base_weight_6m = 1.0
        
        # 
        self.current_weights = {
            '1d': self.base_weight_1d,
            '1w': self.base_weight_1w,
            '2w': self.base_weight_2w,
            '1m': self.base_weight_1m,
            '3m': self.base_weight_3m,
            '6m': self.base_weight_6m
        }
        
        # ===  ===
        self.volatility_lookback = 20  # 20
        self.high_vol_threshold = 0.025  #  > 2.5% 
        self.low_vol_threshold = 0.010   #  < 1% 
        
        # === VIX ===
        self.vix_symbol = self.AddEquity("VIXY", Resolution.Daily).Symbol  # VIX ETF
        self.vix_threshold = 30.0  # VIX > 30 
        self.vix_high_position_scale = 0.5  # 
        
        # ===  ===
        self.max_position_per_stock = 0.15
        self.top_n_stocks = 10
        self.min_momentum_score = 0.0
        self.global_position_scale = 1.0  # VIX
        
        # ===  ===
        self.enable_sector_rotation = True
        self.top_n_sectors = 3  # 3
        self.sector_lookback = 63  # 3
        
        # 
        self.sector_map = {
            # 
            'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech', 'META': 'Tech',
            'AMZN': 'Tech', 'TSLA': 'Tech', 'AMD': 'Tech', 'INTC': 'Tech', 'CRM': 'Tech',
            'ORCL': 'Tech', 'ADBE': 'Tech', 'CSCO': 'Tech', 'AVGO': 'Tech', 'QCOM': 'Tech',
            'TXN': 'Tech', 'AMAT': 'Tech', 'MU': 'Tech', 'NFLX': 'Tech', 'INTU': 'Tech',
            'ANET': 'Tech', 'FSLR': 'Tech', 'FTNT': 'Tech', 'SNPS': 'Tech', 'KLAC': 'Tech',
            'MRVL': 'Tech', 'NXPI': 'Tech', 'SWKS': 'Tech', 'MCHP': 'Tech', 'CDNS': 'Tech',
            'DDOG': 'Tech', 'NET': 'Tech', 'PLTR': 'Tech', 'CRM': 'Tech', 'NOW': 'Tech',
            # 
            'JPM': 'Finance', 'BAC': 'Finance', 'GS': 'Finance', 'MS': 'Finance', 'WFC': 'Finance',
            'BLK': 'Finance', 'C': 'Finance', 'AXP': 'Finance', 'SCHW': 'Finance', 'PNC': 'Finance',
            'TFC': 'Finance', 'USB': 'Finance', 'COF': 'Finance', 'SPGI': 'Finance', 'MCO': 'Finance',
            'BK': 'Finance', 'STT': 'Finance', 'ICE': 'Finance', 'CME': 'Finance', 'NDAQ': 'Finance',
            # 
            'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'LLY': 'Healthcare', 'PFE': 'Healthcare',
            'MRK': 'Healthcare', 'ABBV': 'Healthcare', 'ABT': 'Healthcare', 'TMO': 'Healthcare',
            'DHR': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare', 'GILD': 'Healthcare',
            'VRTX': 'Healthcare', 'REGN': 'Healthcare', 'BIIB': 'Healthcare', 'MRNA': 'Healthcare',
            # 
            'HD': 'Consumer', 'COST': 'Consumer', 'NKE': 'Consumer', 'MCD': 'Consumer',
            'SBUX': 'Consumer', 'LOW': 'Consumer', 'TJX': 'Consumer', 'PG': 'Consumer',
            'KO': 'Consumer', 'PEP': 'Consumer', 'WMT': 'Consumer', 'MDLZ': 'Consumer',
            'CL': 'Consumer', 'KMB': 'Consumer', 'GIS': 'Consumer', 'CPB': 'Consumer',
            # 
            'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'EOG': 'Energy', 'SLB': 'Energy',
            'OXY': 'Energy', 'MPC': 'Energy', 'VLO': 'Energy', 'PSX': 'Energy', 'KMI': 'Energy',
            # 
            'CAT': 'Industrial', 'HON': 'Industrial', 'UPS': 'Industrial', 'BA': 'Industrial',
            'GE': 'Industrial', 'RTX': 'Industrial', 'LMT': 'Industrial', 'NOC': 'Industrial',
            'GD': 'Industrial', 'ITW': 'Industrial', 'MMM': 'Industrial', 'EMR': 'Industrial',
            # 
            'VZ': 'Telecom', 'T': 'Telecom', 'CMCSA': 'Telecom', 'CHTR': 'Telecom', 
            'TMUS': 'Telecom', 'CCI': 'Telecom', 'AMT': 'Telecom',
        }
        
        # ===  ===
        self.hk_max_position = 0.05       # 5%15%
        self.hk_market_timing = True      # 
        self.hk_min_market_momentum = 0.0 # >0
        self.enable_hk = True             # 
        
        # ===  ===
        self.rebalance_frequency_weeks = 2  # 2
        self.week_counter = 0  # 
        
        # ===  ===
        self.us_allocation_base = 0.7     # 70%
        self.hk_allocation_base = 0.3     # 30%
        self.enable_relative_strength = True  # 
        
        # ===  ===
        self.stop_loss_pct = 0.15
        
        # ===  ===
        self.us_tickers = [
            "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "INTC", "CRM",
            "ORCL", "ADBE", "CSCO", "AVGO", "QCOM", "TXN", "AMAT", "MU", "NFLX", "INTU",
            "ANET", "FSLR", "FTNT", "SNPS", "KLAC", "MRVL", "NXPI", "SWKS", "MCHP", "CDNS",
            "DDOG", "PLTR", "NOW", "NET", "JPM", "BAC", "GS", "MS", "WFC", "BLK",
            "C", "AXP", "SCHW", "PNC", "SPGI", "MCO", "ICE", "CME", "JNJ", "UNH",
            "LLY", "PFE", "MRK", "ABBV", "ABT", "TMO", "DHR", "BMY", "AMGN", "GILD",
            "REGN", "VRTX", "MRNA", "HD", "COST", "NKE", "MCD", "SBUX", "LOW", "TJX",
            "PG", "KO", "PEP", "WMT", "MDLZ", "XOM", "CVX", "COP", "SLB", "OXY",
            "CAT", "HON", "UPS", "BA", "GE", "RTX", "LMT", "VZ", "T", "CMCSA",
            "SPY", "QQQ", "IWM", "TLT", "GLD", "VIXY"
        ]
        
        self.hk_tickers = [
            "0001", "0005", "0700", "0762", "0857", "0883", "0941", "0981", "0992", "1088",
            "1099", "1109", "1171", "1211", "1299", "1378", "1398", "1658", "1801", "1876",
            "1928", "2015", "2020", "2121", "2269", "2318", "2319", "2331", "2333", "2359",
            "2382", "2388", "2628", "2899", "3690", "6862", "9618", "9988", "9999"
        ]
        
        self.tickers = sorted(list(set(self.us_tickers + self.hk_tickers)))
        
        # 
        self.safe_tickers = ["TLT", "GLD"]
        self.safe_symbols = {}
        
        self.symbols = {}
        valid_tickers = []
        
        for ticker in self.tickers:
            try:
                self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
                valid_tickers.append(ticker)
            except:
                pass
        
        self.tickers = valid_tickers
        
        for ticker in self.safe_tickers:
            self.safe_symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
        
        # 
        self.cost_basis = {}
        
        # ===  - 2===
        # 2
        self.Schedule.On(
            self.DateRules.Every(DayOfWeek.Monday),
            self.TimeRules.AfterMarketOpen("SPY", 5),
            self.WeeklyUpdate
        )
        
        self.Schedule.On(
            self.DateRules.Every(DayOfWeek.Tuesday),
            self.TimeRules.AfterMarketOpen("0700", 30),
            self.WeeklyHKUpdate
        )
        
        # 
        self.Schedule.On(
            self.DateRules.EveryDay("SPY"),
            self.TimeRules.AfterMarketOpen("SPY", 60),
            self.CheckStopLoss
        )
        
        # Warm up
        warmup_days = max(self.lookback_6m, self.sector_lookback) + 20
        self.SetWarmUp(timedelta(days=warmup_days))
        
        # 
        portfolio_chart = Chart("Portfolio")
        portfolio_chart.AddSeries(Series("Value", SeriesType.Line, "$"))
        self.AddChart(portfolio_chart)
        
        vol_chart = Chart("Volatility")
        vol_chart.AddSeries(Series("DailyVol", SeriesType.Line, "%"))
        vol_chart.AddSeries(Series("VIXY", SeriesType.Line, "$"))
        self.AddChart(vol_chart)
    
    def WeeklyUpdate(self):
        """2"""
        self.week_counter += 1
        if self.week_counter % self.rebalance_frequency_weeks == 1:  # 1, 3, 5...
            self.UpdateAdaptiveWeights()
            self.RebalanceUS()
    
    def WeeklyHKUpdate(self):
        """ - """
        if not self.enable_hk:
            return
        if self.week_counter % self.rebalance_frequency_weeks == 1:
            self.RebalanceHK()
    
    def UpdateAdaptiveWeights(self):
        """"""
        if self.IsWarmingUp:
            return
        
        try:
            # SPY20
            spy_history = self.History(self.symbols.get("SPY"), self.volatility_lookback + 5, Resolution.Daily)
            if not spy_history.empty and len(spy_history) >= self.volatility_lookback:
                spy_returns = spy_history['close'].pct_change().dropna()
                current_vol = spy_returns.iloc[-self.volatility_lookback:].std()
                
                # VIXYVIX
                vixy_price = 0
                if self.Portfolio[self.vix_symbol].Price > 0:
                    vixy_price = self.Portfolio[self.vix_symbol].Price
                
                self.Debug(f"\n  - {self.Time.strftime('%Y-%m-%d')}")
                self.Debug(f"  SPY 20: {current_vol:.4f} ({current_vol*100:.2f}%)")
                self.Debug(f"  VIXY : {vixy_price:.2f}")
                
                # 
                if current_vol > self.high_vol_threshold or vixy_price > self.vix_threshold:
                    # 
                    self.current_weights = {
                        '1d': 0.0,      # 1
                        '1w': 0.2,      # 1
                        '2w': 0.5,      # 2
                        '1m': 1.0,
                        '3m': 1.5,      # 3
                        '6m': 2.0       # 6
                    }
                    self.global_position_scale = self.vix_high_position_scale
                    self.Debug(f"   :  {self.global_position_scale:.0%}")
                    
                elif current_vol < self.low_vol_threshold:
                    # 
                    self.current_weights = {
                        '1d': 0.2,
                        '1w': 0.8,
                        '2w': 1.2,
                        '1m': 1.0,
                        '3m': 0.8,
                        '6m': 0.5
                    }
                    self.global_position_scale = 1.0
                    self.Debug(f"   : ")
                    
                else:
                    # 
                    self.current_weights = {
                        '1d': self.base_weight_1d,
                        '1w': self.base_weight_1w,
                        '2w': self.base_weight_2w,
                        '1m': self.base_weight_1m,
                        '3m': self.base_weight_3m,
                        '6m': self.base_weight_6m
                    }
                    self.global_position_scale = 1.0
                    self.Debug(f"   : ")
                
                # 
                self.Plot("Volatility", "DailyVol", current_vol * 100)
                self.Plot("Volatility", "VIXY", vixy_price)
        except Exception as e:
            self.Debug(f": {e}")
    
    def CalculateMomentumScore(self, symbol, name):
        """"""
        try:
            history_days = self.lookback_6m + 20
            history = self.History(symbol, history_days, Resolution.Daily)
            
            if history.empty or len(history) < self.lookback_6m:
                return None
            
            closes = history['close']
            current_price = closes.iloc[-1]
            
            returns = {}
            for period, days in [
                ('1d', self.lookback_1d), ('1w', self.lookback_1w), 
                ('2w', self.lookback_2w), ('1m', self.lookback_1m),
                ('3m', self.lookback_3m), ('6m', self.lookback_6m)
            ]:
                if len(closes) >= days:
                    past_price = closes.iloc[-days]
                    returns[period] = (current_price - past_price) / past_price
                else:
                    returns[period] = 0
            
            # 
            score = sum(returns[p] * self.current_weights[p] for p in returns)
            
            return {
                'symbol': symbol,
                'score': score,
                'returns': returns,
                'current_price': current_price
            }
            
        except Exception as e:
            return None
    
    def GetSectorMomentum(self):
        """"""
        sector_returns = {}
        
        for ticker, sector in self.sector_map.items():
            if ticker in self.symbols:
                try:
                    history = self.History(self.symbols[ticker], self.sector_lookback + 5, Resolution.Daily)
                    if not history.empty and len(history) >= self.sector_lookback:
                        returns = (history['close'].iloc[-1] - history['close'].iloc[-self.sector_lookback]) / history['close'].iloc[-self.sector_lookback]
                        if sector not in sector_returns:
                            sector_returns[sector] = []
                        sector_returns[sector].append(returns)
                except:
                    pass
        
        # 
        sector_momentum = {}
        for sector, returns_list in sector_returns.items():
            if returns_list:
                sector_momentum[sector] = sum(returns_list) / len(returns_list)
        
        # Top N
        sorted_sectors = sorted(sector_momentum.items(), key=lambda x: x[1], reverse=True)
        top_sectors = [s[0] for s in sorted_sectors[:self.top_n_sectors]]
        
        self.Debug(f"\n :")
        for sector, momentum in sorted_sectors[:5]:
            mark = "" if sector in top_sectors else " "
            self.Debug(f"  [{mark}] {sector:12s}: {momentum:7.2%}")
        
        return top_sectors
    
    def CheckStopLoss(self):
        """"""
        if self.IsWarmingUp:
            return
            
        for symbol, cost in list(self.cost_basis.items()):
            if self.Portfolio[symbol].Invested:
                current_price = self.Portfolio[symbol].Price
                if cost > 0 and (current_price - cost) / cost < -self.stop_loss_pct:
                    ticker = self.GetTickerName(symbol)
                    self.Debug(f" : {ticker}")
                    self.Liquidate(symbol)
                    if symbol in self.cost_basis:
                        del self.cost_basis[symbol]
    
    def GetMarketRelativeStrength(self):
        """ vs """
        # 100%
        if not self.enable_hk or len(self.hk_tickers) == 0:
            return 1.0, 0.0
        
        try:
            # SPY07001
            spy_history = self.History(self.symbols.get("SPY"), self.lookback_1m + 5, Resolution.Daily)
            hk_history = self.History(self.symbols.get("0700"), self.lookback_1m + 5, Resolution.Daily) if "0700" in self.symbols else None
            
            spy_momentum = 0
            hk_momentum = 0
            
            if not spy_history.empty and len(spy_history) >= self.lookback_1m:
                spy_momentum = (spy_history['close'].iloc[-1] - spy_history['close'].iloc[-self.lookback_1m]) / spy_history['close'].iloc[-self.lookback_1m]
            
            if hk_history is not None and not hk_history.empty and len(hk_history) >= self.lookback_1m:
                hk_momentum = (hk_history['close'].iloc[-1] - hk_history['close'].iloc[-self.lookback_1m]) / hk_history['close'].iloc[-self.lookback_1m]
            
            # 
            total_momentum = abs(spy_momentum) + abs(hk_momentum)
            if total_momentum > 0 and self.enable_relative_strength:
                # 
                us_ratio = abs(spy_momentum) / total_momentum
                #  50%-90% 
                us_ratio = max(0.5, min(0.9, us_ratio))
                hk_ratio = 1.0 - us_ratio
            else:
                us_ratio = self.us_allocation_base
                hk_ratio = self.hk_allocation_base
            
            self.Debug(f"\n :")
            self.Debug(f"  SPY: {spy_momentum:.2%}")
            self.Debug(f"  HK: {hk_momentum:.2%}")
            self.Debug(f"  :  {us_ratio:.0%} /  {hk_ratio:.0%}")
            
            return us_ratio, hk_ratio
            
        except Exception as e:
            self.Debug(f": {e}")
            return self.us_allocation_base, self.hk_allocation_base
    
    def CheckHKMarketTiming(self):
        """"""
        if not self.hk_market_timing:
            return True
        
        try:
            # 0700()3
            if "0700" not in self.symbols:
                return True
                
            hk_proxy = self.symbols["0700"]
            history = self.History(hk_proxy, self.lookback_3m + 5, Resolution.Daily)
            
            if history.empty or len(history) < self.lookback_3m:
                return True
            
            momentum = (history['close'].iloc[-1] - history['close'].iloc[-self.lookback_3m]) / history['close'].iloc[-self.lookback_3m]
            
            should_trade = momentum > self.hk_min_market_momentum
            
            self.Debug(f"  : 3={momentum:.2%}, ={'' if should_trade else ''}")
            
            return should_trade
            
        except Exception as e:
            return True
    
    def RebalanceUS(self):
        """ -  + """
        if self.IsWarmingUp:
            return
        
        # 
        us_ratio, hk_ratio = self.GetMarketRelativeStrength()
        
        self.Debug(f"\n{'='*60}")
        self.Debug(f"  - {self.Time.strftime('%Y-%m-%d')}")
        self.Debug(f"  : {us_ratio:.0%}")
        self.Debug(f"  : {self.global_position_scale:.0%}")
        self.Debug(f"{'='*60}")
        
        # 
        if self.enable_sector_rotation:
            top_sectors = self.GetSectorMomentum()
            us_symbols = {}
            for k, v in self.symbols.items():
                if k in self.us_tickers:
                    sector = self.sector_map.get(k, 'Other')
                    if sector in top_sectors or k in ['SPY', 'QQQ', 'TLT', 'GLD']:
                        us_symbols[k] = v
            self.Debug(f"  : {len(us_symbols)} ")
        else:
            us_symbols = {k: v for k, v in self.symbols.items() if k in self.us_tickers}
        
        # 
        self.us_position_scale = us_ratio
        self.RebalanceMarket(us_symbols, "US", is_hk=False)
    
    def RebalanceHK(self):
        """ - """
        if not self.enable_hk or self.IsWarmingUp:
            return
        
        # 
        if not self.CheckHKMarketTiming():
            self.Debug(f"\n{'='*60}")
            self.Debug(f"  - {self.Time.strftime('%Y-%m-%d')}")
            self.Debug(f"   ")
            self.Debug(f"{'='*60}")
            # 
            for symbol in list(self.cost_basis.keys()):
                if self.GetTickerName(symbol) in self.hk_tickers:
                    self.Liquidate(symbol)
                    del self.cost_basis[symbol]
            return
        
        # 
        us_ratio, hk_ratio = self.GetMarketRelativeStrength()
        
        self.Debug(f"\n{'='*60}")
        self.Debug(f"  - {self.Time.strftime('%Y-%m-%d')}")
        self.Debug(f"  : {hk_ratio:.0%}")
        self.Debug(f"  : {self.hk_max_position:.0%}")
        self.Debug(f"  : {self.global_position_scale:.0%}")
        self.Debug(f"{'='*60}")
        
        hk_symbols = {k: v for k, v in self.symbols.items() if k in self.hk_tickers}
        
        # 
        self.hk_position_scale = hk_ratio
        self.RebalanceMarket(hk_symbols, "HK", is_hk=True)
    
    def RebalanceMarket(self, market_symbols, market_name, is_hk=False):
        """VIX + """
        
        momentum_scores = {}
        for name, symbol in market_symbols.items():
            result = self.CalculateMomentumScore(symbol, name)
            if result is not None:
                momentum_scores[name] = result
        
        if not momentum_scores:
            return
        
        positive = {k: v for k, v in momentum_scores.items() if v['score'] > self.min_momentum_score}
        
        if not positive:
            self.Debug(f" {market_name}")
            self.Liquidate([s for s in market_symbols.values()])
            return
        
        sorted_stocks = sorted(positive.items(), key=lambda x: x[1]['score'], reverse=True)
        top_stocks = sorted_stocks[:self.top_n_stocks]
        
        self.Debug(f"\n {market_name} Top {len(top_stocks)}:")
        for name, data in top_stocks:
            returns = data['returns']
            self.Debug(f"  {name:6s}: Score={data['score']:7.4f}")
        
        # 
        total_score = sum(data['score'] for _, data in top_stocks)
        target_holdings = {}
        
        # 
        if is_hk:
            max_pos = self.hk_max_position  # 5%
            market_scale = getattr(self, 'hk_position_scale', self.hk_allocation_base)
        else:
            max_pos = self.max_position_per_stock  # 15%
            market_scale = getattr(self, 'us_position_scale', self.us_allocation_base)
        
        for name, data in top_stocks:
            weight = (data['score'] / total_score) if total_score > 0 else 0
            weight = min(weight, max_pos)  # 
            # VIX * 
            weight *= self.global_position_scale * market_scale
            target_holdings[data['symbol']] = weight
        
        # 
        total_weight = sum(target_holdings.values())
        if total_weight > 0:
            target_holdings = {k: v / total_weight for k, v in target_holdings.items()}
        
        self.Debug(f"\n {market_name} :")
        for symbol, weight in target_holdings.items():
            self.Debug(f"  {self.GetTickerName(symbol)}: {weight:.2%}")
        
        # 
        for symbol in list(self.cost_basis.keys()):
            if symbol not in target_holdings and self.GetTickerName(symbol) in market_symbols:
                self.Liquidate(symbol)
                del self.cost_basis[symbol]
        
        # 
        for symbol, target in target_holdings.items():
            current_weight = self.Portfolio[symbol].HoldingsValue / self.Portfolio.TotalPortfolioValue
            if abs(current_weight - target) > 0.005:
                self.SetHoldings(symbol, target)
                if self.Portfolio[symbol].Invested and symbol not in self.cost_basis:
                    self.cost_basis[symbol] = self.Portfolio[symbol].average_price
        
        self.Plot("Portfolio", "Value", self.Portfolio.TotalPortfolioValue)
    
    def GetTickerName(self, symbol):
        for name, sym in self.symbols.items():
            if sym == symbol:
                return name
        for name, sym in self.safe_symbols.items():
            if sym == symbol:
                return name
        return str(symbol)
    
    def OnData(self, data):
        pass
    
    def OnEndOfAlgorithm(self):
        self.Debug(f"\n{'='*60}")
        self.Debug("")
        self.Debug(f"{'='*60}")
        self.Debug(f": {self.StartDate.strftime('%Y-%m-%d')} ~ {self.EndDate.strftime('%Y-%m-%d')}")
        self.Debug(f": $100,000")
        self.Debug(f": ${self.Portfolio.TotalPortfolioValue:,.2f}")
        total_return = (self.Portfolio.TotalPortfolioValue - 100000) / 100000
        self.Debug(f": {total_return:.2%}")
        
        self.Debug(f"\n:")
        for symbol in self.Portfolio.Keys:
            if self.Portfolio[symbol].Invested:
                ticker = self.GetTickerName(symbol)
                weight = self.Portfolio[symbol].HoldingsValue / self.Portfolio.TotalPortfolioValue
                self.Debug(f"  {ticker}: {weight:.2%}")
        
        self.Debug(f"{'='*60}\n")
