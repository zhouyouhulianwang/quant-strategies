# LocalQuant v2.0 - 详细系统设计文档

**版本**: 2.0.0  
**日期**: 2026-07-13  
**作者**: Qs  
**状态**: 设计阶段

---

## 1. 项目概述

### 1.1 目标
构建一个生产级量化交易平台，支持：
- 前端提交回测/优化/实盘任务
- 数据库存储任务队列和结果
- 后台异步执行（回测引擎、参数优化、实盘交易）
- 结果可查询、可视化、导出

### 1.2 技术栈
| 层级 | 技术 | 理由 |
|------|------|------|
| 前端 | Streamlit + HTML/CSS/JS | 快速开发，兼容 Python 生态 |
| 后端 | FastAPI + Uvicorn | 异步高性能，自动生成 OpenAPI 文档 |
| 数据库 | SQLite (开发) / PostgreSQL (生产) | 轻量，易迁移 |
| 任务队列 | APScheduler + 线程池 | 单机足够，轻量 |
| 缓存 | 内存 Dict + Parquet 文件 | 回测数据缓存 |
| 数据获取 | yfinance, ccxt, akshare | 多资产覆盖 |
| 回测引擎 | 自研事件驱动 | 完全可控，兼容 QuantConnect |
| 可视化 | Plotly + Streamlit | 交互式图表 |

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interface (Frontend)                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Streamlit Dashboard                                   │  │
│  │  - 新建任务页面 (表单提交)                             │  │
│  │  - 任务队列页面 (状态查看)                             │  │
│  │  - 结果分析页面 (图表展示)                             │  │
│  │  - 系统监控页面 (API/数据库状态)                       │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────┘
                              │ HTTP REST API
┌─────────────────────────────┴───────────────────────────────┐
│                    API Gateway (FastAPI)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Task API   │  │  Query API  │  │  Strategy API       │ │
│  │  (创建/取消) │  │  (查询/导出) │  │  (策略CRUD)         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────┴───────────────────────────────┐
│                    Task Scheduler (APScheduler)               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  - 任务队列管理 (pending -> running -> completed)      │  │
│  │  - 后台执行回测引擎                                   │  │
│  │  - 后台执行参数优化                                   │  │
│  │  - 后台执行实盘交易                                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────┴───────────────────────────────┐
│                    Database Layer (SQLite)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  tasks      │  │  results    │  │  strategies         │ │
│  │  任务队列   │  │  回测结果   │  │  策略配置           │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  positions  │  │  trades     │  │  equity_curves      │ │
│  │  持仓快照   │  │  交易记录   │  │  权益曲线           │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
1. 用户提交回测任务 (Frontend -> API)
2. API 验证参数，创建数据库记录 (API -> DB)
3. 任务进入队列，状态 = PENDING (API -> Scheduler)
4. Scheduler 分配线程执行 (Scheduler -> Engine)
5. 回测引擎执行，更新状态 = RUNNING (Engine -> DB)
6. 执行完成，保存结果，状态 = COMPLETED (Engine -> DB)
7. 用户查询结果，前端展示图表 (Frontend -> API -> DB)
```

---

## 3. 数据库设计 (SQLite Schema)

### 3.1 表结构

```sql
-- 任务主表
create table tasks (
    id              integer primary key autoincrement,
    type            text not null,           -- 'backtest', 'optimization', 'live_trade', 'data_sync'
    status          text not null default 'pending',  -- 'pending', 'running', 'completed', 'failed', 'cancelled'
    
    -- 策略配置 (JSON)
    strategy_name   text not null,           -- 'adaptive_momentum_v3'
    strategy_params text,                    -- JSON: {"max_position_pct": 0.1, ...}
    symbols         text,                    -- JSON: ["AAPL", "MSFT"]
    
    -- 时间范围
    start_date      text,                    -- '2023-01-01'
    end_date        text,                    -- '2024-12-31'
    interval        text default '1d',       -- '1d', '1h', '5m', '1m'
    
    -- 资金配置
    initial_cash    real default 100000.0,
    commission_rate real default 0.001,
    
    -- 结果 (JSON, 任务完成后填充)
    result          text,                    -- JSON: {"total_return": 16.15, ...}
    error_message   text,                    -- 错误信息
    
    -- 时间戳
    created_at      timestamp default current_timestamp,
    started_at      timestamp,               -- 开始执行时间
    completed_at    timestamp,               -- 完成时间
    
    -- 执行时间统计
    execution_time  real                      -- 执行耗时（秒）
);

