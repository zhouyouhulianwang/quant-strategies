"""
运行时目录清理 / 归档模块

提供按年龄和大小清理 logs/、orders/、alerts/、charts/、data/ 等目录的能力，
并支持将老文件归档到指定目录。
"""
import argparse
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

DEFAULT_DIRECTORIES = ['logs', 'orders', 'alerts', 'charts', 'data']


def _now() -> datetime:
    return datetime.now()


def _iter_files(directory: Path) -> Iterable[Path]:
    """递归遍历目录下所有文件（不存在时返回空迭代器）。"""
    if not directory.exists() or not directory.is_dir():
        return
    for item in directory.rglob('*'):
        if item.is_file():
            yield item


def _is_currently_in_use(file_path: Path, safety_margin: timedelta = timedelta(hours=1)) -> bool:
    """判断文件是否可能仍在使用。

    启发式规则：最近 safety_margin 内修改过的文件视为正在使用，避免误删。
    """
    try:
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        return (_now() - mtime) < safety_margin
    except OSError:
        return True


def _total_size_bytes(directory: Path) -> int:
    total = 0
    for f in _iter_files(directory):
        try:
            total += f.stat().st_size
        except OSError:
            continue
    return total


def _total_size_mb(directory: Path) -> float:
    return _total_size_bytes(directory) / (1024 * 1024)


def _exclude_paths(file_path: Path, exclude: Optional[Set[Path]] = None) -> bool:
    if not exclude:
        return False
    return any(
        file_path == excluded or excluded in file_path.parents
        for excluded in exclude
    )


def cleanup_old_files(
    directory: str,
    max_age_days: int = 30,
    max_size_mb: Optional[float] = 1024,
    dry_run: bool = False,
    exclude: Optional[Set[Path]] = None,
) -> dict:
    """清理目录下老文件。

    参数:
        directory: 目标目录
        max_age_days: 超过该天数的文件视为老文件
        max_size_mb: 目录总大小上限（MB），超过后继续删除最旧文件直到低于上限；None 表示不限制
        dry_run: 为 True 时只统计不删除
        exclude: 需要跳过的路径集合（如归档目录）

    返回:
        包含 deleted、errors、bytes_freed、size_before_mb、size_after_mb 的字典
    """
    directory = Path(directory).resolve()
    result = {
        'deleted': 0,
        'errors': 0,
        'bytes_freed': 0,
        'size_before_mb': 0.0,
        'size_after_mb': 0.0,
    }

    if not directory.exists():
        return result

    result['size_before_mb'] = _total_size_mb(directory)
    cutoff = _now() - timedelta(days=max_age_days)

    # 1. 按年龄删除
    for f in _iter_files(directory):
        if _exclude_paths(f, exclude):
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff and not _is_currently_in_use(f):
                size = f.stat().st_size
                if not dry_run:
                    f.unlink()
                result['deleted'] += 1
                result['bytes_freed'] += size
        except OSError:
            result['errors'] += 1

    # 2. 按总大小兜底：若仍超限，从旧到新删除直到低于阈值
    if max_size_mb is not None and max_size_mb > 0:
        target_bytes = int(max_size_mb * 1024 * 1024)
        while _total_size_bytes(directory) > target_bytes:
            files = sorted(
                [f for f in _iter_files(directory) if not _exclude_paths(f, exclude)],
                key=lambda x: x.stat().st_mtime,
            )
            if not files:
                break
            oldest = files[0]
            if _is_currently_in_use(oldest):
                # 最旧文件正在使用，无法继续安全释放空间
                break
            try:
                size = oldest.stat().st_size
                if not dry_run:
                    oldest.unlink()
                result['deleted'] += 1
                result['bytes_freed'] += size
            except OSError:
                result['errors'] += 1
                break

    result['size_after_mb'] = _total_size_mb(directory)
    return result


def archive_old_files(
    directory: str,
    archive_dir: str,
    max_age_days: int = 30,
    dry_run: bool = False,
) -> dict:
    """将目录下老文件归档到指定目录，保留相对路径结构。

    参数:
        directory: 源目录
        archive_dir: 归档根目录
        max_age_days: 超过该天数的文件会被归档
        dry_run: 为 True 时只统计不移动

    返回:
        包含 archived、errors 的字典
    """
    directory = Path(directory).resolve()
    archive_root = Path(archive_dir).resolve()
    archive_root.mkdir(parents=True, exist_ok=True)

    result = {'archived': 0, 'errors': 0}
    if not directory.exists():
        return result

    cutoff = _now() - timedelta(days=max_age_days)

    for f in _iter_files(directory):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime >= cutoff or _is_currently_in_use(f):
                continue
            relative = f.relative_to(directory)
            dest = archive_root / directory.name / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dry_run:
                shutil.move(str(f), str(dest))
            result['archived'] += 1
        except OSError:
            result['errors'] += 1

    return result


def _cleanup_all(
    days: int = 30,
    max_size_mb: Optional[float] = 1024,
    archive_dir: Optional[str] = None,
    dry_run: bool = False,
) -> List[Tuple[str, dict, Optional[dict]]]:
    """对默认目录依次执行归档（可选）和清理。"""
    archive_root = Path(archive_dir).resolve() if archive_dir else None
    exclude = {archive_root} if archive_root else None

    summary = []
    for dirname in DEFAULT_DIRECTORIES:
        dir_path = Path(dirname).resolve()
        archive_res = None

        # 如果归档目录与当前目录相同，则跳过该目录的清理，避免自毁
        if archive_root and archive_root == dir_path:
            continue

        if archive_dir:
            archive_res = archive_old_files(dirname, archive_dir, days, dry_run=dry_run)

        cleanup_res = cleanup_old_files(
            dirname,
            max_age_days=days,
            max_size_mb=max_size_mb,
            dry_run=dry_run,
            exclude=exclude,
        )
        summary.append((dirname, cleanup_res, archive_res))

    return summary


def main():
    parser = argparse.ArgumentParser(description='运行时目录清理/归档工具')
    parser.add_argument('--days', type=int, default=30, help='超过多少天的文件视为老文件')
    parser.add_argument('--max-size', type=int, default=1024, help='目录总大小上限（MB）')
    parser.add_argument('--archive', type=str, default=None, help='归档根目录，设置后先归档再清理')
    parser.add_argument('--dry-run', action='store_true', help='仅统计，不执行删除/归档')
    args = parser.parse_args()

    summary = _cleanup_all(
        days=args.days,
        max_size_mb=args.max_size,
        archive_dir=args.archive,
        dry_run=args.dry_run,
    )

    print('Cleanup summary:')
    for dirname, cleanup_res, archive_res in summary:
        line = (
            f"{dirname}: deleted={cleanup_res['deleted']}, "
            f"bytes_freed={cleanup_res['bytes_freed']}, "
            f"size_before_mb={cleanup_res['size_before_mb']:.2f}, "
            f"size_after_mb={cleanup_res['size_after_mb']:.2f}, "
            f"errors={cleanup_res['errors']}"
        )
        if archive_res is not None:
            line += f", archived={archive_res['archived']}"
        print(line)


if __name__ == '__main__':
    main()
