"""任务调度器 - 按 DESIGN_V2.md 规范"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor, Future
import threading
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from localquant.db.manager import DatabaseManager, TaskStatus, BacktestTask
from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from strategies.adaptive_momentum_v3 import AdaptiveMomentumV3
from strategies.minute_momentum import MinuteMomentumStrategy
from strategies.multi_momentum import MultiMomentumStrategy
from strategies.sma_cross import SmaCrossStrategy
from strategies.bull_momentum import BullMomentumStrategy
from strategies.trend_following import TrendFollowingStrategy

from strategies.templates.dual_thrust import DualThrustStrategy
from strategies.templates.grid_trading import GridTradingStrategy
from strategies.templates.pair_trading import PairTradingStrategy
from strategies.templates.alpha_factor import AlphaFactorStrategy

# 策略映射表
STRATEGY_MAP = {
    'AdaptiveMomentumV3': AdaptiveMomentumV3,
    'MinuteMomentumStrategy': MinuteMomentumStrategy,
    'MultiMomentumStrategy': MultiMomentumStrategy,
    'SmaCrossStrategy': SmaCrossStrategy,
    'BullMomentumStrategy': BullMomentumStrategy,
    'TrendFollowingStrategy': TrendFollowingStrategy,
    'DualThrustStrategy': DualThrustStrategy,
    'GridTradingStrategy': GridTradingStrategy,
    'PairTradingStrategy': PairTradingStrategy,
    'AlphaFactorStrategy': AlphaFactorStrategy
}

class TaskScheduler:
    """任务调度器 - 管理任务队列和后台执行"""
    
    def __init__(self, max_workers: int = 4, db_path: str = './data_cache/localquant.db'):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='task_worker')
        self.running_tasks: Dict[int, Future] = {}
        self.db = DatabaseManager(db_path)
        self._lock = threading.Lock()
    
    def submit(self, task_id: int, request) -> None:
        """提交任务到队列"""
        with self._lock:
            if len(self.running_tasks) >= self.max_workers:
                logger.warning(f"Max workers reached ({self.max_workers}), task {task_id} queued")
            
            # 提交到线程池
            future = self.executor.submit(self._run_task, task_id, request)
            self.running_tasks[task_id] = future
            
            # 添加完成回调
            future.add_done_callback(lambda f: self._on_task_done(task_id, f))
            
            logger.info(f"Task {task_id} submitted to scheduler")
    
    def cancel(self, task_id: int) -> bool:
        """取消任务"""
        with self._lock:
            if task_id in self.running_tasks:
                future = self.running_tasks[task_id]
                cancelled = future.cancel()
                if cancelled:
                    logger.info(f"Task {task_id} cancelled")
                return cancelled
            return False
    
    def _run_task(self, task_id: int, request) -> None:
        """执行回测任务"""
        start_time = time.time()
        
        try:
            # 1. 更新状态为 RUNNING
            self.db.update_task_status(task_id, TaskStatus.RUNNING)
            logger.info(f"Task {task_id} started")
            
            # 2. 获取策略类
            strategy_info = self._get_strategy_info(request.strategy_name)
            strategy_class = strategy_info['class']
            
            # 3. 获取数据
            dm = DataManager(cache_dir='./data_cache')
            start = datetime.strptime(request.start_date, '%Y-%m-%d')
            end = datetime.strptime(request.end_date, '%Y-%m-%d')
            
            multi_data = dm.get_multi_data(request.symbols, start, end, request.interval)
            
            if len(multi_data) == 0:
                raise ValueError("No data available")
            
            # 4. 创建策略
            strategy = strategy_class(symbols=request.symbols)
            for key, value in request.strategy_params.items():
                if hasattr(strategy, key):
                    setattr(strategy, key, value)
            
            # 5. 运行回测
            engine = BacktestEngine(
                initial_cash=request.initial_cash,
                commission_rate=request.commission_rate,
                start_date=start,
                end_date=end
            )
            engine.set_data(multi_data)
            engine.set_strategy(strategy)
            
            results = engine.run()
            
            # 6. 计算绩效
            metrics = AnalyticsEngine.calculate_metrics(
                results['returns'],
                results['equity_curve'],
                results['trades'],
                request.initial_cash
            )
            
            # 7. 保存结果文件
            result_dir = Path('./data_cache/results')
            result_dir.mkdir(parents=True, exist_ok=True)
            
            equity_path = result_dir / f'equity_{task_id}.csv'
            trades_path = result_dir / f'trades_{task_id}.csv'
            
            if len(results['equity_curve']) > 0:
                results['equity_curve'].to_csv(equity_path)
            if len(results['trades']) > 0:
                results['trades'].to_csv(trades_path, index=False)
            
            # 8. 保存到数据库
            result_summary = {
                'total_return': metrics['total_return'],
                'cagr': metrics['cagr'],
                'sharpe_ratio': metrics['sharpe_ratio'],
                'max_drawdown': metrics['max_drawdown'],
                'total_trades': metrics['total_trades'],
                'win_rate': metrics['win_rate'],
                'profit_factor': metrics['profit_factor']
            }
            
            self.db.save_backtest_result(
                task_id, metrics,
                str(equity_path), str(trades_path)
            )
            
            # 9. 更新状态为 COMPLETED
            execution_time = time.time() - start_time
            self.db.update_task_status(
                task_id, TaskStatus.COMPLETED,
                result=result_summary, execution_time=execution_time
            )
            
            logger.info(f"Task {task_id} completed in {execution_time:.2f}s")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Task {task_id} failed: {error_msg}")
            self.db.update_task_status(task_id, TaskStatus.FAILED, error=error_msg)
    
    def _on_task_done(self, task_id: int, future) -> None:
        """任务完成回调"""
        with self._lock:
            self.running_tasks.pop(task_id, None)
        
        if future.exception():
            logger.error(f"Task {task_id} raised exception: {future.exception()}")
    
    def _get_strategy_info(self, strategy_name: str) -> dict:
        """获取策略信息"""
        from localquant.api.routes import STRATEGIES
        
        if strategy_name not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        
        info = STRATEGIES[strategy_name]
        class_name = info['class_name']
        
        if class_name not in STRATEGY_MAP:
            raise ValueError(f"Strategy class not found: {class_name}")
        
        return {
            'class': STRATEGY_MAP[class_name],
            'info': info
        }
    
    def get_running_count(self) -> int:
        """获取正在运行的任务数"""
        return len(self.running_tasks)
    
    def shutdown(self) -> None:
        """关闭调度器"""
        self.executor.shutdown(wait=True)
        logger.info("Task scheduler shutdown")
