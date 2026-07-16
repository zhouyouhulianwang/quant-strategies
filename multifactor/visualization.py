"""
可视化模块 - 回测结果图表生成
支持 NAV 曲线、回撤、因子暴露、持仓分布等
"""

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import logging
from datetime import datetime
import os

logger = logging.getLogger('visualization')

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 图表输出目录
CHARTS_DIR = os.path.join(os.path.dirname(__file__), 'charts')
os.makedirs(CHARTS_DIR, exist_ok=True)


def plot_nav_curve(result_df, benchmark=None, save_path=None):
    """
    绘制 NAV 曲线
    
    参数:
        result_df: DataFrame, 回测结果 (含 nav 列)
        benchmark: Series, 基准收益 (可选)
        save_path: str, 保存路径
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # 策略曲线
    ax.plot(result_df['date'], result_df['nav'], 
            label='V14 Strategy', linewidth=2, color='#2196F3')
    
    # 基准曲线
    if benchmark is not None:
        ax.plot(result_df['date'], benchmark, 
                label='Benchmark', linewidth=1.5, color='gray', linestyle='--', alpha=0.7)
    
    ax.set_title('NAV Curve - V14 MultiFactor Strategy', fontsize=14, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('NAV')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    
    # 格式化日期
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"✅ 图表已保存: {save_path}")
    else:
        save_path = os.path.join(CHARTS_DIR, f'nav_curve_{datetime.now():%Y%m%d}.png')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"✅ 图表已保存: {save_path}")
    
    plt.close()
    return save_path


def plot_drawdown(result_df, save_path=None):
    """
    绘制回撤图
    
    参数:
        result_df: DataFrame, 回测结果 (含 nav 列)
        save_path: str, 保存路径
    """
    nav = result_df['nav']
    running_max = nav.cummax()
    drawdown = (nav / running_max - 1) * 100
    
    fig, ax = plt.subplots(figsize=(12, 5))
    
    ax.fill_between(result_df['date'], drawdown, 0, 
                    color='red', alpha=0.3, label='Drawdown')
    ax.plot(result_df['date'], drawdown, color='red', linewidth=1)
    
    ax.set_title('Drawdown Analysis', fontsize=14, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Drawdown (%)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 标记最大回撤
    max_dd_idx = drawdown.idxmin()
    max_dd = drawdown.iloc[max_dd_idx]
    ax.annotate(f'Max DD: {max_dd:.1f}%',
                xy=(result_df['date'].iloc[max_dd_idx], max_dd),
                xytext=(10, -30), textcoords='offset points',
                bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.7),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    else:
        save_path = os.path.join(CHARTS_DIR, f'drawdown_{datetime.now():%Y%m%d}.png')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    plt.close()
    return save_path


def plot_monthly_returns(result_df, save_path=None):
    """
    绘制月度收益热力图
    
    参数:
        result_df: DataFrame, 回测结果
        save_path: str, 保存路径
    """
    # 计算月度收益
    result_df = result_df.copy()
    result_df['year'] = result_df['date'].dt.year
    result_df['month'] = result_df['date'].dt.month
    result_df['monthly_return'] = result_df['nav'].pct_change() * 100
    
    # 按年月汇总
    monthly = result_df.groupby(['year', 'month'])['monthly_return'].sum().reset_index()
    monthly_pivot = monthly.pivot(index='year', columns='month', values='monthly_return')
    
    fig, ax = plt.subplots(figsize=(12, 8))
    
    im = ax.imshow(monthly_pivot.values, cmap='RdYlGn', aspect='auto', 
                   vmin=-10, vmax=10)
    
    # 设置标签 - 只显示实际有的月份
    all_months = list(range(1, 13))  # 1-12
    present_months = [m for m in all_months if m in monthly_pivot.columns]
    col_positions = [all_months.index(m) for m in present_months]
    
    ax.set_xticks(col_positions)
    ax.set_xticklabels(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][min(col_positions):max(col_positions)+1] if col_positions else [])
    ax.set_yticks(range(len(monthly_pivot.index)))
    ax.set_yticklabels(monthly_pivot.index)
    
    # 添加数值标注 - 只遍历实际有的列
    for i in range(len(monthly_pivot.index)):
        for j_idx, j_month in enumerate(present_months):
            col_pos = all_months.index(j_month)
            val = monthly_pivot.iloc[i, j_idx]
            if not np.isnan(val):
                color = 'white' if abs(val) > 5 else 'black'
                ax.text(col_pos, i, f'{val:.1f}%', ha='center', va='center', 
                       color=color, fontsize=8)
    
    ax.set_title('Monthly Returns Heatmap (%)', fontsize=14, fontweight='bold')
    plt.colorbar(im, ax=ax, label='Return (%)')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    else:
        save_path = os.path.join(CHARTS_DIR, f'monthly_returns_{datetime.now():%Y%m%d}.png')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    plt.close()
    return save_path


def plot_position_distribution(holdings, save_path=None):
    """
    绘制持仓分布饼图
    
    参数:
        holdings: dict, {symbol: weight}
        save_path: str, 保存路径
    """
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # 排序并取前15
    sorted_holdings = dict(sorted(holdings.items(), key=lambda x: x[1], reverse=True)[:15])
    
    colors = plt.cm.Set3(np.linspace(0, 1, len(sorted_holdings)))
    
    wedges, texts, autotexts = ax.pie(
        sorted_holdings.values(),
        labels=sorted_holdings.keys(),
        autopct='%1.1f%%',
        startangle=90,
        colors=colors
    )
    
    ax.set_title('Portfolio Holdings Distribution', fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    else:
        save_path = os.path.join(CHARTS_DIR, f'holdings_{datetime.now():%Y%m%d}.png')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    plt.close()
    return save_path


def plot_vix_position_scatter(result_df, save_path=None):
    """
    绘制 VIX-仓位散点图
    
    参数:
        result_df: DataFrame, 回测结果 (含 vix, sc 列)
        save_path: str, 保存路径
    """
    # 检查必要的列是否存在
    if 'vix' not in result_df.columns:
        logger.warning("⚠️ 缺少 vix 列，跳过 VIX-仓位散点图")
        return None
    
    # 如果没有 sc 列，使用默认值 100
    if 'sc' not in result_df.columns:
        logger.warning("⚠️ 缺少 sc 列，使用默认值 100%")
        result_df = result_df.copy()
        result_df['sc'] = 100.0
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    scatter = ax.scatter(result_df['vix'], result_df['sc'], 
                        c=result_df['nav'], cmap='viridis', 
                        alpha=0.6, s=50)
    
    ax.set_xlabel('VIX')
    ax.set_ylabel('Position Scale (%)')
    ax.set_title('VIX vs Position Scale', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    # 添加趋势线
    z = np.polyfit(result_df['vix'], result_df['sc'], 1)
    p = np.poly1d(z)
    ax.plot(result_df['vix'].sort_values(), p(result_df['vix'].sort_values()), 
            "r--", alpha=0.8, linewidth=2, label='Trend')
    
    plt.colorbar(scatter, ax=ax, label='NAV')
    ax.legend()
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    else:
        save_path = os.path.join(CHARTS_DIR, f'vix_position_{datetime.now():%Y%m%d}.png')
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
    
    plt.close()
    return save_path


def generate_full_report(result_df, save_dir=None):
    """
    生成完整回测报告（所有图表）
    
    参数:
        result_df: DataFrame, 回测结果
        save_dir: str, 保存目录
    """
    if save_dir is None:
        save_dir = os.path.join(CHARTS_DIR, f'report_{datetime.now():%Y%m%d_%H%M%S}')
    
    os.makedirs(save_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"生成回测报告: {save_dir}")
    print(f"{'='*60}")
    
    # NAV 曲线
    plot_nav_curve(result_df, save_path=os.path.join(save_dir, '01_nav_curve.png'))
    
    # 回撤
    plot_drawdown(result_df, save_path=os.path.join(save_dir, '02_drawdown.png'))
    
    # 月度收益热力图
    plot_monthly_returns(result_df, save_path=os.path.join(save_dir, '03_monthly_returns.png'))
    
    # VIX-仓位关系
    plot_vix_position_scatter(result_df, save_path=os.path.join(save_dir, '04_vix_position.png'))
    
    print(f"✅ 报告生成完成: {save_dir}")
    return save_dir


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    # 创建模拟数据测试
    from main import run_v14
    import numpy as np
    
    np.random.seed(42)
    dates = pd.bdate_range('2020-01-01', '2024-12-31')
    n = len(dates)
    
    # 模拟回测结果
    result = pd.DataFrame({
        'date': dates[252::21],  # 月度
        'nav': np.cumprod(1 + np.random.normal(0.008, 0.04, len(dates[252::21]))),
        'vix': np.random.uniform(12, 35, len(dates[252::21])),
        'sc': np.random.uniform(65, 100, len(dates[252::21]))
    })
    
    # 生成报告
    generate_full_report(result)
