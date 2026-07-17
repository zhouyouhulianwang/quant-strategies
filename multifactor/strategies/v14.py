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
    logger.info("✅ QuantConnect 数据源可用")
except ImportError:
    QC_DATA_AVAILABLE = False
    logger.warning("quantconnect_data 模块不可用")

YAHOO_DATA_AVAILABLE = False

try:
    from alpaca_executor import AlpacaPaperExecutor, V14AlpacaExecutor
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    logger.warning("alpaca_executor 模块不可用")

try:
    from order_manager import RebalanceManager
    ORDER_MGR_AVAILABLE = True
except ImportError:
    ORDER_MGR_AVAILABLE = False
    logger.warning("order_manager 模块不可用")

try:
    from cost_model import TradingCostModel, apply_costs_to_backtest
    COST_AVAILABLE = True
except ImportError:
    COST_AVAILABLE = False
    logger.warning("cost_model 模块不可用")

try:
    from visualization import generate_full_report
    VIZ_AVAILABLE = True
except ImportError:
    VIZ_AVAILABLE = False
    logger.warning("visualization 模块不可用")

try:
    from risk_monitor import RiskMonitor
    RISK_AVAILABLE = True
except ImportError:
    RISK_AVAILABLE = False
    logger.warning("risk_monitor 模块不可用")

try:
    from intraday_monitor import IntradayMonitor
    INTRADAY_AVAILABLE = True
except ImportError:
    INTRADAY_AVAILABLE = False
    logger.warning("intraday_monitor 模块不可用")

try:
    from weight_allocation import WeightAllocator, normalize_target_positions
    WEIGHT_ALLOC_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_AVAILABLE = False
    logger.warning("weight_allocation 模块不可用")

try:
    from config import V14StrategyConfig, get_config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    logger.warning("config 模块不可用")

# 导入 V14 因子核心（策略模型层）
from main import (
    TICKERS, INDUSTRY, NDX_SET,
    compute_factors_v14, v14_composite_score, v14_scale, run_v14
)


