"""机器学习策略 - 用 RandomForest 预测价格方向"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import TimeSeriesSplit
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("警告: sklearn未安装，ML策略不可用")

from localquant.strategy import BaseStrategy
from localquant.core.events import EventType


class MLStrategy(BaseStrategy):
    """
    机器学习策略
    用 RandomForest 预测未来收益方向
    """
    
    def __init__(self, symbols: List[str], 
                 lookback: int = 20,
                 prediction_horizon: int = 5,
                 top_n: int = 5,
                 model_params: Dict = None):
        super().__init__(symbols)
        
        self.lookback = lookback
        self.prediction_horizon = prediction_horizon
        self.top_n = top_n
        self.model_params = model_params or {
            'n_estimators': 100,
            'max_depth': 5,
            'min_samples_split': 10,
            'random_state': 42
        }
        
        # 模型和 scaler（每个 symbol 一个）
        self.models = {}
        self.scalers = {}
        self.is_trained = False
        
        # 历史数据缓存
        self.price_history = {s: [] for s in symbols}
        self.feature_history = {s: [] for s in symbols}
        self.target_history = {s: [] for s in symbols}
    
    def _calculate_features(self, prices: pd.Series) -> np.ndarray:
        """计算特征向量"""
        if len(prices) < self.lookback:
            return None
        
        # 价格特征
        returns = prices.pct_change().dropna()
        if len(returns) < self.lookback - 1:
            return None
        
        features = []
        
        # 1. 收益率特征
        features.append(returns.mean())
        features.append(returns.std())
        features.append(returns.iloc[-1])  # 最新收益率
        
        # 2. 动量特征
        features.append(prices.iloc[-1] / prices.iloc[-5] - 1)   # 5日动量
        features.append(prices.iloc[-1] / prices.iloc[-10] - 1)  # 10日动量
        features.append(prices.iloc[-1] / prices.iloc[-20] - 1)  # 20日动量
        
        # 3. 技术指标特征
        # SMA 距离
        sma5 = prices.iloc[-5:].mean()
        sma20 = prices.iloc[-20:].mean()
        features.append(prices.iloc[-1] / sma5 - 1)
        features.append(prices.iloc[-1] / sma20 - 1)
        features.append(sma5 / sma20 - 1)  # SMA 交叉
        
        # 4. 波动率特征
        features.append(returns.iloc[-5:].std())
        features.append(returns.iloc[-10:].std())
        
        # 5. 成交量特征（如果有）
        # features.append(...)  # 需要成交量数据
        
        return np.array(features)
    
    def _prepare_training_data(self, symbol: str) -> tuple:
        """准备训练数据"""
        prices = pd.Series(self.price_history[symbol])
        
        if len(prices) < self.lookback + self.prediction_horizon + 10:
            return None, None
        
        X, y = [], []
        
        for i in range(self.lookback, len(prices) - self.prediction_horizon):
            # 特征
            window = prices.iloc[i-self.lookback:i]
            features = self._calculate_features(window)
            if features is None:
                continue
            
            # 目标：未来收益率方向
            future_return = prices.iloc[i+self.prediction_horizon] / prices.iloc[i] - 1
            target = 1 if future_return > 0 else 0
            
            X.append(features)
            y.append(target)
        
        return np.array(X), np.array(y)
    
    def _train_model(self, symbol: str) -> bool:
        """训练模型"""
        X, y = self._prepare_training_data(symbol)
        
        if X is None or len(X) < 50:  # 需要至少50个样本
            return False
        
        # 时间序列交叉验证
        tscv = TimeSeriesSplit(n_splits=3)
        
        # 训练模型
        model = RandomForestClassifier(**self.model_params)
        
        # 标准化
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # 训练
        model.fit(X_scaled, y)
        
        self.models[symbol] = model
        self.scalers[symbol] = scaler
        
        return True
    
    def on_bar(self, event, portfolio, broker):
        """每个 bar 事件"""
        current_time = event.timestamp
        
        # 更新价格历史
        for symbol in self.symbols:
            if symbol in event.data:
                price = event.data[symbol].get('close', event.data[symbol].get('adj_close'))
                if price is not None:
                    self.price_history[symbol].append(price)
        
        # 每月重新训练模型
        if current_time.month != getattr(self, '_last_training_month', None):
            self._last_training_month = current_time.month
            
            print(f"[{current_time}] 训练 ML 模型...")
            trained_count = 0
            for symbol in self.symbols:
                if len(self.price_history[symbol]) >= self.lookback + 50:
                    if self._train_model(symbol):
                        trained_count += 1
            
            print(f"  训练完成: {trained_count}/{len(self.symbols)} 个模型")
            self.is_trained = trained_count > 0
        
        # 预测和交易
        if self.is_trained and current_time.day % 5 == 0:  # 每5天交易
            predictions = {}
            
            for symbol in self.symbols:
                if symbol not in self.models:
                    continue
                
                # 计算特征
                prices = pd.Series(self.price_history[symbol])
                if len(prices) < self.lookback:
                    continue
                
                features = self._calculate_features(prices.iloc[-self.lookback:])
                if features is None:
                    continue
                
                # 预测
                features_scaled = self.scalers[symbol].transform(features.reshape(1, -1))
                prob = self.models[symbol].predict_proba(features_scaled)[0]
                
                # 上涨概率
                predictions[symbol] = prob[1]
            
            if not predictions:
                return
            
            # 选择 top_n 个最可能上涨的股票
            top_symbols = sorted(predictions.items(), key=lambda x: x[1], reverse=True)[:self.top_n]
            
            print(f"[{current_time}] ML 预测 Top {self.top_n}:")
            for sym, prob in top_symbols:
                print(f"  {sym}: {prob:.2%}")
            
            # 清仓当前持仓
            for symbol, position in portfolio.positions.items():
                if position.quantity > 0 and symbol not in [s for s, _ in top_symbols]:
                    broker.place_order(
                        Order(symbol, OrderSide.SELL, OrderType.MARKET, 
                             position.quantity, current_time)
                    )
            
            # 买入 top_n
            target_value = portfolio.total_value / self.top_n
            
            for symbol, prob in top_symbols:
                if prob < 0.55:  # 置信度阈值
                    continue
                
                price = event.data.get(symbol, {}).get('close', event.data.get(symbol, {}).get('adj_close'))
                if price is None:
                    continue
                
                target_qty = int(target_value / price)
                current_qty = portfolio.positions.get(symbol, Position()).quantity
                
                if target_qty > current_qty:
                    qty = target_qty - current_qty
                    broker.place_order(
                        Order(symbol, OrderSide.BUY, OrderType.MARKET, qty, current_time)
                    )


from localquant.core.portfolio import Position
