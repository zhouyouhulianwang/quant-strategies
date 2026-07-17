"""
统一日志配置模块

P2修复：集中定义所有模块共享的日志格式，避免各文件 basicConfig 格式不一致。
调用 setup_logging() 会按统一格式配置根日志处理器；若根日志已配置则不会覆盖。
"""
import logging
import sys

DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logging(level: int = logging.INFO, force: bool = False) -> None:
    """
    配置统一日志格式。

    参数:
        level: 日志级别，默认 INFO
        force: 是否强制覆盖已有处理器（默认 False，避免破坏已配置的日志）
    """
    kwargs = {
        'level': level,
        'format': DEFAULT_LOG_FORMAT,
        'datefmt': DEFAULT_DATE_FORMAT,
    }
    if force:
        kwargs['force'] = True
    logging.basicConfig(**kwargs)


# 兼容旧调用：部分脚本 import logging_config 时即可生效
setup_logging()
