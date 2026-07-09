#!/usr/bin/env python3
"""
为所有策略添加日志功能的辅助脚本
使用方式: python3 add_logging.py
"""

import os
import re

# 需要添加日志的策略目录
STRATEGY_DIRS = [
    "/home/pc/.openclaw/workspace/quant/MyFirstStrategy",
    "/home/pc/.openclaw/workspace/quant/CombinedStrategy",
    "/home/pc/.openclaw/workspace/quant/MomentumStrategy",
    "/home/pc/.openclaw/workspace/quant/MeanReversionStrategy",
    "/home/pc/.openclaw/workspace/quant/MultiFactorStrategy",
    "/home/pc/.openclaw/workspace/quant/OptimizedStrategy",
    "/home/pc/.openclaw/workspace/quant/ProductionStrategy",
    "/home/pc/.openclaw/workspace/quant/RiskManagedStrategy",
]

# 日志辅助代码模板
LOG_HELPER_CODE = '''
    # === 日志方法 ===
    def _log(self, message):
        """统一日志记录"""
        self.log(message)
    
    def _log_trade(self, action, symbol, quantity, price, reason=""):
        """记录交易日志"""
        msg = f"[TRADE] {action} {symbol} | Qty: {quantity} | Price: ${price:.2f}"
        if reason:
            msg += f" | Reason: {reason}"
        self._log(msg)
    
    def _log_portfolio(self):
        """记录投资组合状态"""
        total = self.portfolio.total_portfolio_value
        cash = self.portfolio.cash
        positions = len([x for x in self.portfolio.values() if x.invested])
        self._log(f"[PORTFOLIO] Total: ${total:,.2f} | Cash: ${cash:,.2f} | Positions: {positions}")
    
    def on_end_of_algorithm(self):
        """算法结束时的总结"""
        self._log("=" * 60)
        self._log("策略运行结束")
        self._log("=" * 60)
        self._log_portfolio()
        total_return = (self.portfolio.total_portfolio_value - 100000) / 100000 * 100
        self._log(f"[SUMMARY] Total Return: {total_return:.2f}%")
        self._log(f"[SUMMARY] Final Equity: ${self.portfolio.total_portfolio_value:,.2f}")
'''

def add_logging_to_strategy(strategy_dir):
    """为单个策略添加日志功能"""
    main_file = os.path.join(strategy_dir, "main.py")
    
    if not os.path.exists(main_file):
        print(f"❌ 跳过: {strategy_dir}/main.py 不存在")
        return
    
    with open(main_file, 'r') as f:
        content = f.read()
    
    # 检查是否已经有 _log 方法
    if '_log(self, message)' in content:
        print(f"✅ 跳过: {strategy_dir} 已有日志功能")
        return
    
    # 检查是否有 on_end_of_algorithm 方法
    if 'def on_end_of_algorithm' in content:
        # 已经有结束方法，不需要添加
        pass
    else:
        # 在最后一个方法后面添加日志方法
        # 简单起见，在文件末尾添加
        content += '\n' + LOG_HELPER_CODE
    
    # 写入文件
    with open(main_file, 'w') as f:
        f.write(content)
    
    print(f"✅ 已添加日志: {strategy_dir}")

if __name__ == "__main__":
    print("开始为策略添加日志功能...\n")
    
    for strategy_dir in STRATEGY_DIRS:
        add_logging_to_strategy(strategy_dir)
    
    print("\n完成！")
    print("注意：FINAL_VERSION 和 MyFirstStrategy 已手动增强日志")
    print("其他策略已添加基础日志方法")
