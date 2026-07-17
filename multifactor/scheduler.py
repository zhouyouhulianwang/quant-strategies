"""
调度模块 - 定时执行调仓
支持 monthly / bimonthly / quarterly / weekly / daily 频率
参考 QuantConnect SetRebalanceSchedule 设计：
  - monthly/bimonthly/quarterly：在允许月份的首个交易日，开盘后 30 分钟执行
  - weekly：每周一开盘后 30 分钟执行
  - daily：每个交易日收盘后 16:30 ET 执行（EOD 数据可用后）
使用 exchange_calendars 处理交易日历
"""

import logging
from datetime import datetime, timedelta, time
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
import os
import json

from logging_config import setup_logging
# P2修复：统一全链路日志格式
setup_logging()
logger = logging.getLogger('scheduler')

# 美东时区（交易时间以美东为准）
NY_TZ = ZoneInfo('America/New_York')

# 美股开盘 09:30 ET，参考 QC AfterMarketOpen(..., 30) 设定调仓触发时间
MARKET_OPEN_TIME = time(9, 30)
REBALANCE_AFTER_OPEN_MINUTES = 30
REBALANCE_OPEN_TIME = time(10, 0)

# P1/P2修复: 美股收盘时间为 16:00 ET，此处 16:30 是“收盘后数据已可用的截止判断时间”
MARKET_CLOSE_CUTOFF_TIME = time(16, 30)

# 为了兼容旧代码，保留旧名称别名（ deprecated ）
MARKET_CLOSE_TIME = MARKET_CLOSE_CUTOFF_TIME

