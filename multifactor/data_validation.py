"""
数据质量验证模块 - 价格数据校验、幸存者偏差检测、公司行动校验

提供回测 / 实盘数据管道的质量保障函数：

    - validate_price_data(price_df):
        检查缺失值、陈旧价格、可疑跳变、负价格，返回结构化报告。
    - detect_survivorship_bias(universe, delisted_file=None):
        对比目标 universe 与实际可用数据，报告缺失（可能已退市）标的。
    - validate_corporate_actions(price_df, splits_file=None):
        拆股 / 分红校验占位符（检测未调整价格中的拆股式跳变）。

所有函数均为纯函数：不修改输入，返回 dict 报告，方便日志与断言。
"""

import json
import logging
import os
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 默认阈值
DEFAULT_STALE_DAYS = 10            # 连续相同价格天数阈值
DEFAULT_JUMP_PCT = 0.30            # 单日收益绝对值超过 30% 视为可疑跳变
DEFAULT_SPLIT_JUMP_PCT = 0.45      # 单日收益绝对值超过 45% 且接近整数比例，疑似未调整拆股


# ============================================================
# 1. 价格数据校验
# ============================================================

def validate_price_data(price_df: pd.DataFrame,
                        stale_days: int = DEFAULT_STALE_DAYS,
                        jump_pct: float = DEFAULT_JUMP_PCT) -> Dict:
    """
    校验价格矩阵质量。

    检查项:
        - missing_values:   每列 NaN 数量与比例
        - stale_prices:     连续 >= stale_days 天价格不变的区间（可能停牌/数据中断）
        - suspicious_jumps: 单日收益绝对值 > jump_pct 的（日期, 标的）点
        - negative_prices:  价格 <= 0 的（日期, 标的）点

    参数:
        price_df: DataFrame, 索引=日期, 列=标的, 值=价格
        stale_days: int, 陈旧价格判定阈值（连续相同价格天数）
        jump_pct: float, 可疑跳变阈值（如 0.30 = 30%）

    返回:
        dict: {
            'ok': bool,                    # 是否通过全部检查
            'n_rows': int, 'n_cols': int,
            'missing_values': {symbol: {'count': int, 'pct': float}},
            'stale_prices':   {symbol: [{'start': str, 'end': str, 'days': int}]},
            'suspicious_jumps': {symbol: [{'date': str, 'return': float}]},
            'negative_prices':  {symbol: [{'date': str, 'price': float}]},
            'issues': [str],               # 人类可读的问题摘要
        }
    """
    report: Dict = {
        'ok': True,
        'n_rows': 0,
        'n_cols': 0,
        'missing_values': {},
        'stale_prices': {},
        'suspicious_jumps': {},
        'negative_prices': {},
        'issues': [],
    }

    if price_df is None or not isinstance(price_df, pd.DataFrame) or price_df.empty:
        report['ok'] = False
        report['issues'].append('price_df is empty or not a DataFrame')
        return report

    df = price_df.sort_index()
    report['n_rows'], report['n_cols'] = df.shape

    # ---- 1. 缺失值 ----
    for col in df.columns:
        n_nan = int(df[col].isna().sum())
        if n_nan > 0:
            pct = n_nan / len(df)
            report['missing_values'][col] = {'count': n_nan, 'pct': round(pct, 4)}
            report['issues'].append(f'{col}: {n_nan} missing values ({pct:.1%})')

    # ---- 2. 负价格 / 零价格 ----
    for col in df.columns:
        bad = df[col].dropna()
        bad = bad[bad <= 0]
        if len(bad) > 0:
            report['negative_prices'][col] = [
                {'date': str(d.date() if hasattr(d, 'date') else d), 'price': float(p)}
                for d, p in bad.head(20).items()
            ]
            report['issues'].append(f'{col}: {len(bad)} non-positive prices')

    # ---- 3. 陈旧价格 ----
    for col in df.columns:
        s = df[col].dropna()
        if len(s) < stale_days + 1:
            continue
        stale = _find_stale_runs(s, min_days=stale_days)
        if stale:
            report['stale_prices'][col] = stale
            report['issues'].append(
                f'{col}: {len(stale)} stale run(s) >= {stale_days} days'
            )

    # ---- 4. 可疑跳变 ----
    rets = df.pct_change(fill_method=None)
    for col in rets.columns:
        r = rets[col].dropna()
        jumps = r[r.abs() > jump_pct]
        if len(jumps) > 0:
            report['suspicious_jumps'][col] = [
                {'date': str(d.date() if hasattr(d, 'date') else d), 'return': round(float(v), 4)}
                for d, v in jumps.head(50).items()
            ]
            report['issues'].append(
                f'{col}: {len(jumps)} suspicious jump(s) > {jump_pct:.0%}'
            )

    if report['issues']:
        report['ok'] = False
    return report


