"""回测引擎 - 事件驱动回测"""
import pandas as pd
from typing import Dict, List, Optional, Callable
from datetime import datetime
from .portfolio import Portfolio
from .broker import SimulatedBroker
from .events import Event, EventType, MarketDataEvent, SignalEvent, OrderEvent, FillEvent

class BacktestEngine:
    """事件驱动回测引擎"""
    
    def __init__(self, 
                 initial_cash: float = 100000.0,
                 commission_rate: float = 0.001,
                 start_date: Optional[datetime] = None,
                 end_date: Optional[datetime] = None):
        self.initial_cash = initial_cash
        self.portfolio = Portfolio(initial_cash)
        self.broker = SimulatedBroker(commission_rate=commission_rate)
        self.start_date = start_date
        self.end_date = end_date
        self.data = None  # 初始化 data 属性
        self.symbols = []
        
        # 事件队列和处理器
        self.event_queue: List[Event] = []
        self.data_handler: Optional[Callable] = None
        self.strategy: Optional[Callable] = None
        self.signals: List[SignalEvent] = []
        self.orders: List[OrderEvent] = []
        self.fills: List[FillEvent] = []
        self.trades: List[Dict] = []
        
    def set_strategy(self, strategy):
        """设置策略"""
        self.strategy = strategy
        strategy.set_engine(self)
    
    def set_data(self, data: pd.DataFrame, symbol_name: Optional[str] = None):
        """
        设置回测数据
        data: DataFrame with MultiIndex (date, symbol) or single symbol
        columns: open, high, low, close, volume
        """
        self.data = data
        if isinstance(data.columns, pd.MultiIndex):
            self.symbols = data.columns.get_level_values(1).unique().tolist()
        else:
            self.symbols = [symbol_name or data.columns.name or 'UNKNOWN']
        
    def run(self) -> Dict:
        """运行回测"""
        if self.data is None:
            raise ValueError("No data set. Call set_data() first.")
        if self.strategy is None:
            raise ValueError("No strategy set. Call set_strategy() first.")
        
        print(f"Starting backtest: {len(self.data)} bars, {self.symbols}")
        
        # 初始化策略
        self.strategy.initialize()
        
        # 按时间顺序遍历
        self._current_prices = {}  # 保存当前价格
        for timestamp, row in self.data.iterrows():
            # 过滤日期范围 - 处理时区一致
            ts_cmp = pd.Timestamp(timestamp)
            start_cmp = pd.Timestamp(self.start_date) if self.start_date else None
            end_cmp = pd.Timestamp(self.end_date) if self.end_date else None
            
            if ts_cmp.tz is not None and start_cmp and start_cmp.tz is None:
                start_cmp = start_cmp.tz_localize(ts_cmp.tz)
            if ts_cmp.tz is not None and end_cmp and end_cmp.tz is None:
                end_cmp = end_cmp.tz_localize(ts_cmp.tz)
            
            if start_cmp and ts_cmp < start_cmp:
                continue
            if end_cmp and ts_cmp > end_cmp:
                break
            
            # 构建当前价格字典
            if isinstance(self.data.columns, pd.MultiIndex):
                # 多标的数据
                prices = {}
                for symbol in self.symbols:
                    try:
                        prices[symbol] = row[('close', symbol)]
                    except KeyError:
                        continue
            else:
                # 单标的数据
                prices = {self.symbols[0]: row['close']}
            
            # 保存当前价格用于订单执行
            self._current_prices = prices
            
            # 更新投资组合市值
            self.portfolio.update_market(timestamp, prices)
            
            # 创建市场数据事件
            market_data = self._create_market_data(timestamp, row)
            
            # 策略生成信号
            self.strategy.on_data(market_data)
            
            # 处理事件队列（订单 -> 成交）
            self._process_events()
        
        print("Backtest complete!")
        return self._generate_results()
    
    def _create_market_data(self, timestamp, row) -> Dict[str, Dict]:
        """创建市场数据结构"""
        data = {}
        if isinstance(self.data.columns, pd.MultiIndex):
            for symbol in self.symbols:
                try:
                    data[symbol] = {
                        'open': row[('open', symbol)],
                        'high': row[('high', symbol)],
                        'low': row[('low', symbol)],
                        'close': row[('close', symbol)],
                        'volume': row[('volume', symbol)]
                    }
                except KeyError:
                    continue
        else:
            data[self.symbols[0]] = {
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume']
            }
        return {'timestamp': timestamp, 'data': data}
    
    def place_order(self, symbol: str, quantity: int, 
                   order_type: str = "MARKET", price: float = 0.0):
        """下单"""
        timestamp = self.portfolio.current_date or datetime.now()
        order = OrderEvent(
            event_type=EventType.ORDER,
            timestamp=timestamp,
            symbol=symbol,
            order_type=order_type,
            quantity=quantity,
            price=price
        )
        self.orders.append(order)
        self.event_queue.append(order)
    
    def _process_events(self):
        """处理事件队列"""
        while self.event_queue:
            event = self.event_queue.pop(0)
            
            if event.event_type == EventType.ORDER:
                # 执行订单
                current_prices = self._get_current_prices()
                if event.symbol in current_prices:
                    fill = self.broker.execute_order(event, current_prices[event.symbol])
                    if fill:
                        self.fills.append(fill)
                        self._process_fill(fill)
    
    def _get_current_prices(self) -> Dict[str, float]:
        """获取当前价格"""
        return self._current_prices
    
    def _process_fill(self, fill: FillEvent):
        """处理成交"""
        pnl = self.portfolio.execute_order(
            fill.symbol,
            fill.fill_quantity,
            fill.fill_price,
            fill.commission
        )
        
        self.trades.append({
            'timestamp': fill.timestamp,
            'symbol': fill.symbol,
            'quantity': fill.fill_quantity,
            'price': fill.fill_price,
            'commission': fill.commission,
            'realized_pnl': pnl if pnl else 0
        })
    
    def _generate_results(self) -> Dict:
        """生成回测结果"""
        returns = self.portfolio.get_returns()
        equity = self.portfolio.get_equity_curve()
        
        total_return = (equity.iloc[-1] / self.initial_cash - 1) * 100 if len(equity) > 0 else 0
        
        results = {
            'initial_capital': self.initial_cash,
            'final_equity': equity.iloc[-1] if len(equity) > 0 else self.initial_cash,
            'total_return_pct': total_return,
            'total_trades': len(self.trades),
            'equity_curve': equity,
            'returns': returns,
            'trades': pd.DataFrame(self.trades) if self.trades else pd.DataFrame(),
            'history': pd.DataFrame(self.portfolio.history) if self.portfolio.history else pd.DataFrame()
        }
        
        return results
