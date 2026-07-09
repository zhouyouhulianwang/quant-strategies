#!/usr/bin/env python3
import os
import sys
import yfinance as yf
import pandas as pd
import zipfile

# 
LEAN_DATA_DIR = os.path.expanduser("~/.openclaw/workspace/quantconnect-projects/data")
TICKERS = ["AMD", "TSLA", "AMZN", "SPXL", "MSFT", "NVDA", "META", "GOOGL", "NFLX"]
START_DATE = "2015-01-01"
END_DATE = "2025-12-31"

def download_and_convert(ticker):
    """ Yahoo Finance  LEAN """
    print(f"  {ticker}...")
    
    try:
        # 
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        
        if df.empty:
            print(f"   ")
            return False
        
        #  LEAN   10000
        lean_df = pd.DataFrame()
        lean_df['date'] = df.index.strftime('%Y%m%d %H:%M')
        lean_df['open'] = (df['Open'].values * 10000).astype(int)
        lean_df['high'] = (df['High'].values * 10000).astype(int)
        lean_df['low'] = (df['Low'].values * 10000).astype(int)
        lean_df['close'] = (df['Close'].values * 10000).astype(int)
        lean_df['volume'] = df['Volume'].values.astype(int)
        
        #  zip LEAN 
        daily_dir = os.path.join(LEAN_DATA_DIR, "equity", "usa", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        
        zip_path = os.path.join(daily_dir, f"{ticker.lower()}.zip")
        csv_name = f"{ticker.lower()}.csv"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            csv_data = lean_df.to_csv(index=False, header=False).encode('utf-8')
            zf.writestr(csv_name, csv_data)
        
        print(f"   : {len(df)}   {zip_path}")
        return True
        
    except Exception as e:
        print(f"   : {e}")
        return False

# 
print("=" * 60)
print("Yahoo Finance  LEAN ")
print("=" * 60)

success = 0
for ticker in TICKERS:
    if download_and_convert(ticker):
        success += 1
    # 
    import time
    time.sleep(1)

print(f"\n: {success}/{len(TICKERS)} ")
