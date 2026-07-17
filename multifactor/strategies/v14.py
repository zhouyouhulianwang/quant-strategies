"""
V14 Multi-Factor Strategy implementation.

This module contains the concrete V14Strategy class, subclassing
BaseStrategy. It is intentionally self-contained: all V14-specific
factor/scoring logic is imported from the main factor engine, while
generic infrastructure (data, execution, risk, scheduling, costs,
visualisation, weight allocation) is reused from the project root.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging

from requests.exceptions import RequestException, ConnectionError, Timeout

from logging_config import setup_logging
from strategies.base import BaseStrategy

# 尝试导入各基础设施模块（保持与 run_strategy.py 相同的容错导入）
setup_logging()
logger = logging.getLogger('v14_strategy')

try:
    from quantconnect_data import prepare_backtest_data_qc, HybridQCDataSource
    QC_DATA_AVAILABLE = True
    logger.info("[OK] QuantConnect data source available")
except ImportError:
    QC_DATA_AVAILABLE = False
    logger.warning("quantconnect_data module unavailable")

YAHOO_DATA_AVAILABLE = False

try:
    from alpaca_executor import AlpacaPaperExecutor, AlpacaExecutor
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    logger.warning("alpaca_executor module unavailable")

try:
    from order_manager import RebalanceManager
    ORDER_MGR_AVAILABLE = True
except ImportError:
    ORDER_MGR_AVAILABLE = False
    logger.warning("order_manager module unavailable")

try:
    from cost_model import TradingCostModel, apply_costs_to_backtest
    COST_AVAILABLE = True
except ImportError:
    COST_AVAILABLE = False
    logger.warning("cost_model module unavailable")

try:
    from visualization import generate_full_report
    VIZ_AVAILABLE = True
except ImportError:
    VIZ_AVAILABLE = False
    logger.warning("visualization module unavailable")

try:
    from risk_monitor import RiskMonitor
    RISK_AVAILABLE = True
except ImportError:
    RISK_AVAILABLE = False
    logger.warning("risk_monitor module unavailable")

try:
    from intraday_monitor import IntradayMonitor
    INTRADAY_AVAILABLE = True
except ImportError:
    INTRADAY_AVAILABLE = False
    logger.warning("intraday_monitor module unavailable")

try:
    from weight_allocation import WeightAllocator, normalize_target_positions
    WEIGHT_ALLOC_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_AVAILABLE = False
    logger.warning("weight_allocation module unavailable")

try:
    from config import V14StrategyConfig, get_config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    logger.warning("config module unavailable")

# 导入 V14 因子核心（策略模型层）
from main import (
    TICKERS, INDUSTRY, NDX_SET,
    compute_factors_v14, v14_composite_score, v14_scale, run_v14,
    _get_next_trading_day
)


class V14Strategy(BaseStrategy):
    """V14 多因子策略的完整封装类，继承 BaseStrategy 以复用通用接口。"""

    def __init__(self,
                use_real_data=True,
                use_paper_trading=False,
                paper=True,
                enable_risk_monitor=True,
                enable_intraday_monitor=False,
                weight_method='equal',
                config=None):
        """初始化 V14 策略。

        Parameters
        ----------
        use_real_data : bool
            是否使用真实数据源（默认 True）。
                use_paper_trading : bool
                    是否启用 Alpaca 交易执行（默认 False）。
                paper : bool
                    当 use_paper_trading=True 时，True=Paper, False=Live（默认 True）。
        enable_risk_monitor : bool
            是否启用风险监控（默认 True）。
        enable_intraday_monitor : bool
            是否启用盘中监控（默认 False）。
        weight_method : str
            权重分配方法 ('equal' | 'risk_parity' | 'momentum_weighted')。
        config : V14StrategyConfig or None
            配置对象（默认从 config.get_config() 获取）。
        """
        super().__init__(config=config or (get_config() if CONFIG_AVAILABLE else None))

        # 检查数据源可用性
        has_real_data = QC_DATA_AVAILABLE
        if use_real_data and not has_real_data:
            logger.error("[ERROR] Real data source unavailable (QuantConnect)")
            logger.error("   Please configure QuantConnect Lean CLI")
            self.use_real_data = False
        else:
            self.use_real_data = use_real_data and has_real_data

        self.use_paper_trading = use_paper_trading and ALPACA_AVAILABLE
        self.enable_risk_monitor = enable_risk_monitor and RISK_AVAILABLE

        if not self.use_real_data:
            logger.warning("[WARN] Currently using mock data, backtest results are for reference only")
            logger.warning("   Please ensure real data source is available in production")

        # 初始化各模块
        self.executor = None
        self.risk_monitor = None
        self.intraday_monitor = None
        self.weight_allocator = None
        self.backtest_result = None
        self._last_live_portfolio_value = None

        # PIT/数据一致性：强制回测与实盘使用同一数据源和复权方法
        self.signal_data_source = 'QuantConnect'
        self.signal_adjustment = 'adjusted'
        logger.info(f"[DATA] Unified signal data source: {self.signal_data_source} ({self.signal_adjustment})")
        if self.use_paper_trading:
            executor_kwargs = {}
            if self.config:
                executor_kwargs = {
                    'paper': paper,
                    'enable_pdt': self.config.trading.enable_pdt_check,
                    'pdt_min_equity': self.config.trading.pdt_min_equity,
                    'use_limit_orders': self.config.trading.use_limit_orders,
                    'limit_order_offset_pct': self.config.trading.limit_order_offset_pct,
                }
            else:
                executor_kwargs = {'paper': paper}
                logger.info(f"[LIMIT] Limit orders: {self.config.trading.use_limit_orders}, "
                           f"offset={self.config.trading.limit_order_offset_pct:.2%}")
                logger.info(f"[PDT] PDT check: {self.config.trading.enable_pdt_check}, "
                           f"min_equity=${self.config.trading.pdt_min_equity:,.0f}")
                logger.info(f"[TIMEOUT] Order timeout: {self.config.trading.max_wait_sec}s, "
                           f"poll interval: {self.config.trading.poll_interval}s")

            self.executor = AlpacaExecutor(**executor_kwargs)
            logger.info("[OK] Alpaca Paper Trading enabled")
            if not paper:
                logger.critical("[ALERT] Live trading mode initialized")

            if self.risk_monitor:
                self.executor.set_risk_monitor(self.risk_monitor)
                logger.info("[OK] Risk monitor state synced with executor")

        if self.enable_risk_monitor:
            # P1: 使用 config.risk 驱动风控器
            risk_kwargs = {}
            if self.config and hasattr(self.config, 'risk'):
                risk_config = self.config.risk
                risk_kwargs = {
                    'max_drawdown_limit': getattr(risk_config, 'max_drawdown_limit', 0.15),
                    'max_position_pct': getattr(risk_config, 'max_position_pct', 0.20),
                    'max_sector_pct': getattr(risk_config, 'max_sector_pct', 0.30),
                    'daily_loss_limit': getattr(risk_config, 'daily_loss_limit', 0.03),
                    'vix_pause_level': getattr(risk_config, 'vix_panic_threshold', 35.0),
                }
                # 兼容命名：config.json 中使用 max_intraday_dd 但 RiskMonitor 使用 daily_loss_limit
                if hasattr(risk_config, 'max_intraday_dd') and not hasattr(risk_config, 'daily_loss_limit'):
                    risk_kwargs['daily_loss_limit'] = risk_config.max_intraday_dd
            self.risk_monitor = RiskMonitor(**risk_kwargs)
            logger.info("[OK] Risk monitor enabled")

        # 盘中监控
        if enable_intraday_monitor and INTRADAY_AVAILABLE and self.executor and self.risk_monitor:
            check_interval = 60
            if self.config:
                check_interval = self.config.trading.check_interval
                vix_emergency_level = getattr(self.config.risk, 'vix_panic_threshold', 35.0)
                max_total_drawdown = getattr(self.config.risk, 'max_drawdown_limit', 0.15)
            else:
                vix_emergency_level = 35.0
                max_total_drawdown = 0.15

            class V14IntradayMonitor(IntradayMonitor):
                def __init__(inner_self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    inner_self._daily_baseline_nav = None
                    inner_self._current_baseline_date = None

                def _check_all(inner_self):
                    super()._check_all()
                    if not inner_self.risk_monitor:
                        return
                    try:
                        account = inner_self.executor.get_account()
                        if not account:
                            return
                        portfolio_value = account['portfolio_value']
                        positions = inner_self.executor.get_positions()
                        inner_self.risk_monitor.check_concentration_risk(positions, portfolio_value)

                        today = datetime.now(ZoneInfo('America/New_York')).date()
                        if inner_self._current_baseline_date != today:
                            inner_self._current_baseline_date = today
                            inner_self._daily_baseline_nav = portfolio_value
                        if inner_self._daily_baseline_nav and inner_self._daily_baseline_nav > 0:
                            daily_return = (portfolio_value - inner_self._daily_baseline_nav) / inner_self._daily_baseline_nav
                            inner_self.risk_monitor.check_daily_loss(daily_return)
                    except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                        logger.warning(f"Intraday risk supplement network error: {e}")
                    except Exception as e:
                        logger.warning(f"Intraday risk supplement check failed: {e}")

            self.intraday_monitor = V14IntradayMonitor(
                executor=self.executor,
                risk_monitor=self.risk_monitor,
                check_interval=check_interval,
                vix_emergency_level=vix_emergency_level,
                max_total_drawdown=max_total_drawdown
            )
            self.intraday_monitor.start()
            logger.info("[OK] Intraday monitor enabled")

        # 权重分配
        if WEIGHT_ALLOC_AVAILABLE:
            self.weight_allocator = WeightAllocator(method=weight_method)
            logger.info(f"[OK] Weight allocation: {weight_method}")

        logger.info("[OK] V14 strategy initialization complete")

    # ------------------------------------------------------------------
    # BaseStrategy implementation: backtest
    # ------------------------------------------------------------------

    def run_backtest(self, start_date=None, end_date=None, use_cache=True):
        """运行 V14 回测 - 使用与实盘相同的信号生成逻辑。

        Parameters
        ----------
        start_date : str, optional
            'YYYY-MM-DD'。
        end_date : str, optional
            'YYYY-MM-DD'。
        use_cache : bool, optional
            是否使用数据缓存（当前保留参数，未改变行为）。

        Returns
        -------
        pd.DataFrame
            回测结果。
        """
        if start_date is None or end_date is None:
            default_start, default_end = self._default_backtest_dates()
            start_date = start_date or default_start
            end_date = end_date or default_end

        logger.info(f"\n{'='*60}")
        logger.info(f"V14 strategy backtest (unified signal logic)")
        logger.info(f"{'='*60}")
        logger.info(f"Period: {start_date} ~ {end_date}")
        logger.info(f"Data mode: {'real data' if self.use_real_data else 'mock data'}")

        # 获取数据
        if self.use_real_data:
            price_df, market_df = None, None

            if QC_DATA_AVAILABLE:
                try:
                    price_df, market_df = prepare_backtest_data_qc(
                        TICKERS, start_date, end_date, resolution='daily'
                    )
                    if price_df is not None and len(price_df) > 0:
                        logger.info(f"[DATA] Data source: QuantConnect (Lean)")
                    else:
                        logger.warning("[WARN] QuantConnect data is empty")
                        price_df, market_df = None, None
                except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                    logger.warning(f"[WARN] QuantConnect network failure: {e}")
                    price_df, market_df = None, None
                except ValueError as e:
                    logger.warning(f"[WARN] QuantConnect data error: {e}")
                    price_df, market_df = None, None

            if price_df is None or len(price_df) == 0:
                logger.warning("[WARN] No real data available, using mock data")
                price_df, market_df = self._generate_mock_data(start_date, end_date)
        else:
            price_df, market_df = self._generate_mock_data(start_date, end_date)

        # 检查数据有效性
        if price_df is None or len(price_df) == 0:
            logger.error("[ERROR] Cannot get any data, backtest failed")
            return pd.DataFrame()

        if market_df is None or len(market_df) == 0:
            logger.warning("[WARN] Market data empty, using mock VIX=20")
            market_df = pd.DataFrame({'VIX': [20.0] * len(price_df)}, index=price_df.index)

        # 使用统一信号逻辑进行回测
        result = self._run_backtest_unified(price_df, market_df)

        if result is None or len(result) == 0:
            logger.error("[ERROR] Backtest failed, no result data")
            return pd.DataFrame()

        if COST_AVAILABLE:
            logger.info("Applying trading costs...")
            result = apply_costs_to_backtest(result)

        self.backtest_result = result

        self._print_performance(result)

        if VIZ_AVAILABLE and len(result) > 0:
            logger.info("\nGenerating visualization report...")
            generate_full_report(result)

        return result

    def _get_rebalance_dates(self, price_df, rebalance_frequency):
        """根据调仓频率生成调仓日期序列。

        Parameters
        ----------
        price_df : pd.DataFrame
            价格数据（必须有 DatetimeIndex）。
        rebalance_frequency : str
            'daily' | 'weekly' | 'monthly' | 'bimonthly' | 'quarterly'。

        Returns
        -------
        pd.DatetimeIndex
            调仓日期序列。
        """
        if rebalance_frequency == 'daily':
            return price_df.index.copy()
        elif rebalance_frequency == 'weekly':
            return price_df.groupby([price_df.index.year, price_df.index.isocalendar().week]).tail(1).index
        elif rebalance_frequency == 'monthly':
            return price_df.groupby([price_df.index.year, price_df.index.month]).tail(1).index
        elif rebalance_frequency == 'bimonthly':
            # 每两个月最后一个交易日：1,3,5,7,9,11 月末
            mask = price_df.index.month.isin([1, 3, 5, 7, 9, 11])
            if not mask.any():
                return pd.DatetimeIndex([], tz=price_df.index.tz)
            return price_df[mask].groupby([price_df[mask].index.year, price_df[mask].index.month]).tail(1).index
        elif rebalance_frequency == 'quarterly':
            return price_df.groupby([price_df.index.year, price_df.index.quarter]).tail(1).index
        else:
            logger.warning(f"[WARN] Unknown rebalance frequency '{rebalance_frequency}', falling back to monthly")
            return price_df.groupby([price_df.index.year, price_df.index.month]).tail(1).index

    def _run_backtest_unified(self, price_df, market_df):
        """统一回测引擎 - 使用与实盘相同的 generate_signals 逻辑。

        Parameters
        ----------
        price_df : pd.DataFrame
            价格数据（必须有 DatetimeIndex）。
        market_df : pd.DataFrame
            市场数据（必须有 VIX 列）。

        Returns
        -------
        pd.DataFrame
            回测结果。
        """
        # 空数据保护
        if price_df is None or len(price_df) == 0:
            logger.error("[ERROR] price_df is empty, cannot backtest")
            return pd.DataFrame()

        if not isinstance(price_df.index, pd.DatetimeIndex):
            logger.info(f"[CONVERT] Converting index to DatetimeIndex: {type(price_df.index).__name__}")
            try:
                price_df.index = pd.to_datetime(price_df.index)
            except (ValueError, TypeError) as e:
                logger.error(f"[ERROR] Cannot convert index: {e}")
                return pd.DataFrame()

        if market_df is None or len(market_df) == 0:
            logger.warning("[WARN] market_df is empty, using default VIX=20")
            market_df = pd.DataFrame({'VIX': [20.0] * len(price_df)}, index=price_df.index)
        elif 'VIX' not in market_df.columns:
            logger.warning("[WARN] market_df missing VIX column, using default VIX=20")
            market_df['VIX'] = 20.0

        if not isinstance(market_df.index, pd.DatetimeIndex):
            try:
                market_df.index = pd.to_datetime(market_df.index)
            except (ValueError, TypeError) as e:
                logger.error(f"[ERROR] Cannot convert market_df index: {e}")
                return pd.DataFrame()

        common_dates = price_df.index.intersection(market_df.index)
        if len(common_dates) == 0:
            logger.error("[ERROR] price_df and market_df have no common dates")
            return pd.DataFrame()

        price_df = price_df.loc[common_dates]
        market_df = market_df.loc[common_dates]

        if len(price_df) < 252:
            logger.warning(f"[WARN] Insufficient data 252 days ({len(price_df)} days), cannot warm up")
            return pd.DataFrame()

        rebalance_frequency = 'monthly'
        if self.config and hasattr(self.config, 'trading'):
            rebalance_frequency = getattr(self.config.trading, 'rebalance_frequency', 'monthly')
        rebalance_dates = self._get_rebalance_dates(price_df, rebalance_frequency)
        rebalance_dates = rebalance_dates[rebalance_dates >= price_df.index[252]]

        if len(rebalance_dates) < 2:
            logger.warning(f"[WARN] Insufficient rebalance dates (frequency={rebalance_frequency}), cannot backtest")
            return pd.DataFrame()

        logger.info(f"[SCHEDULE] Backtest rebalance frequency: {rebalance_frequency} ({len(rebalance_dates)} rebalance dates)")

        # 辅助函数：根据目标金额和股价计算整数股数与现金
        INITIAL_CAPITAL = 1_000_000.0

        def build_portfolio(target_positions, nav_multiple, rebalance_d):
            portfolio_value = nav_multiple * INITIAL_CAPITAL
            selected = list(target_positions.keys()) if target_positions else []
            total_target = sum(target_positions.values()) if target_positions else 0.0
            curr_weights = {}
            curr_quantities = {}
            curr_invested = 0.0
            if total_target > 0 and selected:
                # generate_signals 默认基于 $1M 组合生成目标金额，按当前组合价值缩放
                scale = portfolio_value / 1_000_000.0
                for s in selected:
                    if s in price_df.columns:
                        price = float(price_df.loc[rebalance_d, s])
                        target_value = target_positions[s] * scale
                        qty = int(target_value / price)
                        if qty > 0:
                            curr_quantities[s] = qty
                            curr_weights[s] = target_positions[s] / total_target
                            curr_invested += qty * price
            curr_cash = max(0.0, portfolio_value - curr_invested)
            return selected, curr_weights, curr_quantities, curr_invested, curr_cash

        nav = 1.0
        records = []

        # 预热期后的第一个调仓日生成初始持仓，避免丢失首个持有期收益
        first_d = rebalance_dates[0]
        try:
            vix_first = float(market_df.loc[first_d, 'VIX'])
        except (KeyError, TypeError, ValueError):
            vix_first = 20.0
        price_slice_first = price_df.loc[:first_d].iloc[-252:]
        target_positions_first = self.generate_signals(price_slice_first, vix_first)
        # P0修复: 首个信号在 first_d 生成，在下一交易日 first_exec_d 执行，避免 lookahead
        first_exec_d = _get_next_trading_day(price_df, first_d)
        selected, curr_weights, curr_quantities, curr_invested, curr_cash = build_portfolio(
            target_positions_first, nav, first_exec_d
        )
        prev_holdings = selected
        prev_quantities = curr_quantities
        prev_cash = curr_cash

        for i in range(1, len(rebalance_dates)):
            prev_d, curr_d = rebalance_dates[i-1], rebalance_dates[i]
            # P0修复: 在下一交易日执行，避免使用 signal 日当天收盘价同日复权执行
            prev_exec_d = _get_next_trading_day(price_df, prev_d)
            curr_exec_d = _get_next_trading_day(price_df, curr_d)

            try:
                vix_v = float(market_df.loc[prev_d, 'VIX'])
            except (KeyError, TypeError, ValueError):
                vix_v = 20.0

            # 计算上一期持仓收益（使用整数股数与现金）
            if prev_holdings and prev_quantities:
                try:
                    stock_value_start = 0.0
                    stock_value_end = 0.0
                    for s, qty in prev_quantities.items():
                        p_start = float(price_df.loc[prev_exec_d, s])
                        p_end = float(price_df.loc[curr_exec_d, s])
                        stock_value_start += qty * p_start
                        stock_value_end += qty * p_end
                    portfolio_value_start = stock_value_start + prev_cash
                    portfolio_value_end = stock_value_end + prev_cash
                    mr = portfolio_value_end / portfolio_value_start - 1 if portfolio_value_start > 0 else 0.0
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"[WARN] Return calculation error: {e}, using 0")
                    mr = 0.0
            else:
                mr = 0.0

            nav *= (1 + mr)

            # 生成新的目标持仓并模拟整数截断
            price_slice = price_df.loc[:prev_d].iloc[-252:]  # P0修复: 使用 prev_d 收盘前数据生成信号
            target_positions = self.generate_signals(price_slice, vix_v)
            selected, curr_weights, curr_quantities, curr_invested, curr_cash = build_portfolio(
                target_positions, nav, curr_exec_d  # P0修复: 在下一交易日执行
            )

            records.append({
                'date': curr_exec_d,
                'nav': nav,
                'mr': mr,
                'vix': vix_v,
                'n': len(selected),
                'holdings': selected,
                'weights': curr_weights,
                'quantities': curr_quantities,
                'cash': curr_cash,
                'invested': curr_invested,
            })
            prev_holdings = selected
            prev_quantities = curr_quantities
            prev_cash = curr_cash

        return pd.DataFrame(records)

    # ------------------------------------------------------------------
    # BaseStrategy implementation: signal generation
    # ------------------------------------------------------------------

    def _prepare_signal_data(self, start_date, end_date):
        """
        统一为回测信号和实盘信号准备数据，确保数据源和复权方法一致。
        """
        if not QC_DATA_AVAILABLE:
            logger.error("[DATA] QuantConnect data source not available")
            return None, None

        logger.info(
            "[DATA] Preparing signal data: source=%s, adjustment=%s, period=%s ~ %s",
            self.signal_data_source, self.signal_adjustment, start_date, end_date
        )
        price_df, market_df = prepare_backtest_data_qc(
            TICKERS, start_date, end_date, resolution='daily'
        )
        if price_df is not None and len(price_df) > 0:
            logger.info(
                "[DATA] Signal data ready: source=%s, adjustment=%s, latest=%s",
                self.signal_data_source, self.signal_adjustment, price_df.index[-1]
            )
        return price_df, market_df

    def generate_signals(self, price_df=None, vix=None, live_mode=False):
        """生成交易信号 - 桥接回测逻辑到实盘。

        Parameters
        ----------
        price_df : pd.DataFrame, optional
            价格数据（默认获取最新 252 日）。
        vix : float, optional
            当前 VIX（默认从数据获取）。
        live_mode : bool, optional
            实盘模式标记（用于日志提示）。

        Returns
        -------
        dict
            {symbol: target_value} 目标持仓。
        """
        # 获取数据
        if price_df is None:
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')

            price_df, market_df = self._prepare_signal_data(start, end)
            if price_df is None or len(price_df) == 0:
                logger.error("Cannot get signal data, no data source available")
                return {}
            if vix is None:
                vix = market_df['VIX'].iloc[-1]

        if vix is None:
            logger.error("VIX data missing")
            return {}

        logger.info(f"\n{'='*60}")
        logger.info(f"Generating trading signals")
        logger.info(f"{'='*60}")
        logger.info(f"Data source: {self.signal_data_source} ({self.signal_adjustment})")
        logger.info(f"Current VIX: {vix:.2f}")
        logger.info(f"Data date: {price_df.index[-1]}")

        if live_mode:
            freq_desc = ""
            if self.config and hasattr(self.config, 'trading'):
                freq = getattr(self.config.trading, 'rebalance_frequency', 'monthly')
                freq_desc = f"({freq} rebalance)"
            logger.info(f"[NOTE] Live signals based on historical EOD close prices {freq_desc}")
            logger.info(f"[NOTE] Latest available EOD date: {price_df.index[-1]}")
            if self.use_paper_trading:
                logger.info("[NOTE] Live execution will use current real-time prices to calculate shares")

        # 计算因子 (复用回测逻辑)
        price_slice = price_df.iloc[-252:]
        factors = compute_factors_v14(price_slice)
        score = v14_composite_score(factors, vix)

        # 仓位比例
        sc = v14_scale(vix)
        logger.info(f"Target exposure: {sc:.1f}%")

        # NDX 比例
        ndx_mask = score.index.isin(NDX_SET)
        ndx_avg = score[ndx_mask].mean() if ndx_mask.any() else 0.5
        non_avg = score[~ndx_mask].mean() if (~ndx_mask).any() else 0.5
        total = ndx_avg + non_avg
        ndx_ratio = np.clip(ndx_avg / total if total > 0 else 0.5, 0.15, 0.60)

        # 选股数量
        vix_norm = np.clip((vix - 15) / 40, 0, 1)
        n_stocks = max(10, min(40, int(20 + 15 * (1 - vix_norm))))

        # 分层选股
        ndx_n = max(2, int(n_stocks * ndx_ratio))
        ndx_sorted = score[ndx_mask].sort_values(ascending=False).dropna()
        non_sorted = score[~ndx_mask].sort_values(ascending=False).dropna()

        selected = (
            list(ndx_sorted.index[:min(ndx_n, len(ndx_sorted))]) +
            list(non_sorted.index[:min(n_stocks - ndx_n, len(non_sorted))])
        )

        logger.info(f"Selected stocks: {len(selected)} symbols")
        logger.info(f"NDX ratio: {ndx_ratio:.2%}")
        logger.info(f"Selected stocks: {', '.join(selected[:10])}{'...' if len(selected) > 10 else ''}")

        # 获取账户价值
        if self.executor:
            try:
                account = self.executor.get_account()
                portfolio_value = account['portfolio_value'] if account else 1000000
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                logger.warning(f"Failed to get account value network: {e}, using default $1M")
                portfolio_value = 1000000
            except ValueError as e:
                logger.warning(f"Account value parameter error: {e}, using default $1M")
                portfolio_value = 1000000
        else:
            portfolio_value = 1000000

        # 权重分配
        if self.weight_allocator and len(selected) > 0:
            weights = self.weight_allocator.allocate(
                selected,
                price_df=price_df,
                target_value=portfolio_value * sc / 100
            )
            target_positions = weights
            logger.info(f"Weight allocation: {self.weight_allocator.method}")
        else:
            target_value = (portfolio_value * sc / 100) / len(selected)
            target_positions = {s: target_value for s in selected}

        # 确保目标持仓总金额不超过组合价值 * 仓位比例
        max_total_value = portfolio_value * sc / 100
        target_positions = normalize_target_positions(target_positions, max_total_value)
        logger.info(f"[PORTFOLIO] Total target positions: ${sum(target_positions.values()):,.0f} (cap: ${max_total_value:,.0f})")

        for s, v in sorted(target_positions.items(), key=lambda x: x[1], reverse=True)[:10]:
            logger.info(f"  {s}: ${v:,.0f}")

        return target_positions

    def get_signals(self, date):
        """获取指定日期的 V14 交易信号。

        Parameters
        ----------
        date : datetime
            目标日期。

        Returns
        -------
        dict
            {symbol: target_value} 目标持仓。
        """
        if not QC_DATA_AVAILABLE:
            logger.warning("[WARN] No data source available, cannot get historical signals")
            return {}

        end = date.strftime('%Y-%m-%d')
        start = (date - timedelta(days=400)).strftime('%Y-%m-%d')

        try:
            price_df, market_df = prepare_backtest_data_qc(
                TICKERS, start, end, resolution='daily'
            )
            if price_df is None or len(price_df) == 0:
                return {}
            vix = market_df['VIX'].iloc[-1]
            return self.generate_signals(price_df, vix=vix)
        except Exception as e:
            logger.warning(f"Failed to get {date} signals: {e}")
            return {}

    # ------------------------------------------------------------------
    # BaseStrategy implementation: live rebalance / trading
    # ------------------------------------------------------------------

    def run_live_rebalance(self):
        """运行实盘再平衡 - 全自动流程。"""
        if not self.executor:
            logger.error("Alpaca Paper Trading not enabled")
            return

        if not self.executor.market_is_open():
            logger.warning("[WARN] Market not open, skipping this live rebalance")
            logger.warning("   V14 is an end-of-month EOD strategy, recommended to run after market open")
            return

        cutoff_minutes = 15
        if self.config and hasattr(self.config, 'trading'):
            cutoff_minutes = getattr(self.config.trading, 'market_close_cutoff_minutes', 15)
        cutoff_total_minutes = 16 * 60 - cutoff_minutes
        cutoff_hour = cutoff_total_minutes // 60
        cutoff_minute = cutoff_total_minutes % 60
        try:
            now = datetime.now(ZoneInfo('America/New_York'))
        except Exception:
            now = datetime.now()
        if now.hour > cutoff_hour or (now.hour == cutoff_hour and now.minute >= cutoff_minute):
            logger.warning(f"[WARN] Past market-close protection time {cutoff_hour:02d}:{cutoff_minute:02d} ET, rejecting new rebalance")
            return

        self.executor.start_rebalance_session()

        # 每次调仓前同步公司行为（拆股调整）
        if self.use_paper_trading and self.executor:
            try:
                self.executor.sync_corporate_actions(list(self.generate_signals(live_mode=True).keys()))
            except Exception as e:
                logger.warning(f"[WARN] Pre-rebalance corporate action sync failed: {e}, continuing with local state")

        # 每次调仓前同步 PDT 状态（High #8 修复）
        if self.use_paper_trading and self.executor:
            try:
                self.executor.sync_positions()
                logger.info("[PDT] Pre-rebalance PDT state synced")
            except Exception as e:
                logger.warning(f"[WARN] Pre-rebalance PDT sync failed: {e}, continuing with local state")

        target_positions = self.generate_signals(live_mode=True)

        if not target_positions:
            logger.error("Signal generation failed, skipping trade")
            return

        if self.risk_monitor:
            vix = self._get_latest_vix()
            if vix:
                self.risk_monitor.check_vix_level(vix)

            if self.risk_monitor.trading_halted:
                logger.warning("[WARN] Trading halted (risk monitor triggered)")
                return

        self.live_trade(target_positions)

        logger.info("[OK] Live rebalance completed")

    def live_trade(self, target_positions, confirm_fills=True):
        """实盘交易（Paper Trading）。

        Parameters
        ----------
        target_positions : dict
            {symbol: target_value}
        confirm_fills : bool, optional
            是否等待成交确认。
        """
        if not self.executor:
            logger.error("Alpaca Paper Trading not enabled")
            return

        if self.risk_monitor and self.risk_monitor.trading_halted:
            logger.warning("[WARN] Trading halted (risk monitor triggered)")
            return

        logger.info(f"\n{'='*60}")
        logger.info(f"Executing live trades")
        logger.info(f"{'='*60}")

        account = self.executor.get_account()
        if account:
            logger.info(f"Account cash: ${account['cash']:,.2f}")
            logger.info(f"Portfolio value: ${account['portfolio_value']:,.2f}")
        else:
            logger.error("Cannot get account info, trading paused")
            return

        portfolio_value = account['portfolio_value']
        if self.risk_monitor:
            positions = self.executor.get_positions()
            self.risk_monitor.check_concentration_risk(positions, portfolio_value)
            if self._last_live_portfolio_value is not None and self._last_live_portfolio_value > 0:
                daily_return = (portfolio_value - self._last_live_portfolio_value) / self._last_live_portfolio_value
                self.risk_monitor.check_daily_loss(daily_return)
            if self.risk_monitor.trading_halted:
                logger.warning("[WARN] Trading halted (risk monitor triggered)")
                return

        total_target = sum(target_positions.values())
        buying_power = account.get('buying_power', 0.0)
        if total_target > buying_power:
            logger.error(f"Total target amount ${total_target:,.2f} exceeds buying power ${buying_power:,.2f}, trading paused")
            return

        if ORDER_MGR_AVAILABLE:
            manager = RebalanceManager(self.executor)
            kwargs = {}
            if self.config:
                kwargs = {
                    'max_position_pct': self.config.risk.max_position_pct,
                    'max_wait_sec': self.config.trading.max_wait_sec,
                    'poll_interval': self.config.trading.poll_interval,
                    'min_notional': 1.0,
                }
            results = manager.rebalance(
                target_positions,
                confirm_fills=confirm_fills,
                **kwargs
            )

            if COST_AVAILABLE:
                current_positions = {p['symbol']: p for p in self.executor.get_positions()}
                cost = TradingCostModel().estimate_portfolio_cost(
                    target_positions, current_positions
                )
                logger.info(f"\nEstimated trading cost: ${cost['total_cost']:.2f}")
        else:
            self.executor.rebalance_portfolio(target_positions)

        if self.risk_monitor:
            positions = self.executor.get_positions()
            account = self.executor.get_account()
            portfolio_value = account['portfolio_value'] if account else portfolio_value
            self.risk_monitor.check_position_limits(positions, portfolio_value)
            self._last_live_portfolio_value = portfolio_value

    # ------------------------------------------------------------------
    # BaseStrategy implementation: risk / status
    # ------------------------------------------------------------------

    def check_risk(self, nav=None, vix=None, positions=None, portfolio_value=None):
        """风险检查。

        Parameters
        ----------
        nav : float, optional
            当前 NAV。
        vix : float, optional
            当前 VIX。
        positions : dict, optional
            当前持仓。
        portfolio_value : float, optional
            组合价值。
        """
        if not self.risk_monitor:
            return

        logger.info("\nRisk check:")

        if nav is not None:
            self.risk_monitor.check_drawdown(nav)

        if vix is not None:
            level = self.risk_monitor.check_vix_level(vix)
            logger.info(f"  VIX level: {vix:.1f} (risk level: {level})")

        if positions and portfolio_value:
            alerts = self.risk_monitor.check_position_limits(positions, portfolio_value)
            if alerts:
                logger.warning(f"  Triggered {len(alerts)} position alerts")

        summary = self.risk_monitor.get_risk_summary()
        logger.info(f"  Risk level: {summary['risk_level']}")
        logger.info(f"  Trading halted: {summary['trading_halted']}")

    def get_status(self):
        """获取策略状态。

        Returns
        -------
        dict
            策略状态摘要。
        """
        status = {
            'strategy': 'V14 MultiFactor',
            'version': '1.0',
            'real_data': self.use_real_data,
            'paper_trading': self.use_paper_trading,
            'risk_monitor': self.enable_risk_monitor,
            'trading_halted': self.risk_monitor.trading_halted if self.risk_monitor else False,
        }

        if self.executor:
            account = self.executor.get_account()
            if account:
                status['account'] = {
                    'cash': account['cash'],
                    'portfolio_value': account['portfolio_value'],
                }
                status['positions'] = self.executor.get_positions()

        return status

    # ------------------------------------------------------------------
    # V14-specific helpers
    # ------------------------------------------------------------------

    def _get_latest_vix(self):
        """获取最新 VIX - 仅使用 QuantConnect。"""
        if QC_DATA_AVAILABLE:
            try:
                source = HybridQCDataSource()
                vix = source.get_vix()
                if vix:
                    return vix
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                logger.warning(f"QuantConnect VIX network error: {e}")
            except ValueError as e:
                logger.warning(f"QuantConnect VIX data error: {e}")

        logger.warning("[WARN] Cannot get VIX, risk monitor using default state")
        return None

    def _generate_mock_data(self, start_date, end_date):
        """生成模拟数据。"""
        logger.info("Generating mock data...")

        dates = pd.bdate_range(start_date, end_date)
        n_days = len(dates)

        np.random.seed(42)
        prices = np.zeros((n_days, len(TICKERS)))
        prices[0] = np.random.uniform(20, 200, len(TICKERS))
        market_ret = np.random.normal(0.0003, 0.012, n_days)

        for i in range(1, n_days):
            for j, t in enumerate(TICKERS):
                ind = INDUSTRY.get(t, 'other')
                vol = {'semi': 0.022, 'tech': 0.018, 'finance': 0.014,
                       'health': 0.012, 'energy': 0.020, 'industrial': 0.015,
                       'utility': 0.010, 'consumer': 0.013, 'media': 0.016,
                       'telecom': 0.012}.get(ind, 0.015)
                ret = np.random.normal(0.0003, vol) + 0.4 * market_ret[i]
                prices[i, j] = prices[i-1, j] * (1 + ret)

        price_df = pd.DataFrame(prices, index=dates, columns=TICKERS)
        price_df = price_df.replace(0, np.nan).ffill()

        vix = np.clip(15 + np.cumsum(np.random.normal(0, 0.5, n_days)) * 0.08, 9, 55)
        market_df = pd.DataFrame({
            'VIX': vix,
            'RSI': np.random.uniform(30, 70, n_days)
        }, index=dates)

        return price_df, market_df

    def _print_performance(self, result):
        """打印绩效。"""
        if len(result) == 0:
            logger.warning("Backtest result is empty")
            return

        # 优先使用扣除交易成本后的 NAV
        nav_col = 'nav_after_cost' if 'nav_after_cost' in result.columns else 'nav'
        nav = result[nav_col]
        returns = nav.pct_change().dropna()

        years = (result['date'].iloc[-1] - result['date'].iloc[0]).days / 365.25
        cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1/years) - 1

        # 根据调仓频率选择正确的年化系数
        rebalance_frequency = 'monthly'
        if self.config and hasattr(self.config, 'trading'):
            rebalance_frequency = getattr(self.config.trading, 'rebalance_frequency', 'monthly')
        periods_per_year = {
            'daily': 252,
            'weekly': 52,
            'monthly': 12,
            'bimonthly': 6,
            'quarterly': 4,
        }.get(rebalance_frequency, 12)

        vol = returns.std() * np.sqrt(periods_per_year)
        sharpe = cagr / vol if vol > 0 else 0
        maxdd = ((nav / nav.cummax()) - 1).min()

        logger.info(f"\n{'='*60}")
        logger.info(f"Backtest performance")
        logger.info(f"{'='*60}")
        logger.info(f"  Period: {result['date'].iloc[0]} ~ {result['date'].iloc[-1]}")
        logger.info(f"  Rebalance frequency: {rebalance_frequency}")
        logger.info(f"  Rebalance count: {len(result)}")
        logger.info(f"  NAV column: {nav_col}")
        logger.info(f"  Final NAV: {nav.iloc[-1]:.4f}")
        logger.info(f"  CAGR: {cagr:.2%}")
        logger.info(f"  Sharpe: {sharpe:.3f}")
        logger.info(f"  MaxDD: {maxdd:.2%}")
        logger.info(f"  Volatility: {vol:.2%}")
        logger.info(f"  Win rate: {(returns > 0).mean():.1%}")
