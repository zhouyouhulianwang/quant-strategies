# Strategy Backup: Adaptive Momentum Strategy - Ultimate Version

## Backup Information
- **Date**: 2026-07-08 13:04 UTC
- **File**: main.py (41,671 bytes)
- **Location**: backups/2026-07-08_13-04-00/

## Strategy Parameters

### Basic Settings
- Start Date: 2022-01-01
- End Date: 2025-06-01
- Initial Cash: $100,000

### Momentum Parameters
- Lookback periods: 1d, 5d, 10d, 21d, 63d, 126d
- Base weights: 0.1, 0.5, 1.0, 1.0, 1.0, 1.0

### Position Management
- Max position per stock: 15%
- Top N stocks: 10
- Stop loss: 15%

### VIX Control
- VIX threshold: 30
- VIX high position scale: 0.5

### Rebalancing
- Base frequency: 2 weeks
- Min frequency: 1 week (low VIX)
- Max frequency: 4 weeks (high VIX)

### Valuation
- Valuation weight: 30%
- Momentum weight: 70%
- Valuation multiplier range: 0.5x - 1.5x

### Sector Rotation
- Enabled: Yes
- Top N sectors: 3

## Backtest Results (2022-01-01 to 2025-06-01)

| Metric | Value |
|--------|-------|
| Total Return | **+307.14%** |
| Compounding Annual Return | **50.89%** |
| Sharpe Ratio | **0.962** |
| Max Drawdown | **48.6%** |
| Win Rate | **80%** |
| Total Orders | **294** |
| Total Fees | **$58.86** |
| End Equity | **$407,136.58** |

## Multi-Period Validation

| Period | Total Return | CAGR | Sharpe | Max DD |
|--------|-------------|------|--------|--------|
| 2018-2022 | +265.44% | 38.24% | 0.825 | 51.9% |
| 2022-2025 | +307.14% | 50.89% | 0.962 | 48.6% |
| 2020-2025 | +2,073.39% | 76.57% | 1.353 | 55.0% |

## Parameter Optimization Results

All tested parameter combinations failed to exceed the original version:
- 8% stop-loss: +275.08%
- 10% position / 20 stocks: +203.26%
- 20% position / 5 stocks: +90.14%
- VIX threshold 25: +307.14% (same)
- Valuation weight 50%: +307.14% (same)
- 1-week rebalancing: +136.31%

## Notes
- This is the optimal configuration found through extensive testing
- VIXY data was fixed to correct scaling issue
- Strategy uses pure US mode (HK disabled)
- 7-layer risk control system active
