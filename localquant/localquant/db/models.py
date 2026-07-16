"""数据库模型 - LocalQuant 生产级系统"""
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
import json
import sqlite3
from pathlib import Path

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
class StrategyConfig:
    """策略配置"""
    name: str
    class_name: str  # 策略类名
    symbols: list[str]
    params: Dict[str, Any]  # 策略参数
    
    def to_json(self) -> str:
        return json.dumps({
            'name': self.name,
            'class_name': self.class_name,
            'symbols': self.symbols,
            'params': self.params
        })
    
    @classmethod
    def from_json(cls, json_str: str) -> 'StrategyConfig':
        data = json.loads(json_str)
        return cls(**data)

@dataclass
class BacktestTask:
    """回测任务"""
    id: Optional[int] = None
    type: TaskType = TaskType.BACKTEST
    status: TaskStatus = TaskStatus.PENDING
    strategy_config: Optional[StrategyConfig] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    interval: str = '1d'
    initial_cash: float = 100000.0
    commission_rate: float = 0.001
    
    # 执行结果
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    # 时间戳
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'type': self.type.value,
            'status': self.status.value,
            'strategy_config': self.strategy_config.to_json() if self.strategy_config else None,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'interval': self.interval,
            'initial_cash': self.initial_cash,
            'commission_rate': self.commission_rate,
            'result': json.dumps(self.result) if self.result else None,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

class DatabaseManager:
    """SQLite 数据库管理器"""
    
    def __init__(self, db_path: str = './data_cache/localquant.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库表"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    strategy_config TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    interval TEXT DEFAULT '1d',
                    initial_cash REAL DEFAULT 100000.0,
                    commission_rate REAL DEFAULT 0.001,
                    result TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    class_name TEXT NOT NULL,
                    description TEXT,
                    default_params TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    total_return REAL,
                    cagr REAL,
                    sharpe_ratio REAL,
                    max_drawdown REAL,
                    total_trades INTEGER,
                    win_rate REAL,
                    profit_factor REAL,
                    equity_curve TEXT,
                    trades TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
                )
            ''')
            
            conn.commit()
    
    def create_task(self, task: BacktestTask) -> int:
        """创建任务，返回任务ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                INSERT INTO tasks (type, status, strategy_config, start_date, end_date, 
                                 interval, initial_cash, commission_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task.type.value, task.status.value,
                task.strategy_config.to_json() if task.strategy_config else None,
                task.start_date, task.end_date, task.interval,
                task.initial_cash, task.commission_rate
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update_task_status(self, task_id: int, status: TaskStatus, 
                          result: Optional[Dict] = None, error: Optional[str] = None):
        """更新任务状态"""
        with sqlite3.connect(self.db_path) as conn:
            if status == TaskStatus.RUNNING:
                conn.execute('''
                    UPDATE tasks SET status = ?, started_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status.value, task_id))
            elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                conn.execute('''
                    UPDATE tasks SET status = ?, result = ?, error_message = ?,
                                   completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status.value, json.dumps(result) if result else None, error, task_id))
            else:
                conn.execute('UPDATE tasks SET status = ? WHERE id = ?',
                           (status.value, task_id))
            conn.commit()
    
    def get_task(self, task_id: int) -> Optional[BacktestTask]:
        """获取任务"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
            
            if row is None:
                return None
            
            task = BacktestTask(
                id=row['id'],
                type=TaskType(row['type']),
                status=TaskStatus(row['status']),
                strategy_config=StrategyConfig.from_json(row['strategy_config']) if row['strategy_config'] else None,
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
            )
            return task
    
    def list_tasks(self, status: Optional[TaskStatus] = None, limit: int = 50) -> list[BacktestTask]:
        """列出任务"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            if status:
                rows = conn.execute(
                    'SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?',
                    (status.value, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?',
                    (limit,)
                ).fetchall()
            
            tasks = []
            for row in rows:
                task = BacktestTask(
                    id=row['id'],
                    type=TaskType(row['type']),
                    status=TaskStatus(row['status']),
                    start_date=row['start_date'],
                    end_date=row['end_date'],
                    interval=row['interval'],
                    created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
                )
                tasks.append(task)
            return tasks
    
    def save_backtest_result(self, task_id: int, metrics: Dict[str, Any], 
                            equity_curve: str, trades: str):
        """保存回测结果"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO backtest_results 
                (task_id, total_return, cagr, sharpe_ratio, max_drawdown,
                 total_trades, win_rate, profit_factor, equity_curve, trades)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_id,
                metrics.get('total_return'),
                metrics.get('cagr'),
                metrics.get('sharpe_ratio'),
                metrics.get('max_drawdown'),
                metrics.get('total_trades'),
                metrics.get('win_rate'),
                metrics.get('profit_factor'),
                equity_curve, trades
            ))
            conn.commit()
