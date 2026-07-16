"""数据库 Schema 定义 - 按 DESIGN_V2.md 规范"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import json

SCHEMA = """
-- 任务主表
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT NOT NULL,           -- 'backtest', 'optimization', 'live_trade', 'data_sync'
    status          TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'running', 'completed', 'failed', 'cancelled'
    
    -- 策略配置 (JSON)
    strategy_name   TEXT NOT NULL,
    strategy_params TEXT,                    -- JSON: {"max_position_pct": 0.1, ...}
    symbols         TEXT,                    -- JSON: ["AAPL", "MSFT"]
    
    -- 时间范围
    start_date      TEXT,
    end_date        TEXT,
    interval        TEXT DEFAULT '1d',
    
    -- 资金配置
    initial_cash    REAL DEFAULT 100000.0,
    commission_rate REAL DEFAULT 0.001,
    
    -- 结果 (JSON, 任务完成后填充)
    result          TEXT,
    error_message   TEXT,
    
    -- 时间戳
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    
    -- 执行时间统计
    execution_time  REAL
);

-- 回测结果详情表
CREATE TABLE IF NOT EXISTS backtest_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER NOT NULL,
    
    -- 核心指标
    total_return    REAL,
    cagr            REAL,
    sharpe_ratio    REAL,
    sortino_ratio   REAL,
    max_drawdown    REAL,
    volatility      REAL,
    calmar_ratio    REAL,
    
    -- 交易统计
    total_trades    INTEGER,
    winning_trades  INTEGER,
    losing_trades   INTEGER,
    win_rate        REAL,
    profit_factor   REAL,
    avg_trade_pnl   REAL,
    total_commission REAL,
    
    -- 数据文件路径
    equity_curve_path   TEXT,
    trades_path         TEXT,
    
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- 策略配置表
CREATE TABLE IF NOT EXISTS strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    class_name      TEXT NOT NULL,
    description     TEXT,
    default_params  TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户配置表
CREATE TABLE IF NOT EXISTS user_settings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT NOT NULL UNIQUE,
    value           TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_strategy ON tasks(strategy_name);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_results_task ON backtest_results(task_id);
"""

def init_db(db_path: str = './data_cache/localquant.db') -> None:
    """初始化数据库"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
