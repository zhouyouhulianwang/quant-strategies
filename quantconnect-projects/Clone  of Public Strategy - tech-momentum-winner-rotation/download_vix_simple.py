#!/usr/bin/env python3
"""
VIX 现货数据下载脚本 - 修复版
将真实 VIX 指数数据导入 LEAN 本地回测
"""

import yfinance as yf
import pandas as pd
import zipfile
import os

def download_vix():
    print("="*60)
    print("VIX 数据下载")
    print("="*60)
    
    # 下载 VIX 数据
    print("\n下载 ^VIX 数据...")
    df = yf.download("^VIX", start="2015-01-01", end="2025-12-31", progress=False)
    
    print(f"✅ 下载成功: {len(df)} 条")
    
    # 处理 MultiIndex 列
    if isinstance(df.columns, pd.MultiIndex):
        close_col = ('Close', '^VIX')
        high_col = ('High', '^VIX')
        low_col = ('Low', '^VIX')
        open_col = ('Open', '^VIX')
    else:
        close_col = 'Close'
        high_col = 'High'
        low_col = 'Low'
        open_col = 'Open'
    
    # 创建 LEAN 格式
    lean = pd.DataFrame()
    lean['date'] = df.index.strftime('%Y%m%d %H:%M')
    lean['open'] = (df[open_col] * 10000).astype(int).values
    lean['high'] = (df[high_col] * 10000).astype(int).values
    lean['low'] = (df[low_col] * 10000).astype(int).values
    lean['close'] = (df[close_col] * 10000).astype(int).values
    lean['volume'] = 0
    
    # 保存
    base_dir = os.path.expanduser(
        "~/.openclaw/workspace/quantconnect-projects/"
        "Clone  of Public Strategy - tech-momentum-winner-rotation"
    )
    data_dir = os.path.join(base_dir, "data", "vix")
    os.makedirs(data_dir, exist_ok=True)
    
    csv_path = os.path.join(data_dir, 'vix.csv')
    zip_path = os.path.join(data_dir, 'vix.zip')
    
    lean.to_csv(csv_path, header=False, index=False)
    
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(csv_path, 'vix.csv')
    
    os.remove(csv_path)
    
    print(f"\n✅ 保存成功:")
    print(f"   路径: {zip_path}")
    print(f"   大小: {os.path.getsize(zip_path)} bytes")
    print(f"\n数据样本:")
    print(lean.head(3).to_string())
    
    return lean

if __name__ == "__main__":
    download_vix()
