"""生成回测可视化图表"""
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

from localquant.data.manager import DataManager
from localquant.analytics import AnalyticsEngine
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 加载数据
print("Loading backtest results...")
equity = pd.read_csv('data_cache/50symbols_equity.csv')
equity['date'] = pd.to_datetime(equity['date'], utc=True)
equity['date'] = equity['date'].dt.tz_localize(None)
equity.set_index('date', inplace=True)

trades = pd.read_csv('data_cache/50symbols_trades.csv') if Path('data_cache/50symbols_trades.csv').exists() else pd.DataFrame()

# 加载 SPY 基准
dm = DataManager(cache_dir='./data_cache')
spy = dm.get_data('SPY', datetime(2022,1,1), datetime(2024,12,31), '1d')
spy_norm = spy['close'] / spy['close'].iloc[0] * 100000

# 1. 权益曲线 vs 基准
print("Generating equity curve chart...")
# 转换索引为字符串以避免 JSON 序列化问题
equity_reset = equity.reset_index()
equity_reset['date'] = equity_reset['date'].dt.strftime('%Y-%m-%d')
spy_norm_reset = spy_norm.reset_index()
spy_norm_reset.columns = ['date', 'close']
spy_norm_reset['date'] = pd.to_datetime(spy_norm_reset['date']).dt.strftime('%Y-%m-%d')

fig1 = go.Figure()
fig1.add_trace(go.Scatter(x=equity_reset['date'], y=equity_reset['total_value'], mode='lines', name='策略', line=dict(color='#1f77b4', width=2)))
fig1.add_trace(go.Scatter(x=spy_norm_reset['date'], y=spy_norm_reset['close'], mode='lines', name='SPY', line=dict(color='gray', width=1.5, dash='dash')))
fig1.update_layout(title='权益曲线: 策略 vs SPY (2022-2024)', xaxis_title='日期', yaxis_title='资金 ($)', template='plotly_white', hovermode='x unified', legend=dict(orientation='h', yanchor='bottom', y=1.02))
fig1.write_image('data_cache/chart_equity_curve.png', width=1200, height=600, scale=2)

# 2. 回撤图
print("Generating drawdown chart...")
peak = equity['total_value'].expanding().max()
drawdown = (equity['total_value'] - peak) / peak * 100
dd_reset = drawdown.reset_index()
dd_reset['date'] = dd_reset['date'].dt.strftime('%Y-%m-%d')

fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=dd_reset['date'], y=dd_reset['total_value'], mode='lines', fill='tozeroy', line=dict(color='red'), fillcolor='rgba(255,0,0,0.2)', name='回撤'))
fig2.add_hline(y=-10, line_dash="dash", line_color="orange")
fig2.add_hline(y=-15, line_dash="dash", line_color="red")
fig2.add_hline(y=-20, line_dash="dash", line_color="darkred")
fig2.update_layout(title=f'回撤分析 (最大回撤: {drawdown.min():.2f}%)', xaxis_title='日期', yaxis_title='回撤 (%)', template='plotly_white')
fig2.write_image('data_cache/chart_drawdown.png', width=1200, height=400, scale=2)

# 3. 月度收益热力图
print("Generating monthly returns heatmap...")
returns = equity['total_value'].pct_change().fillna(0)
monthly = returns.resample('ME').apply(lambda x: (1 + x).prod() - 1) * 100

monthly_df = pd.DataFrame({'Year': monthly.index.year, 'Month': monthly.index.month, 'Return': monthly.values})
pivot = monthly_df.pivot(index='Year', columns='Month', values='Return')
pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

fig3 = go.Figure(data=go.Heatmap(z=pivot.values, x=pivot.columns, y=pivot.index, colorscale='RdYlGn', zmid=0,
    text=[[f'{v:.1f}' if not np.isnan(v) else '' for v in row] for row in pivot.values],
    texttemplate='%{text}%', textfont={'size': 10}))
fig3.update_layout(title='月度收益热力图 (%)', template='plotly_white', xaxis_title='月份', yaxis_title='年份')
fig3.write_image('data_cache/chart_monthly_returns.png', width=1000, height=400, scale=2)

# 4. 交易分析
if len(trades) > 0:
    print("Generating trade analysis chart...")
    pnl = trades['realized_pnl']
    
    fig4 = make_subplots(rows=2, cols=2, subplot_titles=('盈亏分布', '交易频率', '盈亏散点', '累计盈亏'))
    
    fig4.add_trace(go.Histogram(x=pnl, nbinsx=30, marker_color='blue', name='盈亏'), row=1, col=1)
    fig4.add_vline(x=0, line_dash="dash", line_color="red", row=1, col=1)
    
    trades['month'] = pd.to_datetime(trades['timestamp'], utc=True).dt.strftime('%Y-%m')
    monthly_trades = trades.groupby('month').size()
    fig4.add_trace(go.Bar(x=monthly_trades.index.astype(str), y=monthly_trades.values, marker_color='green', name='交易'), row=1, col=2)
    
    colors = ['green' if v > 0 else 'red' for v in pnl]
    fig4.add_trace(go.Scatter(x=list(range(len(pnl))), y=pnl, mode='markers', marker=dict(color=colors, size=6), name='交易'), row=2, col=1)
    
    cum_pnl = pnl.cumsum()
    fig4.add_trace(go.Scatter(x=list(range(len(cum_pnl))), y=cum_pnl, mode='lines', line=dict(color='blue'), name='累计'), row=2, col=2)
    
    fig4.update_layout(height=700, template='plotly_white', showlegend=False, title_text='交易分析')
    fig4.write_image('data_cache/chart_trades.png', width=1200, height=700, scale=2)

# 5. 关键指标摘要
print("Generating summary...")
metrics = AnalyticsEngine.calculate_metrics(returns, equity['total_value'], trades, 100000)

summary_text = f"""
AdaptiveMomentumV3.1 | 50 Symbols | Optimal Params
{'='*60}
Total Return:     {metrics['total_return']:+.2f}%
CAGR:             {metrics['cagr']:+.2f}%
Sharpe Ratio:     {metrics['sharpe_ratio']:.2f}
Sortino Ratio:    {metrics['sortino_ratio']:.2f}
Max Drawdown:     {metrics['max_drawdown']:.2f}%
Calmar Ratio:     {metrics['calmar_ratio']:.2f}
Volatility:       {metrics['volatility']:.2f}%
{'='*60}
Total Trades:     {metrics['total_trades']}
Win Rate:         {metrics['win_rate']:.2f}%
Profit Factor:    {metrics['profit_factor']:.2f}
Avg Trade PnL:    ${metrics.get('avg_trade_pnl', 0):,.2f}
Total Commission: ${metrics.get('total_commission', 0):,.2f}
{'='*60}
Parameters:
  max_position_pct: 0.10
  rebalance_freq:   10 days
  max_stocks:       10
  stop_loss_pct:    8%
  trailing_stop:    10%
{'='*60}
"""

with open('data_cache/summary.txt', 'w') as f:
    f.write(summary_text)

print(summary_text)
print("\n✓ All charts generated in data_cache/")
print("  - chart_equity_curve.png")
print("  - chart_drawdown.png")
print("  - chart_monthly_returns.png")
print("  - chart_trades.png")
print("  - summary.txt")
