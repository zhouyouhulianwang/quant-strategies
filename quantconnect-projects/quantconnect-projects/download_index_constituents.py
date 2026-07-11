#!/usr/bin/env python3
"""
下载 S&P 500 + Nasdaq 100 + Dow Jones 30 全部成分股到 LEAN 引擎
"""

import os
import sys
import time
import pandas as pd
import yfinance as yf
import zipfile
import requests
from io import StringIO

LEAN_DATA_DIR = os.path.expanduser("~/.openclaw/workspace/quantconnect-projects/data")

def get_sp500_tickers():
    """从维基百科获取S&P 500成分股"""
    print("📊 获取 S&P 500 成分股列表...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        response = requests.get(url, headers=headers, timeout=30)
        tables = pd.read_html(StringIO(response.text))
        df = tables[0]
        tickers = df['Symbol'].tolist()
        print(f"  ✅ 获取成功: {len(tickers)} 只股票")
        return tickers
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return []

def get_nasdaq100_tickers():
    """从维基百科获取Nasdaq 100成分股"""
    print("📊 获取 Nasdaq 100 成分股列表...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        response = requests.get(url, headers=headers, timeout=30)
        tables = pd.read_html(StringIO(response.text))
        for table in tables:
            if 'Ticker' in table.columns or 'Symbol' in table.columns:
                col = 'Ticker' if 'Ticker' in table.columns else 'Symbol'
                tickers = table[col].tolist()
                print(f"  ✅ 获取成功: {len(tickers)} 只股票")
                return tickers
        print("  ⚠️ 未找到成分股表格")
        return []
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return []

def get_dow30_tickers():
    """从维基百科获取Dow Jones 30成分股"""
    print("📊 获取 Dow Jones 30 成分股列表...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        url = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"
        response = requests.get(url, headers=headers, timeout=30)
        tables = pd.read_html(StringIO(response.text))
        for table in tables:
            if 'Symbol' in table.columns:
                tickers = table['Symbol'].tolist()
                print(f"  ✅ 获取成功: {len(tickers)} 只股票")
                return tickers
        print("  ⚠️ 未找到成分股表格")
        return []
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return []

def download_stock(ticker, start="2015-01-01", end="2025-12-31"):
    """下载单只股票并转换为LEAN格式"""
    try:
        df = yf.download(ticker, start=start, end=end, progress=False)
        if df.empty:
            return False, "无数据"
        
        lean_df = pd.DataFrame()
        lean_df['date'] = df.index.strftime('%Y%m%d %H:%M')
        lean_df['open'] = (df['Open'].values * 10000).astype(int)
        lean_df['high'] = (df['High'].values * 10000).astype(int)
        lean_df['low'] = (df['Low'].values * 10000).astype(int)
        lean_df['close'] = (df['Close'].values * 10000).astype(int)
        lean_df['volume'] = df['Volume'].values.astype(int)
        
        daily_dir = os.path.join(LEAN_DATA_DIR, "equity", "usa", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        
        zip_path = os.path.join(daily_dir, f"{ticker.lower()}.zip")
        csv_name = f"{ticker.lower()}.csv"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            csv_data = lean_df.to_csv(index=False, header=False).encode('utf-8')
            zf.writestr(csv_name, csv_data)
        
        return True, len(df)
    except Exception as e:
        return False, str(e)

def main():
    print("=" * 70)
    print("S&P 500 + Nasdaq 100 + Dow 30 成分股批量下载")
    print("=" * 70)
    
    # 获取成分股列表
    sp500 = get_sp500_tickers()
    nasdaq100 = get_nasdaq100_tickers()
    dow30 = get_dow30_tickers()
    
    # 合并并去重
    all_tickers = list(set(sp500 + nasdaq100 + dow30))
    # 过滤掉特殊字符
    all_tickers = [t for t in all_tickers if isinstance(t, str) and t.isalpha()]
    all_tickers.sort()
    
    print(f"\n📈 总计去重后: {len(all_tickers)} 只股票")
    print(f"  - S&P 500: {len(sp500)} 只")
    print(f"  - Nasdaq 100: {len(nasdaq100)} 只")
    print(f"  - Dow 30: {len(dow30)} 只")
    print()
    
    # 检查已下载的股票
    daily_dir = os.path.join(LEAN_DATA_DIR, "equity", "usa", "daily")
    existing = set()
    if os.path.exists(daily_dir):
        for f in os.listdir(daily_dir):
            if f.endswith('.zip'):
                existing.add(f.replace('.zip', '').upper())
    
    # 过滤掉已下载的
    to_download = [t for t in all_tickers if t.upper() not in existing]
    print(f"💾 已存在: {len(existing)} 只")
    print(f"📥 需下载: {len(to_download)} 只")
    print()
    
    if not to_download:
        print("✅ 所有数据已存在，无需下载！")
        return
    
    # 批量下载
    success = 0
    failed = []
    
    for i, ticker in enumerate(to_download, 1):
        print(f"[{i}/{len(to_download)}] {ticker}...", end=" ")
        ok, result = download_stock(ticker)
        if ok:
            print(f"✅ {result}条")
            success += 1
        else:
            print(f"❌ {result}")
            failed.append(ticker)
        
        # 每10只暂停一下，避免被封
        if i % 10 == 0:
            print(f"  ⏸️  暂停 2 秒...")
            time.sleep(2)
    
    print()
    print("=" * 70)
    print(f"下载完成: {success}/{len(to_download)} 成功")
    if failed:
        print(f"失败: {len(failed)} 只 - {', '.join(failed[:20])}")
    print("=" * 70)
    
    # 统计总数
    total_existing = len(existing) + success
    print(f"\n📊 本地数据总量: {total_existing} 只股票")

if __name__ == "__main__":
    main()
