# VIX 数据配置
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
