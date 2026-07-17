"""
MinimalExampleStrategy - A minimal reusable strategy demonstrating the BaseStrategy interface.

This strategy uses hardcoded symbols and equal weights for simplicity. It is intended
as a reference/template for new strategies and does not contain any real data/logic.
"""

from typing import Any, Dict, Optional
from datetime import datetime
from strategies.base import BaseStrategy


class MinimalExampleStrategy(BaseStrategy):
    """
    Minimal example strategy: equal-weight long-only basket, rebalanced at each call.

    Demonstrates that a new strategy can reuse the generic BaseStrategy interface
    without depending on V14-specific factor logic.
    """

    DEFAULT_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

    def __init__(self, config: Optional[Any] = None, symbols: Optional[list] = None):
        """
        Parameters
        ----------
        config : Any, optional
            Strategy-agnostic configuration object.
        symbols : list, optional
            List of symbols to hold. Defaults to DEFAULT_SYMBOLS.
        """
        super().__init__(config=config)
        self.symbols = symbols or list(self.DEFAULT_SYMBOLS)
        self._last_signals: Dict[str, float] = {}
        self._status: Dict[str, Any] = {"rebalances": 0, "live_trades": 0}

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def run_backtest(self, start_date: Optional[str] = None,
                     end_date: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Run a trivial backtest: equal-weight target allocation over the symbols.

        Returns
        -------
        dict
            Minimal backtest result summary.
        """
        start, end = self._default_backtest_dates()
        start_date = start_date or start
        end_date = end_date or end

        weights = self.generate_signals()
        result = {
            "start_date": start_date,
            "end_date": end_date,
            "symbols": self.symbols,
            "target_weights": weights,
            "status": "ok",
        }
        self.backtest_result = result
        self._status["rebalances"] += 1
        return result

    def run_live_rebalance(self) -> None:
        """Execute one live rebalance iteration using equal weights."""
        target = self.generate_signals()
        self._last_signals = target
        self.live_trade(target)
        self._status["rebalances"] += 1

    # ------------------------------------------------------------------
    # Signal hooks
    # ------------------------------------------------------------------

    def generate_signals(self, **kwargs) -> Dict[str, float]:
        """
        Generate equal-weight target positions for the configured symbols.

        Returns
        -------
        dict
            Symbol -> weight (sum to 1.0).
        """
        n = len(self.symbols)
        weight = 1.0 / n if n > 0 else 0.0
        return {sym: weight for sym in self.symbols}

    def get_signals(self, date: datetime) -> Dict[str, float]:
        """Return the same equal-weight signals for any historical date."""
        # Minimal example ignores the date and returns constant weights.
        return self.generate_signals()

    # ------------------------------------------------------------------
    # Trading / risk hooks
    # ------------------------------------------------------------------

    def live_trade(self, target_positions: Dict[str, float], **kwargs) -> None:
        """
        Simulate live trading by recording the target positions.

        In a real implementation this would call an order manager / broker.
        """
        self._last_signals = target_positions
        self._status["live_trades"] += 1

    def check_risk(self, **kwargs) -> None:
        """Run trivial risk checks: ensure weights sum to ~1.0."""
        weights = self.generate_signals()
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Weights do not sum to 1.0: {total}")

    def get_status(self) -> Dict[str, Any]:
        """Return a serializable status snapshot."""
        return {
            "strategy": self.__class__.__name__,
            "symbols": self.symbols,
            "last_signals": self._last_signals,
            **self._status,
        }

    def __repr__(self) -> str:
        return f"MinimalExampleStrategy(symbols={self.symbols}, config={self.config is not None})"
