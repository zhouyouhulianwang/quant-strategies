#!/usr/bin/env python3
"""Data quality validation dashboard for the S&P 500 + NASDAQ-100 universe.

Reads the universe from data/sp500_tickers.json and data/ndx100_tickers.json,
loads cached price series via data_source.DataCache, and runs a battery of
quality checks on each ticker.

Quality checks performed per ticker:
  - missing dates vs NYSE trading calendar (or inferred min/max)
  - NaN / empty series
  - zero or negative prices
  - extreme single-day returns (abs return > 30%)
  - splits/mergers-like jumps (abs return > 50%)
  - stale prices (same price repeated >10 consecutive days)

Exit code:
  0 if no issues found, 1 otherwise.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Ensure the multifactor directory is importable when run from anywhere
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import numpy as np
import pandas as pd

# Lightweight import only: no HybridQCDataSource / yfinance instantiation here
from data_source import DataCache, CACHE_DIR

# Issue type constants
ISSUE_NAN_EMPTY = 'nan_or_empty_series'
ISSUE_ZERO_OR_NEGATIVE = 'zero_or_negative_prices'
ISSUE_EXTREME_RETURN = 'extreme_single_day_return'
ISSUE_SPLIT_MERGER_JUMP = 'split_merger_like_jump'
ISSUE_STALE_PRICES = 'stale_prices'
ISSUE_MISSING_DATES = 'missing_dates'

ISSUE_LABELS = {
    ISSUE_NAN_EMPTY: 'NaN / empty series',
    ISSUE_ZERO_OR_NEGATIVE: 'Zero or negative prices',
    ISSUE_EXTREME_RETURN: 'Extreme single-day return (>30%)',
    ISSUE_SPLIT_MERGER_JUMP: 'Split / merger-like jump (>50%)',
    ISSUE_STALE_PRICES: 'Stale prices (>10 consecutive days)',
    ISSUE_MISSING_DATES: 'Missing dates',
}


def load_universe() -> List[str]:
    """Load the union of S&P 500 and NASDAQ-100 tickers (uppercase, sorted)."""
    tickers = set()
    for name in ('sp500_tickers.json', 'ndx100_tickers.json'):
        path = os.path.join(SCRIPT_DIR, 'data', name)
        if not os.path.exists(path):
            print(f'[WARN] Universe file not found: {path}', file=sys.stderr)
            continue
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Support plain list ["AAPL", ...] and dict-of-lists / dict formats
        if isinstance(data, dict):
            items = data.get('tickers') or data.get('symbols') or list(data.keys())
        else:
            items = data
        for t in items:
            if isinstance(t, dict):
                t = t.get('symbol') or t.get('ticker')
            if t:
                tickers.add(str(t).upper().strip())
    return sorted(tickers)


def get_nyse_calendar() -> Optional[Any]:
    """Return the NYSE (XNYS) calendar, or None if unavailable."""
    try:
        import exchange_calendars as xc
        return xc.get_calendar('XNYS')
    except Exception:
        return None


def expected_trading_dates(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Return the NYSE trading-day calendar between start and end (inclusive)."""
    cal = get_nyse_calendar()
    if cal is None:
        # Fallback: use pandas CustomBusinessDay with a reasonable approximation
        freq = pd.offsets.CustomBusinessDay(weekmask='Mon Tue Wed Thu Fri')
        return pd.date_range(start=start, end=end, freq=freq)
    try:
        # Clamp to the calendar's available range to avoid DateOutOfBounds
        first_session = pd.Timestamp(cal.first_session)
        last_session = pd.Timestamp(cal.last_session)
        if start < first_session:
            start = first_session
        if end > last_session:
            end = last_session
        return cal.sessions_in_range(start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
    except Exception:
        # Fallback if anything goes wrong
        freq = pd.offsets.CustomBusinessDay(weekmask='Mon Tue Wed Thu Fri')
        return pd.date_range(start=start, end=end, freq=freq)


def normalize_price_series(data) -> Optional[pd.Series]:
    """Convert a loaded DataFrame or Series into a clean Series with DatetimeIndex."""
    if data is None or (hasattr(data, '__len__') and len(data) == 0):
        return None

    if isinstance(data, pd.DataFrame):
        if data.empty:
            return None
        # Use the first numeric column if the column is not named 'value'
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) == 0:
            return None
        col = numeric_cols[0]
        series = data[col].copy()
    else:
        series = data.copy()

    if not isinstance(series, pd.Series):
        return None

    # Ensure DatetimeIndex and timezone-naive
    if not isinstance(series.index, pd.DatetimeIndex):
        try:
            series.index = pd.to_datetime(series.index)
        except Exception:
            return None
    if hasattr(series.index, 'tz') and series.index.tz is not None:
        series.index = series.index.tz_localize(None)
    if hasattr(series.index, 'normalize'):
        series.index = series.index.normalize()

    series = series.sort_index()
    # Remove rows with invalid index or NaN values (we'll report NaN/empty separately)
    series = series[series.index.notna()]
    return series


