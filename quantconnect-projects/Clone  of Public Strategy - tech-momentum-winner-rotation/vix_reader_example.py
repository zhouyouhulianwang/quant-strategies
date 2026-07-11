"""
VIX 数据读取示例
在 main.py 中使用真实 VIX 现货数据
"""

from AlgorithmImports import *

class VIXReaderExample(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2022, 1, 1)
        self.SetEndDate(2025, 6, 1)
        
        # === 方法1: 使用自定义数据类（推荐）===
        self.vix_symbol = self.AddData(VIXData, "VIX", Resolution.Daily).Symbol
        
        # VIX 阈值（基于真实 VIX）
        self.vix_high = 25.0   # 高波动（减仓）
        self.vix_low = 15.0    # 低波动（正常）
        
        # 每日检查
        self.Schedule.On(
            self.DateRules.EveryDay("SPY"),
            self.TimeRules.AfterMarketOpen("SPY", 5),
            self.CheckVIX
        )
    
    def CheckVIX(self):
        """读取 VIX 并调整仓位"""
        # 获取 VIX 数据
        vix_data = self.History(self.vix_symbol, 5, Resolution.Daily)
        
        if len(vix_data) == 0:
            self.Debug("⚠️ 无 VIX 数据")
            return
        
        # 读取最新 VIX 值（注意：LEAN 数据是整数，需除以 10000）
        vix_raw = vix_data['close'].iloc[-1]
        vix = vix_raw / 10000.0
        
        self.Debug(f"📊 VIX = {vix:.2f}")
        
        # 风控逻辑
        if vix > self.vix_high:
            self.Debug(f"⚠️ 高波动! VIX={vix:.1f} > {self.vix_high}")
            # 降低仓位...
        elif vix < self.vix_low:
            self.Debug(f"✅ 低波动! VIX={vix:.1f} < {self.vix_low}")
            # 正常仓位...

class VIXData(PythonData):
    """
    VIX 自定义数据类
    读取 data/vix/vix.zip 文件
    """
    def GetSource(self, config, date, isLiveMode):
        return SubscriptionDataSource(
            f"data/vix/vix.zip",
            SubscriptionTransportMedium.LocalFile
        )
    
    def Reader(self, config, line, date, isLiveMode):
        data = VIXData()
        data.Symbol = config.Symbol
        
        # CSV 格式: date,open,high,low,close,volume
        parts = line.split(',')
        if len(parts) < 5:
            return None
        
        try:
            data.Time = datetime.strptime(parts[0], '%Y%m%d %H:%M')
            data.Open = float(parts[1]) / 10000
            data.High = float(parts[2]) / 10000
            data.Low = float(parts[3]) / 10000
            data.Close = float(parts[4]) / 10000
            data.Value = data.Close
            data.Volume = 0
        except:
            return None
        
        return data

"""
使用说明:

1. 数据准备:
   python3 download_vix_simple.py
   
   这会下载真实 VIX 数据到 data/vix/vix.zip

2. 在策略中使用:
   - 复制上面的 VIXData 类到 main.py
   - 在 Initialize 中添加: self.AddData(VIXData, "VIX", Resolution.Daily)
   - 读取时使用: self.History("VIX", 30, Resolution.Daily)

3. 阈值调整（基于真实 VIX）:
   高波动: VIX > 25  (原 VIXY: >30)
   低波动: VIX < 15  (原 VIXY: <18)
   
   原因: 真实 VIX 通常比 VIXY 高 15-20%

4. 验证:
   运行回测，检查日志输出:
   "📊 VIX = 18.02" (正常范围 10-50)
"""
