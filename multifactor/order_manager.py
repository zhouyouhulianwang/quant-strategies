"""
订单管理模块 - 订单状态跟踪、成交确认、重试机制
新增: 回滚机制、Decimal 精度
"""

import time
import logging
from logging_config import setup_logging

# P2修复：统一全链路日志格式
setup_logging()
logger = logging.getLogger('order_manager')

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import csv
import os

from requests.exceptions import RequestException, ConnectionError, Timeout

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


class OrderManager:
    """订单管理器 - 跟踪订单状态，处理成交确认"""
    
    def __init__(self, executor, max_wait_sec=300, poll_interval=5, alert_manager=None):
        """
        初始化订单管理器
        
        参数:
            executor: AlpacaPaperExecutor 实例
            max_wait_sec: int, 最大等待时间（秒）
            poll_interval: int, 轮询间隔（秒）
            alert_manager: AlertManager, 可选告警管理器（P2修复）
        """
        self.executor = executor
        self.max_wait_sec = max_wait_sec
        self.poll_interval = poll_interval
        self.orders_log = []

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
                logger.debug(f"告警发送失败: {e}")
    
    def submit_and_wait(self, symbol, qty, side, order_type='market', 
                        time_in_force='day', limit_price=None, max_wait_sec=None,
                        poll_interval=None) -> Dict:
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
        
        返回:
            dict: 最终订单状态
        """
        max_wait = max_wait_sec if max_wait_sec is not None else self.max_wait_sec
        poll_int = poll_interval if poll_interval is not None else self.poll_interval
        
        # 1. 提交订单
        order = self.executor.submit_order(
            symbol=symbol, qty=qty, side=side,
            order_type=order_type,
            time_in_force=time_in_force,
            limit_price=limit_price
        )
        
        if not order:
            logger.error(f"❌ {symbol} 订单提交失败")
            self._send_alert('order_failed', symbol, side, qty, 'submit_failed')
            return {'status': 'FAILED', 'symbol': symbol, 'reason': 'submit_failed'}
        
        order_id = order['id']
        logger.info(f"📋 订单已提交: {order_id} {side} {qty} {symbol}")
        
        # 2. 轮询等待成交
        start_time = time.time()
        final_status = None
        
        while time.time() - start_time < max_wait:
            # 获取订单状态
            status = self._get_order_status(order_id)
            
            if status:
                logger.debug(f"  订单状态: {order_id} = {status['status']}")
                
                # 检查是否完成
                if status['status'] in ['filled', 'partially_filled', 'canceled', 'rejected', 'expired']:
                    final_status = status
                    break
            
            time.sleep(poll_int)
        
        # 3. 处理结果
        if final_status:
            filled_qty = int(final_status.get('filled_qty', 0))
            if final_status['status'] == 'filled':
                logger.info(f"✅ 订单成交: {symbol} {filled_qty} 股 @ ${final_status.get('filled_avg_price', 'N/A')}")
                # 记录 PDT 成交
                if hasattr(self.executor, 'record_fill') and filled_qty > 0:
                    self.executor.record_fill(symbol, side, filled_qty)
            elif final_status['status'] == 'partially_filled':
                logger.warning(f"⚠️ 部分成交: {symbol} {filled_qty}/{qty}")
                # P2修复：部分成交发送告警
                self._send_alert('order_partial_fill', symbol, side, filled_qty, qty, order_id)
                # 部分成交也记录
                if hasattr(self.executor, 'record_fill') and filled_qty > 0:
                    self.executor.record_fill(symbol, side, filled_qty)
            elif final_status['status'] == 'rejected':
                logger.error(f"❌ 订单被拒: {symbol} - {final_status.get('reason', 'Unknown')}")
                # P2修复：订单被拒发送告警
                self._send_alert('order_rejected', symbol, side, qty, final_status.get('reason', 'Unknown'), order_id)
            else:
                logger.warning(f"⚠️ 订单 {final_status['status']}: {symbol}")
            
            # 记录日志
            self._log_order(final_status)
            return final_status
        else:
            # 超时：尝试撤销订单
            logger.error(f"⏱️ 订单超时: {symbol} (等待 {max_wait} 秒)，尝试撤销...")
            if hasattr(self.executor, 'cancel_order'):
                try:
                    self.executor.cancel_order(order_id)
                    logger.info(f"✅ 已撤销超时订单: {order_id}")
                except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                    logger.error(f"撤销超时订单 {order_id} 网络失败: {e}")
                except ValueError as e:
                    logger.error(f"撤销超时订单 {order_id} 参数错误: {e}")
            self._log_order({
                'order_id': order_id,
                'symbol': symbol,
                'status': 'TIMEOUT',
                'side': side,
                'qty': qty
            })
            # P2修复：订单超时发送告警
            self._send_alert('order_timeout', symbol, side, qty, order_id)
            return {'status': 'TIMEOUT', 'order_id': order_id, 'symbol': symbol}
    
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
            logger.warning(f"获取订单 {order_id} 状态网络错误: {e}")
        except ValueError as e:
            logger.warning(f"获取订单 {order_id} 状态参数错误: {e}")

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
                logger.debug(f"结构化日志记录失败: {e}")
            except (OSError, IOError) as e:
                logger.debug(f"结构化日志写入失败: {e}")
    
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
    
    def __init__(self, executor, alert_manager=None):
        self.executor = executor
        # P2修复：将告警管理器透传给 OrderManager
        self.order_manager = OrderManager(executor, alert_manager=alert_manager)
        self.alert_manager = alert_manager
        if self.alert_manager is None and ALERT_MGR_AVAILABLE:
            self.alert_manager = AlertManager(enabled=True)

    def _send_alert(self, method, *args, **kwargs):
        """P2修复：统一封装告警调用"""
        if self.alert_manager is not None and hasattr(self.alert_manager, method):
            try:
                getattr(self.alert_manager, method)(*args, **kwargs)
            except Exception as e:
                logger.debug(f"告警发送失败: {e}")
    
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
            logger.error("无法获取账户信息")
            return []
        
        portfolio_value = account['portfolio_value']
        
        # P1 修复：确保目标持仓总金额不超过组合价值
        if WEIGHT_ALLOC_NORM_AVAILABLE:
            original_total = sum(target_positions.values())
            target_positions = normalize_target_positions(target_positions, portfolio_value)
            if abs(original_total - sum(target_positions.values())) > 1:
                logger.info(f"📊 目标持仓已归一化: ${original_total:,.0f} → ${sum(target_positions.values()):,.0f}")
        
        current_positions = {p['symbol']: p for p in self.executor.get_positions()}
        
        results = []
        executed_sell_orders = []  # 记录已执行的卖出订单（用于回滚）
        executed_buy_orders = []   # 记录已执行的买入订单（失败时可能需要卖出）
        
        logger.info(f"\n{'='*60}")
        logger.info(f"组合再平衡")
        logger.info(f"{'='*60}")
        logger.info(f"组合价值: ${portfolio_value:,.2f}")
        
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
                logger.error(f"卖出网络异常 {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
            except ValueError as e:
                logger.error(f"卖出参数错误 {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
        
        # 2. 买入/调整目标持仓
        buy_orders = []
        for symbol, target_value in target_positions.items():
            # Decimal 精度计算
            target_value = min(target_value, portfolio_value * max_position_pct)
            try:
                current_price = self._get_current_price(symbol)
            except RuntimeError as e:
                logger.error(f"无法获取价格 {symbol}: {e}")
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
                    logger.warning(f"{symbol} 订单名义金额 ${notional:.2f} 小于最小 ${min_notional}，跳过")
                    continue
                buy_orders.append({
                    'symbol': symbol, 'qty': qty, 'side': side,
                    'target_value': target_value, 'current_price': current_price
                })
        
        # 执行买入/调整（逐个执行，失败时回滚）
        failed_buy = False
        for order in buy_orders:
            try:
                # P1 修复：买入前检查购买力
                if order['side'] == 'buy':
                    account = self.executor.get_account()
                    if account and order['qty'] * order['current_price'] > account.get('buying_power', 0):
                        logger.error(f"购买力不足，跳过 {order['symbol']}")
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
                        # P1-3 修复：部分成交时优先补单，避免直接全仓回滚
                        remaining_qty = ordered_qty - filled_qty
                        logger.warning(
                            f"⚠️ 部分成交 {order['symbol']} {fill_ratio:.1%} < {min_buy_fill_ratio:.0%}，"
                            f"尝试补单 {remaining_qty} 股"
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
                                logger.info(f"✅ 补单后 {order['symbol']} 合计成交 {fill_ratio:.1%}")
                            else:
                                failed_buy = True
                                reason = f"partially_filled_topup_failed ({fill_ratio:.1%} < {min_buy_fill_ratio:.0%})"
                                logger.error(f"❌ 买入失败 {order['symbol']} (原因: {reason})，触发回滚...")
                                break
                        else:
                            failed_buy = True
                            reason = f"partially_filled_topup_submit_failed ({fill_ratio:.1%})"
                            logger.error(f"❌ 买入失败 {order['symbol']} (原因: {reason})，触发回滚...")
                            break
                    elif is_failed or is_insufficient_fill:
                        failed_buy = True
                        reason = status if is_failed else f"partially_filled ({fill_ratio:.1%} < {min_buy_fill_ratio:.0%})"
                        logger.error(f"❌ 买入失败 {order['symbol']} (原因: {reason})，触发回滚...")
                        break
                        
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                logger.error(f"买入网络异常 {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
                if order['side'] == 'buy':
                    failed_buy = True
                    break
            except ValueError as e:
                logger.error(f"买入参数错误 {order['symbol']}: {e}")
                results.append({'status': 'ERROR', 'symbol': order['symbol'], 'error': str(e)})
                if order['side'] == 'buy':
                    failed_buy = True
                    break
        
        # 回滚：如果买入失败，撤销已执行的卖出（重新买回）
        if failed_buy and enable_rollback:
            # P2修复：买入失败触发回滚时发送告警
            self._send_alert('risk_triggered', 'REBALANCE_ROLLBACK', f"买入失败，触发回滚", {'results_count': len(results)})
            # P0 修复：回滚卖出仓位（重新买回）
            if executed_sell_orders:
                logger.warning(f"🔄 执行回滚: {len(executed_sell_orders)} 笔卖出")
                for sell_result in executed_sell_orders:
                    symbol = sell_result.get('symbol')
                    qty = sell_result.get('filled_qty', sell_result.get('qty', 0))
                    if qty > 0 and symbol:
                        try:
                            logger.info(f"🔄 回滚: 买回 {symbol} x {qty}")
                            self.executor.submit_order(symbol, qty, 'buy')
                        except (ConnectionError, TimeoutError, Timeout, RequestException, ValueError) as e:
                            logger.error(f"回滚失败 {symbol}: {e}")
            # P0 修复：撤销已买入但目标未达成的新仓位
            if executed_buy_orders:
                logger.warning(f"🔄 撤销已买入: {len(executed_buy_orders)} 笔买入")
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
                        logger.error(f"撤销买入失败 {buy_result.get('symbol')}: {e}")
        
        logger.info(f"✅ 再平衡完成，共 {len(results)} 笔订单")
        
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
                logger.debug(f"组合快照日志失败: {e}")
            except (ValueError, TypeError) as e:
                logger.debug(f"组合快照日志参数错误: {e}")
            except (OSError, IOError) as e:
                logger.debug(f"组合快照日志写入失败: {e}")
        
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
        # 尝试从 V14AlpacaExecutor 获取
        if hasattr(self.executor, '_get_current_price'):
            return self.executor._get_current_price(symbol)
        
        # 回退：使用持仓中的当前价格
        positions = self.executor.get_positions()
        for p in positions:
            if p['symbol'] == symbol:
                return p['current_price']
        
        # P1 修复：不再兜底 100，价格不可用时显式报错
        raise RuntimeError(f"无法获取 {symbol} 当前价格，暂停交易")


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
    
    print(f"\n订单结果: {len(results)} 笔")
