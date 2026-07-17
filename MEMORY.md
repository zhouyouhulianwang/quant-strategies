# MEMORY.md - Long-term memory for Qs

## User preferences

- **Backtests must use real data.** Dave explicitly requested (2026-07-17): always use real QuantConnect data for backtests, never default to mock data. When running backtests, default to `python3 run_strategy.py --backtest` (or `V14Strategy(use_real_data=True)`) so the QuantConnect/Lean data path is used.

## Projects

- **multifactor** (V14 multi-factor trading strategy): Dave's active quantitative trading project under `/home/pc/.openclaw/workspace/multifactor/`. Uses Alpaca Paper/Live for execution, QuantConnect for historical data, Python/pandas stack.

## Important decisions

- V14 strategy has been refactored to inherit from `BaseStrategy` in `strategies/` (2026-07-17).
- V3 paper/live audit fixes implemented and pushed (2026-07-17): risk-monitor trading halts, next-trading-day backtest execution, paper/live CLI separation, real backup encryption, order/PDT/data-cache fixes.
- `config.json` is ignored from Git; credentials should come from environment variables (`ALPACA_API_KEY`, `ALPACA_API_SECRET`).

## Lessons learned

- Before claiming fixes are done, verify actual file contents and git status.
- Run `pytest test_suite.py` after every batch of changes; small indentation errors can break the whole module import chain.
- Sub-agents are effective for parallel domain work but require review and integration testing.
