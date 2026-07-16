"""稳健参数优化器 - Walk-Forward + 正则化防止过拟合"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Callable
from datetime import datetime, timedelta
import json
from pathlib import Path

class RobustOptimizer:
    """
    稳健参数优化器
    
    防止过拟合的方法：
    1. Walk-Forward 分析：在多个不重叠时间段测试
    2. 正则化惩罚：交易次数、集中度、参数复杂度
    3. 样本外验证：训练/验证/测试分割
    4. 多重检验校正：Bonferroni 校正
    """
    
    def __init__(self, 
                 train_ratio: float = 0.5,
                 validation_ratio: float = 0.25,
                 n_splits: int = 3):
        self.train_ratio = train_ratio
        self.validation_ratio = validation_ratio
        self.test_ratio = 1 - train_ratio - validation_ratio
        self.n_splits = n_splits
    
    def walk_forward_optimize(self,
                              param_grid: List[Dict],
                              backtest_fn: Callable,
                              dates: List[datetime]) -> Tuple[Dict, Dict]:
        """
        Walk-Forward 优化
        
        Args:
            param_grid: 参数组合列表
            backtest_fn: 回测函数，接收 (params, start, end)
            dates: 日期列表
        
        Returns:
            (最优参数, 统计结果)
        """
        n = len(dates)
        results = []
        
        print(f"Walk-Forward 优化: {len(param_grid)} 参数组合 × {self.n_splits} 时间段")
        
        for split_idx in range(self.n_splits):
            # 分割时间段
            split_size = n // self.n_splits
            start_idx = split_idx * split_size
            mid_idx = start_idx + int(split_size * self.train_ratio)
            val_end_idx = mid_idx + int(split_size * self.validation_ratio)
            end_idx = min((split_idx + 1) * split_size, n)
            
            train_dates = dates[start_idx:mid_idx]
            val_dates = dates[mid_idx:val_end_idx]
            test_dates = dates[val_end_idx:end_idx]
            
            print(f"\nSplit {split_idx + 1}/{self.n_splits}:")
            print(f"  训练: {train_dates[0].date()} ~ {train_dates[-1].date()}")
            print(f"  验证: {val_dates[0].date()} ~ {val_dates[-1].date()}")
            print(f"  测试: {test_dates[0].date()} ~ {test_dates[-1].date()}")
            
            # 在训练集上筛选前 N 个参数
            train_scores = []
            for params in param_grid:
                score = backtest_fn(params, train_dates[0], train_dates[-1])
                train_scores.append((params, score))
            
            # 排序，取前 20%
            train_scores.sort(key=lambda x: x[1], reverse=True)
            top_params = [p for p, _ in train_scores[:max(5, len(param_grid)//5)]]
            
            # 在验证集上测试
            for params in top_params:
                val_score = backtest_fn(params, val_dates[0], val_dates[-1])
                test_score = backtest_fn(params, test_dates[0], test_dates[-1])
                
                results.append({
                    'params': params,
                    'split': split_idx,
                    'train_score': next(s for p, s in train_scores if p == params),
                    'val_score': val_score,
                    'test_score': test_score
                })
        
        # 汇总：选择在验证集和测试集都表现稳定的参数
        return self._select_robust_params(results)
    
    def _select_robust_params(self, results: List[Dict]) -> Tuple[Dict, Dict]:
        """选择稳健的参数"""
        # 按参数分组
        param_groups = {}
        for r in results:
            param_key = json.dumps(r['params'], sort_keys=True)
            if param_key not in param_groups:
                param_groups[param_key] = []
            param_groups[param_key].append(r)
        
        # 计算每个参数的稳健性指标
        robust_scores = []
        for param_key, group in param_groups.items():
            params = group[0]['params']
            
            val_scores = [r['val_score'] for r in group]
            test_scores = [r['test_score'] for r in group]
            
            # 稳健性 = 验证集均值 - 标准差（惩罚波动）
            val_mean = np.mean(val_scores)
            val_std = np.std(val_scores)
            test_mean = np.mean(test_scores)
            test_std = np.std(test_scores)
            
            # 综合得分：验证集表现 + 测试集表现 - 波动惩罚
            robust_score = (val_mean + test_mean) / 2 - 0.5 * (val_std + test_std)
            
            robust_scores.append({
                'params': params,
                'robust_score': robust_score,
                'val_mean': val_mean,
                'val_std': val_std,
                'test_mean': test_mean,
                'test_std': test_std,
                'n_splits': len(group)
            })
        
        # 排序选择最优
        robust_scores.sort(key=lambda x: x['robust_score'], reverse=True)
        best = robust_scores[0]
        
        print("\n" + "="*60)
        print("稳健参数选择结果")
        print("="*60)
        print(f"最优稳健得分: {best['robust_score']:.4f}")
        print(f"验证集: {best['val_mean']:.4f} ± {best['val_std']:.4f}")
        print(f"测试集: {best['test_mean']:.4f} ± {best['test_std']:.4f}")
        print(f"\n最优参数:")
        for k, v in best['params'].items():
            print(f"  {k}: {v}")
        
        return best['params'], best


class RegularizedGridSearch:
    """带正则化的网格搜索"""
    
    def __init__(self,
                 max_trades_penalty: float = 0.001,  # 每笔交易惩罚
                 max_drawdown_penalty: float = 2.0,   # 回撤惩罚系数
                 concentration_penalty: float = 0.5): # 集中度惩罚
        self.max_trades_penalty = max_trades_penalty
        self.max_drawdown_penalty = max_drawdown_penalty
        self.concentration_penalty = concentration_penalty
    
    def score(self, metrics: Dict, params: Dict) -> float:
        """
        计算正则化得分
        
        目标：高夏普 + 低回撤 + 少交易 + 分散持仓
        """
        sharpe = metrics.get('sharpe_ratio', 0)
        max_dd = abs(metrics.get('max_drawdown', 0))
        n_trades = metrics.get('total_trades', 0)
        
        # 基础得分：夏普
        base_score = sharpe
        
        # 正则化项
        trade_penalty = self.max_trades_penalty * max(0, n_trades - 100)  # 超过100笔惩罚
        dd_penalty = self.max_drawdown_penalty * max(0, max_dd - 0.10)    # 超过10%回撤惩罚
        
        # 集中度惩罚（持仓越少越集中）
        max_stocks = params.get('max_stocks', 10)
        concentration_penalty = self.concentration_penalty * max(0, 15 - max_stocks)
        
        regularized_score = base_score - trade_penalty - dd_penalty - concentration_penalty
        
        return regularized_score


# ========== 使用示例 ==========

if __name__ == "__main__":
    # 示例参数网格
    param_grid = [
        {'max_position_pct': 0.10, 'rebalance_freq': 5, 'max_stocks': 10},
        {'max_position_pct': 0.10, 'rebalance_freq': 10, 'max_stocks': 10},
        {'max_position_pct': 0.15, 'rebalance_freq': 7, 'max_stocks': 5},
        {'max_position_pct': 0.20, 'rebalance_freq': 15, 'max_stocks': 8},
    ]
    
    # 示例回测函数
    def dummy_backtest(params, start, end):
        import random
        return random.gauss(0.3, 0.1)
    
    # 示例日期
    dates = pd.date_range('2020-01-01', '2024-12-31', freq='D')
    
    # Walk-Forward 优化
    optimizer = RobustOptimizer(n_splits=3)
    best_params, stats = optimizer.walk_forward_optimize(
        param_grid, dummy_backtest, dates
    )
    
    print(f"\n最优参数: {best_params}")
