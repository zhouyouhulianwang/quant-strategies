"""LocalQuant Streamlit Dashboard - 可视化回测结果"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'localquant'))

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from strategies.adaptive_momentum_v3 import AdaptiveMomentumV3

st.set_page_config(
    page_title="LocalQuant - 量化回测平台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义样式
st.markdown("""
<style>
    .main-header {font-size: 2.5rem; font-weight: bold; color: #1f77b4;}
    .metric-card {background: #f0f2f6; padding: 1rem; border-radius: 0.5rem;}
    .positive {color: #2ecc71;}
    .negative {color: #e74c3c;}
</style>
""", unsafe_allow_html=True)

def load_equity_data(filepath):
    """加载权益曲线数据"""
    df = pd.read_csv(filepath)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    return df['total_value']

def load_spy_data(start, end):
    """加载 SPY 数据作为基准"""
    dm = DataManager(cache_dir='./data_cache')
    spy = dm.get_data('SPY', start, end, '1d')
    if len(spy) > 0:
        # 归一化到初始资金
        initial = 100000
        spy_norm = spy['close'] / spy['close'].iloc[0] * initial
        return spy_norm
    return pd.Series()

def calculate_drawdown(equity):
    """计算回撤"""
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak * 100
    return drawdown

def plot_equity_curve(equity, spy_equity=None):
    """绘制权益曲线"""
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=equity.index, y=equity.values,
        mode='lines', name='策略',
        line=dict(color='#1f77b4', width=2)
    ))
    
    if spy_equity is not None and len(spy_equity) > 0:
        fig.add_trace(go.Scatter(
            x=spy_equity.index, y=spy_equity.values,
            mode='lines', name='SPY (基准)',
            line=dict(color='gray', width=1.5, dash='dash')
        ))
    
    fig.update_layout(
        title='权益曲线 vs 基准',
        xaxis_title='日期',
        yaxis_title='资金',
        template='plotly_white',
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
    )
    return fig

def plot_drawdown(equity):
    """绘制回撤图"""
    dd = calculate_drawdown(equity)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dd.index, y=dd.values,
        mode='lines', name='回撤',
        fill='tozeroy',
        line=dict(color='red'),
        fillcolor='rgba(255,0,0,0.2)'
    ))
    
    # 添加关键回撤线
    fig.add_hline(y=-10, line_dash="dash", line_color="orange", annotation_text="-10%")
    fig.add_hline(y=-15, line_dash="dash", line_color="red", annotation_text="-15%")
    fig.add_hline(y=-20, line_dash="dash", line_color="darkred", annotation_text="-20%")
    
    fig.update_layout(
        title='回撤分析',
        xaxis_title='日期',
        yaxis_title='回撤 (%)',
        template='plotly_white',
        yaxis=dict(tickformat='.1f', ticksuffix='%')
    )
    return fig

def plot_monthly_returns(equity):
    """绘制月度收益热力图"""
    returns = equity.pct_change().fillna(0)
    monthly = returns.resample('M').apply(lambda x: (1 + x).prod() - 1) * 100
    
    monthly_df = pd.DataFrame({
        'Year': monthly.index.year,
        'Month': monthly.index.month,
        'Return': monthly.values
    })
    
    pivot = monthly_df.pivot(index='Year', columns='Month', values='Return')
    pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        colorscale='RdYlGn',
        zmid=0,
        text=[[f'{v:.1f}%' if not np.isnan(v) else '' for v in row] for row in pivot.values],
        texttemplate='%{text}',
        textfont={'size': 10}
    ))
    
    fig.update_layout(
        title='月度收益热力图 (%)',
        template='plotly_white',
        xaxis_title='月份',
        yaxis_title='年份'
    )
    return fig

def plot_trade_distribution(trades_df):
    """绘制交易分布"""
    if len(trades_df) == 0:
        return go.Figure()
    
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=('已实现盈亏分布', '交易频率', '盈亏散点', '累计盈亏')
    )
    
    # 1. 盈亏分布
    pnl = trades_df['realized_pnl']
    fig.add_trace(go.Histogram(x=pnl, nbinsx=30, name='盈亏'), row=1, col=1)
    fig.add_vline(x=0, line_dash="dash", line_color="red", row=1, col=1)
    
    # 2. 交易频率 (按月)
    trades_df['month'] = pd.to_datetime(trades_df['timestamp']).dt.to_period('M')
    monthly_trades = trades_df.groupby('month').size()
    fig.add_trace(go.Bar(x=monthly_trades.index.astype(str), y=monthly_trades.values, name='交易笔数'), row=1, col=2)
    
    # 3. 盈亏散点
    fig.add_trace(go.Scatter(x=list(range(len(pnl))), y=pnl, mode='markers', 
                               marker=dict(color=['green' if v > 0 else 'red' for v in pnl]),
                               name='交易'), row=2, col=1)
    
    # 4. 累计盈亏
    cum_pnl = pnl.cumsum()
    fig.add_trace(go.Scatter(x=list(range(len(cum_pnl))), y=cum_pnl, mode='lines', name='累计盈亏'), row=2, col=2)
    
    fig.update_layout(height=600, template='plotly_white', showlegend=False)
    return fig

def run_backtest_ui(params):
    """运行回测并返回结果"""
    start = datetime(2022, 1, 1)
    end = datetime(2024, 12, 31)
    
    symbols = list(params['symbols'])
    
    with st.spinner('下载数据...'):
        dm = DataManager(cache_dir='./data_cache')
        multi_data = dm.get_multi_data(symbols, start, end, '1d')
    
    with st.spinner('运行回测...'):
        strategy = AdaptiveMomentumV3(symbols=symbols)
        strategy.max_position_pct = params['max_position_pct']
        strategy.rebalance_freq = params['rebalance_freq']
        strategy.max_stocks = params['max_stocks']
        strategy.stop_loss_pct = params['stop_loss_pct']
        strategy.trailing_stop_pct = params['trailing_stop_pct']
        strategy.use_trend_filter = params['use_trend_filter']
        strategy.sector_rotation_enabled = params['sector_rotation_enabled']
        
        engine = BacktestEngine(
            initial_cash=params['initial_cash'],
            commission_rate=params['commission_rate'],
            start_date=start,
            end_date=end
        )
        engine.set_data(multi_data)
        engine.set_strategy(strategy)
        results = engine.run()
    
    metrics = AnalyticsEngine.calculate_metrics(
        results['returns'],
        results['equity_curve'],
        results['trades'],
        params['initial_cash']
    )
    
    return results, metrics

# ========== UI ==========
st.markdown('<p class="main-header">📊 LocalQuant 量化回测平台</p>', unsafe_allow_html=True)

# 侧边栏
st.sidebar.header('⚙️ 参数配置')

st.sidebar.subheader('标的设置')
universe_size = st.sidebar.selectbox('标的数量', [20, 50, 100, 200], index=1)

st.sidebar.subheader('策略参数')
max_position_pct = st.sidebar.slider('最大仓位 (%)', 5, 30, 10) / 100
rebalance_freq = st.sidebar.slider('再平衡频率 (天)', 5, 30, 10)
max_stocks = st.sidebar.slider('最大持股数', 5, 20, 10)

st.sidebar.subheader('风险管理')
stop_loss_pct = st.sidebar.slider('止损 (%)', 3, 15, 8) / 100
trailing_stop_pct = st.sidebar.slider('移动止损 (%)', 5, 20, 10) / 100

st.sidebar.subheader('功能开关')
use_trend_filter = st.sidebar.checkbox('趋势过滤', value=True)
sector_rotation_enabled = st.sidebar.checkbox('板块轮动', value=True)

st.sidebar.subheader('回测设置')
initial_cash = st.sidebar.number_input('初始资金', 10000, 1000000, 100000, step=10000)
commission_rate = st.sidebar.slider('手续费率 (%)', 0.0, 0.5, 0.1, 0.01) / 100

run_button = st.sidebar.button('🚀 运行回测', type='primary', use_container_width=True)

# 主区域
tab1, tab2, tab3 = st.tabs(['📈 回测结果', '📊 绩效分析', '⚡ 快速查看'])

with tab3:
    st.header('快速查看历史回测')
    
    # 查找历史回测结果
    data_dir = Path('./data_cache')
    equity_files = list(data_dir.glob('*_equity.csv'))
    
    if equity_files:
        selected_file = st.selectbox('选择历史回测', [f.name for f in equity_files])
        
        if selected_file:
            equity_path = data_dir / selected_file
            equity = load_equity_data(equity_path)
            
            col1, col2, col3, col4 = st.columns(4)
            total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
            
            col1.metric('总收益', f'{total_return:+.2f}%', delta=f'{total_return:.2f}%')
            col2.metric('最终资金', f'${equity.iloc[-1]:,.2f}')
            col3.metric('最大回撤', f'{calculate_drawdown(equity).min():.2f}%')
            col4.metric('交易天数', f'{len(equity)} 天')
            
            # 权益曲线
            st.plotly_chart(plot_equity_curve(equity), use_container_width=True)
            
            # 回撤
            st.plotly_chart(plot_drawdown(equity), use_container_width=True)
            
            # 月度收益
            st.plotly_chart(plot_monthly_returns(equity), use_container_width=True)
    else:
        st.info('暂无历史回测结果。请先运行回测或选择已有数据。')

with tab1:
    if run_button:
        # 获取标的列表
        sys.path.insert(0, '/home/pc/.openclaw/workspace/AdaptiveMomentumV3_1')
        from strategy_config import SECTOR_MAP
        symbols = list(SECTOR_MAP.keys())[:universe_size]
        
        params = {
            'symbols': symbols,
            'max_position_pct': max_position_pct,
            'rebalance_freq': rebalance_freq,
            'max_stocks': max_stocks,
            'stop_loss_pct': stop_loss_pct,
            'trailing_stop_pct': trailing_stop_pct,
            'use_trend_filter': use_trend_filter,
            'sector_rotation_enabled': sector_rotation_enabled,
            'initial_cash': initial_cash,
            'commission_rate': commission_rate
        }
        
        try:
            results, metrics = run_backtest_ui(params)
            
            # 保存结果
            results['equity_curve'].to_csv(f'./data_cache/dashboard_equity.csv')
            if len(results['trades']) > 0:
                results['trades'].to_csv(f'./data_cache/dashboard_trades.csv', index=False)
            
            st.success('回测完成！')
            
            # 关键指标
            st.subheader('核心绩效指标')
            cols = st.columns(4)
            cols[0].metric('总收益', f"{metrics['total_return']:+.2f}%")
            cols[1].metric('夏普比率', f"{metrics['sharpe_ratio']:.2f}")
            cols[2].metric('最大回撤', f"{metrics['max_drawdown']:.2f}%")
            cols[3].metric('总交易', f"{metrics['total_trades']}")
            
            # 权益曲线
            equity = results['equity_curve']
            spy = load_spy_data(datetime(2022,1,1), datetime(2024,12,31))
            st.plotly_chart(plot_equity_curve(equity, spy), use_container_width=True)
            
            # 回撤
            st.plotly_chart(plot_drawdown(equity), use_container_width=True)
            
        except Exception as e:
            st.error(f'回测失败: {e}')
            st.exception(e)
    else:
        st.info('👈 在左侧配置参数，然后点击"运行回测"')

with tab2:
    if run_button and 'results' in locals():
        st.subheader('详细绩效指标')
        
        col1, col2, col3 = st.columns(3)
        col1.metric('初始资金', f"${metrics['initial_capital']:,.2f}")
        col1.metric('最终资金', f"${metrics['final_equity']:,.2f}")
        col1.metric('总收益', f"{metrics['total_return']:+.2f}%")
        
        col2.metric('CAGR', f"{metrics['cagr']:+.2f}%")
        col2.metric('年化波动', f"{metrics['volatility']:.2f}%")
        col2.metric('夏普比率', f"{metrics['sharpe_ratio']:.2f}")
        
        col3.metric('索提诺', f"{metrics['sortino_ratio']:.2f}")
        col3.metric('Calmar', f"{metrics['calmar_ratio']:.2f}")
        col3.metric('最大回撤', f"{metrics['max_drawdown']:.2f}%")
        
        st.markdown('---')
        
        col4, col5, col6 = st.columns(3)
        col4.metric('总交易', f"{metrics['total_trades']}")
        col4.metric('盈利交易', f"{metrics.get('winning_trades', 0)}")
        col4.metric('亏损交易', f"{metrics.get('losing_trades', 0)}")
        
        col5.metric('胜率', f"{metrics['win_rate']:.2f}%")
        col5.metric('盈亏比', f"{metrics['profit_factor']:.2f}")
        col5.metric('平均盈亏', f"${metrics.get('avg_trade_pnl', 0):,.2f}")
        
        col6.metric('总佣金', f"${metrics.get('total_commission', 0):,.2f}")
        
        # 交易分析
        if len(results['trades']) > 0:
            st.subheader('交易分析')
            st.plotly_chart(plot_trade_distribution(results['trades']), use_container_width=True)
            
            with st.expander('查看交易明细'):
                st.dataframe(results['trades'], use_container_width=True)
    else:
        st.info('先运行回测查看详细分析')

st.sidebar.markdown('---')
st.sidebar.markdown('**LocalQuant v0.1.0**')
st.sidebar.markdown('本地量化回测平台')
