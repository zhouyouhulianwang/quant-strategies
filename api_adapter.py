#!/usr/bin/env python3
"""
QuantAlpha API 适配层 - 统一接口封装
解决接口漂移问题，提供一致的 API
"""
import sys, os
sys.path.insert(0, '.')

from core.backtest_v2 import BacktestEngineV2, Portfolio, RiskEngine, Signal
from application.portfolio_engine import PortfolioEngine as AppPortfolioEngine, Order, OrderSide, OrderType
from application.risk_engine import RiskEngine as AppRiskEngine, RiskLimit, RiskResult
from execution.broker_connectors import AlpacaConnector, BinanceConnector, InteractiveBrokersConnector, OANDAConnector
from execution.paper_trading import PaperTradingSystem, PaperTradingConfig, SimulatedExchangeConnector
from data.technical_indicators import vwap, supertrend, ichimoku_cloud, fibonacci_retracement, chandelier_exit, money_flow_index, pivot_points, volume_profile
from data.validator_enhanced import DataValidator, ValidationResult, DataCleaner
from infrastructure.security.rbac import RBACManager, Role, Permission, User
from infrastructure.security.encryption import APIKeyEncryption, SecureConfig, get_encryption
from domain.portfolio.portfolio import Position

class QuantAlphaAPI:
    """QuantAlpha 统一 API 适配器"""
    
    @staticmethod
    def create_backtest_engine():
        """创建回测引擎"""
        return BacktestEngineV2()
    
    @staticmethod
    def create_portfolio():
        """创建投资组合"""
        return Portfolio()
    
    @staticmethod
    def add_position(portfolio, symbol, quantity, price, side='long'):
        """添加持仓 - 适配不同接口"""
        position = Position(symbol, quantity, price, side)
        portfolio.add_position(position)
        return position
    
    @staticmethod
    def get_portfolio_value(portfolio):
        """获取投资组合价值"""
        return portfolio.total_value
    
    @staticmethod
    def create_order(symbol, side, quantity, price=None, order_type='MARKET'):
        """创建订单"""
        side_enum = OrderSide.BUY if side == 'BUY' else OrderSide.SELL
        return Order(symbol=symbol, side=side_enum, quantity=quantity, limit_price=price)
    
    @staticmethod
    def calculate_var(returns, confidence=0.95):
        """计算 VaR - 使用风险引擎"""
        # 简化实现
        if not returns:
            return 0.0
        sorted_returns = sorted(returns)
        index = int((1 - confidence) * len(sorted_returns))
        return abs(sorted_returns[index]) if index < len(sorted_returns) else 0.0
    
    @staticmethod
    def calculate_sma(prices, window=20):
        """计算简单移动平均"""
        if len(prices) < window:
            return [sum(prices) / len(prices)] * len(prices)
        result = []
        for i in range(len(prices)):
            if i < window - 1:
                result.append(sum(prices[:i+1]) / (i+1))
            else:
                result.append(sum(prices[i-window+1:i+1]) / window)
        return result
    
    @staticmethod
    def validate_ohlcv(data):
        """验证 OHLCV 数据"""
        validator = DataValidator()
        result = validator.validate_prices(data)
        return ValidationResult(is_valid=result, errors=[])
    
    @staticmethod
    def create_paper_trading_system(initial_capital=100000):
        """创建模拟交易系统"""
        config = PaperTradingConfig()
        config.initial_capital = initial_capital
        return PaperTradingSystem(config)
    
    @staticmethod
    def authenticate_user(username, password):
        """用户认证"""
        rbac = RBACManager()
        return rbac.authenticate(username, password)
    
    @staticmethod
    def check_permission(user, permission_str):
        """检查权限"""
        perm = getattr(Permission, permission_str, None)
        if perm is None:
            return False
        return user.has_permission(perm)
    
    @staticmethod
    def encrypt_api_key(api_key, secret_key):
        """加密 API 密钥"""
        encryption = APIKeyEncryption()
        return encryption.encrypt(api_key, secret_key)

# 便捷导入
__all__ = [
    'QuantAlphaAPI',
    'BacktestEngineV2', 'Portfolio', 'Position', 'RiskEngine', 'Signal',
    'AppPortfolioEngine', 'Order', 'OrderSide', 'OrderType',
    'AppRiskEngine', 'RiskLimit', 'RiskResult',
    'AlpacaConnector', 'BinanceConnector', 'InteractiveBrokersConnector', 'OANDAConnector',
    'PaperTradingSystem', 'PaperTradingConfig', 'SimulatedExchangeConnector',
    'DataValidator', 'ValidationResult', 'DataCleaner',
    'RBACManager', 'Role', 'Permission', 'User',
    'APIKeyEncryption', 'SecureConfig',
    'vwap', 'supertrend', 'ichimoku_cloud', 'fibonacci_retracement',
    'chandelier_exit', 'money_flow_index', 'pivot_points', 'volume_profile',
]
