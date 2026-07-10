from AI import *
import os
import json
class AdaptiveMomentumStrategy(QCA):
    def Initialize(self):
        s.SetStartDate(2020, 1, 1)
        s.SetEndDate(2025, 6, 1)
        s.SetCash(100000)
        
        s.lbs = {'1d':1,'1w':5,'2w':10,'1m':21,'3m':63,'6m':126}
        s.base_w = {'1d':0.1,'1w':0.5,'2w':1.0,'1m':1.0,'3m':1.0,'6m':1.0}
        s.cur_w = s.base_w.copy()
        
        s.val_d = {}
        s.val_filter = True
        s.val_w = 0.3
        s.mom_w = 0.7
        s.val_w_min = 0.2
        s.val_w_max = 0.5
        s.val_mul_min = 0.5
        s.val_mul_max = 1.5
        s.LoadValuationData()
        
        s.vol_lb = 20
        s.vol_hi = 0.025
        s.vol_lo = 0.01
        
        s.vix_symbol = s.AddEquity("VIXY", R.D).Symbol
        s.vix_th = 30.0
        s.vix_scale = 0.4
        
        s.max_pos = 0.08
        s.n_stocks = 10
        s.min_score = 0.0
        s.g_pos_scale = 1.0
        
        s.sec_rot = True
        s.n_sectors = 3
        s.sec_lb = 63
        
        s.sec_m = {
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
        
        s.base_freq = 2
        s.min_freq = 1
        s.max_freq = 8
        s.week_counter = 0
        s.cur_freq = 2
        s.pause_wks = 0
        s.vix_pause = 30
        s.vix_boost = 18
        s.val_extreme = 0.8
        s.max_pause = 4
        
        s.us_alloc = 1.0
        s.hk_alloc = 0.0
        s.rel_strength = False
        s.enable_hk = False
        s.sl_pct = 0.15
        
        s.us_t = [
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
        
        s.safe_t = ["TLT","GLD"]
        s.safe_s = {}
        s.symbols = {}
        s.tickers = []
        
        for ticker in s.us_t:
            try:
                s.symbols[ticker] = s.AddEquity(ticker, R.D).Symbol
                s.tickers.append(ticker)
            except:
                pass
        
        for ticker in s.safe_t:
            s.safe_s[ticker] = s.AddEquity(ticker, R.D).Symbol
        
        s.cost_b = {}
        
        s.Schedule.On(s.DR.Every(D.Monday), s.TR.AfterMarketOpen("SPY",5), s.WeeklyUpdate)
        s.Schedule.On(s.DR.Every(D.Tuesday), s.TR.AfterMarketOpen("0700",30), s.WeeklyHKUpdate)
        s.Schedule.On(s.DR.EveryDay("SPY"), s.TR.AfterMarketOpen("SPY",60), s.CheckStopLoss)
        
        warmup = max(s.lbs['6m'], s.sec_lb) + 20
        s.SetWarmUp(td(days=warmup))
    
    def LoadValuationData(self):
        try:
            valuation_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "val_d.json")
            if os.path.exists(valuation_file):
                with open(valuation_file,'r') as f:
                    data = json.load(f)
                for item in data:
                    ticker = item.get('ticker')
                    if ticker:
                        s.val_d[ticker] = {
                            'score': item.get('valuation_score',0.5),
                            'pe': item.get('pe_trailing'),
                            'pe_forward': item.get('pe_forward'),
                            'peg': item.get('peg_ratio'),
                            'ps': item.get('price_to_sales')
                        }
        except:
            pass
    
    def GetValuationScore(self, ticker):
        if not s.val_filter or not s.val_d:
            return 0.5
        return s.val_d.get(ticker, {}).get('score', 0.5)
    
    def GetValuationMultiplier(self, ticker):
        if not s.val_filter or not s.val_d:
            return 1.0
        score = s.GetValuationScore(ticker)
        return s.val_mul_min + score * (s.val_mul_max - s.val_mul_min)
    
    def WeeklyUpdate(self):
        s.week_counter += 1
        s.AdjustRebalanceFrequency()
        if s.week_counter % s.cur_freq == 1:
            s.UpdateAdaptiveWeights()
            s.RebalanceUS()
    
    def AdjustRebalanceFrequency(self):
        try:
            vixy_price = s.Portfolio[s.vix_symbol].Price if s.Portfolio[s.vix_symbol].Price > 0 else 25
            spy_valuation = 0.5
            try:
                spy_history = s.History(s.symbols.get("SPY"), 63, R.D)
                if not spy_history.empty and len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[-63]) - 1
                    spy_valuation = max(0, min(1, 0.5 + spy_3m_return * 2))
            except:
                pass
            
            is_extreme = spy_valuation > s.val_extreme or spy_valuation < (1 - s.val_extreme)
            
            if vixy_price > s.vix_pause or is_extreme:
                new_freq = min(s.cur_freq + 1, s.max_freq)
                if new_freq != s.cur_freq:
                    s.pause_wks += 1
                s.cur_freq = new_freq
            elif vixy_price < s.vix_boost and not is_extreme:
                new_freq = max(s.cur_freq - 1, s.min_freq)
                if new_freq != s.cur_freq:
                    s.cur_freq = new_freq
                s.pause_wks = 0
            else:
                s.cur_freq = s.base_freq
                s.pause_wks = 0
            
            if s.pause_wks >= s.max_pause:
                s.cur_freq = s.base_freq
                s.pause_wks = 0
        except:
            s.cur_freq = s.base_freq
    
    def WeeklyHKUpdate(self):
        if not s.enable_hk:
            return
        if s.week_counter % s.cur_freq == 1:
            s.RebalanceHK()
    
    def UpdateAdaptiveWeights(self):
        if s.IsWarmingUp:
            return
        try:
            spy_history = s.History(s.symbols.get("SPY"), s.vol_lb + 5, R.D)
            if not spy_history.empty and len(spy_history) >= s.vol_lb:
                spy_returns = spy_history['close'].pct_change().dropna()
                current_vol = spy_returns.iloc[-s.vol_lb:].std()
                vixy_price = s.Portfolio[s.vix_symbol].Price if s.Portfolio[s.vix_symbol].Price > 0 else 0
                
                spy_3m_return = 0
                if len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[-63]) - 1
                
                if spy_3m_return > 0.15:
                    v_lvl = 'high'
                elif spy_3m_return < -0.15:
                    v_lvl = 'low'
                else:
                    v_lvl = 'medium'
                
                if current_vol > s.vol_hi or vixy_price > s.vix_th:
                    if v_lvl == 'low':
                        s.cur_w = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        s.g_pos_scale = 1.0
                    elif v_lvl == 'high':
                        s.cur_w = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        s.g_pos_scale = 0.3
                    else:
                        s.cur_w = {'1d':0.0,'1w':0.2,'2w':0.5,'1m':1.0,'3m':1.5,'6m':2.0}
                        s.g_pos_scale = s.vix_scale
                elif current_vol < s.vol_lo:
                    s.cur_w = {'1d':0.2,'1w':0.8,'2w':1.2,'1m':1.0,'3m':0.8,'6m':0.5}
                    s.g_pos_scale = 1.0
                else:
                    s.cur_w = s.base_w.copy()
                    s.g_pos_scale = 1.0
                
                if s.val_filter:
                    if spy_3m_return > 0.15 and current_vol < s.vol_lo:
                        s.val_w = s.val_w_min
                        s.mom_w = 1.0 - s.val_w_min
                    elif spy_3m_return < -0.15 or current_vol > s.vol_hi:
                        s.val_w = s.val_w_max
                        s.mom_w = 1.0 - s.val_w_max
                    else:
                        s.val_w = 0.3
                        s.mom_w = 0.7
        except:
            pass
    
    def CalculateMomentumScore(self, symbol, name):
        try:
            history_days = s.lbs['6m'] + 20
            history = s.History(symbol, history_days, R.D)
            if history.empty or len(history) < s.lbs['6m']:
                return None
            closes = history['close']
            current_price = closes.iloc[-1]
            
            returns = {}
            for period, days in s.lbs.items():
                if len(closes) >= days:
                    returns[period] = (current_price - closes.iloc[-days]) / closes.iloc[-days]
                else:
                    returns[period] = 0
            
            score = sum(returns[p] * s.cur_w[p] for p in returns)
            return {'symbol':symbol,'score':score,'returns':returns,'current_price':current_price}
        except:
            return None
    
    def GetSectorMomentum(self):
        sec_ret = {}
        for ticker, sector in s.sec_m.items():
            if ticker in s.symbols:
                try:
                    history = s.History(s.symbols[ticker], s.sec_lb + 5, R.D)
                    if not history.empty and len(history) >= s.sec_lb:
                        ret = (history['close'].iloc[-1] - history['close'].iloc[-s.sec_lb]) / history['close'].iloc[-s.sec_lb]
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
        return [s[0] for s in sorted_sectors[:s.n_sectors]]
    
    def CheckStopLoss(self):
        if s.IsWarmingUp:
            return
        for symbol, cost in list(s.cost_b.items()):
            if s.Portfolio[symbol].Invested:
                current_price = s.Portfolio[symbol].Price
                if cost > 0 and (current_price - cost) / cost < -s.sl_pct:
                    s.Liquidate(symbol)
                    del s.cost_b[symbol]
    
    def RebalanceUS(self):
        if s.IsWarmingUp:
            return
        
        if s.sec_rot:
            top_sectors = s.GetSectorMomentum()
            us_symbols = {}
            for k, v in s.symbols.items():
                if k in s.us_t:
                    sector = s.sec_m.get(k, 'Other')
                    if sector in top_sectors or k in ['SPY','QQQ','TLT','GLD']:
                        us_symbols[k] = v
        else:
            us_symbols = {k:v for k,v in s.symbols.items() if k in s.us_t}
        
        s.RebalanceMarket(us_symbols, "US")
    
    def RebalanceHK(self):
        if not s.enable_hk or s.IsWarmingUp:
            return
        pass
    
    def RebalanceMarket(self, m_sym, m_name):
        mom_scores = {}
        for name, symbol in m_sym.items():
            result = s.CalculateMomentumScore(symbol, name)
            if result is not None:
                mom_scores[name] = result
        
        if not mom_scores:
            return
        
        pos = {k:v for k,v in mom_scores.items() if v['score'] > s.min_score}
        if not pos:
            s.Liquidate([s for s in m_sym.values()])
            return
        
        sort_s = sorted(pos.items(), key=lambda x: x[1]['score'], reverse=True)
        top_s = sort_s[:s.n_stocks]
        
        t_score = sum(data['score'] for _, data in top_s)
        targets = {}
        
        for name, data in top_s:
            weight = (data['score'] / t_score) if t_score > 0 else 0
            weight = min(weight, s.max_pos)
            
            if s.val_filter and s.val_d:
                multiplier = s.GetValuationMultiplier(name)
                weight *= multiplier
            
            weight *= s.g_pos_scale
            targets[data['symbol']] = weight
        
        t_weight = sum(targets.values())
        if t_weight > 0:
            targets = {k: v/t_weight for k, v in targets.items()}
        
        for symbol in list(s.cost_b.keys()):
            if symbol not in targets and s.GetTickerName(symbol) in m_sym and s.Portfolio[symbol].Invested:
                s.Liquidate(symbol)
                del s.cost_b[symbol]
        
        for symbol, target in targets.items():
            c_weight = s.Portfolio[symbol].HoldingsValue / s.Portfolio.TotalPortfolioValue if s.Portfolio.TotalPortfolioValue > 0 else 0
            dev = abs(c_weight - target)
            
            if c_weight == 0 or dev > 0.10:
                s.SetHoldings(symbol, target)
                if s.Portfolio[symbol].Invested and symbol not in s.cost_b:
                    s.cost_b[symbol] = s.Portfolio[symbol].average_price
    
    def GetTickerName(self, symbol):
        for name, sym in s.symbols.items():
            if sym == symbol:
                return name
        for name, sym in s.safe_s.items():
            if sym == symbol:
                return name
        return str(symbol)
    
    def OnData(self, data):
        pass
    
    def OnEndOfAlgorithm(self):
        total_return = (s.Portfolio.TotalPortfolioValue - 100000) / 100000
        s.Log(f"总收益率: {total_return:.2%}")
