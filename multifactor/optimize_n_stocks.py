"""
Parameter optimization: sweep n_stocks for each sub-strategy.
Runs standalone backtests with real data and saves results.
"""
import sys
import os
import json
import logging
import pandas as pd
from itertools import product

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

from strategies.momentum import MomentumStrategy
from strategies.value import ValueStrategy
from strategies.quality import QualityStrategy
from strategies.growth import GrowthStrategy
from strategies.sector_rotation import SectorRotationStrategy


STRATEGIES = {
    'momentum': MomentumStrategy,
    'value': ValueStrategy,
    'quality': QualityStrategy,
    'growth': GrowthStrategy,
    'sector_rotation': SectorRotationStrategy,
}

N_STOCKS_LIST = [10, 15, 20, 25, 30]
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
        'rebalances': len(result),
    }


def run_sweep():
    results = []
    for name, cls in STRATEGIES.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"Optimizing {name}")
        logger.info(f"{'='*60}")
        for n in N_STOCKS_LIST:
            logger.info(f"  n_stocks={n}")
            try:
                strategy = cls(use_real_data=True, n_stocks=n)
                result = strategy.run_backtest(START_DATE, END_DATE, generate_report=False)
                m = metrics(result)
                if m:
                    row = {'strategy': name, 'n_stocks': n}
                    row.update(m)
                    results.append(row)
                    logger.info(f"    CAGR={m['cagr']:.2%} Sharpe={m['sharpe']:.3f} MaxDD={m['maxdd']:.2%} Vol={m['vol']:.2%}")
                else:
                    logger.warning(f"    No results for n_stocks={n}")
            except Exception as e:
                logger.error(f"    Error for n_stocks={n}: {e}")

    df = pd.DataFrame(results)
    out_path = os.path.join(os.path.dirname(__file__), 'optimization_n_stocks.json')
    df.to_json(out_path, orient='records', indent=2)
    logger.info(f"\nResults saved to {out_path}")

    # Print summary
    logger.info("\n" + "="*60)
    logger.info("Best n_stocks by Sharpe for each strategy")
    logger.info("="*60)
    for name in STRATEGIES:
        sub = df[df['strategy'] == name]
        if len(sub) > 0:
            best = sub.loc[sub['sharpe'].idxmax()]
            logger.info(f"{name}: n_stocks={int(best['n_stocks'])}, Sharpe={best['sharpe']:.3f}, CAGR={best['cagr']:.2%}, MaxDD={best['maxdd']:.2%}")


if __name__ == '__main__':
    run_sweep()