class V14Strategy(BaseStrategy):
    """V14 多因子策略的完整封装类，继承 BaseStrategy 以复用通用接口。"""

    def __init__(self,
                 use_real_data=True,
                 use_paper_trading=False,
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
            是否使用 Alpaca Paper Trading（默认 False）。
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
            logger.error("❌ 真实数据源不可用 (QuantConnect)")
            logger.error("   请配置 QuantConnect Lean CLI")
            self.use_real_data = False
        else:
            self.use_real_data = use_real_data and has_real_data

        self.use_paper_trading = use_paper_trading and ALPACA_AVAILABLE
        self.enable_risk_monitor = enable_risk_monitor and RISK_AVAILABLE

        if not self.use_real_data:
            logger.warning("⚠️ 当前使用模拟数据，回测结果仅供测试参考")
            logger.warning("   生产环境请确保真实数据源可用")

        # 初始化各模块
        self.executor = None
        self.risk_monitor = None
        self.intraday_monitor = None
        self.weight_allocator = None
        self.backtest_result = None
        self._last_live_portfolio_value = None

        if self.use_paper_trading:
            executor_kwargs = {}
            if self.config:
                executor_kwargs = {
                    'enable_pdt': self.config.trading.enable_pdt_check,
                    'pdt_min_equity': self.config.trading.pdt_min_equity,
                    'use_limit_orders': self.config.trading.use_limit_orders,
                    'limit_order_offset_pct': self.config.trading.limit_order_offset_pct,
                }
                logger.info(f"💰 限价单: {self.config.trading.use_limit_orders}, "
                           f"offset={self.config.trading.limit_order_offset_pct:.2%}")
                logger.info(f"🛡️ PDT 检查: {self.config.trading.enable_pdt_check}, "
                           f"min_equity=${self.config.trading.pdt_min_equity:,.0f}")
                logger.info(f"⏱️ 订单超时: {self.config.trading.max_wait_sec}秒, "
                           f"轮询间隔: {self.config.trading.poll_interval}秒")

            self.executor = V14AlpacaExecutor(**executor_kwargs)
            logger.info("✅ Alpaca Paper Trading 已启用")

        if self.enable_risk_monitor:
            self.risk_monitor = RiskMonitor()
            logger.info("✅ 风险监控已启用")

        # 盘中监控
        if enable_intraday_monitor and INTRADAY_AVAILABLE and self.executor and self.risk_monitor:
            check_interval = 60
            vix_emergency_level = 35.0
            max_total_drawdown = 0.15
            if self.config:
                check_interval = self.config.trading.check_interval
                vix_emergency_level = self.config.risk.vix_panic_threshold

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
                    except Exception as e:
                        logger.warning(f"盘中风控补充检查失败: {e}")

            self.intraday_monitor = V14IntradayMonitor(
                executor=self.executor,
                risk_monitor=self.risk_monitor,
                check_interval=check_interval,
                vix_emergency_level=vix_emergency_level,
                max_total_drawdown=max_total_drawdown
            )
            self.intraday_monitor.start()
            logger.info("✅ 盘中监控已启用")

        # 权重分配
        if WEIGHT_ALLOC_AVAILABLE:
            self.weight_allocator = WeightAllocator(method=weight_method)
            logger.info(f"✅ 权重分配: {weight_method}")

        logger.info("✅ V14 策略初始化完成")

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
        logger.info(f"V14 策略回测（统一信号逻辑）")
        logger.info(f"{'='*60}")
        logger.info(f"期间: {start_date} ~ {end_date}")
        logger.info(f"数据模式: {'真实数据' if self.use_real_data else '模拟数据'}")

        # 获取数据
        if self.use_real_data:
            price_df, market_df = None, None

            if QC_DATA_AVAILABLE:
                try:
                    price_df, market_df = prepare_backtest_data_qc(
                        TICKERS, start_date, end_date, resolution='daily'
                    )
                    if price_df is not None and len(price_df) > 0:
                        logger.info(f"📊 数据源: QuantConnect (Lean)")
                    else:
                        logger.warning("⚠️ QuantConnect 数据为空")
                        price_df, market_df = None, None
                except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                    logger.warning(f"⚠️ QuantConnect 获取网络失败: {e}")
                    price_df, market_df = None, None
                except ValueError as e:
                    logger.warning(f"⚠️ QuantConnect 数据错误: {e}")
                    price_df, market_df = None, None

            if price_df is None or len(price_df) == 0:
                logger.warning("⚠️ 无可用真实数据，使用模拟数据")
                price_df, market_df = self._generate_mock_data(start_date, end_date)
        else:
            price_df, market_df = self._generate_mock_data(start_date, end_date)

        # 检查数据有效性
        if price_df is None or len(price_df) == 0:
            logger.error("❌ 无法获取任何数据，回测失败")
            return pd.DataFrame()

        if market_df is None or len(market_df) == 0:
            logger.warning("⚠️ 市场数据为空，使用模拟 VIX")
            market_df = pd.DataFrame({'VIX': [20.0] * len(price_df)}, index=price_df.index)

        # 使用统一信号逻辑进行回测
        result = self._run_backtest_unified(price_df, market_df)

        if result is None or len(result) == 0:
            logger.error("❌ 回测失败，无结果数据")
            return pd.DataFrame()

        if COST_AVAILABLE:
            logger.info("应用交易成本...")
            result = apply_costs_to_backtest(result)

        self.backtest_result = result

        self._print_performance(result)

        if VIZ_AVAILABLE and len(result) > 0:
            logger.info("\n生成可视化报告...")
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
            logger.warning(f"⚠️ 未知调仓频率 '{rebalance_frequency}'，回退到 monthly")
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
            logger.error("❌ price_df 为空，无法回测")
            return pd.DataFrame()

        if not isinstance(price_df.index, pd.DatetimeIndex):
            logger.info(f"🔄 转换索引为 DatetimeIndex: {type(price_df.index).__name__}")
            try:
                price_df.index = pd.to_datetime(price_df.index)
            except (ValueError, TypeError) as e:
                logger.error(f"❌ 无法转换索引: {e}")
                return pd.DataFrame()

        if market_df is None or len(market_df) == 0:
            logger.warning("⚠️ market_df 为空，使用默认 VIX=20")
            market_df = pd.DataFrame({'VIX': [20.0] * len(price_df)}, index=price_df.index)
        elif 'VIX' not in market_df.columns:
            logger.warning("⚠️ market_df 缺少 VIX 列，使用默认 VIX=20")
            market_df['VIX'] = 20.0

        if not isinstance(market_df.index, pd.DatetimeIndex):
            try:
                market_df.index = pd.to_datetime(market_df.index)
            except (ValueError, TypeError) as e:
                logger.error(f"❌ 无法转换 market_df 索引: {e}")
                return pd.DataFrame()

        common_dates = price_df.index.intersection(market_df.index)
        if len(common_dates) == 0:
            logger.error("❌ price_df 和 market_df 没有共同日期")
            return pd.DataFrame()

        price_df = price_df.loc[common_dates]
        market_df = market_df.loc[common_dates]

        if len(price_df) < 252:
            logger.warning(f"⚠️ 数据不足 252 日 ({len(price_df)} 日)，无法预热")
            return pd.DataFrame()

        rebalance_frequency = 'monthly'
        if self.config and hasattr(self.config, 'trading'):
            rebalance_frequency = getattr(self.config.trading, 'rebalance_frequency', 'monthly')
        rebalance_dates = self._get_rebalance_dates(price_df, rebalance_frequency)
        rebalance_dates = rebalance_dates[rebalance_dates >= price_df.index[252]]

        if len(rebalance_dates) < 2:
            logger.warning(f"⚠️ 调仓日不足 2 个 (frequency={rebalance_frequency})，无法回测")
            return pd.DataFrame()

        logger.info(f"📅 回测调仓频率: {rebalance_frequency} ({len(rebalance_dates)} 个调仓日)")

        nav = 1.0
        prev_holdings = []
        prev_weights = {}
        records = []

        for i in range(1, len(rebalance_dates)):
            prev_d, curr_d = rebalance_dates[i-1], rebalance_dates[i]

            try:
                vix_v = float(market_df.loc[prev_d, 'VIX'])
            except (KeyError, TypeError, ValueError):
                vix_v = 20.0

            price_slice = price_df.loc[:prev_d].iloc[-252:]
            target_positions = self.generate_signals(price_slice, vix_v)

            selected = list(target_positions.keys()) if target_positions else []

            # 记录当前目标权重（用于收益计算和成本估算）
            total_target = sum(target_positions.values()) if target_positions else 0.0
            curr_weights = {s: v / total_target for s, v in target_positions.items()} if total_target > 0 else {}

            if prev_holdings and prev_weights:
                try:
                    p_start = price_df.loc[prev_d, prev_holdings].values
                    p_end = price_df.loc[curr_d, prev_holdings].values
                    returns = p_end / p_start - 1
                    sc = v14_scale(vix_v)
                    weights_arr = np.array([prev_weights.get(s, 0.0) for s in prev_holdings])
                    mr = np.dot(weights_arr, returns) * (sc / 100)
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"⚠️ 收益计算错误: {e}, 使用 0")
                    mr = 0
            else:
                mr = 0

            nav *= (1 + mr)

            records.append({
                'date': curr_d,
                'nav': nav,
                'mr': mr,
                'vix': vix_v,
                'n': len(selected),
                'holdings': selected,
                'weights': curr_weights,
            })
            prev_holdings = selected
            prev_weights = curr_weights

        return pd.DataFrame(records)

    # ------------------------------------------------------------------
    # BaseStrategy implementation: signal generation
    # ------------------------------------------------------------------

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

            if QC_DATA_AVAILABLE:
                logger.info("📊 信号生成数据源: QuantConnect")
                price_df, market_df = prepare_backtest_data_qc(
                    TICKERS, start, end, resolution='daily'
                )
                if vix is None:
                    vix = market_df['VIX'].iloc[-1]
            else:
                logger.error("无法获取数据，无可用数据源")
                return {}

        if vix is None:
            logger.error("VIX 数据缺失")
            return {}

        logger.info(f"\n{'='*60}")
        logger.info(f"生成交易信号")
        logger.info(f"{'='*60}")
        logger.info(f"当前 VIX: {vix:.2f}")
        logger.info(f"数据日期: {price_df.index[-1]}")

        if price_df is None or live_mode:
            freq_desc = ""
            if self.config and hasattr(self.config, 'trading'):
                freq = getattr(self.config.trading, 'rebalance_frequency', 'monthly')
                freq_desc = f"({freq} 再平衡)"
            logger.info(f"📌 信号基于历史 EOD 收盘价计算 {freq_desc}")
            if self.use_paper_trading:
                logger.info("📌 实盘执行时将使用当前实时价格计算股数")

        # 计算因子 (复用回测逻辑)
        price_slice = price_df.iloc[-252:]
        factors = compute_factors_v14(price_slice)
        score = v14_composite_score(factors, vix)

        # 仓位比例
        sc = v14_scale(vix)
        logger.info(f"目标仓位: {sc:.1f}%")

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

        logger.info(f"选股数量: {len(selected)} 只")
        logger.info(f"NDX 比例: {ndx_ratio:.2%}")
        logger.info(f"选中股票: {', '.join(selected[:10])}{'...' if len(selected) > 10 else ''}")

        # 获取账户价值
        if self.executor:
            try:
                account = self.executor.get_account()
                portfolio_value = account['portfolio_value'] if account else 1000000
            except (ConnectionError, TimeoutError, Timeout, RequestException) as e:
                logger.warning(f"获取账户价值网络失败: {e}，使用默认值 $1M")
                portfolio_value = 1000000
            except ValueError as e:
                logger.warning(f"获取账户价值参数错误: {e}，使用默认值 $1M")
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
            logger.info(f"权重分配: {self.weight_allocator.method}")
        else:
            target_value = (portfolio_value * sc / 100) / len(selected)
            target_positions = {s: target_value for s in selected}

        # 确保目标持仓总金额不超过组合价值 * 仓位比例
        max_total_value = portfolio_value * sc / 100
        target_positions = normalize_target_positions(target_positions, max_total_value)
        logger.info(f"📊 目标持仓总额: ${sum(target_positions.values()):,.0f} (上限: ${max_total_value:,.0f})")

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
            logger.warning("⚠️ 无可用数据源，无法获取历史信号")
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
            logger.warning(f"获取 {date} 信号失败: {e}")
            return {}

    # ------------------------------------------------------------------
    # BaseStrategy implementation: live rebalance / trading
    # ------------------------------------------------------------------

    def run_live_rebalance(self):
        """运行实盘再平衡 - 全自动流程。"""
        if not self.executor:
            logger.error("未启用 Alpaca Paper Trading")
            return

        if not self.executor.market_is_open():
            logger.warning("⚠️ 市场未开盘，跳过本次实盘调仓")
            logger.warning("   V14 是月末 EOD 策略，建议在开盘后执行")
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
            logger.warning(f"⚠️ 已过收盘前保护时间 {cutoff_hour:02d}:{cutoff_minute:02d} ET，拒绝启动新调仓")
            return

        self.executor.start_rebalance_session()

        target_positions = self.generate_signals(live_mode=True)

        if not target_positions:
            logger.error("信号生成失败，跳过交易")
            return

        if self.risk_monitor:
            vix = self._get_latest_vix()
            if vix:
                self.risk_monitor.check_vix_level(vix)

            if self.risk_monitor.trading_halted:
                logger.warning("⚠️ 交易已暂停（风险监控触发）")
                return

        self.live_trade(target_positions)

        logger.info("✅ 实盘再平衡完成")

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
            logger.error("未启用 Alpaca Paper Trading")
            return

        if self.risk_monitor and self.risk_monitor.trading_halted:
            logger.warning("⚠️ 交易已暂停（风险监控触发）")
            return

        logger.info(f"\n{'='*60}")
        logger.info(f"执行实盘交易")
        logger.info(f"{'='*60}")

        account = self.executor.get_account()
        if account:
            logger.info(f"账户现金: ${account['cash']:,.2f}")
            logger.info(f"组合价值: ${account['portfolio_value']:,.2f}")
        else:
            logger.error("无法获取账户信息，暂停交易")
            return

        portfolio_value = account['portfolio_value']
        if self.risk_monitor:
            positions = self.executor.get_positions()
            self.risk_monitor.check_concentration_risk(positions, portfolio_value)
            if self._last_live_portfolio_value is not None and self._last_live_portfolio_value > 0:
                daily_return = (portfolio_value - self._last_live_portfolio_value) / self._last_live_portfolio_value
                self.risk_monitor.check_daily_loss(daily_return)
            if self.risk_monitor.trading_halted:
                logger.warning("⚠️ 交易已暂停（风险监控触发）")
                return

        total_target = sum(target_positions.values())
        buying_power = account.get('buying_power', 0.0)
        if total_target > buying_power:
            logger.error(f"目标总金额 ${total_target:,.2f} 超过购买力 ${buying_power:,.2f}，暂停交易")
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
                logger.info(f"\n预估交易成本: ${cost['total_cost']:.2f}")
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

        logger.info("\n风险检查:")

        if nav is not None:
            self.risk_monitor.check_drawdown(nav)

        if vix is not None:
            level = self.risk_monitor.check_vix_level(vix)
            logger.info(f"  VIX 水平: {vix:.1f} (风险等级: {level})")

        if positions and portfolio_value:
            alerts = self.risk_monitor.check_position_limits(positions, portfolio_value)
            if alerts:
                logger.warning(f"  触发 {len(alerts)} 个仓位告警")

        summary = self.risk_monitor.get_risk_summary()
        logger.info(f"  风险等级: {summary['risk_level']}")
        logger.info(f"  交易暂停: {summary['trading_halted']}")

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
                logger.warning(f"QuantConnect 获取 VIX 网络错误: {e}")
            except ValueError as e:
                logger.warning(f"QuantConnect 获取 VIX 数据错误: {e}")

        logger.warning("⚠️ 无法获取 VIX，风控使用默认状态")
        return None

    def _generate_mock_data(self, start_date, end_date):
        """生成模拟数据。"""
        logger.info("生成模拟数据...")

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
            logger.warning("回测结果为空")
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
        logger.info(f"回测绩效")
        logger.info(f"{'='*60}")
        logger.info(f"  期间: {result['date'].iloc[0]} ~ {result['date'].iloc[-1]}")
        logger.info(f"  调仓频率: {rebalance_frequency}")
        logger.info(f"  调仓次数: {len(result)}")
        logger.info(f"  NAV 列: {nav_col}")
        logger.info(f"  Final NAV: {nav.iloc[-1]:.4f}")
        logger.info(f"  CAGR: {cagr:.2%}")
        logger.info(f"  Sharpe: {sharpe:.3f}")
        logger.info(f"  MaxDD: {maxdd:.2%}")
        logger.info(f"  波动率: {vol:.2%}")
        logger.info(f"  胜率: {(returns > 0).mean():.1%}")
