from AlgorithmImports import *

class MeanReversionStrategy(QCAlgorithm):
    """
    均值回归策略 (Mean Reversion / RSI Strategy)
    
    策略逻辑：
    - RSI < 30（超卖）→ 买入（价格低于均值，预期回归）
    - RSI > 70（超买）→ 卖出（价格高于均值，预期回归）
    - 添加布林带确认波动区间
    """

    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 参数
        self.rsi_period = int(self.get_parameter("rsi_period", 14))
        self.rsi_oversold = int(self.get_parameter("rsi_oversold", 30))
        self.rsi_overbought = int(self.get_parameter("rsi_overbought", 70))
        self.bb_period = int(self.get_parameter("bb_period", 20))
        self.bb_std = float(self.get_parameter("bb_std", 2.0))
        self.max_hold_days = int(self.get_parameter("max_hold_days", 20))
        self.stop_loss_pct = float(self.get_parameter("stop_loss_pct", 0.05))
        
        # 添加标的
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        
        # 指标 - 使用正确的Lean API
        self.rsi_indicator = self.rsi(self.symbol, self.rsi_period, MovingAverageType.WILDERS, Resolution.DAILY)
        # 布林带通过SMA和StdDev计算
        self.bb_middle = self.sma(self.symbol, self.bb_period, Resolution.DAILY)
        self.bb_std_dev = self.std(self.symbol, self.bb_period, Resolution.DAILY)
        
        # Warm-up
        self.set_warm_up(self.bb_period + 10)
        
        # 状态
        self.entry_price = None
        self.entry_date = None
        self.is_invested = False
        
        self.log(f"均值回归策略初始化: RSI({self.rsi_period}), "
                  f"超卖={self.rsi_oversold}, 超买={self.rsi_overbought}")

    def on_data(self, data: Slice):
        # 检查指标准备就绪
        if not self.rsi_indicator.is_ready or not self.bb_middle.is_ready or not self.bb_std_dev.is_ready:
            return
        
        if self.symbol not in data.bars:
            return
        
        price = data.bars[self.symbol].close
        rsi_val = self.rsi_indicator.current.value
        middle = self.bb_middle.current.value
        std_dev = self.bb_std_dev.current.value
        bb_upper = middle + self.bb_std * std_dev
        bb_lower = middle - self.bb_std * std_dev
        
        # 已有持仓：检查退出条件
        if self.portfolio.invested:
            # 1. 止损
            if self.entry_price and price < self.entry_price * (1 - self.stop_loss_pct):
                self.liquidate(self.symbol)
                self.log(f"止损退出: 价格={price:.2f}, 入场={self.entry_price:.2f}")
                self._reset_state()
                return
            
            # 2. RSI超买退出
            if rsi_val > self.rsi_overbought:
                self.liquidate(self.symbol)
                self.log(f"RSI超买退出: 价格={price:.2f}, RSI={rsi_val:.1f}")
                self._reset_state()
                return
            
            # 3. 时间退出
            if self.entry_date:
                hold_days = (self.time - self.entry_date).days
                if hold_days >= self.max_hold_days:
                    self.liquidate(self.symbol)
                    self.log(f"时间退出: 持有{hold_days}天")
                    self._reset_state()
                    return
            
            # 4. 价格触及布林带上轨
            if price > bb_upper:
                self.liquidate(self.symbol)
                self.log(f"触及上轨退出: 价格={price:.2f}, 上轨={bb_upper:.2f}")
                self._reset_state()
                return
        
        # 无持仓：检查入场条件
        else:
            # 入场条件：
            # 1. RSI < 超卖阈值（超卖）
            # 2. 价格触及或跌破布林带下轨
            if (rsi_val < self.rsi_oversold and      # RSI超卖
                price <= bb_lower * 1.01):          # 价格在下轨附近
                
                # 动态仓位：RSI越低，仓位越大
                position_size = min(1.0, (self.rsi_oversold - rsi_val) / 20 + 0.5)
                self.set_holdings(self.symbol, position_size)
                
                self.entry_price = price
                self.entry_date = self.time
                self.is_invested = True
                self.log(f"买入(均值回归): 价格={price:.2f}, RSI={rsi_val:.1f}, "
                        f"下轨={bb_lower:.2f}, 仓位={position_size:.0%}")

    def _reset_state(self):
        self.entry_price = None
        self.entry_date = None
        self.is_invested = False

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.log(f"订单执行: {order_event.symbol} {order_event.direction} "
                    f"{order_event.fill_quantity} @ {order_event.fill_price:.2f}")

    def on_end_of_algorithm(self):
        self.log(f"策略结束: 最终权益={self.portfolio.total_portfolio_value:.2f}")
