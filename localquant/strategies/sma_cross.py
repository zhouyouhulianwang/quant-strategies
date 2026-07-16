"""SMA 交叉策略示例 - 买入信号: 短期 SMA 上穿长期 SMA"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

from localquant.strategy import BaseStrategy
from localquant.strategy.indicators import sma

class SmaCrossStrategy(BaseStrategy):
    """SMA 交叉策略"""
    
    def __init__(self, symbols=None, short_period=20, long_period=50):
        super().__init__()
        self.short_period = short_period
        self.long_period = long_period
        self.symbols = symbols or ['AAPL']  # 默认标的
        self._in_position = False
    
    def initialize(self):
        """初始化策略参数"""
        self.name = f"SMA_Cross_{self.short_period}_{self.long_period}"
        print(f"Strategy initialized: {self.name}")
    
    def on_data(self, data):
        """处理每个数据 bar"""
        super().on_data(data)
        
        for symbol in self.symbols:
            if symbol not in self.context.current_data:
                continue
            
            # 获取历史收盘价
            history = self.context.get_history(symbol, 'close', lookback=self.long_period + 10)
            if len(history) < self.long_period:
                continue
            
            # 计算 SMA
            short_sma = sma(history, self.short_period).iloc[-1]
            long_sma = sma(history, self.long_period).iloc[-1]
            
            current_price = self.context.get_price(symbol, 'close')
            if current_price is None:
                continue
            
            # 信号判断
            if short_sma > long_sma and not self._in_position:
                # 金叉买入
                quantity = int(self._engine.portfolio.cash / current_price * 0.95)
                if quantity > 0:
                    self.buy(symbol, quantity)
                    self._in_position = True
                    print(f"BUY {symbol} @ {current_price:.2f} ({quantity} shares)")
            
            elif short_sma < long_sma and self._in_position:
                # 死叉卖出
                if symbol in self._engine.portfolio.positions:
                    qty = self._engine.portfolio.positions[symbol].quantity
                    if qty > 0:
                        self.sell(symbol, qty)
                        self._in_position = False
                        print(f"SELL {symbol} @ {current_price:.2f} ({qty} shares)")
