"""LocalQuant Dashboard v2.0 - 生产级前端"""
import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import time

# API 基础 URL
API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="LocalQuant v2.0 - 量化交易平台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

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

# ========== API 客户端 ==========

class APIClient:
    """API 客户端封装"""
    
    @staticmethod
    def get(endpoint: str, timeout: int = 10):
        try:
            response = requests.get(f"{API_BASE}{endpoint}", timeout=timeout)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            st.error(f"API Error: {e}")
            return None
    
    @staticmethod
    def post(endpoint: str, data: dict, timeout: int = 10):
        try:
            response = requests.post(f"{API_BASE}{endpoint}", json=data, timeout=timeout)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            st.error(f"API Error: {e}")
            return None
    
    @staticmethod
    def delete(endpoint: str, timeout: int = 10):
        try:
            response = requests.delete(f"{API_BASE}{endpoint}", timeout=timeout)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            st.error(f"API Error: {e}")
            return None

# ========== 页面组件 ==========

def render_header():
    st.markdown('<p class="main-header">📊 LocalQuant v2.0 量化交易平台</p>', unsafe_allow_html=True)

def render_sidebar():
    return st.sidebar.radio("导航", [
        "🏠 首页",
        "🚀 新建回测",
        "📋 任务队列",
        "📈 结果分析",
        "⚙️ 系统管理"
    ])

# ========== 页面: 首页 ==========

def page_home():
    st.header("系统概览")
    
    col1, col2, col3 = st.columns(3)
    
    # API 健康检查
    health = APIClient.get("/health")
    if health:
        col1.metric("API 状态", "✅ 运行中", delta=health.get('timestamp', '')[:19])
    else:
        col1.metric("API 状态", "❌ 离线")
    
    # 策略数量
    strategies = APIClient.get("/strategies")
    if strategies:
        col2.metric("可用策略", len(strategies))
    
    # 任务统计
    tasks = APIClient.get("/tasks?limit=100")
    if tasks:
        completed = len([t for t in tasks if t['status'] == 'completed'])
        failed = len([t for t in tasks if t['status'] == 'failed'])
        running = len([t for t in tasks if t['status'] == 'running'])
        pending = len([t for t in tasks if t['status'] == 'pending'])
        
        col3.metric(
            "任务统计", 
            f"总:{len(tasks)}", 
            delta=f"完成:{completed} 失败:{failed} 运行:{running} 队列:{pending}"
        )
    
    st.markdown("---")
    
    # 最近任务
    st.subheader("最近任务")
    if tasks:
        recent_tasks = tasks[:5]
        for task in recent_tasks:
            status_color = {
                'pending': '🟡', 'running': '🔵', 'completed': '🟢',
                'failed': '🔴', 'cancelled': '⚪'
            }.get(task['status'], '⚪')
            
            cols = st.columns([1, 2, 3, 2])
            cols[0].write(f"**{task['id']}**")
            cols[1].write(f"{status_color} {task['status']}")
            cols[2].write(f"{task['strategy_name']}")
            cols[3].write(f"{task['created_at'][:19] if task['created_at'] else '-'}")
    
    # 快速开始
    st.markdown("---")
    st.subheader("快速开始")
    st.markdown("""
    1. **🚀 新建回测** → 选择策略、配置参数、提交任务
    2. **📋 任务队列** → 查看所有回测任务的状态
    3. **📈 结果分析** → 查看回测结果、权益曲线、绩效指标
    """)

# ========== 页面: 新建回测 ==========

def page_new_backtest():
    st.header("新建回测任务")
    
    strategies = APIClient.get("/strategies")
    if not strategies:
        st.warning("无法获取策略列表，请确保 API 服务器正在运行")
        return
    
    with st.form("backtest_form"):
        st.subheader("策略配置")
        
        strategy_names = [s['name'] for s in strategies]
        strategy_name = st.selectbox("选择策略", strategy_names)
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
                if 0 <= value <= 1:
                    params[key] = st.slider(key, 0.0, 1.0, value=value, step=0.01)
                else:
                    params[key] = st.number_input(key, value=float(value), step=0.1)
            else:
                params[key] = st.text_input(key, value=str(value))
        
        # 标的配置
        st.subheader("标的配置")
        preset_options = {
            "Tech Giants (10)": ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'NFLX', 'AMD', 'INTC'],
            "Blue Chips (20)": ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'JPM', 'JNJ', 'V', 'WMT', 'MA', 'PG', 
                               'HD', 'BAC', 'XOM', 'CVX', 'UNH', 'PFE', 'KO', 'PEP', 'COST', 'DIS'],
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
        
        submitted = st.form_submit_button("🚀 提交回测任务", use_container_width=True)
        
        if submitted:
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
                result = APIClient.post("/backtest", request_data)
            
            if result:
                st.success(f"✅ 任务创建成功！ID: {result['id']}")
                st.info(f"状态: {result['status']}")
                st.balloons()
            else:
                st.error("❌ 任务创建失败")

