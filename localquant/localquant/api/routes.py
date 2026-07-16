"""FastAPI 路由 - 按 DESIGN_V2.md 规范"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from localquant.db.manager import DatabaseManager, BacktestTask, TaskType, TaskStatus
from localquant.scheduler.scheduler import TaskScheduler

router = APIRouter()
db = DatabaseManager()
scheduler = TaskScheduler()

# ========== Pydantic 模型 ==========

class BacktestRequest(BaseModel):
    strategy_name: str = Field(..., description="策略名称")
    symbols: List[str] = Field(..., description="交易标的列表")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")
    interval: str = Field(default='1d', description="时间间隔")
    initial_cash: float = Field(default=100000.0)
    commission_rate: float = Field(default=0.001)
    strategy_params: Optional[Dict[str, Any]] = Field(default={})

class TaskResponse(BaseModel):
    id: int
    type: str
    status: str
    strategy_name: str
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]

class StrategyInfo(BaseModel):
    name: str
    class_name: str
    description: str
    default_params: Dict[str, Any]

class MetricsResponse(BaseModel):
    total_return: float
    cagr: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    profit_factor: float

# ========== 可用策略注册 ==========

STRATEGIES = {
    'adaptive_momentum_v3': {
        'class_name': 'AdaptiveMomentumV3',
        'description': 'AdaptiveMomentumV3.1 - 多周期动量策略',
        'default_params': {
            'max_position_pct': 0.10,
            'rebalance_freq': 10,
            'max_stocks': 10,
            'stop_loss_pct': 0.08,
            'trailing_stop_pct': 0.10,
            'use_trend_filter': True,
            'sector_rotation_enabled': True
        }
    },
    'minute_momentum': {
        'class_name': 'MinuteMomentumStrategy',
        'description': '分钟级动量策略',
        'default_params': {
            'max_position_pct': 0.33,
            'rebalance_hours': 4,
            'top_n': 3
        }
    },
    'multi_momentum': {
        'class_name': 'MultiMomentumStrategy',
        'description': '多周期动量组合策略',
        'default_params': {
            'top_n': 5,
            'rebalance_freq': 20
        }
    },
    'bull_momentum': {
        'class_name': 'BullMomentumStrategy',
        'description': '牛市增强策略 - 高Beta动量+止盈止损',
        'default_params': {
            'top_n': 10,
            'momentum_lookback': 20,
            'spy_filter': True,
            'profit_target': 0.10,
            'stop_loss_pct': 0.08,
            'max_position_pct': 0.15,
            'rebalance_freq': 5
        }
    },
    'trend_following': {
        'class_name': 'TrendFollowingStrategy',
        'description': '趋势跟踪策略 - 均线突破+MACD确认',
        'default_params': {
            'fast_ma': 20,
            'slow_ma': 50,
            'risk_per_trade': 0.02,
            'use_macd': True
        }
    },
    'dual_thrust': {
        'class_name': 'DualThrustStrategy',
        'description': 'Dual Thrust日内突破 - 经典期货策略',
        'default_params': {
            'n': 5,
            'm': 0.5,
            'stop_loss_pct': 0.01
        }
    },
    'grid_trading': {
        'class_name': 'GridTradingStrategy',
        'description': '网格交易策略 - 震荡市低买高卖',
        'default_params': {
            'grid_count': 10,
            'quantity_per_grid': 100,
            'trailing_grid': True,
            'trail_pct': 0.05
        }
    },
    'pair_trading': {
        'class_name': 'PairTradingStrategy',
        'description': '配对交易策略 - 统计套利',
        'default_params': {
            'lookback': 60,
            'entry_z': 2.0,
            'exit_z': 0.5
        }
    },
    'alpha_factor': {
        'class_name': 'AlphaFactorStrategy',
        'description': 'Alpha多因子 - 价值+质量+动量',
        'default_params': {
            'value_weight': 0.3,
            'quality_weight': 0.3,
            'momentum_weight': 0.4,
            'top_n': 20,
            'rebalance_freq': 20
        }
    }
}

# ========== 路由 ==========

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@router.get("/strategies", response_model=List[StrategyInfo])
async def list_strategies():
    """列出可用策略"""
    return [
        StrategyInfo(
            name=name,
            class_name=info['class_name'],
            description=info['description'],
            default_params=info['default_params']
        )
        for name, info in STRATEGIES.items()
    ]

@router.get("/strategies/{name}")
async def get_strategy(name: str):
    """获取策略详情"""
    if name not in STRATEGIES:
        raise HTTPException(status_code=404, detail="Strategy not found")
    info = STRATEGIES[name]
    return StrategyInfo(
        name=name,
        class_name=info['class_name'],
        description=info['description'],
        default_params=info['default_params']
    )

@router.post("/backtest", response_model=TaskResponse)
async def create_backtest(request: BacktestRequest, background_tasks: BackgroundTasks):
    """创建回测任务"""
    if request.strategy_name not in STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {request.strategy_name}")
    
    # 创建任务记录
    task = BacktestTask(
        type=TaskType.BACKTEST,
        status=TaskStatus.PENDING,
        strategy_name=request.strategy_name,
        strategy_params=request.strategy_params,
        symbols=request.symbols,
        start_date=request.start_date,
        end_date=request.end_date,
        interval=request.interval,
        initial_cash=request.initial_cash,
        commission_rate=request.commission_rate
    )
    
    task_id = db.create_task(task)
    
    # 提交到调度器
    scheduler.submit(task_id, request)
    
    return _task_to_response(db.get_task(task_id))

@router.get("/tasks", response_model=List[TaskResponse])
async def list_tasks(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    """列出任务"""
    task_status = TaskStatus(status) if status else None
    tasks = db.list_tasks(status=task_status, limit=limit, offset=offset)
    return [_task_to_response(task) for task in tasks]

@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int):
    """获取任务详情"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_response(task)

