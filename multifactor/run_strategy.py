"""
V14 MultiFactor Strategy - 完整版
整合数据获取、回测、可视化、风控、实盘执行
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('v14_strategy')

# 尝试导入各模块

# 1. 优先 QuantConnect 数据源
try:
    from quantconnect_data import prepare_backtest_data_qc, HybridQCDataSource
    QC_DATA_AVAILABLE = True
    logger.info("✅ QuantConnect 数据源可用")
except ImportError:
    QC_DATA_AVAILABLE = False
    logger.warning("quantconnect_data 模块不可用")

# 2. 回退: 原 data_source (Yahoo Finance)
try:
    from data_source import prepare_backtest_data
    YAHOO_DATA_AVAILABLE = True
except ImportError:
    YAHOO_DATA_AVAILABLE = False
    logger.warning("data_source (Yahoo) 模块不可用")

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
    from weight_allocation import WeightAllocator
    WEIGHT_ALLOC_AVAILABLE = True
except ImportError:
    WEIGHT_ALLOC_AVAILABLE = False
    logger.warning("weight_allocation 模块不可用")

# 导入策略核心
from main import (
    TICKERS, INDUSTRY, NDX_SET,
    compute_factors_v14, v14_composite_score, v14_scale, run_v14
)


class V14Strategy:
    """V14 策略完整封装类"""
    
    def __init__(self, 
                 use_real_data=True,
                 use_paper_trading=False,
                 enable_risk_monitor=True,
                 enable_intraday_monitor=False,
                 weight_method='equal'):
        """
        初始化策略
        
        参数:
            use_real_data: bool, 使用真实数据（默认True）
            use_paper_trading: bool, 使用 Alpaca Paper Trading
            enable_risk_monitor: bool, 启用风险监控
            enable_intraday_monitor: bool, 启用盘中监控
            weight_method: str, 权重分配方法 ('equal' | 'risk_parity' | 'momentum_weighted')
        """
        # 检查数据源可用性
        has_real_data = QC_DATA_AVAILABLE or YAHOO_DATA_AVAILABLE
        
        if use_real_data and not has_real_data:
            logger.error("❌ 真实数据源不可用 (QuantConnect/Yahoo Finance)")
            logger.error("   请安装: pip install yfinance")
            logger.error("   或配置 QuantConnect Lean CLI")
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
        
        if self.use_paper_trading:
            self.executor = V14AlpacaExecutor()
            logger.info("✅ Alpaca Paper Trading 已启用")
        
        if self.enable_risk_monitor:
            self.risk_monitor = RiskMonitor()
            logger.info("✅ 风险监控已启用")
        
        # 盘中监控
        if enable_intraday_monitor and INTRADAY_AVAILABLE and self.executor and self.risk_monitor:
            self.intraday_monitor = IntradayMonitor(
                executor=self.executor,
                risk_monitor=self.risk_monitor,
                check_interval=60,
                vix_emergency_level=35.0
            )
            self.intraday_monitor.start()
            logger.info("✅ 盘中监控已启用")
        
        # 权重分配
        if WEIGHT_ALLOC_AVAILABLE:
            self.weight_allocator = WeightAllocator(method=weight_method)
            logger.info(f"✅ 权重分配: {weight_method}")
        
        logger.info("✅ V14 策略初始化完成")
    
    def run_backtest(self, start_date=None, end_date=None, use_cache=True):
        """
        运行回测 - 使用与实盘相同的信号生成逻辑
        
        参数:
            start_date: str, 'YYYY-MM-DD'
            end_date: str, 'YYYY-MM-DD'
            use_cache: bool, 使用数据缓存
        
        返回:
            DataFrame: 回测结果
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"\n{'='*60}")
        logger.info(f"V14 策略回测（统一信号逻辑）")
        logger.info(f"{'='*60}")
        logger.info(f"期间: {start_date} ~ {end_date}")
        logger.info(f"数据模式: {'真实数据' if self.use_real_data else '模拟数据'}")
        
        # 获取数据
        if self.use_real_data:
            price_df, market_df = None, None
            
            # 1. 尝试 QuantConnect
            if QC_DATA_AVAILABLE:
                try:
                    price_df, market_df = prepare_backtest_data_qc(
                        TICKERS, start_date, end_date, resolution='daily'
                    )
                    if price_df is not None and len(price_df) > 0:
                        logger.info(f"📊 数据源: QuantConnect (Lean)")
                    else:
                        logger.warning("⚠️ QuantConnect 数据为空，回退到 Yahoo Finance")
                        price_df, market_df = None, None
                except Exception as e:
                    logger.warning(f"⚠️ QuantConnect 获取失败: {e}，回退到 Yahoo Finance")
                    price_df, market_df = None, None
            
            # 2. 回退到 Yahoo Finance
            if (price_df is None or len(price_df) == 0) and YAHOO_DATA_AVAILABLE:
                try:
                    logger.info("📊 数据源: Yahoo Finance (QuantConnect 不可用)")
                    price_df, market_df = prepare_backtest_data(
                        TICKERS, start_date, end_date, use_cache
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Yahoo Finance 获取失败: {e}")
                    price_df, market_df = None, None
            
            # 3. 最终回退: 模拟数据
            if price_df is None or len(price_df) == 0:
                logger.warning("⚠️ 无可用真实数据，使用模拟数据")
                price_df, market_df = self._generate_mock_data(start_date, end_date)
        else:
            # 使用模拟数据
            price_df, market_df = self._generate_mock_data(start_date, end_date)
        
        # 检查数据有效性
        if price_df is None or len(price_df) == 0:
            logger.error("❌ 无法获取任何数据，回测失败")
            return pd.DataFrame()
        
        if market_df is None or len(market_df) == 0:
            logger.warning("⚠️ 市场数据为空，使用模拟 VIX")
            market_df = pd.DataFrame({'VIX': [20.0] * len(price_df)}, index=price_df.index)
        
        # 使用统一的信号生成逻辑进行回测
        result = self._run_backtest_unified(price_df, market_df)
        
        # 空数据保护
        if result is None or len(result) == 0:
            logger.error("❌ 回测失败，无结果数据")
            return pd.DataFrame()
        
        # 应用交易成本
        if COST_AVAILABLE:
            logger.info("应用交易成本...")
            result = apply_costs_to_backtest(result)
        
        self.backtest_result = result
        
        # 计算指标
        self._print_performance(result)
        
        # 生成可视化
        if VIZ_AVAILABLE and len(result) > 0:
            logger.info("\n生成可视化报告...")
            generate_full_report(result)
        
        return result
    
    def _run_backtest_unified(self, price_df, market_df):
        """
        统一回测引擎 - 使用与实盘相同的 generate_signals 逻辑
        
        参数:
            price_df: DataFrame, 价格数据 (必须有 DatetimeIndex)
            market_df: DataFrame, 市场数据 (必须有 VIX 列)
        
        返回:
            DataFrame: 回测结果
        """
        import numpy as np
        
        # 空数据保护
        if price_df is None or len(price_df) == 0:
            logger.error("❌ price_df 为空，无法回测")
            return pd.DataFrame()
        
        # 确保索引为 DatetimeIndex
        if not isinstance(price_df.index, pd.DatetimeIndex):
            logger.info(f"🔄 转换索引为 DatetimeIndex: {type(price_df.index).__name__}")
            try:
                price_df.index = pd.to_datetime(price_df.index)
            except Exception as e:
                logger.error(f"❌ 无法转换索引: {e}")
                return pd.DataFrame()
        
        # 确保 market_df 有 DatetimeIndex 和 VIX 列
        if market_df is None or len(market_df) == 0:
            logger.warning("⚠️ market_df 为空，使用默认 VIX=20")
            market_df = pd.DataFrame({'VIX': [20.0] * len(price_df)}, index=price_df.index)
        elif 'VIX' not in market_df.columns:
            logger.warning("⚠️ market_df 缺少 VIX 列，使用默认 VIX=20")
            market_df['VIX'] = 20.0
        
        if not isinstance(market_df.index, pd.DatetimeIndex):
            try:
                market_df.index = pd.to_datetime(market_df.index)
            except Exception as e:
                logger.error(f"❌ 无法转换 market_df 索引: {e}")
                return pd.DataFrame()
        
        # 确保两个 DataFrame 日期对齐
        common_dates = price_df.index.intersection(market_df.index)
        if len(common_dates) == 0:
            logger.error("❌ price_df 和 market_df 没有共同日期")
            return pd.DataFrame()
        
        price_df = price_df.loc[common_dates]
        market_df = market_df.loc[common_dates]
        
        # 月末调仓日
        if len(price_df) < 252:
            logger.warning(f"⚠️ 数据不足 252 日 ({len(price_df)} 日)，无法预热")
            return pd.DataFrame()
        
        monthly = price_df.groupby([price_df.index.year, price_df.index.month]).tail(1).index
        monthly = monthly[monthly >= price_df.index[252]]  # 252日预热
        
        if len(monthly) < 2:
            logger.warning("⚠️ 调仓日不足 2 个，无法回测")
            return pd.DataFrame()
        
        nav = 1.0
        prev_holdings = []
        records = []
        
        for i in range(1, len(monthly)):
            prev_d, curr_d = monthly[i-1], monthly[i]
            
            # 安全获取 VIX
            try:
                vix_v = float(market_df.loc[prev_d, 'VIX'])
            except (KeyError, TypeError, ValueError):
                vix_v = 20.0  # 默认值
            
            # 使用与实盘相同的信号生成逻辑
            price_slice = price_df.loc[:prev_d].iloc[-252:]
            target_positions = self.generate_signals(price_slice, vix_v)
            
            selected = list(target_positions.keys()) if target_positions else []
            
            # 收益计算
            if prev_holdings:
                try:
                    p_start = price_df.loc[prev_d, prev_holdings].values
                    p_end = price_df.loc[curr_d, prev_holdings].values
                    from main import v14_scale
                    sc = v14_scale(vix_v)
                    mr = np.mean(p_end / p_start - 1) * (sc / 100)
                except Exception as e:
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
            })
            prev_holdings = selected
        
        return pd.DataFrame(records)
    
    def generate_signals(self, price_df=None, vix=None):
        """
        生成交易信号 - 桥接回测逻辑到实盘
        
        参数:
            price_df: DataFrame, 价格数据 (默认获取最新252日)
            vix: float, 当前VIX (默认从数据获取)
        
        返回:
            dict: {symbol: target_value} 目标持仓
        """
        import numpy as np
        
        # 获取数据
        if price_df is None:
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')
            
            # 优先 QuantConnect
            if QC_DATA_AVAILABLE:
                logger.info("📊 信号生成数据源: QuantConnect")
                price_df, market_df = prepare_backtest_data_qc(
                    TICKERS, start, end, resolution='daily'
                )
            elif YAHOO_DATA_AVAILABLE:
                logger.info("📊 信号生成数据源: Yahoo Finance")
                price_df, market_df = prepare_backtest_data(
                    TICKERS, start, end, use_cache=True
                )
            else:
                logger.error("无法获取数据，无可用数据源")
                return {}
            
            vix = market_df['VIX'].iloc[-1]
        
        if vix is None:
            logger.error("VIX 数据缺失")
            return {}
        
        logger.info(f"\n{'='*60}")
        logger.info(f"生成交易信号")
        logger.info(f"{'='*60}")
        logger.info(f"当前 VIX: {vix:.2f}")
        logger.info(f"数据日期: {price_df.index[-1]}")
        
        # 计算因子 (复用回测逻辑)
        price_slice = price_df.iloc[-252:]  # 最近252日
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
        
        # 分层选股 (复用回测逻辑)
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
        
        # 等权分配目标金额
        # 如果启用了 executor，获取账户价值；否则使用默认 $1M
        if self.executor:
            try:
                account = self.executor.get_account()
                portfolio_value = account['portfolio_value'] if account else 1000000
            except Exception:
                portfolio_value = 1000000
        else:
            portfolio_value = 1000000  # 回测默认
        
        # 权重分配（如果配置了 allocator）
        if self.weight_allocator and len(selected) > 0:
            weights = self.weight_allocator.allocate(
                selected, 
                price_df=price_df,
                target_value=portfolio_value * sc / 100
            )
            target_positions = weights
            logger.info(f"权重分配: {self.weight_allocator.method}")
        else:
            # 等权分配
            target_value = (portfolio_value * sc / 100) / len(selected)
            target_positions = {s: target_value for s in selected}
        
        # 打印分配结果
        for s, v in sorted(target_positions.items(), key=lambda x: x[1], reverse=True)[:10]:
            logger.info(f"  {s}: ${v:,.0f}")
        
        return target_positions
    
    def run_live_rebalance(self):
        """
        运行实盘再平衡 - 全自动流程:
        1. 开始调仓会话（幂等性保障）
        2. 获取最新数据
        3. 计算信号
        4. 风控检查
        5. 执行再平衡
        """
        if not self.executor:
            logger.error("未启用 Alpaca Paper Trading")
            return
        
        # 0. 开始新会话（幂等性保障）
        self.executor.start_rebalance_session()
        
        # 1. 获取数据并生成信号
        target_positions = self.generate_signals()
        
        if not target_positions:
            logger.error("信号生成失败，跳过交易")
            return
        
        # 2. 风控检查
        if self.risk_monitor:
            # 获取当前 VIX
            vix = self._get_latest_vix()
            if vix:
                self.risk_monitor.check_vix_level(vix)
            
            if self.risk_monitor.trading_halted:
                logger.warning("⚠️ 交易已暂停（风险监控触发）")
                return
        
        # 3. 执行交易
        self.live_trade(target_positions)
        
        logger.info("✅ 实盘再平衡完成")
    
    def _get_latest_vix(self):
        """获取最新 VIX - 优先 QuantConnect, 回退 Yahoo"""
        # 1. 尝试 QuantConnect
        if QC_DATA_AVAILABLE:
            try:
                source = HybridQCDataSource()
                vix = source.get_vix()
                if vix:
                    return vix
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"QuantConnect 获取 VIX 网络错误: {e}")
            except Exception as e:
                logger.warning(f"QuantConnect 获取 VIX 失败: {e}")
        
        # 2. 回退到 Yahoo Finance
        if YAHOO_DATA_AVAILABLE:
            try:
                from data_source import fetch_vix_data
                end = datetime.now().strftime('%Y-%m-%d')
                start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                vix_series = fetch_vix_data(start, end)
                if vix_series is not None and len(vix_series) > 0:
                    return float(vix_series.iloc[-1])
            except (ConnectionError, TimeoutError) as e:
                logger.warning(f"Yahoo 获取 VIX 网络错误: {e}")
            except Exception as e:
                logger.warning(f"Yahoo 获取 VIX 失败: {e}")
        
        # 3. 最终回退: 直接请求
        try:
            import yfinance as yf
            vix_data = yf.Ticker('^VIX').history(period='5d')
            if len(vix_data) > 0:
                return float(vix_data['Close'].iloc[-1])
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"yfinance 获取 VIX 网络错误: {e}")
        except Exception as e:
            logger.warning(f"yfinance 获取 VIX 失败: {e}")
        
        return None
    
    def live_trade(self, target_positions, confirm_fills=True):
        """
        实盘交易（Paper Trading）
        
        参数:
            target_positions: dict, {symbol: target_value}
            confirm_fills: bool, 是否等待成交确认
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
        
        # 检查账户
        account = self.executor.get_account()
        if account:
            logger.info(f"账户现金: ${account['cash']:,.2f}")
            logger.info(f"组合价值: ${account['portfolio_value']:,.2f}")
        
        # 使用 OrderManager 执行再平衡（带成交确认）
        if ORDER_MGR_AVAILABLE:
            manager = RebalanceManager(self.executor)
            results = manager.rebalance(
                target_positions, 
                confirm_fills=confirm_fills
            )
            
            # 估算成本
            if COST_AVAILABLE:
                current_positions = {p['symbol']: p for p in self.executor.get_positions()}
                cost = TradingCostModel().estimate_portfolio_cost(
                    target_positions, current_positions
                )
                logger.info(f"\n预估交易成本: ${cost['total_cost']:.2f}")
        else:
            # 回退到基础再平衡
            self.executor.rebalance_portfolio(target_positions)
        
        # 风控检查
        if self.risk_monitor:
            positions = self.executor.get_positions()
            portfolio_value = account['portfolio_value']
            self.risk_monitor.check_position_limits(positions, portfolio_value)
    
    def check_risk(self, nav=None, vix=None, positions=None, portfolio_value=None):
        """
        风险检查
        
        参数:
            nav: float, 当前NAV
            vix: float, 当前VIX
            positions: dict, 当前持仓
            portfolio_value: float, 组合价值
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
    
    def _generate_mock_data(self, start_date, end_date):
        """生成模拟数据"""
        logger.info("生成模拟数据...")
        
        dates = pd.bdate_range(start_date, end_date)
        n_days = len(dates)
        
        # 生成价格数据
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
        
        # 生成 VIX
        vix = np.clip(15 + np.cumsum(np.random.normal(0, 0.5, n_days)) * 0.08, 9, 55)
        market_df = pd.DataFrame({
            'VIX': vix,
            'RSI': np.random.uniform(30, 70, n_days)
        }, index=dates)
        
        return price_df, market_df
    
    def _print_performance(self, result):
        """打印绩效"""
        if len(result) == 0:
            logger.warning("回测结果为空")
            return
        
        nav = result['nav']
        returns = nav.pct_change().dropna()
        
        years = (result['date'].iloc[-1] - result['date'].iloc[0]).days / 365.25
        cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1/years) - 1
        vol = returns.std() * np.sqrt(12)
        sharpe = cagr / vol if vol > 0 else 0
        maxdd = ((nav / nav.cummax()) - 1).min()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"回测绩效")
        logger.info(f"{'='*60}")
        logger.info(f"  期间: {result['date'].iloc[0]} ~ {result['date'].iloc[-1]}")
        logger.info(f"  调仓次数: {len(result)}")
        logger.info(f"  Final NAV: {nav.iloc[-1]:.4f}")
        logger.info(f"  CAGR: {cagr:.2%}")
        logger.info(f"  Sharpe: {sharpe:.3f}")
        logger.info(f"  MaxDD: {maxdd:.2%}")
        logger.info(f"  波动率: {vol:.2%}")
        logger.info(f"  胜率: {(returns > 0).mean():.1%}")
    
    def get_status(self):
        """获取策略状态"""
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