def check_missing_dates(series: pd.Series, start: Optional[str], end: Optional[str]) -> Tuple[bool, str]:
    """Check for missing trading dates relative to NYSE calendar or inferred range."""
    if series is None or series.empty:
        return False, ''

    if start and end:
        try:
            start_dt = pd.to_datetime(start).normalize()
            end_dt = pd.to_datetime(end).normalize()
        except Exception:
            start_dt, end_dt = series.index.min(), series.index.max()
    else:
        start_dt, end_dt = series.index.min(), series.index.max()

    if pd.isna(start_dt) or pd.isna(end_dt):
        return False, ''

    expected = expected_trading_dates(start_dt, end_dt)
    actual = pd.DatetimeIndex(series.index).normalize()
    missing = expected.difference(actual)
    if len(missing) == 0:
        return False, ''
    return True, f'{len(missing)} missing dates (e.g. {missing[0].strftime("%Y-%m-%d")})'


def check_nan_empty(series: pd.Series) -> Tuple[bool, str]:
    """Check if the series is empty or entirely NaN."""
    if series is None or len(series) == 0:
        return True, 'series is empty or missing'
    if series.isna().all():
        return True, 'all values are NaN'
    return False, ''


def check_zero_negative(series: pd.Series) -> Tuple[bool, str]:
    """Check for zero or negative prices."""
    valid = series.dropna()
    if valid.empty:
        return False, ''
    bad = valid[valid <= 0]
    if bad.empty:
        return False, ''
    return True, f'{len(bad)} days with price <= 0 (e.g. {bad.index[0].strftime("%Y-%m-%d")}: {bad.iloc[0]:.4f})'


def check_returns(series: pd.Series, threshold: float) -> Tuple[bool, str, int]:
    """Check for single-day absolute returns exceeding the threshold."""
    valid = series.dropna()
    if valid.empty or len(valid) < 2:
        return False, '', 0
    returns = valid.pct_change().dropna()
    if returns.empty:
        return False, '', 0
    bad = returns[returns.abs() > threshold]
    if bad.empty:
        return False, '', 0
    sample = bad.iloc[0]
    return True, (
        f'{len(bad)} days with abs return > {threshold:.0%} '
        f'(e.g. {bad.index[0].strftime("%Y-%m-%d")}: {sample:.2%})'
    ), len(bad)


def check_stale_prices(series: pd.Series, consecutive: int = 10) -> Tuple[bool, str]:
    """Check for prices that remain unchanged for more than `consecutive` days."""
    valid = series.dropna()
    if valid.empty or len(valid) < consecutive + 1:
        return False, ''
    # Count consecutive identical prices
    diffs = valid.diff().ne(0)
    # Group by consecutive runs of equal values
    groups = diffs.cumsum()
    run_lengths = groups.groupby(groups).size()
    max_run = run_lengths.max()
    if max_run <= consecutive:
        return False, ''
    # Find the run with the longest stale stretch
    stale_group = run_lengths.idxmax()
    first_date = valid[groups == stale_group].index[0]
    return True, f'{max_run} consecutive days with same price starting {first_date.strftime("%Y-%m-%d")}'


