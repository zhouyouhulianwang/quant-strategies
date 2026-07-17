"""
订单管理模块 - 订单状态跟踪、成交确认、重试机制
新增: 回滚机制、Decimal 精度
"""

import time
import logging

# P2修复：统一全链路日志格式
logger = logging.getLogger(__name__)

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from enum import Enum, auto
import csv
import os

from requests.exceptions import RequestException, ConnectionError, Timeout

try:
    from alpaca_executor import APIError
except ImportError:
    class APIError(Exception):
        pass

try:
    from matching_engine import ExecutionParameters, default_execution_params
    MATCHING_ENGINE_AVAILABLE = True
except ImportError:
    MATCHING_ENGINE_AVAILABLE = False

# 订单日志目录
ORDERS_DIR = os.path.join(os.path.dirname(__file__), 'orders')
os.makedirs(ORDERS_DIR, exist_ok=True)

try:
    from weight_allocation import normalize_target_positions
    WEIGHT_ALLOC_NORM_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_NORM_AVAILABLE = False

try:
    from json_logger import log_trade_event, log_risk_event, log_portfolio_snapshot
    JSON_LOGGER_AVAILABLE = True
except ImportError:
    JSON_LOGGER_AVAILABLE = False

# P2修复：引入统一告警管理器
try:
    from alert_manager import AlertManager
    ALERT_MGR_AVAILABLE = True
except ImportError:
    ALERT_MGR_AVAILABLE = False


class OrderState(str, Enum):
    """P1/P2 修复：订单生命周期状态机"""
    PENDING = 'PENDING'
    SUBMITTED = 'SUBMITTED'
    PARTIAL_FILLED = 'PARTIAL_FILLED'
    FILLED = 'FILLED'
    CANCELLED = 'CANCELLED'
    FAILED = 'FAILED'
    TIMEOUT = 'TIMEOUT'


# 合法状态转换图：key=当前状态，value=允许的目标状态集合
_VALID_TRANSITIONS = {
    OrderState.PENDING: {OrderState.SUBMITTED, OrderState.FAILED, OrderState.CANCELLED},
    OrderState.SUBMITTED: {OrderState.PARTIAL_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.FAILED, OrderState.TIMEOUT},
    OrderState.PARTIAL_FILLED: {OrderState.FILLED, OrderState.CANCELLED, OrderState.FAILED, OrderState.TIMEOUT, OrderState.PARTIAL_FILLED},
    OrderState.FILLED: set(),
    OrderState.CANCELLED: set(),
    OrderState.FAILED: set(),
    OrderState.TIMEOUT: {OrderState.CANCELLED, OrderState.FAILED, OrderState.FILLED, OrderState.PARTIAL_FILLED},
}