@router.get("/tasks/{task_id}/result")
async def get_task_result(task_id: int):
    """获取任务执行结果"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status != TaskStatus.COMPLETED:
        return {"status": task.status.value, "message": "Task not completed yet"}
    
    # 获取详细结果
    result = db.get_backtest_result(task_id)
    if result:
        return {
            "task_id": task_id,
            "status": task.status.value,
            "result": task.result,
            "metrics": {k: result[k] for k in result if k not in ['id', 'task_id', 'created_at']}
        }
    
    return {"task_id": task_id, "status": task.status.value, "result": task.result}

@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: int):
    """取消任务"""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel task with status {task.status.value}")
    
    if task.status == TaskStatus.RUNNING:
        scheduler.cancel(task_id)
    
    db.update_task_status(task_id, TaskStatus.CANCELLED)
    return {"message": "Task cancelled", "task_id": task_id}

@router.get("/tasks/{task_id}/equity")
async def download_equity(task_id: int):
    """下载权益曲线"""
    from fastapi.responses import FileResponse
    
    result = db.get_backtest_result(task_id)
    if not result or not result.get('equity_curve_path'):
        raise HTTPException(status_code=404, detail="Equity curve not found")
    
    return FileResponse(result['equity_curve_path'], filename=f"equity_{task_id}.csv")

@router.get("/tasks/{task_id}/trades")
async def download_trades(task_id: int):
    """下载交易记录"""
    from fastapi.responses import FileResponse
    
    result = db.get_backtest_result(task_id)
    if not result or not result.get('trades_path'):
        raise HTTPException(status_code=404, detail="Trades not found")
    
    return FileResponse(result['trades_path'], filename=f"trades_{task_id}.csv")

# ========== 辅助函数 ==========

def _task_to_response(task: BacktestTask) -> TaskResponse:
    """Task 对象转响应模型"""
    return TaskResponse(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        strategy_name=task.strategy_name,
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        result=task.result,
        error_message=task.error_message
    )
