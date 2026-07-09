from AlgorithmImports import *

class RiskManagedMomentumStrategy(QCAlgorithm):
    """
    风险管理版动量策略 (Risk-Managed Momentum Strategy)
    
    在优化动量策略基础上添加：
    1. 仓位管理（根据波动率动态调整）
    2. 单日最大亏损限制
    3. 组合层面止损
    4. 最大回撤熔断机制
    5. 波动率缩放仓位
    """

    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 策略参数
        self.lookback = int(self.get_parameter("lookback", 15))
        self.adx_threshold = int(self.get_parameter("adx_threshold", 15))
        self.stop_loss_pct = float(self.get_parameter("stop_loss_pct", 0.05))
        self.trailing_stop = float(self.get_parameter("trailing_stop", 0.05))
        
        # 风险管理参数（放宽限制）
        self.max_position_pct = float(self.get_parameter("max_position_pct", 0.95))  # 最大95%仓位
        self.max_daily_loss_pct = float(self.get_parameter("max_daily_loss_pct", 0.05))  # 单日最大亏损5%
        self.max_drawdown_pct = float(self.get_parameter("max_drawdown_pct", 0.20))  # 组合最大回撤20%
        self.volatility_lookback = int(self.get_parameter("volatility_lookback", 20))  # 波动率计算周期
        self.target_volatility = float(self.get_parameter("target_volatility", 0.20))  # 目标年化波动率20%
        
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
        self.log(f"风险管理策略初始化:")
        self.log(f"  策略: Lookback={self.lookback}, ADX={self.adx_threshold}, Stop={self.stop_loss_pct}")
        self.log(f"  风控: MaxPos={self.max_position_pct:.0%}, MaxDailyLoss={self.max_daily_loss_pct:.1%}, "
                f"MaxDD={self.max_drawdown_pct:.0%}, TargetVol={self.target_volatility:.0%}")

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
        
        # 2. 计算当前波动率（年化）
        current_volatility = self._calculate_volatility()
        
        # 3. 计算波动率缩放因子
        vol_scale = 1.0
        if current_volatility > 0:
            vol_scale = self.target_volatility / current_volatility
            vol_scale = min(1.5, max(0.3, vol_scale))  # 限制在0.3-1.5倍
        
        # 4. 检查组合最大回撤熔断
        if self.portfolio_peak is None or self.portfolio.total_portfolio_value > self.portfolio_peak:
            self.portfolio_peak = self.portfolio.total_portfolio_value
            self.drawdown_triggered = False
        
        current_drawdown = (self.portfolio_peak - self.portfolio.total_portfolio_value) / self.portfolio_peak
        if current_drawdown > self.max_drawdown_pct:
            if not self.drawdown_triggered:
                self.drawdown_triggered = True
                self.log(f"⚠️ 回撤熔断触发: 当前回撤={current_drawdown:.1%}, 阈值={self.max_drawdown_pct:.0%}")
            if self.portfolio.invested:
                self.liquidate(self.symbol)
                self.log(f"清仓: 回撤熔断")
                self._reset_state()
                return
        
        # 5. 检查单日最大亏损
        if self.daily_start_value and self.daily_start_value > 0:
            daily_return = (self.portfolio.total_portfolio_value - self.daily_start_value) / self.daily_start_value
            if daily_return < -self.max_daily_loss_pct:
                if not self.daily_loss_triggered:
                    self.daily_loss_triggered = True
                    self.log(f"⚠️ 单日亏损限制触发: {daily_return:.1%}")
                if self.portfolio.invested:
                    self.liquidate(self.symbol)
                    self.log(f"清仓: 单日亏损限制")
                    self._reset_state()
                    return
        
        # === 策略逻辑 ===
        
        highest_high = max(self.price_history[-self.lookback:])
        lowest_low = min(self.price_history[-self.lookback:])
        adx_val = self.adx.current.value
        
        # 已有持仓：检查退出条件
        if self.portfolio.invested:
            # 更新最高价
            if self.highest_price is None or price > self.highest_price:
                self.highest_price = price
            
            # 1. 固定止损
            if self.entry_price and price < self.entry_price * (1 - self.stop_loss_pct):
                self.liquidate(self.symbol)
                self.log(f"止损: 价格={price:.2f}")
                self._reset_state()
                return
            
            # 2. Trailing Stop
            if self.highest_price and price < self.highest_price * (1 - self.trailing_stop):
                self.liquidate(self.symbol)
                self.log(f"Trailing Stop: 价格={price:.2f}")
                self._reset_state()
                return
            
            # 3. 跌破低点退出
            if price < lowest_low * 1.01:
                self.liquidate(self.symbol)
                self.log(f"跌破低点退出: 价格={price:.2f}")
                self._reset_state()
                return
        
        # 无持仓：检查入场条件
        else:
            # 如果有熔断，不允许新入场
            if self.drawdown_triggered or self.daily_loss_triggered:
                return
            
            # 突破N日高点 + ADX趋势强
            if price > highest_high * 0.995 and adx_val > self.adx_threshold:
                # 计算波动率调整后的仓位
                base_position = 1.0
                adjusted_position = base_position * vol_scale
                
                # 应用最大仓位限制
                final_position = min(adjusted_position, self.max_position_pct)
                
                self.set_holdings(self.symbol, final_position)
                self.entry_price = price
                self.highest_price = price
                self.is_invested = True
                
                self.log(f"买入: 价格={price:.2f}, ADX={adx_val:.1f}, "
                        f"波动率={current_volatility:.1%}, 缩放={vol_scale:.2f}, "
                        f"仓位={final_position:.0%}")

    def _calculate_volatility(self):
        """计算年化波动率"""
        if len(self.price_history) < self.volatility_lookback:
            return 0.15  # 默认15%
        
        # 计算日收益率
        returns = []
        for i in range(1, len(self.price_history)):
            ret = (self.price_history[i] - self.price_history[i-1]) / self.price_history[i-1]
            returns.append(ret)
        
        if len(returns) < 2:
            return 0.15
        
        # 计算标准差并年化
        import statistics
        daily_vol = statistics.stdev(returns)
        annual_vol = daily_vol * (252 ** 0.5)  # 假设252个交易日
        
        return annual_vol

    def _reset_state(self):
        self.entry_price = None
        self.highest_price = None
        self.is_invested = False

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.log(f"订单: {order_event.symbol} {order_event.direction} "
                    f"{order_event.fill_quantity} @ {order_event.fill_price:.2f}")

    def on_end_of_algorithm(self):
        self.log(f"策略结束: 最终权益={self.portfolio.total_portfolio_value:.2f}")
