"""多策略切换器 - 根据市场状态自动选择策略"""
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd

from localquant.strategy import BaseStrategy


class StrategyRotator(BaseStrategy):
    """
    策略切换器
    
    根据市场状态自动切换策略:
    - 牛市: BullMomentum (高收益)
    - 熊市: AdaptiveMomentum (防御)
    - 震荡: TrendFollowing (稳健)
    """
    
    def __init__(self, symbols: List[str],
                 spy_symbol: str = 'SPY',
                 vix_symbol: str = 'VIXY',
                 bull_weight: float = 0.6,
                 bear_weight: float = 0.2,
                 sideways_weight: float = 0.2):
        super().__init__()
        self.symbols = symbols
        self.spy_symbol = spy_symbol
        self.vix_symbol = vix_symbol
        self.bull_weight = bull_weight
        self.bear_weight = bear_weight
        self.sideways_weight = sideways_weight
        
        # 当前状态和策略
        self.current_regime = "unknown"
        self.current_strategy = None
        self.last_switch = None
        
        # 历史数据缓存
        self.spy_history = []
        self.vix_history = []
    
    def detect_market_regime(self, spy_price: float, vix_price: Optional[float]) -> str:
        """检测市场状态"""
        if len(self.spy_history) < 20:
            return "unknown"
        
        # SPY 20日收益率
        spy_return_20d = spy_price / self.spy_history[-20] - 1
        
        # SPY 60日收益率
        spy_return_60d = spy_price / self.spy_history[-min(60, len(self.spy_history))] - 1
        
        # VIX 水平
        vix_level = vix_price if vix_price else 20.0
        if len(self.vix_history) > 0 and vix_price is None:
            vix_level = self.vix_history[-1]
        
        # 判断逻辑
        if spy_return_20d > 0.03 and vix_level < 20:
            return "bull"
        elif spy_return_20d < -0.03 or vix_level > 25:
            return "bear"
        else:
            return "sideways"
    
    def on_data(self, data: Dict):
        super().on_data(data)
        
        current_time = data['timestamp']
        bar_data = data['data']
        
        # 更新历史数据
        if self.spy_symbol in bar_data:
            spy_close = bar_data[self.spy_symbol].get('close')
            if spy_close:
                self.spy_history.append(spy_close)
                self.spy_history = self.spy_history[-100:]  # 保留100条
        
        if self.vix_symbol in bar_data:
            vix_close = bar_data[self.vix_symbol].get('close')
            if vix_close:
                self.vix_history.append(vix_close)
                self.vix_history = self.vix_history[-100:]
        
        # 检测市场状态
        spy_price = self.spy_history[-1] if self.spy_history else None
        vix_price = self.vix_history[-1] if self.vix_history else None
        
        if spy_price:
            new_regime = self.detect_market_regime(spy_price, vix_price)
        else:
            new_regime = "sideways"  # 默认
        
        # 状态切换
        if new_regime != self.current_regime:
            print(f"\n[{current_time.date()}] 市场状态切换: {self.current_regime} -> {new_regime}")
            self.current_regime = new_regime
            self.last_switch = current_time
            
            # 清仓旧策略持仓
            self._liquidate_all()
        
        # 根据状态执行对应策略
        if self.current_regime == "bull":
            self._execute_bull_strategy(bar_data, current_time)
        elif self.current_regime == "bear":
            self._execute_bear_strategy(bar_data, current_time)
        else:
            self._execute_sideways_strategy(bar_data, current_time)
    
    def _execute_bull_strategy(self, bar_data, current_time):
        """执行牛市策略 - 买入最强动量股"""
        momentum_scores = {}
        for symbol in self.symbols:
            if symbol not in bar_data or symbol == self.spy_symbol:
                continue
            
            close = bar_data[symbol].get('close')
            if close is None:
                continue
            
            hist = self.context.get_history(symbol, 'close', 20)
            if len(hist) >= 20:
                momentum = close / hist.iloc[0] - 1
                momentum_scores[symbol] = momentum
        
        if not momentum_scores:
            return
        
        # 买入Top 5
        top5 = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)[:5]
        
        for symbol, _ in top5:
            self.target_percent(symbol, 0.12)  # 每只12%
    
    def _execute_bear_strategy(self, bar_data, current_time):
        """执行熊市策略 - 防御性持仓"""
        # 清仓或减仓
        portfolio = self._engine.portfolio
        for symbol, position in list(portfolio.positions.items()):
            if position.quantity > 0:
                # 保留部分防御性持仓
                self.target_percent(symbol, 0.05)  # 降至5%
    
    def _execute_sideways_strategy(self, bar_data, current_time):
        """执行震荡市策略 - 趋势跟踪"""
        for symbol in self.symbols:
            if symbol not in bar_data or symbol == self.spy_symbol:
                continue
            
            close = bar_data[symbol].get('close')
            if close is None:
                continue
            
            hist = self.context.get_history(symbol, 'close', 50)
            if len(hist) < 50:
                continue
            
            sma50 = hist.mean()
            
            if close > sma50:
                self.target_percent(symbol, 0.08)  # 8%仓位
            else:
                # 清仓
                portfolio = self._engine.portfolio
                position = portfolio.positions.get(symbol)
                if position and position.quantity > 0:
                    self.sell(symbol, position.quantity)
    
    def _liquidate_all(self):
        """清仓所有持仓"""
        portfolio = self._engine.portfolio
        for symbol, position in portfolio.positions.items():
            if position.quantity > 0:
                self.sell(symbol, position.quantity)
