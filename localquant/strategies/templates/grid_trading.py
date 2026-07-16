"""网格交易策略 - 震荡市盈利利器

策略逻辑:
1. 设定价格区间 [lower, upper]
2. 将区间分成N等份网格
3. 价格触及网格下沿 → 买入
4. 价格触及网格上沿 → 卖出
5. 每个网格固定买卖数量

适用场景: 震荡市、横盘整理
时间框架: 任意（适合长期运行）
"""
import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime

from localquant.strategy import BaseStrategy


class GridTradingStrategy(BaseStrategy):
    """
    网格交易策略
    
    参数:
    - grid_lower: 网格下界
    - grid_upper: 网格上界
    - grid_count: 网格数量
    - quantity_per_grid: 每格交易数量
    
    使用示例:
    ```python
    strategy = GridTradingStrategy(
        symbols=['BTC-USD'],
        grid_lower=50000,
        grid_upper=70000,
        grid_count=20,
        quantity_per_grid=0.1
    )
    ```
    """
    
    def __init__(self, symbols: List[str],
                 grid_lower: float = None,
                 grid_upper: float = None,
                 grid_count: int = 10,
                 quantity_per_grid: int = 100,
                 trailing_grid: bool = True,
                 trail_pct: float = 0.05):
        super().__init__()
        self.symbols = symbols
        self.grid_lower = grid_lower
        self.grid_upper = grid_upper
        self.grid_count = grid_count
        self.quantity_per_grid = quantity_per_grid
        self.trailing_grid = trailing_grid
        self.trail_pct = trail_pct
        
        # 网格状态
        self.grids = {}  # symbol -> [price_levels]
        self.last_grid = {}  # symbol -> 上次所在网格
        self.base_price = {}  # symbol -> 基准价格（用于动态网格）
        
        # 统计
        self.grid_trades = {}  # symbol -> 交易次数
        self.grid_profit = {}  # symbol -> 累计盈利
    
    def _init_grids(self, symbol: str, current_price: float):
        """初始化网格"""
        if self.grid_lower is None or self.grid_upper is None:
            # 动态网格：基于当前价格
            if self.trailing_grid:
                self.grid_lower = current_price * (1 - self.trail_pct)
                self.grid_upper = current_price * (1 + self.trail_pct)
            else:
                # 默认 ±10%
                self.grid_lower = current_price * 0.9
                self.grid_upper = current_price * 1.1
        
        # 生成网格
        step = (self.grid_upper - self.grid_lower) / self.grid_count
        self.grids[symbol] = [self.grid_lower + i * step 
                             for i in range(self.grid_count + 1)]
        self.base_price[symbol] = current_price
        
        print(f"初始化网格 {symbol}: ${self.grid_lower:.2f} ~ ${self.grid_upper:.2f}")
        print(f"网格线: {['${:.2f}'.format(g) for g in self.grids[symbol]]}")
    
    def _get_grid_index(self, symbol: str, price: float) -> int:
        """获取价格所在网格索引"""
        grids = self.grids.get(symbol, [])
        if not grids:
            return -1
        
        for i in range(len(grids) - 1):
            if grids[i] <= price <= grids[i + 1]:
                return i
        
        if price < grids[0]:
            return -1  # 低于最低网格
        return len(grids) - 1  # 高于最高网格
    
    def _update_trailing_grid(self, symbol: str, current_price: float):
        """更新动态网格"""
        if not self.trailing_grid:
            return
        
        base = self.base_price.get(symbol)
        if base is None:
            return
        
        # 价格偏离基准超过阈值时移动网格
        if abs(current_price - base) / base > self.trail_pct * 0.5:
            self.grid_lower = current_price * (1 - self.trail_pct)
            self.grid_upper = current_price * (1 + self.trail_pct)
            step = (self.grid_upper - self.grid_lower) / self.grid_count
            self.grids[symbol] = [self.grid_lower + i * step 
                                 for i in range(self.grid_count + 1)]
            self.base_price[symbol] = current_price
            
            print(f"[{datetime.now()}] 更新网格 {symbol}: ${self.grid_lower:.2f} ~ ${self.grid_upper:.2f}")
    
    def on_data(self, data: Dict):
        super().on_data(data)
        
        current_time = data['timestamp']
        bar_data = data['data']
        
        for symbol in self.symbols:
            if symbol not in bar_data:
                continue
            
            close = bar_data[symbol].get('close')
            if close is None:
                continue
            
            # 初始化网格
            if symbol not in self.grids:
                self._init_grids(symbol, close)
                self.last_grid[symbol] = self._get_grid_index(symbol, close)
                continue
            
            # 获取当前网格
            current_grid = self._get_grid_index(symbol, close)
            last_grid = self.last_grid.get(symbol, -1)
            
            if current_grid == -1 or last_grid == -1:
                continue
            
            portfolio = self._engine.portfolio
            position = portfolio.positions.get(symbol)
            current_qty = position.quantity if position else 0
            
            # 网格向上穿越 → 卖出
            if current_grid > last_grid:
                # 向上穿过多少格就卖多少
                grids_crossed = current_grid - last_grid
                sell_qty = min(grids_crossed * self.quantity_per_grid, current_qty)
                
                if sell_qty > 0:
                    self.sell(symbol, sell_qty)
                    
                    # 计算盈利
                    grid_price = self.grids[symbol][last_grid]
                    profit = (close - grid_price) * sell_qty
                    
                    self.grid_trades[symbol] = self.grid_trades.get(symbol, 0) + 1
                    self.grid_profit[symbol] = self.grid_profit.get(symbol, 0) + profit
                    
                    print(f"[{current_time}] 网格卖出 {symbol}: {sell_qty}股 @ ${close:.2f} "
                          f"(网格{last_grid}->{current_grid}, 盈利: ${profit:.2f})")
            
            # 网格向下穿越 → 买入
            elif current_grid < last_grid:
                # 向下穿过多少格就买多少
                grids_crossed = last_grid - current_grid
                
                # 计算可买数量
                max_cost = portfolio.cash * 0.1  # 每次最多10%资金
                max_qty = int(max_cost / close)
                buy_qty = min(grids_crossed * self.quantity_per_grid, max_qty)
                
                if buy_qty > 0:
                    self.buy(symbol, buy_qty)
                    
                    self.grid_trades[symbol] = self.grid_trades.get(symbol, 0) + 1
                    
                    print(f"[{current_time}] 网格买入 {symbol}: {buy_qty}股 @ ${close:.2f} "
                          f"(网格{last_grid}->{current_grid})")
            
            self.last_grid[symbol] = current_grid
            
            # 更新动态网格
            self._update_trailing_grid(symbol, close)
    
    def get_parameters(self) -> Dict:
        return {
            'grid_lower': {'value': self.grid_lower, 'type': 'float'},
            'grid_upper': {'value': self.grid_upper, 'type': 'float'},
            'grid_count': {'value': self.grid_count, 'min': 5, 'max': 100, 'type': 'int'},
            'quantity_per_grid': {'value': self.quantity_per_grid, 'min': 1, 'max': 10000, 'type': 'int'}
        }
    
    def get_description(self) -> str:
        return "网格交易策略 - 震荡市利器，自动低买高卖"
