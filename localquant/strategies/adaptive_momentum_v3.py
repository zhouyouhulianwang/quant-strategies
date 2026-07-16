"""AdaptiveMomentumV3_1 LocalQuant 适配版
保留核心逻辑：多周期动量、RSI调整、板块轮动、VIX市场状态、回撤保护
简化：限价单→市价单，日内执行→日终执行
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

from localquant.strategy import BaseStrategy
from localquant.strategy.indicators import rsi, sma

# 板块映射
SECTOR_MAP = {
    "AAPL": "Tech", "MSFT": "Tech", "GOOGL": "Tech", "AMZN": "Consumer", "NVDA": "Tech",
    "TSLA": "Tech", "META": "Tech", "NFLX": "Tech", "AMD": "Tech", "INTC": "Tech",
    "JPM": "Finance", "BAC": "Finance", "WFC": "Finance", "GS": "Finance", "MS": "Finance",
    "JNJ": "Healthcare", "PFE": "Healthcare", "UNH": "Healthcare", "LLY": "Healthcare", "ABBV": "Healthcare",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "EOG": "Energy", "SLB": "Energy",
    "CAT": "Industrial", "BA": "Industrial", "HON": "Industrial", "GE": "Industrial", "RTX": "Industrial",
    "WMT": "Consumer", "COST": "Consumer", "HD": "Consumer", "LOW": "Consumer", "TGT": "Consumer",
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "AEP": "Utilities", "SRE": "Utilities",
    "PLD": "REITs", "AMT": "REITs", "EQIX": "REITs", "PSA": "REITs", "O": "REITs",
    "VZ": "Telecom", "T": "Telecom", "TMUS": "Telecom", "CCI": "Telecom", "SBAC": "Telecom",
    "LIN": "Materials", "APD": "Materials", "SHW": "Materials", "FCX": "Materials", "NEM": "Materials",
    "SPY": "Index", "QQQ": "Index", "TLT": "Safe", "GLD": "Safe"
}

# 扩展标的
ALL_TICKERS = list(SECTOR_MAP.keys())

class AdaptiveMomentumV3(BaseStrategy):
    """AdaptiveMomentumV3.1 LocalQuant 适配版"""
    
    def __init__(self, symbols=None, **kwargs):
        super().__init__()
        
        # 标的
        self.symbols = symbols or ALL_TICKERS[:20]  # 默认20只，避免数据量太大
        self.safe_assets = ["TLT", "GLD"]
        self.spy = "SPY"
        
        # 动量参数
        self.lookback_periods = {'1d': 1, '1w': 5, '2w': 10, '1m': 21, '3m': 63, '6m': 126}
        self.base_weights = {'1d': 0.1, '1w': 0.5, '2w': 1.0, '1m': 1.0, '3m': 0.7, '6m': 0.5}
        self.current_weights = self.base_weights.copy()
        
        # RSI 参数
        self.rsi_overbought = 65
        self.rsi_oversold = 35
        self.rsi_adjustment_factor = 0.4
        self.rsi_period = 14
        
        # VIX 参数
        self.vix_pause_level = 30.0
        self.vix_boost_level = 18.0
        self.vix_symbol = "VIXY"  # 用 VIXY 代替 VIX
        
        # 仓位管理
        self.max_position_pct = 0.15
        self.min_position_pct = 0.0
        self.max_stocks = 10
        self.min_score = 0.0
        self.max_total_exposure = 0.80
        self.min_total_exposure = 0.30
        self.current_total_exposure = self.min_total_exposure
        self.max_sector_pct = 0.50
        
        # 再平衡
        self.rebalance_freq = 5  # 每5个交易日（约1周）
        self._last_rebalance = None
        self._day_counter = 0
        
        # 风险管理
        self.stop_loss_pct = 0.08
        self.trailing_stop_enabled = True
        self.trailing_stop_pct = 0.10
        self.drawdown_trigger_level = 0.10
        self.drawdown_severe_level = 0.15
        self.drawdown_extreme_level = 0.20
        self.high_water_mark = 0
        self.drawdown_protection_triggered = False
        
        # 市场状态
        self.market_bear_mode = False
        self.bear_mode_confirm_days = 3
        self.bear_mode_counter = 0
        
        # 板块轮动
        self.sector_rotation_enabled = True
        self.n_top_sectors = 3
        self.sector_lookback = 30
        
        # 持仓跟踪
        self.position_entry_date = {}
        self.cost_basis = {}
        self.position_high = {}
        self.min_hold_days = 3
        
        # 流动性过滤
        self.liquid_stocks = set()
        self.liquid_stocks_initialized = False
        
        # 流动性阈值
        self.min_volume = 10000000
        
    def initialize(self):
        """初始化策略"""
        self.name = "AdaptiveMomentumV3.1"
        print(f"Strategy initialized: {self.name}")
        print(f"  Universe: {len(self.symbols)} symbols")
        print(f"  Max stocks: {self.max_stocks}")
        print(f"  Max position: {self.max_position_pct*100:.0f}%")
        print(f"  Rebalance: every {self.rebalance_freq} days")
        print(f"  Sector rotation: {self.sector_rotation_enabled}")
    
    def on_data(self, data):
        """每个数据 bar 触发"""
        super().on_data(data)
        
        timestamp = self.context.current_time
        self._day_counter += 1
        
        # 检查止损（每个bar）
        self._check_stop_loss()
        
        # 检查回撤保护（每个bar）
        self._check_drawdown()
        
        # 检查市场状态（每个bar）
        self._check_market_state()
        
        # 再平衡 - 基于实际时间差（支持分钟级/日线）
        if self._last_rebalance is None:
            self._last_rebalance = timestamp
            self._rebalance()
        else:
            # 使用实际时间差（天）
            days_since = (timestamp - self._last_rebalance).total_seconds() / 86400
            if days_since >= self.rebalance_freq:
                self._rebalance()
                self._last_rebalance = timestamp
    
    def _check_market_state(self):
        """检查市场状态（SPY 50SMA）"""
        if self.spy not in self.context.current_data:
            return
        
        spy_history = self.context.get_history(self.spy, 'close', 60)
        if len(spy_history) < 50:
            return
        
        spy_sma50 = sma(spy_history, 50).iloc[-1]
        spy_price = self.context.get_price(self.spy, 'close')
        
        if np.isnan(spy_sma50) or spy_price is None:
            return
        
        is_below = spy_price < spy_sma50
        
        if is_below:
            self.bear_mode_counter += 1
        else:
            self.bear_mode_counter = 0
        
        was_bear = self.market_bear_mode
        self.market_bear_mode = self.bear_mode_counter >= self.bear_mode_confirm_days
        
        if self.market_bear_mode:
            self.current_total_exposure = self.min_total_exposure
        else:
            dev = (spy_price - spy_sma50) / spy_sma50 if spy_sma50 > 0 else 0
            if dev > 0.05:
                self.current_total_exposure = self.max_total_exposure
            elif dev > 0.02:
                self.current_total_exposure = 0.60
            else:
                self.current_total_exposure = 0.45
        
        if self.market_bear_mode and not was_bear:
            print(f"[ALERT] Bear market: SPY={spy_price:.2f} < 50SMA={spy_sma50:.2f}")
            # 清仓并买入安全资产
            for symbol in list(self._engine.portfolio.positions.keys()):
                self.liquidate(symbol)
            for safe in self.safe_assets:
                if safe in self.context.current_data:
                    self.target_percent(safe, 0.5 / len(self.safe_assets))
        elif not self.market_bear_mode and was_bear:
            print(f"[ALERT] Bull market resumed: SPY={spy_price:.2f} > 50SMA={spy_sma50:.2f}")
            for safe in self.safe_assets:
                if safe in self._engine.portfolio.positions:
                    self.liquidate(safe)
    
    def _check_stop_loss(self):
        """检查止损和移动止损"""
        for symbol, cost in list(self.cost_basis.items()):
            if symbol not in self._engine.portfolio.positions:
                continue
            
            price = self.context.get_price(symbol, 'close')
            if price is None:
                continue
            
            # 止损
            if cost > 0 and (price - cost) / cost < -self.stop_loss_pct:
                if self._can_sell(symbol):
                    self.liquidate(symbol)
                    print(f"Stop-loss: {symbol} @ ${price:.2f}")
                    self._remove_position_tracking(symbol)
                    continue
            
            # 移动止损
            if self.trailing_stop_enabled and symbol in self.position_high:
                if price > self.position_high[symbol]:
                    self.position_high[symbol] = price
                high = self.position_high[symbol]
                if high > 0 and (price - high) / high < -self.trailing_stop_pct:
                    if self._can_sell(symbol):
                        self.liquidate(symbol)
                        print(f"Trailing stop: {symbol} @ ${price:.2f}")
                        self._remove_position_tracking(symbol)
    
    def _check_drawdown(self):
        """检查最大回撤保护"""
        current_value = self._engine.portfolio.total_value(self._get_current_prices())
        
        if current_value > self.high_water_mark:
            self.high_water_mark = current_value
            if self.drawdown_protection_triggered and current_value >= self.high_water_mark * 0.95:
                print(f"Drawdown recovered: ${current_value:,.2f}")
                self.drawdown_protection_triggered = False
        
        if self.high_water_mark <= 0:
            return
        
        drawdown = (current_value - self.high_water_mark) / self.high_water_mark
        
        if drawdown < -self.drawdown_extreme_level:
            if self.drawdown_protection_triggered != "extreme":
                self._execute_drawdown_protection("extreme", drawdown)
        elif drawdown < -self.drawdown_severe_level:
            if self.drawdown_protection_triggered not in ["severe", "extreme"]:
                self._execute_drawdown_protection("severe", drawdown)
        elif drawdown < -self.drawdown_trigger_level:
            if not self.drawdown_protection_triggered:
                self._execute_drawdown_protection("triggered", drawdown)
                for safe in self.safe_assets:
                    if safe in self.context.current_data:
                        self.target_percent(safe, 0.5 / len(self.safe_assets))
        elif drawdown > -0.05 and self.drawdown_protection_triggered:
            print(f"Drawdown recovered: {drawdown:.2%}")
            self.drawdown_protection_triggered = False
    
    def _execute_drawdown_protection(self, level, drawdown):
        """执行回撤保护"""
        print(f"[{'CRITICAL' if level=='extreme' else 'WARNING'}] Drawdown protection ({level}): {drawdown:.2%}")
        for symbol in list(self._engine.portfolio.positions.keys()):
            self.liquidate(symbol)
        self.drawdown_protection_triggered = level
    
    def _can_sell(self, symbol):
        """检查最小持仓天数"""
        if symbol not in self.position_entry_date:
            return True
        days = (self.context.current_time - self.position_entry_date[symbol]).days
        return days >= self.min_hold_days
    
    def _remove_position_tracking(self, symbol):
        """移除持仓跟踪"""
        self.cost_basis.pop(symbol, None)
        self.position_high.pop(symbol, None)
        self.position_entry_date.pop(symbol, None)
    
    def _get_current_prices(self):
        """获取当前价格字典"""
        prices = {}
        for symbol in self.symbols + self.safe_assets + [self.spy]:
            if symbol in self.context.current_data:
                prices[symbol] = self.context.current_data[symbol].get('close', 0)
        return prices
    
    def _update_liquidity(self):
        """更新流动性过滤"""
        self.liquid_stocks = set()
        min_vol = self.min_volume if not self.market_bear_mode else self.min_volume // 2
        
        for symbol in self.symbols:
            if symbol not in self.context.current_data:
                continue
            
            price = self.context.get_price(symbol, 'close')
            if price is None or price < 5.0:
                continue
            
            history = self.context.get_history(symbol, 'volume', 20)
            if len(history) >= 10 and history.mean() >= min_vol:
                self.liquid_stocks.add(symbol)
        
        print(f"Liquidity filter: {len(self.liquid_stocks)}/{len(self.symbols)} stocks")
    
    def _calculate_momentum_score(self, symbol):
        """计算动量得分"""
        max_period = max(self.lookback_periods.values()) + 20
        history = self.context.get_history(symbol, 'close', max_period)
        
        if len(history) < max(self.lookback_periods.values()):
            return None
        
        closes = history.values
        price = closes[-1]
        
        returns = {}
        for period, days in self.lookback_periods.items():
            if len(closes) >= days:
                returns[period] = (price - closes[-days]) / closes[-days]
            else:
                returns[period] = 0
        
        base_score = sum(returns[p] * self.current_weights[p] for p in returns)
        
        # RSI 调整
        rsi_adj_score = base_score
        rsi_val = rsi(history, self.rsi_period).iloc[-1]
        if not np.isnan(rsi_val):
            if rsi_val > self.rsi_overbought:
                rsi_adj_score = base_score * self.rsi_adjustment_factor
            elif rsi_val < self.rsi_oversold and base_score > 0:
                rsi_adj_score = base_score * (2.0 - self.rsi_adjustment_factor)
        
        return {'score': rsi_adj_score, 'base_score': base_score, 'price': price}
    
    def _get_top_sectors(self):
        """获取动量最高的板块"""
        sector_returns = {}
        for symbol in self.symbols:
            if symbol not in self.context.current_data:
                continue
            
            sector = SECTOR_MAP.get(symbol, 'Other')
            history = self.context.get_history(symbol, 'close', self.sector_lookback + 5)
            
            if len(history) >= self.sector_lookback:
                ret = (history.iloc[-1] - history.iloc[0]) / history.iloc[0]
                sector_returns.setdefault(sector, []).append(ret)
        
        sector_momentum = {s: sum(r)/len(r) for s, r in sector_returns.items() if r}
        sorted_sectors = sorted(sector_momentum.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_sectors[:self.n_top_sectors]]
    
    def _limit_sector_concentration(self, targets):
        """限制板块集中度"""
        if not self.sector_rotation_enabled:
            return targets
        
        sector_weights = {}
        for symbol, weight in targets.items():
            sector = SECTOR_MAP.get(symbol, 'Other')
            sector_weights[sector] = sector_weights.get(sector, 0) + weight
        
        adjusted = targets.copy()
        for sector, total in sector_weights.items():
            if total > self.max_sector_pct:
                scale = self.max_sector_pct / total
                for symbol in list(adjusted.keys()):
                    if SECTOR_MAP.get(symbol, 'Other') == sector:
                        adjusted[symbol] *= scale
        
        return adjusted
    
    def _rebalance(self):
        """执行再平衡"""
        print(f"\n[{self.context.current_time.date()}] Rebalancing...")
        
        if self.market_bear_mode:
            print("Bear mode: skipping equity rebalance")
            return
        
        if not self.liquid_stocks_initialized:
            self._update_liquidity()
            self.liquid_stocks_initialized = True
        
        if self._day_counter % 20 == 0:
            self._update_liquidity()
        
        # 板块筛选
        if self.sector_rotation_enabled:
            top_sectors = self._get_top_sectors()
            if not top_sectors:
                top_sectors = ['Other']
            if 'Other' not in top_sectors:
                top_sectors.append('Other')
            
            eligible_symbols = [s for s in self.symbols 
                             if s in self.liquid_stocks and 
                             (SECTOR_MAP.get(s, 'Other') in top_sectors or s in ['SPY', 'QQQ', 'TLT', 'GLD'])]
        else:
            eligible_symbols = [s for s in self.symbols if s in self.liquid_stocks]
        
        # 计算动量得分
        scores = {}
        for symbol in eligible_symbols:
            result = self._calculate_momentum_score(symbol)
            if result and result['score'] > self.min_score:
                scores[symbol] = result
        
        if not scores:
            print("No valid momentum scores")
            return
        
        # 排序并选择 Top N
        sorted_scores = sorted(scores.items(), key=lambda x: x[1]['score'], reverse=True)
        top_stocks = sorted_scores[:self.max_stocks]
        
        # 按得分权重分配
        total_score = sum(d['score'] for _, d in top_stocks)
        targets = {}
        for symbol, data in top_stocks:
            weight = data['score'] / total_score if total_score > 0 else 0
            targets[symbol] = weight
        
        # 限制最大仓位
        max_w = max(targets.values()) if targets else 0
        if max_w > self.max_position_pct:
            scale = self.max_position_pct / max_w
            for sym in targets:
                targets[sym] *= scale
        
        # 过滤最小仓位
        targets = {s: w for s, w in targets.items() if w >= self.min_position_pct}
        total_w = sum(targets.values())
        
        # 限制总仓位
        if total_w > self.current_total_exposure:
            scale = self.current_total_exposure / total_w
            for sym in targets:
                targets[sym] *= scale
        
        # 限制板块集中度
        targets = self._limit_sector_concentration(targets)
        
        final_w = sum(targets.values())
        top5 = sorted(targets.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"  {len(targets)} stocks, total={final_w*100:.1f}%, top5={[(s,round(w*100,1)) for s,w in top5]}")
        
        # 清仓不在目标中的
        for symbol in list(self._engine.portfolio.positions.keys()):
            if symbol not in targets and symbol not in self.safe_assets:
                if self._can_sell(symbol):
                    self.liquidate(symbol)
                    self._remove_position_tracking(symbol)
                    print(f"  SELL {symbol} (not in top)")
        
        # 调整目标仓位
        for symbol, target in targets.items():
            current_prices = self._get_current_prices()
            total_value = self._engine.portfolio.total_value(current_prices)
            
            # 获取当前持仓价值
            current_value = 0
            if symbol in self._engine.portfolio.positions:
                price = self.context.get_price(symbol, 'close') or 0
                current_value = self._engine.portfolio.positions[symbol].quantity * price
            
            current_w = current_value / total_value if total_value > 0 else 0
            
            if abs(current_w - target) > 0.05:  # 5% 阈值
                self.target_percent(symbol, target)
                if symbol not in self.cost_basis:
                    self.cost_basis[symbol] = self.context.get_price(symbol, 'close') or 0
                if symbol not in self.position_high:
                    self.position_high[symbol] = self.context.get_price(symbol, 'close') or 0
                if symbol not in self.position_entry_date:
                    self.position_entry_date[symbol] = self.context.current_time
                print(f"  BUY {symbol} target={target*100:.1f}%")
