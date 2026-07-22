"""
StrategyPortfolio - 多策略组合管理器

负责：
1. 维护多个子策略及其组合权重
2. 每个策略独立选股、独立回测
3. 组合层面按权重分配资金、聚合目标持仓
4. 组合层面统一风控与执行

用法:
    from strategies.portfolio import StrategyPortfolio
    from strategies.v14 import MultiFactorStrategy
    from strategies.momentum import MomentumStrategy
    from strategies.value import ValueStrategy

    portfolio = StrategyPortfolio(
        strategies=[
            ('multifactor', MultiFactorStrategy(use_real_data=True), 0.4),
            ('momentum', MomentumStrategy(use_real_data=True), 0.3),
            ('value', ValueStrategy(use_real_data=True), 0.3),
        ],
        enable_risk_monitor=True,
        use_paper_trading=True,
        paper=True,
    )
    portfolio.run_backtest('2020-01-01', '2024-01-01')
    portfolio.run_live_rebalance()
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# 可选模块：失败时优雅回退
try:
    from alpaca_executor import AlpacaExecutor, ALPACA_AVAILABLE
except ImportError:
    AlpacaExecutor = None
    ALPACA_AVAILABLE = False

try:
    from order_manager import RebalanceManager
    ORDER_MGR_AVAILABLE = True
except ImportError:
    RebalanceManager = None
    ORDER_MGR_AVAILABLE = False

try:
    from risk_monitor import RiskMonitor
    RISK_AVAILABLE = True
except ImportError:
    RiskMonitor = None
    RISK_AVAILABLE = False

try:
    from weight_allocation import (
        normalize_target_positions,
        apply_sector_constraints,
        apply_volatility_target,
    )
    WEIGHT_ALLOC_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_AVAILABLE = False

    def normalize_target_positions(target_positions, max_total_value, min_position_value=0):
        total = sum(target_positions.values())
        if total <= max_total_value:
            return target_positions
        scale = max_total_value / total if total > 0 else 1.0
        return {s: v * scale for s, v in target_positions.items()}

    def apply_sector_constraints(weights, sectors, max_sector_pct=0.30, max_iter=20):
        return weights

    def apply_volatility_target(target_positions, price_df, target_vol=0.20, lookback=60):
        return target_positions

try:
    from main import INDUSTRY, TICKERS
except ImportError:
    INDUSTRY = {}
    TICKERS = []

try:
    from quantconnect_data import prepare_backtest_data_qc, HybridQCDataSource
    QC_DATA_AVAILABLE = True
except ImportError:
    QC_DATA_AVAILABLE = False

try:
    from config import get_config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False

try:
    from risk_overlay import RiskOverlayAdvisor, apply_risk_overlay_to_positions
    RISK_OVERLAY_AVAILABLE = True
except ImportError:
    RiskOverlayAdvisor = None
    apply_risk_overlay_to_positions = None
    RISK_OVERLAY_AVAILABLE = False

try:
    from regime_allocator import RegimeAllocator, DEFAULT_REGIME_DETECTOR as regime_detect
    REGIME_ALLOC_AVAILABLE = True
except ImportError:
    regime_detect = None
    RegimeAllocator = None
    REGIME_ALLOC_AVAILABLE = False


class StrategyPortfolio:
    """多策略组合管理器。

    每个子策略独立生成目标持仓，组合按配置权重分配资金，
    并在组合层面做行业集中度、波动率目标等 overlay。

    Parameters
    ----------
    strategies : list of (name, BaseStrategy, weight)
        子策略三元组列表。weight 为组合内资金权重，总和应接近 1.0。
    enable_risk_monitor : bool
        是否启用组合级风控。
    use_paper_trading : bool
        是否连接 Alpaca 执行交易。
    paper : bool
        True=Paper, False=Live（仅当 use_paper_trading=True 时有效）。
    config : Any, optional
        配置对象。默认从 config.get_config() 获取。
    regime_allocator : RegimeAllocator, optional
        市场状态感知的子策略权重分配器。传入即启用；未传入时若
        config.risk.regime_allocator_enabled=True 则自动创建默认实例。
        启用后 generate_signals() 会根据 regime_detect() 的输出动态调整
        各子策略权重（默认关闭，保持既有静态权重行为）。
    """

    def __init__(
        self,
        strategies: List[Tuple[str, BaseStrategy, float]],
        enable_risk_monitor: bool = True,
        use_paper_trading: bool = False,
        paper: bool = True,
        config: Optional[Any] = None,
        regime_allocator: Optional[Any] = None,
    ):
        if not strategies:
            raise ValueError("strategies 不能为空")

        self.config = config or (get_config() if CONFIG_AVAILABLE else None)
        self.use_paper_trading = use_paper_trading and ALPACA_AVAILABLE
        self.paper = paper
        self.enable_risk_monitor = enable_risk_monitor and RISK_AVAILABLE

        # 子策略归一化权重
        total_weight = sum(w for _, _, w in strategies)
        if total_weight <= 0:
            raise ValueError("策略权重总和必须 > 0")
        self.strategies: List[Dict[str, Any]] = []
        for name, strategy, weight in strategies:
            if not isinstance(strategy, BaseStrategy):
                raise TypeError(f"策略 {name} 必须继承 BaseStrategy")
            self.strategies.append({
                'name': name,
                'strategy': strategy,
                'weight': weight / total_weight,
                'backtest_result': None,
                'last_signals': None,
            })

        self.risk_monitor = None
        self.executor = None
        self._last_live_portfolio_value = None

        # 风控 overlay（动态杠杆 / 回撤守卫 / 市场状态调整），默认关闭，
        # 通过 config.risk.risk_overlay_enabled = true 启用
        self.risk_overlay = None
        if RISK_OVERLAY_AVAILABLE and self.config and hasattr(self.config, 'risk'):
            risk_cfg = self.config.risk
            if getattr(risk_cfg, 'risk_overlay_enabled', False):
                self.risk_overlay = RiskOverlayAdvisor(
                    target_vol=getattr(risk_cfg, 'target_vol', 0.20),
                    max_dd=getattr(risk_cfg, 'max_drawdown_limit', 0.15),
                    max_leverage=getattr(risk_cfg, 'max_leverage', 1.5),
                    min_leverage=getattr(risk_cfg, 'min_leverage', 0.5),
                    enabled=True,
                )
                logger.info("[OK] Risk overlay advisor enabled "
                            f"(target_vol={self.risk_overlay.target_vol:.0%}, "
                            f"max_dd={self.risk_overlay.max_dd:.0%}, "
                            f"leverage=[{self.risk_overlay.min_leverage}, {self.risk_overlay.max_leverage}])")

        # Regime-aware 子策略权重分配，默认关闭；
        # 显式传入 regime_allocator 或 config.risk.regime_allocator_enabled=true 启用
        self.regime_allocator = regime_allocator
        if self.regime_allocator is None and REGIME_ALLOC_AVAILABLE and RegimeAllocator is not None:
            if self.config and hasattr(self.config, 'risk') and \
                    getattr(self.config.risk, 'regime_allocator_enabled', False):
                self.regime_allocator = RegimeAllocator(
                    min_weight=getattr(self.config.risk, 'regime_allocator_min_weight', 0.05),
                    max_step=getattr(self.config.risk, 'regime_allocator_max_step', 0.10),
                    enabled=True,
                )
        if self.regime_allocator is not None:
            logger.info(f"[OK] Regime-aware allocation enabled: {self.regime_allocator}")

        # 初始化风控
        if self.enable_risk_monitor and RiskMonitor is not None:
            risk_kwargs = self._build_risk_kwargs()
            self.risk_monitor = RiskMonitor(**risk_kwargs)
            logger.info("[OK] Portfolio risk monitor enabled")

        # 最小持仓金额（从配置读取）
        self.min_position_value = 0.0
        if self.config and hasattr(self.config, 'trading') and hasattr(self.config.trading, 'min_position_value'):
            self.min_position_value = self.config.trading.min_position_value

        # 初始化执行器
        if self.use_paper_trading:
            executor_kwargs = self._build_executor_kwargs()
            self.executor = AlpacaExecutor(**executor_kwargs)
            mode = 'PAPER' if paper else 'LIVE'
            logger.info(f"[OK] Alpaca {mode} executor enabled")
            if self.risk_monitor and hasattr(self.executor, 'set_risk_monitor'):
                self.executor.set_risk_monitor(self.risk_monitor)

        logger.info(f"[OK] StrategyPortfolio initialized with {len(self.strategies)} strategies")
        for s in self.strategies:
            logger.info(f"  - {s['name']}: weight={s['weight']:.2%}")

    # ------------------------------------------------------------------
    # 构造辅助
    # ------------------------------------------------------------------

    def _build_risk_kwargs(self) -> Dict[str, Any]:
        """从配置中提取风控参数。"""
        if not self.config or not hasattr(self.config, 'risk'):
            return {
                'max_drawdown_limit': 0.15,
                'max_position_pct': 0.20,
                'max_sector_pct': 0.30,
                'daily_loss_limit': 0.03,
                'vix_pause_level': 35.0,
            }
        risk_config = self.config.risk
        daily_loss = getattr(risk_config, 'daily_loss_limit', None)
        if daily_loss is None:
            daily_loss = getattr(risk_config, 'max_intraday_dd', 0.03)
        kwargs = {
            'max_drawdown_limit': getattr(risk_config, 'max_drawdown_limit', 0.15),
            'max_position_pct': getattr(risk_config, 'max_position_pct', 0.20),
            'max_sector_pct': getattr(risk_config, 'max_sector_pct', 0.30),
            'daily_loss_limit': daily_loss,
            'vix_pause_level': getattr(risk_config, 'vix_panic_threshold', 35.0),
        }
        return kwargs

    def _build_executor_kwargs(self) -> Dict[str, Any]:
        """从配置中提取执行器参数。"""
        if not self.config:
            return {'paper': self.paper}
        return {
            'base_url': self.config.alpaca_base_url,
            'paper': self.paper,
            'enable_pdt': getattr(self.config.trading, 'enable_pdt_check', True),
            'pdt_min_equity': getattr(self.config.trading, 'pdt_min_equity', 25000.0),
            'use_limit_orders': getattr(self.config.trading, 'use_limit_orders', False),
            'limit_order_offset_pct': getattr(self.config.trading, 'limit_order_offset_pct', 0.001),
        }

    # ------------------------------------------------------------------
    # 回测
    # ------------------------------------------------------------------

    def run_backtest(self, start_date: Optional[str] = None,
                     end_date: Optional[str] = None, **kwargs) -> pd.DataFrame:
        """组合回测：每个子策略按权重独立回测，聚合为组合收益曲线。

        Returns
        -------
        pd.DataFrame
            组合层面的回测结果（NAV 曲线）。
        """
        individual = self.run_individual_backtests(start_date, end_date, **kwargs)
        if not individual:
            logger.error("[ERROR] 所有子策略回测均失败")
            return pd.DataFrame()

        # 按权重聚合 NAV 曲线
        nav_curves = []
        for item in self.strategies:
            name = item['name']
            result = item['backtest_result']
            if result is None or len(result) == 0:
                continue
            nav_col = 'nav_after_cost' if 'nav_after_cost' in result.columns else 'nav'
            if nav_col not in result.columns:
                continue
            df = result[['date', nav_col]].copy()
            df = df.rename(columns={nav_col: name})
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            # 去重：同一日期保留最后一条记录
            df = df[~df.index.duplicated(keep='last')]
            # 统一归一化到 1.0 起点，解决 V14 归一化 NAV 与 子策略绝对 NAV 混合加权失真
            first = df.iloc[0, 0]
            df = df / first if first != 0 else df
            nav_curves.append(df)

        if not nav_curves:
            logger.error("[ERROR] 无可用的 NAV 曲线")
            return pd.DataFrame()

        # 对齐日期并计算加权 NAV
        aligned = pd.concat(nav_curves, axis=1).ffill().dropna()
        weights = {item['name']: item['weight'] for item in self.strategies}
        weights_series = pd.Series({k: weights[k] for k in aligned.columns})
        portfolio_nav = (aligned * weights_series).sum(axis=1)

        result = pd.DataFrame({
            'date': portfolio_nav.index,
            'nav': portfolio_nav.values,
        })

        # 打印绩效
        self._print_portfolio_performance(result, individual)
        return result

    def run_individual_backtests(self, start_date: Optional[str] = None,
                                 end_date: Optional[str] = None, **kwargs) -> Dict[str, pd.DataFrame]:
        """单独回测每个子策略。

        Returns
        -------
        dict
            {strategy_name: backtest_result}
        """
        results = {}
        logger.info(f"\n{'='*60}")
        logger.info("Running individual backtests for each strategy")
        logger.info(f"{'='*60}")
        for item in self.strategies:
            name = item['name']
            strategy = item['strategy']
            logger.info(f"\n--- Strategy: {name} (weight={item['weight']:.2%}) ---")
            try:
                result = strategy.run_backtest(start_date, end_date, **kwargs)
                item['backtest_result'] = result
                results[name] = result
            except Exception as e:
                logger.error(f"[ERROR] Backtest failed for {name}: {e}")
                item['backtest_result'] = None
                results[name] = pd.DataFrame()
        return results

    # ------------------------------------------------------------------
    # 信号生成 / 调仓
    # ------------------------------------------------------------------

    def generate_signals(self, total_value: Optional[float] = None,
                         live_mode: bool = False) -> Dict[str, float]:
        """组合层面生成目标持仓。

        Parameters
        ----------
        total_value : float, optional
            组合总资金。默认从 executor 账户获取。
        live_mode : bool
            是否实盘模式（用于日志提示）。

        Returns
        -------
        dict
            {symbol: target_value} 聚合目标持仓。
        """
        if total_value is None:
            if self.executor:
                try:
                    account = self.executor.get_account()
                    total_value = account['portfolio_value'] if account else 1_000_000.0
                except Exception as e:
                    logger.warning(f"Failed to get account value: {e}, using $1M")
                    total_value = 1_000_000.0
            else:
                total_value = 1_000_000.0

        logger.info(f"\n{'='*60}")
        logger.info(f"Generating portfolio signals (total_value=${total_value:,.2f})")
        logger.info(f"{'='*60}")

        # 组合层只加载一次数据，注入所有子策略，避免 5× 重复 IO/因子计算
        shared_price_df, shared_market_df = None, None
        if QC_DATA_AVAILABLE and TICKERS:
            try:
                end = datetime.now().strftime('%Y-%m-%d')
                start = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')
                shared_price_df, shared_market_df = prepare_backtest_data_qc(
                    TICKERS, start, end, resolution='daily'
                )
                self._shared_price_df = shared_price_df
                logger.info(f"[SHARED] Loaded shared price data: {shared_price_df.shape}")
            except Exception as e:
                logger.warning(f"[SHARED] Failed to load shared data: {e}")
        shared_vix = None
        if shared_market_df is not None and 'VIX' in shared_market_df.columns:
            shared_vix = float(shared_market_df['VIX'].iloc[-1])

        # Regime-aware 权重调整（opt-in）：按市场状态动态调整子策略资金权重
        if self.regime_allocator is not None and regime_detect is not None:
            try:
                regime = regime_detect(shared_price_df, shared_vix)
                current_weights = {item['name']: item['weight'] for item in self.strategies}
                new_weights = self.regime_allocator.allocate(regime, current_weights)
                for item in self.strategies:
                    if item['name'] in new_weights:
                        item['weight'] = new_weights[item['name']]
                logger.info(f"[REGIME_ALLOC] Applied regime-adjusted weights (regime={regime})")
            except Exception as e:
                logger.warning(f"[REGIME_ALLOC] Failed, keeping static weights: {e}")

        aggregated = {}  # symbol -> list of (target_value, strategy_name)
        for item in self.strategies:
            name = item['name']
            strategy = item['strategy']
            alloc = total_value * item['weight']
            signals = strategy.generate_signals(
                price_df=shared_price_df,
                vix=shared_vix,
                capital=alloc,
                live_mode=live_mode,
            )
            item['last_signals'] = signals

            if not signals:
                logger.warning(f"[WARN] {name} generated empty signals")
                continue

            logger.info(f"[{name}] target=${sum(signals.values()):,.2f} (alloc=${alloc:,.2f}), n={len(signals)}")
            for s, v in signals.items():
                aggregated.setdefault(s, []).append((v, name))

        # 合并同名标的：简单加总（过滤 NaN，避免某个子策略的 NaN 污染组合）
        target_positions = {}
        for s, values in aggregated.items():
            total = sum(v for v, _ in values if pd.notna(v))
            target_positions[s] = total

        # 归一化到 total_value
        target_positions = normalize_target_positions(target_positions, total_value, min_position_value=self.min_position_value)

        # 组合层面行业集中度约束
        if WEIGHT_ALLOC_AVAILABLE and target_positions:
            max_sector_pct = 0.30
            if self.config and hasattr(self.config, 'risk') and hasattr(self.config.risk, 'max_sector_pct'):
                max_sector_pct = self.config.risk.max_sector_pct
            if not INDUSTRY:
                logger.warning("[WARN] INDUSTRY mapping empty, skipping sector constraint")
            else:
                total = sum(target_positions.values())
                weights = {s: v / total for s, v in target_positions.items()}
                weights = apply_sector_constraints(weights, INDUSTRY, max_sector_pct=max_sector_pct)
                target_positions = {s: weights.get(s, 0.0) * total for s in target_positions}

        # 组合层面目标波动率 overlay
        # 需要获取价格数据 —— 从子策略中尝试
        price_df = self._get_common_price_df()
        if WEIGHT_ALLOC_AVAILABLE and target_positions and price_df is not None:
            target_positions = apply_volatility_target(
                target_positions, price_df, target_vol=0.20, lookback=60
            )
            target_positions = normalize_target_positions(target_positions, total_value, min_position_value=self.min_position_value)

        # 组合层面风险 overlay：市场状态调整 + 动态杠杆 + 回撤守卫
        if self.risk_overlay is not None and target_positions:
            nav_series = self._get_nav_series()
            leverage, exposure = self.risk_overlay.recommend(
                price_df=price_df,
                vix=shared_vix,
                nav_series=nav_series,
            )
            if leverage != 1.0 or exposure != 1.0:
                target_positions = apply_risk_overlay_to_positions(
                    target_positions, leverage=leverage, exposure_scale=exposure
                )
                logger.info(f"[RISK_OVERLAY] regime={self.risk_overlay.last_regime}, "
                            f"leverage={leverage:.2f}x, exposure={exposure:.2f}, "
                            f"total=${sum(target_positions.values()):,.2f}")

        logger.info(f"[PORTFOLIO] Aggregated target positions: ${sum(target_positions.values()):,.2f}, n={len(target_positions)}")
        for s, v in sorted(target_positions.items(), key=lambda x: x[1], reverse=True)[:10]:
            logger.info(f"  {s}: ${v:,.0f}")

        return target_positions

    def _get_common_price_df(self) -> Optional[pd.DataFrame]:
        """返回组合层共享的 price_df，用于 vol target overlay。"""
        if hasattr(self, '_shared_price_df') and self._shared_price_df is not None:
            return self._shared_price_df
        return None

    def _get_nav_series(self) -> Optional[pd.Series]:
        """返回组合 NAV 序列，供风险 overlay 计算回撤。

        优先使用 RiskMonitor 的实盘 nav_history（与风控口径一致）；
        否则返回 None（overlay 将按零回撤处理）。
        """
        if self.risk_monitor is not None and getattr(self.risk_monitor, 'nav_history', None):
            history = self.risk_monitor.nav_history
            if len(history) >= 2:
                return pd.Series(
                    [h['nav'] for h in history],
                    index=pd.to_datetime([h['timestamp'] for h in history]),
                )
        return None

    def run_live_rebalance(self):
        """执行组合层面实盘调仓。"""
        if not self.executor:
            logger.error("[ERROR] Alpaca executor not enabled")
            return

        # 风控检查
        if self.risk_monitor:
            self.risk_monitor.check_remote_kill_switch()
            if self.risk_monitor.trading_halted:
                logger.warning("[WARN] Trading halted by remote kill switch")
                return

        # 市场检查
        if hasattr(self.executor, 'market_is_open') and not self.executor.market_is_open():
            logger.warning("[WARN] Market not open, skipping rebalance")
            return

        # 检查 open orders
        try:
            open_orders = self.executor.get_orders(status='open') if hasattr(self.executor, 'get_orders') else []
            if open_orders:
                logger.warning(f"[WARN] {len(open_orders)} open orders exist, aborting to avoid double-trading")
                return
        except Exception as e:
            logger.warning(f"[WARN] Failed to check open orders: {e}")

        self.executor.start_rebalance_session() if hasattr(self.executor, 'start_rebalance_session') else None

        target_positions = self.generate_signals(live_mode=True)
        if not target_positions:
            logger.error("[ERROR] Signal generation failed, skipping trade")
            return

        # 再次风控检查
        if self.risk_monitor:
            account = self.executor.get_account()
            portfolio_value = account['portfolio_value'] if account else 0
            positions = self.executor.get_positions() if hasattr(self.executor, 'get_positions') else []
            self.risk_monitor.check_concentration_risk(positions, portfolio_value)
            if self.risk_monitor.trading_halted:
                logger.warning("[WARN] Trading halted (risk monitor triggered)")
                return

        # 执行
        self._execute_live_trades(target_positions)
        logger.info("[OK] Portfolio live rebalance completed")

    def _execute_live_trades(self, target_positions: Dict[str, float]):
        """组合层面执行交易。

        优先使用 executor 的 rebalance_portfolio（含 atomic precheck、流动性检查、
        PDT 预估算、drawdown 检查），退回到 RebalanceManager。
        """
        # 优先走 AlpacaExecutor.rebalance_portfolio 全风控路径
        if hasattr(self.executor, 'rebalance_portfolio'):
            self.executor.rebalance_portfolio(target_positions)
        elif ORDER_MGR_AVAILABLE and RebalanceManager is not None:
            manager = RebalanceManager(self.executor)
            kwargs = {}
            if self.config:
                kwargs = {
                    'max_position_pct': self.config.risk.max_position_pct,
                    'max_wait_sec': self.config.trading.max_wait_sec,
                    'poll_interval': self.config.trading.poll_interval,
                    'min_notional': 1.0,
                }
            manager.rebalance(target_positions, confirm_fills=True, **kwargs)
        else:
            logger.error("[ERROR] Executor does not support rebalance_portfolio")

        # 执行后对账
        if hasattr(self.executor, 'reconcile_positions'):
            try:
                report = self.executor.reconcile_positions()
                if not report.get('ok', True):
                    logger.warning(f"[RECONCILE] {report}")
            except Exception as e:
                logger.warning(f"[RECONCILE] failed: {e}")

        # 保存状态
        if self.risk_monitor:
            account = self.executor.get_account()
            portfolio_value = account['portfolio_value'] if account else 0
            self._last_live_portfolio_value = portfolio_value
            self.risk_monitor.persist_state()

    # ------------------------------------------------------------------
    # 状态 / 绩效
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """获取组合状态。"""
        status = {
            'portfolio': 'StrategyPortfolio',
            'strategies': [
                {
                    'name': item['name'],
                    'weight': item['weight'],
                    'type': item['strategy'].__class__.__name__,
                }
                for item in self.strategies
            ],
            'risk_monitor': self.enable_risk_monitor,
            'trading_halted': self.risk_monitor.trading_halted if self.risk_monitor else False,
            'paper_trading': self.use_paper_trading,
        }
        if self.executor:
            account = self.executor.get_account()
            if account:
                status['account'] = {
                    'cash': account['cash'],
                    'portfolio_value': account['portfolio_value'],
                }
                status['positions'] = self.executor.get_positions() if hasattr(self.executor, 'get_positions') else []
        return status

    def _print_portfolio_performance(self, result: pd.DataFrame, individual: Dict[str, pd.DataFrame]):
        """打印组合绩效。"""
        if len(result) == 0:
            return

        nav = result['nav']
        returns = nav.pct_change().dropna()
        years = (result['date'].iloc[-1] - result['date'].iloc[0]).days / 365.25
        cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / max(years, 1e-6)) - 1
        # 根据实际 rebalance 频率推断年化期数（与 V14 保持一致）
        periods_per_year = max(1, int(round(len(result) / max(years, 1e-6))))
        vol = returns.std() * np.sqrt(periods_per_year)
        sharpe = cagr / vol if vol > 0 else 0
        maxdd = ((nav / nav.cummax()) - 1).min()

        logger.info(f"\n{'='*60}")
        logger.info("Portfolio backtest performance")
        logger.info(f"{'='*60}")
        logger.info(f"  Period: {result['date'].iloc[0]} ~ {result['date'].iloc[-1]}")
        logger.info(f"  Final NAV: {nav.iloc[-1]:.4f}")
        logger.info(f"  CAGR: {cagr:.2%}")
        logger.info(f"  Sharpe: {sharpe:.3f}")
        logger.info(f"  MaxDD: {maxdd:.2%}")
        logger.info(f"  Volatility: {vol:.2%}")

        logger.info("\nIndividual strategy performance:")
        for name, df in individual.items():
            if df is None or len(df) == 0:
                continue
            nav_col = 'nav_after_cost' if 'nav_after_cost' in df.columns else 'nav'
            if nav_col not in df.columns:
                continue
            s_nav = df[nav_col]
            s_cagr = (s_nav.iloc[-1] / s_nav.iloc[0]) ** (1 / max(years, 1e-6)) - 1
            s_returns = s_nav.pct_change().dropna()
            s_periods_per_year = max(1, int(round(len(df) / max(years, 1e-6))))
            s_vol = s_returns.std() * np.sqrt(s_periods_per_year)
            s_sharpe = s_cagr / s_vol if s_vol > 0 else 0
            s_maxdd = ((s_nav / s_nav.cummax()) - 1).min()
            logger.info(f"  {name}: CAGR={s_cagr:.2%}, Sharpe={s_sharpe:.3f}, MaxDD={s_maxdd:.2%}")

    def __repr__(self) -> str:
        return f"StrategyPortfolio(strategies={len(self.strategies)}, paper={self.use_paper_trading})"
