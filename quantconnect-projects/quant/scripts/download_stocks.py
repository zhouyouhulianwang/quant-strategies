#!/usr/bin/env python3
"""
下载更多历史数据用于回测
使用 yfinance（免费数据源）
"""

import yfinance as yf
import pandas as pd
import os
from datetime import datetime, timedelta

def download_stock_data(symbol, start_date, end_date, output_dir):
    """下载单只股票数据并保存为 Lean 格式"""
    try:
        print(f"下载 {symbol}...")
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date)
        
        if df.empty:
            print(f"  ⚠️ {symbol} 无数据")
            return False
        
        # 转换为 Lean 格式
        df = df.reset_index()
        df['Date'] = df['Date'].dt.strftime('%Y%m%d %H:%M')
        
        # 价格转换为整数 (×10000)
        for col in ['Open', 'High', 'Low', 'Close']:
            df[col] = (df[col] * 10000).astype(int)
        
        df['Volume'] = df['Volume'].astype(int)
        
        # 重命名列
        df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
        
        # 保存为 CSV
        output_file = os.path.join(output_dir, f"{symbol.lower()}.csv")
        df.to_csv(output_file, index=False, header=False)
        
        print(f"  ✅ {symbol}: {len(df)} 条记录")
        return True
        
    except Exception as e:
        print(f"  ❌ {symbol} 错误: {e}")
        return False

def main():
    # 数据目录
    data_dir = "/home/pc/.openclaw/workspace/quant/data/equity/usa/daily"
    os.makedirs(data_dir, exist_ok=True)
    
    # 下载参数
    end_date = datetime.now()
    start_date = end_date - timedelta(days=10*365)  # 10年历史
    
    # 要下载的股票列表
    symbols = [
        # 科技股
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'NFLX', 'AMD', 'INTC',
        # 金融股
        'JPM', 'BAC', 'WFC', 'GS', 'MS', 'C', 'BLK',
        # 医疗股
        'JNJ', 'PFE', 'UNH', 'ABBV', 'MRK', 'LLY', 'TMO',
        # 消费股
        'PG', 'KO', 'PEP', 'WMT', 'COST', 'HD', 'NKE', 'SBUX', 'MCD',
        # 工业股
        'BA', 'CAT', 'GE', 'HON', 'UPS', 'RTX',
        # 能源股
        'XOM', 'CVX', 'COP', 'EOG',
        # ETF
        'SPY', 'QQQ', 'IWM', 'VTI', 'VOO', 'VEA', 'VWO', 'BND', 'TLT', 'GLD', 'SLV',
        # 其他
        'DIS', 'V', 'MA', 'PYPL', 'ADBE', 'CRM', 'CSCO', 'IBM', 'ORCL', 'INTU'
    ]
    
    print(f"=== 下载历史数据 ===")
    print(f"时间范围: {start_date.date()} 到 {end_date.date()}")
    print(f"股票数量: {len(symbols)}")
    print("")
    
    success_count = 0
    for symbol in symbols:
        if download_stock_data(symbol, start_date, end_date, data_dir):
            success_count += 1
    
    print("")
    print(f"=== 下载完成 ===")
    print(f"成功: {success_count}/{len(symbols)}")
    print(f"数据目录: {data_dir}")

if __name__ == "__main__":
    main()
