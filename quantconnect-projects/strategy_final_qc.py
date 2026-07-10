from AlgorithmImports import *
import os
import json
class AdaptiveMomentumStrategy(QCAlgorithm):
    def Initialize(self):
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2026, 6, 30)  # 回测版：固定结束日期
        self.set_cash(100000)
        # 使用 Margin 账户，支持更大仓位灵活性
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        
        # ... (其余代码与当前版本相同)
