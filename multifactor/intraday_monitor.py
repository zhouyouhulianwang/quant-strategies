"""
盘中监控模块 - VIX 实时监控和紧急平仓
支持日内风险事件触发自动保护
"""

import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

logger = logging.getLogger('intraday_monitor')


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
                 single_stock_limit=0.05):
        """
        初始化盘中监控
        
        参数:
            executor: V14AlpacaExecutor
            risk_monitor: RiskMonitor
            check_interval: int, 检查间隔（秒）
            vix_emergency_level: float, VIX 紧急平仓阈值
            max_intraday_dd: float, 最大日内回撤
            single_stock_limit: float, 单只股票跌幅限制
        """
        self.executor = executor
        self.risk_monitor = risk_monitor
        self.check_interval = check_interval
        self.vix_emergency_level = vix_emergency_level
        self.max_intraday_dd = max_intraday_dd
        self.single_stock_limit = single_stock_limit
        
        # 线程锁（防止和主交易线程竞态）
        self._halt_lock = threading.Lock()
        self._halted = False
        
        # 状态
        self.monitoring = False
        self.monitor_thread = None
        self.daily_high_nav = None
        self.last_check_time = None
        self._current_date = None  # 用于每日重置日内高点
        
        # 回调
        self.on_vix_spike: Optional[Callable] = None
        self.on_drawdown: Optional[Callable] = None
        self.on_single_stock_drop: Optional[Callable] = None
        
        logger.info("✅ 盘中监控器已初始化")
        logger.info(f"   VIX 紧急阈值: {vix_emergency_level}")
        logger.info(f"   日内回撤限制: {max_intraday_dd:.1%}")
    
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
    
    def start(self):
        """启动监控线程"""
        if self.monitoring:
            logger.warning("监控已在运行")
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        logger.info("🟢 盘中监控已启动")
    
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
        
        # 3. 检查单只股票
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
    
    def _emergency_liquidation(self, reason):
        """
        紧急平仓 - 平掉所有持仓（线程安全）
        
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

            if not market_open:
                logger.critical("❌ 市场未开盘，紧急平仓订单将在开盘后执行")
                logger.critical("   已暂停交易，请在开盘后检查账户状态")

            # 1. 暂停交易（线程安全）
            self.trading_halted = True

            # 2. 平掉所有持仓（如果市场开盘则立即执行）
            if market_open:
                count = self.executor.liquidate_all()
                logger.critical(f"✅ 已平掉 {count} 个持仓")
            else:
                # 市场关闭时提交订单将在次日开盘执行，记录待处理
                count = self.executor.liquidate_all()
                logger.critical(f"⏳ 市场已收盘，已提交 {count} 个平仓订单，将在下次开盘执行")

            logger.critical("⚠️ 交易已暂停，请手动检查并恢复")
            
            # 3. 发送告警（如果配置了）
            self._send_emergency_alert(reason)
            
        except ConnectionError as e:
            logger.critical(f"❌ 紧急平仓网络错误: {e}")
        except Exception as e:
            logger.critical(f"❌ 紧急平仓失败: {e}")
            logger.critical(f"❌ 紧急平仓失败: {e}")
    
    def _liquidate_symbol(self, symbol, reason):
        """
        平仓单只股票
        
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
                logger.critical(f"⏳ 市场未开盘，{symbol} 平仓订单将在开盘后执行")

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
            'vix_threshold': self.vix_emergency_level,
            'drawdown_limit': self.max_intraday_dd,
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
