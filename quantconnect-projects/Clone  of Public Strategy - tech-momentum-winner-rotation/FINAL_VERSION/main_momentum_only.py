from AlgorithmImports import *
import os
import json
class AdaptiveMomentumStrategy(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2025, 6, 1)
        self.SetCash(100000)
        
        self.lbs = {'1d':1,'1w':5,'2w':10,'1m':21,'3m':63,'6m':126}
        self.base_w = {'1d':0.1,'1w':0.5,'2w':1.0,'1m':1.0,'3m':1.0,'6m':1.0}
        self.cur_w = self.base_w.copy()
        
        self.val_d = {}
        self.val_filter = False
        self.val_w = 0.3
        self.mom_w = 0.7
        self.val_w_min = 0.2
        self.val_w_max = 0.5
        self.val_mul_min = 0.5
        self.val_mul_max = 1.5
        self.LoadValuationData()
        
        self.vol_lookback = 20
        self.vol_high = 0.025
        self.vol_low = 0.01
        
        self.vix_symbol = self.AddEquity("VIXY", Resolution.Daily).Symbol
        self.vix_th = 30.0
        self.vix_scale = 0.4
        
        self.max_pos = 0.08
        self.n_stocks = 10
        self.min_score = 0.0
        self.g_pos_scale = 1.0
        
        self.sec_rot = True
        self.n_sectors = 3
        self.sec_lookback = 63
        
        self.sec_m = {
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
        
        self.base_freq = 2
        self.min_freq = 1
        self.max_freq = 8
        self.week_counter = 0
        self.cur_freq = 2
        self.pause_weeks = 0
        self.vix_pause = 30
        self.vix_boost = 18
        self.val_extreme = 0.8
        self.max_pause = 4
        
        self.us_alloc = 1.0
        self.hk_alloc = 0.0
        self.rel_strength = False
        self.enable_hk = False
        self.sl_pct = 0.15
        
        self.us_t = [
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
        
        self.safe_t = ["TLT","GLD"]
        self.safe_s = {}
        self.symbols = {}
        self.tickers = []
        
        for ticker in self.us_t:
            try:
                self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
                self.tickers.append(ticker)
            except:
                pass
        
        for ticker in self.safe_t:
            self.safe_s[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
        
        self.cost_b = {}
        
        self.Schedule.On(self.DateRules.Every(DayOfWeek.Monday), self.TimeRules.AfterMarketOpen("SPY",5), self.WeeklyUpdate)
        self.Schedule.On(self.DateRules.Every(DayOfWeek.Tuesday), self.TimeRules.AfterMarketOpen("0700",30), self.WeeklyHKUpdate)
        self.Schedule.On(self.DateRules.EveryDay("SPY"), self.TimeRules.AfterMarketOpen("SPY",60), self.CheckStopLoss)
        
        warmup = max(self.lbs['6m'], self.sec_lookback) + 20
        self.SetWarmUp(timedelta(days=warmup))
    
    def LoadValuationData(self):
        try:
            valuation_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "val_d.json")
            if os.path.exists(valuation_file):
                with open(valuation_file,'r') as f:
                    data = json.load(f)
                for item in data:
                    ticker = item.get('ticker')
                    if ticker:
                        self.val_d[ticker] = {
                            'score': item.get('valuation_score',0.5),
                            'pe': item.get('pe_trailing'),
                            'pe_forward': item.get('pe_forward'),
                            'peg': item.get('peg_ratio'),
                            'ps': item.get('price_to_sales')
                        }
        except:
            pass
    
    def GetValuationScore(self, ticker):
        if not self.val_filter or not self.val_d:
            return 0.5
        return self.val_d.get(ticker, {}).get('score', 0.5)
    
    def GetValuationMultiplier(self, ticker):
        if not self.val_filter or not self.val_d:
            return 1.0
        score = self.GetValuationScore(ticker)
        return self.val_mul_min + score * (self.val_mul_max - self.val_mul_min)
    
    def WeeklyUpdate(self):
        self.week_counter += 1
        self.AdjustRebalanceFrequency()
        if self.week_counter % self.cur_freq == 1:
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
            
            is_extreme = spy_valuation > self.val_extreme or spy_valuation < (1 - self.val_extreme)
            
            if vixy_price > self.vix_pause or is_extreme:
                new_freq = min(self.cur_freq + 1, self.max_freq)
                if new_freq != self.cur_freq:
                    self.pause_weeks += 1
                self.cur_freq = new_freq
            elif vixy_price < self.vix_boost and not is_extreme:
                new_freq = max(self.cur_freq - 1, self.min_freq)
                if new_freq != self.cur_freq:
                    self.cur_freq = new_freq
                self.pause_weeks = 0
            else:
                self.cur_freq = self.base_freq
                self.pause_weeks = 0
            
            if self.pause_weeks >= self.max_pause:
                self.cur_freq = self.base_freq
                self.pause_weeks = 0
        except:
            self.cur_freq = self.base_freq
    
    def WeeklyHKUpdate(self):
        if not self.enable_hk:
            return
        if self.week_counter % self.cur_freq == 1:
            self.RebalanceHK()
    
    def UpdateAdaptiveWeights(self):
        if self.IsWarmingUp:
            return
        try:
            spy_history = self.History(self.symbols.get("SPY"), self.vol_lookback + 5, Resolution.Daily)
            if not spy_history.empty and len(spy_history) >= self.vol_lookback:
                spy_returns = spy_history['close'].pct_change().dropna()
                current_vol = spy_returns.iloc[-self.vol_lookback:].std()
                vixy_price = self.Portfolio[self.vix_symbol].Price if self.Portfolio[self.vix_symbol].Price > 0 else 0
                
                spy_3m_return = 0
                if len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[-63]) - 1
                
                if spy_3m_return > 0.15:
                    v_lvl = 'high'
                elif spy_3m_return < -0.15:
                    v_lvl = 'low'
                else:
                    v_lvl = 'medium'
                
                if current_vol > self.vol_high or vixy_price > self.vix_th:
                    if v_lvl == 'low':
                        self.cur_w = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        self.g_pos_scale = 1.0
                    elif v_lvl == 'high':
                        self.cur_w = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        self.g_pos_scale = 0.3
                    else:
                        self.cur_w = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        self.g_pos_scale = self.vix_scale
                elif current_vol < self.vol_low:
                    self.cur_w = {'1d':0.2,'1w':0.8,'2w':1.2,'1m':1.0,'3m':0.8,'6m':0.5}
                    self.g_pos_scale = 1.0
                else:
                    self.cur_w = self.base_w.copy()
                    self.g_pos_scale = 1.0
                
                if self.val_filter:
                    if spy_3m_return > 0.15 and current_vol < self.vol_low:
                        self.val_w = self.val_w_min
                        self.mom_w = 1.0 - self.val_w_min
                    elif spy_3m_return < -0.15 or current_vol > self.vol_high:
                        self.val_w = self.val_w_max
                        self.mom_w = 1.0 - self.val_w_max
                    else:
                        self.val_w = 0.3
                        self.mom_w = 0.7
        except:
            pass
    
    def CalculateMomentumScore(self, symbol, name):
        try:
            history_days = self.lbs['6m'] + 20
            history = self.History(symbol, history_days, Resolution.Daily)
            if history.empty or len(history) < self.lbs['6m']:
                return None
            closes = history['close']
            current_price = closes.iloc[-1]
            
            returns = {}
            for period, days in self.lbs.items():
                if len(closes) >= days:
                    returns[period] = (current_price - closes.iloc[-days]) / closes.iloc[-days]
                else:
                    returns[period] = 0
            
            score = sum(returns[p] * self.cur_w[p] for p in returns)
            return {'symbol':symbol,'score':score,'returns':returns,'current_price':current_price}
        except:
            return None
    
    def GetSectorMomentum(self):
        sec_ret = {}
        for ticker, sector in self.sec_m.items():
            if ticker in self.symbols:
                try:
                    history = self.History(self.symbols[ticker], self.sec_lookback + 5, Resolution.Daily)
                    if not history.empty and len(history) >= self.sec_lookback:
                        ret = (history['close'].iloc[-1] - history['close'].iloc[-self.sec_lookback]) / history['close'].iloc[-self.sec_lookback]
                        if sector not in sec_ret:
                            sec_ret[sector] = []
                        sec_ret[sector].append(ret)
                except:
                    pass
        
        sec_mom = {}
        for sector, ret_list in sec_ret.items():
            if ret_list:
                sec_mom[sector] = sum(ret_list) / len(ret_list)
        
        sorted_sectors = sorted(sec_mom.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_sectors[:self.n_sectors]]
    
    def CheckStopLoss(self):
        if self.IsWarmingUp:
            return
        for symbol, cost in list(self.cost_b.items()):
            if self.Portfolio[symbol].Invested:
                current_price = self.Portfolio[symbol].Price
                if cost > 0 and (current_price - cost) / cost < -self.sl_pct:
                    self.Liquidate(symbol)
                    del self.cost_b[symbol]
    
    def RebalanceUS(self):
        if self.IsWarmingUp:
            return
        
        if self.sec_rot:
            top_sectors = self.GetSectorMomentum()
            us_symbols = {}
            for k, v in self.symbols.items():
                if k in self.us_t:
                    sector = self.sec_m.get(k, 'Other')
                    if sector in top_sectors or k in ['SPY','QQQ','TLT','GLD']:
                        us_symbols[k] = v
        else:
            us_symbols = {k:v for k,v in self.symbols.items() if k in self.us_t}
        
        self.RebalanceMarket(us_symbols, "US")
    
    def RebalanceHK(self):
        if not self.enable_hk or self.IsWarmingUp:
            return
        pass
    
    def RebalanceMarket(self, m_sym, m_name):
        mom_scores = {}
        for name, symbol in m_sym.items():
            result = self.CalculateMomentumScore(symbol, name)
            if result is not None:
                mom_scores[name] = result
        
        if not mom_scores:
            return
        
        pos = {k:v for k,v in mom_scores.items() if v['score'] > self.min_score}
        if not pos:
            self.Liquidate([s for s in m_sym.values()])
            return
        
        sort_s = sorted(pos.items(), key=lambda x: x[1]['score'], reverse=True)
        top_s = sort_s[:self.n_stocks]
        
        t_score = sum(data['score'] for _, data in top_s)
        targets = {}
        
        for name, data in top_s:
            weight = (data['score'] / t_score) if t_score > 0 else 0
            weight = min(weight, self.max_pos)
            
            if self.val_filter and self.val_d:
                multiplier = self.GetValuationMultiplier(name)
                weight *= multiplier
            
            weight *= self.g_pos_scale
            targets[data['symbol']] = weight
        
        t_weight = sum(targets.values())
        if t_weight > 0:
            targets = {k: v/t_weight for k, v in targets.items()}
        
        for symbol in list(self.cost_b.keys()):
            if symbol not in targets and self.GetTickerName(symbol) in m_sym and self.Portfolio[symbol].Invested:
                self.Liquidate(symbol)
                del self.cost_b[symbol]
        
        for symbol, target in targets.items():
            c_weight = self.Portfolio[symbol].HoldingsValue / self.Portfolio.TotalPortfolioValue if self.Portfolio.TotalPortfolioValue > 0 else 0
            dev = abs(c_weight - target)
            
            if c_weight == 0 or dev > 0.10:
                self.SetHoldings(symbol, target)
                if self.Portfolio[symbol].Invested and symbol not in self.cost_b:
                    self.cost_b[symbol] = self.Portfolio[symbol].average_price
    
    def GetTickerName(self, symbol):
        for name, sym in self.symbols.items():
            if sym == symbol:
                return name
        for name, sym in self.safe_s.items():
            if sym == symbol:
                return name
        return str(symbol)
    
    def OnData(self, data):
        pass
    
    def OnEndOfAlgorithm(self):
        total_return = (self.Portfolio.TotalPortfolioValue - 100000) / 100000
        self.Log(f"总收益率: {total_return:.2%}")
