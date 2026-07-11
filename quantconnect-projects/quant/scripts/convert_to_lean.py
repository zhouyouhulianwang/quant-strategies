import pandas as pd
import zipfile
import os
from pathlib import Path

def convert_to_lean_format(csv_path, symbol='SPY', resolution='daily'):
    """将 yfinance CSV 转换为 Lean 格式"""
    
    # 读取 CSV，处理多层表头
    df = pd.read_csv(csv_path, header=[0,1])
    
    # 清理列名
    df.columns = ['Date', 'Close', 'High', 'Low', 'Open', 'Volume']
    
    # 删除表头行
    df = df[df['Date'] != 'Date'].copy()
    
    # 转换数据类型
    df['Date'] = pd.to_datetime(df['Date'])
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 删除 NaN 行
    df = df.dropna()
    
    # 按年分组
    df['Year'] = df['Date'].dt.year
    
    # Lean 数据目录
    lean_data_dir = Path('/home/pc/.openclaw/workspace/quant/data')
    
    if resolution == 'daily':
        # 日频数据: {data-folder}/equity/usa/daily/{symbol}.zip
        output_dir = lean_data_dir / 'equity' / 'usa' / 'daily'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = output_dir / f'{symbol.lower()}.zip'
        
        # Lean 格式: date,open,high,low,close,volume
        lean_df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].copy()
        lean_df['Date'] = lean_df['Date'].dt.strftime('%Y%m%d')
        lean_df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        
        # 保存为 zip
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            csv_content = lean_df.to_csv(index=False)
            zf.writestr(f'{symbol.lower()}.csv', csv_content)
        
        print(f"Created: {output_file}")
        print(f"Records: {len(lean_df)}")
        print(f"Date range: {lean_df['date'].min()} to {lean_df['date'].max()}")
        
    return output_file

if __name__ == '__main__':
    csv_path = '/home/pc/.openclaw/workspace/quant/data/spy_daily.csv'
    output = convert_to_lean_format(csv_path, 'SPY', 'daily')
    print(f"\nLean data ready at: {output}")
