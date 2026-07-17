"""
版本追踪模块

提供策略与风控进程的版本号，用于变更追踪和回滚。
"""

__version__ = "1.0.0"


def get_version():
    """返回当前版本号"""
    return __version__


def version_info():
    """返回版本信息字典"""
    return {
        "version": __version__,
        "major": 1,
        "minor": 0,
        "patch": 0,
    }