-- 回测结果详情表
create table backtest_results (
    id              integer primary key autoincrement,
    task_id         integer not null references tasks(id),
    
    -- 核心指标
    total_return    real,
    cagr            real,
    sharpe_ratio    real,
    sortino_ratio   real,
    max_drawdown    real,
    volatility      real,
    calmar_ratio    real,
    
    -- 交易统计
    total_trades    integer,
    winning_trades  integer,
    losing_trades   integer,
    win_rate        real,
    profit_factor   real,
    avg_trade_pnl   real,
    total_commission real,
    
    -- 数据文件路径
    equity_curve_path   text,               -- 'data_cache/results/equity_1.csv'
    trades_path         text,               -- 'data_cache/results/trades_1.csv'
    
    created_at      timestamp default current_timestamp
);

-- 策略配置表
create table strategies (
    id              integer primary key autoincrement,
    name            text not null unique,     -- 'adaptive_momentum_v3'
    class_name      text not null,           -- 'AdaptiveMomentumV3'
    description     text,
    default_params  text,                    -- JSON
    created_at      timestamp default current_timestamp
);

-- 用户配置表
create table user_settings (
    id              integer primary key autoincrement,
    key             text not null unique,
    value           text,
    updated_at      timestamp default current_timestamp
);

-- 索引
-- 快速查询任务状态
CREATE INDEX idx_tasks_status ON tasks(status);
-- 快速查询策略
CREATE INDEX idx_tasks_strategy ON tasks(strategy_name);
-- 快速查询时间范围
CREATE INDEX idx_tasks_created ON tasks(created_at);
-- 快速查询结果
CREATE INDEX idx_results_task ON backtest_results(task_id);
```

---

## 4. API 设计 (RESTful)

### 4.1 端点列表

| 方法 | 端点 | 描述 | 请求体 | 响应 |
|------|------|------|--------|------|
| GET | `/health` | 健康检查 | - | `{"status": "healthy"}` |
| GET | `/strategies` | 列出策略 | - | `List[StrategyInfo]` |
| GET | `/strategies/{name}` | 策略详情 | - | `StrategyInfo` |
| POST | `/backtest` | 创建回测 | `BacktestRequest` | `TaskResponse` |
| POST | `/optimize` | 创建参数优化 | `OptimizeRequest` | `TaskResponse` |
| GET | `/tasks` | 列出任务 | `?status=completed&limit=50` | `List[TaskResponse]` |
| GET | `/tasks/{id}` | 任务详情 | - | `TaskResponse` |
| GET | `/tasks/{id}/result` | 回测结果 | - | `BacktestResult` |
| DELETE | `/tasks/{id}` | 取消任务 | - | `{"message": "cancelled"}` |
| GET | `/results/{id}/equity` | 下载权益曲线 | - | CSV file |
| GET | `/results/{id}/trades` | 下载交易记录 | - | CSV file |

### 4.2 请求/响应模型

```python
# BacktestRequest
{
    "strategy_name": "adaptive_momentum_v3",
    "symbols": ["AAPL", "MSFT", "NVDA"],
    "start_date": "2023-01-01",
    "end_date": "2024-12-31",
    "interval": "1d",
    "initial_cash": 100000.0,
    "commission_rate": 0.001,
    "strategy_params": {
        "max_position_pct": 0.10,
        "rebalance_freq": 10
    }
}

