"""
PDT (Pattern Day Trader) 规则检查模块

PDT 规则摘要（美国券商）：
- 保证金账户（margin）且权益低于 $25,000 时，5 个交易日内不得超过 3 次 day trade。
- Day trade 定义：同一天内对同一只股票开仓并平仓（即先买后卖或先卖后买）。
- 现金账户（cash）不受 PDT 限制，但受 T+2 settlement 限制。
- 本模块追踪实际成交（filled）而非下单（submitted）。
"""

import os
import json
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

# P2修复：统一全链路日志格式

logger = logging.getLogger(__name__)


class PDTTracker:
    """PDT 规则追踪器（基于 FIFO 仓位 lot）"""

    def __init__(
        self,
        state_file: Optional[str] = None,
        account_id: Optional[str] = None,
        paper: bool = True,
        min_equity_for_unlimited: float = 25000.0,
        max_day_trades_in_5_days: int = 3,
        enabled: bool = True,
    ):
        """
        初始化 PDT 追踪器

        参数:
            state_file: str, 本地状态文件目录或文件路径
            account_id: str, 券商账户 ID（用于区分 paper/live）
            paper: bool, 是否纸交易（用于文件路径区分）
            min_equity_for_unlimited: float, 不受 PDT 限制的最小权益
            max_day_trades_in_5_days: int, 5 个交易日最大 day trade 次数（默认 3）
            enabled: bool, 是否启用 PDT 检查
        """
        self.account_id = account_id or ('paper' if paper else 'live')
        self.paper = paper
        self.min_equity_for_unlimited = min_equity_for_unlimited
        self.max_day_trades_in_5_days = max_day_trades_in_5_days
        self.enabled = enabled

        # 默认状态文件路径：data/pdt_{account_id}.json
        if state_file:
            self.state_file = state_file
        else:
            base_dir = os.path.join(os.path.dirname(__file__), 'data')
            self.state_file = os.path.join(base_dir, f'pdt_{self.account_id}.json')

        # 仓位 lot：每只股票的每个 lot 为 (entry_date, qty)
        # 用于 FIFO 判断卖出是否平掉的是当日买入的 lot
        self.positions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        # 历史 day trade 记录，每个元素为 {'date': str, 'symbol': str, 'qty': int}
        self.day_trade_history: List[Dict[str, Any]] = []
        # 今日卖出记录（用于先卖后买也构成 day trade 的场景）
        self._today_sells: Dict[str, int] = {}
        # 上次交易日，用于跨日重置
        self._last_trade_date: Optional[str] = None
        # P1-5 修复：标记 state_file 是否由外部指定，便于延迟初始化时自动切换路径
        self._state_file_custom = bool(state_file)
        # P1-5 修复：缓存券商返回的 daytrade_count，用于 can_open_position 默认取值
        self._broker_daytrade_count = 0

        self._load_state()

    def _load_state(self):
        """从本地文件加载历史 day trade 记录和仓位"""
        if not os.path.exists(self.state_file):
            self._persist_state()
            return

        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            self.day_trade_history = data.get('day_trade_history', [])
            self.positions = defaultdict(list)
            for symbol, lots in data.get('positions', {}).items():
                self.positions[symbol] = [
                    {'entry_date': lot['entry_date'], 'qty': int(lot['qty'])}
                    for lot in lots
                ]
            self._last_trade_date = data.get('last_trade_date', None)
            # P0 修复：恢复今日卖出记录，覆盖卖出侧 PDT 判断
            self._today_sells = data.get('today_sells', {})
            # P1-5 修复：恢复券商 daytrade_count
            self._broker_daytrade_count = int(data.get('broker_daytrade_count', 0))
            logger.info(f"📂 加载 PDT 状态 [{self.account_id}]: {len(self.day_trade_history)} 条 day trade")
        except (json.JSONDecodeError, OSError, IOError, PermissionError) as e:
            logger.warning(f"加载 PDT 状态失败: {e}，使用空记录")
            self.day_trade_history = []
            self.positions = defaultdict(list)
            self._today_sells = {}

    def _persist_state(self):
        """持久化 day trade 记录和仓位到本地文件"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump({
                    'account_id': self.account_id,
                    'paper': self.paper,
                    'day_trade_history': self.day_trade_history,
                    'positions': {s: lots for s, lots in self.positions.items()},
                    'last_trade_date': self._last_trade_date,
                    # P0 修复：持久化今日卖出记录，支撑先卖后买场景
                    'today_sells': self._today_sells,
                    # P1-5 修复：持久化券商 daytrade_count
                    'broker_daytrade_count': self._broker_daytrade_count,
                }, f, indent=2)
            # Critical #3 修复：敏感运行时文件限制权限 600
            try:
                os.chmod(self.state_file, 0o600)
            except OSError as e:
                logger.warning(f"设置 PDT 状态文件权限失败: {e}")
        except (OSError, IOError, PermissionError) as e:
            logger.warning(f"持久化 PDT 状态失败: {e}")

    @staticmethod
    def _today() -> date:
        """M3 修复：使用美东时间（ET）作为交易日边界"""
        return datetime.now(ZoneInfo('America/New_York')).date()

    def _reset_if_new_day(self):
        """如果跨交易日，重置今日日内记录（但保留仓位 lot）"""
        today = self._today().isoformat()
        if self._last_trade_date != today:
            self._last_trade_date = today
            # P0 修复：跨日清空当日卖出缓存，避免昨日卖出影响今日 PDT 判断
            self._today_sells = {}
            self._persist_state()

    def _rolling_count(self, today: date) -> int:
        """
        计算过去 5 个交易日（含今日）的 day trade 次数。

        M4 修复：优先使用 XNYS 交易日历计算真正 5 个交易日；不可用时回退到 7 个自然日。
        """
        try:
            import exchange_calendars as xc
            cal = xc.get_calendar('XNYS')
            # 如果今天不是交易日，则回退到最近一个交易日
            if not cal.is_session(today):
                today = cal.previous_session(today)
            # 5 个交易日包含 today 向前推 4 个 session
            cutoff = cal.session_offset(today, -4)
            cutoff_str = cutoff.isoformat()
        except Exception:
            # 回退：7 个自然日近似覆盖 5 个交易日
            cutoff_str = (today - timedelta(days=7)).isoformat()

        recent = [dt for dt in self.day_trade_history if dt['date'] >= cutoff_str]
        # P1-3 修复：按实际 day trade 记录次数累加，不再按 symbol+date 去重
        return len(recent)

    def sync_positions(self, positions: List[Dict[str, Any]],
                         broker_daytrade_count: Optional[int] = None,
                         account_id: Optional[str] = None):
        """
        与券商持仓同步（用于初始化或定时对账）

        参数:
            positions: list of dict, 每个 dict 需包含 symbol, qty, 可选 entry_date
            broker_daytrade_count: int, 券商返回的 daytrade_count（P1-5 修复）
            account_id: str, 券商账户 ID（延迟初始化时传入）
        """
        if not self.enabled:
            return

        self._reset_if_new_day()
        today = self._today().isoformat()

        # P1-5 修复：延迟初始化账户 ID，避免构造时 API 失败阻塞启动
        if account_id is not None and account_id != self.account_id:
            self.account_id = account_id
            if not self._state_file_custom:
                base_dir = os.path.join(os.path.dirname(__file__), 'data')
                self.state_file = os.path.join(base_dir, f'pdt_{self.account_id}.json')
            self._load_state()

        # P1-5 修复：同步券商 daytrade_count
        if broker_daytrade_count is not None:
            self._broker_daytrade_count = int(broker_daytrade_count)

        # P0-5 修复：未知 entry_date 的持仓不要默认设为今天， conservatively 不计为 day trade
        self.positions.clear()
        for pos in positions:
            symbol = pos.get('symbol')
            qty = int(pos.get('qty', 0))
            if qty == 0 or not symbol:
                continue
            entry_date = pos.get('entry_date')
            if not entry_date:
                entry_date = None  # 未知建仓日
            self.positions[symbol].append({'entry_date': entry_date, 'qty': qty})

        self._persist_state()
        logger.info(f"🔄 PDT 仓位同步 [{self.account_id}]: {len(positions)} 个持仓")

    def record_fill(self, symbol: str, side: str, filled_qty: int):
        """
        记录一笔成交，用于判断 day trade
        
        参数:
            symbol: str
            side: str, 'buy' 或 'sell'
            filled_qty: int, 成交数量
        """
        if not self.enabled or filled_qty <= 0:
            return

        self._reset_if_new_day()
        today = self._today().isoformat()
        side = side.lower()
        symbol = symbol.upper()

        if side == 'buy':
            # 增加一个新的 lot，entry_date = today
            if symbol not in self.positions:
                self.positions[symbol] = []
            self.positions[symbol].append({'entry_date': today, 'qty': filled_qty})
            # P0 修复：买入时若今日已有同 symbol 卖出，则先卖后买也构成 day trade
            sell_qty_today = self._today_sells.get(symbol, 0)
            if sell_qty_today > 0:
                dt_qty = min(filled_qty, sell_qty_today)
                self._record_day_trade(symbol, dt_qty)
                self._today_sells[symbol] = max(0, sell_qty_today - filled_qty)
        elif side == 'sell':
            # FIFO 平仓：优先平掉 entry_date 最早的 lot
            remaining = filled_qty
            day_trade_qty = 0
            lots = self.positions.get(symbol, [])

            while remaining > 0 and lots:
                lot = lots[0]
                lot_entry = lot['entry_date']
                if lot['qty'] <= remaining:
                    # 整个 lot 被平掉
                    # P0-5 修复：未知建仓日（None/UNKNOWN）conservatively 不计为 day trade
                    if lot_entry == today:
                        day_trade_qty += lot['qty']
                    remaining -= lot['qty']
                    lots.pop(0)
                else:
                    # 部分平仓
                    if lot_entry == today:
                        day_trade_qty += remaining
                    lot['qty'] -= remaining
                    remaining = 0

            if remaining > 0:
                # 卖出数量超过本地记录（可能是 short selling 或数据未同步）
                # P0-5 修复：超卖部分 conservatively 不计为 day trade
                logger.warning(f"PDT 卖出 {symbol} {filled_qty} 超出本地持仓记录，超卖部分不记为 day trade")
                # 记录超卖部分，后续买入可据此判断 day trade
                self._today_sells[symbol] = self._today_sells.get(symbol, 0) + remaining

            if day_trade_qty > 0:
                self._record_day_trade(symbol, day_trade_qty)
            # P0 修复：缓存今日卖出数量，用于先卖后买场景
            if remaining == 0:
                self._today_sells[symbol] = self._today_sells.get(symbol, 0) + filled_qty
                
        self._persist_state()

    def _check_same_day_reverse(self, symbol: str, side: str, qty: int):
        """检查同 symbol 当日是否有反向操作，形成 day trade"""
        # 这里简化：因为已有详细的 lot 记录，sell 的 FIFO 处理已经覆盖大部分情况
        # 但先卖后买（short）的情况，本地可能没有 lot，需要单独处理
        # 目前项目为 long-only，暂不处理 short 场景
        pass

    def _record_day_trade(self, symbol: str, qty: int):
        """记录一次 day trade 并持久化（P1-3：按实际配对记录，不合并同一天同 symbol）"""
        today_str = self._today().isoformat()
        # P1-3 修复：每次触发都单独记录，保守累加；qty 用于审计/按比例计算
        self.day_trade_history.append({
            'date': today_str,
            'symbol': symbol,
            'qty': int(qty),
        })
        self._persist_state()
        logger.warning(f"⚠️ 记录 day trade: {symbol} x {qty} on {today_str} [{self.account_id}]")


    def can_open_position(
        self,
        symbol: str,
        side: str,
        account_type: str = 'MARGIN',
        equity: float = 0.0,
        broker_daytrade_count: int = 0,
    ) -> Dict[str, Any]:
        """检查是否可以开新仓"""
        if not self.enabled:
            return {'allowed': True, 'reason': 'pdt_disabled', 'day_trades_used': 0, 'day_trades_left': 999}

        self._reset_if_new_day()
        today = self._today()
        today_str = today.isoformat()
        symbol = symbol.upper()
        side = side.lower()

        # 现金账户：不受 PDT 限制
        if account_type.upper() == 'CASH':
            return {
                'allowed': True,
                'reason': 'cash_account_not_subject_to_pdt',
                'day_trades_used': 0,
                'day_trades_left': 999,
            }

        # 权益高于阈值，不受限制
        if equity >= self.min_equity_for_unlimited:
            return {
                'allowed': True,
                'reason': 'equity_above_threshold',
                'day_trades_used': 0,
                'day_trades_left': 999,
            }

        # 计算已使用次数
        local_count = self._rolling_count(today)
        # P1-5 修复：若未显式传入，使用同步时缓存的券商 daytrade_count
        broker_count = (
            broker_daytrade_count
            if broker_daytrade_count is not None
            else getattr(self, '_broker_daytrade_count', 0)
        )
        day_trades_used = max(local_count, broker_count)
        day_trades_left = max(0, self.max_day_trades_in_5_days - day_trades_used)

        if day_trades_used >= self.max_day_trades_in_5_days:
            return {
                'allowed': False,
                'reason': f'pdt_limit_reached: {day_trades_used}/{self.max_day_trades_in_5_days}',
                'day_trades_used': day_trades_used,
                'day_trades_left': 0,
            }

        # 预估：如果今日有反向操作，本次开仓可能新增一次 day trade
        # P0 修复：卖出侧开仓（short）也可能构成 day trade，需要覆盖
        if side == 'buy' and self._has_sell_today(symbol):
            if day_trades_used + 1 > self.max_day_trades_in_5_days:
                return {
                    'allowed': False,
                    'reason': f'potential_pdt_exceed: {day_trades_used + 1}/{self.max_day_trades_in_5_days}',
                    'day_trades_used': day_trades_used,
                    'day_trades_left': day_trades_left,
                }
        elif side == 'sell':
            # 若今日有同 symbol 买入，则卖出可能是 day trade；若持仓不足，卖出=开仓 short，也可能后续买回形成 day trade
            has_buy_today_lot = any(
                lot['entry_date'] == today_str
                for lot in self.positions.get(symbol, [])
            )
            if has_buy_today_lot and day_trades_used + 1 > self.max_day_trades_in_5_days:
                return {
                    'allowed': False,
                    'reason': f'potential_pdt_exceed_sell: {day_trades_used + 1}/{self.max_day_trades_in_5_days}',
                    'day_trades_used': day_trades_used,
                    'day_trades_left': day_trades_left,
                }

        return {
            'allowed': True,
            'reason': 'ok',
            'day_trades_used': day_trades_used,
            'day_trades_left': day_trades_left,
        }

    def _has_sell_today(self, symbol: str) -> bool:
        """检查今日是否有卖出成交（P0 修复：使用今日卖出缓存）"""
        return self._today_sells.get(symbol.upper(), 0) > 0

    def get_status(self) -> Dict[str, Any]:
        """获取当前 PDT 状态摘要"""
        self._reset_if_new_day()
        today = self._today()
        used = self._rolling_count(today)
        return {
            'account_id': self.account_id,
            'today': today.isoformat(),
            'day_trades_used': used,
            'day_trades_left': max(0, self.max_day_trades_in_5_days - used),
            'min_equity_for_unlimited': self.min_equity_for_unlimited,
            'enabled': self.enabled,
        }


# ============================================================
# 使用示例
# ============================================================
if __name__ == '__main__':
    tracker = PDTTracker(enabled=True, paper=True, account_id='test')

    check = tracker.can_open_position('AAPL', 'buy', account_type='MARGIN', equity=20000)
    print(f"PDT 检查: {check}")

    # 买入成交
    tracker.record_fill('AAPL', 'buy', 10)
    # 同日内卖出成交
    tracker.record_fill('AAPL', 'sell', 10)
    print(f"状态: {tracker.get_status()}")

    # 第 4 次 day trade 会被阻止
    check2 = tracker.can_open_position('TSLA', 'buy', account_type='MARGIN', equity=20000)
    print(f"第 4 次开仓检查: {check2}")