def _find_stale_runs(series: pd.Series, min_days: int) -> List[Dict]:
    """查找连续相同价格的区间（长度 >= min_days）"""
    runs: List[Dict] = []
    values = series.values
    index = series.index
    n = len(values)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[j + 1] == values[i]:
            j += 1
        run_len = j - i + 1
        if run_len >= min_days:
            start, end = index[i], index[j]
            runs.append({
                'start': str(start.date() if hasattr(start, 'date') else start),
                'end': str(end.date() if hasattr(end, 'date') else end),
                'days': int(run_len),
            })
        i = j + 1
    return runs


# ============================================================
# 2. 幸存者偏差检测
# ============================================================

def detect_survivorship_bias(universe: Sequence[str],
                             available: Optional[Sequence[str]] = None,
                             delisted_file: Optional[str] = None) -> Dict:
    """
    检测幸存者偏差：对比目标 universe 与实际可用数据 / 已知退市名单。

    参数:
        universe: list[str], 目标股票池（例如回测期初的成分股）
        available: list[str], 可选，实际获得数据的标的列表；
                   为 None 时仅基于 delisted_file 分析
        delisted_file: str, 可选，已知退市标的清单（JSON list 或纯文本每行一个代码）

    返回:
        dict: {
            'universe_size': int,
            'available_size': int or None,
            'missing_from_data': [str],     # 在 universe 中但无数据
            'known_delisted': [str],        # 从 delisted_file 加载且在 universe 中
            'coverage_pct': float or None,  # available / universe
            'warning': str or None,
            'ok': bool,
        }
    """
    uni = sorted({str(s).upper().strip() for s in universe if s})
    report: Dict = {
        'universe_size': len(uni),
        'available_size': None,
        'missing_from_data': [],
        'known_delisted': [],
        'coverage_pct': None,
        'warning': None,
        'ok': True,
    }

    if not uni:
        report['ok'] = False
        report['warning'] = 'empty universe'
        return report

    # 可用数据覆盖
    if available is not None:
        avail = sorted({str(s).upper().strip() for s in available if s})
        report['available_size'] = len(avail)
        missing = sorted(set(uni) - set(avail))
        report['missing_from_data'] = missing
        report['coverage_pct'] = round(len(avail) / len(uni), 4)
        if missing:
            report['warning'] = (
                f'{len(missing)}/{len(uni)} tickers have no data; '
                f'backtest may suffer survivorship bias'
            )

    # 已知退市名单
    if delisted_file:
        known = _load_ticker_file(delisted_file)
        in_universe = sorted(set(uni) & known)
        report['known_delisted'] = in_universe
        if in_universe:
            msg = f'{len(in_universe)} known delisted tickers present in universe: {in_universe[:10]}'
            report['warning'] = (report['warning'] + '; ' + msg) if report['warning'] else msg

    if report['missing_from_data'] or report['known_delisted']:
        report['ok'] = False
    return report


def _load_ticker_file(path: str) -> set:
    """加载标的清单文件（JSON list 或每行一个代码的文本）"""
    if not os.path.exists(path):
        logger.warning("delisted_file not found: %s", path)
        return set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read().strip()
        if not text:
            return set()
        if text.startswith('['):
            data = json.loads(text)
            return {str(t).upper().strip() for t in data}
        return {
            line.split(',')[0].strip().upper()
            for line in text.splitlines() if line.strip()
        }
    except Exception as e:
        logger.warning("failed to load delisted_file %s: %s", path, e)
        return set()


# ============================================================
# 3. 公司行动校验（占位实现）
# ============================================================

