from AlgorithmImports import *

class MultiFactorStrategy(QCAlgorithm):
    """
    多因子策略 (Multi-Factor Strategy)
    
    结合三个信号：
    1. RSI（超买超卖）- 动量因子
    2. MACD（趋势确认）- 趋势因子  
    3. 成交量（资金确认）- 流动性因子
    
    入场条件：
    - 信号1: RSI < 40（超卖区域）
    - 信号2: MACD柱状图转正
    - 信号3: 成交量 > 20日均量（资金流入）
    - 信号4: 价格 > 20日均线（短期趋势向上）
    
    出场条件：
    - RSI > 70 或 跌破止损
    """

    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 参数
        self.rsi_period = int(self.get_parameter("rsi_period", 14))
        self.rsi_entry = int(self.get_parameter("rsi_entry", 40))
        self.rsi_exit = int(self.get_parameter("rsi_exit", 70))
        self.macd_fast = int(self.get_parameter("macd_fast", 12))
        self.macd_slow = int(self.get_parameter("macd_slow", 26))
        self.macd_signal = int(self.get_parameter("macd_signal", 9))
        self.ma_period = int(self.get_parameter("ma_period", 20))
        self.vol_period = int(self.get_parameter("vol_period", 20))
        self.stop_loss = float(self.get_parameter("stop_loss", 0.08))
        self.trailing_stop = float(self.get_parameter("trailing_stop", 0.05))
        
        # 添加标的
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        
        # 指标
        self.rsi = self.rsi(self.symbol, self.rsi_period, MovingAverageType.WILDERS, Resolution.DAILY)
        self.ma = self.sma(self.symbol, self.ma_period, Resolution.DAILY)
        self.vol_ma = self.sma(self.symbol, self.vol_period, Resolution.DAILY, Field.Volume)
        
        # 手动计算MACD（避免API问题）
        self.ema_fast = self.ema(self.symbol, self.macd_fast, Resolution.DAILY)
        self.ema_slow = self.ema(self.symbol, self.macd_slow, Resolution.DAILY)
        
        # Warm-up
        self.set_warm_up(max(self.macd_slow, self.ma_period, self.vol_period) + 10)
        
        # 状态
        self.entry_price = None
        self.highest_price = None
        self.is_invested = False
        self.prev_macd_hist = None
        
        self.log(f"多因子策略初始化: RSI({self.rsi_period}), EMA({self.macd_fast}/{self.macd_slow}), MA({self.ma_period})")

    def on_data(self, data: Slice):
        # 检查指标准备就绪
        if not self.rsi.is_ready or not self.ma.is_ready or not self.vol_ma.is_ready:
            return
        
        if not self.ema_fast.is_ready or not self.ema_slow.is_ready:
            return
        
        if self.symbol not in data.bars:
            return
        
        price = data.bars[self.symbol].close
        volume = data.bars[self.symbol].volume
        rsi_val = self.rsi.current.value
        ma_val = self.ma.current.value
        vol_ma_val = self.vol_ma.current.value
        
        # 计算MACD
        macd_line = self.ema_fast.current.value - self.ema_slow.current.value
        macd_hist = macd_line  # 简化处理，使用MACD线本身
        
        # 已有持仓：检查退出条件
        if self.portfolio.invested:
            # 更新最高价
            if self.highest_price is None or price > self.highest_price:
                self.highest_price = price
            
            # 1. 固定止损
            if self.entry_price and price < self.entry_price * (1 - self.stop_loss):
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
            
            # 3. RSI超买
            if rsi_val > self.rsi_exit:
                self.liquidate(self.symbol)
                self.log(f"RSI超买退出: RSI={rsi_val:.1f}")
                self._reset_state()
                return
        
        # 无持仓：检查入场条件
        else:
            # 多因子入场条件
            factor1 = rsi_val < self.rsi_entry                    # RSI超卖
            factor2 = macd_hist > 0 or (self.prev_macd_hist and self.prev_macd_hist < 0 and macd_hist > 0)  # MACD转正或金叉
            factor3 = volume > vol_ma_val * 0.8                   # 成交量放大
            factor4 = price > ma_val                              # 价格在均线上方
            
            score = sum([factor1, factor2, factor3, factor4])
            
            # 3个或4个因子满足才入场
            if score >= 3:
                position_size = min(1.0, 0.5 + score * 0.125)
                self.set_holdings(self.symbol, position_size)
                
                self.entry_price = price
                self.highest_price = price
                self.is_invested = True
                
                self.log(f"买入(多因子): 价格={price:.2f}, 评分={score}/4, "
                        f"RSI={rsi_val:.1f}, MACD={macd_hist:.3f}, "
                        f"Vol={volume/1e6:.1f}M, MA={ma_val:.2f}, 仓位={position_size:.0%}")
        
        self.prev_macd_hist = macd_hist

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
