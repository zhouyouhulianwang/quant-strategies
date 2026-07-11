from AlgorithmImports import *
from collections import defaultdict
import pandas as pd
import numpy as np


class VixPanicStatAndTrade(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2026, 7, 10)
        self.set_cash(100000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)

        # 標的 (使用VXX ETF替代VIX指數，因為QC雲端無VIX指數數據)
        self.spx = self.add_equity("SPY", Resolution.DAILY).symbol
        self.dji = self.add_equity("DIA", Resolution.DAILY).symbol
        self.ndx = self.add_equity("QQQ", Resolution.DAILY).symbol
        self.vix = self.add_equity("VXX", Resolution.DAILY).symbol
        self.symbols = {"SPX": self.spx, "DJI": self.dji, "NDX": self.ndx}

        # 參數設定 (根據統計規律優化)
        self.vix_thresh = 20  # VXX對應VIX=30的代理閾值
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70

        # SPX 14日RSI
        self.rsi_indicator = self.rsi(self.spx, self.rsi_period, MovingAverageType.SIMPLE)
        
        # 持有信號
        self.hold_long = False
        self.last_processed_date = None
        
        # WarmUp
        self.set_warm_up(self.rsi_period + 5)

        # 統計存儲
        self.stats = defaultdict(lambda: {
            "count": 0,
            "SPX_D0": [], "SPX_D1": [], "SPX_D2": [], "SPX_D3": [], "SPX_D4": [], "SPX_D5": [],
            "DJI_D0": [], "DJI_D1": [], "DJI_D2": [], "DJI_D3": [], "DJI_D4": [], "DJI_D5": [],
            "NDX_D0": [], "NDX_D1": [], "NDX_D2": [], "NDX_D3": [], "NDX_D4": [], "NDX_D5": [],
        })
        
        # 交易記錄
        self.trades = []

    def on_data(self, data):
        if not data.contains_key(self.spx):
            return
        
        if self.last_processed_date == self.time.date():
            return
        self.last_processed_date = self.time.date()
        
        # 平倉昨日抄底單
        if self.hold_long:
            for sym in self.symbols.values():
                self.liquidate(sym)
            self.hold_long = False
        
        vix_sec = self.securities[self.vix]
        vix_high = vix_sec.high
        vix_close = vix_sec.close
        
        # 僅處理VIX盤中衝高交易日
        if vix_high <= self.vix_thresh:
            return
        
        # 獲取RSI
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
        
        # ========== 交易邏輯 (基於統計規律) ==========
        # 1. 超買組 - 見頂止盈/做空 (RSI>70，VIX>30)
        if rsi_group == "Overbought":
            if any(self.portfolio[s].invested for s in self.symbols.values()):
                for sym in self.symbols.values():
                    self.liquidate(sym)
                self.trades.append({"date": str(self.time.date()), "action": "sell_overbought", "rsi": rsi_val, "vix_close": vix_close})
            return
        
        # 2. 超賣組 - 恐慌抄底 (RSI<30，VIX>30)
        if rsi_group == "Oversold":
            # A類: 持續恐慌，重倉 (勝率84.6%，5日+2.38%)
            if vix_type == "A" and not any(self.portfolio[s].invested for s in self.symbols.values()):
                weight = 1.0 / len(self.symbols)  # 均分滿倉
                for sym in self.symbols.values():
                    self.set_holdings(sym, weight)
                self.hold_long = True
                self.trades.append({"date": str(self.time.date()), "action": "buy_oversold_A", "rsi": rsi_val, "vix_close": vix_close})
            
            # B類: 脉冲恐慌，輕倉 (勝率66.7%，5日+1.18%)
            elif vix_type == "B" and not any(self.portfolio[s].invested for s in self.symbols.values()):
                weight = 0.5 / len(self.symbols)  # 半倉
                for sym in self.symbols.values():
                    self.set_holdings(sym, weight)
                self.hold_long = True
                self.trades.append({"date": str(self.time.date()), "action": "buy_oversold_B", "rsi": rsi_val, "vix_close": vix_close})
            return
        
        # 3. 中性組 - 不交易 (無明確趨勢)

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
