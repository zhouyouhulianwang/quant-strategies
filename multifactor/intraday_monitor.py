"""
盘中监控模块 - VIX 实时监控和紧急平仓
支持日内风险事件触发自动保护
"""

import time
import logging
import threading
import json
import os
from datetime import datetime, timedelta
from typing import Callable, Optional

# P2修复：统一全链路日志格式
logger = logging.getLogger(__name__)

try:
    from json_logger import log_risk_event
    JSON_LOGGER_AVAILABLE = True
except ImportError:
    JSON_LOGGER_AVAILABLE = False

# 持久化状态目录
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# 默认保留的最近强平事件数量
DEFAULT_MAX_PENDING_LIQUIDATIONS = 10


class IntradayMonitor:
    """
    盘中监控器
    
    监控指标:
    - VIX 飙升 (>30)
    - 组合回撤 (>10% 日内)
    - 单只股票暴跌 (>5%)
    - 市场熔断信号
    """
    
    def __init__(self, executor, risk_monitor, 
                 check_interval=60,  # 检查间隔（秒）
                 vix_emergency_level=35.0,
                 max_intraday_dd=0.10,
                 single_stock_limit=0.05,
                 max_total_drawdown=0.15,
                 state_file=None,
                 max_pending_liquidations=DEFAULT_MAX_PENDING_LIQUIDATIONS):
        """
        初始化盘中监控
        
        参数:
            executor: AlpacaExecutor
            risk_monitor: RiskMonitor
            check_interval: int, 检查间隔（秒）
            vix_emergency_level: float, VIX 紧急平仓阈值
            max_intraday_dd: float, 最大日内回撤
            single_stock_limit: float, 单只股票跌幅限制
            max_total_drawdown: float, 最大累计回撤（P1 修复）
            state_file: str, 可选持久化状态文件路径
            max_pending_liquidations: int, 保留的最近强平事件数量
        """
        self.executor = executor
        self.risk_monitor = risk_monitor
        self.check_interval = check_interval
        self.vix_emergency_level = vix_emergency_level
        self.max_intraday_dd = max_intraday_dd
        self.single_stock_limit = single_stock_limit
        self.max_total_drawdown = max_total_drawdown
        
        # 线程锁（防止和主交易线程竞态）
        # P0: 交易暂停状态统一由 RiskMonitor 持有，本模块仅做代理
        
        # P1-4: 统一锁保护 monitoring、daily_high_nav、peak_nav、
        # _current_date 和 _pending_liquidation_reasons 等可变状态
        self._lock = threading.Lock()
        
        # 状态
        self._monitoring = False
        self.monitor_thread = None
        self.daily_high_nav = None
        self.last_check_time = None
        self._current_date = None  # 用于每日重置日内高点
        
        # P1 修复：累计回撤跟踪
        self.peak_nav = None
        
        # P1修复: 收盘时未执行的强平请求，待次日开盘再触发
        # P1修复: 使用队列保留最近 N 条强平事件，避免新事件覆盖旧原因
        self.state_file = state_file or os.path.join(DATA_DIR, 'intraday_state.json')
        self.max_pending_liquidations = max_pending_liquidations
        self._pending_liquidation_reasons = []
        self.on_vix_spike: Optional[Callable] = None
        self.on_drawdown: Optional[Callable] = None
        self.on_single_stock_drop: Optional[Callable] = None
        
        # 启动时加载历史状态
        self._load_state()
        
        logger.info("[OK] Intraday monitor initialized")
        logger.info(f"   VIX emergency threshold: {vix_emergency_level}")
        logger.info(f"   Intraday drawdown limit: {max_intraday_dd:.1%}")
        logger.info(f"   Total drawdown limit: {max_total_drawdown:.1%}")
    
    @property
    def trading_halted(self):
        """交易暂停状态：统一由 RiskMonitor 持有"""
        if self.risk_monitor:
            return self.risk_monitor.trading_halted
        return False
    
    @trading_halted.setter
    def trading_halted(self, value):
        """交易暂停状态：统一写入 RiskMonitor"""
        if self.risk_monitor:
            self.risk_monitor.trading_halted = value
    
    @property
    def monitoring(self):
        """线程安全读取监控运行状态"""
        with self._lock:
            return self._monitoring
    
    @monitoring.setter
    def monitoring(self, value):
        """线程安全写入监控运行状态"""
        with self._lock:
            self._monitoring = value
    
    def _load_state(self):
        """加载历史状态（如存在）"""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if not isinstance(state, dict):
                return
            with self._lock:
                self.daily_high_nav = state.get('daily_high_nav')
                self.peak_nav = state.get('peak_nav')
                current_date_str = state.get('current_date')
                self._current_date = (
                    datetime.fromisoformat(current_date_str).date()
                    if current_date_str else None
                )
                self._pending_liquidation_reasons = state.get('pending_liquidation_reasons', [])
                if not isinstance(self._pending_liquidation_reasons, list):
                    self._pending_liquidation_reasons = []
            logger.info(f"[OK] Loaded intraday state from {self.state_file}")
        except Exception as e:
            logger.warning(f"Failed to load intraday state from {self.state_file}: {e}")
    
    def persist_state(self):
        """将盘中状态持久化到磁盘"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with self._lock:
                state = {
                    'daily_high_nav': self.daily_high_nav,
                    'peak_nav': self.peak_nav,
                    'current_date': self._current_date.isoformat() if self._current_date else None,
                    'pending_liquidation_reasons': list(self._pending_liquidation_reasons),
                    'monitoring': self._monitoring,
                    'persisted_at': datetime.now().isoformat(),
                }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to persist intraday state: {e}")
    
    def _record_pending_liquidation(self, reason):
        """记录一条待执行的强平事件（带时间戳），并持久化"""
        entry = {
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
        }
        with self._lock:
            self._pending_liquidation_reasons.append(entry)
            # 保留最近 N 条
            while len(self._pending_liquidation_reasons) > self.max_pending_liquidations:
                self._pending_liquidation_reasons.pop(0)
        self.persist_state()
    
    def start(self, daemon=True):
        """启动监控线程
        
        参数:
            daemon: bool, 是否以 daemon 方式运行线程。
                   默认 True（兼容旧行为，作为主交易线程的子线程）。
                   独立进程中建议传入 False，以保证进程不随主线程退出。
        """
        if self.monitoring:
            logger.warning("Monitor already running")
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=daemon)
        self.monitor_thread.start()
        
        logger.info(f"[START] Intraday monitor started (daemon={daemon})")
    
    def join(self, timeout=None):
        """等待监控线程结束
        
        参数:
            timeout: float, 最大等待时间（秒），None 表示一直等待。
        """
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=timeout)
    
    def is_alive(self):
        """检查监控线程是否仍在运行"""
        return self.monitor_thread is not None and self.monitor_thread.is_alive()
    
    def stop(self):
        """停止监控"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("[STOP] Intraday monitor stopped")
    
    def _monitor_loop(self):
        """监控循环"""
        while True:
            with self._lock:
                if not self._monitoring:
                    break
            try:
                # P0 修复：每日开盘时重置日内高点
                today = datetime.now().date()
                with self._lock:
                    if self._current_date != today:
                        self._current_date = today
                        reset_high = True
                    else:
                        reset_high = False
                if reset_high:
                    self.reset_daily_high()
                    logger.info(f"[NEW_DAY] New day, intraday high reset: {today}")

                # P1修复: 若收盘期间触发了强平但市场关闭，开盘后执行
                while True:
                    with self._lock:
                        if not self._pending_liquidation_reasons:
                            break
                        reasons = [r['reason'] for r in self._pending_liquidation_reasons]
                    try:
                        market_open = self.executor.market_is_open()
                    except AttributeError:
                        market_open = True
                    if market_open:
                        self._execute_pending_liquidation()
                    else:
                        logger.info(f"[PENDING] Pending liquidation reasons: {reasons}, waiting for market open...")
                        break

                self._check_all()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            time.sleep(self.check_interval)
    
    def _check_all(self):
        """执行所有检查"""
        now = datetime.now()
        self.last_check_time = now
        
        # P1: 远程 kill switch 检查
        if self.risk_monitor and hasattr(self.risk_monitor, 'check_remote_kill_switch'):
            self.risk_monitor.check_remote_kill_switch()
        
        # 1. 检查 VIX
        self._check_vix()
        
        # 2. 检查日内回撤
        self._check_intraday_drawdown()
        
        # 3. 检查累计回撤（P1 修复）
        self._check_total_drawdown()
        
        # 4. 检查单只股票
        self._check_single_stocks()
    
    def _check_vix(self):
        """检查 VIX 水平"""
        try:
            # 获取最新 VIX
            vix = self._get_latest_vix()
            
            if vix is None:
                return
            
            logger.debug(f"Current VIX: {vix:.2f}")
            
            # 检查是否超过紧急阈值
            if vix >= self.vix_emergency_level:
                logger.critical(f"[ALERT] VIX emergency alert: {vix:.2f} (threshold: {self.vix_emergency_level})")
                
                # 触发紧急平仓
                self._emergency_liquidation(f"VIX spiked to {vix:.2f}")
                
                if self.on_vix_spike:
                    self.on_vix_spike(vix)
            
            # 更新风险监控
            if self.risk_monitor:
                self.risk_monitor.check_vix_level(vix)
                
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"VIX check network error: {e}")
        except Exception as e:
            logger.error(f"VIX check failed: {e}")
    
    def _check_intraday_drawdown(self):
        """检查日内回撤"""
        try:
            account = self.executor.get_account()
            if not account:
                return
            
            current_nav = account['portfolio_value']
            
            # 初始化/更新日内高点（P1-4 线程安全）
            with self._lock:
                if self.daily_high_nav is None:
                    self.daily_high_nav = current_nav
                if current_nav > self.daily_high_nav:
                    self.daily_high_nav = current_nav
                daily_high = self.daily_high_nav
            
            # 计算回撤
            if daily_high > 0:
                drawdown = (current_nav - daily_high) / daily_high
                
                logger.debug(f"Intraday drawdown: {drawdown:.2%}")
                
                if drawdown <= -self.max_intraday_dd:
                    logger.critical(
                        f"[ALERT] Intraday drawdown exceeded: {drawdown:.2%} "
                        f"(limit: {-self.max_intraday_dd:.1%})"
                    )
                    
                    self._emergency_liquidation(f"Intraday drawdown {drawdown:.2%}")
                    
                    if self.on_drawdown:
                        self.on_drawdown(drawdown)
                        
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Drawdown check network error: {e}")
        except Exception as e:
            logger.error(f"Drawdown check failed: {e}")
    
    def _check_total_drawdown(self):
        """检查累计回撤（P1 修复）"""
        try:
            account = self.executor.get_account()
            if not account:
                return
            
            current_nav = account['portfolio_value']
            
            # 初始化/更新累计高点（P1-4 线程安全）
            with self._lock:
                if self.peak_nav is None or current_nav > self.peak_nav:
                    self.peak_nav = current_nav
                peak_nav = self.peak_nav
            
            if peak_nav > 0:
                drawdown = (current_nav - peak_nav) / peak_nav
                
                logger.debug(f"Total drawdown: {drawdown:.2%}")
                
                if drawdown <= -self.max_total_drawdown:
                    logger.critical(
                        f"[ALERT] Total drawdown exceeded: {drawdown:.2%} "
                        f"(limit: {-self.max_total_drawdown:.1%})"
                    )
                    
                    self._emergency_liquidation(f"Total drawdown {drawdown:.2%}")
                    
                    if self.on_drawdown:
                        self.on_drawdown(drawdown)
                        
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Total drawdown check network error: {e}")
        except Exception as e:
            logger.error(f"Total drawdown check failed: {e}")

    def _check_single_stocks(self):
        """检查单只股票跌幅"""
        try:
            positions = self.executor.get_positions()
            
            for pos in positions:
                symbol = pos['symbol']
                current_price = pos['current_price']
                avg_price = pos['avg_entry_price']
                
                if avg_price > 0:
                    pnl_pct = (current_price - avg_price) / avg_price
                    
                    if pnl_pct <= -self.single_stock_limit:
                        logger.critical(
                            f"[ALERT] Single-stock crash: {symbol} "
                            f"Drop {pnl_pct:.2%} (limit: {-self.single_stock_limit:.1%})"
                        )
                        
                        # 仅平仓该股票
                        self._liquidate_symbol(symbol, f"Drop {pnl_pct:.2%}")
                        
                        if self.on_single_stock_drop:
                            self.on_single_stock_drop(symbol, pnl_pct)
                            
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Single-stock check network error: {e}")
        except Exception as e:
            logger.error(f"Single-stock check failed: {e}")
    
    def _get_latest_vix(self):
        """获取最新 VIX"""
        try:
            # 优先使用 polygon_data
            try:
                from polygon_data import HybridDataSource
                source = HybridDataSource()
                vix = source.get_vix()
                if vix:
                    return vix
            except ImportError:
                pass
            
            # 回退到 yfinance
            import yfinance as yf
            vix_data = yf.Ticker('^VIX').history(period="5d")
            if len(vix_data) > 0:
                return float(vix_data['Close'].iloc[-1])
                
        except Exception as e:
            logger.warning(f"Failed to get VIX: {e}")
        
        return None
    
    def _execute_pending_liquidation(self):
        """
        P1修复: 执行收盘期间记录下来的待处理强平，避免订单挂到次日开盘。
        """
        with self._lock:
            if not self._pending_liquidation_reasons:
                return
            entry = self._pending_liquidation_reasons.pop(0)
        reason = entry.get('reason', 'unknown')
        try:
            count = self.executor.liquidate_all()
            logger.critical(f"[OK] Executed pending liquidation: {count} positions, reason: {reason}")
            self._send_emergency_alert(f"Executed pending liquidation after market open: {reason}")
        except Exception as e:
            logger.critical(f"[ERROR] Pending liquidation execution failed: {e}")
            # 失败时重新标记待处理，下次循环再试
            with self._lock:
                self._pending_liquidation_reasons.insert(0, entry)
        finally:
            self.persist_state()

    def _emergency_liquidation(self, reason):
        """
        紧急平仓 - 平掉所有持仓（线程安全）
        P1修复: 市场关闭时记录待平仓，开盘再触发，避免挂单到次日开盘。
        
        参数:
            reason: str, 触发原因
        """
        logger.critical(f"\n{'='*60}")
        logger.critical(f"[ALERT] Emergency liquidation triggered")
        logger.critical(f"Reason: {reason}")
        logger.critical(f"{'='*60}")

        # 1. 暂停交易（线程安全）
        self.trading_halted = True
        
        # P0 修复：检查市场是否开盘
        try:
            market_open = self.executor.market_is_open()
        except AttributeError:
            market_open = True  # 无 market_is_open 时放行（兼容模式）

        if not market_open:
            # P1修复: 市场关闭时记录待平仓，不提交订单，避免挂单到次日开盘
            self._record_pending_liquidation(reason)
            logger.critical("[PENDING] Market closed, liquidation recorded and will trigger on next open")
            logger.critical("   Trading paused, please check account status")
            logger.critical("[WARN] Trading paused, please manually check and resume")
            # 发送告警
            self._send_emergency_alert(reason)
            return

        # 2. 市场开盘，立即平掉所有持仓
        count = self.executor.liquidate_all()
        logger.critical(f"[OK] Liquidated {count} positions")
        # P1: 确认持仓是否真正归零，未归零则重试
        self._confirm_liquidation()

        logger.critical("[WARN] Trading paused, please manually check and resume")
        self.persist_state()
    
    def _confirm_liquidation(self, max_retries=3, wait_sec=5):
        """P1: 确认平仓是否真正完成，未完成则重试"""
        for attempt in range(max_retries):
            try:
                positions = self.executor.get_positions() or []
                remaining = [p for p in positions if float(p.get('qty', 0)) != 0]
                if not remaining:
                    logger.critical("[OK] Liquidation confirmed: all positions closed")
                    return True
                logger.critical(f"[RETRY] Liquidation incomplete: {len(remaining)} positions remain (attempt {attempt+1}/{max_retries})")
                for pos in remaining:
                    self._liquidate_symbol(pos['symbol'], "liquidation confirmation retry")
                time.sleep(wait_sec)
            except Exception as e:
                logger.critical(f"[ERROR] Liquidation confirmation failed: {e}")
                time.sleep(wait_sec)
        logger.critical("[FAIL] Liquidation could not be fully confirmed after retries")
        self._send_emergency_alert("Liquidation incomplete after retries - manual intervention required")
        return False

    def _liquidate_symbol(self, symbol, reason):
        """
        平仓单只股票
        P1修复: 收盘时记录待平仓，开盘再触发，避免挂单到次日开盘。
        
        参数:
            symbol: str
            reason: str
        """
        logger.critical(f"[ALERT] Liquidate {symbol}: {reason}")
        
        try:
            # P0 修复：市场关闭时记录告警
            try:
                market_open = self.executor.market_is_open()
            except AttributeError:
                market_open = True

            if not market_open:
                # P1修复: 收盘时记录整体待平仓，不提交订单，避免挂单到次日开盘
                self._record_pending_liquidation(f"{symbol} {reason}")
                logger.critical(f"[PENDING] Market not open, {symbol} liquidation recorded and will trigger after open")
                return

            positions = self.executor.get_positions()
            for pos in positions:
                if pos['symbol'] == symbol:
                    self.executor.submit_order(symbol, pos['qty'], 'sell')
                    logger.critical(f"[OK] Submitted liquidation {symbol} x {pos['qty']}")
                    break
        except Exception as e:
            logger.error(f"Liquidate {symbol} failed: {e}")
    
    def _send_emergency_alert(self, reason):
        """发送紧急告警"""
        try:
            # 尝试通过 risk_monitor 发送
            if self.risk_monitor and hasattr(self.risk_monitor, '_trigger_alert'):
                self.risk_monitor._trigger_alert(
                    'EMERGENCY_LIQUIDATION',
                    f'Emergency liquidation: {reason}',
                    {'reason': reason, 'timestamp': datetime.now().isoformat()}
                )
        except Exception:
            pass
    
    def reset_daily_high(self):
        """重置日内高点（每天开盘调用）"""
        with self._lock:
            self.daily_high_nav = None
        logger.info("[RESET] Intraday high reset")
    
    def get_status(self):
        """获取监控状态"""
        with self._lock:
            return {
                'monitoring': self._monitoring,
                'last_check': self.last_check_time.isoformat() if self.last_check_time else None,
                'daily_high_nav': self.daily_high_nav,
                'peak_nav': self.peak_nav,
                'vix_threshold': self.vix_emergency_level,
                'drawdown_limit': self.max_intraday_dd,
                'total_drawdown_limit': self.max_total_drawdown,
                'pending_liquidation_reasons': list(self._pending_liquidation_reasons),
            }

    # ------------------------------------------------------------------
    # P0 修复：自动恢复交易已删除
    # 交易暂停后必须由人工/外部显式调用 resume_trading() 恢复；盘中监控
    # 不再根据 VIX 回落或回撤修复自动解除暂停。
    # ------------------------------------------------------------------
    def resume_trading(self):
        """手动恢复交易，重置暂停状态。"""
        logger.warning("[RESUME] Trading manually resumed")
        self.trading_halted = False
        with self._lock:
            self._pending_liquidation_reasons = []
        self.persist_state()
        return {'status': 'RESUMED', 'trading_halted': False}


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    from alpaca_executor import AlpacaPaperExecutor
    from risk_monitor import RiskMonitor
    
    # 初始化
    executor = AlpacaPaperExecutor()
    risk_monitor = RiskMonitor()
    
    monitor = IntradayMonitor(
        executor=executor,
        risk_monitor=risk_monitor,
        check_interval=10,  # 测试用10秒
        vix_emergency_level=30.0,
    )
    
    # 设置回调
    def on_vix_spike(vix):
        print(f"Callback: VIX spiked to {vix}")
    
    monitor.on_vix_spike = on_vix_spike
    
    # 启动监控
    print("Starting monitor (test mode, press Ctrl+C to stop)...")
    monitor.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        print("\nMonitor stopped")