# TaskResponse
{
    "id": 1,
    "type": "backtest",
    "status": "completed",
    "created_at": "2026-07-13T01:00:00",
    "started_at": "2026-07-13T01:00:05",
    "completed_at": "2026-07-13T01:02:30",
    "result": {
        "total_return": 16.15,
        "sharpe_ratio": 0.60,
        "max_drawdown": -6.07
    },
    "error_message": null
}

# BacktestResult
{
    "task_id": 1,
    "metrics": {
        "total_return": 16.15,
        "cagr": 5.14,
        "sharpe_ratio": 0.60,
        "max_drawdown": -6.07
    },
    "equity_curve": ["2023-01-01", 100000, ...],
    "trades": [...]
}
```

---

## 5. 前端设计

### 5.1 页面结构

```
Dashboard (Streamlit)
├── 🏠 首页
│   ├── 系统状态概览 (API/DB/Scheduler)
│   ├── 最近任务列表
│   └── 策略统计
├── 🚀 新建回测
│   ├── 策略选择 (下拉框)
│   ├── 参数配置 (动态表单)
│   ├── 标的集选择 (预设/自定义)
│   ├── 时间范围选择
│   ├── 资金配置
│   └── 提交按钮
├── 📋 任务队列
│   ├── 任务列表 (表格 + 状态筛选)
│   ├── 任务详情 (点击展开)
│   └── 操作按钮 (取消/重试/删除)
├── 📈 结果分析
│   ├── 任务选择
│   ├── 核心指标卡片
│   ├── 权益曲线图
│   ├── 回撤图
│   ├── 月度收益热力图
│   ├── 交易分布图
│   └── 下载按钮 (CSV/JSON)
└── ⚙️ 系统管理
    ├── API 配置
    ├── 数据库管理
    ├── 日志查看
    └── 策略管理
```

### 5.2 前端-后端交互流程

```
1. 页面加载 -> GET /health (检查API状态)
2. 策略选择 -> GET /strategies (加载策略列表)
3. 提交表单 -> POST /backtest (创建任务)
4. 轮询状态 -> GET /tasks/{id} (每5秒轮询)
5. 查看结果 -> GET /tasks/{id}/result (加载数据)
6. 下载图表 -> GET /results/{id}/equity (下载CSV)
```

---

## 6. 任务调度设计

### 6.1 调度器架构

```python
class TaskScheduler:
    """任务调度器 - 管理任务队列和后台执行"""
    
    # 状态机
    # PENDING -> RUNNING -> COMPLETED/FAILED
    # PENDING -> CANCELLED
    
    def __init__(self, max_workers=4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers)
        self.running_tasks = {}  # task_id -> Future
    
    def submit(self, task_id: int, request: BacktestRequest) -> None:
        """提交任务到队列"""
        # 1. 检查并发数
        if len(self.running_tasks) >= self.max_workers:
            raise QueueFull("Max workers reached")
        
        # 2. 提交到线程池
        future = self.executor.submit(self._run_task, task_id, request)
        self.running_tasks[task_id] = future
        
        # 3. 添加完成回调
        future.add_done_callback(
            lambda f: self._on_task_done(task_id, f)
        )
    
    def _run_task(self, task_id: int, request: BacktestRequest) -> None:
        """执行任务"""
        # 1. 更新状态为 RUNNING
        db.update_task_status(task_id, TaskStatus.RUNNING)
        
        # 2. 执行回测
        result = self._execute_backtest(request)
        
        # 3. 保存结果
        db.save_backtest_result(task_id, result)
        
        # 4. 更新状态为 COMPLETED
        db.update_task_status(task_id, TaskStatus.COMPLETED, result=result)
    
    def cancel(self, task_id: int) -> bool:
        """取消任务"""
        if task_id in self.running_tasks:
            future = self.running_tasks[task_id]
            future.cancel()
            return True
        return False
    
    def _on_task_done(self, task_id: int, future) -> None:
        """任务完成回调"""
        self.running_tasks.pop(task_id, None)
        
        if future.exception():
            # 执行失败
            error = str(future.exception())
            db.update_task_status(task_id, TaskStatus.FAILED, error=error)
