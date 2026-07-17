"""
统一日志配置模块

P2修复：集中定义所有模块共享的日志格式，避免各文件 basicConfig 格式不一致。
调用 setup_logging() 会按统一格式配置根日志处理器；若根日志已配置则不会覆盖。

新增：支持 JSON 结构化日志、按大小/时间轮转的文件日志。
"""
import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict

DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
DEFAULT_LOG_DIR = 'logs'
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_BACKUP_COUNT = 5
DEFAULT_TIMED_INTERVAL = 'D'  # 每天轮转
DEFAULT_TIMED_BACKUP_COUNT = 7

# 标准 LogRecord 字段，JSON 格式化时排除，避免冗余
_STANDARD_RECORD_KEYS = {
    'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
    'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
    'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
    'processName', 'process', 'message',
}


class JSONFormatter(logging.Formatter):
    """JSON 格式日志格式化器

    输出字段包含 timestamp、level、logger、message、module、function、line，
    以及日志调用 extra 参数传入的所有自定义字段（如 event、symbol、qty、price、
    nav、drawdown 等）。
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # 合并 extra 字段，可覆盖默认字段（如 risk level 会覆盖 levelname）
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS:
                log_obj[key] = value

        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False, default=str)


def _text_formatter() -> logging.Formatter:
    return logging.Formatter(DEFAULT_LOG_FORMAT, DEFAULT_DATE_FORMAT)


def _ensure_log_dir(log_dir: str) -> Path:
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    return log_path


def _has_file_handler(root: logging.Logger) -> bool:
    return any(
        isinstance(h, (RotatingFileHandler, TimedRotatingFileHandler))
        for h in root.handlers
    )


def _add_file_handler(
    root: logging.Logger,
    log_dir: str,
    json_format: bool,
    file_handler_type: str,
    max_bytes: int,
    backup_count: int,
    timed_interval: str,
    timed_backup_count: int,
) -> None:
    if _has_file_handler(root):
        return

    log_path = _ensure_log_dir(log_dir)
    filename = log_path / 'multifactor.log'

    if file_handler_type == 'rotating':
        file_handler = RotatingFileHandler(
            filename=str(filename),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
        )
    elif file_handler_type == 'timed':
        file_handler = TimedRotatingFileHandler(
            filename=str(filename),
            when=timed_interval,
            interval=1,
            backupCount=timed_backup_count,
            encoding='utf-8',
        )
    else:
        raise ValueError(
            f"Unknown file_handler_type: {file_handler_type}, "
            "expected 'rotating' or 'timed'"
        )

    file_handler.setFormatter(
        JSONFormatter() if json_format else _text_formatter()
    )
    root.addHandler(file_handler)


def _configure_json_logger(level: int, log_dir: str = DEFAULT_LOG_DIR) -> None:
    """为结构化日志 logger 'json' 配置 JSON 处理器。

    该 logger 用于 json_logger.py 中的 trade/risk/portfolio 事件，
    与根日志的文本/文件格式解耦。
    """
    json_logger = logging.getLogger('json')
    json_logger.setLevel(level)

    # P2 修复：'json' logger 同时输出到控制台和文件，避免只走 StreamHandler
    if not json_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        json_logger.addHandler(handler)

    # 添加独立的 JSON 文件处理器（幂等）
    has_file_handler = any(
        isinstance(h, (RotatingFileHandler, TimedRotatingFileHandler))
        for h in json_logger.handlers
    )
    if not has_file_handler:
        log_path = _ensure_log_dir(log_dir)
        filename = log_path / 'multifactor.json.log'
        file_handler = RotatingFileHandler(
            filename=str(filename),
            maxBytes=DEFAULT_MAX_BYTES,
            backupCount=DEFAULT_BACKUP_COUNT,
            encoding='utf-8',
        )
        file_handler.setFormatter(JSONFormatter())
        json_logger.addHandler(file_handler)

    json_logger.propagate = False


def setup_logging(
    level: int = logging.INFO,
    force: bool = False,
    json_format: bool = False,
    log_dir: str = DEFAULT_LOG_DIR,
    file_handler_type: str = 'rotating',
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    timed_interval: str = DEFAULT_TIMED_INTERVAL,
    timed_backup_count: int = DEFAULT_TIMED_BACKUP_COUNT,
) -> None:
    """
    配置统一日志格式。

    参数:
        level: 日志级别，默认 INFO
        force: 是否强制覆盖已有处理器（默认 False，避免破坏已配置的日志）
        json_format: 是否使用 JSON 格式输出（默认 False，保留文本兼容）
        log_dir: 文件日志目录，默认 logs/
        file_handler_type: 文件轮转方式，'rotating' 或 'timed'
        max_bytes: RotatingFileHandler 单文件最大字节数
        backup_count: RotatingFileHandler 保留备份数
        timed_interval: TimedRotatingFileHandler 轮转间隔单位
        timed_backup_count: TimedRotatingFileHandler 保留备份数
    """
    kwargs = {
        'level': level,
        'format': DEFAULT_LOG_FORMAT,
        'datefmt': DEFAULT_DATE_FORMAT,
    }
    if force:
        kwargs['force'] = True
    logging.basicConfig(**kwargs)

    root = logging.getLogger()
    root.setLevel(level)

    # 若开启 JSON，同步更新已有 StreamHandler 的格式
    if json_format:
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setFormatter(JSONFormatter())

    # 添加文件轮转处理器（幂等，避免多个模块重复调用时重复 Handler）
    _add_file_handler(
        root,
        log_dir,
        json_format,
        file_handler_type,
        max_bytes,
        backup_count,
        timed_interval,
        timed_backup_count,
    )

    # 为结构化事件日志配置独立 JSON 输出
    _configure_json_logger(level)

    # 支持环境变量切换 JSON 格式
    if os.environ.get('MULTIFACTOR_LOG_JSON', '').lower() in ('1', 'true', 'yes'):
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setFormatter(JSONFormatter())


# 兼容旧调用：部分脚本 import logging_config 时即可生效
# P2/L-01: 模块导入期不再自动初始化日志，避免 Handler 重复；由入口文件调用。
