#!/usr/bin/env python3
"""
批量下载美股权重股数据到 LEAN 引擎
包含多维度数据：日线、行业ETF、避险资产
"""

import os
import sys
import yfinance as yf
import pandas as pd
import zipfile
import time

# 配置
LEAN_DATA_DIR = os.path.expanduser("~/.openclaw/workspace/quantconnect-projects/data")

# === 美股权重股列表 ===
# 按行业分类，确保覆盖各大板块

STOCKS = {
    # 科技巨头 (Magnificent 7)
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "GOOGL": "Alphabet",
    "META": "Meta",
    "AMZN": "Amazon",
    "TSLA": "Tesla",
    
    # 其他科技
    "AMD": "AMD",
    "INTC": "Intel",
    "CRM": "Salesforce",
    "ORCL": "Oracle",
    "ADBE": "Adobe",
    "CSCO": "Cisco",
    "AVGO": "Broadcom",
    "QCOM": "Qualcomm",
    "TXN": "Texas Instruments",
    "AMAT": "Applied Materials",
    "MU": "Micron",
    "NFLX": "Netflix",
    
    # 金融
    "JPM": "JPMorgan",
    "BAC": "Bank of America",
    "GS": "Goldman Sachs",
    "MS": "Morgan Stanley",
    "WFC": "Wells Fargo",
    "BLK": "BlackRock",
    
    # 消费
    "HD": "Home Depot",
    "COST": "Costco",
    "NKE": "Nike",
    "MCD": "McDonald's",
    "SBUX": "Starbucks",
    
    # 医药
    "JNJ": "Johnson & Johnson",
    "UNH": "UnitedHealth",
    "LLY": "Eli Lilly",
    "PFE": "Pfizer",
    "MRK": "Merck",
    "ABT": "Abbott",
    
    # 能源
    "XOM": "Exxon Mobil",
    "CVX": "Chevron",
    
    # 工业
    "BA": "Boeing",
    "CAT": "Caterpillar",
    "HON": "Honeywell",
    "UPS": "UPS",
    
    # 消费必需品
    "PG": "Procter & Gamble",
    "KO": "Coca-Cola",
    "PEP": "PepsiCo",
    "WMT": "Walmart",
    
    # 通信
    "VZ": "Verizon",
    
    # 杠杆ETF（高风险高收益）
    "SPXL": "Direxion Daily S&P 500 Bull 3X",
    "TQQQ": "ProShares UltraPro QQQ",
    "SSO": "ProShares Ultra S&P 500",
    
    # 指数ETF（基准）
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq-100 ETF",
    "IWM": "Russell 2000 ETF",
    
    # 避险资产
    "TLT": "20+ Year Treasury ETF",
    "GLD": "Gold ETF",
    "SLV": "Silver ETF",
    "VIXY": "VIX Short-Term Futures ETF",
}

START_DATE = "2015-01-01"
END_DATE = "2025-12-31"

def download_and_convert(ticker, name):
    """下载 Yahoo Finance 数据并转换为 LEAN 格式"""
    print(f"📥 {ticker:6s} ({name})...", end=" ")
    
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        
        if df.empty:
            print("❌ 无数据")
            return False
        
        # 转换为 LEAN 格式
        lean_df = pd.DataFrame()
        lean_df['date'] = df.index.strftime('%Y%m%d %H:%M')
        lean_df['open'] = (df['Open'].values * 10000).astype(int)
        lean_df['high'] = (df['High'].values * 10000).astype(int)
        lean_df['low'] = (df['Low'].values * 10000).astype(int)
        lean_df['close'] = (df['Close'].values * 10000).astype(int)
        lean_df['volume'] = df['Volume'].values.astype(int)
        
        # 保存为 zip
        daily_dir = os.path.join(LEAN_DATA_DIR, "equity", "usa", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        
        zip_path = os.path.join(daily_dir, f"{ticker.lower()}.zip")
        csv_name = f"{ticker.lower()}.csv"
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            csv_data = lean_df.to_csv(index=False, header=False).encode('utf-8')
            zf.writestr(csv_name, csv_data)
        
        print(f"✅ {len(df):4d} 条")
        return True
        
    except Exception as e:
        print(f"❌ 失败: {e}")
        return False

# 主程序
print("=" * 70)
print("批量下载美股权重股到 LEAN 引擎")
print("=" * 70)
print(f"目标目录: {LEAN_DATA_DIR}")
print(f"数据范围: {START_DATE} ~ {END_DATE}")
print(f"股票数量: {len(STOCKS)}")
print("=" * 70)

success = 0
failed = []

for ticker, name in STOCKS.items():
    if download_and_convert(ticker, name):
        success += 1
    else:
        failed.append(ticker)
    time.sleep(0.5)  # 避免被封

print("=" * 70)
print(f"导入完成: {success}/{len(STOCKS)} 成功")
if failed:
    print(f"失败股票: {', '.join(failed)}")
print("=" * 70)
