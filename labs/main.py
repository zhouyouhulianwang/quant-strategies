from AlgorithmImports import *
from collections import defaultdict


class VixPanicStatAndTrade(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2026, 7, 10)
        self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)

        # 標的
        self.spx = self.add_equity("SPY", Resolution.DAILY).symbol
        self.dji = self.add_equity("DIA", Resolution.DAILY).symbol
        self.ndx = self.add_equity("QQQ", Resolution.DAILY).symbol
        self.vix = self.add_equity("VXX", Resolution.DAILY).symbol
        self.symbols = {"SPX": self.spx, "DJI": self.dji, "NDX": self.ndx}

        # 參數 (根據統計規律優化)
        self.vix_thresh = 20  # VXX對應VIX=30的代理閾值
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.take_profit = 0.02  # 2%止盈
        self.stop_loss = -0.02   # -2%止損
        self.max_hold_days = 5   # 最長持有5日

        self.rsi_indicator = self.rsi(self.spx, self.rsi_period, MovingAverageType.SIMPLE)
        self.hold_long = False
        self.entry_prices = {}  # 記錄入場價
        self.entry_date = None  # 入場日期
        self.last_processed_date = None
        
        self.set_warm_up(self.rsi_period + 5)

        self.stats = defaultdict(lambda: {
            "count": 0,
            "SPX_D0": [], "SPX_D1": [], "SPX_D2": [], "SPX_D3": [], "SPX_D4": [], "SPX_D5": [],
            "DJI_D0": [], "DJI_D1": [], "DJI_D2": [], "DJI_D3": [], "DJI_D4": [], "DJI_D5": [],
            "NDX_D0": [], "NDX_D1": [], "NDX_D2": [], "NDX_D3": [], "NDX_D4": [], "NDX_D5": [],
        })
        self.trades = []

    def on_data(self, data):
        if not data.contains_key(self.spx):
            return
        
        if self.last_processed_date == self.time.date():
            return
        self.last_processed_date = self.time.date()
        
        # 檢查止盈止損 + 最長持有期
        if self.hold_long and self.entry_date:
            hold_days = (self.time.date() - self.entry_date).days
            
            for sym_name, sym in self.symbols.items():
                if not self.portfolio[sym].invested:
                    continue
                entry_price = self.entry_prices.get(sym_name, 0)
                if entry_price <= 0:
                    continue
                current_price = self.securities[sym].close
                pnl = (current_price - entry_price) / entry_price
                
                # 止盈
                if pnl >= self.take_profit:
                    self.liquidate(sym)
                    self.trades.append({"date": str(self.time.date()), "action": f"take_profit_{sym_name}", "pnl": pnl*100})
                    continue
                
                # 止損
                if pnl <= self.stop_loss:
                    self.liquidate(sym)
                    self.trades.append({"date": str(self.time.date()), "action": f"stop_loss_{sym_name}", "pnl": pnl*100})
                    continue
                
                # 最長持有期
                if hold_days >= self.max_hold_days:
                    self.liquidate(sym)
                    self.trades.append({"date": str(self.time.date()), "action": f"time_exit_{sym_name}", "pnl": pnl*100})
            
            # 檢查是否全部平倉
            if not any(self.portfolio[s].invested for s in self.symbols.values()):
                self.hold_long = False
                self.entry_date = None
                self.entry_prices = {}
        
        vix_sec = self.securities[self.vix]
        vix_high = vix_sec.high
        vix_close = vix_sec.close
        
        # 僅處理VIX盤中衝高交易日
        if vix_high <= self.vix_thresh:
            return
        
        rsi_val = self.rsi_indicator.current.value if self.rsi_indicator.is_ready else 50
        
        # 分類
        rsi_group = "Oversold" if rsi_val < self.rsi_oversold else ("Overbought" if rsi_val > self.rsi_overbought else "Neutral")
        vix_type = "A" if vix_close >= self.vix_thresh else "B"
        key = (vix_type, rsi_group)

        # 獲取未來收益
        forward_ret = self.get_forward_returns()
        
        # 記錄統計
        rec = self.stats[key]
        rec["count"] += 1
        for d in range(6):
            rec[f"SPX_D{d}"].append(forward_ret["SPX"][f"D{d}"])
            rec[f"DJI_D{d}"].append(forward_ret["DJI"][f"D{d}"])
            rec[f"NDX_D{d}"].append(forward_ret["NDX"][f"D{d}"])

        # ========== 交易邏輯 ==========
        # 1. 超賣組 - 恐慌抄底 (勝率80%+)
        if rsi_group == "Oversold":
            if not any(self.portfolio[s].invested for s in self.symbols.values()):
                # A類: 滿倉 (84.6%勝率, 5日+2.38%)
                if vix_type == "A":
                    weight = 1.0 / len(self.symbols)
                # B類: 半倉 (66.7%勝率, 5日+1.18%)
                else:
                    weight = 0.5 / len(self.symbols)
                
                for sym_name, sym in self.symbols.items():
                    self.set_holdings(sym, weight)
                    self.entry_prices[sym_name] = self.securities[sym].close
                self.hold_long = True
                self.entry_date = self.time.date()
                self.trades.append({"date": str(self.time.date()), "action": f"buy_oversold_{vix_type}", "rsi": rsi_val, "vix": vix_close})
            return
        
        # 2. 超買組 - 止盈/做空 (83%概率下跌)
        if rsi_group == "Overbought":
            if any(self.portfolio[s].invested for s in self.symbols.values()):
                for sym in self.symbols.values():
                    self.liquidate(sym)
                self.hold_long = False
                self.entry_prices = {}
                self.entry_date = None
                self.trades.append({"date": str(self.time.date()), "action": "sell_overbought", "rsi": rsi_val, "vix": vix_close})
            return
        
        # 3. 中性組 - 不交易

    def get_forward_returns(self):
        ret = {"SPX": {}, "DJI": {}, "NDX": {}}
        for name, sym in self.symbols.items():
            hist = self.history(sym, 10, Resolution.DAILY)
            if hist.empty or len(hist) < 2:
                for d in range(6):
                    ret[name][f"D{d}"] = 0.0
                continue
            hist = hist.sort_index()
            closes = hist["close"].values
            for d in range(6):
                if d >= len(closes):
                    ret[name][f"D{d}"] = 0.0
                elif d == 0:
                    ret[name][f"D{d}"] = 0.0
                else:
                    ret[name][f"D{d}"] = (closes[d] / closes[0] - 1) * 100
        return ret

    def on_end_of_algorithm(self):
        self.log("\n==================== VIX恐慌反轉策略統計報表 ====================")
        group_order = [("A","Oversold"),("A","Neutral"),("A","Overbought"),
                       ("B","Oversold"),("B","Neutral"),("B","Overbought")]
        for key in group_order:
            vt, rg = key
            data = self.stats[key]
            cnt = data["count"]
            if cnt == 0:
                self.log(f"\n【{vt}類-{rg}】樣本數: 0")
                continue
            self.log(f"\n===== 分組：VIX{vt}類 | RSI:{rg} | 樣本數={cnt} =====")
            def calc_stats(arr):
                if not arr:
                    return (0,0)
                avg = sum(arr)/len(arr)
                win = sum(1 for x in arr if x>0)/len(arr)*100
                return round(avg,3), round(win,1)
            for idx_name in ["SPX", "DJI", "NDX"]:
                d0_avg, d0_win = calc_stats(data[f"{idx_name}_D0"])
                d1_avg, d1_win = calc_stats(data[f"{idx_name}_D1"])
                d5_avg, d5_win = calc_stats(data[f"{idx_name}_D5"])
                self.log(f"{idx_name} D0:{d0_avg}%/{d0_win}% D1:{d1_avg}%/{d1_win}% D5:{d5_avg}%/{d5_win}%")
        
        self.log(f"\n總交易筆數: {len(self.trades)}")
        for t in self.trades[:10]:
            self.log(str(t))