class OrderManager:
    """订单管理器 - 跟踪订单状态，处理成交确认"""
    
    def __init__(self, executor, max_wait_sec=300, poll_interval=5, alert_manager=None, max_makeup_depth=1):
        """
        初始化订单管理器
        
        参数:
            executor: AlpacaPaperExecutor 实例
            max_wait_sec: int, 最大等待时间（秒）
            poll_interval: int, 轮询间隔（秒）
            alert_manager: AlertManager, 可选告警管理器（P2修复）
            max_makeup_depth: int, 部分成交/超时后最大补单深度（默认 1）
        """
        self.executor = executor
        self.max_wait_sec = max_wait_sec
        self.poll_interval = poll_interval
        self.max_makeup_depth = max_makeup_depth
        self.orders_log = []
        # P1/P2 修复：维护订单状态机
        self.order_states: Dict[str, OrderState] = {}
        self.order_metadata: Dict[str, Dict] = {}

        # P2修复：接入统一告警管理器
        self.alert_manager = alert_manager
        if self.alert_manager is None and ALERT_MGR_AVAILABLE:
            self.alert_manager = AlertManager(enabled=True)

    def _send_alert(self, method, *args, **kwargs):
        """P2修复：统一封装告警调用"""
        if self.alert_manager is not None and hasattr(self.alert_manager, method):
            try:
                getattr(self.alert_manager, method)(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Alert send failed: {e}")

    def _transition(self, order_id: str, new_state: OrderState, symbol: str = '', qty: int = 0,
                    filled: int = 0, reason: str = '', source: str = 'state_machine'):
        """
        P1/P2 修复：订单状态转换与结构化日志。
        检查状态转换合法性，记录 warning 并写入结构化日志。
        """
        if not order_id:
            return
        old_state = self.order_states.get(order_id, OrderState.PENDING)
        # 允许重复进入同一状态
        if old_state == new_state:
            self.order_states[order_id] = new_state
            return
        valid = _VALID_TRANSITIONS.get(old_state, set())
        if new_state not in valid:
            logger.warning(
                f"[STATE_MACHINE] Invalid order state transition: {order_id} "
                f"{old_state.value} -> {new_state.value} (source={source}, reason={reason})"
            )
            # 仍然记录目标状态，但保留原状态作为 metadata 用于审计
            self.order_metadata.setdefault(order_id, {})['invalid_transition'] = {
                'from': old_state.value,
                'to': new_state.value,
                'source': source,
                'reason': reason,
            }
            return
        self.order_states[order_id] = new_state
        log_payload = {
            'order_id': order_id,
            'symbol': symbol,
            'qty': qty,
            'filled': filled,
            'state': new_state.value,
            'previous_state': old_state.value,
            'reason': reason,
            'source': source,
        }
        # 统一全链路日志：关键状态转换点
        if new_state in (OrderState.FILLED, OrderState.PARTIAL_FILLED):
            logger.info(f"[ORDER_STATE] {order_id} {symbol} transitioned to {new_state.value}: filled={filled}/{qty} reason={reason}")
        elif new_state in (OrderState.CANCELLED, OrderState.FAILED, OrderState.TIMEOUT):
            logger.warning(f"[ORDER_STATE] {order_id} {symbol} transitioned to {new_state.value}: reason={reason}")
        else:
            logger.info(f"[ORDER_STATE] {order_id} {symbol} transitioned to {new_state.value}: reason={reason}")
        # 结构化日志（JSON）
        if JSON_LOGGER_AVAILABLE:
            try:
                log_trade_event(
                    symbol=symbol or order_id,
                    side=self.order_metadata.get(order_id, {}).get('side', ''),
                    qty=filled or qty,
                    price=0.0,
                    status=new_state.value,
                    order_id=order_id,
                )
            except Exception as e:
                logger.debug(f"Structured state log failed: {e}")
        self.order_metadata.setdefault(order_id, {}).update(log_payload)

    def _get_executor_attr(self, attr):
        """获取执行器属性，兼容 AlpacaPaperExecutor 和 AlpacaExecutor 包装器"""
        if hasattr(self.executor, attr):
            return getattr(self.executor, attr)
        if hasattr(self.executor, 'executor') and hasattr(self.executor.executor, attr):
            return getattr(self.executor.executor, attr)
        return None

    def _check_pdt_can_open(self, symbol: str, side: str) -> Dict:
        """H8 修复：开新仓前检查 PDT 限制"""
        pdt_tracker = self._get_executor_attr('pdt_tracker')
        enable_pdt = self._get_executor_attr('enable_pdt')
        if not pdt_tracker or not enable_pdt:
            return {'allowed': True, 'reason': 'pdt_disabled'}

        account = self.executor.get_account() if hasattr(self.executor, 'get_account') else None
        if not account:
            return {'allowed': False, 'reason': 'account_unavailable'}

        return pdt_tracker.can_open_position(
            symbol=symbol,
            side=side,
            account_type=account.get('account_type', 'MARGIN'),
            equity=account.get('equity', 0.0),
            broker_daytrade_count=account.get('daytrade_count', 0),
        )

    def _place_makeup_with_cancel(self, order_id, symbol, qty, side, order_type, time_in_force, limit_price,
                                   max_wait_sec, poll_interval, makeup_depth) -> Optional[Dict]:
        """P0-3 修复：补单前取消原订单，确认状态后再下补单"""
        if makeup_depth >= self.max_makeup_depth:
            logger.warning(f"[MAKEUP] Max makeup depth reached for {symbol}, skipping")
            return None
        if qty <= 0:
            return None

        # 1. 撤销原订单
        cancel_ok = False
        if hasattr(self.executor, 'cancel_order') and order_id:
            try:
                cancel_ok = self.executor.cancel_order(order_id)
                if cancel_ok:
                    current_state = self.order_states.get(order_id)
                    # P2 修复：TIMEOUT 是最终状态，不应被覆盖为 CANCELLED
                    if current_state != OrderState.TIMEOUT:
                        self._transition(order_id, OrderState.CANCELLED, symbol=symbol, qty=qty, reason='makeup_cancel_original', source='makeup')
            except (ConnectionError, TimeoutError, Timeout, RequestException, ValueError) as e:
                logger.warning(f"[MAKEUP] Cancel original order {order_id} failed: {e}")

        # 2. 确认原订单状态为 canceled / expired / filled
        status_after_cancel = None
        if cancel_ok:
            status_check = self._get_order_status(order_id)
            status_after_cancel = status_check.get('status') if status_check else None

        if status_after_cancel in ('canceled', 'expired', 'filled'):
            logger.info(f"[MAKEUP] Original order {order_id} status={status_after_cancel}, placing makeup for {symbol} {side} remaining {qty}")
            return self.submit_and_wait(
                symbol=symbol, qty=qty, side=side,
                order_type=order_type, time_in_force=time_in_force, limit_price=limit_price,
                max_wait_sec=max_wait_sec, poll_interval=poll_interval,
                _makeup_depth=makeup_depth + 1
            )

        # 取消失败或状态未确认：保守处理，不下补单
        logger.warning(
            f"[MAKEUP] Skipping makeup for {symbol}: original order {order_id} "
            f"cancel_ok={cancel_ok}, status_after_cancel={status_after_cancel}"
        )
        return None

    def _place_makeup_order(self, symbol, qty, side, order_type, time_in_force, limit_price,
                            max_wait_sec, poll_interval, makeup_depth) -> Optional[Dict]:
        """M1 修复：对部分成交/超时剩余数量发起补单（保留兼容旧调用）"""
        if makeup_depth >= self.max_makeup_depth:
            logger.warning(f"[MAKEUP] Max makeup depth reached for {symbol}, skipping")
            return None
        if qty <= 0:
            return None
        logger.info(f"[MAKEUP] Placing makeup order for {symbol} {side} remaining {qty}")
        return self.submit_and_wait(
            symbol=symbol, qty=qty, side=side,
            order_type=order_type, time_in_force=time_in_force, limit_price=limit_price,
            max_wait_sec=max_wait_sec, poll_interval=poll_interval,
            _makeup_depth=makeup_depth + 1
        )

    def _merge_makeup_status(self, original: Dict, makeup: Optional[Dict], ordered_qty: int) -> Dict:
        """M1 修复：合并原始部分成交与补单结果"""
        if not makeup:
            return original

        orig_filled = int(original.get('filled_qty', 0))
        makeup_filled = int(makeup.get('filled_qty', 0))
        total_filled = orig_filled + makeup_filled
        remaining = ordered_qty - total_filled

        original['filled_qty'] = total_filled
        original['remaining_qty'] = remaining
        original['makeup_order'] = makeup

        if remaining <= 0:
            original['status'] = 'filled'
        elif makeup.get('status') in ['filled', 'partially_filled']:
            original['status'] = makeup.get('status')
        # else keep original partial status

        return original
    
    def submit_and_wait(self, symbol, qty, side, order_type='market', 
                        time_in_force='day', limit_price=None, max_wait_sec=None,
                        poll_interval=None, _makeup_depth=0) -> Dict:
        """
        提交订单并等待成交确认
        
        参数:
            symbol: str
            qty: int
            side: str, 'buy' 或 'sell'
            order_type: str
            time_in_force: str
            limit_price: float
            max_wait_sec: int, 覆盖默认最大等待时间
            poll_interval: int, 覆盖默认轮询间隔
            _makeup_depth: int, 内部补单深度（私有参数）
        
        返回:
            dict: 最终订单状态
        """
        max_wait = max_wait_sec if max_wait_sec is not None else self.max_wait_sec
        poll_int = poll_interval if poll_interval is not None else self.poll_interval

        # H8 修复：开新仓前进行 PDT 检查（仅针对买入/开仓）
        if side.lower() == 'buy':
            pdt_check = self._check_pdt_can_open(symbol, side)
            if not pdt_check['allowed']:
                logger.error(f"[ERROR] PDT blocked opening: {symbol} ({pdt_check['reason']})")
                self._send_alert('pdt_blocked', symbol, side, qty, pdt_check.get('reason', 'unknown'))
                return {'status': 'REJECTED', 'symbol': symbol, 'reason': pdt_check['reason']}
        
        # 1. 提交订单（P2-4 修复：仅在网络/瞬态错误时重试，明确拒绝直接失败）
        order = None
        last_error = None
        for attempt in range(3):
            try:
                order = self.executor.submit_order(
                    symbol=symbol, qty=qty, side=side,
                    order_type=order_type,
                    time_in_force=time_in_force,
                    limit_price=limit_price,
                    _record_pdt=False,
                )
                if order is not None:
                    break
                logger.warning(f"submit_order returned None for {symbol} {side}, attempt {attempt + 1}/3")
                last_error = Exception("submit_order returned None")
                if attempt < 2:
                    time.sleep(2 ** attempt)
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                # 网络/瞬态错误，指数退避重试
                last_error = e
                logger.warning(f"submit_order network error for {symbol} {side}, attempt {attempt + 1}/3: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
            except APIError as e:
                # P2-4：明确业务拒绝（PDT、资金、风控等）不重试；仅瞬态 API 错误重试
                error_message = str(e).lower()
                transient_api = any(k in error_message for k in ('rate limit', 'gateway', 'timeout', '503', '504'))
                if transient_api and attempt < 2:
                    last_error = e
                    logger.warning(f"submit_order transient API error for {symbol} {side}, attempt {attempt + 1}/3: {e}")
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"submit_order API rejection for {symbol} {side}: {e}")
                    return {'status': 'FAILED', 'symbol': symbol, 'reason': f'api_error: {e}'}
            except ValueError as e:
                # 明确参数错误，不重试
                logger.error(f"submit_order parameter error for {symbol} {side}: {e}")
                return {'status': 'FAILED', 'symbol': symbol, 'reason': f'value_error: {e}'}

        if order and order.get('status') == 'REJECTED':
            reason = order.get('reason', 'rejected')
            logger.error(f"❌ {symbol} order rejected: {reason}")
            self._send_alert('order_failed', symbol, side, qty, reason)
            rej_order_id = order.get('id', f'{symbol}-rejected')
            self._transition(rej_order_id, OrderState.FAILED, symbol=symbol, qty=qty, reason=reason, source='submit_rejected')
            return {'status': 'REJECTED', 'symbol': symbol, 'reason': reason}

        if order is None:
            logger.error(f"❌ {symbol} order submission failed after retries: {last_error}")
            self._send_alert('order_failed', symbol, side, qty, 'submit_failed')
            return {'status': 'FAILED', 'symbol': symbol, 'reason': 'submit_failed'}
        
        order_id = order['id']
        # P1/P2 修复：初始化订单元数据（含子订单追踪）并迁移到 SUBMITTED
        self.order_metadata[order_id] = {
            'symbol': symbol, 'qty': qty, 'side': side,
            'child_orders': [],
            'composite_status': None,
        }
        self._transition(order_id, OrderState.SUBMITTED, symbol=symbol, qty=qty, reason='order_submitted', source='submit_and_wait')
        logger.info(f"[ORDER] Order submitted: {order_id} {side} {qty} {symbol}")
        
        # 2. 轮询等待成交
        start_time = time.time()
        final_status = None
        
        while time.time() - start_time < max_wait:
            # 获取订单状态
            status = self._get_order_status(order_id)
            
            if status:
                logger.debug(f"  Order status: {order_id} = {status['status']}")
                
                # 检查是否完成
                if status['status'] in ['filled', 'partially_filled', 'canceled', 'rejected', 'expired']:
                    final_status = status
                    break
            
            time.sleep(poll_int)
        
        # 3. 处理结果
        if final_status:
            filled_qty = int(final_status.get('filled_qty', 0))
            remaining_qty = qty - filled_qty
            final_status['filled_qty'] = filled_qty
            final_status['remaining_qty'] = remaining_qty

            if final_status['status'] == 'filled':
                self._transition(order_id, OrderState.FILLED, symbol=symbol, qty=qty, filled=filled_qty, reason='order_filled', source='poll_result')
                logger.info(f"[OK] Order filled: {symbol} {filled_qty} shares @ ${final_status.get('filled_avg_price', 'N/A')}")
                # 记录 PDT 成交
                if hasattr(self.executor, 'record_fill') and filled_qty > 0:
                    self.executor.record_fill(symbol, side, filled_qty)
            elif final_status['status'] == 'partially_filled':
                self._transition(order_id, OrderState.PARTIAL_FILLED, symbol=symbol, qty=qty, filled=filled_qty, reason='partial_fill', source='poll_result')
                logger.warning(f"[PARTIAL] Partial fill: {symbol} {filled_qty}/{qty}")
                # P2修复：部分成交发送告警
                self._send_alert('order_partial_fill', symbol, side, filled_qty, qty, order_id)
                # 部分成交也记录
                if hasattr(self.executor, 'record_fill') and filled_qty > 0:
                    self.executor.record_fill(symbol, side, filled_qty)
                # M1 / P0-3 / P1-2 修复：部分成交后先撤销原订单，再对剩余数量补单
                if remaining_qty > 0:
                    makeup = self._place_makeup_with_cancel(
                        order_id, symbol, remaining_qty, side, order_type, time_in_force, limit_price,
                        max_wait_sec, poll_interval, _makeup_depth
                    )
                    if makeup:
                        final_status = self._merge_makeup_status(final_status, makeup, qty)
                        # P1-2：原订单已被撤销，状态保持 CANCELLED；组合订单结果写入元数据
                        self.order_metadata[order_id].setdefault('child_orders', []).append(makeup)
                        self.order_metadata[order_id]['composite_status'] = final_status.get('status')
                        self.order_metadata[order_id]['composite_filled'] = final_status.get('filled_qty')
                        self.order_metadata[order_id]['composite_remaining'] = final_status.get('remaining_qty')
                        if final_status.get('status') == 'filled':
                            logger.info(f"[OK] Original order {order_id} cancelled; combined fill via makeup: filled={final_status.get('filled_qty')}/{qty}")
            elif final_status['status'] in ('canceled', 'expired'):
                self._transition(order_id, OrderState.CANCELLED, symbol=symbol, qty=qty, filled=filled_qty, reason=final_status['status'], source='poll_result')
                logger.warning(f"[WARN] Order {final_status['status']}: {symbol}")
            elif final_status['status'] == 'rejected':
                self._transition(order_id, OrderState.FAILED, symbol=symbol, qty=qty, reason=final_status.get('reason', 'Unknown'), source='poll_result')
                logger.error(f"[ERROR] Order rejected: {symbol} - {final_status.get('reason', 'Unknown')}")
                # P2修复：订单被拒发送告警
                self._send_alert('order_rejected', symbol, side, qty, final_status.get('reason', 'Unknown'), order_id)
            else:
                logger.warning(f"[WARN] Order {final_status['status']}: {symbol}")
            
            # 记录日志
            self._log_order(final_status)
            return final_status
        else:
            # 超时：尝试撤销订单
            logger.error(f"[TIMEOUT] Order timeout: {symbol} (waited {max_wait} s), attempting cancel...")
            self._transition(order_id, OrderState.TIMEOUT, symbol=symbol, qty=qty, reason='wait_timeout', source='poll_result')
            if hasattr(self.executor, 'cancel_order'):
                try:
                    self.executor.cancel_order(order_id)
                    logger.info(f"[OK] Canceled timed-out order: {order_id}")
                except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                    logger.error(f"Cancel timed-out order {order_id} network failed: {e}")
                except ValueError as e:
                    logger.error(f"Cancel timed-out order {order_id} parameter error: {e}")

            # M1 / P0-3 修复：超时后确认实际成交数量，若有部分成交则先撤单再补单
            final_status = self._get_order_status(order_id)
            if final_status:
                filled_qty = int(final_status.get('filled_qty', 0))
                remaining_qty = qty - filled_qty
                timeout_result = {
                    'order_id': order_id,
                    'symbol': symbol,
                    'status': 'TIMEOUT',
                    'side': side,
                    'qty': qty,
                    'filled_qty': filled_qty,
                    'remaining_qty': remaining_qty,
                }
                self._log_order(timeout_result)
                if filled_qty > 0:
                    self._transition(order_id, OrderState.PARTIAL_FILLED, symbol=symbol, qty=qty, filled=filled_qty, reason='timeout_with_fill', source='timeout_recheck')
                if remaining_qty > 0:
                    makeup = self._place_makeup_with_cancel(
                        order_id, symbol, remaining_qty, side, order_type, time_in_force, limit_price,
                        max_wait_sec, poll_interval, _makeup_depth
                    )
                    if makeup:
                        merged = self._merge_makeup_status(timeout_result, makeup, qty)
                        timeout_result['filled_qty'] = merged['filled_qty']
                        timeout_result['remaining_qty'] = merged['remaining_qty']
                        timeout_result['makeup_order'] = merged.get('makeup_order')
                        self.order_metadata[order_id].setdefault('child_orders', []).append(makeup)
                        self.order_metadata[order_id]['composite_status'] = merged.get('status')
                        self.order_metadata[order_id]['composite_filled'] = merged.get('filled_qty')
                        self.order_metadata[order_id]['composite_remaining'] = merged.get('remaining_qty')
                        # 若补单完全成交，整体视为 filled；否则仍标记为 TIMEOUT
                        if merged['status'] == 'filled':
                            timeout_result['status'] = 'filled'
                            logger.info(f"[OK] Timed-out order {order_id} combined fill via makeup: filled={timeout_result['filled_qty']}/{qty}")
                return timeout_result

            self._log_order({
                'order_id': order_id,
                'symbol': symbol,
                'status': 'TIMEOUT',
                'side': side,
                'qty': qty,
                'filled_qty': 0,
                'remaining_qty': qty,
            })
            # P2修复：订单超时发送告警
            self._send_alert('order_timeout', symbol, side, qty, order_id)
            return {'status': 'TIMEOUT', 'order_id': order_id, 'symbol': symbol, 'filled_qty': 0, 'remaining_qty': qty}
    
    def _get_order_status(self, order_id):
        """获取订单状态（使用新版 alpaca-py API）"""
        try:
            # 优先使用 executor 的 get_order_by_id 方法（兼容新 SDK）
            if hasattr(self.executor, 'get_order_by_id'):
                order = self.executor.get_order_by_id(order_id)
                if order:
                    return order

            # 兼容旧代码：直接调用底层 API
            if self.executor.api:
                order = self.executor.api.get_order_by_id(order_id)
                return {
                    'order_id': order.id,
                    'symbol': order.symbol,
                    'status': order.status,
                    'filled_qty': int(float(order.filled_qty)) if order.filled_qty is not None else 0,
                    'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price is not None else None,
                    'side': order.side,
                    'qty': int(float(order.qty)) if order.qty is not None else 0,
                }
        except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
            logger.warning(f"Get order {order_id} status network error: {e}")
        except ValueError as e:
            logger.warning(f"Get order {order_id} status parameter error: {e}")

        return None
    
    def _log_order(self, order_info):
        """记录订单到 CSV 和结构化日志"""
        self.orders_log.append({
            'timestamp': datetime.now().isoformat(),
            **order_info
        })
        
        # 保存到文件
        filename = f"orders_{datetime.now():%Y%m%d}.csv"
        filepath = os.path.join(ORDERS_DIR, filename)
        
        # 追加写入
        file_exists = os.path.exists(filepath)
        with open(filepath, 'a', newline='') as f:
            fieldnames = ['timestamp', 'order_id', 'symbol', 'side', 'qty', 
                         'status', 'filled_qty', 'filled_avg_price']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            # 只写入存在的字段
            row = {k: v for k, v in order_info.items() if k in fieldnames}
            row['timestamp'] = datetime.now().isoformat()
            writer.writerow(row)
        
        # P2 修复：结构化日志
        if JSON_LOGGER_AVAILABLE:
            try:
                filled_qty = int(order_info.get('filled_qty', 0))
                filled_price = float(order_info.get('filled_avg_price', 0)) if order_info.get('filled_avg_price') else 0.0
                log_trade_event(
                    symbol=order_info.get('symbol', ''),
                    side=order_info.get('side', ''),
                    qty=filled_qty or int(order_info.get('qty', 0)),
                    price=filled_price,
                    status=order_info.get('status', ''),
                    order_id=order_info.get('order_id', order_info.get('id'))
                )
            except (ValueError, TypeError) as e:
                logger.debug(f"Structured log record failed: {e}")
            except (OSError, IOError) as e:
                logger.debug(f"Structured log write failed: {e}")
    
    def get_order_history(self, date=None):
        """获取订单历史"""
        if date is None:
            date = datetime.now()
        
        filename = f"orders_{date:%Y%m%d}.csv"
        filepath = os.path.join(ORDERS_DIR, filename)
        
        if not os.path.exists(filepath):
            return []
        
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            return list(reader)


class RebalanceManager:
    """再平衡管理器 - 带订单跟踪、成交确认、回滚机制的组合再平衡"""
    
    def __init__(self, executor, alert_manager=None, execution_params=None):
        self.executor = executor
        # P2修复：将告警管理器透传给 OrderManager
        self.order_manager = OrderManager(executor, alert_manager=alert_manager)
        self.alert_manager = alert_manager
        if self.alert_manager is None and ALERT_MGR_AVAILABLE:
            self.alert_manager = AlertManager(enabled=True)
        # Critical #2 修复：统一使用 ExecutionParameters 对齐回测与 live 执行假设
        if execution_params is not None:
            self.execution_params = execution_params
        elif MATCHING_ENGINE_AVAILABLE:
            self.execution_params = default_execution_params
        else:
            self.execution_params = None

    def _send_alert(self, method, *args, **kwargs):
        """P2修复：统一封装告警调用"""
        if self.alert_manager is not None and hasattr(self.alert_manager, method):
            try:
                getattr(self.alert_manager, method)(*args, **kwargs)
            except Exception as e:
                logger.debug(f"Alert send failed: {e}")

    def _cancel_open_orders_for_symbol(self, symbol: str):
        """P1-4 修复：取消同一标的尚未完结的订单，避免补单与内部 makeup 并发"""
        try:
            open_orders = self.executor.get_orders(status='open')
            for o in open_orders:
                if o.get('symbol') == symbol:
                    order_id = o.get('id')
                    if order_id:
                        logger.warning(f"[TOPUP] Cancelling outstanding order {order_id} for {symbol} before top-up")
                        self.executor.cancel_order(order_id)
        except Exception as e:
            logger.warning(f"Failed to cancel open orders for {symbol}: {e}")
    
    def rebalance(self, target_positions: Dict[str, float], 
                  max_position_pct=0.20,
                  confirm_fills=True,
                  enable_rollback=True,
                  min_buy_fill_ratio=0.95,
                  topup_on_partial=True,
                  max_wait_sec=300,
                  poll_interval=5,
                  min_notional=1.0) -> List[Dict]:
        """
        执行再平衡，带成交确认和回滚机制

        P0 修复：回滚处理部分成交与已买入仓位；买入失败时真正撤单或反向交易。
        P1-3 修复：min_buy_fill_ratio 默认 0.95，部分成交优先补单而非全仓回滚。
        
        参数:
            target_positions: dict, {symbol: target_value}
            max_position_pct: float
            confirm_fills: bool, 是否等待成交确认
            enable_rollback: bool, 失败时是否回滚（撤销已成交订单）
            min_buy_fill_ratio: float, 买入最小成交比例，低于此值触发回滚（默认 0.95）
            topup_on_partial: bool, 部分成交时是否优先补单
            max_wait_sec: int, 订单等待成交超时时间
            poll_interval: int, 订单轮询间隔
            min_notional: float, 最小订单名义金额
        
        返回:
            list: 所有订单结果
        """
        account = self.executor.get_account()
        if not account:
            logger.error("Cannot get account info")
            return []
        
        portfolio_value = account['portfolio_value']
        
        # P1 修复：确保目标持仓总金额不超过组合价值
        if WEIGHT_ALLOC_NORM_AVAILABLE:
            original_total = sum(target_positions.values())
            target_positions = normalize_target_positions(target_positions, portfolio_value)
            if abs(original_total - sum(target_positions.values())) > 1:
                logger.info(f"[PORTFOLIO] Target positions normalized: ${original_total:,.0f} → ${sum(target_positions.values()):,.0f}")
        
        current_positions = {p['symbol']: p for p in self.executor.get_positions()}
        
        results = []
        executed_sell_orders = []  # 记录已执行的卖出订单（用于回滚）
        executed_buy_orders = []   # 记录已执行的买入订单（失败时可能需要卖出）
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Portfolio rebalance")
        logger.info(f"{'='*60}")
        logger.info(f"Portfolio value: ${portfolio_value:,.2f}")
        
        # 1. 先卖出不在目标列表中的持仓
        sell_orders = []
        for symbol, pos in current_positions.items():
            if symbol not in target_positions:
                sell_orders.append({'symbol': symbol, 'qty': pos['qty'], 'side': 'sell'})
        
        # 执行卖出
        for order in sell_orders:
            try:
                if confirm_fills:
                    result = self.order_manager.submit_and_wait(
                        order['symbol'], order['qty'], order['side'],
                        max_wait_sec=max_wait_sec, poll_interval=poll_interval
                    )
                else:
                    result = self.executor.submit_order(
                        order['symbol'], order['qty'], order['side']
                    )
                
                if result and result.get('status') in ['filled', 'partially_filled']:
                    executed_sell_orders.append(result)
                
                results.append(result)
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                logger.error(f"Sell network error {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
            except ValueError as e:
                logger.error(f"Sell parameter error {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
        
        # 2. 买入/调整目标持仓
        buy_orders = []
        for symbol, target_value in target_positions.items():
            # Decimal 精度计算
            target_value = min(target_value, portfolio_value * max_position_pct)
            try:
                current_price = self._get_current_price(symbol)
            except RuntimeError as e:
                logger.error(f"Cannot get price {symbol}: {e}")
                results.append({'status': 'ERROR', 'symbol': symbol, 'error': str(e)})
                continue
            target_qty = self._calculate_qty(target_value, current_price, symbol=symbol)
            
            current_qty = current_positions.get(symbol, {}).get('qty', 0)
            diff = target_qty - current_qty
            
            if abs(diff) > 0:
                side = 'buy' if diff > 0 else 'sell'
                qty = abs(diff)
                notional = qty * current_price
                if notional < min_notional:
                    logger.warning(f"{symbol} order notional ${notional:.2f} below minimum ${min_notional}, skipping")
                    continue
                buy_orders.append({
                    'symbol': symbol, 'qty': qty, 'side': side,
                    'target_value': target_value, 'current_price': current_price
                })
        
        # 执行买入/调整（逐个执行，失败时回滚）
        failed_buy = False

        # P1-7 修复：循环买入前汇总所有买入金额，与可用购买力（含卖出释放资金）比较
        buy_only_orders = [o for o in buy_orders if o['side'] == 'buy']
        if buy_only_orders:
            total_buy_notional = sum(o['qty'] * o['current_price'] for o in buy_only_orders)
            account = self.executor.get_account()
            available_bp = account.get('buying_power', 0.0) if account else 0.0
            if total_buy_notional > available_bp:
                logger.error(
                    f"[BUYING_POWER] Total buy notional ${total_buy_notional:.2f} exceeds "
                    f"available buying power ${available_bp:.2f}; aborting buy loop and triggering rollback"
                )
                self._send_alert(
                    'risk_triggered', 'INSUFFICIENT_BUYING_POWER',
                    f"Total buy notional ${total_buy_notional:.2f} > buying power ${available_bp:.2f}",
                    {'total_buy_notional': total_buy_notional, 'buying_power': available_bp}
                )
                failed_buy = True

        for order in buy_orders:
            if failed_buy:
                break
            try:
                # P1 修复：买入前检查购买力（单订单兜底，保留作为二次防护）
                if order['side'] == 'buy':
                    account = self.executor.get_account()
                    if account and order['qty'] * order['current_price'] > account.get('buying_power', 0):
                        logger.error(f"Insufficient buying power, skipping {order['symbol']}")
                        # P2修复：购买力不足发送告警
                        self._send_alert('order_failed', order['symbol'], order['side'], order['qty'], 'insufficient_buying_power')
                        failed_buy = True
                        results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': 'insufficient_buying_power'})
                        break

                if confirm_fills:
                    result = self.order_manager.submit_and_wait(
                        order['symbol'], order['qty'], order['side'],
                        max_wait_sec=max_wait_sec, poll_interval=poll_interval
                    )
                else:
                    result = self.executor.submit_order(
                        order['symbol'], order['qty'], order['side']
                    )
                
                results.append(result)
                
                if result and result.get('status') in ['filled', 'partially_filled']:
                    executed_buy_orders.append(result)
                
                # P1-3 修复：更完善的买入失败判断
                # 包括 rejected/TIMEOUT/ERROR，以及部分成交未达最小比例
                if result and order['side'] == 'buy':
                    filled_qty = int(result.get('filled_qty', 0))
                    ordered_qty = order['qty']
                    fill_ratio = filled_qty / ordered_qty if ordered_qty > 0 else 1.0
                    
                    status = result.get('status', '')
                    is_failed = status in ['rejected', 'TIMEOUT', 'ERROR']
                    is_insufficient_fill = status == 'partially_filled' and fill_ratio < min_buy_fill_ratio
                    
                    if is_insufficient_fill and topup_on_partial:
                        # P1-4 修复：topup 前取消尚未完结的同类补单，避免同标的多个活跃订单
                        self._cancel_open_orders_for_symbol(order['symbol'])
                        # P1-3 修复：部分成交时优先补单，避免直接全仓回滚
                        remaining_qty = ordered_qty - filled_qty
                        logger.warning(
                            f"[PARTIAL] Partial fill {order['symbol']} {fill_ratio:.1%} < {min_buy_fill_ratio:.0%}，"
                            f"attempting top-up {remaining_qty} shares"
                        )
                        topup = self.order_manager.submit_and_wait(
                            order['symbol'], remaining_qty, 'buy',
                            max_wait_sec=max_wait_sec, poll_interval=poll_interval
                        )
                        if topup:
                            results.append(topup)
                            topup_filled = int(topup.get('filled_qty', 0))
                            total_filled = filled_qty + topup_filled
                            # 更新原始结果，便于后续回滚判断
                            result['filled_qty'] = total_filled
                            result['status'] = 'filled' if total_filled >= ordered_qty else topup.get('status', 'partially_filled')
                            if topup.get('status') in ['filled', 'partially_filled']:
                                executed_buy_orders.append(topup)
                            fill_ratio = total_filled / ordered_qty if ordered_qty > 0 else 1.0
                            if fill_ratio >= min_buy_fill_ratio:
                                logger.info(f"[OK] After top-up {order['symbol']} total filled {fill_ratio:.1%}")
                            else:
                                failed_buy = True
                                reason = f"partially_filled_topup_failed ({fill_ratio:.1%} < {min_buy_fill_ratio:.0%})"
                                logger.error(f"[ERROR] Buy failed {order['symbol']} (reason: {reason}), triggering rollback...")
                                break
                        else:
                            failed_buy = True
                            reason = f"partially_filled_topup_submit_failed ({fill_ratio:.1%})"
                            logger.error(f"[ERROR] Buy failed {order['symbol']} (reason: {reason}), triggering rollback...")
                            break
                    elif is_failed or is_insufficient_fill:
                        failed_buy = True
                        reason = status if is_failed else f"partially_filled ({fill_ratio:.1%} < {min_buy_fill_ratio:.0%})"
                        logger.error(f"[ERROR] Buy failed {order['symbol']} (reason: {reason}), triggering rollback...")
                        break
                        
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                logger.error(f"Buy network error {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
                if order['side'] == 'buy':
                    failed_buy = True
                    break
            except ValueError as e:
                logger.error(f"Buy parameter error {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
                if order['side'] == 'buy':
                    failed_buy = True
                    break
        
        # 回滚：如果买入失败，撤销已执行的卖出（重新买回）
        if failed_buy and enable_rollback:
            # P2修复：买入失败触发回滚时发送告警
            self._send_alert('risk_triggered', 'REBALANCE_ROLLBACK', f"Buy failed, triggering rollback", {'results_count': len(results)})
            # P0 修复：回滚卖出仓位（重新买回）
            if executed_sell_orders:
                logger.warning(f"[ROLLBACK] Executing rollback: {len(executed_sell_orders)} sell(s)")
                for sell_result in executed_sell_orders:
                    symbol = sell_result.get('symbol')
                    qty = sell_result.get('filled_qty', sell_result.get('qty', 0))
                    if qty > 0 and symbol:
                        try:
                            logger.info(f"[ROLLBACK] Rollback: buy back {symbol} x {qty}")
                            self.executor.submit_order(symbol, qty, 'buy')
                        except (ConnectionError, TimeoutError, Timeout, RequestException, ValueError) as e:
                            logger.error(f"Rollback failed {symbol}: {e}")
            # P0 修复：撤销已买入但目标未达成的新仓位
            if executed_buy_orders:
                logger.warning(f"[ROLLBACK] Canceling bought positions: {len(executed_buy_orders)} buy(s)")
                for buy_result in executed_buy_orders:
                    try:
                        order_id = buy_result.get('id')
                        if order_id:
                            self.executor.cancel_order(order_id)
                        # 如果已经成交，则卖出已买入部分
                        filled_qty = buy_result.get('filled_qty', 0)
                        if filled_qty > 0:
                            self.executor.submit_order(buy_result['symbol'], filled_qty, 'sell')
                    except (ConnectionError, TimeoutError, Timeout, RequestException, ValueError) as e:
                        logger.error(f"Failed to cancel buy {buy_result.get('symbol')}: {e}")
        
        logger.info(f"[OK] Rebalance completed, total {len(results)} orders")
        
        # P2 修复：结构化日志记录组合快照
        if JSON_LOGGER_AVAILABLE:
            try:
                account = self.executor.get_account()
                if account:
                    positions = self.executor.get_positions()
                    log_portfolio_snapshot(
                        cash=account.get('cash', 0.0),
                        portfolio_value=account.get('portfolio_value', 0.0),
                        positions_count=len(positions)
                    )
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                logger.debug(f"Portfolio snapshot log failed: {e}")
            except (ValueError, TypeError) as e:
                logger.debug(f"Portfolio snapshot log parameter error: {e}")
            except (OSError, IOError) as e:
                logger.debug(f"Portfolio snapshot log write failed: {e}")
        
        return results
    
    def _calculate_qty(self, target_value, current_price, symbol=None):
        """使用 Decimal 精度计算股数（P1 修复：复用 executor 的误差补偿）"""
        if hasattr(self.executor, '_calculate_qty'):
            return self.executor._calculate_qty(target_value, current_price, symbol=symbol)
        if current_price <= 0:
            return 0
        value_d = Decimal(str(target_value))
        price_d = Decimal(str(current_price))
        qty_d = (value_d / price_d).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
        return int(qty_d)
    
    def _get_current_price(self, symbol):
        """获取当前价格（使用 executor 的方法）"""
        # 尝试从 AlpacaExecutor 获取
        if hasattr(self.executor, '_get_current_price'):
            return self.executor._get_current_price(symbol)
        
        # 回退：使用持仓中的当前价格
        positions = self.executor.get_positions()
        for p in positions:
            if p['symbol'] == symbol:
                return p['current_price']
        
        # P1 修复：不再兜底 100，价格不可用时显式报错
        raise RuntimeError(f"Cannot get {symbol} current price, trading paused")


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    from alpaca_executor import AlpacaPaperExecutor
    
    executor = AlpacaPaperExecutor()
    manager = RebalanceManager(executor)
    
    # 测试再平衡
    targets = {'AAPL': 20000, 'MSFT': 20000}
    results = manager.rebalance(targets, confirm_fills=False)
    
    print(f"\nOrder results: {len(results)} orders")