def evaluate_ticker(ticker: str, cache: DataCache, source: str, resolution: str,
                    start: Optional[str], end: Optional[str]) -> Dict[str, Any]:
    """Load a ticker and run all quality checks."""
    path = cache.get_path(ticker, source=source, adjustment='adjusted',
                           frequency=resolution)
    result = {
        'ticker': ticker,
        'path': path,
        'loaded': False,
        'records': 0,
        'issues': [],
    }

    try:
        data = cache.load(path, expected={'source': source, 'adjustment': 'adjusted'})
    except Exception as e:
        result['issues'].append((ISSUE_NAN_EMPTY, f'failed to load cache: {e}'))
        return result

    series = normalize_price_series(data)
    has_nan_empty, nan_detail = check_nan_empty(series)
    if has_nan_empty:
        result['issues'].append((ISSUE_NAN_EMPTY, nan_detail))
        return result

    result['loaded'] = True
    result['records'] = len(series)

    # Missing dates (based on NYSE calendar or inferred range)
    missing, missing_detail = check_missing_dates(series, start, end)
    if missing:
        result['issues'].append((ISSUE_MISSING_DATES, missing_detail))

    # Zero or negative prices
    zero_neg, zero_neg_detail = check_zero_negative(series)
    if zero_neg:
        result['issues'].append((ISSUE_ZERO_OR_NEGATIVE, zero_neg_detail))

    # Extreme returns (>30%)
    extreme, extreme_detail, _ = check_returns(series, threshold=0.30)
    if extreme:
        result['issues'].append((ISSUE_EXTREME_RETURN, extreme_detail))

    # Split/merger-like jumps (>50%)
    jump, jump_detail, _ = check_returns(series, threshold=0.50)
    if jump:
        result['issues'].append((ISSUE_SPLIT_MERGER_JUMP, jump_detail))

    # Stale prices (>10 consecutive days)
    stale, stale_detail = check_stale_prices(series, consecutive=10)
    if stale:
        result['issues'].append((ISSUE_STALE_PRICES, stale_detail))

    return result


def print_summary_table(results: List[Dict[str, Any]], issue_counts: Dict[str, int],
                        total: int, valid: int) -> None:
    """Print a concise summary table."""
    print('\n' + '=' * 70)
    print('DATA QUALITY VALIDATION SUMMARY')
    print('=' * 70)
    print(f'Total tickers checked:  {total}')
    print(f'Valid (no issues):      {valid}')
    print(f'With issues:            {total - valid}')
    print('-' * 70)
    print('Breakdown by issue type:')
    for key, label in ISSUE_LABELS.items():
        count = issue_counts.get(key, 0)
        print(f'  {label:45s} {count:>6d}')
    print('=' * 70)


def print_sample(results: List[Dict[str, Any]], sample_size: int = 20) -> None:
    """Print a sample of problematic tickers with issue details."""
    problematic = [r for r in results if r['issues']]
    if not problematic:
        print('No problematic tickers found.')
        return

    print(f'\nSample of problematic tickers (first {min(sample_size, len(problematic))}):')
    print('-' * 70)
    for r in problematic[:sample_size]:
        issue_summary = '; '.join(f'{ISSUE_LABELS[k]}: {v}' for k, v in r['issues'])
        print(f"  {r['ticker']:<6s} {issue_summary}")
    print('-' * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate data quality for the S&P 500 + NASDAQ-100 universe.')
    parser.add_argument('--start', default=None, help='Start date (YYYY-MM-DD); if omitted, inferred from data')
    parser.add_argument('--end', default=None, help='End date (YYYY-MM-DD); if omitted, inferred from data')
    parser.add_argument('--resolution', default='daily', help='Data resolution (default: daily)')
    parser.add_argument('--source', default='Yahoo', help='Data source (default: Yahoo)')
    parser.add_argument('--max-symbols', type=int, default=0,
                        help='Max symbols to check (default: 0 for all)')
    args = parser.parse_args()

    universe = load_universe()
    if args.max_symbols > 0:
        universe = universe[:args.max_symbols]

    print(f"Universe: {len(universe)} tickers (sp500 ∪ ndx100)")
    print(f"Source: {args.source} | Resolution: {args.resolution} | Adjustment: adjusted")
    print(f"Cache dir: {CACHE_DIR}")
    print(f"Date range: {args.start or '(inferred from data)'} -> {args.end or '(inferred from data)'}")
    print('-' * 70)

    cache = DataCache()
    results = []
    issue_counts = defaultdict(int)

    for i, ticker in enumerate(universe, start=1):
        result = evaluate_ticker(ticker, cache, args.source, args.resolution,
                                 args.start, args.end)
        results.append(result)
        for key, _ in result['issues']:
            issue_counts[key] += 1
        if i % 50 == 0 or i == len(universe):
            print(f'  ... checked {i}/{len(universe)} tickers')

    valid = sum(1 for r in results if not r['issues'])
    print_summary_table(results, issue_counts, total=len(universe), valid=valid)
    print_sample(results, sample_size=20)

    # Print a few tickers that could not be loaded at all
    not_loaded = [r for r in results if not r['loaded'] and not r['issues']]
    if not_loaded:
        print(f'\nNot loaded / no cache (first {min(10, len(not_loaded))}): ' +
              ', '.join(r['ticker'] for r in not_loaded[:10]))

    return 0 if valid == len(universe) else 1


if __name__ == '__main__':
    sys.exit(main())
