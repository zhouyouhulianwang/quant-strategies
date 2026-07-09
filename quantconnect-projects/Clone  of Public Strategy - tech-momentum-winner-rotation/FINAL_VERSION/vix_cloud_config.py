# 云端版 VIX 期货配置 - 用于 QuantConnect 云端部署
# 将此代码片段替换 main.py 中的 VIX 相关部分

# === 文件顶部添加导入 ===
from AlgorithmImports import *

class AdaptiveMomentumStrategyCloud(QCAlgorithm):
    def Initialize(self):
        # ... 其他初始化代码 ...
        
        # === VIX 配置（云端版）===
        self.use_vix_future = True  # True=使用VIX期货, False=使用VIXY
        
        if self.use_vix_future:
            # 方法1: VIX 期货（推荐，更准确）
            self.vix_future = self.AddFuture(Futures.Indices.VIX)
            self.vix_future.SetFilter(timedelta(0), timedelta(90))  # 近月合约
            self.vix_symbol = self.vix_future.Symbol
            self.Debug("✅ 使用 VIX 期货（云端模式）")
        else:
            # 方法2: VIXY ETF（本地回测用）
            self.vix_symbol = self.AddEquity("VIXY").Symbol
            self.Debug("⚠️ 使用 VIXY ETF（本地模式）")
        
        # === VIX 阈值（根据数据源调整）===
        if self.use_vix_future:
            # VIX 期货阈值（VIX 通常比 VIXY 高 15-20%）
            self.vix_high = 25.0   # 相当于 VIXY 的 30
            self.vix_low = 15.0    # 相当于 VIXY 的 18
            self.vol_high = 0.020  # 波动率阈值（VIX期货更敏感）
        else:
            # VIXY 阈值（当前使用）
            self.vix_high = 30.0
            self.vix_low = 18.0
            self.vol_high = 0.025
    
    def GetVIX(self):
        """获取当前 VIX 值"""
        if self.use_vix_future:
            # VIX 期货：直接读取
            # 注意：期货价格通常略高于现货VIX
            future_price = self.Securities[self.vix_symbol].Price
            # 简单估算：近月期货 ≈ 现货 VIX + 0.5-2.0
            vix_estimated = future_price - 1.0  # 减去基差估算
            return max(vix_estimated, 5.0)  # 最低5防止异常
        else:
            # VIXY：估算真实 VIX
            vixy_price = self.Securities[self.vix_symbol].Price
            # VIXY 通常 = VIX × 0.85
            vix_estimated = vixy_price / 0.85
            return vix_estimated
    
    def CheckVIXFilter(self):
        """VIX 风控检查"""
        try:
            vix = self.GetVIX()
            
            if vix > self.vix_high:
                # 高波动：降低仓位
                scale = 0.5
                self.Debug(f"⚠️ VIX={vix:.1f}>{self.vix_high}，仓位降至{scale:.0%}")
                return scale
            elif vix < self.vix_low:
                # 低波动：正常仓位
                self.Debug(f"✅ VIX={vix:.1f}<{self.vix_low}，仓位正常")
                return 1.0
            else:
                # 中等波动
                return 1.0
                
        except Exception as e:
            self.Debug(f"VIX检查错误: {e}")
            return 1.0

# === 使用说明 ===
"""
云端部署步骤：

1. 在 QuantConnect 云端创建项目
2. 粘贴此代码片段到 main.py
3. 设置 use_vix_future = True
4. 确保有 VIX 期货数据订阅（QuantConnect免费提供）

本地回测步骤：

1. 保持 use_vix_future = False
2. 继续使用 VIXY 数据
3. 阈值自动适配

阈值对照表：
┌──────────────┬──────────┬────────────┐
│   市场环境   │ VIX阈值  │ VIXY阈值   │
├──────────────┼──────────┼────────────┤
│ 高波动(减仓) │   25     │    30      │
│ 低波动(正常) │   15     │    18      │
│ 恐慌(清仓)   │   35     │    40      │
└──────────────┴──────────┴────────────┘
"""
