from AlgorithmImports import *

class DualMovingAverageStrategy(QCAlgorithm):
    """
    双均线交叉策略 (Dual Moving Average Crossover)
    
    策略逻辑：
    - 短期均线上穿长期均线（金叉）→ 买入
    - 短期均线下穿长期均线（死叉）→ 卖出
    
    参数：
    - fast_period: 短期均线周期（默认20日）
    - slow_period: 长期均线周期（默认50日）
    """

    def initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 12, 30)
        self.set_cash(100000)
        
        # 参数外部化（便于优化）
        self.fast_period = int(self.get_parameter("fast_period", 20))
        self.slow_period = int(self.get_parameter("slow_period", 50))
        
        # 添加标的
        self.symbol = self.add_equity("SPY", Resolution.DAILY).symbol
        
        # 创建移动平均线指标
        self.fast_ma = self.sma(self.symbol, self.fast_period, Resolution.DAILY)
        self.slow_ma = self.sma(self.symbol, self.slow_period, Resolution.DAILY)
        
        # 设置 warm-up 期（确保指标有数据）
        self.set_warm_up(self.slow_period)
        
        # 记录交易状态
        self.is_invested = False
        
        self.log(f"策略初始化完成: Fast MA={self.fast_period}, Slow MA={self.slow_period}")

    def on_data(self, data: Slice):
        """主交易逻辑"""
        # 检查指标是否已准备好
        if not self.fast_ma.is_ready or not self.slow_ma.is_ready:
            return
        
        # 获取当前价格
        if self.symbol not in data.bars:
            return
            
        price = data.bars[self.symbol].close
        fast_value = self.fast_ma.current.value
        slow_value = self.slow_ma.current.value
        
        # 检查是否已持仓
        if not self.portfolio.invested:
            # 金叉：短期均线上穿长期均线
            if fast_value > slow_value * 1.001:  # 1.001避免震荡
                self.set_holdings(self.symbol, 1.0)
                self.log(f"买入信号: 价格={price:.2f}, Fast MA={fast_value:.2f}, Slow MA={slow_value:.2f}")
                self.is_invested = True
        else:
            # 死叉：短期均线下穿长期均线
            if fast_value < slow_value * 0.999:  # 0.999避免震荡
                self.liquidate(self.symbol)
                self.log(f"卖出信号: 价格={price:.2f}, Fast MA={fast_value:.2f}, Slow MA={slow_value:.2f}")
                self.is_invested = False

    def on_order_event(self, order_event):
        """订单事件处理"""
        if order_event.status == OrderStatus.FILLED:
            self.log(f"订单执行: {order_event.symbol} {order_event.direction} {order_event.fill_quantity} @ {order_event.fill_price}")

    def on_end_of_algorithm(self):
        """算法结束时的总结"""
        self.log("策略运行结束")
        self.log(f"最终权益: {self.portfolio.total_portfolio_value:.2f}")
