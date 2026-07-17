"""
风险监控模块 - 实时监控和风险告警
支持回撤监控、仓位限制、异常检测
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import logging
import json
import os
import threading

# 日志设置（P2修复：统一使用 logging_config 的格式）
logger = logging.getLogger(__name__)

# P2修复：引入统一告警管理器
try:
    from alert_manager import AlertManager
    ALERT_MGR_AVAILABLE = True
except ImportError:
    ALERT_MGR_AVAILABLE = False

# 告警记录
ALERTS_DIR = os.path.join(os.path.dirname(__file__), 'alerts')
os.makedirs(ALERTS_DIR, exist_ok=True)

# 持久化状态目录
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)


class RiskMonitor:
    """风险监控器"""
    
    def __init__(self, 
                 max_drawdown_limit=0.15,
                 max_position_pct=0.20,
                 max_sector_pct=0.30,
                 daily_loss_limit=0.03,
                 vix_pause_level=35.0,
                 alert_callbacks=None,
                 alert_manager=None,
                 state_file=None,
                 kill_switch_file=None):
        """
        初始化风险监控器
        
        参数:
            max_drawdown_limit: float, 最大回撤限制 (15%)
            max_position_pct: float, 单仓上限 (20%)
            max_sector_pct: float, 单行业上限 (30%)
            daily_loss_limit: float, 日亏损限制 (3%)
            vix_pause_level: float, VIX暂停交易水平
            alert_callbacks: list, 告警回调函数列表
            alert_manager: AlertManager, 可选统一告警管理器（P2修复）
            state_file: str, 可选持久化状态文件路径
            kill_switch_file: str, 可选 kill switch 文件路径
        """
        self.limits = {
            'max_drawdown': max_drawdown_limit,
            'max_position': max_position_pct,
            'max_sector': max_sector_pct,
            'daily_loss': daily_loss_limit,
            'vix_pause': vix_pause_level,
        }
        
        self.alert_callbacks = alert_callbacks or []
        self.alert_manager = alert_manager
        if self.alert_manager is None and ALERT_MGR_AVAILABLE:
            self.alert_manager = AlertManager(enabled=True)
        
        # P0: 线程安全状态
        self._lock = threading.Lock()
        self._trading_halted = False
        
        # P1: 持久化相关状态
        self.state_file = state_file or os.path.join(DATA_DIR, 'risk_state.json')
        self.kill_switch_file = kill_switch_file or os.path.join(DATA_DIR, 'kill_switch')
        self._kill_switch_triggered = False
        self.halt_reason = None
        self.halt_time = None
        self.max_dd_seen = 0.0
        
        self.alerts_history = []
        self.nav_history = []
        self.position_history = []
        
        # 风险状态
        self.risk_level = 'NORMAL'  # NORMAL, ELEVATED, HIGH, CRITICAL
        
        # 启动时加载历史状态
        self._load_state()
        
        logger.info(f"[OK] Risk monitor started")
        logger.info(f"   Max drawdown limit: {max_drawdown_limit:.1%}")
        logger.info(f"   Max position limit: {max_position_pct:.1%}")
        logger.info(f"   VIX pause level: {vix_pause_level}")
    
    @property
    def trading_halted(self):
        """线程安全读取交易暂停状态"""
        with self._lock:
            return self._trading_halted
    
    @trading_halted.setter
    def trading_halted(self, value):
        """线程安全写入交易暂停状态"""
        with self._lock:
            self._trading_halted = value
    
    def _load_state(self):
        """从历史状态文件加载风控状态"""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if not isinstance(state, dict):
                return
            with self._lock:
                self._trading_halted = bool(state.get('trading_halted', False))
                self.halt_reason = state.get('halt_reason')
                halt_time_str = state.get('halt_time')
                self.halt_time = datetime.fromisoformat(halt_time_str) if halt_time_str else None
                self.max_dd_seen = float(state.get('max_dd_seen', 0.0))
                self._kill_switch_triggered = bool(state.get('kill_switch_triggered', False))
            logger.info(f"[OK] Loaded risk state from {self.state_file}")
        except Exception as e:
            logger.warning(f"Failed to load risk state from {self.state_file}: {e}")
    
    def persist_state(self):
        """将风控状态持久化到磁盘"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with self._lock:
                state = {
                    'trading_halted': self._trading_halted,
                    'halt_reason': self.halt_reason,
                    'halt_time': self.halt_time.isoformat() if self.halt_time else None,
                    'max_dd_seen': self.max_dd_seen,
                    'kill_switch_triggered': self._kill_switch_triggered,
                    'persisted_at': datetime.now().isoformat(),
                }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to persist risk state: {e}")
    
    def halt_trading(self, reason, alert_type='HALT'):
        """暂停交易并记录原因，同时持久化状态"""
        with self._lock:
            self._trading_halted = True
            self.halt_reason = reason
            self.halt_time = datetime.now()
        logger.critical(f"[HALT] Trading halted: {reason}")
        if alert_type:
            self._trigger_alert(alert_type, f'Trading halted: {reason}', {'reason': reason})
        self.persist_state()
    
    def resume_trading(self, reason=None):
        """恢复交易，同时持久化状态"""
        with self._lock:
            self._trading_halted = False
            self.halt_reason = None
            self.halt_time = None
        msg = f"Trading resumed"
        if reason:
            msg = f"Trading resumed: {reason}"
        logger.info(f"[RESUME] {msg}")
        self.persist_state()
    
    def check_remote_kill_switch(self):
        """
        检查远程 kill switch：
        - 文件 data/kill_switch 存在
        - 或环境变量 MULTIFACTOR_KILL_SWITCH=1
        
        返回:
            bool: 是否被触发
        """
        if self._kill_switch_triggered:
            return True
        triggered = (
            os.environ.get('MULTIFACTOR_KILL_SWITCH') == '1'
            or os.path.exists(self.kill_switch_file)
        )
        if triggered:
            self._kill_switch_triggered = True
            reason = 'Remote kill switch triggered'
            logger.critical(f"[KILL_SWITCH] {reason}")
            self.halt_trading(reason, alert_type='KILL_SWITCH')
        return self._kill_switch_triggered
    
    
    def check_drawdown(self, current_nav):
        """
        检查回撤
        
        参数:
            current_nav: float, 当前NAV
        
        返回:
            bool: 是否触发暂停
        """
        self.nav_history.append({
            'timestamp': datetime.now(),
            'nav': current_nav
        })
        # P1: 限制历史记录长度，防止内存无限增长
        if len(self.nav_history) > 1000:
            self.nav_history = self.nav_history[-1000:]
        
        if len(self.nav_history) < 2:
            return False
        
        # 计算回撤
        nav_series = pd.Series([h['nav'] for h in self.nav_history])
        peak = nav_series.cummax().iloc[-1]
        drawdown = (current_nav - peak) / peak
        
        # P1: 跟踪历史最大回撤幅度
        if drawdown < 0 and abs(drawdown) > self.max_dd_seen:
            self.max_dd_seen = abs(drawdown)
        
        if drawdown <= -self.limits['max_drawdown']:
            self.halt_trading(
                f'Drawdown exceeded: {drawdown:.2%} (limit: {-self.limits["max_drawdown"]:.1%})',
                alert_type='DRAWDOWN'
            )
            # P0: 回撤触发时真正暂停交易
            return True
        
        return False
    
    def check_position_limits(self, positions, portfolio_value):
        """
        检查仓位限制
        
        参数:
            positions: dict, {symbol: {'qty': int, 'market_value': float}}
            portfolio_value: float, 组合总价值
        
        返回:
            list: 触发的告警
        """
        alerts = []
        
        # 检查单仓限制
        for symbol, pos in positions.items():
            weight = pos['market_value'] / portfolio_value
            
            if weight > self.limits['max_position']:
                alerts.append({
                    'type': 'POSITION_LIMIT',
                    'symbol': symbol,
                    'weight': weight,
                    'limit': self.limits['max_position'],
                    'message': f'{symbol} position limit exceeded: {weight:.1%} (limit: {self.limits["max_position"]:.1%})'
                })
        
        # 检查行业集中度
        sector_weights = self._calculate_sector_weights(positions, portfolio_value)
        for sector, weight in sector_weights.items():
            if weight > self.limits['max_sector']:
                alerts.append({
                    'type': 'SECTOR_LIMIT',
                    'sector': sector,
                    'weight': weight,
                    'limit': self.limits['max_sector'],
                    'message': f'{sector} sector concentration too high: {weight:.1%}'
                })
        
        # 触发告警
        for alert in alerts:
            self._trigger_alert(alert['type'], alert['message'], alert)
        
        return alerts
    
    def check_daily_loss(self, daily_return):
        """
        检查日亏损
        
        参数:
            daily_return: float, 日收益率（如 -0.03 表示 -3%）
        
        返回:
            bool: 是否触发告警
        """
        # P1/P2: 确保接口签名可用，防御非数值输入
        try:
            daily_return = float(daily_return)
        except (TypeError, ValueError):
            logger.warning(f"check_daily_loss received non-numeric input: {daily_return}")
            return False
        
        if daily_return <= -self.limits['daily_loss']:
            self.halt_trading(
                f'Daily loss exceeded: {daily_return:.2%} (limit: {-self.limits["daily_loss"]:.1%})',
                alert_type='DAILY_LOSS'
            )
            # P0: 日亏损触发时真正暂停交易
            return True
        return False
    
    def check_vix_level(self, vix_value):
        """
        检查VIX水平

        P2 修复：VIX 不可用时保守跳过，不进行交易决策。

        参数:
            vix_value: float or None, 当前VIX

        返回:
            str: 风险等级
        """
        if vix_value is None:
            logger.warning("[VIX] VIX unavailable, conservatively skipping VIX risk check")
            return self.risk_level
        try:
            vix_value = float(vix_value)
        except (TypeError, ValueError):
            logger.warning("[VIX] Invalid VIX value: %s, skipping check", vix_value)
            return self.risk_level

        if vix_value >= self.limits['vix_pause']:
            self.risk_level = 'CRITICAL'
            self.halt_trading(
                f'VIX extremely high: {vix_value:.1f} (limit: {self.limits["vix_pause"]})',
                alert_type='VIX_HIGH'
            )
        elif vix_value >= 30:
            self.risk_level = 'HIGH'
            self._trigger_alert(
                'VIX_ELEVATED',
                f'VIX elevated: {vix_value:.1f}',
                {'vix': vix_value}
            )
        elif vix_value >= 25:
            self.risk_level = 'ELEVATED'
        else:
            self.risk_level = 'NORMAL'
            # P0: VIX 回落不再自动恢复交易；恢复必须显式调用 resume_trading()

        return self.risk_level
    
    def check_concentration_risk(self, positions, portfolio_value):
        """
        检查集中度风险
        
        参数:
            positions: dict, 持仓
            portfolio_value: float, 组合价值
        
        返回:
            dict: 集中度指标
        """
        # P1/P2: 确保接口签名可用，防御组合价值异常
        if not positions or portfolio_value <= 0:
            return {'hh_index': 0, 'top5_concentration': 0}
        
        weights = [p['market_value'] / portfolio_value for p in positions.values()]
        weights = sorted(weights, reverse=True)
        
        # 赫芬达尔指数
        hh_index = sum(w**2 for w in weights)
        
        # 前5大持仓集中度
        top5_concentration = sum(weights[:5]) if len(weights) >= 5 else sum(weights)
        
        metrics = {
            'hh_index': hh_index,
            'top5_concentration': top5_concentration,
            'num_positions': len(positions),
        }
        
        # 检查集中度告警
        if hh_index > 0.15:  # 高度集中
            self._trigger_alert(
                'CONCENTRATION',
                f'High concentration: HHI={hh_index:.3f}',
                metrics
            )
        
        return metrics
    
    def _calculate_sector_weights(self, positions, portfolio_value):
        """计算行业权重 - 使用 INDUSTRY 映射"""
        # 导入策略的行业映射
        try:
            from main import INDUSTRY
        except ImportError:
            INDUSTRY = {}
        
        sector_weights = {}
        
        for symbol, pos in positions.items():
            # 使用 INDUSTRY 映射获取行业
            sector = INDUSTRY.get(symbol, 'other')
            weight = pos['market_value'] / portfolio_value
            
            if sector not in sector_weights:
                sector_weights[sector] = 0
            sector_weights[sector] += weight
        
        return sector_weights
    
    def _send_alert(self, method, *args, **kwargs):
        """P2修复：统一封装告警调用"""
        if self.alert_manager is not None and hasattr(self.alert_manager, method):
            try:
                getattr(self.alert_manager, method)(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Alert send failed: {e}")

    def _trigger_alert(self, alert_type, message, data):
        """触发告警"""
        alert = {
            'timestamp': datetime.now().isoformat(),
            'type': alert_type,
            'level': self.risk_level,
            'message': message,
            'data': data,
        }
        
        self.alerts_history.append(alert)
        # P1: 限制告警历史长度，防止内存无限增长
        if len(self.alerts_history) > 1000:
            self.alerts_history = self.alerts_history[-1000:]
        
        
        # 记录日志
        logger.warning(f"[ALERT] [{alert_type}] {message}")
        
        # P2修复：通过统一告警管理器发送风控告警
        self._send_alert('risk_triggered', alert_type, message, data)
        
        # 执行回调
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")
        
        # 保存到文件
        self._save_alert(alert)
    
    def _save_alert(self, alert):
        """保存告警到文件"""
        filename = f"alerts_{datetime.now():%Y%m%d}.json"
        filepath = os.path.join(ALERTS_DIR, filename)

        # 读取现有告警（损坏时自动重置为空列表）
        alerts = []
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    alerts = json.load(f)
                    if not isinstance(alerts, list):
                        alerts = []
            except json.JSONDecodeError:
                logger.warning(f"Alert file {filepath} corrupted, will reset")
                alerts = []
            except Exception as e:
                logger.warning(f"Failed to read alert file: {e}")
                alerts = []

        alerts.append(alert)

        # 保存
        try:
            with open(filepath, 'w') as f:
                json.dump(alerts, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save alert file: {e}")
    
    def get_risk_summary(self):
        """获取风险摘要"""
        return {
            'risk_level': self.risk_level,
            'trading_halted': self.trading_halted,
            'halt_reason': self.halt_reason,
            'halt_time': self.halt_time.isoformat() if self.halt_time else None,
            'max_dd_seen': self.max_dd_seen,
            'total_alerts': len(self.alerts_history),
            'recent_alerts': self.alerts_history[-5:] if self.alerts_history else [],
            'limits': self.limits,
        }
    
    def generate_risk_report(self):
        """生成风险报告"""
        report = {
            'generated_at': datetime.now().isoformat(),
            'risk_level': self.risk_level,
            'trading_halted': self.trading_halted,
            'halt_reason': self.halt_reason,
            'halt_time': self.halt_time.isoformat() if self.halt_time else None,
            'max_dd_seen': self.max_dd_seen,
            'alerts_count': len(self.alerts_history),
            'alerts_by_type': {},
            'limits': self.limits,
        }
        
        # 统计告警类型
        for alert in self.alerts_history:
            alert_type = alert['type']
            report['alerts_by_type'][alert_type] = report['alerts_by_type'].get(alert_type, 0) + 1
        
        # 保存报告
        filename = f"risk_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        filepath = os.path.join(ALERTS_DIR, filename)
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"[OK] Risk report generated: {filepath}")
        return report


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    # 创建监控器
    monitor = RiskMonitor()
    
    # 模拟数据
    nav = 1.0
    positions = {
        'AAPL': {'qty': 100, 'market_value': 20000},
        'MSFT': {'qty': 50, 'market_value': 25000},
    }
    portfolio_value = 100000
    
    # 检查风险
    print("\nRisk check example:")
    monitor.check_drawdown(nav)
    monitor.check_position_limits(positions, portfolio_value)
    monitor.check_vix_level(40)
    
    # 打印摘要
    summary = monitor.get_risk_summary()
    print(f"\nRisk level: {summary['risk_level']}")
    print(f"Trading halted: {summary['trading_halted']}")
    print(f"Total alerts: {summary['total_alerts']}")
    
    # 生成报告
    monitor.generate_risk_report()
