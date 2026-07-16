"""
调度模块 - 定时执行月度调仓
支持月末最后一个交易日自动执行
使用 exchange_calendars 处理交易日历
"""

import logging
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os

logger = logging.getLogger('scheduler')

# 尝试导入 exchange_calendars（美国NYSE日历）
try:
    import exchange_calendars as xcals
    XCALS_AVAILABLE = True
    XNYS = xcals.get_calendar('XNYS')  # NYSE
except ImportError:
    XCALS_AVAILABLE = False
    XNYS = None
    logger.warning("exchange_calendars 未安装，使用简化周末逻辑（不识别节假日）")


class RebalanceScheduler:
    """调仓调度器"""
    
    def __init__(self, strategy):
        """
        初始化调度器
        
        参数:
            strategy: V14Strategy 实例
        """
        self.strategy = strategy
        self.last_run = None
        self.run_log = []
    
    def should_rebalance(self, now=None) -> bool:
        """
        检查是否该调仓
        
        规则：每月最后一个交易日
        
        参数:
            now: datetime, 当前时间 (默认 now())
        
        返回:
            bool: 是否需要调仓
        """
        if now is None:
            now = datetime.now()
        
        # 获取本月最后一个交易日
        last_trading_day = self._get_last_trading_day_of_month(now.year, now.month)
        
        # 如果今天是最后一个交易日，且今天还没执行过
        today = now.date()
        
        if today == last_trading_day:
            # 检查今天是否已经执行过
            if self.last_run and self.last_run.date() == today:
                return False
            return True
        
        return False
    
    def _get_last_trading_day_of_month(self, year, month):
        """
        获取某月最后一个交易日
        使用 exchange_calendars (XNYS - NYSE) 识别所有节假日
        """
        if XCALS_AVAILABLE and XNYS is not None:
            # 使用 NYSE 交易日历
            start = f"{year}-{month:02d}-01"
            # 下月1日
            if month == 12:
                next_month_start = f"{year+1}-01-01"
            else:
                next_month_start = f"{year}-{month+1:02d}-01"
            
            # 获取该月所有交易日
            schedule = XNYS.sessions_in_range(start, next_month_start)
            # 过滤出该月的交易日
            month_sessions = [s for s in schedule if s.year == year and s.month == month]
            
            if month_sessions:
                return month_sessions[-1].date()
        
        # 回退: 简化逻辑（只跳过周末）
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day).date()
        
        while last_date.weekday() >= 5:  # 5=周六, 6=周日
            last_date -= timedelta(days=1)
        
        return last_date
    
    def run_if_due(self):
        """
        检查并执行调仓（如果到期）
        
        返回:
            bool: 是否执行了调仓
        """
        if self.should_rebalance():
            logger.info(f"\n{'='*60}")
            logger.info(f"🕐 定时调仓触发: {datetime.now()}")
            logger.info(f"{'='*60}")
            
            try:
                # 执行再平衡
                self.strategy.run_live_rebalance()
                
                self.last_run = datetime.now()
                self.run_log.append({
                    'timestamp': self.last_run.isoformat(),
                    'status': 'SUCCESS'
                })
                
                logger.info("✅ 定时调仓完成")
                return True
                
            except Exception as e:
                logger.error(f"❌ 定时调仓失败: {e}")
                self.run_log.append({
                    'timestamp': datetime.now().isoformat(),
                    'status': 'FAILED',
                    'error': str(e)
                })
                return False
        
        return False
    
    def get_next_rebalance_date(self):
        """获取下次调仓日期"""
        now = datetime.now()
        
        # 本月最后一个交易日
        this_month = self._get_last_trading_day_of_month(now.year, now.month)
        
        if now.date() <= this_month:
            return this_month
        else:
            # 下月
            next_month = now + relativedelta(months=1)
            return self._get_last_trading_day_of_month(next_month.year, next_month.month)
    
    def get_run_history(self):
        """获取执行历史"""
        return self.run_log


def run_scheduler_loop(strategy, check_interval=3600):
    """
    运行调度循环（阻塞模式）
    
    参数:
        strategy: V14Strategy 实例
        check_interval: int, 检查间隔（秒），默认1小时
    """
    import time
    
    scheduler = RebalanceScheduler(strategy)
    
    logger.info(f"🕐 调度器已启动")
    logger.info(f"   下次调仓: {scheduler.get_next_rebalance_date()}")
    logger.info(f"   检查间隔: {check_interval/3600:.1f} 小时")
    
    try:
        while True:
            # 检查是否到期
            if scheduler.run_if_due():
                logger.info(f"   下次调仓: {scheduler.get_next_rebalance_date()}")
            
            # 等待
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        logger.info("🛑 调度器已停止")


# 用于 cron 的简化入口
def run_once():
    """
    单次执行入口（用于 cron/celery 调用）
    
    使用方式:
        python -c "from scheduler import run_once; run_once()"
    """
    from run_strategy import V14Strategy
    
    strategy = V14Strategy(
        use_real_data=True,
        use_paper_trading=True,
        enable_risk_monitor=True
    )
    
    scheduler = RebalanceScheduler(strategy)
    scheduler.run_if_due()


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    from run_strategy import V14Strategy
    
    strategy = V14Strategy(
        use_real_data=True,
        use_paper_trading=False,  # 测试模式
        enable_risk_monitor=True
    )
    
    scheduler = RebalanceScheduler(strategy)
    
    # 检查是否到期
    if scheduler.should_rebalance():
        print("今天需要调仓！")
    else:
        print(f"下次调仓: {scheduler.get_next_rebalance_date()}")
    
    # 运行调度循环（测试模式，每60秒检查一次）
    # run_scheduler_loop(strategy, check_interval=60)
