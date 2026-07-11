#!/usr/bin/env python3
"""Download missing equity data from Yahoo Finance and convert to Lean format."""

import json
import os
import zipfile
import io
from datetime import datetime, timedelta
import time

import yfinance as yf

# Config paths
CONFIG_FILE = "/home/pc/.openclaw/workspace/quantconnect-projects/strategy_config.json"
DATA_DIR = "/home/pc/.openclaw/workspace/quantconnect-projects/data/equity/usa/daily"

START_DATE = "2015-01-01"
END_DATE = "2026-06-30"

def yf_ticker(ticker: str) -> str:
    """Map ticker to Yahoo Finance format."""
    # BRK.B -> BRK-B in yfinance
    if ticker == "BRK.B":
        return "BRK-B"
    return ticker

def to_lean_csv(df) -> str:
    """Convert DataFrame to Lean CSV format."""
    lines = []
    for date, row in df.iterrows():
        date_str = date.strftime("%Y%m%d 00:00")
        o = int(round(row["Open"] * 10000))
        h = int(round(row["High"] * 10000))
        l = int(round(row["Low"] * 10000))
        c = int(round(row["Close"] * 10000))
        v = int(row["Volume"])
        lines.append(f"{date_str},{o},{h},{l},{c},{v}")
    return "\n".join(lines) + "\n"

def download_ticker(ticker: str):
    """Download and save a single ticker."""
    yf_t = yf_ticker(ticker)
    zip_path = os.path.join(DATA_DIR, f"{ticker.lower()}.zip")

    if os.path.exists(zip_path):
        print(f"  [{ticker}] already exists, skipping")
        return True

    try:
        print(f"  Downloading {ticker} (yf: {yf_t})...")
        df = yf.download(
            yf_t,
            start=START_DATE,
            end=END_DATE,
            progress=False,
            auto_adjust=False,
        )
        if df.empty:
            print(f"  [{ticker}] no data returned")
            return False

        # Handle multi-index column names from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if c[1] == yf_t else c[0] for c in df.columns]

        # Drop rows with NaN
        df = df.dropna()
        if df.empty:
            print(f"  [{ticker}] empty after dropna")
            return False

        csv_content = to_lean_csv(df)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{ticker.lower()}.csv", csv_content)

        print(f"  [{ticker}] saved {len(df)} rows")
        return True

    except Exception as e:
        print(f"  [{ticker}] ERROR: {e}")
        return False

if __name__ == "__main__":
    import pandas as pd

    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    tickers = list(config["sector_map"].keys())

    existing = set()
    for f in os.listdir(DATA_DIR):
        if f.endswith('.zip'):
            existing.add(f.replace('.zip', '').upper())

    missing = [t for t in tickers if t not in existing]
    print(f"Total tickers in config: {len(tickers)}")
    print(f"Existing data: {len(existing)}")
    print(f"Missing data: {len(missing)}")
    print(f"Missing: {missing}")
    print()

    success = 0
    fail = 0
    for i, ticker in enumerate(missing, 1):
        print(f"[{i}/{len(missing)}] {ticker}")
        if download_ticker(ticker):
            success += 1
        else:
            fail += 1
        time.sleep(0.5)  # rate limit

    print(f"\nDone: {success} success, {fail} failed")
