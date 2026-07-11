#!/usr/bin/env python3
"""
将 CSV 数据转换为 Lean 格式 (ZIP)
"""

import os
import zipfile
from pathlib import Path

def convert_to_lean_format(csv_dir):
    """将 CSV 文件转换为 Lean ZIP 格式"""
    
    print("=== 转换数据为 Lean 格式 ===")
    
    csv_files = list(Path(csv_dir).glob("*.csv"))
    print(f"找到 {len(csv_files)} 个 CSV 文件")
    
    for csv_file in csv_files:
        symbol = csv_file.stem.upper()
        zip_file = csv_file.with_suffix('.zip')
        
        # 创建 ZIP 文件
        with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(csv_file, csv_file.name)
        
        # 删除原始 CSV
        csv_file.unlink()
        
        print(f"  ✅ {symbol}: {zip_file.stat().st_size / 1024:.1f} KB")
    
    print(f"\n=== 转换完成 ===")

def main():
    data_dir = "/home/pc/.openclaw/workspace/quant/data/equity/usa/daily"
    convert_to_lean_format(data_dir)
    
    # 显示最终统计
    zip_files = list(Path(data_dir).glob("*.zip"))
    print(f"\n总计: {len(zip_files)} 个 ZIP 文件")
    
    total_size = sum(f.stat().st_size for f in zip_files)
    print(f"总大小: {total_size / (1024*1024):.1f} MB")

if __name__ == "__main__":
    main()
