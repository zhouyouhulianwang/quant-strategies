import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path

def visualize_backtest(backtest_dir):
    """可视化回测结果"""
    
    # 读取回测结果
    summary_file = Path(backtest_dir) / "1564382000-summary.json"
    with open(summary_file) as f:
        data = json.load(f)
    
    # 提取权益曲线数据
    equity_data = data['charts']['Strategy Equity']['series']['Equity']['values']
    
    # 转换为时间序列
    dates = []
    equities = []
    for item in equity_data:
        timestamp = item[0]  # Unix timestamp
        equity = item[3]      # 收盘价（权益）
        dates.append(datetime.fromtimestamp(timestamp))
        equities.append(equity)
    
    # 创建图表
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Backtest Results - Dual Moving Average Strategy', fontsize=14, fontweight='bold')
    
    # 1. 权益曲线
    ax1 = axes[0, 0]
    ax1.plot(dates, equities, color='blue', linewidth=1.5)
    ax1.fill_between(dates, 100000, equities, alpha=0.3, color='blue')
    ax1.axhline(y=100000, color='red', linestyle='--', alpha=0.5, label='Initial Capital')
    ax1.set_title('Equity Curve')
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Portfolio Value ($)')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
    
    # 2. 收益分布
    ax2 = axes[0, 1]
    returns = [(equities[i] - equities[i-1]) / equities[i-1] * 100 
               for i in range(1, len(equities))]
    ax2.hist(returns, bins=50, color='green', alpha=0.7, edgecolor='black')
    ax2.axvline(x=0, color='red', linestyle='--')
    ax2.set_title('Daily Returns Distribution')
    ax2.set_xlabel('Daily Return (%)')
    ax2.set_ylabel('Frequency')
    ax2.grid(True, alpha=0.3)
    
    # 3. 关键指标
    ax3 = axes[1, 0]
    stats = data['statistics']
    metrics = ['Net Profit', 'Compounding Annual Return', 'Sharpe Ratio', 'Win Rate']
    values = [
        float(stats['Net Profit'].replace('%', '')),
        float(stats['Compounding Annual Return'].replace('%', '')),
        float(stats['Sharpe Ratio']),
        float(stats['Win Rate'].replace('%', ''))
    ]
    colors = ['green' if v > 0 else 'red' for v in values]
    bars = ax3.bar(metrics, values, color=colors, alpha=0.7, edgecolor='black')
    ax3.set_title('Key Performance Metrics')
    ax3.set_ylabel('Value')
    ax3.grid(True, alpha=0.3, axis='y')
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # 添加数值标签
    for bar, val in zip(bars, values):
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height,
                f'{val:.2f}', ha='center', va='bottom', fontsize=9)
    
    # 4. 回撤分析
    ax4 = axes[1, 1]
    peak = equities[0]
    drawdowns = []
    for eq in equities:
        if eq > peak:
            peak = eq
        drawdown = (eq - peak) / peak * 100
        drawdowns.append(drawdown)
    
    ax4.fill_between(dates, drawdowns, 0, color='red', alpha=0.3)
    ax4.plot(dates, drawdowns, color='red', linewidth=1)
    ax4.set_title('Drawdown Analysis')
    ax4.set_xlabel('Date')
    ax4.set_ylabel('Drawdown (%)')
    ax4.grid(True, alpha=0.3)
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.setp(ax4.xaxis.get_majorticklabels(), rotation=45)
    
    # 最大回撤标注
    max_dd = min(drawdowns)
    ax4.axhline(y=max_dd, color='darkred', linestyle='--', 
                label=f'Max DD: {max_dd:.2f}%')
    ax4.legend()
    
    plt.tight_layout()
    
    # 保存图片
    output_path = Path(backtest_dir) / 'backtest_visualization.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Visualization saved to: {output_path}")
    
    plt.close()

if __name__ == '__main__':
    backtest_dir = '/home/pc/.openclaw/workspace/quant/MyFirstStrategy/backtests/2026-07-07_11-13-49'
    visualize_backtest(backtest_dir)
