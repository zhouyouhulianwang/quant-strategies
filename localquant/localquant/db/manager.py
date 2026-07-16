"""数据库管理器 - 按 DESIGN_V2.md 规范"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
import json

from .schema import init_db

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskType(Enum):
    BACKTEST = "backtest"
    OPTIMIZATION = "optimization"
    LIVE_TRADE = "live_trade"
    DATA_SYNC = "data_sync"

@dataclass
class BacktestTask:
    """回测任务数据模型"""
    id: Optional[int] = None
    type: TaskType = TaskType.BACKTEST
    status: TaskStatus = TaskStatus.PENDING
    strategy_name: str = ""
    strategy_params: Dict[str, Any] = None
    symbols: List[str] = None
    start_date: str = ""
    end_date: str = ""
    interval: str = "1d"
    initial_cash: float = 100000.0
    commission_rate: float = 0.001
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time: Optional[float] = None
    
    def __post_init__(self):
        if self.strategy_params is None:
            self.strategy_params = {}
        if self.symbols is None:
            self.symbols = []

class DatabaseManager:
    """数据库管理器 - 所有数据库操作封装"""
    
    def __init__(self, db_path: str = './data_cache/localquant.db'):
        self.db_path = db_path
        self._init()
    
    def _init(self):
        """初始化数据库"""
        if not Path(self.db_path).exists():
            init_db(self.db_path)
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def create_task(self, task: BacktestTask) -> int:
        """创建任务，返回任务ID"""
        with self._get_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO tasks (type, status, strategy_name, strategy_params, symbols,
                                 start_date, end_date, interval, initial_cash, commission_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task.type.value, task.status.value,
                task.strategy_name, json.dumps(task.strategy_params), json.dumps(task.symbols),
                task.start_date, task.end_date, task.interval,
                task.initial_cash, task.commission_rate
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update_task_status(self, task_id: int, status: TaskStatus, 
                          result: Optional[Dict] = None, 
                          error: Optional[str] = None,
                          execution_time: Optional[float] = None):
        """更新任务状态"""
        with self._get_connection() as conn:
            if status == TaskStatus.RUNNING:
                conn.execute('''
                    UPDATE tasks SET status = ?, started_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status.value, task_id))
            elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                conn.execute('''
                    UPDATE tasks SET status = ?, result = ?, error_message = ?,
                                   execution_time = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status.value, json.dumps(result) if result else None, error, execution_time, task_id))
            elif status == TaskStatus.CANCELLED:
                conn.execute('''
                    UPDATE tasks SET status = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status.value, task_id))
            else:
                conn.execute('UPDATE tasks SET status = ? WHERE id = ?',
                           (status.value, task_id))
            conn.commit()
    
    def get_task(self, task_id: int) -> Optional[BacktestTask]:
        """获取任务详情"""
        with self._get_connection() as conn:
            row = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_task(row)
    
    def list_tasks(self, status: Optional[TaskStatus] = None, 
                   limit: int = 50, offset: int = 0) -> List[BacktestTask]:
        """列出任务"""
        with self._get_connection() as conn:
            if status:
                rows = conn.execute(
                    'SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?',
                    (status.value, limit, offset)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?',
                    (limit, offset)
                ).fetchall()
            return [self._row_to_task(row) for row in rows]
    
    def save_backtest_result(self, task_id: int, metrics: Dict[str, Any],
                            equity_curve_path: str = None, trades_path: str = None):
        """保存回测结果"""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO backtest_results 
                (task_id, total_return, cagr, sharpe_ratio, sortino_ratio, max_drawdown,
                 volatility, calmar_ratio, total_trades, winning_trades, losing_trades,
                 win_rate, profit_factor, avg_trade_pnl, total_commission,
                 equity_curve_path, trades_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id,
                metrics.get('total_return'),
                metrics.get('cagr'),
                metrics.get('sharpe_ratio'),
                metrics.get('sortino_ratio'),
                metrics.get('max_drawdown'),
                metrics.get('volatility'),
                metrics.get('calmar_ratio'),
                metrics.get('total_trades'),
                metrics.get('winning_trades'),
                metrics.get('losing_trades'),
                metrics.get('win_rate'),
                metrics.get('profit_factor'),
                metrics.get('avg_trade_pnl'),
                metrics.get('total_commission'),
                equity_curve_path, trades_path
            ))
            conn.commit()
    
    def get_backtest_result(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取回测结果"""
        with self._get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM backtest_results WHERE task_id = ?',
                (task_id,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)
    
    def count_tasks(self, status: Optional[TaskStatus] = None) -> int:
        """统计任务数量"""
        with self._get_connection() as conn:
            if status:
                row = conn.execute(
                    'SELECT COUNT(*) FROM tasks WHERE status = ?',
                    (status.value,)
                ).fetchone()
            else:
                row = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()
            return row[0]
    
    def _row_to_task(self, row: sqlite3.Row) -> BacktestTask:
        """数据库行转 Task 对象"""
        return BacktestTask(
            id=row['id'],
            type=TaskType(row['type']),
            status=TaskStatus(row['status']),
            strategy_name=row['strategy_name'],
            strategy_params=json.loads(row['strategy_params']) if row['strategy_params'] else {},
            symbols=json.loads(row['symbols']) if row['symbols'] else [],
            start_date=row['start_date'],
            end_date=row['end_date'],
            interval=row['interval'],
            initial_cash=row['initial_cash'],
            commission_rate=row['commission_rate'],
            result=json.loads(row['result']) if row['result'] else None,
            error_message=row['error_message'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            started_at=datetime.fromisoformat(row['started_at']) if row['started_at'] else None,
            completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
            execution_time=row['execution_time']
        )