# 持久化文件：记录上次调仓时间，避免重启后重复调仓
LAST_RUN_FILE = os.path.join(os.path.dirname(__file__), '.last_rebalance.json')

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

    def __init__(self, strategy, rebalance_frequency='monthly'):
        """
        初始化调度器

        参数:
            strategy: V14Strategy 实例
            rebalance_frequency: str, 'monthly' / 'bimonthly' / 'quarterly' / 'weekly' / 'daily'
        """
        self.strategy = strategy
        self.rebalance_frequency = rebalance_frequency
        self.last_run = None
        self.run_log = []
        self.last_run_file = LAST_RUN_FILE
        self._load_last_run()

    def _load_last_run(self):
        """从文件读取上次调仓时间"""
        if not os.path.exists(self.last_run_file):
            return

        try:
            with open(self.last_run_file, 'r', encoding='utf-8') as f:
                payload = json.load(f)

            ts = payload.get('last_run')
            if ts:
                self.last_run = datetime.fromisoformat(ts)
                logger.info(f"📂 已加载上次调仓时间: {self.last_run}")
        except Exception as e:
            logger.warning(f"读取上次调仓时间失败: {e}")

    def _save_last_run(self):
        """保存上次调仓时间到文件"""
        try:
            payload = {
                'last_run': self.last_run.isoformat() if self.last_run else None
            }
            with open(self.last_run_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存上次调仓时间失败: {e}")

    def should_rebalance(self, now=None) -> bool:
        """
        检查是否该调仓

        规则（统一在开盘后 30 分钟，即 10:00 ET 触发）：
            - daily：每个交易日 10:00 ET 后
            - weekly：每周一 10:00 ET 后
            - monthly / bimonthly / quarterly：允许月份的首个交易日 10:00 ET 后

        参数:
            now: datetime, 当前时间（默认美东时间）

        返回:
            bool: 是否需要调仓
        """
        if now is None:
            now = datetime.now(NY_TZ)
        elif now.tzinfo is None:
            # 将 naive datetime 视为美东时间
            now = now.replace(tzinfo=NY_TZ)

        today = now.date()

        # 必须已过开盘后 30 分钟（10:00 ET）
        if now.time() < REBALANCE_OPEN_TIME:
            return False

        # 如果今天已经执行过，跳过
        if self.last_run:
            last_run_date = self.last_run.date() if self.last_run.tzinfo is None else self.last_run.astimezone(NY_TZ).date()
            if last_run_date == today:
                return False

        if self.rebalance_frequency == 'daily':
            # 每个交易日都调仓
            return self._is_trading_day(today)

        if self.rebalance_frequency == 'weekly':
            # 每周一
            return today.weekday() == 0 and self._is_trading_day(today)

        # monthly / bimonthly / quarterly
        allowed_months = self._get_allowed_months()
        if today.month not in allowed_months:
            return False

        first_trading_day = self._get_first_trading_day_of_month(today.year, today.month)
        return today == first_trading_day

    def _get_allowed_months(self):
        """根据调仓频率返回允许调仓的月份列表（参考 QC SetRebalanceSchedule）"""
        freq = self.rebalance_frequency
        if freq == 'monthly':
            return list(range(1, 13))
        elif freq == 'bimonthly':
            return [1, 3, 5, 7, 9, 11]
        elif freq == 'quarterly':
            return [1, 4, 7, 10]
        elif freq == 'weekly' or freq == 'daily':
            return list(range(1, 13))
        else:
            raise ValueError(f"Invalid rebalance frequency: {freq}")

    def _get_first_trading_day_of_month(self, year, month):
        """获取某月首个交易日（基于 XNYS 日历，回退到跳过周末）"""
        first_day = datetime(year, month, 1).date()
        if self._is_trading_day(first_day):
            return first_day

        next_day = first_day + timedelta(days=1)
        while not self._is_trading_day(next_day):
            next_day += timedelta(days=1)
        return next_day

    def _is_trading_day(self, date):
        """判断某天是否为交易日（基于 XNYS 日历）"""
        if XCALS_AVAILABLE and XNYS is not None:
            try:
                # 只查询该日本身，避免跨边界和类型比较问题
                sessions = XNYS.sessions_in_range(
                    date.isoformat(),
                    date.isoformat()
                )
                return len(sessions) > 0
            except Exception as e:
                logger.warning(f"XNYS 交易日查询失败 {date}: {e}，回退到周末逻辑")
        # 回退: 仅跳过周末
        return date.weekday() < 5

    def _get_next_trading_day(self, date):
        """获取某日期之后的下一个交易日"""
        next_day = date + timedelta(days=1)
        while not self._is_trading_day(next_day):
            next_day += timedelta(days=1)
        return next_day

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
        now = datetime.now(NY_TZ)

        if self.should_rebalance(now):
            logger.info(f"\n{'='*60}")
            logger.info(f"🕐 定时调仓触发: {now}")
            logger.info(f"{'='*60}")

            try:
                # 执行再平衡
                self.strategy.run_live_rebalance()

                self.last_run = now
                self._save_last_run()
                self.run_log.append({
                    'timestamp': self.last_run.isoformat(),
                    'status': 'SUCCESS'
                })

                logger.info("✅ 定时调仓完成")
                return True

            except Exception as e:
                logger.error(f"❌ 定时调仓失败: {e}")
                self.run_log.append({
                    'timestamp': now.isoformat(),
                    'status': 'FAILED',
                    'error': str(e)
                })
                return False

        return False

    def get_next_rebalance_date(self):
        """获取下次调仓日期"""
        now = datetime.now(NY_TZ)
        today = now.date()

        if self.rebalance_frequency == 'daily':
            # 如果今天还是交易日且未过 10:00 ET，下次可能是今天；否则下一个交易日
            if self._is_trading_day(today) and now.time() < REBALANCE_OPEN_TIME:
                return today
            return self._get_next_trading_day(today)

        if self.rebalance_frequency == 'weekly':
            # 找到下周一
            days_until_monday = (7 - today.weekday()) % 7
            if days_until_monday == 0 and now.time() >= REBALANCE_OPEN_TIME:
                days_until_monday = 7
            next_monday = today + timedelta(days=days_until_monday)
            while not self._is_trading_day(next_monday):
                next_monday += timedelta(days=1)
            return next_monday

        # monthly / bimonthly / quarterly：找到下一个允许月份的首个交易日
        allowed_months = self._get_allowed_months()
        current_month_idx = today.month

        # 同月内是否还有机会？
        if current_month_idx in allowed_months:
            first_day = self._get_first_trading_day_of_month(today.year, today.month)
            if today < first_day or (today == first_day and now.time() < REBALANCE_OPEN_TIME):
                return first_day

        # 往后找下一个允许月份
        for offset in range(1, 25):
            next_month_date = today + relativedelta(months=offset)
            if next_month_date.month in allowed_months:
                return self._get_first_trading_day_of_month(next_month_date.year, next_month_date.month)

        # 不应该执行到这里
        raise RuntimeError("无法找到下次调仓日期")

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

    frequency = 'monthly'
    if strategy.config and hasattr(strategy.config.trading, 'rebalance_frequency'):
        frequency = strategy.config.trading.rebalance_frequency

    scheduler = RebalanceScheduler(strategy, rebalance_frequency=frequency)

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
def run_once(paper=True, require_live_confirmation=True):
    """
    单次执行入口（用于 cron/celery 调用）
    
    参数:
        paper: bool, True=Paper Trading, False=Live Trading
        require_live_confirmation: bool, live 模式下是否需要确认

    使用方式:
        python -c "from scheduler import run_once; run_once(paper=True)"
    """
    from run_strategy import V14Strategy

    strategy = V14Strategy(
        use_real_data=True,
        use_paper_trading=True,
        paper=paper,
        enable_risk_monitor=True,
    )

    frequency = 'monthly'
    if strategy.config and hasattr(strategy.config.trading, 'rebalance_frequency'):
        frequency = strategy.config.trading.rebalance_frequency

    scheduler = RebalanceScheduler(strategy, rebalance_frequency=frequency)
    scheduler.run_if_due()


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    from run_strategy import V14Strategy

    strategy = V14Strategy(
        use_real_data=True,
        use_paper_trading=False,  # 测试模式
        paper=True,
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
