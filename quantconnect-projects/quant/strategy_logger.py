"""
Strategy Logger Module
通用策略日志模块，为所有策略提供统一的日志记录功能
"""

import logging
import os
from datetime import datetime

class StrategyLogger:
    """策略日志记录器"""
    
    def __init__(self, strategy_name, log_dir="logs"):
        """
        初始化日志记录器
        
        Args:
            strategy_name: 策略名称
            log_dir: 日志目录
        """
        self.strategy_name = strategy_name
        self.log_dir = log_dir
        self.logger = None
        self._setup_logger()
        
    def _setup_logger(self):
        """配置日志记录器"""
        # 创建日志目录
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
        # 创建日志文件名（按日期）
        date_str = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(self.log_dir, f"{self.strategy_name}_{date_str}.log")
        
        # 配置日志记录器
        self.logger = logging.getLogger(self.strategy_name)
        self.logger.setLevel(logging.DEBUG)
        
        # 如果已经配置过处理器，不再重复配置
        if self.logger.handlers:
            return
            
        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 日志格式
        formatter = logging.Formatter(
            '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
    def debug(self, message):
        """调试日志"""
        if self.logger:
            self.logger.debug(message)
            
    def info(self, message):
        """信息日志"""
        if self.logger:
            self.logger.info(message)
            
    def warning(self, message):
        """警告日志"""
        if self.logger:
            self.logger.warning(message)
            
    def error(self, message):
        """错误日志"""
        if self.logger:
            self.logger.error(message)
            
    def trade(self, action, symbol, quantity, price, reason=""):
        """
        交易日志
        
        Args:
            action: 交易动作（BUY/SELL）
            symbol: 交易标的
            quantity: 交易数量
            price: 交易价格
            reason: 交易原因
        """
        message = f"[TRADE] {action} {symbol} | Qty: {quantity} | Price: ${price:.2f}"
        if reason:
            message += f" | Reason: {reason}"
        self.info(message)
        
    def performance(self, metric_name, value, details=""):
        """
        性能日志
        
        Args:
            metric_name: 指标名称
            value: 指标值
            details: 详细信息
        """
        message = f"[PERF] {metric_name}: {value}"
        if details:
            message += f" | {details}"
        self.info(message)
        
    def portfolio(self, total_value, cash, positions_count):
        """
        投资组合日志
        
        Args:
            total_value: 总资产
            cash: 现金
            positions_count: 持仓数量
        """
        message = f"[PORTFOLIO] Total: ${total_value:,.2f} | Cash: ${cash:,.2f} | Positions: {positions_count}"
        self.info(message)
        
    def signal(self, signal_type, symbol, strength, details=""):
        """
        交易信号日志
        
        Args:
            signal_type: 信号类型（BUY/SELL/HOLD）
            symbol: 标的
            strength: 信号强度
            details: 详细信息
        """
        message = f"[SIGNAL] {signal_type} {symbol} | Strength: {strength:.2f}"
        if details:
            message += f" | {details}"
        self.info(message)
        
    def risk(self, risk_type, level, details=""):
        """
        风险日志
        
        Args:
            risk_type: 风险类型
            level: 风险等级
            details: 详细信息
        """
        message = f"[RISK] {risk_type} | Level: {level}"
        if details:
            message += f" | {details}"
        self.warning(message)

# 便捷的日志装饰器
def log_execution_time(logger):
    """记录函数执行时间的装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = datetime.now()
            try:
                result = func(*args, **kwargs)
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.debug(f"[EXEC] {func.__name__} completed in {duration:.3f}s")
                return result
            except Exception as e:
                logger.error(f"[EXEC] {func.__name__} failed: {str(e)}")
                raise
        return wrapper
    return decorator
