"""
告警管理模块 - 统一订单、风控、执行异常告警

P2修复：新增 AlertManager，集中管理订单失败、风控触发等关键事件的告警，
并将告警记录写入 alerts/ 目录，供后续审计和监控。

支持:
- 控制台日志
- JSON 文件持久化 (alerts/alerts_YYYYMMDD.json)
- 可选扩展: 邮件、Slack、Telegram 等 webhook（当前预留接口）
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from logging_config import setup_logging

# P2修复：统一全链路日志格式
setup_logging()
logger = logging.getLogger('alert_manager')


ALERTS_DIR = os.path.join(os.path.dirname(__file__), 'alerts')
os.makedirs(ALERTS_DIR, exist_ok=True)

# 告警级别
LEVEL_INFO = 'INFO'
LEVEL_WARNING = 'WARNING'
LEVEL_CRITICAL = 'CRITICAL'


class AlertManager:
    """统一告警管理器"""

    def __init__(self, enabled: bool = True, alert_file: Optional[str] = None):
        """
        初始化告警管理器

        参数:
            enabled: bool, 是否启用告警
            alert_file: str, 可选，指定告警记录文件路径
        """
        self.enabled = enabled
        self.alert_file = alert_file or os.path.join(
            ALERTS_DIR, f"alerts_{datetime.now():%Y%m%d}.json"
        )
        self._alert_buffer: List[Dict[str, Any]] = []

    def _write_alert(self, level: str, category: str, message: str, context: Optional[Dict[str, Any]] = None):
        """写入一条告警记录"""
        if not self.enabled:
            return

        alert = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'category': category,
            'message': message,
            'context': context or {},
        }

        self._alert_buffer.append(alert)

        # 同时输出到日志
        log_msg = f"[ALERT-{level}] {category}: {message}"
        if level == LEVEL_CRITICAL:
            logger.critical(log_msg)
        elif level == LEVEL_WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # 追加写入 JSON 文件
        try:
            with open(self.alert_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(alert, ensure_ascii=False, default=str) + '\n')
        except (OSError, IOError) as e:
            logger.error(f"告警写入文件失败: {e}")

    def send_alert(self, level: str, category: str, message: str, context: Optional[Dict[str, Any]] = None):
        """发送通用告警"""
        self._write_alert(level, category, message, context)

    # ------------------------------------------------------------------
    # 订单相关告警
    # ------------------------------------------------------------------
    def order_failed(self, symbol: str, side: str, qty: Any, reason: str, order_id: Optional[str] = None):
        """订单提交失败"""
        self._write_alert(
            LEVEL_CRITICAL,
            'ORDER_FAILED',
            f"订单提交失败 {symbol} {side} {qty}: {reason}",
            {'symbol': symbol, 'side': side, 'qty': qty, 'reason': reason, 'order_id': order_id},
        )

    def order_rejected(self, symbol: str, side: str, qty: Any, reason: str, order_id: Optional[str] = None):
        """订单被券商拒绝"""
        self._write_alert(
            LEVEL_CRITICAL,
            'ORDER_REJECTED',
            f"订单被拒绝 {symbol} {side} {qty}: {reason}",
            {'symbol': symbol, 'side': side, 'qty': qty, 'reason': reason, 'order_id': order_id},
        )

    def order_timeout(self, symbol: str, side: str, qty: Any, order_id: Optional[str] = None):
        """订单等待成交超时"""
        self._write_alert(
            LEVEL_WARNING,
            'ORDER_TIMEOUT',
            f"订单超时 {symbol} {side} {qty}",
            {'symbol': symbol, 'side': side, 'qty': qty, 'order_id': order_id},
        )

    def order_partial_fill(self, symbol: str, side: str, filled_qty: int, ordered_qty: int, order_id: Optional[str] = None):
        """订单部分成交"""
        self._write_alert(
            LEVEL_WARNING,
            'ORDER_PARTIAL_FILL',
            f"订单部分成交 {symbol} {side}: {filled_qty}/{ordered_qty}",
            {'symbol': symbol, 'side': side, 'filled_qty': filled_qty, 'ordered_qty': ordered_qty, 'order_id': order_id},
        )

    # ------------------------------------------------------------------
    # 风控相关告警
    # ------------------------------------------------------------------
    def risk_triggered(self, risk_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        """风控触发"""
        self._write_alert(
            LEVEL_CRITICAL,
            'RISK_TRIGGERED',
            f"风控触发 [{risk_type}]: {message}",
            {'risk_type': risk_type, **(context or {})},
        )

    def emergency_liquidation(self, reason: str, context: Optional[Dict[str, Any]] = None):
        """紧急平仓"""
        self._write_alert(
            LEVEL_CRITICAL,
            'EMERGENCY_LIQUIDATION',
            f"紧急平仓: {reason}",
            context or {},
        )

    # ------------------------------------------------------------------
    # 执行相关告警
    # ------------------------------------------------------------------
    def execution_error(self, operation: str, error: str, context: Optional[Dict[str, Any]] = None):
        """执行器错误"""
        self._write_alert(
            LEVEL_CRITICAL,
            'EXECUTION_ERROR',
            f"执行错误 [{operation}]: {error}",
            {'operation': operation, 'error': error, **(context or {})},
        )

    def pdt_blocked(self, symbol: str, side: str, reason: str):
        """PDT 阻止交易"""
        self._write_alert(
            LEVEL_WARNING,
            'PDT_BLOCKED',
            f"PDT 阻止 {symbol} {side}: {reason}",
            {'symbol': symbol, 'side': side, 'reason': reason},
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def get_recent_alerts(self, n: int = 10) -> List[Dict[str, Any]]:
        """获取最近 n 条告警"""
        return self._alert_buffer[-n:]

    def flush(self):
        """预留：批量刷新到外部系统（如 webhook、邮件）"""
        pass


# 全局默认告警管理器实例
_default_alert_manager = AlertManager()


def get_alert_manager(enabled: bool = True) -> AlertManager:
    """获取告警管理器实例"""
    return AlertManager(enabled=enabled)


if __name__ == '__main__':
    # 简单测试
    mgr = AlertManager()
    mgr.order_failed('AAPL', 'buy', 100, 'insufficient_buying_power', 'order-123')
    mgr.risk_triggered('DRAWDOWN', '累计回撤超过 15%', {'current_nav': 0.85})
    print(f"告警已写入: {mgr.alert_file}")