```

---

## 7. 开发计划

### Phase 1: 数据库完善 (已完成基础，需扩展)
- [ ] 完善表结构（增加索引、外键约束）
- [ ] 实现 CRUD 操作封装
- [ ] 数据迁移脚本

### Phase 2: 后端 API 完善 (部分完成)
- [ ] 完善所有端点（已完成基础，需增加错误处理）
- [ ] 实现任务调度器
- [ ] 增加认证/授权（可选）
- [ ] 增加限流/队列管理

### Phase 3: 前端 Dashboard 完善 (部分完成)
- [ ] 连接后端 API（已完成）
- [ ] 实现轮询机制（任务状态更新）
- [ ] 结果可视化图表（Plotly）
- [ ] 下载功能（CSV/JSON）

### Phase 4: 测试与优化
- [ ] 单元测试覆盖所有 API
- [ ] 集成测试（前端-后端-数据库）
- [ ] 性能测试（并发回测）
- [ ] 错误处理完善

---

## 8. 文件结构

```
localquant/
├── DESIGN.md                    # 本设计文档
├── localquant/
│   ├── __init__.py
│   ├── api/                     # 后端 API
│   │   ├── __init__.py
│   │   ├── server.py            # FastAPI 主入口
│   │   ├── routes.py            # 路由定义
│   │   ├── models.py            # Pydantic 模型
│   │   └── dependencies.py      # 依赖注入
│   ├── db/                      # 数据库
│   │   ├── __init__.py
│   │   ├── models.py            # 数据模型
│   │   ├── manager.py           # 数据库管理器
│   │   └── schema.py            # 表结构定义
│   ├── core/                    # 回测引擎
│   │   ├── engine.py
│   │   ├── portfolio.py
│   │   ├── broker.py
│   │   └── events.py
│   ├── scheduler/               # 任务调度
│   │   ├── __init__.py
│   │   └── scheduler.py         # APScheduler 封装
│   ├── strategy/                # 策略框架
│   │   ├── base.py
│   │   └── indicators.py
│   ├── data/                    # 数据管理
│   │   ├── manager.py
│   │   └── cache.py
│   ├── live/                    # 实盘接口
│   │   ├── base.py
│   │   └── binance.py
│   └── analytics/               # 绩效分析
│       └── __init__.py
├── web/                         # 前端
│   ├── dashboard.py             # Streamlit 主入口
│   ├── components/              # 可复用组件
│   │   ├── charts.py            # 图表组件
│   │   ├── forms.py             # 表单组件
│   │   └── tables.py            # 表格组件
│   └── pages/                   # 页面
│       ├── home.py
│       ├── backtest.py
│       ├── tasks.py
│       ├── results.py
│       └── settings.py
├── tests/                       # 测试
│   ├── unit/                    # 单元测试
│   ├── integration/             # 集成测试
│   └── conftest.py              # pytest 配置
├── scripts/                     # 脚本
│   ├── start_api.sh             # 启动后端
│   ├── start_dashboard.sh       # 启动前端
│   └── seed_db.py               # 数据库初始化
├── data_cache/                  # 数据缓存
│   ├── localquant.db            # SQLite 数据库
│   └── stocks/                  # 股票数据
├── config.yaml                  # 配置文件
├── requirements.txt             # 依赖
└── setup.py                     # 安装配置
```

---

## 9. 关键设计决策

### 9.1 为什么用 SQLite 而不是 PostgreSQL？
- 单机部署足够
- 零配置，无需额外服务
- 后续可无缝迁移到 PostgreSQL
- 文件级备份简单

### 9.2 为什么用 APScheduler 而不是 Celery/RabbitMQ？
- 单机量化平台，不需要分布式队列
- 轻量，无需额外服务
- 支持定时任务和后台执行
- 后续可升级到 Redis + Celery

### 9.3 为什么用 Streamlit 而不是 React/Vue？
- Python 生态一致
- 快速开发，适合量化工具
- 无需构建步骤
- 后续可迁移到 React + FastAPI

---

*本文档是 LocalQuant v2.0 的权威设计参考，所有开发必须遵循此文档。*
