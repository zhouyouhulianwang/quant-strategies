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
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import base64

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


ROOT = Path(__file__).resolve().parent
DEFAULT_BACKUP_ROOT = ROOT / "backups"
ENCRYPTION_KEY_ENV = "MULTIFACTOR_BACKUP_KEY"

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


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """从密码派生 Fernet 兼容的 32-byte base64 密钥。"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _encrypt_backup_dir(backup_dir: Path, key: str) -> Path:
    """将备份目录打包为 tar.gz 并用 AES-GCM (Fernet) 加密。"""
    tar_path = backup_dir.with_suffix(".tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(backup_dir, arcname=backup_dir.name)

    salt = os.urandom(16)
    fernet = Fernet(_derive_fernet_key(key, salt))
    with open(tar_path, "rb") as f:
        encrypted = fernet.encrypt(f.read())

    enc_path = backup_dir.with_suffix(".enc.tar.gz")
    with open(enc_path, "wb") as f:
        f.write(salt + encrypted)

    # 删除未加密残留
    shutil.rmtree(backup_dir)
    tar_path.unlink()
    return enc_path


def _decrypt_backup(enc_path: Path, key: str, dest: Path) -> Path:
    """解密 .enc.tar.gz 备份并解压到 dest。"""
    with open(enc_path, "rb") as f:
        data = f.read()
    salt = data[:16]
    encrypted = data[16:]
    fernet = Fernet(_derive_fernet_key(key, salt))
    decrypted = fernet.decrypt(encrypted)

    tar_path = dest / enc_path.with_suffix("").name
    tar_path = tar_path.with_suffix(".tar.gz")
    with open(tar_path, "wb") as f:
        f.write(decrypted)

    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(dest)
    restored_dir = dest / enc_path.with_suffix("").with_suffix("").name
    return restored_dir


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
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "--encrypt 需要 cryptography 库。请安装: pip install cryptography"
            )
        key = os.environ.get(ENCRYPTION_KEY_ENV)
        if not key:
            raise RuntimeError(
                f"--encrypt 需要环境变量 {ENCRYPTION_KEY_ENV} 提供加密口令"
            )
        backup_dir = _encrypt_backup_dir(backup_dir, key)
        print(f"Encrypted backup created: {backup_dir}")

    return backup_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup multifactor runtime state and secrets")
    parser.add_argument("--dest", type=Path, help="Backup destination directory")
    parser.add_argument("--days", type=int, default=7, help="Recent days of logs/orders/alerts/charts to keep")
    parser.add_argument("--encrypt", action="store_true", help="Encrypt the backup with AES-GCM (requires environment variable MULTIFACTOR_BACKUP_KEY)")
    parser.add_argument("--decrypt", type=Path, metavar="FILE", help="Decrypt a .enc.tar.gz backup")
    parser.add_argument("--decrypt-dest", type=Path, metavar="DIR", help="Destination for --decrypt")
    parser.add_argument("--chmod-only", type=Path, metavar="DIR", help="Fix permissions on an existing backup directory")
    args = parser.parse_args()

    if args.chmod_only:
        _set_restrictive_permissions(args.chmod_only)
        print(f"Permissions fixed: {args.chmod_only}")
        return 0

    if args.decrypt:
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("--decrypt 需要 cryptography 库")
        key = os.environ.get(ENCRYPTION_KEY_ENV)
        if not key:
            raise RuntimeError(f"--decrypt 需要环境变量 {ENCRYPTION_KEY_ENV}")
        dest = args.decrypt_dest or Path.cwd()
        restored = _decrypt_backup(args.decrypt, key, dest)
        print(f"Backup restored to: {restored}")
        return 0

    run_backup(dest=args.dest, recent_days=args.days, encrypt=args.encrypt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
