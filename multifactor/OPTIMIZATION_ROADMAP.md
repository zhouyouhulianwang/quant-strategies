# Multifactor Trading System — Continuous Optimization Roadmap

_Updated: 2026-07-22_

## Current Baseline

- **Strategy:** V14 MultiFactor + sub-strategies (Growth, Momentum, Sector Rotation, Value, Quality)
- **Best in-sample portfolio (Sharpe):** G40 / S20 / M15 / V10 / Q15 → Sharpe 1.336, CAGR 23.71%, MaxDD -9.78%, Vol 17.75%
- **Best in-sample portfolio (CAGR):** G40 / S35 / M10 / V10 / Q05 → CAGR 25.49%, Sharpe 1.296, MaxDD -10.90%, Vol 19.67%
- **Tests:** 156 passed, 1 warning (tarfile deprecation)
- **Git:** 3 uncommitted optimization artifacts (optimization_n_stocks.json, optimization_portfolio_weights.json, scripts)

## Key Findings from Portfolio Weight Optimization

| Factor | Correlation with Sharpe | Correlation with CAGR |
|--------|------------------------|----------------------|
| growth | +0.60 | +0.51 |
| quality | +0.39 | -0.84 |
| momentum | +0.08 | -0.17 |
| value | -0.04 | -0.22 |
| sector_rotation | -0.92 | +0.43 |

**Insight:** High Growth improves both Sharpe and CAGR. Sector Rotation is a major Sharpe drag when >20%, but boosts CAGR. Quality is the strongest CAGR drag. This suggests a potential **regime-dependent allocation**: use higher Sector Rotation in strong trends, lower in volatile/choppy markets.

## Optimization Streams (Professional Quant Standards)

### 1. Out-of-Sample Validation (P0)
- [ ] Walk-forward portfolio test (rolling train/test) → `walk_forward_portfolio.py`
- [ ] Cross-validation by year and by regime
- [ ] Purged k-fold cross-validation for time-series
- [ ] OOS Sharpe decay analysis (in-sample vs OOS)

### 2. Risk Management & Portfolio Construction (P0)
- [ ] Regime detection (bull/bear/volatile) based on VIX + trend
- [ ] Dynamic leverage / drawdown guard
- [ ] Correlation stress test and concentration limits
- [ ] Turnover control to reduce transaction costs
- [ ] Maximum Drawdown (MaxDD) target overlay
- [x] **Regime-aware allocation** → `regime_allocator.py` (done 2026-07-22: RegimeAllocator maps regime→weights, bear/volatile tilts defensive (sector_rotation 20%→10%/5%, quality up), bull tilts offensive (sector_rotation 30%), max-step smoothing 10% to avoid whipsaw; integrated into StrategyPortfolio via `regime.risk.regime_allocator_enabled` (default off); 27 tests in `test_regime_allocator.py`, full suite 247 passed)

### 3. Execution Quality (P1)
- [ ] Market impact model (linear & square-root)
- [ ] Slippage estimation by liquidity/ADV
- [ ] Smart order routing / TWAP / VWAP considerations
- [ ] Limit order vs market order backtesting

### 4. Data Quality (P1)
- [ ] Automated price data validation
- [ ] Survivorship bias detection
- [ ] Corporate action (split/dividend) validation
- [ ] Data source reconciliation (Alpaca vs Yahoo vs QuantConnect)

### 5. Alpha Research (P1)
- [ ] Factor performance attribution (which factor, when)
- [ ] Factor decay / momentum of alpha signals
- [ ] Seasonality and macro regime analysis
- [ ] New alpha factor candidates (e.g., earnings quality, short-term reversal, low volatility)

### 6. Operational Reliability (P1)
- [ ] P&L attribution and daily risk report
- [ ] Alerting for data staleness, drawdown breaches, API failures
- [ ] Automated health checks and heartbeat integration
- [ ] Backup and disaster recovery verification

### 7. Code Quality & Testing (P2)
- [ ] Increase test coverage beyond 156 tests
- [ ] Type hints across core modules
- [ ] Refactor duplicated code in data loading
- [ ] Performance profiling for backtest speed

## Immediate Next Steps

1. **Integrate sub-agent deliverables** (walk-forward portfolio, risk overlay, execution/data quality modules)
2. **Run OOS validation** on the best portfolio weights
3. ~~**Implement regime-aware allocation** if OOS confirms the Sharpe/CAGR trade-off~~ ✅ Done — `regime_allocator.py` + portfolio integration + tests (2026-07-22); next: OOS walk-forward of regime-aware vs static weights with `use_real_data=True`
4. **Clean up and commit** optimization artifacts (scripts + results) with proper documentation
5. **Update HEARTBEAT.md** to include new monitoring checks

## Metrics to Track

- In-sample Sharpe / OOS Sharpe ratio (should be > 0.5 ideally)
- MaxDD across regimes
- Turnover and transaction cost drag
- Hit rate and win/loss ratio
- Information ratio vs SPY
- Beta / market neutrality

---
