"""
JSON 结构化日志模块
支持日志分析和审计追踪
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # 添加额外字段（如果存在）
        if hasattr(record, 'event'):
            log_obj['event'] = record.event
        if hasattr(record, 'data') and record.data:
            log_obj['data'] = record.data
        
        # 添加异常信息
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_obj, ensure_ascii=False, default=str)


class StructuredLogger:
    """结构化日志包装器
    
    使用方式:
        logger = StructuredLogger('trading')
        logger.info('下单成功', event='order_filled', data={'symbol': 'AAPL', 'qty': 100})
    """
    
    def __init__(self, name: str, level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        # 清除现有处理器
        self.logger.handlers.clear()
        
        # 添加 JSON 处理器
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        self.logger.addHandler(handler)
    
    def _log(self, level: int, message: str, event: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        """内部日志方法"""
        extra = {}
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


# 便捷函数：记录交易事件
def log_trade_event(symbol: str, side: str, qty: int, price: float, status: str, order_id: str = None):
    """记录交易事件"""
    logger = StructuredLogger('trading')
    logger.info(
        f"{side.upper()} {qty} {symbol} @ ${price:.2f}",
        event='trade_executed',
        data={
            'symbol': symbol,
            'side': side,
            'qty': qty,
            'price': price,
            'status': status,
            'order_id': order_id,
        }
    )


def log_risk_event(event_type: str, level: str, value: float, action: str):
    """记录风控事件"""
    logger = StructuredLogger('risk')
    logger.warning(
        f"风控触发: {event_type}={value:.2f} -> {action}",
        event='risk_triggered',
        data={
            'type': event_type,
            'level': level,
            'value': value,
            'action': action,
        }
    )


def log_portfolio_snapshot(cash: float, portfolio_value: float, positions_count: int, timestamp: str = None):
    """记录组合快照"""
    logger = StructuredLogger('portfolio')
    logger.info(
        f"组合快照: NAV=${portfolio_value:,.2f}, Cash=${cash:,.2f}, Positions={positions_count}",
        event='portfolio_snapshot',
        data={
            'cash': cash,
            'portfolio_value': portfolio_value,
            'positions_count': positions_count,
            'timestamp': timestamp or datetime.now(timezone.utc).isoformat(),
        }
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
    log_portfolio_snapshot(100000.0, 500000.0, 15)
