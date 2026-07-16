"""参数优化框架 - 网格搜索最优参数组合"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional
import pandas as pd
import numpy as np
from itertools import product
import multiprocessing as mp
from functools import partial

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'localquant'))

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine

def run_single_backtest(args_tuple) -> Dict:
    """运行单组参数的回测（用于多进程）"""
    params, strategy_class, symbols, data, start, end, initial_cash, commission_rate = args_tuple
    
    try:
        engine = BacktestEngine(
            initial_cash=initial_cash,
            commission_rate=commission_rate,
            start_date=start,
            end_date=end
        )
        engine.set_data(data)
        
        # 创建策略实例并设置参数
        strategy = strategy_class(symbols=symbols)
        for key, value in params.items():
            if hasattr(strategy, key):
                setattr(strategy, key, value)
        
        engine.set_strategy(strategy)
        results = engine.run()
        
        # 计算绩效指标
        metrics = AnalyticsEngine.calculate_metrics(
            results['returns'],
            results['equity_curve'],
            results['trades'],
            initial_cash
        )
        
        return {
            'params': params,
            'metrics': metrics,
            'success': True,
            'error': None
        }
    except Exception as e:
        return {
            'params': params,
            'metrics': None,
            'success': False,
            'error': str(e)
        }

class ParamOptimizer:
    """参数优化器 - 网格搜索"""
    
    def __init__(self, strategy_class, symbols, data, start, end,
                 initial_cash=100000, commission_rate=0.001):
        self.strategy_class = strategy_class
        self.symbols = symbols
        self.data = data
        self.start = start
        self.end = end
        self.initial_cash = initial_cash
        self.commission_rate = commission_rate
        self.results = []
    
    def grid_search(self, param_grid: Dict[str, List], 
                    scoring='sharpe_ratio', maximize=True,
                    n_jobs=-1) -> Tuple[Dict, List[Dict]]:
        """
        网格搜索最优参数
        
        Args:
            param_grid: {'param_name': [value1, value2, ...]}
            scoring: 优化目标指标 ('sharpe_ratio', 'total_return', 'calmar_ratio', 'profit_factor')
            maximize: 是否最大化目标
            n_jobs: 并行进程数，-1 使用所有 CPU
        
        Returns:
            (best_params, all_results)
        """
        # 生成所有参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))
        
        print(f"Grid search: {len(combinations)} combinations")
        print(f"Parameters: {param_names}")
        print(f"Scoring: {scoring} (maximize={maximize})")
        
        # 构建参数组合列表
        param_combinations = []
        for combo in combinations:
            params = dict(zip(param_names, combo))
            param_combinations.append((
                params, self.strategy_class, self.symbols, self.data,
                self.start, self.end, self.initial_cash, self.commission_rate
            ))
        
        # 并行运行回测
        if n_jobs == -1:
            n_jobs = max(1, mp.cpu_count() - 1)
        
        print(f"Running with {n_jobs} parallel jobs...")
        
        if n_jobs > 1 and len(param_combinations) > 1:
            with mp.Pool(n_jobs) as pool:
                self.results = pool.map(run_single_backtest, param_combinations)
        else:
            self.results = [run_single_backtest(args) for args in param_combinations]
        
        # 过滤成功结果
        valid_results = [r for r in self.results if r['success'] and r['metrics'] is not None]
        
        if not valid_results:
            print("No valid results!")
            return None, self.results
        
        # 排序找出最优
        valid_results.sort(
            key=lambda x: x['metrics'].get(scoring, 0),
            reverse=maximize
        )
        
        best = valid_results[0]
        
        print(f"\n{'='*60}")
        print(f"OPTIMIZATION COMPLETE")
        print(f"{'='*60}")
        print(f"Best params: {best['params']}")
        print(f"Best {scoring}: {best['metrics'][scoring]:.4f}")
        print(f"Total return: {best['metrics']['total_return']:+.2f}%")
        print(f"Max drawdown: {best['metrics']['max_drawdown']:.2f}%")
        print(f"Calmar ratio: {best['metrics']['calmar_ratio']:.2f}")
        
        return best['params'], self.results
    
    def get_results_df(self) -> pd.DataFrame:
        """获取结果 DataFrame"""
        rows = []
        for r in self.results:
            if r['success'] and r['metrics']:
                row = {**r['params']}
                row.update({k: v for k, v in r['metrics'].items() if isinstance(v, (int, float, str))})
                row['success'] = True
                rows.append(row)
            else:
                row = {**r['params']}
                row['success'] = False
                row['error'] = r['error']
                rows.append(row)
        
        return pd.DataFrame(rows)
    
    def print_top_results(self, n=5, scoring='sharpe_ratio'):
        """打印 top N 结果"""
        valid = [r for r in self.results if r['success'] and r['metrics']]
        valid.sort(key=lambda x: x['metrics'].get(scoring, 0), reverse=True)
        
        print(f"\n{'='*60}")
        print(f"TOP {n} RESULTS (by {scoring})")
        print(f"{'='*60}")
        
        for i, r in enumerate(valid[:n]):
            m = r['metrics']
            print(f"\n#{i+1} {r['params']}")
            print(f"  Return: {m['total_return']:+.2f}% | Sharpe: {m['sharpe_ratio']:.2f} | "
                  f"MaxDD: {m['max_drawdown']:.2f}% | Calmar: {m['calmar_ratio']:.2f} | "
                  f"WinRate: {m['win_rate']:.1f}% | PF: {m['profit_factor']:.2f}")
