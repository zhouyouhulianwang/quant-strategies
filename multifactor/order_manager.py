"""
订单管理模块 - 订单状态跟踪、成交确认、重试机制
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import csv
import os

logger = logging.getLogger('order_manager')

# 订单日志目录
ORDERS_DIR = os.path.join(os.path.dirname(__file__), 'orders')
os.makedirs(ORDERS_DIR, exist_ok=True)


class OrderManager:
    """订单管理器 - 跟踪订单状态，处理成交确认"""
    
    def __init__(self, executor, max_wait_sec=300, poll_interval=5):
        """
        初始化订单管理器
        
        参数:
            executor: AlpacaPaperExecutor 实例
            max_wait_sec: int, 最大等待时间（秒）
            poll_interval: int, 轮询间隔（秒）
        """
        self.executor = executor
        self.max_wait_sec = max_wait_sec
        self.poll_interval = poll_interval
        self.orders_log = []
    
    def submit_and_wait(self, symbol, qty, side, order_type='market', 
                        time_in_force='day', limit_price=None) -> Dict:
        """
        提交订单并等待成交确认
        
        参数:
            symbol: str
            qty: int
            side: str, 'buy' 或 'sell'
            order_type: str
            time_in_force: str
            limit_price: float
        
        返回:
            dict: 最终订单状态
        """
        # 1. 提交订单
        order = self.executor.submit_order(
            symbol=symbol, qty=qty, side=side,
            order_type=order_type,
            time_in_force=time_in_force,
            limit_price=limit_price
        )
        
        if not order:
            logger.error(f"❌ {symbol} 订单提交失败")
            return {'status': 'FAILED', 'symbol': symbol, 'reason': 'submit_failed'}
        
        order_id = order['id']
        logger.info(f"📋 订单已提交: {order_id} {side} {qty} {symbol}")
        
        # 2. 轮询等待成交
        start_time = time.time()
        final_status = None
        
        while time.time() - start_time < self.max_wait_sec:
            # 获取订单状态
            status = self._get_order_status(order_id)
            
            if status:
                logger.debug(f"  订单状态: {order_id} = {status['status']}")
                
                # 检查是否完成
                if status['status'] in ['filled', 'partially_filled', 'canceled', 'rejected', 'expired']:
                    final_status = status
                    break
            
            time.sleep(self.poll_interval)
        
        # 3. 处理结果
        if final_status:
            if final_status['status'] == 'filled':
                logger.info(f"✅ 订单成交: {symbol} {final_status.get('filled_qty', qty)} 股 @ ${final_status.get('filled_avg_price', 'N/A')}")
            elif final_status['status'] == 'partially_filled':
                logger.warning(f"⚠️ 部分成交: {symbol} {final_status.get('filled_qty', 0)}/{qty}")
            elif final_status['status'] == 'rejected':
                logger.error(f"❌ 订单被拒: {symbol} - {final_status.get('reason', 'Unknown')}")
            else:
                logger.warning(f"⚠️ 订单 {final_status['status']}: {symbol}")
            
            # 记录日志
            self._log_order(final_status)
            return final_status
        else:
            # 超时
            logger.error(f"⏱️ 订单超时: {symbol} (等待 {self.max_wait_sec} 秒)")
            self._log_order({
                'order_id': order_id,
                'symbol': symbol,
                'status': 'TIMEOUT',
                'side': side,
                'qty': qty
            })
            return {'status': 'TIMEOUT', 'order_id': order_id, 'symbol': symbol}
    
    def _get_order_status(self, order_id):
        """获取订单状态"""
        try:
            # 通过 API 获取
            if self.executor.api:
                order = self.executor.api.get_order(order_id)
                return {
                    'order_id': order.id,
                    'symbol': order.symbol,
                    'status': order.status,
                    'filled_qty': int(order.filled_qty) if hasattr(order, 'filled_qty') else 0,
                    'filled_avg_price': float(order.filled_avg_price) if hasattr(order, 'filled_avg_price') else None,
                    'side': order.side,
                    'qty': int(order.qty),
                }
        except Exception as e:
            logger.warning(f"获取订单 {order_id} 状态失败: {e}")
        
        return None
    
    def _log_order(self, order_info):
        """记录订单到 CSV"""
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
    """再平衡管理器 - 带订单跟踪的组合再平衡"""
    
    def __init__(self, executor):
        self.executor = executor
        self.order_manager = OrderManager(executor)
    
    def rebalance(self, target_positions: Dict[str, float], 
                  max_position_pct=0.20,
                  confirm_fills=True) -> List[Dict]:
        """
        执行再平衡，带成交确认
        
        参数:
            target_positions: dict, {symbol: target_value}
            max_position_pct: float
            confirm_fills: bool, 是否等待成交确认
        
        返回:
            list: 所有订单结果
        """
        account = self.executor.get_account()
        if not account:
            logger.error("无法获取账户信息")
            return []
        
        portfolio_value = account['portfolio_value']
        current_positions = {p['symbol']: p for p in self.executor.get_positions()}
        
        results = []
        
        logger.info(f"\n{'='*60}")
        logger.info(f"组合再平衡")
        logger.info(f"{'='*60}")
        logger.info(f"组合价值: ${portfolio_value:,.2f}")
        
        # 1. 先卖出不在目标列表中的持仓
        sell_orders = []
        for symbol, pos in current_positions.items():
            if symbol not in target_positions:
                if confirm_fills:
                    result = self.order_manager.submit_and_wait(
                        symbol, pos['qty'], 'sell'
                    )
                    results.append(result)
                else:
                    result = self.executor.submit_order(symbol, pos['qty'], 'sell')
                    results.append(result)
        
        # 2. 买入/调整目标持仓
        for symbol, target_value in target_positions.items():
            target_value = min(target_value, portfolio_value * max_position_pct)
            
            # 获取当前价格
            current_price = self._get_current_price(symbol)
            target_qty = int(target_value / current_price)
            
            current_qty = current_positions.get(symbol, {}).get('qty', 0)
            diff = target_qty - current_qty
            
            if abs(diff) > 0:
                side = 'buy' if diff > 0 else 'sell'
                qty = abs(diff)
                
                logger.info(f"🔄 {side.upper()}: {symbol} x {qty} (目标: ${target_value:,.0f})")
                
                if confirm_fills:
                    result = self.order_manager.submit_and_wait(symbol, qty, side)
                else:
                    result = self.executor.submit_order(symbol, qty, side)
                
                results.append(result)
        
        logger.info(f"✅ 再平衡完成，共 {len(results)} 笔订单")
        return results
    
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
        
        return 100.0  # 兜底


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
