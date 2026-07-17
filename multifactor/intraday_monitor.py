"""
盘中监控模块 - VIX 实时监控和紧急平仓
支持日内风险事件触发自动保护
"""

import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

# P2修复：统一全链路日志格式
from logging_config import setup_logging
setup_logging()

logger = logging.getLogger('intraday_monitor')

try:
    from json_logger import log_risk_event
    JSON_LOGGER_AVAILABLE = True
except ImportError:
    JSON_LOGGER_AVAILABLE = False


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
                 max_total_drawdown=0.15):
        """
        初始化盘中监控
        
        参数:
            executor: V14AlpacaExecutor
            risk_monitor: RiskMonitor
            check_interval: int, 检查间隔（秒）
            vix_emergency_level: float, VIX 紧急平仓阈值
            max_intraday_dd: float, 最大日内回撤
            single_stock_limit: float, 单只股票跌幅限制
            max_total_drawdown: float, 最大累计回撤（P1 修复）
        """
        self.executor = executor
        self.risk_monitor = risk_monitor
        self.check_interval = check_interval
        self.vix_emergency_level = vix_emergency_level
        self.max_intraday_dd = max_intraday_dd
        self.single_stock_limit = single_stock_limit
        self.max_total_drawdown = max_total_drawdown
        
        # 线程锁（防止和主交易线程竞态）
        self._halt_lock = threading.Lock()
        self._halted = False
        
        # 状态
        self.monitoring = False
        self.monitor_thread = None
        self.daily_high_nav = None
        self.last_check_time = None
        self._current_date = None  # 用于每日重置日内高点
        
        # P1 修复：累计回撤跟踪
        self.peak_nav = None
        
        # P1修复: 收盘时未执行的强平请求，待次日开盘再触发
        self._pending_liquidation_reason = None
        self.on_vix_spike: Optional[Callable] = None
        self.on_drawdown: Optional[Callable] = None
        self.on_single_stock_drop: Optional[Callable] = None
        
        logger.info("✅ 盘中监控器已初始化")
        logger.info(f"   VIX 紧急阈值: {vix_emergency_level}")
        logger.info(f"   日内回撤限制: {max_intraday_dd:.1%}")
        logger.info(f"   累计回撤限制: {max_total_drawdown:.1%}")
    
    @property
    def trading_halted(self):
        """线程安全的 trading_halted 读取"""
        with self._halt_lock:
            return self._halted
    
    @trading_halted.setter
    def trading_halted(self, value):
        """线程安全的 trading_halted 设置"""
        with self._halt_lock:
            self._halted = value
            if self.risk_monitor:
                self.risk_monitor.trading_halted = value
    
    def start(self, daemon=True):
        """启动监控线程
        
        参数:
            daemon: bool, 是否以 daemon 方式运行线程。
                   默认 True（兼容旧行为，作为主交易线程的子线程）。
                   独立进程中建议传入 False，以保证进程不随主线程退出。
        """
        if self.monitoring:
            logger.warning("监控已在运行")
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=daemon)
        self.monitor_thread.start()
        
        logger.info(f"🟢 盘中监控已启动 (daemon={daemon})")
    
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
        
        logger.info("🔴 盘中监控已停止")
    
    def _monitor_loop(self):
        """监控循环"""
        while self.monitoring:
            try:
                # P0 修复：每日开盘时重置日内高点
                today = datetime.now().date()
                if self._current_date != today:
                    self._current_date = today
                    self.reset_daily_high()
                    logger.info(f"📅 新的一天，日内高点已重置: {today}")

                # P1修复: 若收盘期间触发了强平但市场关闭，开盘后执行
                if self._pending_liquidation_reason:
                    try:
                        market_open = self.executor.market_is_open()
                    except AttributeError:
                        market_open = True
                    if market_open:
                        self._execute_pending_liquidation()
                    else:
                        logger.info(f"⏳ 待平仓原因: {self._pending_liquidation_reason}，等待市场开盘...")

                self._check_all()
            except Exception as e:
                logger.error(f"监控循环错误: {e}")

            time.sleep(self.check_interval)
    
    def _check_all(self):
        """执行所有检查"""
        now = datetime.now()
        self.last_check_time = now
        
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
            
            logger.debug(f"当前 VIX: {vix:.2f}")
            
            # 检查是否超过紧急阈值
            if vix >= self.vix_emergency_level:
                logger.critical(f"🚨 VIX 紧急预警: {vix:.2f} (阈值: {self.vix_emergency_level})")
                
                # 触发紧急平仓
                self._emergency_liquidation(f"VIX飙升至 {vix:.2f}")
                
                if self.on_vix_spike:
                    self.on_vix_spike(vix)
            
            # 更新风险监控
            if self.risk_monitor:
                self.risk_monitor.check_vix_level(vix)
                
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"VIX 检查网络错误: {e}")
        except Exception as e:
            logger.error(f"VIX 检查失败: {e}")
    
    def _check_intraday_drawdown(self):
        """检查日内回撤"""
        try:
            account = self.executor.get_account()
            if not account:
                return
            
            current_nav = account['portfolio_value']
            
            # 初始化日内高点
            if self.daily_high_nav is None:
                self.daily_high_nav = current_nav
            
            # 更新高点
            if current_nav > self.daily_high_nav:
                self.daily_high_nav = current_nav
            
            # 计算回撤
            if self.daily_high_nav > 0:
                drawdown = (current_nav - self.daily_high_nav) / self.daily_high_nav
                
                logger.debug(f"日内回撤: {drawdown:.2%}")
                
                if drawdown <= -self.max_intraday_dd:
                    logger.critical(
                        f"🚨 日内回撤超限: {drawdown:.2%} "
                        f"(限制: {-self.max_intraday_dd:.1%})"
                    )
                    
                    self._emergency_liquidation(f"日内回撤 {drawdown:.2%}")
                    
                    if self.on_drawdown:
                        self.on_drawdown(drawdown)
                        
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"回撤检查网络错误: {e}")
        except Exception as e:
            logger.error(f"回撤检查失败: {e}")
    
    def _check_total_drawdown(self):
        """检查累计回撤（P1 修复）"""
        try:
            account = self.executor.get_account()
            if not account:
                return
            
            current_nav = account['portfolio_value']
            
            # 初始化/更新累计高点
            if self.peak_nav is None or current_nav > self.peak_nav:
                self.peak_nav = current_nav
            
            if self.peak_nav > 0:
                drawdown = (current_nav - self.peak_nav) / self.peak_nav
                
                logger.debug(f"累计回撤: {drawdown:.2%}")
                
                if drawdown <= -self.max_total_drawdown:
                    logger.critical(
                        f"🚨 累计回撤超限: {drawdown:.2%} "
                        f"(限制: {-self.max_total_drawdown:.1%})"
                    )
                    
                    self._emergency_liquidation(f"累计回撤 {drawdown:.2%}")
                    
                    if self.on_drawdown:
                        self.on_drawdown(drawdown)
                        
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"累计回撤检查网络错误: {e}")
        except Exception as e:
            logger.error(f"累计回撤检查失败: {e}")

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
                            f"🚨 单只股票暴跌: {symbol} "
                            f"跌幅 {pnl_pct:.2%} (限制: {-self.single_stock_limit:.1%})"
                        )
                        
                        # 仅平仓该股票
                        self._liquidate_symbol(symbol, f"跌幅 {pnl_pct:.2%}")
                        
                        if self.on_single_stock_drop:
                            self.on_single_stock_drop(symbol, pnl_pct)
                            
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"个股检查网络错误: {e}")
        except Exception as e:
            logger.error(f"个股检查失败: {e}")
    
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
            logger.warning(f"获取 VIX 失败: {e}")
        
        return None
    
    def _execute_pending_liquidation(self):
        """
        P1修复: 执行收盘期间记录下来的待处理强平，避免订单挂到次日开盘。
        """
        if not self._pending_liquidation_reason:
            return
        reason = self._pending_liquidation_reason
        self._pending_liquidation_reason = None
        try:
            count = self.executor.liquidate_all()
            logger.critical(f"✅ 已执行待处理强平: {count} 个持仓，原因: {reason}")
            self._send_emergency_alert(f"开盘后执行待处理强平: {reason}")
        except Exception as e:
            logger.critical(f"❌ 待处理强平执行失败: {e}")
            # 失败时重新标记待处理，下次循环再试
            self._pending_liquidation_reason = reason

    def _emergency_liquidation(self, reason):
        """
        紧急平仓 - 平掉所有持仓（线程安全）
        P1修复: 市场关闭时记录待平仓，开盘再触发，避免挂单到次日开盘。
        
        参数:
            reason: str, 触发原因
        """
        logger.critical(f"\n{'='*60}")
        logger.critical(f"🚨 紧急平仓触发")
        logger.critical(f"原因: {reason}")
        logger.critical(f"{'='*60}")

        try:
            # P0 修复：检查市场是否开盘
            try:
                market_open = self.executor.market_is_open()
            except AttributeError:
                market_open = True  # 无 market_is_open 时放行（兼容模式）

            # 1. 暂停交易（线程安全）
            self.trading_halted = True

            if not market_open:
                # P1修复: 市场关闭时记录待平仓，不提交订单，避免挂单到次日开盘
                self._pending_liquidation_reason = reason
                logger.critical("⏳ 市场已收盘，强平已记录待执行，将在下次开盘触发")
                logger.critical("   已暂停交易，请检查账户状态")
                logger.critical("⚠️ 交易已暂停，请手动检查并恢复")
                # 发送告警
                self._send_emergency_alert(reason)
                return

            # 2. 市场开盘，立即平掉所有持仓
            count = self.executor.liquidate_all()
            logger.critical(f"✅ 已平掉 {count} 个持仓")

            logger.critical("⚠️ 交易已暂停，请手动检查并恢复")
            
            # 3. 发送告警（如果配置了）
            self._send_emergency_alert(reason)
            
        except ConnectionError as e:
            logger.critical(f"❌ 紧急平仓网络错误: {e}")
        except Exception as e:
            logger.critical(f"❌ 紧急平仓失败: {e}")
    
    def _liquidate_symbol(self, symbol, reason):
        """
        平仓单只股票
        P1修复: 收盘时记录待平仓，开盘再触发，避免挂单到次日开盘。
        
        参数:
            symbol: str
            reason: str
        """
        logger.critical(f"🚨 平仓 {symbol}: {reason}")
        
        try:
            # P0 修复：市场关闭时记录告警
            try:
                market_open = self.executor.market_is_open()
            except AttributeError:
                market_open = True

            if not market_open:
                # P1修复: 收盘时记录整体待平仓，不提交订单，避免挂单到次日开盘
                if not self._pending_liquidation_reason:
                    self._pending_liquidation_reason = f"{symbol} {reason}"
                logger.critical(f"⏳ 市场未开盘，{symbol} 平仓已记录待执行，将在开盘后触发")
                return

            positions = self.executor.get_positions()
            for pos in positions:
                if pos['symbol'] == symbol:
                    self.executor.submit_order(symbol, pos['qty'], 'sell')
                    logger.critical(f"✅ 已提交平仓 {symbol} x {pos['qty']}")
                    break
        except Exception as e:
            logger.error(f"平仓 {symbol} 失败: {e}")
    
    def _send_emergency_alert(self, reason):
        """发送紧急告警"""
        try:
            # 尝试通过 risk_monitor 发送
            if self.risk_monitor and hasattr(self.risk_monitor, '_trigger_alert'):
                self.risk_monitor._trigger_alert(
                    'EMERGENCY_LIQUIDATION',
                    f'紧急平仓: {reason}',
                    {'reason': reason, 'timestamp': datetime.now().isoformat()}
                )
        except Exception:
            pass
    
    def reset_daily_high(self):
        """重置日内高点（每天开盘调用）"""
        self.daily_high_nav = None
        logger.info("📊 日内高点已重置")
    
    def get_status(self):
        """获取监控状态"""
        return {
            'monitoring': self.monitoring,
            'last_check': self.last_check_time.isoformat() if self.last_check_time else None,
            'daily_high_nav': self.daily_high_nav,
            'peak_nav': self.peak_nav,
            'vix_threshold': self.vix_emergency_level,
            'drawdown_limit': self.max_intraday_dd,
            'total_drawdown_limit': self.max_total_drawdown,
        }


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
        print(f"回调: VIX 飙升至 {vix}")
    
    monitor.on_vix_spike = on_vix_spike
    
    # 启动监控
    print("启动监控（测试模式，按 Ctrl+C 停止）...")
    monitor.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        print("\n监控已停止")