def validate_corporate_actions(price_df: pd.DataFrame,
                               splits_file: Optional[str] = None,
                               jump_pct: float = DEFAULT_SPLIT_JUMP_PCT) -> Dict:
    """
    校验拆股 / 分红调整（占位实现）。

    当前逻辑：检测疑似未调整的拆股跳变 —— 单日收益绝对值 > jump_pct
    且收益率接近简单拆股比例（1/2, 1/3, 2, 3...）对应的价格变化。
    若提供 splits_file（JSON: {symbol: [{date, ratio}, ...]}），
    检查每个拆股事件前后价格是否已按比例调整。

    参数:
        price_df: DataFrame, 价格矩阵
        splits_file: str, 可选，拆股事件 JSON 文件
        jump_pct: float, 疑似拆股跳变阈值

    返回:
        dict: {
            'ok': bool,
            'suspected_unadjusted_splits': {symbol: [{date, return, implied_ratio}]},
            'split_events_checked': int,
            'split_events_mismatched': [...],
            'note': str,
        }
    """
    report: Dict = {
        'ok': True,
        'suspected_unadjusted_splits': {},
        'split_events_checked': 0,
        'split_events_mismatched': [],
        'note': 'placeholder implementation: heuristic detection only',
    }

    if price_df is None or price_df.empty:
        report['ok'] = False
        return report

    # 启发式：接近 1/k 或 k 倍价格变化的跳变（k = 2,3,4,5）
    ratios = {2: -0.5, 3: -0.6667, 4: -0.75, 5: -0.8}
    rets = price_df.pct_change(fill_method=None)
    for col in rets.columns:
        r = rets[col].dropna()
        for d, v in r[r.abs() > jump_pct].items():
            implied = None
            for k, target in ratios.items():
                if abs(v - target) < 0.03:
                    implied = f'1:{k}'
                    break
                if abs(v - (k - 1)) < 0.15:  # k:1 正向拆股 -> +(k-1)*100%
                    implied = f'{k}:1'
                    break
            if implied:
                report['suspected_unadjusted_splits'].setdefault(col, []).append({
                    'date': str(d.date() if hasattr(d, 'date') else d),
                    'return': round(float(v), 4),
                    'implied_ratio': implied,
                })

    if report['suspected_unadjusted_splits']:
        report['ok'] = False

    # 若提供拆股事件文件，核对事件前后的价格比率
    if splits_file and os.path.exists(splits_file):
        try:
            with open(splits_file, 'r', encoding='utf-8') as f:
                events = json.load(f)
            for symbol, evs in events.items():
                if symbol not in price_df.columns:
                    continue
                s = price_df[symbol].dropna()
                for ev in evs:
                    report['split_events_checked'] += 1
                    date = pd.to_datetime(ev.get('date'))
                    ratio = float(ev.get('ratio', 0))
                    if ratio <= 0:
                        continue
                    before = s[s.index < date]
                    after = s[s.index >= date]
                    if len(before) == 0 or len(after) == 0:
                        continue
                    px_ratio = float(before.iloc[-1]) / float(after.iloc[0])
                    # 若价格已调整，前后比率应接近 1；未调整则接近拆股比例
                    if abs(px_ratio - 1.0) > 0.2 and abs(px_ratio - ratio) < 0.2:
                        report['split_events_mismatched'].append({
                            'symbol': symbol,
                            'date': str(date.date()),
                            'ratio': ratio,
                            'price_ratio': round(px_ratio, 3),
                        })
            if report['split_events_mismatched']:
                report['ok'] = False
        except Exception as e:
            logger.warning("splits_file validation failed: %s", e)
            report['note'] += f'; splits_file error: {e}'

    return report


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    # 构造测试数据
    dates = pd.date_range('2024-01-01', periods=60, freq='B')
    rng = np.random.default_rng(42)
    good = 100 * np.cumprod(1 + rng.normal(0, 0.01, len(dates)))
    stale = good.copy()
    stale[20:35] = stale[20]                     # 15 天陈旧价格
    bad = good.copy()
    bad[40] = bad[40] * 0.5                      # 疑似拆股跳变
    df = pd.DataFrame({'GOOD': good, 'STALE': stale, 'SPLITCO': bad}, index=dates)
    df.iloc[5:8, 0] = np.nan                     # 缺失值

    print('--- validate_price_data ---')
    rep = validate_price_data(df)
    print('ok:', rep['ok'])
    for issue in rep['issues']:
        print(' -', issue)

    print('\n--- detect_survivorship_bias ---')
    rep2 = detect_survivorship_bias(
        universe=['GOOD', 'STALE', 'SPLITCO', 'ENRON'],
        available=df.columns,
    )
    print(rep2)

    print('\n--- validate_corporate_actions ---')
    rep3 = validate_corporate_actions(df)
    print('ok:', rep3['ok'], '| suspected:', rep3['suspected_unadjusted_splits'])
