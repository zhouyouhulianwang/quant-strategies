from AlgorithmImports import *

class CombinedStrategy(QCAlgorithm):
    """
    组合策略 (Combined Strategy)
    
    同时运行三个子策略，根据信号强度分配仓位：
    1. 趋势策略（双均线）- 40%权重
    2. 动量策略（突破）- 30%权重
    3. 均值回归（RSI）- 30%权重
    
    仓位管理：
    - 每个子策略独立计算信号
    - 根据信号一致性确定总仓位
    - 最多80%仓位（保留20%现金缓冲）
    """

    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 参数
        self.max_position = 0.8  # 最大80%仓位
        self.stop_loss = 0.10
        
        # 添加标的
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        
        # === 子策略1: 双均线趋势 ===
        self.fast_ma = self.sma(self.symbol, 20, Resolution.DAILY)
        self.slow_ma = self.sma(self.symbol, 50, Resolution.DAILY)
        
        # === 子策略2: 动量突破 ===
        self.adx = self.adx(self.symbol, 14, Resolution.DAILY)
        self.price_history = []
        self.lookback = 20
        
        # === 子策略3: 均值回归 (RSI) ===
        self.rsi = self.rsi(self.symbol, 14, MovingAverageType.WILDERS, Resolution.DAILY)
        self.rsi_ma = self.sma(self.symbol, 20, Resolution.DAILY)
        
        # Warm-up
        self.set_warm_up(60)
        
        # 状态
        self.entry_price = None
        self.is_invested = False
        
        self.log("组合策略初始化: 趋势40% + 动量30% + 均值回归30%")

    def on_data(self, data: Slice):
        if not self.fast_ma.is_ready or not self.slow_ma.is_ready or \
           not self.adx.is_ready or not self.rsi.is_ready or not self.rsi_ma.is_ready:
            return
        
        if self.symbol not in data.bars:
            return
        
        price = data.bars[self.symbol].close
        
        # 更新历史价格
        self.price_history.append(price)
        if len(self.price_history) > self.lookback:
            self.price_history.pop(0)
        
        # 计算各子策略信号
        signal1 = self._trend_signal(price)      # 趋势策略
        signal2 = self._momentum_signal(price)   # 动量策略
        signal3 = self._mean_reversion_signal(price)  # 均值回归
        
        # 综合信号 (-1 到 +1)
        combined_signal = signal1 * 0.4 + signal2 * 0.3 + signal3 * 0.3
        
        # 仓位管理
        target_position = combined_signal * self.max_position
        target_position = max(-0.5, min(0.8, target_position))  # 限制范围
        
        # 执行交易
        if target_position > 0.1 and not self.portfolio.invested:
            # 买入
            self.set_holdings(self.symbol, target_position)
            self.entry_price = price
            self.is_invested = True
            self.log(f"买入(组合): 信号={combined_signal:.2f}, "
                    f"趋势={signal1:.2f}, 动量={signal2:.2f}, 回归={signal3:.2f}, "
                    f"仓位={target_position:.0%}")
        
        elif target_position < -0.1 and self.portfolio.invested:
            # 卖出
            self.liquidate(self.symbol)
            self.log(f"卖出(组合): 信号={combined_signal:.2f}")
            self._reset_state()
        
        elif self.portfolio.invested:
            # 检查止损
            if self.entry_price and price < self.entry_price * (1 - self.stop_loss):
                self.liquidate(self.symbol)
                self.log(f"止损: 价格={price:.2f}")
                self._reset_state()

    def _trend_signal(self, price):
        """趋势策略信号: +1(多头) / -1(空头) / 0(无信号)"""
        fast = self.fast_ma.current.value
        slow = self.slow_ma.current.value
        if fast > slow * 1.01:
            return 1.0
        elif fast < slow * 0.99:
            return -1.0
        return 0.0

    def _momentum_signal(self, price):
        """动量策略信号"""
        if len(self.price_history) < self.lookback:
            return 0.0
        
        highest = max(self.price_history)
        lowest = min(self.price_history)
        adx_val = self.adx.current.value
        
        if price > highest * 0.995 and adx_val > 20:
            return 1.0
        elif price < lowest * 1.005:
            return -1.0
        return 0.0

    def _mean_reversion_signal(self, price):
        """均值回归信号"""
        rsi_val = self.rsi.current.value
        ma_val = self.rsi_ma.current.value
        
        if rsi_val < 35 and price > ma_val:
            return 1.0  # 超卖回归
        elif rsi_val > 65:
            return -1.0  # 超买回落
        return 0.0

    def _reset_state(self):
        self.entry_price = None
        self.is_invested = False

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.log(f"订单: {order_event.symbol} {order_event.direction} "
                    f"{order_event.fill_quantity} @ {order_event.fill_price:.2f}")

    def on_end_of_algorithm(self):
        self.log(f"策略结束: 最终权益={self.portfolio.total_portfolio_value:.2f}")
