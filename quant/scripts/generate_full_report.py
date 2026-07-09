import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path
import numpy as np

def generate_full_report():
    """生成完整策略对比报告和可视化"""
    
    # 所有策略数据
    strategies = {
        '原始趋势': {'dir': 'MyFirstStrategy/backtests/2026-07-07_11-13-49', 'color': 'blue'},
        '优化趋势': {'dir': 'OptimizedStrategy/backtests/2026-07-07_11-20-59', 'color': 'cyan'},
        '动量突破': {'dir': 'MomentumStrategy/backtests', 'color': 'green'},
        '多因子': {'dir': 'MultiFactorStrategy/backtests', 'color': 'purple'},
        '组合策略': {'dir': 'CombinedStrategy/backtests', 'color': 'orange'},
        '风险管理': {'dir': 'RiskManagedStrategy/backtests', 'color': 'red'},
    }
    
    fig = plt.figure(figsize=(16, 20))
    
    # 1. 权益曲线对比
    ax1 = plt.subplot(4, 2, 1)
    for name, info in strategies.items():
        backtest_dir = Path('/home/pc/.openclaw/workspace/quant') / info['dir']
        if backtest_dir.is_dir():
            # 找到最新的回测目录
            subdirs = [d for d in backtest_dir.iterdir() if d.is_dir()]
            if subdirs:
                latest = max(subdirs, key=lambda x: x.stat().st_mtime)
                json_files = list(latest.glob('*-summary.json'))
                if json_files:
                    with open(json_files[0]) as f:
                        data = json.load(f)
                    if 'charts' in data and 'Strategy Equity' in data['charts']:
                        equity_data = data['charts']['Strategy Equity']['series']['Equity']['values']
                        dates = [datetime.fromtimestamp(item[0]) for item in equity_data]
                        equities = [item[3] for item in equity_data]
                        ax1.plot(dates, equities, label=name, color=info['color'], linewidth=1.5)
    
    ax1.axhline(y=100000, color='black', linestyle='--', alpha=0.3, label='Initial')
    ax1.set_title('Equity Curve Comparison', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Portfolio Value ($)')
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    
    # 2. 回撤对比
    ax2 = plt.subplot(4, 2, 2)
    for name, info in strategies.items():
        backtest_dir = Path('/home/pc/.openclaw/workspace/quant') / info['dir']
        if backtest_dir.is_dir():
            subdirs = [d for d in backtest_dir.iterdir() if d.is_dir()]
            if subdirs:
                latest = max(subdirs, key=lambda x: x.stat().st_mtime)
                json_files = list(latest.glob('*-summary.json'))
                if json_files:
                    with open(json_files[0]) as f:
                        data = json.load(f)
                    if 'charts' in data and 'Strategy Equity' in data['charts']:
                        equity_data = data['charts']['Strategy Equity']['series']['Equity']['values']
                        dates = [datetime.fromtimestamp(item[0]) for item in equity_data]
                        equities = [item[3] for item in equity_data]
                        
                        peak = equities[0]
                        drawdowns = []
                        for eq in equities:
                            if eq > peak:
                                peak = eq
                            drawdowns.append((eq - peak) / peak * 100)
                        
                        ax2.plot(dates, drawdowns, label=name, color=info['color'], linewidth=1)
                        ax2.fill_between(dates, drawdowns, 0, alpha=0.1, color=info['color'])
    
    ax2.set_title('Drawdown Comparison', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Date')
    ax2.set_ylabel('Drawdown (%)')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    
    # 3. 收益 vs 风险散点图
    ax3 = plt.subplot(4, 2, 3)
    
    strategy_stats = []
    for name, info in strategies.items():
        backtest_dir = Path('/home/pc/.openclaw/workspace/quant') / info['dir']
        if backtest_dir.is_dir():
            subdirs = [d for d in backtest_dir.iterdir() if d.is_dir()]
            if subdirs:
                latest = max(subdirs, key=lambda x: x.stat().st_mtime)
                json_files = list(latest.glob('*-summary.json'))
                if json_files:
                    with open(json_files[0]) as f:
                        data = json.load(f)
                    s = data['statistics']
                    net_profit = float(s.get('Net Profit', '0').replace('%', ''))
                    drawdown = float(s.get('Drawdown', '0').replace('%', ''))
                    sharpe = float(s.get('Sharpe Ratio', '0'))
                    strategy_stats.append((name, net_profit, drawdown, sharpe, info['color']))
    
    for name, profit, dd, sharpe, color in strategy_stats:
        ax3.scatter(dd, profit, s=200, c=color, alpha=0.7, edgecolors='black')
        ax3.annotate(name, (dd, profit), fontsize=9, ha='center', va='bottom')
    
    ax3.set_title('Return vs Risk', fontsize=12, fontweight='bold')
    ax3.set_xlabel('Max Drawdown (%)')
    ax3.set_ylabel('Net Profit (%)')
    ax3.grid(True, alpha=0.3)
    
    # 4. 夏普比率对比
    ax4 = plt.subplot(4, 2, 4)
    names = [s[0] for s in strategy_stats]
    sharpes = [s[3] for s in strategy_stats]
    colors = [s[4] for s in strategy_stats]
    bars = ax4.barh(names, sharpes, color=colors, alpha=0.7, edgecolor='black')
    ax4.set_title('Sharpe Ratio Comparison', fontsize=12, fontweight='bold')
    ax4.set_xlabel('Sharpe Ratio')
    ax4.grid(True, alpha=0.3, axis='x')
    
    for bar, val in zip(bars, sharpes):
        ax4.text(val, bar.get_y() + bar.get_height()/2, f'{val:.2f}', 
                va='center', ha='left', fontsize=9)
    
    # 5. 交易统计
    ax5 = plt.subplot(4, 2, 5)
    stats_text = "STRATEGY PERFORMANCE SUMMARY\n" + "="*50 + "\n\n"
    for name, info in strategies.items():
        backtest_dir = Path('/home/pc/.openclaw/workspace/quant') / info['dir']
        if backtest_dir.is_dir():
            subdirs = [d for d in backtest_dir.iterdir() if d.is_dir()]
            if subdirs:
                latest = max(subdirs, key=lambda x: x.stat().st_mtime)
                json_files = list(latest.glob('*-summary.json'))
                if json_files:
                    with open(json_files[0]) as f:
                        data = json.load(f)
                    s = data['statistics']
                    stats_text += f"{name}:\n"
                    stats_text += f"  Profit: {s.get('Net Profit', 'N/A')}\n"
                    stats_text += f"  Sharpe: {s.get('Sharpe Ratio', 'N/A')}\n"
                    stats_text += f"  DD: {s.get('Drawdown', 'N/A')}\n"
                    stats_text += f"  Orders: {s.get('Total Orders', 'N/A')}\n\n"
    
    ax5.text(0.1, 0.5, stats_text, fontsize=9, family='monospace', 
            verticalalignment='center')
    ax5.axis('off')
    
    # 6. 推荐策略详情
    ax6 = plt.subplot(4, 2, 6)
    recommendation = """
🏆 RECOMMENDED: Risk-Managed Momentum

Parameters:
  lookback: 15
  adx_threshold: 15
  stop_loss_pct: 0.05

Risk Management:
  max_position: 95%
  max_daily_loss: 5%
  max_drawdown: 20%
  target_volatility: 20%

Performance:
  Return: 57.56%
  Sharpe: 0.76
  Drawdown: 11.1%
    """
    ax6.text(0.1, 0.5, recommendation, fontsize=10, family='monospace',
            verticalalignment='center', bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.3))
    ax6.axis('off')
    
    plt.tight_layout()
    
    output_path = Path('/home/pc/.openclaw/workspace/quant/FULL_STRATEGY_REPORT.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Full report saved to: {output_path}")
    plt.close()

if __name__ == '__main__':
    generate_full_report()
