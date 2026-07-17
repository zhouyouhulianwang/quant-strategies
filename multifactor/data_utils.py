"""Data utilities shared across data source modules.

This module contains helpers that are used by multiple data sources to avoid
code duplication: limited forward fill, timezone-naive index normalization,
and Wilder RSI computation.
"""

import os
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# P0修复：最大前向填充交易日数（默认 5 日），防止停牌/退市股票无限制前向填充导致前视偏差
MAX_FFILL_DAYS = int(os.getenv('MULTIFACTOR_MAX_FFILL_DAYS', 5))


def _normalize_index(data):
    """将时区感知索引统一为 naive 日期，保证多源数据对齐"""
    if data is None or len(data) == 0:
        return data
    if hasattr(data.index, 'tz') and data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    return data


def _limited_ffill(df, max_days=MAX_FFILL_DAYS, active=None):
    """
    P0修复：受限前向填充，超过 max_days 的缺失值保持 NaN。

    参数:
        df: DataFrame/Series
        max_days: int, 最大前向填充天数（交易日）
        active: 可选，dict/Series/DataFrame，标记标的是否仍活跃；
                若提供，退市/不活跃日期后不再填充。
    """
    if df is None or df.empty:
        return df
    filled = df.ffill(limit=max_days)
    if active is not None:
        try:
            if isinstance(active, pd.DataFrame) and filled.shape == active.shape:
                filled = filled.where(active)
            elif isinstance(active, dict):
                for symbol, is_active in active.items():
                    if symbol in filled.columns and not is_active:
                        filled[symbol] = np.nan
        except Exception as e:
            logger.warning("[PIT] active/delisted marker handling failed: %s", e)
    return filled


def _compute_rsi_wilder(prices, window=14):
    """
    使用 Wilder 平滑（指数移动平均 alpha=1/window）计算 RSI
    """
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))

    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi
