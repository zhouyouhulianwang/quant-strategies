#!/usr/bin/env python3
"""Check DataCache coverage for the S&P 500 + NASDAQ-100 universe.

Reads the universe from data/sp500_tickers.json and data/ndx100_tickers.json,
then checks whether a valid DataCache file exists for each ticker under
data_cache/ for the given source / adjustment / resolution.

Usage:
    python check_cache_coverage.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                                   [--resolution daily] [--source Yahoo]

Note: --start/--end are accepted for CLI compatibility; cache paths in this
project are date-range independent unless both are provided, so coverage is
checked against the canonical per-ticker cache file.
"""

import argparse
import glob
import json
import os
import sys

# Ensure the multifactor directory is importable when run from anywhere
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from data_source import DataCache, CACHE_DIR  # lightweight; no yfinance/QC imports


def load_universe():
    """Load union of S&P 500 and NASDAQ-100 tickers (uppercase, sorted)."""
    tickers = set()
    for name in ('sp500_tickers.json', 'ndx100_tickers.json'):
        path = os.path.join(SCRIPT_DIR, 'data', name)
        if not os.path.exists(path):
            print(f"[WARN] Universe file not found: {path}", file=sys.stderr)
            continue
        with open(path, 'r') as f:
            data = json.load(f)
        # Support both plain list ["AAPL", ...] and dict-of-lists / dict formats
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


def main():
    parser = argparse.ArgumentParser(description='Check DataCache coverage for the universe.')
    parser.add_argument('--start', default=None, help='Start date (YYYY-MM-DD), informational')
    parser.add_argument('--end', default=None, help='End date (YYYY-MM-DD), informational')
    parser.add_argument('--resolution', default='daily', help='Data resolution (default: daily)')
    parser.add_argument('--source', default='Yahoo', help='Data source (default: Yahoo)')
    args = parser.parse_args()

    universe = load_universe()
    total = len(universe)
    print(f"Universe: {total} tickers (sp500 ∪ ndx100)")
    if args.start or args.end:
        print(f"Requested range: {args.start or '...'} -> {args.end or '...'} "
              f"(cache paths are range-independent)")
    print(f"Source: {args.source} | Resolution: {args.resolution} | Adjustment: adjusted")
    print(f"Cache dir: {CACHE_DIR}")
    print('-' * 70)

    cache = DataCache()
    ttl_days = cache.frequency_ttl(args.resolution)

    covered = []
    missing = []
    for ticker in universe:
        path = cache.get_path(ticker, source=args.source,
                              adjustment='adjusted', frequency=args.resolution)
        if os.path.exists(path) and cache.is_valid(path, ttl_days=ttl_days):
            covered.append(ticker)
        else:
            missing.append(ticker)

    n_covered = len(covered)
    pct = (100.0 * n_covered / total) if total else 0.0

    print(f"Total universe:   {total}")
    print(f"Covered (valid):  {n_covered}")
    print(f"Missing/stale:    {len(missing)}")
    print(f"Coverage:         {pct:.1f}%")
    print(f"TTL used:         {ttl_days} day(s)")
    print('-' * 70)
    if missing:
        print(f"Missing sample (first {min(20, len(missing))}): "
              f"{', '.join(missing[:20])}")
    else:
        print("Missing sample: none — full coverage 🎉")

    # Count valid cache files present on disk for this source/resolution
    pattern = os.path.join(
        CACHE_DIR, f"*_{args.source}_adjusted_{args.resolution}.parquet")
    valid_on_disk = sum(
        1 for p in glob.glob(pattern)
        if cache.is_valid(p, ttl_days=ttl_days)
    )
    print('-' * 70)
    print(f"Valid cache files in data_cache/ for source={args.source}, "
          f"resolution={args.resolution}: {valid_on_disk}")
    print(f"SUMMARY: {n_covered}/{total} tickers covered ({pct:.1f}%) "
          f"for {args.source}/{args.resolution}; "
          f"{valid_on_disk} valid cache files on disk.")

    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
