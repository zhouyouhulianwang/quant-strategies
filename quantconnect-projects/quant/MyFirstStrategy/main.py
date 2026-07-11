from AlgorithmImports import *
import sys
import os

# 添加日志模块路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from strategy_logger import StrategyLogger, log_execution_time
except ImportError:
    # 如果导入失败，使用基础日志
    StrategyLogger = None
    log_execution_time = lambda x: x

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
        
        # 初始化日志
        if StrategyLogger:
            self.logger = StrategyLogger("MyFirstStrategy", log_dir="logs")
        else:
            self.logger = None
        
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
        
        # 记录策略参数
        self._log_info(f"策略初始化完成: Fast MA={self.fast_period}, Slow MA={self.slow_period}")
        self._log_info(f"回测期间: 2020-01-01 至 2024-12-30")
        self._log_info(f"初始资金: $100,000")

    def _log_info(self, message):
        """统一日志记录"""
        self.log(message)
        if self.logger:
            self.logger.info(message)

    def _log_trade(self, action, symbol, quantity, price, reason=""):
        """记录交易日志"""
        msg = f"[TRADE] {action} {symbol} | Qty: {quantity} | Price: ${price:.2f}"
        if reason:
            msg += f" | Reason: {reason}"
        self._log_info(msg)

    def _log_portfolio(self):
        """记录投资组合状态"""
        total = self.portfolio.total_portfolio_value
        cash = self.portfolio.cash
        positions = len([x for x in self.portfolio.values() if x.invested])
        self._log_info(f"[PORTFOLIO] Total: ${total:,.2f} | Cash: ${cash:,.2f} | Positions: {positions}")

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
        
        # 记录价格数据（每5天记录一次，避免日志过多）
        if self.time.day % 5 == 0:
            self._log_info(f"[DATA] SPY Price: ${price:.2f} | Fast MA: {fast_value:.2f} | Slow MA: {slow_value:.2f}")
        
        # 检查是否已持仓
        if not self.portfolio.invested:
            # 金叉：短期均线上穿长期均线
            if fast_value > slow_value * 1.001:  # 1.001避免震荡
                self.set_holdings(self.symbol, 1.0)
                self._log_trade("BUY", "SPY", 1, price, f"Golden Cross: Fast({fast_value:.2f}) > Slow({slow_value:.2f})")
                self._log_portfolio()
                self.is_invested = True
        else:
            # 死叉：短期均线下穿长期均线
            if fast_value < slow_value * 0.999:  # 0.999避免震荡
                self.liquidate(self.symbol)
                self._log_trade("SELL", "SPY", 1, price, f"Death Cross: Fast({fast_value:.2f}) < Slow({slow_value:.2f})")
                self._log_portfolio()
                self.is_invested = False

    def on_order_event(self, order_event):
        """订单事件处理"""
        if order_event.status == OrderStatus.FILLED:
            self._log_info(f"[ORDER FILLED] {order_event.symbol} {order_event.direction} {order_event.fill_quantity} @ ${order_event.fill_price:.2f}")
            self._log_portfolio()

    def on_end_of_algorithm(self):
        """算法结束时的总结"""
        self._log_info("=" * 60)
        self._log_info("策略运行结束")
        self._log_info("=" * 60)
        self._log_portfolio()
        
        # 计算收益
        total_return = (self.portfolio.total_portfolio_value - 100000) / 100000 * 100
        self._log_info(f"[SUMMARY] Total Return: {total_return:.2f}%")
        self._log_info(f"[SUMMARY] Final Equity: ${self.portfolio.total_portfolio_value:,.2f}")
        
        # 记录夏普比率（如果可用）
        if hasattr(self, 'sharpe_ratio'):
            self._log_info(f"[SUMMARY] Sharpe Ratio: {self.sharpe_ratio:.2f}")
