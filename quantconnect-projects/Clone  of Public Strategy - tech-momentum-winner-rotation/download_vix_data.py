#!/usr/bin/env python3
"""
VIX 现货数据下载脚本
将真实 VIX 指数数据导入 LEAN 本地回测

数据来源: Yahoo Finance (^VIX)
"""

import yfinance as yf
import pandas as pd
import zipfile
import os
from datetime import datetime

def download_vix_data(start_date="2015-01-01", end_date="2025-12-31"):
    """
    下载 VIX 历史数据
    
    注意: Yahoo Finance 的 ^VIX 是 VIX 指数，不是可交易资产
    但可以作为只读数据使用
    """
    print(f"正在下载 VIX 数据 ({start_date} ~ {end_date})...")
    
    try:
        # 下载 VIX 数据 (^VIX)
        vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)
        
        if len(vix) == 0:
            print("❌ 无法下载 VIX 数据")
            return None
            
        print(f"✅ 下载成功: {len(vix)} 条记录")
        print(f"   日期范围: {vix.index[0]} ~ {vix.index[-1]}")
        print(f"   VIX 范围: {vix['Close'].min().iloc[0]:.2f} ~ {vix['Close'].max().iloc[0]:.2f}")
        
        return vix
        
    except Exception as e:
        print(f"❌ 下载错误: {e}")
        return None

def convert_to_lean_format(vix_data):
    """
    将 VIX 数据转换为 LEAN 格式
    
    LEAN 格式要求:
    - 日期格式: yyyyMMdd HH:mm
    - 价格格式: 整数 (价格 × 10000)
    - 文件格式: ZIP 压缩的 CSV
    """
    print("\n正在转换为 LEAN 格式...")
    
    # 创建 LEAN 格式数据框
    lean_data = pd.DataFrame()
    lean_data['date'] = vix_data.index.strftime('%Y%m%d %H:%M')
    
    # VIX 是指数，价格直接使用（不乘10000，因为VIX本身是小数值）
    # 但为了统一格式，我们仍然乘10000
    lean_data['open'] = (vix_data['Open'].fillna(0) * 10000).astype(int)
    lean_data['high'] = (vix_data['High'].fillna(0) * 10000).astype(int)
    lean_data['low'] = (vix_data['Low'].fillna(0) * 10000).astype(int)
    lean_data['close'] = (vix_data['Close'].fillna(0) * 10000).astype(int)
    lean_data['volume'] = 0  # VIX 指数无成交量
    
    # 删除所有价格为0的行（缺失数据）
    lean_data = lean_data[lean_data['close'] > 0]
    
    print("✅ 转换完成")
    print(f"   样本: {lean_data.head(3).to_string()}")
    
    return lean_data

def save_lean_data(lean_data, output_dir):
    """
    保存为 LEAN 格式文件
    """
    # 确保目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存 CSV
    csv_path = os.path.join(output_dir, 'vix.csv')
    lean_data.to_csv(csv_path, header=False, index=False)
    
    # 打包 ZIP
    zip_path = os.path.join(output_dir, 'vix.zip')
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(csv_path, 'vix.csv')
    
    # 删除临时 CSV
    os.remove(csv_path)
    
    print(f"\n✅ 保存完成:")
    print(f"   ZIP 文件: {zip_path}")
    print(f"   文件大小: {os.path.getsize(zip_path)} bytes")
    
    return zip_path

def create_lean_config(project_dir):
    """
    创建 LEAN 配置文件，让策略使用 VIX 数据
    """
    config_content = """# VIX 数据配置
# 将此文件内容添加到 main.py 的 Initialize 方法中

# 方法1: 使用自定义数据（推荐）
class VIXData(PythonData):
    def GetSource(self, config, date, isLiveMode):
        return SubscriptionDataSource(
            f"data/vix/vix.zip",
            SubscriptionTransportMedium.LocalFile
        )
    
    def Reader(self, config, line, date, isLiveMode):
        data = VIXData()
        data.Symbol = config.Symbol
        
        # 解析 CSV 格式: date,open,high,low,close,volume
        parts = line.split(',')
        if len(parts) < 5:
            return None
            
        data.Time = datetime.strptime(parts[0], '%Y%m%d %H:%M')
        data.Open = float(parts[1]) / 10000
        data.High = float(parts[2]) / 10000
        data.Low = float(parts[3]) / 10000
        data.Close = float(parts[4]) / 10000
        data.Value = data.Close
        
        return data

# 在 Initialize 中使用:
# self.vix_symbol = self.AddData(VIXData, "VIX", Resolution.Daily).Symbol
"""
    
    config_path = os.path.join(project_dir, 'vix_config.py')
    with open(config_path, 'w') as f:
        f.write(config_content)
    
    print(f"\n✅ 配置文件已保存: {config_path}")

def main():
    """
    主函数
    """
    print("="*60)
    print("VIX 数据下载工具")
    print("="*60)
    
    # 下载数据
    vix_data = download_vix_data()
    
    if vix_data is None:
        print("\n❌ 下载失败，退出")
        return
    
    # 转换为 LEAN 格式
    lean_data = convert_to_lean_format(vix_data)
    
    # 保存路径
    project_dir = os.path.expanduser(
        "~/.openclaw/workspace/quantconnect-projects/"
        "Clone  of Public Strategy - tech-momentum-winner-rotation"
    )
    data_dir = os.path.join(project_dir, "data", "vix")
    
    # 保存数据
    zip_path = save_lean_data(lean_data, data_dir)
    
    # 创建配置
    create_lean_config(project_dir)
    
    # 使用说明
    print("\n" + "="*60)
    print("使用说明")
    print("="*60)
    print("""
1. 数据已保存到:
   data/vix/vix.zip

2. 修改 main.py 的 Initialize 方法:
   
   # 添加自定义数据读取
   self.vix_symbol = self.AddData(VIXData, "VIX", Resolution.Daily).Symbol
   
   # 或者简单方式（推荐）:
   # 直接读取 VIX 数据文件
   vix_data = self.History("VIX", 30, Resolution.Daily)
   if len(vix_data) > 0:
       current_vix = vix_data['close'][-1]
   else:
       current_vix = 20  # 默认值

3. 修改阈值（基于真实 VIX）:
   self.vix_high = 25.0   # 原 VIXY: 30
   self.vix_low = 15.0    # 原 VIXY: 18

4. 注意:
   - VIX 是指数，不能交易
   - 只能作为只读风控指标
   - 真实 VIX 通常比 VIXY 高 15-20%

5. 验证:
   运行回测，检查日志中的 VIX 值是否正常（10-50范围）
""")

if __name__ == "__main__":
    main()