# ============================================================
# 主入口
# ============================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='V14 MultiFactor Strategy')
    parser.add_argument('--backtest', action='store_true', help='运行回测')
    parser.add_argument('--live', action='store_true', help='运行实盘')
    parser.add_argument('--real-data', action='store_true', help='使用真实数据')
    parser.add_argument('--paper', action='store_true', help='使用 Paper Trading')
    parser.add_argument('--start', type=str, help='开始日期 YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='结束日期 YYYY-MM-DD')
    
    parser.add_argument('--monitor', action='store_true', help='启用盘中监控')
    parser.add_argument('--weight-method', type=str, default='equal',
                       choices=['equal', 'risk_parity', 'momentum_weighted'],
                       help='权重分配方法')
    
    args = parser.parse_args()
    
    # 初始化策略 - 默认使用真实数据，回测模式
    strategy = V14Strategy(
        use_real_data=True,  # 强制使用真实数据
        use_paper_trading=args.paper,
        enable_risk_monitor=True,
        enable_intraday_monitor=args.monitor,
        weight_method=args.weight_method
    )
    
    # 检查数据可用性
    if not strategy.use_real_data:
        logger.error("❌ 真实数据不可用，请检查网络连接或数据源配置")
        logger.error("   可选数据源: Yahoo Finance (pip install yfinance)")
        logger.error("   回测已中止，未使用模拟数据")
        exit(1)
    
    if args.backtest or not args.live:
        # 运行回测
        result = strategy.run_backtest(args.start, args.end)
        if len(result) == 0:
            logger.error("❌ 回测失败: 无数据或数据不足")
            exit(1)
    
    if args.live:
        # 检查是否启用了 Paper Trading
        if not strategy.use_paper_trading:
            logger.error("❌ 实盘模式需要 --paper 参数启用 Paper Trading")
            logger.error("   运行: python run_strategy.py --live --paper")
            exit(1)
        
        # 全自动实盘再平衡
        strategy.run_live_rebalance()
    
    # 打印状态
    status = strategy.get_status()
    logger.info(f"\n策略状态: {status}")
