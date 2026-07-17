"""
公共 Parquet 缓存模块

为 multifactor 项目提供统一的 parquet 缓存读写、校验和元数据管理接口。
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


# 默认缓存版本，向后兼容 data_source.py / polygon_data.py / quantconnect_data.py 中的旧版本
CACHE_VERSION = 1


def _decode_metadata(meta_dict):
    """将 pyarrow 字节型 metadata 解码为字符串字典"""
    if not meta_dict:
        return {}

    result = {}
    for k, v in meta_dict.items():
        if k in (b'ARROW:schema', b'pandas'):
            continue
        key = k.decode('utf-8') if isinstance(k, bytes) else str(k)
        val = v.decode('utf-8') if isinstance(v, bytes) else str(v)
        result[key] = val
    return result


def _encode_metadata(meta_dict):
    """将字符串字典编码为 pyarrow metadata 字节字典"""
    encoded = {}
    for k, v in (meta_dict or {}).items():
        if k in (b'ARROW:schema', b'pandas'):
            continue
        key = k.encode('utf-8') if isinstance(k, str) else k
        val = str(v).encode('utf-8') if v is not None else b''
        encoded[key] = val
    return encoded


def is_cache_valid(path: str, ttl_days: int = 1, version: Optional[Any] = None) -> bool:
    """
    检查 parquet 缓存是否有效

    参数:
        path: str, 缓存文件路径
        ttl_days: int, 缓存有效天数（默认 1 天）
        version: Any, 期望的版本号（默认 None 表示不检查版本）

    返回:
        bool: 缓存存在且有效
    """
    if not path or not os.path.exists(path):
        return False

    try:
        metadata = get_cache_metadata(path)

        # 版本检查
        if version is not None:
            cache_version = metadata.get('cache_version') or metadata.get('version')
            if str(cache_version) != str(version):
                return False

        # TTL 检查
        downloaded_at = metadata.get('downloaded_at')
        if downloaded_at:
            try:
                created = datetime.fromisoformat(downloaded_at)
                if datetime.now() - created > timedelta(days=ttl_days):
                    return False
            except ValueError:
                return False
        elif ttl_days > 0:
            # 没有创建时间且要求 TTL，则视为无效
            return False

        return True
    except Exception:
        return False


def get_cache_metadata(path: str) -> Dict[str, str]:
    """
    读取 parquet 缓存的元数据

    参数:
        path: str, 缓存文件路径

    返回:
        dict: 元数据键值对
    """
    if not os.path.exists(path):
        return {}

    try:
        meta = pq.read_metadata(path)
        return _decode_metadata(meta.metadata)
    except Exception:
        return {}


def load_parquet_cache(path: str, ttl_days: int = 1, version: Optional[Any] = None) -> Optional[Union[pd.DataFrame, pd.Series]]:
    """
    从 parquet 缓存加载数据

    参数:
        path: str, 缓存文件路径
        ttl_days: int, 缓存有效天数
        version: Any, 期望版本号

    返回:
        DataFrame 或 Series，缓存无效/不存在时返回 None
    """
    if not is_cache_valid(path, ttl_days=ttl_days, version=version):
        return None

    try:
        df = pd.read_parquet(path)
        # 兼容旧单列表缓存：自动还原为 Series
        if isinstance(df, pd.DataFrame) and len(df.columns) == 1:
            return df.iloc[:, 0]
        return df
    except Exception:
        return None


def save_parquet_cache(df, path: str, metadata: Optional[Dict[str, Any]] = None, version: Optional[Any] = None) -> bool:
    """
    保存数据到 parquet 缓存

    参数:
        df: DataFrame / Series, 待保存数据
        path: str, 缓存文件路径
        metadata: dict, 自定义元数据（默认空）
        version: Any, 版本号（默认 None，则使用默认版本 CACHE_VERSION）

    返回:
        bool: 保存是否成功
    """
    try:
        if df is None or (hasattr(df, '__len__') and len(df) == 0):
            return False

        # 统一转换为 DataFrame，保留索引
        if isinstance(df, pd.Series):
            save_df = df.to_frame(name=df.name or 'value')
        else:
            save_df = df.copy()

        if save_df.index.name is None:
            save_df.index.name = 'date'

        # 丢弃索引为 NaT 的无效行，避免 parquet 写入失败
        save_df = save_df[save_df.index.notna()]
        if len(save_df) == 0:
            return False

        # 确保目录存在
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

        table = pa.Table.from_pandas(save_df)
        existing_metadata = table.schema.metadata or {}

        cache_metadata = {
            'cache_version': str(version if version is not None else CACHE_VERSION),
            'downloaded_at': datetime.now().isoformat(),
        }
        if metadata:
            cache_metadata.update(metadata)

        new_metadata = {
            **existing_metadata,
            **_encode_metadata(cache_metadata),
        }
        table = table.replace_schema_metadata(new_metadata)
        pq.write_table(table, path)
        return True
    except Exception:
        return False
