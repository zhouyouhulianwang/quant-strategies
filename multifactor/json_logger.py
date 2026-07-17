"""
JSON 结构化日志模块
支持日志分析和审计追踪

本模块中的便捷函数统一使用 logging.getLogger('json') 输出结构化事件，
字段名与 logging_config.JSONFormatter 保持一致：timestamp、level、event、
symbol、qty、side、price、status、nav、drawdown、message 等。
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from logging_config import JSONFormatter


class StructuredLogger:
    """结构化日志包装器（保留以兼容旧代码）

    使用方式:
        logger = StructuredLogger('trading')
        logger.info('下单成功', event='order_filled', data={'symbol': 'AAPL', 'qty': 100})
    """

    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # 清除现有处理器，避免重复
        self.logger.handlers.clear()

        # 添加 JSON 处理器
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)

    def _log(self, level: int, message: str, event: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        """内部日志方法"""
        extra: Dict[str, Any] = {}
        if event:
            extra['event'] = event
        if data:
            extra['data'] = data

        self.logger.log(level, message, extra=extra)

    def debug(self, message: str, event: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        self._log(logging.DEBUG, message, event, data)

    def info(self, message: str, event: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        self._log(logging.INFO, message, event, data)

    def warning(self, message: str, event: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        self._log(logging.WARNING, message, event, data)

    def error(self, message: str, event: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        self._log(logging.ERROR, message, event, data)

    def critical(self, message: str, event: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        self._log(logging.CRITICAL, message, event, data)


def _ensure_json_logger() -> logging.Logger:
    """确保 'json' logger 已配置 JSON 处理器。"""
    logger = logging.getLogger('json')
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger


# 便捷函数：记录交易事件
def log_trade_event(symbol: str, side: str, qty: int, price: float, status: str, order_id: str = None):
    """记录交易事件

    输出字段：timestamp、level、event、message、symbol、qty、side、price、status、order_id
    """
    logger = _ensure_json_logger()
    logger.info(
        f"{side.upper()} {qty} {symbol} @ ${price:.2f}",
        extra={
            'event': 'trade_executed',
            'symbol': symbol,
            'side': side,
            'qty': qty,
            'price': price,
            'status': status,
            'order_id': order_id,
        }
    )


def log_risk_event(event_type: str, level: str, value: float, action: str):
    """记录风控事件

    输出字段：timestamp、level、event、message、type、level、value、action
    """
    logger = _ensure_json_logger()
    logger.warning(
        f"风控触发: {event_type}={value:.2f} -> {action}",
        extra={
            'event': 'risk_triggered',
            'type': event_type,
            'level': level,
            'value': value,
            'action': action,
        }
    )


def log_portfolio_snapshot(cash: float, portfolio_value: float, positions_count: int, timestamp: str = None, drawdown: Optional[float] = None):
    """记录组合快照

    输出字段：timestamp、level、event、message、nav、cash、positions_count、drawdown
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    logger = _ensure_json_logger()
    extra = {
        'event': 'portfolio_snapshot',
        'nav': portfolio_value,
        'cash': cash,
        'positions_count': positions_count,
        'timestamp': ts,
    }
    if drawdown is not None:
        extra['drawdown'] = drawdown

    logger.info(
        f"组合快照: NAV=${portfolio_value:,.2f}, Cash=${cash:,.2f}, Positions={positions_count}",
        extra=extra,
    )


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    # 示例 1: 普通结构化日志
    logger = StructuredLogger('test')
    logger.info('系统启动', event='system_start', data={'version': '1.0.0'})

    # 示例 2: 交易事件
    log_trade_event('AAPL', 'buy', 100, 150.25, 'filled', 'order-12345')

    # 示例 3: 风控事件
    log_risk_event('vix_spike', 'critical', 36.5, 'emergency_liquidation')

    # 示例 4: 组合快照
    log_portfolio_snapshot(100000.0, 500000.0, 15, drawdown=0.05)
