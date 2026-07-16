"""绩效分析 - 回测结果计算与报告"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta

class AnalyticsEngine:
    """绩效分析引擎"""
    
    @staticmethod
    def calculate_metrics(returns: pd.Series, equity: pd.Series, 
                         trades: pd.DataFrame, initial_capital: float,
                         risk_free_rate: float = 0.02) -> Dict:
        """计算核心绩效指标"""
        metrics = {}
        
        # 基础指标
        metrics['initial_capital'] = initial_capital
        metrics['final_equity'] = equity.iloc[-1] if len(equity) > 0 else initial_capital
        metrics['total_return'] = (metrics['final_equity'] / initial_capital - 1) * 100
        
        # 年化收益率
        if len(equity) > 1:
            total_days = (equity.index[-1] - equity.index[0]).days
            if total_days > 0:
                metrics['cagr'] = ((metrics['final_equity'] / initial_capital) ** (365.25 / total_days) - 1) * 100
            else:
                metrics['cagr'] = 0.0
        else:
            metrics['cagr'] = 0.0
        
        # 波动率
        if len(returns) > 0:
            metrics['volatility'] = returns.std() * np.sqrt(252) * 100
        else:
            metrics['volatility'] = 0.0
        
        # 夏普比率
        if metrics['volatility'] > 0:
            excess_return = metrics['cagr'] - risk_free_rate * 100
            metrics['sharpe_ratio'] = excess_return / metrics['volatility']
        else:
            metrics['sharpe_ratio'] = 0.0
        
        # 索提诺比率
        downside_returns = returns[returns < 0]
        if len(downside_returns) > 0:
            downside_std = downside_returns.std() * np.sqrt(252)
            if downside_std > 0:
                metrics['sortino_ratio'] = (returns.mean() * 252 - risk_free_rate) / downside_std
            else:
                metrics['sortino_ratio'] = 0.0
        else:
            metrics['sortino_ratio'] = 0.0
        
        # 最大回撤
        if len(equity) > 0:
            peak = equity.expanding().max()
            drawdown = (equity - peak) / peak
            metrics['max_drawdown'] = drawdown.min() * 100
        else:
            metrics['max_drawdown'] = 0.0
        
        # Calmar 比率
        if metrics['max_drawdown'] != 0:
            metrics['calmar_ratio'] = metrics['cagr'] / abs(metrics['max_drawdown'])
        else:
            metrics['calmar_ratio'] = 0.0
        
        # 交易统计
        if len(trades) > 0:
            metrics['total_trades'] = len(trades)
            metrics['winning_trades'] = len(trades[trades['realized_pnl'] > 0])
            metrics['losing_trades'] = len(trades[trades['realized_pnl'] < 0])
            metrics['win_rate'] = (metrics['winning_trades'] / metrics['total_trades'] * 100) if metrics['total_trades'] > 0 else 0.0
            
            total_pnl = trades['realized_pnl'].sum()
            gross_profit = trades[trades['realized_pnl'] > 0]['realized_pnl'].sum() if metrics['winning_trades'] > 0 else 0
            gross_loss = abs(trades[trades['realized_pnl'] < 0]['realized_pnl'].sum()) if metrics['losing_trades'] > 0 else 0
            metrics['profit_factor'] = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            metrics['avg_trade_pnl'] = total_pnl / metrics['total_trades']
            metrics['avg_win'] = gross_profit / metrics['winning_trades'] if metrics['winning_trades'] > 0 else 0
            metrics['avg_loss'] = gross_loss / metrics['losing_trades'] if metrics['losing_trades'] > 0 else 0
            
            # 佣金
            metrics['total_commission'] = trades['commission'].sum()
        else:
            metrics['total_trades'] = 0
            metrics['win_rate'] = 0.0
            metrics['profit_factor'] = 0.0
        
        return metrics
    
    @staticmethod
    def print_report(metrics: Dict):
        """打印回测报告"""
        print("\n" + "="*60)
        print("           BACKTEST PERFORMANCE REPORT")
        print("="*60)
        print(f"\nInitial Capital:     ${metrics['initial_capital']:,.2f}")
        print(f"Final Equity:          ${metrics['final_equity']:,.2f}")
        print(f"Total Return:          {metrics['total_return']:+.2f}%")
        print(f"CAGR:                  {metrics['cagr']:+.2f}%")
        print(f"Volatility (Ann):      {metrics['volatility']:.2f}%")
        print(f"Sharpe Ratio:          {metrics['sharpe_ratio']:.2f}")
        print(f"Sortino Ratio:         {metrics['sortino_ratio']:.2f}")
        print(f"Max Drawdown:          {metrics['max_drawdown']:.2f}%")
        print(f"Calmar Ratio:          {metrics['calmar_ratio']:.2f}")
        print("\n--- TRADE STATISTICS ---")
        print(f"Total Trades:          {metrics['total_trades']}")
        print(f"Winning Trades:        {metrics.get('winning_trades', 0)}")
        print(f"Losing Trades:         {metrics.get('losing_trades', 0)}")
        print(f"Win Rate:              {metrics['win_rate']:.2f}%")
        print(f"Profit Factor:         {metrics['profit_factor']:.2f}")
        print(f"Avg Trade PnL:         ${metrics.get('avg_trade_pnl', 0):,.2f}")
        print(f"Total Commission:      ${metrics.get('total_commission', 0):,.2f}")
        print("="*60)
