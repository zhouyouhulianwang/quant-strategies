"""策略模板索引 - 快速使用指南

此文件索引所有可用的策略模板，提供快速导入和使用方式。
"""

# 内置策略
from strategies.adaptive_momentum_v3 import AdaptiveMomentumV3
from strategies.bull_momentum import BullMomentumStrategy
from strategies.trend_following import TrendFollowingStrategy
from strategies.sma_cross import SmaCrossStrategy
from strategies.ml_strategy import MLStrategy
from strategies.minute_momentum import MinuteMomentumStrategy
from strategies.multi_momentum import MultiMomentumStrategy
from strategies.strategy_rotator import StrategyRotator

# 模板策略
from strategies.templates.dual_thrust import DualThrustStrategy
from strategies.templates.grid_trading import GridTradingStrategy
from strategies.templates.pair_trading import PairTradingStrategy
from strategies.templates.alpha_factor import AlphaFactorStrategy


# 策略注册表 - 用于API和Dashboard
STRATEGY_TEMPLATES = {
    # 内置策略
    'adaptive_momentum_v3': {
        'class': AdaptiveMomentumV3,
        'name': 'Adaptive Momentum V3',
        'type': '防御型',
        'description': '多周期动量策略，适合熊市防御',
        'complexity': '⭐⭐⭐',
        'timeframe': '日线/周线',
        'market': '🐻 熊市/震荡'
    },
    'bull_momentum': {
        'class': BullMomentumStrategy,
        'name': 'Bull Momentum',
        'type': '进攻型',
        'description': '动量选股+快速止盈止损，适合牛市',
        'complexity': '⭐⭐',
        'timeframe': '日线',
        'market': '🐂 牛市'
    },
    'trend_following': {
        'class': TrendFollowingStrategy,
        'name': 'Trend Following',
        'type': '趋势型',
        'description': '均线突破+MACD确认，跟随趋势',
        'complexity': '⭐⭐',
        'timeframe': '日线/周线',
        'market': '🔄 趋势市'
    },
    'sma_cross': {
        'class': SmaCrossStrategy,
        'name': 'SMA Cross',
        'type': '简单型',
        'description': '最简单的双均线交叉策略',
        'complexity': '⭐',
        'timeframe': '日线',
        'market': '📊 任意'
    },
    
    # 模板策略
    'dual_thrust': {
        'class': DualThrustStrategy,
        'name': 'Dual Thrust',
        'type': '突破型',
        'description': '经典日内突破策略，适合期货',
        'complexity': '⭐⭐',
        'timeframe': '1分钟/5分钟/15分钟',
        'market': '📈 趋势启动'
    },
    'grid_trading': {
        'class': GridTradingStrategy,
        'name': 'Grid Trading',
        'type': '震荡型',
        'description': '网格低买高卖，适合震荡市',
        'complexity': '⭐',
        'timeframe': '任意',
        'market': '〰️ 震荡市'
    },
    'pair_trading': {
        'class': PairTradingStrategy,
        'name': 'Pair Trading',
        'type': '套利型',
        'description': '统计套利，适合低风险偏好',
        'complexity': '⭐⭐⭐',
        'timeframe': '日线/小时线',
        'market': '📊 任意'
    },
    'alpha_factor': {
        'class': AlphaFactorStrategy,
        'name': 'Alpha Factor',
        'type': '多因子型',
        'description': '价值+质量+动量综合评分选股',
        'complexity': '⭐⭐⭐⭐',
        'timeframe': '月线/周线',
        'market': '📊 任意'
    },
    
    # 组合策略
    'strategy_rotator': {
        'class': StrategyRotator,
        'name': 'Strategy Rotator',
        'type': '组合型',
        'description': '根据市场状态自动切换策略',
        'complexity': '⭐⭐⭐⭐',
        'timeframe': '日线',
        'market': '📊 全天候'
    }
}


def list_strategies():
    """列出所有可用策略"""
    print("="*80)
    print("LocalQuant 策略模板库")
    print("="*80)
    
    for key, info in STRATEGY_TEMPLATES.items():
        print(f"\n【{info['name']}】({key})")
        print(f"  类型: {info['type']} | 复杂度: {info['complexity']}")
        print(f"  适用: {info['market']} | 周期: {info['timeframe']}")
        print(f"  描述: {info['description']}")
    
    print(f"\n共 {len(STRATEGY_TEMPLATES)} 个策略模板")


def get_strategy(name: str):
    """获取策略类"""
    if name in STRATEGY_TEMPLATES:
        return STRATEGY_TEMPLATES[name]['class']
    raise ValueError(f"未知策略: {name}")


# 快速示例
if __name__ == "__main__":
    list_strategies()
    
    print("\n" + "="*80)
    print("使用示例:")
    print("="*80)
    print("""
    # 1. 导入策略
    from strategies.templates import get_strategy
    
    # 2. 创建实例
    StrategyClass = get_strategy('bull_momentum')
    strategy = StrategyClass(
        symbols=['AAPL', 'MSFT', 'GOOGL'],
        top_n=5,
        rebalance_freq=5
    )
    
    # 3. 运行回测
    engine = BacktestEngine()
    engine.set_strategy(strategy)
    results = engine.run()
    
    # 4. 查看结果
    print(f"夏普: {results['sharpe']:.2f}")
    print(f"收益: {results['total_return']:.2%}")
    """)
