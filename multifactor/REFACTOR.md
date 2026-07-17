# Refactor: Strategy-agnostic architecture

## Goals

- Separate **strategy-specific** V14 code from **generic infrastructure** so that future strategies can reuse data sources, execution, risk, scheduling, cost, and logging components.
- Introduce a clean `BaseStrategy` abstract interface.
- Preserve existing behavior and all existing tests.
- Keep top-level imports backward compatible.

## New directory structure

```
multifactor/
├── strategies/
│   ├── __init__.py          # Exports BaseStrategy and V14Strategy
│   ├── base.py              # Abstract BaseStrategy class
│   └── v14.py               # V14Strategy implementation
├── run_strategy.py          # Thin CLI wrapper; re-exports V14Strategy for backward compatibility
├── main.py                  # Generic backtest/factor engine (unchanged)
├── test_suite.py            # Updated to import V14Strategy from strategies.v14
├── REFACTOR.md              # This file
└── ...                      # Generic infrastructure files (data, execution, risk, etc.)
```

## `BaseStrategy` interface (`strategies/base.py`)

Abstract methods every concrete strategy must implement:

| Method | Purpose |
|--------|---------|
| `run_backtest(start_date, end_date, **kwargs)` | Run a historical backtest. |
| `run_live_rebalance()` | Execute one live rebalance iteration. |
| `generate_signals(**kwargs)` | Generate target positions/signals. |
| `get_signals(date)` | Get signals for a specific historical date. |
| `live_trade(target_positions, **kwargs)` | Execute target positions in a live account. |
| `check_risk(**kwargs)` | Run risk checks and update risk state. |
| `get_status()` | Return a serializable strategy status snapshot. |

Shared helpers provided by `BaseStrategy`:
- `_default_backtest_dates()`
- `get_backtest_result()`
- `__repr__`

## `V14Strategy` implementation (`strategies/v14.py`)

- Inherits from `BaseStrategy`.
- Keeps all V14-specific logic: data-source selection, mock-data generation, signal generation, backtest engine, live rebalance, risk checks, and status reporting.
- Reuses generic infrastructure from the project root (`alpaca_executor`, `risk_monitor`, `weight_allocation`, `cost_model`, `visualization`, etc.) via optional try/except imports, matching the original behavior.
- Reuses V14 factor/scoring functions from `main.py` (`compute_factors_v14`, `v14_composite_score`, `v14_scale`).

## `run_strategy.py` changes

- Now a thin entry point/wrapper.
- Imports `V14Strategy` from `strategies.v14`.
- Re-exports `V14Strategy` at the top level so `from run_strategy import V14Strategy` still works.
- Retains the CLI (`--backtest`, `--live`, `--paper`, etc.) and main entry logic unchanged.

## `test_suite.py` changes

- Imports `V14Strategy` from `strategies.v14` instead of `run_strategy`.
- All other infrastructure and factor tests remain unchanged.
- All 54 tests continue to pass.

## `main.py` changes

- Left unchanged. `main.py` is the generic backtest/factor engine and contains the V14 factor model that `V14Strategy` consumes. Importing `V14Strategy` into `main.py` would create a circular dependency because `strategies/v14.py` already imports from `main.py`.

## How to add a new strategy

1. Create a new file under `strategies/`, e.g. `strategies/my_strategy.py`.
2. Subclass `BaseStrategy` and implement all abstract methods:

```python
from strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, config=None, **my_params):
        super().__init__(config=config)
        # ... strategy-specific init ...

    def run_backtest(self, start_date=None, end_date=None, **kwargs):
        # ... implement backtest ...
        pass

    def run_live_rebalance(self):
        # ... implement live rebalance ...
        pass

    def generate_signals(self, **kwargs):
        # ... implement signal generation ...
        return {}

    def get_signals(self, date):
        # ... implement date-specific signal lookup ...
        return {}

    def live_trade(self, target_positions, **kwargs):
        # ... implement execution ...
        pass

    def check_risk(self, **kwargs):
        # ... implement risk checks ...
        pass

    def get_status(self):
        # ... return status dict ...
        return {}
```

## Concrete example: `MinimalExampleStrategy`

A working minimal strategy is provided in `strategies/minimal_example.py`. It demonstrates:

- Subclassing `BaseStrategy` and implementing all abstract methods.
- Accepting strategy-specific parameters (`symbols`) plus the shared `config`.
- Generating simple equal-weight target signals.
- Running a trivial backtest and live rebalance.
- Using `check_risk` and `get_status` hooks.

Example usage:

```python
from strategies import MinimalExampleStrategy

strategy = MinimalExampleStrategy(symbols=['AAPL', 'MSFT', 'GOOGL'])
signals = strategy.generate_signals()  # {'AAPL': 0.333..., 'MSFT': 0.333..., 'GOOGL': 0.333...}
strategy.run_live_rebalance()
print(strategy.get_status())
```

Tests covering the minimal strategy are in `test_suite.py` under `TestMinimalExampleStrategy`.

3. Register it in `strategies/__init__.py`:

```python
from strategies.base import BaseStrategy
from strategies.v14 import V14Strategy
from strategies.my_strategy import MyStrategy

__all__ = ['BaseStrategy', 'V14Strategy', 'MyStrategy']
```

4. Add a thin CLI wrapper if desired (e.g. `run_my_strategy.py`), or reuse a generic runner that instantiates strategies by name.

## Backward compatibility

- `from run_strategy import V14Strategy` still works.
- `from main import compute_factors_v14, v14_composite_score, v14_scale, run_v14` still works.
- `python run_strategy.py --backtest ...` and other CLI invocations still work identically.

## Verification

Run the full test suite:

```bash
python -m pytest test_suite.py -q
```

Expected result: `54 passed`.
