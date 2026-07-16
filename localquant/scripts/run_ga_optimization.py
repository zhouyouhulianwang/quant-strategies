#!/usr/bin/env python3
"""遗传算法优化 AdaptiveMomentumV3 策略"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import time

from localquant.data.manager import DataManager
from localquant.core.engine import BacktestEngine
from localquant.analytics import AnalyticsEngine
from localquant.optimization.genetic import GeneticOptimizer, ParameterSpace, GAConfig
from strategies.adaptive_momentum_v3 import AdaptiveMomentumV3

# 回测配置
SYMBOLS = ['AAPL','MSFT','GOOGL','AMZN','NVDA','TSLA','META','NFLX','AMD','INTC',
           'JPM','JNJ','V','WMT','MA','PG','HD','BAC','XOM','CVX',
           'UNH','PFE','KO','PEP','COST','DIS','ADBE','CRM','AVGO','TXN',
           'QCOM','AMGN','HON','SBUX','MDT','AMT','IBM','GE','MMM','CAT',
           'BA','GS','MS','BLK','SPGI','C','WFC','USB','AXP','COP']

START_DATE = datetime(2023, 1, 1)
END_DATE = datetime(2024, 6, 30)
INITIAL_CASH = 100000

# 参数空间
PARAM_SPACE = ParameterSpace({
    'max_position_pct': ('float', 0.05, 0.25),
    'rebalance_freq': ('int', 5, 25),
    'max_stocks': ('int', 3, 12),
    'stop_loss_pct': ('float', 0.03, 0.12),
    'trailing_stop_pct': ('float', 0.05, 0.20),
    'use_trend_filter': ('bool', None, None),
    'sector_rotation_enabled': ('bool', None, None)
})

def fitness_fn(params):
    """适应度函数：运行回测，返回夏普比率"""
    try:
        # 创建策略
        strategy = AdaptiveMomentumV3(symbols=SYMBOLS[:20])  # 用20个标的加速
        
        # 设置参数
        for key, value in params.items():
            if hasattr(strategy, key):
                setattr(strategy, key, value)
        
        # 获取数据（使用缓存）
        dm = DataManager(cache_dir='./data_cache')
        multi_data = dm.get_multi_data(SYMBOLS[:20], START_DATE, END_DATE, '1d')
        
        if len(multi_data) == 0:
            return -999
        
        # 运行回测
        engine = BacktestEngine(
            initial_cash=INITIAL_CASH,
            commission_rate=0.001,
            start_date=START_DATE,
            end_date=END_DATE
        )
        engine.set_data(multi_data)
        engine.set_strategy(strategy)
        
        results = engine.run()
        
        # 计算指标
        metrics = AnalyticsEngine.calculate_metrics(
            results['returns'],
            results['equity_curve'],
            results['trades'],
            INITIAL_CASH
        )
        
        # 返回夏普比率（优化目标）
        sharpe = metrics['sharpe_ratio']
        
        # 惩罚过多交易
        if metrics['total_trades'] > 500:
            sharpe -= 0.1
        
        return sharpe
        
    except Exception as e:
        print(f"回测失败: {e}")
        return -999

def main():
    print("="*60)
    print("遗传算法优化 - AdaptiveMomentumV3")
    print("="*60)
    print(f"标的数: {len(SYMBOLS[:20])}")
    print(f"回测区间: {START_DATE.date()} ~ {END_DATE.date()}")
    print(f"优化目标: 夏普比率")
    print()
    
    start_time = time.time()
    
    # 创建优化器
    optimizer = GeneticOptimizer(GAConfig(
        population_size=15,          # 15个个体
        generations=10,              # 10代
        crossover_rate=0.8,
        mutation_rate=0.3,
        elite_count=2,
        early_stopping_generations=3
    ))
    
    # 运行优化
    best_params, best_sharpe = optimizer.optimize(
        PARAM_SPACE, fitness_fn, maximize=True
    )
    
    elapsed = time.time() - start_time
    
    print("\n" + "="*60)
    print("优化完成!")
    print("="*60)
    print(f"最优夏普比率: {best_sharpe:.4f}")
    print(f"最优参数:")
    for key, value in best_params.items():
        print(f"  {key}: {value}")
    print(f"\n总耗时: {elapsed:.1f} 秒")
    print(f"平均每代: {elapsed/10:.1f} 秒")
    
    # 保存结果
    result_file = Path('./data_cache/ga_optimization_result.json')
    import json
    with open(result_file, 'w') as f:
        json.dump({
            'best_params': best_params,
            'best_sharpe': best_sharpe,
            'elapsed_time': elapsed,
            'fitness_history': [float(x) for x in optimizer.best_fitness_history]
        }, f, indent=2)
    print(f"\n结果已保存: {result_file}")

if __name__ == "__main__":
    main()
