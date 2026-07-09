import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path

def visualize_comparison(original_dir, optimized_dir):
    """对比两个策略的可视化"""
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Strategy Comparison: Original vs Optimized', fontsize=14, fontweight='bold')
    
    # 读取两个策略的数据
    for idx, (backtest_dir, label, color) in enumerate([
        (original_dir, 'Original (MA 20/50)', 'blue'),
        (optimized_dir, 'Optimized (EMA 10/30 + Stop Loss)', 'green')
    ]):
        summary_file = Path(backtest_dir) / "1564382000-summary.json" if idx == 0 else \
                       Path(backtest_dir) / "1564382000-summary.json" if idx == 1 else None
        
        if not summary_file or not summary_file.exists():
            # Find the correct file
            json_files = list(Path(backtest_dir).glob('*.json'))
            if json_files:
                summary_file = json_files[0]
        
        if not summary_file or not summary_file.exists():
            continue
            
        with open(summary_file) as f:
            data = json.load(f)
        
        # 权益曲线
        equity_data = data['charts']['Strategy Equity']['series']['Equity']['values']
        dates = [datetime.fromtimestamp(item[0]) for item in equity_data]
        equities = [item[3] for item in equity_data]
        
        ax = axes[0, 0]
        ax.plot(dates, equities, color=color, linewidth=1.5, label=label)
        ax.set_title('Equity Curve Comparison')
        ax.set_xlabel('Date')
        ax.set_ylabel('Portfolio Value ($)')
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        # 回撤
        ax_dd = axes[0, 1]
        peak = equities[0]
        drawdowns = []
        for eq in equities:
            if eq > peak:
                peak = eq
            drawdowns.append((eq - peak) / peak * 100)
        ax_dd.plot(dates, drawdowns, color=color, linewidth=1, label=label, alpha=0.7)
        ax_dd.fill_between(dates, drawdowns, 0, alpha=0.2, color=color)
        ax_dd.set_title('Drawdown Comparison')
        ax_dd.set_xlabel('Date')
        ax_dd.set_ylabel('Drawdown (%)')
        ax_dd.grid(True, alpha=0.3)
        ax_dd.legend()
        ax_dd.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.setp(ax_dd.xaxis.get_majorticklabels(), rotation=45)
    
    # 关键指标对比
    ax_metrics = axes[1, 0]
    metrics = ['Net Profit', 'Sharpe Ratio', 'Max Drawdown', 'Win Rate']
    
    original_stats = {}
    optimized_stats = {}
    
    for idx, backtest_dir in enumerate([original_dir, optimized_dir]):
        json_files = list(Path(backtest_dir).glob('*summary.json'))
        if json_files:
            with open(json_files[0]) as f:
                data = json.load(f)
            stats = data['statistics']
            if idx == 0:
                original_stats = {
                    'Net Profit': float(stats['Net Profit'].replace('%', '')),
                    'Sharpe Ratio': float(stats['Sharpe Ratio']),
                    'Max Drawdown': float(stats['Drawdown'].replace('%', '')),
                    'Win Rate': float(stats['Win Rate'].replace('%', ''))
                }
            else:
                optimized_stats = {
                    'Net Profit': float(stats['Net Profit'].replace('%', '')),
                    'Sharpe Ratio': float(stats['Sharpe Ratio']),
                    'Max Drawdown': float(stats['Drawdown'].replace('%', '')),
                    'Win Rate': float(stats['Win Rate'].replace('%', ''))
                }
    
    x = range(len(metrics))
    width = 0.35
    if original_stats and optimized_stats:
        ax_metrics.bar([i - width/2 for i in x], 
                      [original_stats.get(m, 0) for m in metrics],
                      width, label='Original', color='blue', alpha=0.7)
        ax_metrics.bar([i + width/2 for i in x], 
                      [optimized_stats.get(m, 0) for m in metrics],
                      width, label='Optimized', color='green', alpha=0.7)
    ax_metrics.set_title('Metrics Comparison')
    ax_metrics.set_ylabel('Value')
    ax_metrics.set_xticks(x)
    ax_metrics.set_xticklabels(metrics, rotation=45, ha='right')
    ax_metrics.legend()
    ax_metrics.grid(True, alpha=0.3, axis='y')
    
    # 总结表格
    ax_table = axes[1, 1]
    ax_table.axis('off')
    
    if original_stats and optimized_stats:
        table_data = [
            ['Metric', 'Original', 'Optimized', 'Improvement'],
            ['Net Profit', f"{original_stats['Net Profit']:.1f}%", f"{optimized_stats['Net Profit']:.1f}%", 
             f"{optimized_stats['Net Profit'] - original_stats['Net Profit']:.1f}%"],
            ['Sharpe Ratio', f"{original_stats['Sharpe Ratio']:.2f}", f"{optimized_stats['Sharpe Ratio']:.2f}",
             f"{optimized_stats['Sharpe Ratio'] - original_stats['Sharpe Ratio']:.2f}"],
            ['Max Drawdown', f"{original_stats['Max Drawdown']:.1f}%", f"{optimized_stats['Max Drawdown']:.1f}%",
             f"{original_stats['Max Drawdown'] - optimized_stats['Max Drawdown']:.1f}%"],
            ['Win Rate', f"{original_stats['Win Rate']:.1f}%", f"{optimized_stats['Win Rate']:.1f}%",
             f"{optimized_stats['Win Rate'] - original_stats['Win Rate']:.1f}%"],
        ]
        
        table = ax_table.table(cellText=table_data, cellLoc='center', loc='center',
                              colWidths=[0.25, 0.25, 0.25, 0.25])
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 2)
        
        # 设置表头颜色
        for i in range(4):
            table[(0, i)].set_facecolor('#40466e')
            table[(0, i)].set_text_props(weight='bold', color='white')
    
    plt.tight_layout()
    
    output_path = Path('/home/pc/.openclaw/workspace/quant/comparison_visualization.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Comparison saved to: {output_path}")
    plt.close()

if __name__ == '__main__':
    original_dir = '/home/pc/.openclaw/workspace/quant/MyFirstStrategy/backtests/2026-07-07_11-13-49'
    optimized_dir = '/home/pc/.openclaw/workspace/quant/OptimizedStrategy/backtests/2026-07-07_11-21-00'
    visualize_comparison(original_dir, optimized_dir)
