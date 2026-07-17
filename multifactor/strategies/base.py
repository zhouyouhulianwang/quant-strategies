"""
BaseStrategy - Abstract base class for all strategy implementations.

Provides a common interface and shared hooks for backtests, live trading,
signal generation, and risk/status reporting. New strategies should subclass
BaseStrategy and implement the abstract methods.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


class BaseStrategy(ABC):
    """Abstract base class defining the strategy interface.

    Subclasses must implement the lifecycle hooks below. Concrete strategies
    may add their own init parameters, but should accept ``config=None`` to
    stay compatible with generic execution infrastructure.
    """

    def __init__(self, config: Optional[Any] = None):
        """Initialize the strategy with an optional configuration object.

        Parameters
        ----------
        config : Any, optional
            Strategy-agnostic configuration (e.g. risk/trading parameters).
        """
        self.config = config
        self.backtest_result = None

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def run_backtest(self, start_date: Optional[str] = None,
                     end_date: Optional[str] = None, **kwargs) -> Any:
        """Run a backtest over the requested date range.

        Parameters
        ----------
        start_date : str, optional
            Start date in 'YYYY-MM-DD'. Defaults to a sensible history.
        end_date : str, optional
            End date in 'YYYY-MM-DD'. Defaults to today.
        **kwargs : dict
            Strategy-specific backtest options (e.g. weight_method).

        Returns
        -------
        Any
            Backtest result object (e.g. pandas DataFrame).
        """
        ...

    @abstractmethod
    def run_live_rebalance(self) -> None:
        """Execute one live rebalance iteration.

        Typically: fetch data, generate signals, run risk checks, and trade.
        """
        ...

    # ------------------------------------------------------------------
    # Signal hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def generate_signals(self, **kwargs) -> Dict[str, float]:
        """Generate target positions/signals for the strategy.

        Parameters
        ----------
        **kwargs : dict
            Strategy-specific inputs (e.g. price_df, vix, live_mode).

        Returns
        -------
        dict
            Mapping of symbol -> target value/weight.
        """
        ...

    @abstractmethod
    def get_signals(self, date: datetime) -> Dict[str, float]:
        """Get signals for a specific historical or future date.

        Parameters
        ----------
        date : datetime
            Date for which signals should be produced.

        Returns
        -------
        dict
            Mapping of symbol -> target value/weight.
        """
        ...

    # ------------------------------------------------------------------
    # Trading / risk hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def live_trade(self, target_positions: Dict[str, float], **kwargs) -> None:
        """Execute target positions in a live brokerage account.

        Parameters
        ----------
        target_positions : dict
            Symbol -> target value mapping produced by generate_signals.
        **kwargs : dict
            Strategy-specific execution options (e.g. confirm_fills).
        """
        ...

    @abstractmethod
    def check_risk(self, **kwargs) -> None:
        """Run risk checks and update internal risk state.

        Parameters
        ----------
        **kwargs : dict
            Risk inputs (e.g. nav, vix, positions, portfolio_value).
        """
        ...

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Return a serializable snapshot of strategy state.

        Returns
        -------
        dict
            Strategy status summary.
        """
        ...

    # ------------------------------------------------------------------
    # Shared helper defaults
    # ------------------------------------------------------------------

    def _default_backtest_dates(self) -> tuple:
        """Return a sensible default (start, end) date pair.

        Returns
        -------
        tuple(str, str)
            (start_date, end_date) as 'YYYY-MM-DD' strings.
        """
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=5 * 365)).strftime('%Y-%m-%d')
        return start, end

    def get_backtest_result(self) -> Optional[Any]:
        """Return the most recent backtest result, if any.

        Returns
        -------
        Any or None
            Cached backtest result.
        """
        return self.backtest_result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(config={self.config is not None})"
