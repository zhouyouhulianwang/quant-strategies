from AlgorithmImports import *

class OptimizedDualMAStrategy(QCAlgorithm):
    """
    优化版双均线策略 (Optimized Dual Moving Average)
    
    改进点：
    1. 添加止损机制（最大回撤控制）
    2. 使用EMA替代SMA（更灵敏）
    3. 添加ADX趋势过滤（避免震荡市）
    4. 优化参数
    """

    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 参数（可优化）
        self.fast_period = int(self.get_parameter("fast_period", 10))
        self.slow_period = int(self.get_parameter("slow_period", 30))
        self.adx_period = int(self.get_parameter("adx_period", 14))
        self.adx_threshold = int(self.get_parameter("adx_threshold", 25))
        self.stop_loss_pct = float(self.get_parameter("stop_loss_pct", 0.08))
        self.trailing_stop = float(self.get_parameter("trailing_stop", 0.05))
        
        # 添加标的
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        
        # 指标 - 使用正确的Lean API
        self.fast_ema = self.ema(self.symbol, self.fast_period, Resolution.DAILY)
        self.slow_ema = self.ema(self.symbol, self.slow_period, Resolution.DAILY)
        self.adx = self.adx(self.symbol, self.adx_period, Resolution.DAILY)
        
        # Warm-up
        self.set_warm_up(max(self.slow_period, self.adx_period) + 10)
        
        # 状态跟踪
        self.entry_price = None
        self.highest_price = None
        self.is_invested = False
        
        self.log(f"优化策略初始化: Fast EMA={self.fast_period}, Slow EMA={self.slow_period}, "
                  f"ADX={self.adx_period}, Stop Loss={self.stop_loss_pct:.0%}")

    def on_data(self, data: Slice):
        # 检查指标准备就绪
        if not self.fast_ema.is_ready or not self.slow_ema.is_ready or not self.adx.is_ready:
            return
        
        if self.symbol not in data.bars:
            return
        
        price = data.bars[self.symbol].close
        fast_val = self.fast_ema.current.value
        slow_val = self.slow_ema.current.value
        adx_val = self.adx.current.value
        
        # 已有持仓：检查止损和退出条件
        if self.portfolio.invested:
            # 更新最高价（用于 trailing stop）
            if self.highest_price is None or price > self.highest_price:
                self.highest_price = price
            
            # 1. 固定止损
            if self.entry_price and price < self.entry_price * (1 - self.stop_loss_pct):
                self.liquidate(self.symbol)
                self.log(f"固定止损: 价格={price:.2f}, 入场价={self.entry_price:.2f}, "
                        f"亏损={((price/self.entry_price)-1)*100:.1f}%")
                self._reset_state()
                return
            
            # 2. Trailing Stop
            if self.highest_price and price < self.highest_price * (1 - self.trailing_stop):
                self.liquidate(self.symbol)
                self.log(f"Trailing Stop: 价格={price:.2f}, 最高价={self.highest_price:.2f}")
                self._reset_state()
                return
            
            # 3. 死叉退出（ADX不强时）
            if fast_val < slow_val * 0.995 and adx_val < self.adx_threshold:
                self.liquidate(self.symbol)
                self.log(f"死叉退出: 价格={price:.2f}, ADX={adx_val:.1f}")
                self._reset_state()
                return
        
        # 无持仓：检查入场条件
        else:
            # 入场条件：
            # 1. 金叉
            # 2. ADX > 阈值（趋势强）
            # 3. 价格 > 慢速EMA（趋势向上）
            if (fast_val > slow_val * 1.005 and  # 金叉
                adx_val > self.adx_threshold and    # 趋势强
                price > slow_val):                   # 价格在均线上方
                
                self.set_holdings(self.symbol, 1.0)
                self.entry_price = price
                self.highest_price = price
                self.is_invested = True
                self.log(f"买入: 价格={price:.2f}, Fast EMA={fast_val:.2f}, "
                        f"Slow EMA={slow_val:.2f}, ADX={adx_val:.1f}")

    def _reset_state(self):
        """重置状态"""
        self.entry_price = None
        self.highest_price = None
        self.is_invested = False

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.log(f"订单执行: {order_event.symbol} {order_event.direction} "
                    f"{order_event.fill_quantity} @ {order_event.fill_price:.2f}")

    def on_end_of_algorithm(self):
        self.log(f"策略结束: 最终权益={self.portfolio.total_portfolio_value:.2f}")
