#!/usr/bin/env python3
"""Backup runtime configuration and trading state for the multifactor system.

Usage:
    python3 backup_state.py [--dest /path/to/backup] [--encrypt]

By default creates a timestamped backup directory and copies:
- .env
- config.json
- data/pdt_*.json
- latest logs/orders/alerts (last 7 days)

It does NOT copy large data caches (quant/, data/parquet/, Clone*/)."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_BACKUP_ROOT = ROOT / "backups"

# Sensitive / small runtime files to keep
PROTECTED_FILES = [
    ".env",
    "config.json",
    "local.json",
]

# Directories to partially back up (last N days only)
DATED_DIRS = [
    "logs",
    "orders",
    "alerts",
    "charts",
]

# Glob patterns to always back up under data/
DATA_GLOBS = [
    "data/pdt_*.json",
]


def _backup_dir_name() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _set_restrictive_permissions(path: Path) -> None:
    """Set 600 for files, 700 for dirs inside the backup."""
    if path.is_file():
        path.chmod(0o600)
    elif path.is_dir():
        path.chmod(0o700)
        for child in path.rglob("*"):
            if child.is_file():
                child.chmod(0o600)
            elif child.is_dir():
                child.chmod(0o700)


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    dest.chmod(0o600)


def _collect_recent_files(src_dir: Path, days: int) -> list[Path]:
    """Return files under src_dir modified in the last `days` days."""
    if not src_dir.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    files: list[Path] = []
    for path in src_dir.rglob("*"):
        if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) > cutoff:
            files.append(path)
    return files


def run_backup(dest: Path | None = None, recent_days: int = 7, encrypt: bool = False) -> Path:
    backup_root = dest or DEFAULT_BACKUP_ROOT
    backup_dir = backup_root / _backup_dir_name()
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Copy protected files
    for rel in PROTECTED_FILES:
        src = ROOT / rel
        if src.exists():
            _copy_file(src, backup_dir / rel)

    # Copy PDT / state files
    for pattern in DATA_GLOBS:
        for src in ROOT.glob(pattern):
            rel = src.relative_to(ROOT)
            _copy_file(src, backup_dir / rel)

    # Partial copy of dated directories
    for name in DATED_DIRS:
        src_dir = ROOT / name
        if not src_dir.exists():
            continue
        recent_files = _collect_recent_files(src_dir, recent_days)
        for src in recent_files:
            rel = src.relative_to(ROOT)
            _copy_file(src, backup_dir / rel)

    # Metadata
    meta_file = backup_dir / "backup_metadata.txt"
    meta_file.write_text(
        f"created_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"source: {ROOT}\n"
        f"recent_days: {recent_days}\n"
        f"encrypt: {encrypt}\n"
    )
    meta_file.chmod(0o600)

    _set_restrictive_permissions(backup_dir)

    print(f"Backup created: {backup_dir}")
    print(f"Total size: {sum(f.stat().st_size for f in backup_dir.rglob('*') if f.is_file())} bytes")

    if encrypt:
        # Placeholder: real encryption should use gpg or age
        print("NOTE: --encrypt is a placeholder; install gpg/age and update this script for production.")

    return backup_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup multifactor runtime state and secrets")
    parser.add_argument("--dest", type=Path, help="Backup destination directory")
    parser.add_argument("--days", type=int, default=7, help="Recent days of logs/orders/alerts/charts to keep")
    parser.add_argument("--encrypt", action="store_true", help="Placeholder: encrypt the backup (not implemented)")
    parser.add_argument("--chmod-only", type=Path, metavar="DIR", help="Fix permissions on an existing backup directory")
    args = parser.parse_args()

    if args.chmod_only:
        _set_restrictive_permissions(args.chmod_only)
        print(f"Permissions fixed: {args.chmod_only}")
        return 0

    run_backup(dest=args.dest, recent_days=args.days, encrypt=args.encrypt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