# ========== 页面: 任务队列 ==========

def page_tasks():
    st.header("回测任务队列")
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 刷新"):
            st.rerun()
    with col2:
        status_filter = st.selectbox("状态筛选", ["全部", "pending", "running", "completed", "failed", "cancelled"])
    
    endpoint = "/tasks"
    if status_filter != "全部":
        endpoint = f"/tasks?status={status_filter}"
    
    tasks = APIClient.get(endpoint)
    
    if not tasks:
        st.info("暂无任务")
        return
    
    # 显示任务表格
    task_data = []
    for task in tasks:
        status_color = {
            'pending': '🟡', 'running': '🔵', 'completed': '🟢',
            'failed': '🔴', 'cancelled': '⚪'
        }.get(task['status'], '⚪')
        
        task_data.append({
            'ID': task['id'],
            '状态': f"{status_color} {task['status']}",
            '策略': task['strategy_name'],
            '创建时间': task['created_at'][:19] if task['created_at'] else '-',
            '完成时间': task['completed_at'][:19] if task['completed_at'] else '-'
        })
    
    df = pd.DataFrame(task_data)
    st.dataframe(df, use_container_width=True)
    
    # 任务详情
    st.subheader("任务详情")
    task_id = st.number_input("输入任务ID查看详情", 1, 10000, 1)
    
    if st.button("查看详情"):
        task = APIClient.get(f"/tasks/{task_id}")
        if task:
            st.json(task)
            
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

# ========== 页面: 结果分析 ==========

def page_results():
    st.header("回测结果分析")
    
    task_id = st.number_input("任务ID", 1, 10000, 1)
    
    if st.button("加载结果"):
        task = APIClient.get(f"/tasks/{task_id}")
        
        if task and task['status'] == 'completed' and task['result']:
            metrics = task['result']
            
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
            
            # 下载按钮
            st.subheader("下载数据")
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "下载权益曲线",
                    data="placeholder",  # 实际需要从 API 获取
                    file_name=f"equity_{task_id}.csv",
                    mime="text/csv"
                )
            with col2:
                st.download_button(
                    "下载交易记录",
                    data="placeholder",
                    file_name=f"trades_{task_id}.csv",
                    mime="text/csv"
                )
        else:
            if not task:
                st.error("任务不存在")
            elif task['status'] != 'completed':
                st.warning(f"任务状态: {task['status']}")
            else:
                st.warning("暂无结果")

# ========== 页面: 系统管理 ==========

def page_settings():
    st.header("系统管理")
    
    # API 状态
    st.subheader("API 状态")
    health = APIClient.get("/health")
    if health:
        st.success(f"✅ API 运行正常 - {health.get('timestamp', '')}")
    else:
        st.error("❌ API 连接失败")
    
    # 策略列表
    st.subheader("可用策略")
    strategies = APIClient.get("/strategies")
    if strategies:
        for s in strategies:
            with st.expander(f"{s['name']} - {s['description']}"):
                st.json(s['default_params'])
    
    # 系统配置
    st.subheader("系统配置")
    st.markdown(f"""
    - **API 地址**: {API_BASE}
    - **数据库**: SQLite (./data_cache/localquant.db)
    - **缓存目录**: ./data_cache/
    - **结果目录**: ./data_cache/results/
    """)

# ========== 主入口 ==========

def main():
    render_header()
    page = render_sidebar()
    
    if page == "🏠 首页":
        page_home()
    elif page == "🚀 新建回测":
        page_new_backtest()
    elif page == "📋 任务队列":
        page_tasks()
    elif page == "📈 结果分析":
        page_results()
    elif page == "⚙️ 系统管理":
        page_settings()
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("**LocalQuant v2.0.0**")
    st.sidebar.markdown("生产级量化回测系统")

if __name__ == "__main__":
    main()
