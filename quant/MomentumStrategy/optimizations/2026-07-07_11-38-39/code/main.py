from AlgorithmImports import *

class MomentumStrategy(QCAlgorithm):
    """
    动量策略 (Momentum Strategy)
    
    策略逻辑：
    - 价格突破N日高点 → 买入（动量延续）
    - 价格跌破N日低点 → 卖出（动量反转）
    - 使用ADX确认趋势强度
    """

    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 参数
        self.lookback = int(self.get_parameter("lookback", 20))
        self.adx_period = int(self.get_parameter("adx_period", 14))
        self.adx_threshold = int(self.get_parameter("adx_threshold", 20))
        self.stop_loss_pct = float(self.get_parameter("stop_loss_pct", 0.10))
        
        # 添加标的
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        
        # 指标
        self.adx = self.adx(self.symbol, self.adx_period, Resolution.DAILY)
        
        # 存储历史数据用于计算高点/低点
        self.price_history = []
        
        # Warm-up
        self.set_warm_up(self.lookback + 10)
        
        # 状态
        self.entry_price = None
        self.is_invested = False
        
        self.log(f"动量策略初始化: Lookback={self.lookback}, ADX={self.adx_period}")

    def on_data(self, data: Slice):
        if not self.adx.is_ready:
            return
        
        if self.symbol not in data.bars:
            return
        
        price = data.bars[self.symbol].close
        adx_val = self.adx.current.value
        
        # 更新历史价格
        self.price_history.append(price)
        if len(self.price_history) > self.lookback:
            self.price_history.pop(0)
        
        if len(self.price_history) < self.lookback:
            return
        
        highest_high = max(self.price_history)
        lowest_low = min(self.price_history)
        
        # 已有持仓：检查退出条件
        if self.portfolio.invested:
            # 1. 止损
            if self.entry_price and price < self.entry_price * (1 - self.stop_loss_pct):
                self.liquidate(self.symbol)
                self.log(f"止损退出: 价格={price:.2f}")
                self._reset_state()
                return
            
            # 2. 跌破N日低点退出
            if price < lowest_low * 1.01:
                self.liquidate(self.symbol)
                self.log(f"跌破低点退出: 价格={price:.2f}, 低点={lowest_low:.2f}")
                self._reset_state()
                return
        
        # 无持仓：检查入场条件
        else:
            # 突破N日高点 + ADX趋势强
            if price > highest_high * 0.995 and adx_val > self.adx_threshold:
                self.set_holdings(self.symbol, 1.0)
                self.entry_price = price
                self.is_invested = True
                self.log(f"买入(动量): 价格={price:.2f}, 高点={highest_high:.2f}, ADX={adx_val:.1f}")

    def _reset_state(self):
        self.entry_price = None
        self.is_invested = False

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.log(f"订单执行: {order_event.symbol} {order_event.direction} "
                    f"{order_event.fill_quantity} @ {order_event.fill_price:.2f}")

    def on_end_of_algorithm(self):
        self.log(f"策略结束: 最终权益={self.portfolio.total_portfolio_value:.2f}")
