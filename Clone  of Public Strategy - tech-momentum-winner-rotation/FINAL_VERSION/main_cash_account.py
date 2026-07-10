from AlgorithmImports import *
import os
import json

class AdaptiveMomentumStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2018, 1, 1)
        self.SetEndDate(2022, 1, 1)
        self.SetCash(100000)
        # 使用现金账户（无杠杆，无Margin Call）
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Cash)
        
        # 动量参数
        self.lookbacks = {'1d':1,'1w':5,'2w':10,'1m':21,'3m':63,'6m':126}
        self.base_weights = {'1d':0.1,'1w':0.5,'2w':1.0,'1m':1.0,'3m':1.0,'6m':1.0}
        self.current_weights = self.base_weights.copy()
        
        # 估值参数
        self.valuation_data = {}
        self.enable_valuation_filter = True
        self.valuation_weight = 0.3
        self.momentum_weight = 0.7
        self.valuation_weight_min = 0.2
        self.valuation_weight_max = 0.5
        self.valuation_multiplier_min = 0.5
        self.valuation_multiplier_max = 1.5
        self.LoadValuationData()
        
        # 波动率参数
        self.volatility_lookback = 20
        self.high_vol_threshold = 0.025
        self.low_vol_threshold = 0.01
        
        # VIX参数
        self.vix_symbol = self.AddEquity("VIXY", Resolution.Daily).Symbol
        self.vix_threshold = 30.0
        self.vix_high_position_scale = 0.4
        
        # 仓位管理
        self.max_position_per_stock = 0.08
        self.top_n_stocks = 10
        self.min_momentum_score = 0.0
        self.global_position_scale = 1.0
        
        # 行业轮动
        self.enable_sector_rotation = True
        self.top_n_sectors = 3
        self.sector_lookback = 63
        
        self.sector_map = {
            'AAPL':'Tech','MSFT':'Tech','NVDA':'Tech','GOOGL':'Tech','META':'Tech','AMZN':'Tech','TSLA':'Tech','AMD':'Tech','INTC':'Tech','CRM':'Tech',
            'ORCL':'Tech','ADBE':'Tech','CSCO':'Tech','AVGO':'Tech','QCOM':'Tech','TXN':'Tech','AMAT':'Tech','MU':'Tech','NFLX':'Tech','INTU':'Tech',
            'ANET':'Tech','FSLR':'Tech','FTNT':'Tech','SNPS':'Tech','KLAC':'Tech','MRVL':'Tech','NXPI':'Tech','SWKS':'Tech','MCHP':'Tech','CDNS':'Tech',
            'DDOG':'Tech','PLTR':'Tech','NOW':'Tech','NET':'Tech','JPM':'Finance','BAC':'Finance','GS':'Finance','MS':'Finance','WFC':'Finance','BLK':'Finance',
            'C':'Finance','AXP':'Finance','SCHW':'Finance','PNC':'Finance','SPGI':'Finance','MCO':'Finance','ICE':'Finance','CME':'Finance',
            'TFC':'Finance','USB':'Finance','COF':'Finance','BK':'Finance','STT':'Finance','NDAQ':'Finance',
            'JNJ':'Healthcare','UNH':'Healthcare','LLY':'Healthcare','PFE':'Healthcare','MRK':'Healthcare','ABBV':'Healthcare','ABT':'Healthcare','TMO':'Healthcare',
            'DHR':'Healthcare','BMY':'Healthcare','AMGN':'Healthcare','GILD':'Healthcare','REGN':'Healthcare','VRTX':'Healthcare','MRNA':'Healthcare','BIIB':'Healthcare',
            'HD':'Consumer','COST':'Consumer','NKE':'Consumer','MCD':'Consumer','SBUX':'Consumer','LOW':'Consumer','TJX':'Consumer',
            'PG':'Consumer','KO':'Consumer','PEP':'Consumer','WMT':'Consumer','MDLZ':'Consumer','CL':'Consumer','KMB':'Consumer','GIS':'Consumer','CPB':'Consumer',
            'XOM':'Energy','CVX':'Energy','COP':'Energy','SLB':'Energy','OXY':'Energy','EOG':'Energy','MPC':'Energy','VLO':'Energy','PSX':'Energy','KMI':'Energy',
            'CAT':'Industrial','HON':'Industrial','UPS':'Industrial','BA':'Industrial','GE':'Industrial','RTX':'Industrial','LMT':'Industrial',
            'NOC':'Industrial','GD':'Industrial','ITW':'Industrial','MMM':'Industrial','EMR':'Industrial',
            'VZ':'Telecom','T':'Telecom','CMCSA':'Telecom','TMUS':'Telecom','CHTR':'Telecom','CCI':'Telecom','AMT':'Telecom'
        }
        
        # 调仓周期
        self.base_rebalance_freq = 2
        self.min_rebalance_freq = 1
        self.max_rebalance_freq = 8
        self.week_counter = 0
        self.current_rebalance_freq = 2
        self.consecutive_pause_weeks = 0
        self.vix_pause_threshold = 30
        self.vix_boost_threshold = 18
        self.valuation_extreme_threshold = 0.8
        self.max_pause_weeks = 4
        
        # 纯美股模式
        self.us_allocation_base = 1.0
        self.hk_allocation_base = 0.0
        self.enable_relative_strength = False
        self.enable_hk = False
        self.stop_loss_pct = 0.15
        
        self.us_tickers = [
            "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AMD","INTC","CRM",
            "ORCL","ADBE","CSCO","AVGO","QCOM","TXN","AMAT","MU","NFLX","INTU",
            "ANET","FSLR","FTNT","SNPS","KLAC","MRVL","NXPI","SWKS","MCHP","CDNS",
            "DDOG","PLTR","NOW","NET","JPM","BAC","GS","MS","WFC","BLK",
            "C","AXP","SCHW","PNC","SPGI","MCO","ICE","CME","JNJ","UNH",
            "LLY","PFE","MRK","ABBV","ABT","TMO","DHR","BMY","AMGN","GILD",
            "REGN","VRTX","MRNA","HD","COST","NKE","MCD","SBUX","LOW","TJX",
            "PG","KO","PEP","WMT","MDLZ","XOM","CVX","COP","SLB","OXY",
            "CAT","HON","UPS","BA","GE","RTX","LMT","VZ","T","CMCSA",
            "SPY","QQQ","IWM","TLT","GLD","VIXY"
        ]
        
        self.safe_tickers = ["TLT","GLD"]
        self.safe_symbols = {}
        self.symbols = {}
        self.tickers = []
        
        for ticker in self.us_tickers:
            try:
                self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
                self.tickers.append(ticker)
            except:
                pass
        
        for ticker in self.safe_tickers:
            self.safe_symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
        
        self.cost_basis = {}
        
        self.Schedule.On(self.DateRules.Every(DayOfWeek.Monday), self.TimeRules.AfterMarketOpen("SPY",5), self.WeeklyUpdate)
        self.Schedule.On(self.DateRules.Every(DayOfWeek.Tuesday), self.TimeRules.AfterMarketOpen("0700",30), self.WeeklyHKUpdate)
        self.Schedule.On(self.DateRules.EveryDay("SPY"), self.TimeRules.AfterMarketOpen("SPY",60), self.CheckStopLoss)
        
        warmup = max(self.lookbacks['6m'], self.sector_lookback) + 20
        self.SetWarmUp(timedelta(days=warmup))
    
    def LoadValuationData(self):
        try:
            valuation_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "valuation_data.json")
            if os.path.exists(valuation_file):
                with open(valuation_file,'r') as f:
                    data = json.load(f)
                for item in data:
                    ticker = item.get('ticker')
                    if ticker:
                        self.valuation_data[ticker] = {
                            'score': item.get('valuation_score',0.5),
                            'pe': item.get('pe_trailing'),
                            'pe_forward': item.get('pe_forward'),
                            'peg': item.get('peg_ratio'),
                            'ps': item.get('price_to_sales')
                        }
        except:
            pass
    
    def GetValuationScore(self, ticker):
        if not self.enable_valuation_filter or not self.valuation_data:
            return 0.5
        return self.valuation_data.get(ticker, {}).get('score', 0.5)
    
    def GetValuationMultiplier(self, ticker):
        if not self.enable_valuation_filter or not self.valuation_data:
            return 1.0
        score = self.GetValuationScore(ticker)
        return self.valuation_multiplier_min + score * (self.valuation_multiplier_max - self.valuation_multiplier_min)
    
    def WeeklyUpdate(self):
        self.week_counter += 1
        self.AdjustRebalanceFrequency()
        if self.week_counter % self.current_rebalance_freq == 1:
            self.UpdateAdaptiveWeights()
            self.RebalanceUS()
    
    def AdjustRebalanceFrequency(self):
        try:
            vixy_price = self.Portfolio[self.vix_symbol].Price if self.Portfolio[self.vix_symbol].Price > 0 else 25
            spy_valuation = 0.5
            try:
                spy_history = self.History(self.symbols.get("SPY"), 63, Resolution.Daily)
                if not spy_history.empty and len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[-63]) - 1
                    spy_valuation = max(0, min(1, 0.5 + spy_3m_return * 2))
            except:
                pass
            
            is_extreme = spy_valuation > self.valuation_extreme_threshold or spy_valuation < (1 - self.valuation_extreme_threshold)
            
            if vixy_price > self.vix_pause_threshold or is_extreme:
                new_freq = min(self.current_rebalance_freq + 1, self.max_rebalance_freq)
                if new_freq != self.current_rebalance_freq:
                    self.consecutive_pause_weeks += 1
                self.current_rebalance_freq = new_freq
            elif vixy_price < self.vix_boost_threshold and not is_extreme:
                new_freq = max(self.current_rebalance_freq - 1, self.min_rebalance_freq)
                if new_freq != self.current_rebalance_freq:
                    self.current_rebalance_freq = new_freq
                self.consecutive_pause_weeks = 0
            else:
                self.current_rebalance_freq = self.base_rebalance_freq
                self.consecutive_pause_weeks = 0
            
            if self.consecutive_pause_weeks >= self.max_pause_weeks:
                self.current_rebalance_freq = self.base_rebalance_freq
                self.consecutive_pause_weeks = 0
        except:
            self.current_rebalance_freq = self.base_rebalance_freq
    
    def WeeklyHKUpdate(self):
        if not self.enable_hk:
            return
        if self.week_counter % self.current_rebalance_freq == 1:
            self.RebalanceHK()
    
    def UpdateAdaptiveWeights(self):
        if self.IsWarmingUp:
            return
        try:
            spy_history = self.History(self.symbols.get("SPY"), self.volatility_lookback + 5, Resolution.Daily)
            if not spy_history.empty and len(spy_history) >= self.volatility_lookback:
                spy_returns = spy_history['close'].pct_change().dropna()
                current_vol = spy_returns.iloc[-self.volatility_lookback:].std()
                vixy_price = self.Portfolio[self.vix_symbol].Price if self.Portfolio[self.vix_symbol].Price > 0 else 0
                
                spy_3m_return = 0
                if len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[-63]) - 1
                
                if spy_3m_return > 0.15:
                    val_level = 'high'
                elif spy_3m_return < -0.15:
                    val_level = 'low'
                else:
                    val_level = 'medium'
                
                if current_vol > self.high_vol_threshold or vixy_price > self.vix_threshold:
                    if val_level == 'low':
                        self.current_weights = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        self.global_position_scale = 1.0
                    elif val_level == 'high':
                        self.current_weights = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        self.global_position_scale = 0.3
                    else:
                        self.current_weights = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        self.global_position_scale = self.vix_high_position_scale
                elif current_vol < self.low_vol_threshold:
                    self.current_weights = {'1d':0.2,'1w':0.8,'2w':1.2,'1m':1.0,'3m':0.8,'6m':0.5}
                    self.global_position_scale = 1.0
                else:
                    self.current_weights = self.base_weights.copy()
                    self.global_position_scale = 1.0
                
                if self.enable_valuation_filter:
                    if spy_3m_return > 0.15 and current_vol < self.low_vol_threshold:
                        self.valuation_weight = self.valuation_weight_min
                        self.momentum_weight = 1.0 - self.valuation_weight_min
                    elif spy_3m_return < -0.15 or current_vol > self.high_vol_threshold:
                        self.valuation_weight = self.valuation_weight_max
                        self.momentum_weight = 1.0 - self.valuation_weight_max
                    else:
                        self.valuation_weight = 0.3
                        self.momentum_weight = 0.7
        except:
            pass
    
    def CalculateMomentumScore(self, symbol, name):
        try:
            history_days = self.lookbacks['6m'] + 20
            history = self.History(symbol, history_days, Resolution.Daily)
            if history.empty or len(history) < self.lookbacks['6m']:
                return None
            closes = history['close']
            current_price = closes.iloc[-1]
            
            returns = {}
            for period, days in self.lookbacks.items():
                if len(closes) >= days:
                    returns[period] = (current_price - closes.iloc[-days]) / closes.iloc[-days]
                else:
                    returns[period] = 0
            
            score = sum(returns[p] * self.current_weights[p] for p in returns)
            return {'symbol':symbol,'score':score,'returns':returns,'current_price':current_price}
        except:
            return None
    
    def GetSectorMomentum(self):
        sector_returns = {}
        for ticker, sector in self.sector_map.items():
            if ticker in self.symbols:
                try:
                    history = self.History(self.symbols[ticker], self.sector_lookback + 5, Resolution.Daily)
                    if not history.empty and len(history) >= self.sector_lookback:
                        ret = (history['close'].iloc[-1] - history['close'].iloc[-self.sector_lookback]) / history['close'].iloc[-self.sector_lookback]
                        if sector not in sector_returns:
                            sector_returns[sector] = []
                        sector_returns[sector].append(ret)
                except:
                    pass
        
        sector_momentum = {}
        for sector, ret_list in sector_returns.items():
            if ret_list:
                sector_momentum[sector] = sum(ret_list) / len(ret_list)
        
        sorted_sectors = sorted(sector_momentum.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_sectors[:self.top_n_sectors]]
    
    def CheckStopLoss(self):
        if self.IsWarmingUp:
            return
        for symbol, cost in list(self.cost_basis.items()):
            if self.Portfolio[symbol].Invested:
                current_price = self.Portfolio[symbol].Price
                if cost > 0 and (current_price - cost) / cost < -self.stop_loss_pct:
                    self.Liquidate(symbol)
                    del self.cost_basis[symbol]
    
    def RebalanceUS(self):
        if self.IsWarmingUp:
            return
        
        if self.enable_sector_rotation:
            top_sectors = self.GetSectorMomentum()
            us_symbols = {}
            for k, v in self.symbols.items():
                if k in self.us_tickers:
                    sector = self.sector_map.get(k, 'Other')
                    if sector in top_sectors or k in ['SPY','QQQ','TLT','GLD']:
                        us_symbols[k] = v
        else:
            us_symbols = {k:v for k,v in self.symbols.items() if k in self.us_tickers}
        
        self.RebalanceMarket(us_symbols, "US")
    
    def RebalanceHK(self):
        if not self.enable_hk or self.IsWarmingUp:
            return
        pass
    
    def RebalanceMarket(self, market_symbols, market_name):
        momentum_scores = {}
        for name, symbol in market_symbols.items():
            result = self.CalculateMomentumScore(symbol, name)
            if result is not None:
                momentum_scores[name] = result
        
        if not momentum_scores:
            return
        
        positive = {k:v for k,v in momentum_scores.items() if v['score'] > self.min_momentum_score}
        if not positive:
            self.Liquidate([s for s in market_symbols.values()])
            return
        
        sorted_stocks = sorted(positive.items(), key=lambda x: x[1]['score'], reverse=True)
        top_stocks = sorted_stocks[:self.top_n_stocks]
        
        total_score = sum(data['score'] for _, data in top_stocks)
        target_holdings = {}
        
        for name, data in top_stocks:
            weight = (data['score'] / total_score) if total_score > 0 else 0
            weight = min(weight, self.max_position_per_stock)
            
            if self.enable_valuation_filter and self.valuation_data:
                multiplier = self.GetValuationMultiplier(name)
                weight *= multiplier
            
            weight *= self.global_position_scale
            target_holdings[data['symbol']] = weight
        
        total_weight = sum(target_holdings.values())
        if total_weight > 0:
            target_holdings = {k: v/total_weight for k, v in target_holdings.items()}
        
        for symbol in list(self.cost_basis.keys()):
            if symbol not in target_holdings and self.GetTickerName(symbol) in market_symbols and self.Portfolio[symbol].Invested:
                self.Liquidate(symbol)
                del self.cost_basis[symbol]
        
        for symbol, target in target_holdings.items():
            current_weight = self.Portfolio[symbol].HoldingsValue / self.Portfolio.TotalPortfolioValue if self.Portfolio.TotalPortfolioValue > 0 else 0
            deviation = abs(current_weight - target)
            
            if current_weight == 0 or deviation > 0.10:
                self.SetHoldings(symbol, target)
                if self.Portfolio[symbol].Invested and symbol not in self.cost_basis:
                    self.cost_basis[symbol] = self.Portfolio[symbol].average_price
    
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
        total_return = (self.Portfolio.TotalPortfolioValue - 100000) / 100000
        self.Log(f"总收益率: {total_return:.2%}")
