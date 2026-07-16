"""Streamlit 前端 - LocalQuant 生产级系统"""
import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json

# API 基础 URL
API_BASE = "http://localhost:8000"

def api_get(endpoint):
    """GET 请求"""
    try:
        response = requests.get(f"{API_BASE}{endpoint}", timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None

def api_post(endpoint, data):
    """POST 请求"""
    try:
        response = requests.post(f"{API_BASE}{endpoint}", json=data, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None

# 页面配置
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
    .task-pending {color: #f39c12;}
    .task-running {color: #3498db;}
    .task-completed {color: #2ecc71;}
    .task-failed {color: #e74c3c;}
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header">📊 LocalQuant 量化回测平台</p>', unsafe_allow_html=True)

# 侧边栏导航
page = st.sidebar.radio("导航", [
    "🏠 首页",
    "🚀 新建回测", 
    "📋 任务列表",
    "📈 结果分析",
    "⚙️ 系统状态"
])

# ========== 首页 ==========
if page == "🏠 首页":
    st.header("系统概览")
    
    col1, col2, col3 = st.columns(3)
    
    # 健康检查
    health = api_get("/health")
    if health:
        col1.metric("API 状态", "✅ 运行中", delta=health.get('timestamp', ''))
    else:
        col1.metric("API 状态", "❌ 离线")
    
    # 策略数量
    strategies = api_get("/strategies")
    if strategies:
        col2.metric("可用策略", len(strategies))
    
    # 任务统计
    tasks = api_get("/tasks?limit=100")
    if tasks:
        completed = len([t for t in tasks if t['status'] == 'completed'])
        failed = len([t for t in tasks if t['status'] == 'failed'])
        running = len([t for t in tasks if t['status'] == 'running'])
        
        col3.metric("任务统计", f"总:{len(tasks)}", delta=f"完成:{completed} 失败:{failed} 运行:{running}")
    
    st.markdown("---")
    
    # 快速开始
    st.subheader("快速开始")
    st.markdown("""
    1. **新建回测** → 选择策略、配置参数、提交任务
    2. **任务列表** → 查看所有回测任务的状态
    3. **结果分析** → 查看回测结果、权益曲线、绩效指标
    """)
    
    # 系统信息
    st.subheader("系统信息")
    st.markdown("""
    - **版本**: v1.0.0
    - **数据源**: Yahoo Finance (美股), CCXT/Binance (加密货币), AKShare (A股)
    - **支持策略**: AdaptiveMomentumV3.1, 分钟级动量, 多周期动量, SMA交叉
    - **时间级别**: 1m/5m/15m/1h/1d/1wk/1mo
    """)

# ========== 新建回测 ==========
elif page == "🚀 新建回测":
    st.header("新建回测任务")
    
    # 获取策略列表
    strategies = api_get("/strategies")
    
    if not strategies:
        st.warning("无法获取策略列表，请确保 API 服务器正在运行")
    else:
        with st.form("backtest_form"):
            st.subheader("策略配置")
            
            # 策略选择
            strategy_names = [s['name'] for s in strategies]
            strategy_name = st.selectbox("选择策略", strategy_names)
            
            # 获取策略详情
            selected_strategy = next(s for s in strategies if s['name'] == strategy_name)
            st.info(f"**{selected_strategy['description']}**")
            
            # 策略参数
            st.subheader("策略参数")
            params = {}
            for key, value in selected_strategy['default_params'].items():
                if isinstance(value, bool):
                    params[key] = st.checkbox(key, value=value)
                elif isinstance(value, int):
                    params[key] = st.number_input(key, value=value, step=1)
                elif isinstance(value, float):
                    params[key] = st.slider(key, 0.0, 1.0, value=value, step=0.01)
                else:
                    params[key] = st.text_input(key, value=str(value))
            
            # 标的配置
            st.subheader("标的配置")
            
            # 预设标的集
            preset_options = {
                "Tech Giants (10)": ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'NFLX', 'AMD', 'INTC'],
                "Blue Chips (20)": ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'JPM', 'JNJ', 'V', 'WMT', 'MA', 'PG', 
                                   'HD', 'BAC', 'XOM', 'CVX', 'UNH', 'PFE', 'KO', 'PEP', 'COST', 'DIS'],
                "Crypto (5)": ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'ADA/USDT'],
                "Custom": []
            }
            
            preset = st.selectbox("选择标的集", list(preset_options.keys()))
            
            if preset == "Custom":
                symbols_text = st.text_area("输入标的（逗号分隔）", "AAPL,MSFT,NVDA")
                symbols = [s.strip() for s in symbols_text.split(',')]
            else:
                symbols = preset_options[preset]
                st.text(f"已选: {', '.join(symbols)}")
            
            # 时间配置
            st.subheader("时间配置")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                start_date = st.date_input("开始日期", datetime(2023, 1, 1))
            with col2:
                end_date = st.date_input("结束日期", datetime(2024, 12, 31))
            with col3:
                interval = st.selectbox("时间间隔", ['1d', '1h', '15m', '5m', '1m'])
            
            # 资金配置
            st.subheader("资金配置")
            col1, col2 = st.columns(2)
            with col1:
                initial_cash = st.number_input("初始资金", 10000, 10000000, 100000, step=10000)
            with col2:
                commission_rate = st.slider("手续费率", 0.0, 0.01, 0.001, step=0.0001)
            
            # 提交按钮
            submitted = st.form_submit_button("🚀 提交回测任务", use_container_width=True)
            
            if submitted:
                # 构建请求
                request_data = {
                    "strategy_name": strategy_name,
                    "symbols": symbols,
                    "start_date": start_date.strftime('%Y-%m-%d'),
                    "end_date": end_date.strftime('%Y-%m-%d'),
                    "interval": interval,
                    "initial_cash": initial_cash,
                    "commission_rate": commission_rate,
                    "strategy_params": params
                }
                
                with st.spinner("正在提交任务..."):
                    result = api_post("/backtest", request_data)
                
                if result:
                    st.success(f"✅ 任务创建成功！ID: {result['id']}")
                    st.info(f"状态: {result['status']}")
                    st.balloons()
                else:
                    st.error("❌ 任务创建失败")

# ========== 任务列表 ==========
elif page == "📋 任务列表":
    st.header("回测任务列表")
    
    # 刷新按钮
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 刷新"):
            st.rerun()
    with col2:
        status_filter = st.selectbox("状态筛选", ["全部", "pending", "running", "completed", "failed"])
    
    # 获取任务列表
    endpoint = "/tasks"
    if status_filter != "全部":
        endpoint = f"/tasks?status={status_filter}"
    
    tasks = api_get(endpoint)
    
    if not tasks:
        st.info("暂无任务")
    else:
        # 显示任务表格
        task_data = []
        for task in tasks:
            status_color = {
                'pending': '🟡',
                'running': '🔵',
                'completed': '🟢',
                'failed': '🔴',
                'cancelled': '⚪'
            }.get(task['status'], '⚪')
            
            task_data.append({
                'ID': task['id'],
                '状态': f"{status_color} {task['status']}",
                '类型': task['type'],
                '创建时间': task['created_at'][:19] if task['created_at'] else '-',
                '完成时间': task['completed_at'][:19] if task['completed_at'] else '-'
            })
        
        df = pd.DataFrame(task_data)
        st.dataframe(df, use_container_width=True)
        
        # 查看任务详情
        st.subheader("任务详情")
        task_id = st.number_input("输入任务ID查看详情", 1, 10000, 1)
        
        if st.button("查看详情"):
            task = api_get(f"/tasks/{task_id}")
            if task:
                st.json(task)
                
                # 如果已完成，显示结果
                if task['status'] == 'completed' and task['result']:
                    st.subheader("回测结果")
                    result = task['result']
                    
                    cols = st.columns(4)
                    cols[0].metric("总收益", f"{result.get('total_return', 0):+.2f}%")
                    cols[1].metric("夏普", f"{result.get('sharpe_ratio', 0):.2f}")
                    cols[2].metric("最大回撤", f"{result.get('max_drawdown', 0):.2f}%")
                    cols[3].metric("总交易", result.get('total_trades', 0))
            else:
                st.error("任务不存在")

# ========== 结果分析 ==========
elif page == "📈 结果分析":
    st.header("回测结果分析")
    
    task_id = st.number_input("任务ID", 1, 10000, 1)
    
    if st.button("加载结果"):
        result = api_get(f"/tasks/{task_id}/result")
        
        if result and result.get('status') == 'completed':
            metrics = result.get('result', {})
            
            # 核心指标
            st.subheader("核心绩效指标")
            cols = st.columns(4)
            cols[0].metric("总收益", f"{metrics.get('total_return', 0):+.2f}%")
            cols[1].metric("CAGR", f"{metrics.get('cagr', 0):+.2f}%")
            cols[2].metric("夏普比率", f"{metrics.get('sharpe_ratio', 0):.2f}")
            cols[3].metric("最大回撤", f"{metrics.get('max_drawdown', 0):.2f}%")
            
            cols = st.columns(4)
            cols[0].metric("总交易", metrics.get('total_trades', 0))
            cols[1].metric("胜率", f"{metrics.get('win_rate', 0):.2f}%")
            cols[2].metric("盈亏比", f"{metrics.get('profit_factor', 0):.2f}")
            cols[3].metric("最终资金", f"${metrics.get('final_equity', 0):,.2f}")
            
            # 权益曲线（模拟数据，实际需要 API 返回）
            st.subheader("权益曲线")
            st.info("权益曲线需要从数据库加载，完整实现需要额外 API 端点")
            
            # 这里可以添加从数据库直接读取权益曲线的逻辑
        elif result and result.get('status') != 'completed':
            st.warning(f"任务状态: {result.get('status')}")
        else:
            st.error("无法加载结果")

# ========== 系统状态 ==========
elif page == "⚙️ 系统状态":
    st.header("系统状态")
    
    # API 健康检查
    health = api_get("/health")
    if health:
        st.success(f"✅ API 运行正常 - {health.get('timestamp', '')}")
    else:
        st.error("❌ API 连接失败")
    
    # 策略列表
    st.subheader("可用策略")
    strategies = api_get("/strategies")
    if strategies:
        for s in strategies:
            with st.expander(f"{s['name']} - {s['description']}"):
                st.json(s['default_params'])
    
    # 数据库状态
    st.subheader("数据库状态")
    try:
        import sqlite3
        conn = sqlite3.connect('./data_cache/localquant.db')
        cursor = conn.cursor()
        
        # 任务统计
        cursor.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
        task_stats = cursor.fetchall()
        
        if task_stats:
            st.write("任务统计:")
            for status, count in task_stats:
                st.write(f"  {status}: {count}")
        else:
            st.write("暂无任务数据")
        
        # 回测结果统计
        cursor.execute("SELECT COUNT(*) FROM backtest_results")
        result_count = cursor.fetchone()[0]
        st.write(f"回测结果数: {result_count}")
        
        conn.close()
    except Exception as e:
        st.error(f"数据库连接失败: {e}")

st.sidebar.markdown("---")
st.sidebar.markdown("**LocalQuant v1.0.0**")
st.sidebar.markdown("生产级量化回测系统")
