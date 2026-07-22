"""
Portfolio weight optimization: sweep strategy weights and run combined backtests.
"""
import sys
import os
import json
import logging
import itertools
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

from strategies.portfolio import StrategyPortfolio
from strategies.momentum import MomentumStrategy
from strategies.value import ValueStrategy
from strategies.quality import QualityStrategy
from strategies.growth import GrowthStrategy
from strategies.sector_rotation import SectorRotationStrategy
from strategies.v14 import MultiFactorStrategy

START_DATE = '2020-01-01'
END_DATE = '2024-01-01'


def metrics(result):
    if result is None or len(result) == 0:
        return None
    nav = result['nav_after_cost'] if 'nav_after_cost' in result.columns else result['nav']
    returns = nav.pct_change().dropna()
    years = (result['date'].iloc[-1] - result['date'].iloc[0]).days / 365.25
    if years <= 0:
        return None
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1
    periods = max(1, int(round(len(result) / years))) if years > 0 else 12
    vol = returns.std() * (periods ** 0.5)
    sharpe = cagr / vol if vol > 0 else 0
    maxdd = ((nav / nav.cummax()) - 1).min()
    return {
        'cagr': cagr,
        'sharpe': sharpe,
        'maxdd': maxdd,
        'vol': vol,
        'start': str(result['date'].iloc[0]),
        'end': str(result['date'].iloc[-1]),
    }


def build_strategies():
    return {
        'multifactor': MultiFactorStrategy(use_real_data=True, weight_method='risk_parity'),
        'growth': GrowthStrategy(use_real_data=True, weight_method='momentum_weighted', n_stocks=25),
        'momentum': MomentumStrategy(use_real_data=True, weight_method='momentum_weighted', n_stocks=10),
        'sector_rotation': SectorRotationStrategy(use_real_data=True, weight_method='momentum_weighted', n_stocks=15, top_sectors=4, sector_lookback=80, sector_weight=0.4),
        'value': ValueStrategy(use_real_data=True, weight_method='equal', n_stocks=20),
        'quality': QualityStrategy(use_real_data=True, weight_method='risk_parity', n_stocks=20),
    }


def generate_weight_grid():
    """Generate weight combinations in 5% increments with constraints."""
    weights = {}
    weights['growth'] = [25, 30, 35, 40]
    weights['sector_rotation'] = [20, 25, 30, 35]
    weights['momentum'] = [5, 10, 15]
    weights['value'] = [10, 15, 20]
    weights['quality'] = [5, 10, 15]

    combos = []
    for g, s, m, v, q in itertools.product(
        weights['growth'], weights['sector_rotation'], weights['momentum'],
        weights['value'], weights['quality']
    ):
        if g + s + m + v + q == 100:
            combos.append({
                'growth': g / 100.0,
                'sector_rotation': s / 100.0,
                'momentum': m / 100.0,
                'value': v / 100.0,
                'quality': q / 100.0,
            })
    return combos


def run_sweep():
    strategy_map = build_strategies()
    weight_combos = generate_weight_grid()
    logger.info(f"Total weight combinations to test: {len(weight_combos)}")

    results = []
    for i, weights in enumerate(weight_combos, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"[{i}/{len(weight_combos)}] Testing weights: {weights}")
        logger.info(f"{'='*60}")

        try:
            strategies = [
                ('multifactor', strategy_map['multifactor'], 0.0),
                ('growth', strategy_map['growth'], weights['growth']),
                ('momentum', strategy_map['momentum'], weights['momentum']),
                ('sector_rotation', strategy_map['sector_rotation'], weights['sector_rotation']),
                ('value', strategy_map['value'], weights['value']),
                ('quality', strategy_map['quality'], weights['quality']),
            ]
            portfolio = StrategyPortfolio(
                strategies=strategies,
                enable_risk_monitor=False,
                use_paper_trading=False,
                paper=False,
            )
            result = portfolio.run_backtest(START_DATE, END_DATE)
            m = metrics(result)
            if m:
                row = {'weights': weights}
                row.update(m)
                results.append(row)
                logger.info(f"  CAGR={m['cagr']:.2%} Sharpe={m['sharpe']:.3f} MaxDD={m['maxdd']:.2%} Vol={m['vol']:.2%}")
            else:
                logger.warning("  No results")
        except Exception as e:
            logger.error(f"  Error: {e}")

        # Save partial results after each run
        df = pd.DataFrame(results)
        out_path = os.path.join(os.path.dirname(__file__), 'optimization_portfolio_weights.json')
        df.to_json(out_path, orient='records', indent=2)

    logger.info(f"\nResults saved to optimization_portfolio_weights.json")

    # Print best by Sharpe
    if len(results) > 0:
        df = pd.DataFrame(results)
        best = df.loc[df['sharpe'].idxmax()]
        logger.info(f"\nBest by Sharpe: {best['weights']}")
        logger.info(f"  CAGR={best['cagr']:.2%} Sharpe={best['sharpe']:.3f} MaxDD={best['maxdd']:.2%} Vol={best['vol']:.2%}")


if __name__ == '__main__':
    run_sweep()
