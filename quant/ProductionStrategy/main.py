from AlgorithmImports import *

class ProductionMomentumStrategy(QCAlgorithm):
    """
    生产环境动量策略 (Production-Ready Momentum Strategy)
    
    版本: 1.0.0
    日期: 2026-07-07
    作者: Qs
    
    策略逻辑:
    - 突破N日高点 + ADX趋势确认 → 买入
    - 跌破N日低点或止损 → 卖出
    
    风险管理:
    - 波动率缩放仓位
    - 单日亏损限制
    - 最大回撤熔断
    - 最大仓位限制
    """

    def initialize(self):
        self.set_start_date(2016, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 策略参数
        self.lookback = int(self.get_parameter("lookback", 15))
        self.adx_threshold = int(self.get_parameter("adx_threshold", 15))
        self.stop_loss_pct = float(self.get_parameter("stop_loss_pct", 0.05))
        self.trailing_stop = float(self.get_parameter("trailing_stop", 0.05))
        
        # 风险管理参数
        self.max_position_pct = float(self.get_parameter("max_position_pct", 0.95))
        self.max_daily_loss_pct = float(self.get_parameter("max_daily_loss_pct", 0.05))
        self.max_drawdown_pct = float(self.get_parameter("max_drawdown_pct", 0.20))
        self.volatility_lookback = int(self.get_parameter("volatility_lookback", 20))
        self.target_volatility = float(self.get_parameter("target_volatility", 0.20))
        
        # 添加标的
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        
        # 指标
        self.adx = self.adx(self.symbol, 14, Resolution.DAILY)
        self.price_history = []
        
        # Warm-up
        self.set_warm_up(self.lookback + self.volatility_lookback + 10)
        
        # 状态
        self.entry_price = None
        self.highest_price = None
        self.is_invested = False
        self.daily_start_value = None
        self.daily_loss_triggered = False
        self.portfolio_peak = None
        self.drawdown_triggered = False
        
        # 记录
        self.log(f"Production Strategy v1.0.0 initialized")
        self.log(f"Strategy: Lookback={self.lookback}, ADX={self.adx_threshold}, Stop={self.stop_loss_pct}")
        self.log(f"Risk: MaxPos={self.max_position_pct:.0%}, MaxDailyLoss={self.max_daily_loss_pct:.1%}, MaxDD={self.max_drawdown_pct:.0%}")

    def on_data(self, data: Slice):
        if not self.adx.is_ready:
            return
        
        if self.symbol not in data.bars:
            return
        
        price = data.bars[self.symbol].close
        
        # 更新历史价格
        self.price_history.append(price)
        if len(self.price_history) > max(self.lookback, self.volatility_lookback):
            self.price_history.pop(0)
        
        if len(self.price_history) < self.lookback:
            return
        
        # === 风险管理检查 ===
        
        # 1. 检查是否需要重置每日统计
        if self.daily_start_value is None or self.time.date() != getattr(self, '_last_date', None):
            self.daily_start_value = self.portfolio.total_portfolio_value
            self.daily_loss_triggered = False
            self._last_date = self.time.date()
        
        # 2. 计算当前波动率
        current_volatility = self._calculate_volatility()
        
        # 3. 波动率缩放
        vol_scale = 1.0
        if current_volatility > 0:
            vol_scale = self.target_volatility / current_volatility
            vol_scale = min(1.5, max(0.3, vol_scale))
        
        # 4. 检查组合最大回撤熔断
        if self.portfolio_peak is None or self.portfolio.total_portfolio_value > self.portfolio_peak:
            self.portfolio_peak = self.portfolio.total_portfolio_value
            self.drawdown_triggered = False
        
        current_drawdown = (self.portfolio_peak - self.portfolio.total_portfolio_value) / self.portfolio_peak
        if current_drawdown > self.max_drawdown_pct:
            if not self.drawdown_triggered:
                self.drawdown_triggered = True
                self.log(f"DRAWDOWN CIRCUIT BREAKER: {current_drawdown:.1%}")
            if self.portfolio.invested:
                self.liquidate(self.symbol)
                self.log(f"LIQUIDATED: Drawdown circuit breaker")
                self._reset_state()
                return
        
        # 5. 检查单日最大亏损
        if self.daily_start_value and self.daily_start_value > 0:
            daily_return = (self.portfolio.total_portfolio_value - self.daily_start_value) / self.daily_start_value
            if daily_return < -self.max_daily_loss_pct:
                if not self.daily_loss_triggered:
                    self.daily_loss_triggered = True
                    self.log(f"DAILY LOSS LIMIT: {daily_return:.1%}")
                if self.portfolio.invested:
                    self.liquidate(self.symbol)
                    self.log(f"LIQUIDATED: Daily loss limit")
                    self._reset_state()
                    return
        
        # === 策略逻辑 ===
        
        highest_high = max(self.price_history[-self.lookback:])
        lowest_low = min(self.price_history[-self.lookback:])
        adx_val = self.adx.current.value
        
        # 已有持仓：检查退出条件
        if self.portfolio.invested:
            if self.highest_price is None or price > self.highest_price:
                self.highest_price = price
            
            # 1. 固定止损
            if self.entry_price and price < self.entry_price * (1 - self.stop_loss_pct):
                self.liquidate(self.symbol)
                self.log(f"STOP LOSS: Price={price:.2f}")
                self._reset_state()
                return
            
            # 2. Trailing Stop
            if self.highest_price and price < self.highest_price * (1 - self.trailing_stop):
                self.liquidate(self.symbol)
                self.log(f"TRAILING STOP: Price={price:.2f}")
                self._reset_state()
                return
            
            # 3. 跌破低点退出
            if price < lowest_low * 1.01:
                self.liquidate(self.symbol)
                self.log(f"LOW BREAK: Price={price:.2f}")
                self._reset_state()
                return
        
        # 无持仓：检查入场条件
        else:
            if self.drawdown_triggered or self.daily_loss_triggered:
                return
            
            if price > highest_high * 0.995 and adx_val > self.adx_threshold:
                base_position = 1.0
                adjusted_position = base_position * vol_scale
                final_position = min(adjusted_position, self.max_position_pct)
                
                self.set_holdings(self.symbol, final_position)
                self.entry_price = price
                self.highest_price = price
                self.is_invested = True
                
                self.log(f"BUY: Price={price:.2f}, ADX={adx_val:.1f}, Vol={current_volatility:.1%}, "
                        f"Scale={vol_scale:.2f}, Position={final_position:.0%}")

    def _calculate_volatility(self):
        """Calculate annualized volatility"""
        if len(self.price_history) < self.volatility_lookback:
            return 0.20
        
        returns = []
        for i in range(1, len(self.price_history)):
            ret = (self.price_history[i] - self.price_history[i-1]) / self.price_history[i-1]
            returns.append(ret)
        
        if len(returns) < 2:
            return 0.20
        
        import statistics
        daily_vol = statistics.stdev(returns)
        annual_vol = daily_vol * (252 ** 0.5)
        
        return annual_vol

    def _reset_state(self):
        self.entry_price = None
        self.highest_price = None
        self.is_invested = False

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.log(f"ORDER: {order_event.symbol} {order_event.direction} "
                    f"Qty={order_event.fill_quantity} Price={order_event.fill_price:.2f}")

    def on_end_of_algorithm(self):
        self.log(f"ALGORITHM END: Final Equity=${self.portfolio.total_portfolio_value:.2f}")
