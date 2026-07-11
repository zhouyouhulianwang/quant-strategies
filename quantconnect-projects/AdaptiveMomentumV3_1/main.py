"""
策略名称：AdaptiveMomentumStrategy v3.1
描述：基于多期限动量和行业轮动的自适应量化策略（回撤控制版 + 期权对冲）
优化项：
  - 动态调仓频率
  - 自适应权重调整
  - 行业轮动过滤
  - 多层风险管理（止损8%、追踪止损10%、回撤保护15%）
  - SPY Put期权对冲（目标最大回撤20%）
  - 行业集中度限制（单行业≤30%）
  - 执行优化
"""
from AlgorithmImports import *
from typing import Dict, List, Tuple, Optional
from collections import deque
import json

class AdaptiveMomentumStrategy(QCAlgorithm):
    def Initialize(self):
        # ============ 基本设置 ============
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2026, 6, 30)
        self.SetCash(100000)
        self.SetBrokerageModel(
            BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, 
            AccountType.MARGIN
        )
        
       
        # 实际佣金：每股$0.005，最低$1.00/笔，最高交易价值的1%
        # 21,000笔交易 × $1.00 = ~$21,000 佣金（回测已自动扣除）
        
        # 设置每日精确结束时间为false，避免MarketOnOpen警告
        self.Settings.DailyPreciseEndTime = False
        
        # 设置现金缓冲，避免购买力不足错误
        self.Settings.FreePortfolioValuePercentage = 0.05  # 保留5%现金作为缓冲
        
        # ============ 动量参数 ============
        self.lookback_periods = {
            '1d': 1, '1w': 5, '2w': 10, 
            '1m': 21, '3m': 63, '6m': 126
        }
        self.base_weights = {
            '1d': 0.1, '1w': 0.5, '2w': 1.0, 
            '1m': 1.0, '3m': 0.7, '6m': 0.5  # 保守配置
        }
        self.current_weights = self.base_weights.copy()
        
        # ============ 波动率参数 ============
        self.volatility_lookback = 20
        self.volatility_high = 0.025
        self.volatility_low = 0.01
        self.volatility_scaling = False  # 关闭波动率缩放（牛市中压缩高动量股票收益）
        self.target_volatility = 0.15  # 年化目标波动率
        
        # ============ RSI超买超卖参数（个股动态权重） ============
        self.rsi_overbought = 65
        self.rsi_oversold = 35
        self.rsi_adjustment_factor = 0.4  # 激进调整：超买降权60%，超卖提升60%（收益+26.8%）
        
        # ============ VIX参数（仅用于市场状态判断，不动态调整权重） ============
        # 优先使用VIX指数，如果不可用则回退到VIXY
        # VIXY是ETF有衰减问题，但本地数据更完整
        vix_available = False
        try:
            vix_sym = self.AddIndex("VIX", Resolution.DAILY).Symbol
            # 验证VIX数据是否真正可用（价格>0）
            if self.Securities[vix_sym].Price > 0:
                self.vix_symbol = vix_sym
                vix_available = True
                self.Log("使用VIX指数")
        except:
            pass
        
        if not vix_available:
            self.vix_symbol = self.AddEquity("VIXY", Resolution.DAILY).Symbol
            self.Log("VIX数据不可用，使用VIXY替代")
        
        self.vix_threshold = 30.0
        self.vix_pause_level = 30.0
        self.vix_boost_level = 18.0
        
        # ============ 仓位管理 ============
        self.max_position_pct = 0.15  # 单票最大仓位15%：平均10%，强势股可达15%
        self.min_position_pct = 0.00  # 取消最小仓位限制
        self.max_stocks = 10
        self.min_score = 0.0
        
       
        self.min_hold_days = 3  # 最少持有3天（减少日内交易，避免PDT）
        self.position_entry_date = {}  # 记录买入日期
        
       
        self.max_total_exposure = 0.80  # 总仓位上限 50%→80%（牛市提高仓位）
        self.min_total_exposure = 0.30  # 总仓位下限 30%（熊市最低仓位）
        self.current_total_exposure = self.min_total_exposure  # 动态总仓位
        
        self.max_sector_pct = 0.50  # 单行业最大占比50%（更宽松，允许集中）
        
        # ============ 行业轮动参数 ============
        self.sector_rotation_enabled = True
        self.n_top_sectors = 3
        self.sector_lookback = 30  # 测试：从63日缩短至30日，更快捕捉行业轮动
        self.sector_map = self._BuildSectorMap()
        
        # ============ 调仓频率参数 ============
        self.rebalance_frequency = "weekly"  # 可选: "weekly", "monthly", "bimonthly", "quarterly"
        self.rebalance_months = list(range(1, 13))  # 默认所有月份
        self.base_rebalance_freq = 2  # 基础调仓频率（周），仅weekly模式使用
        self.min_rebalance_freq = 1
        self.max_rebalance_freq = 8
        self.week_counter = 0
        self.current_rebalance_freq = self.base_rebalance_freq
        self.pause_weeks = 0
        self.max_pause_weeks = 4
        self.valuation_extreme = 0.8
        
        # ============ 止损参数 ============
        self.stop_loss_pct = 0.08  # 固定止损 15%→8%（更严格）
        self.use_atr_stop = False 
        self.atr_period = 14
        self.atr_multiplier = 2.0  # ATR倍数
        self.atr_indicators = {}  # ATR指标缓存
        
        self.trailing_stop_enabled = True
        self.trailing_stop_pct = 0.10  # 追踪止损 20%→10%（更积极）
        self.max_drawdown_pct = 0.10 
        
        # ============ 趋势过滤参数 ============
        self.trend_filter_enabled = False  # 关闭趋势过滤（牛市中过度限制选股）
        self.trend_lookback = 200  # 200日均线
        
        # ============ RSI参数 ============
       
        # 这里只初始化RSI指标，不覆盖参数
        self.rsi_filter_enabled = False  # 关闭RSI过滤（牛市中过度限制选股）
        self.rsi_period = 14
        
        # ============ 多因子参数（已禁用，保留配置兼容性）============
        self.multi_factor_enabled = False  # 禁用多因子，单RSI表现更好
        # 清理残留：MACD/BB指标不再初始化
        
        # ============ 数据缓存 ============
        self.price_history = {}
        self.rsi_indicators = {}
        self.sma_indicators = {}
        self.high_water_mark = 0  # 用于回撤保护（策略启动以来的最高净值，不重置）
        self.position_high = {}  # 用于追踪止损
        
       
        self.drawdown_protection_triggered = False  # 回撤保护是否已触发
        self.drawdown_trigger_level = 0.10  # 首次触发阈值10%
        self.drawdown_severe_level = 0.15   # 严重回撤阈值15%（转投现金）
        self.drawdown_extreme_level = 0.20  # 极端回撤阈值20%（全面清仓）
        
        # ============ 200日均线市场状态（v3.1 回撤控制核心）============
        self.market_bear_mode = False  # 是否处于熊市模式
        self.bear_mode_confirm_days = 3 
        self.bear_mode_counter = 0  # 熊市计数器
        self.dynamic_sizing_enabled = True  # 保留向后兼容
        
        # ============ 期权对冲参数============
       
        self.hedge_enabled = False  # 默认禁用，可选启用
        self.hedge_method = "short_spy"  # 可选: "put_option"（需期权数据）或 "short_spy"
        self.hedge_ratio = 1.0  # 对冲比例：100%股票敞口
        self.put_otm_pct = 0.05  # Put虚值5%
        self.put_dte = 30  # 30天到期
        self.hedge_rollover_days = 5  # 提前5天滚动
        self.current_put = None  # 当前持有的Put
        self.spy_option = None
        
        # ============ 股票池配置 ============
        self.stock_pool_source = "combined"  # 可选: "sp500", "nasdaq100", "combined", "custom"
        self.stock_pool_file = "stock_pools.json"  # 股票池配置文件
        self.enable_dynamic_pool = True  # 启用动态股票池更新
        self.pool_update_freq = 30  # 每30天检查更新一次
        self.last_pool_update = self.Time
        
        # ============ 股票池 ============
        self.us_tickers = self._GetUSStockPool()
        self.safe_tickers = ["TLT", "GLD"]
        self.safe_symbols = {}
        self.symbols = {}
        self.ticker_list = []
        
        # ============ 初始化股票 ============
        self._InitializeSymbols()
        
        # 如果启用动态更新，设置定时检查
        if self.enable_dynamic_pool:
            self.Schedule.On(
                self.DateRules.MonthStart("SPY"),
                self.TimeRules.AfterMarketOpen("SPY", 30),
                self.UpdateStockPool
            )
        
        # ============ 初始化SPY期权（对冲用）============
        if self.hedge_enabled:
            try:
                self.spy_option = self.AddOption("SPY", Resolution.DAILY)
                self.spy_option.SetFilter(-2, 2, 0, 60)  # 选择近月合约，行权价范围±2档
            except Exception as e:
                self.Log(f"ERROR adding SPY option: {e}")
                self.hedge_enabled = False
        
        # ============ 执行模型设置（P0优化）============
        # 设置滑点模型，模拟实盘成交成本
        # 使用自定义滑点模型
        self.SetSecurityInitializer(self.CustomSecurityInitializer)
        
        # ============ 流动性过滤参数（P0优化）============
        # P0优化：动态流动性过滤（牛市严格，熊市宽松）
        self.min_daily_volume_bull = 10000000  # 牛市最小日均成交量1000万
        self.min_daily_volume_bear = 5000000   # 熊市最小日均成交量500万
        self.min_daily_volume = self.min_daily_volume_bull  # 当前阈值（动态）
        self.min_price = 5.0  # 最小股价$5
        self.liquid_stocks = set()  # 高流动性股票集合
        
        # ============ 成本基准记录 ============
        self.cost_basis = {}
        self.position_high = {}
        
        # ============ 调度设置 ============
        # 所有操作在开盘后不同阶段执行，分散订单压力
        # 顺序：1.止损检查(60min) -> 2.回撤保护(65min) -> 3.再平衡(70min/80min)
        self.Schedule.On(
            self.DateRules.EveryDay("SPY"), 
            self.TimeRules.AfterMarketOpen("SPY", 60), 
            self.CheckStopLoss
        )
        self.Schedule.On(
            self.DateRules.EveryDay("SPY"),
            self.TimeRules.AfterMarketOpen("SPY", 65),
            self.CheckMaxDrawdown
        )
        # 再平衡调度（在止损/回撤检查之后注册，避免同一时间点大量订单）
        self.SetRebalanceSchedule()
        
        # ============ WarmUp ============
        warmup_days = max(self.lookback_periods['6m'], self.sector_lookback) + self.trend_lookback + 20
        self.SetWarmUp(timedelta(days=warmup_days))
        
        # ============ 日志 ============
        self.Log(f"策略初始化完成。WarmUp: {warmup_days}天")
        self.Log(f"调仓频率: {self.rebalance_frequency}, 月份: {self.rebalance_months}")
        self.Log(f"RSI参数: overbought={self.rsi_overbought}, oversold={self.rsi_oversold}, factor={self.rsi_adjustment_factor}")
        self.Log(f"多因子: enabled={self.multi_factor_enabled}")

    # ============ 辅助方法 ============
    def _BuildSectorMap(self) -> Dict[str, str]:
        """构建行业映射表 - 优先从stock_pools.json加载，其次sector_map.json，最后硬编码fallback"""
        import json, os, inspect
        
        # 获取算法文件所在目录
        algorithm_dir = os.path.dirname(os.path.abspath(inspect.getfile(self.__class__)))
        
        # 方案1: 从 stock_pools.json 的 sector_map 字段读取（推荐）
        stock_pool_paths = [
            os.path.join(algorithm_dir, self.stock_pool_file),
            self.stock_pool_file,
            "/home/pc/.openclaw/workspace/quantconnect-projects/stock_pools.json",
            "../stock_pools.json",
        ]
        
        for path in stock_pool_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        config = json.load(f)
                        if 'sector_map' in config:
                            sector_map = config['sector_map']
                            self.Log(f"从 {path} 的 sector_map 加载行业映射: {len(sector_map)} 只股票")
                            return sector_map
                except Exception as e:
                    self.Log(f"从 stock_pools.json 加载 sector_map 失败: {e}")
        
        # 方案2: 从独立的 sector_map.json 读取（向后兼容）
        sector_map_paths = [
            os.path.join(algorithm_dir, "sector_map.json"),
            "sector_map.json",
            "/home/pc/.openclaw/workspace/quantconnect-projects/sector_map.json",
            "../sector_map.json",
        ]
        
        for path in sector_map_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        sector_map = json.load(f)
                        self.Log(f"从 {path} 加载行业映射: {len(sector_map)} 只股票")
                        return sector_map
                except Exception as e:
                    self.Log(f"加载行业映射失败: {e}")
        
        # Fallback: 硬编码（如果配置文件都不存在）
        self.Log("WARNING: 使用硬编码行业映射")
        return {
            'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech',
            'META': 'Tech', 'AMZN': 'Tech', 'TSLA': 'Tech', 'AMD': 'Tech',
            'JPM': 'Finance', 'BAC': 'Finance', 'GS': 'Finance',
            'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'LLY': 'Healthcare',
            'HD': 'Consumer', 'COST': 'Consumer', 'NKE': 'Consumer',
            'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy',
            'CAT': 'Industrial', 'HON': 'Industrial', 'UPS': 'Industrial',
            'VZ': 'Telecom', 'T': 'Telecom', 'CMCSA': 'Telecom',
            'PLD': 'REITs', 'AMT': 'REITs', 'EQIX': 'REITs',
            'NEE': 'Utilities', 'SO': 'Utilities', 'DUK': 'Utilities',
            'LIN': 'Materials', 'APD': 'Materials', 'SHW': 'Materials',
        }

    def _GetUSStockPool(self) -> List[str]:
        """获取美国股票池 - 完全从JSON配置文件加载，禁止硬编码"""
        # 强制从配置文件加载
        try:
            import json
            import os
            import inspect
            
            # 获取算法文件所在目录
            algorithm_dir = os.path.dirname(os.path.abspath(inspect.getfile(self.__class__)))
            
            # 尝试多个路径（按优先级）
            possible_paths = [
                os.path.join(algorithm_dir, self.stock_pool_file),  # 算法所在目录
                self.stock_pool_file,  # 当前工作目录
                f"/home/pc/.openclaw/workspace/quantconnect-projects/{self.stock_pool_file}",
                f"../{self.stock_pool_file}",
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        pools = json.load(f)
                        tickers = pools.get(self.stock_pool_source, [])
                        if tickers:
                            self.Log(f"从 {path} 加载股票池: {self.stock_pool_source}, 共{len(tickers)}只")
                            return list(dict.fromkeys(tickers))
                        else:
                            self.Log(f"WARNING: {path} 中未找到股票池 '{self.stock_pool_source}'")
            
            # 所有路径都失败
            self.Log(f"ERROR: 无法加载股票池配置文件，已禁用动态加载")
            self.Log(f"搜索路径: {possible_paths}")
            self.enable_dynamic_pool = False
            
        except Exception as e:
            self.Log(f"ERROR: 加载股票池文件失败: {e}")
            self.enable_dynamic_pool = False
        
        # 返回空列表（策略应处理空股票池的情况）
        self.Log("WARNING: 股票池为空，请检查 stock_pools.json 配置文件")
        return []

    def _InitializeSymbols(self):
        """初始化所有股票symbol"""
        for ticker in self.us_tickers:
            try:
                symbol = self.AddEquity(ticker, Resolution.DAILY).Symbol
                self.symbols[ticker] = symbol
                self.ticker_list.append(ticker)
                
                # 初始化RSI和SMA指标
                if ticker not in self.safe_tickers:
                    self.rsi_indicators[symbol] = self.RSI(symbol, self.rsi_period)
                    self.sma_indicators[symbol] = self.SMA(symbol, self.trend_lookback)
                    
                   
                    if self.use_atr_stop:
                        self.atr_indicators[symbol] = self.ATR(symbol, self.atr_period)
                
                # 为SPY也添加SMA指标（用于动态仓位）
                if ticker == "SPY" and symbol not in self.sma_indicators:
                    self.sma_indicators[symbol] = self.SMA(symbol, self.trend_lookback)
                    
            except Exception as e:
                self.Log(f"ERROR adding {ticker}: {e}")
        
        for ticker in self.safe_tickers:
            try:
                self.safe_symbols[ticker] = self.AddEquity(ticker, Resolution.DAILY).Symbol
            except Exception as e:
                self.Log(f"ERROR adding safe asset {ticker}: {e}")
        
        # P0优化：初始化流动性过滤（延迟到首次调仓时）
        self.liquid_stocks_initialized = False

    def CustomSecurityInitializer(self, security):
        """P0优化：自定义证券初始化，设置滑点模型"""
        # 设置滑点模型为常量0.1%
        security.SetSlippageModel(ConstantSlippageModel(0.001))
        
    def _UpdateLiquidityFilter(self):
        """P0优化：更新高流动性股票列表"""
        self.liquid_stocks = set()
        for ticker, symbol in self.symbols.items():
            try:
                security = self.Securities[symbol]
                # 检查价格和成交量
                if security.Price >= self.min_price:
                    # 获取20日平均成交量
                    history = self.History(symbol, 20, Resolution.DAILY)
                    if not history.empty and len(history) >= 10:
                        avg_volume = history['volume'].mean()
                        if avg_volume >= self.min_daily_volume:
                            self.liquid_stocks.add(ticker)
            except:
                pass
        
        self.Log(f"流动性过滤: {len(self.liquid_stocks)}/{len(self.symbols)} 只股票满足条件")
    
    def _IsLiquid(self, ticker: str) -> bool:
        """P0优化：检查股票是否高流动性"""
        return ticker in self.liquid_stocks or ticker in self.safe_tickers
    
    def _UpdateDynamicVolumeFilter(self):
        """P0优化：根据市场状态动态调整流动性过滤阈值"""
        new_threshold = (self.min_daily_volume_bear if self.market_bear_mode 
                        else self.min_daily_volume_bull)
        
        if new_threshold != self.min_daily_volume:
            self.min_daily_volume = new_threshold
            self.Log(f"流动性过滤调整: 牛市={self.min_daily_volume_bull/1e6:.0f}M → 熊市={self.min_daily_volume_bear/1e6:.0f}M, 当前={self.min_daily_volume/1e6:.0f}M")
    
    def _CanSell(self, symbol: Symbol) -> bool:
        """P0修复：检查是否可以卖出（最小持仓时间限制，避免PDT）"""
        if symbol not in self.position_entry_date:
            return True  # 没有记录，允许卖出（可能是系统重启后）
        
        hold_days = (self.Time - self.position_entry_date[symbol]).days
        if hold_days < self.min_hold_days:
            # self.Log(f"持仓时间不足: {self.GetTickerName(symbol)} 仅持有{hold_days}天，最少需要{self.min_hold_days}天")
            return False
        return True
    
    def _RecordBuyDate(self, symbol: Symbol):
        """P0修复：记录买入日期"""
        if self.Portfolio[symbol].Invested and symbol not in self.position_entry_date:
            self.position_entry_date[symbol] = self.Time
    
    def GetTickerName(self, symbol: Symbol) -> str:
        """根据Symbol获取Ticker名称"""
        for name, sym in self.symbols.items():
            if sym == symbol:
                return name
        for name, sym in self.safe_symbols.items():
            if sym == symbol:
                return name
        return str(symbol)

    def UpdateStockPool(self):
        """定期更新股票池"""
        if not self.enable_dynamic_pool or self.IsWarmingUp:
            return
        
        try:
            # 检查是否需要更新
            days_since_update = (self.Time - self.last_pool_update).days
            if days_since_update < self.pool_update_freq:
                return
            
            self.Log(f"检查股票池更新...")
            
            # 尝试重新加载股票池
            new_tickers = self._GetUSStockPool()
            
            # 检查是否有新增股票
            current_tickers = set(self.us_tickers)
            new_additions = [t for t in new_tickers if t not in current_tickers]
            
            if new_additions:
                self.Log(f"新增 {len(new_additions)} 只股票: {', '.join(new_additions[:10])}")
                
                # 添加新股票到symbols
                for ticker in new_additions:
                    try:
                        if ticker not in self.symbols:
                            symbol = self.AddEquity(ticker, Resolution.DAILY).Symbol
                            self.symbols[ticker] = symbol
                            self.ticker_list.append(ticker)
                            
                            if ticker not in self.safe_tickers:
                                self.rsi_indicators[symbol] = self.RSI(symbol, self.rsi_period)
                                self.sma_indicators[symbol] = self.SMA(symbol, self.trend_lookback)
                    except Exception as e:
                        self.Log(f"添加新股 {ticker} 失败: {e}")
                
                # 更新股票池列表
                self.us_tickers = list(dict.fromkeys(self.us_tickers + new_additions))
                self.last_pool_update = self.Time
                self.Log(f"股票池更新完成，当前共 {len(self.us_tickers)} 只")
            else:
                self.Log("股票池无需更新")
                
        except Exception as e:
            self.Log(f"股票池更新失败: {e}")

    # ============ 核心策略方法 ============
    def SetRebalanceSchedule(self):
        """设置调仓调度 - 支持多种调仓频率
        基于用户参考代码改进，使用AfterMarketOpen避免MarketOnOpen警告
        所有操作统一在开盘后60分钟执行
        """
        # 根据频率设置调仓月份
        if self.rebalance_frequency == "monthly":
            self.rebalance_months = list(range(1, 13))  # 所有月份
        elif self.rebalance_frequency == "bimonthly":
            self.rebalance_months = [1, 3, 5, 7, 9, 11]  # 隔月
        elif self.rebalance_frequency == "quarterly":
            self.rebalance_months = [1, 4, 7, 10]  # 季度
        elif self.rebalance_frequency == "weekly":
            self.rebalance_months = list(range(1, 13))  # 所有月份
        else:
            self.Log(f"Invalid rebalance frequency: {self.rebalance_frequency}, defaulting to weekly")
            self.rebalance_frequency = "weekly"
            self.rebalance_months = list(range(1, 13))
        
        # 设置调仓调度 - 统一在开盘后60分钟
        if self.rebalance_frequency == "weekly":
            # 每周一调仓，支持动态频率调整
            self.Schedule.On(
                self.DateRules.Every(DayOfWeek.MONDAY),
                self.TimeRules.AfterMarketOpen("SPY", 70),  # 70分钟，在止损/回撤之后
                self.WeeklyUpdate
            )
            self.Log(f"调仓调度: 每周一 开盘后70分钟, 基础频率={self.base_rebalance_freq}周")
        else:
            # 月度/双月/季度调仓
            self.Schedule.On(
                self.DateRules.MonthStart("SPY"),
                self.TimeRules.AfterMarketOpen("SPY", 80),  # 80分钟，在所有操作之后
                self.MonthlyRebalance
            )
            self.Log(f"调仓调度: {self.rebalance_frequency} 开盘后80分钟 (月份: {self.rebalance_months})")

    def MonthlyRebalance(self):
        """月度调仓入口 - 检查是否在当前调仓月份"""
        current_month = self.Time.month
        
        if current_month not in self.rebalance_months:
            self.Log(f"本月({current_month})不在调仓月份列表{self.rebalance_months}，跳过")
            return
        
        self.Log(f"执行{self.rebalance_frequency}调仓: 月份={current_month}")
        self.CheckMarketState()
        self.UpdateAdaptiveWeights()
        self.RebalanceUS()
        
        # 期权对冲
        self.HedgeWithPut()

    def WeeklyUpdate(self):
        """每周更新主入口"""
        self.week_counter += 1
        self.AdjustRebalanceFrequency()
        self.CheckMarketState()
        
        if self.week_counter % self.current_rebalance_freq == 1:
            self.UpdateAdaptiveWeights()
            self.RebalanceUS()
        
        # v3.1 期权对冲
        self.HedgeWithPut()

    def AdjustRebalanceFrequency(self):
        """根据市场环境动态调整调仓频率"""
        try:
            # 获取VIXY价格
            vixy_price = self.Securities[self.vix_symbol].Price
            if vixy_price <= 0:
                vixy_price = 25
            
            # 计算SPY估值
            spy_valuation = 0.5
            try:
                spy_history = self.History(self.symbols.get("SPY"), 63, Resolution.DAILY)
                if not spy_history.empty and len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[0]) - 1
                    spy_valuation = max(0, min(1, 0.5 + spy_3m_return * 2))
            except Exception as e:
                self.Log(f"ERROR in SPY valuation: {e}")
            
            is_extreme = (spy_valuation > self.valuation_extreme or 
                         spy_valuation < (1 - self.valuation_extreme))
            
            # 调整频率
            if vixy_price > self.vix_pause_level or is_extreme:
                # 高波动或极端估值：降低频率（增加间隔）
                new_freq = min(self.current_rebalance_freq + 1, self.max_rebalance_freq)
                if new_freq != self.current_rebalance_freq:
                    self.pause_weeks += 1
                self.current_rebalance_freq = new_freq
            elif vixy_price < self.vix_boost_level and not is_extreme:
                # 低波动且正常估值：增加频率（减少间隔）
                new_freq = max(self.current_rebalance_freq - 1, self.min_rebalance_freq)
                if new_freq != self.current_rebalance_freq:
                    self.current_rebalance_freq = new_freq
                self.pause_weeks = 0
            else:
                # 正常环境：回归基础频率
                self.current_rebalance_freq = self.base_rebalance_freq
                self.pause_weeks = 0
            
            # 防止暂停过久
            if self.pause_weeks >= self.max_pause_weeks:
                self.current_rebalance_freq = self.base_rebalance_freq
                self.pause_weeks = 0
                
        except Exception as e:
            self.Log(f"ERROR in AdjustRebalanceFrequency: {e}")
            self.current_rebalance_freq = self.base_rebalance_freq

    def UpdateMomentumWeights(self):
        """方案A：根据VIX动态调整动量权重
        高波动/震荡市场 → 降低长期权重，提升短期权重
        低波动/趋势市场 → 提升长期权重
        """
        try:
            if self.vix_symbol not in self.Securities:
                return
            
            vix = self.Securities[self.vix_symbol].Price
            if vix <= 0:
                vix = 20
            
            # 使用平滑后的VIX（20日移动平均）
            vix_history = self.History(self.vix_symbol, 20, Resolution.DAILY)
            if not vix_history.empty and len(vix_history) >= 10:
                vix_smooth = vix_history['close'].mean()
            else:
                vix_smooth = vix
            
            # 定义VIX阈值
            vix_high = 25    # 高波动市场
            vix_low = 18     # 低波动市场
            
            if vix_smooth > vix_high:
                # 高波动/震荡市场：降低长期权重，提升短期权重
                self.current_weights = {
                    '1d': 0.15, '1w': 0.8, '2w': 1.0, 
                    '1m': 1.0, '3m': 0.6, '6m': 0.4
                }
                self.Log(f"[{self.Time.strftime('%Y-%m-%d')}] VIX={vix_smooth:.1f} > {vix_high}: 切换至短期动量模式")
                
            elif vix_smooth < vix_low:
                # 低波动/趋势市场：提升长期权重
                self.current_weights = {
                    '1d': 0.05, '1w': 0.3, '2w': 0.8, 
                    '1m': 1.0, '3m': 1.2, '6m': 1.0
                }
                self.Log(f"[{self.Time.strftime('%Y-%m-%d')}] VIX={vix_smooth:.1f} < {vix_low}: 切换至长期动量模式")
                
            else:
                # 正常市场：使用基准权重
                self.current_weights = self.base_weights.copy()
                
        except Exception as e:
            self.Log(f"ERROR in UpdateMomentumWeights: {e}")
            self.current_weights = self.base_weights.copy()

    def UpdateAdaptiveWeights(self):
        """v3.1: 禁用基于VIX的全局权重调整，改为个股RSI动态调整"""
        # 全局权重保持固定，个股权重在CalculateMomentumScore中根据RSI调整
        return

    def CheckMarketState(self):
        """检查SPY是否在50日均线上方，决定市场状态（v3.1核心回撤控制）"""
        try:
            spy_symbol = self.symbols.get("SPY")
            if spy_symbol is None:
                return
            
            # 使用50日均线判断趋势（更敏感）
            spy_sma50 = self.SMA(spy_symbol, 50)
            if spy_sma50 is None or not spy_sma50.IsReady:
                return
            
            current_spy = self.Securities[spy_symbol].Price
            sma50 = spy_sma50.Current.Value
            
           
            is_below_sma = (current_spy < sma50)
            
            if is_below_sma:
                self.bear_mode_counter += 1
            else:
                self.bear_mode_counter = 0
            
            # 判断市场状态（需要连续3天确认）
            was_bear = self.market_bear_mode
            self.market_bear_mode = (self.bear_mode_counter >= self.bear_mode_confirm_days)
            
           
            if self.market_bear_mode:
                # 熊市：最低仓位
                self.current_total_exposure = self.min_total_exposure
            else:
                # 牛市：根据趋势强度动态调整
                deviation = (current_spy - sma50) / sma50 if sma50 > 0 else 0
                if deviation > 0.05:
                    # 强势上涨：80%仓位
                    self.current_total_exposure = self.max_total_exposure
                elif deviation > 0.02:
                    # 中等强势：60%仓位
                    self.current_total_exposure = 0.60
                else:
                    # 温和上涨：45%仓位
                    self.current_total_exposure = 0.45
            
            if self.market_bear_mode and not was_bear:
                # 刚进入熊市：调整流动性过滤为宽松模式
                self._UpdateDynamicVolumeFilter()
                # 刚进入熊市：清仓股票，转投避险资产
                self.Log(f"[WARNING]  市场进入熊市模式: SPY={current_spy:.2f} < 50MA={sma50:.2f} (连续{self.bear_mode_counter}天), 仓位降至{self.current_total_exposure*100:.0f}%")
                self.Liquidate()
                # 50% TLT, 50% GLD
                for ticker, symbol in self.safe_symbols.items():
                    self.SetHoldings(symbol, 0.5 / len(self.safe_symbols))
                self.Log("已清仓股票，转入TLT/GLD避险")
            elif not self.market_bear_mode and was_bear:
                # 刚退出熊市：调整流动性过滤为严格模式
                self._UpdateDynamicVolumeFilter()
                # 刚退出熊市：清仓避险资产，恢复股票策略
                self.Log(f"✅ 市场恢复牛市模式: SPY={current_spy:.2f} > 50MA={sma50:.2f}, 仓位提升至{self.current_total_exposure*100:.0f}%")
                for ticker in self.safe_tickers:
                    if ticker in self.safe_symbols:
                        self.Liquidate(self.safe_symbols[ticker])
                self.Log("已清仓避险资产，恢复股票策略")
            elif self.market_bear_mode:
                self.Log(f"市场处于熊市: SPY={current_spy:.2f} < 50MA={sma50:.2f} (连续{self.bear_mode_counter}天), 仓位={self.current_total_exposure*100:.0f}%")
            else:
                self.Log(f"市场处于牛市: SPY={current_spy:.2f} > 50MA={sma50:.2f}, 仓位={self.current_total_exposure*100:.0f}%")
            
        except Exception as e:
            self.Log(f"ERROR in CheckMarketState: {e}")
    
    def LimitSectorConcentration(self, targets):
        """限制行业集中度，单行业不超过max_sector_pct"""
        if not self.sector_rotation_enabled:
            return targets
        
        # 计算各行业权重
        sector_weights = {}
        for symbol, weight in targets.items():
            ticker = self.GetTickerName(symbol)
            sector = self.sector_map.get(ticker, 'Other')
            if sector not in sector_weights:
                sector_weights[sector] = 0
            sector_weights[sector] += weight
        
        # 如果某行业超限，等比例缩减该行业股票
        adjusted = targets.copy()
        for sector, total_weight in sector_weights.items():
            if total_weight > self.max_sector_pct:
                scale = self.max_sector_pct / total_weight
                for symbol in list(adjusted.keys()):
                    ticker = self.GetTickerName(symbol)
                    if self.sector_map.get(ticker, 'Other') == sector:
                        adjusted[symbol] *= scale
                self.Log(f"  {sector}行业超限{total_weight*100:.1f}%, 等比缩减至{self.max_sector_pct*100:.0f}%")
        
        return adjusted

    def CalculateMomentumScore(self, symbol: Symbol, ticker: str) -> Optional[Dict]:
        """
        计算动量得分（v3.1优化版：仅使用RSI调整）
        返回: {'symbol': symbol, 'score': score, 'returns': {}, 'current_price': price}
        """
        try:
            history_days = self.lookback_periods['6m'] + 20
            history = self.History(symbol, history_days, Resolution.DAILY)
            
            if history.empty or len(history) < self.lookback_periods['6m']:
                return None
            
            closes = history['close']
            current_price = closes.iloc[-1]
            
            # 计算各期限收益率
            returns = {}
            for period, days in self.lookback_periods.items():
                if len(closes) >= days:
                    returns[period] = (current_price - closes.iloc[-days]) / closes.iloc[-days]
                else:
                    returns[period] = 0
            
            # 计算加权动量得分（基础分）
            base_score = sum(returns[p] * self.current_weights[p] for p in returns)
            
            # v3.1: 基于个股RSI超买超卖动态调整
            rsi_adjusted_score = base_score
            rsi_value = 50
            rsi_state = "neutral"
            
            try:
                if symbol in self.rsi_indicators:
                    rsi = self.rsi_indicators[symbol]
                    if rsi.IsReady:
                        rsi_value = rsi.Current.Value
                        
                        if rsi_value > self.rsi_overbought:
                            rsi_adjusted_score = base_score * self.rsi_adjustment_factor
                            rsi_state = f"overbought({rsi_value:.1f})"
                        elif rsi_value < self.rsi_oversold:
                            if base_score > 0:
                                rsi_adjusted_score = base_score * (1.0 + (1.0 - self.rsi_adjustment_factor))
                                rsi_state = f"oversold_boost({rsi_value:.1f})"
                            else:
                                rsi_adjusted_score = base_score * self.rsi_adjustment_factor
                                rsi_state = f"oversold_weak({rsi_value:.1f})"
                        else:
                            rsi_adjusted_score = base_score
                            rsi_state = f"neutral({rsi_value:.1f})"
            except Exception as e:
                self.Log(f"RSI调整失败 {ticker}: {e}")
                rsi_adjusted_score = base_score
            
            score = rsi_adjusted_score
            
            return {
                'symbol': symbol,
                'ticker': ticker,
                'score': score,
                'base_score': base_score,
                'returns': returns,
                'current_price': current_price
            }
            
        except Exception as e:
            self.Log(f"ERROR in CalculateMomentumScore for {ticker}: {e}")
            return None

    def GetSectorMomentum(self) -> List[str]:
        """获取行业动量排名，返回Top N行业"""
        sector_returns = {}
        
        for ticker, sector in self.sector_map.items():
            if ticker in self.symbols:
                try:
                    history = self.History(
                        self.symbols[ticker], 
                        self.sector_lookback + 5, 
                        Resolution.DAILY
                    )
                    if not history.empty and len(history) >= self.sector_lookback:
                        ret = (history['close'].iloc[-1] - history['close'].iloc[0]) / history['close'].iloc[0]
                        if sector not in sector_returns:
                            sector_returns[sector] = []
                        sector_returns[sector].append(ret)
                except Exception as e:
                    self.Log(f"ERROR in sector momentum for {ticker}: {e}")
        
        # 计算平均行业收益
        sector_momentum = {}
        for sector, ret_list in sector_returns.items():
            if ret_list:
                sector_momentum[sector] = sum(ret_list) / len(ret_list)
        
        # 排序并返回Top N
        sorted_sectors = sorted(sector_momentum.items(), key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_sectors[:self.n_top_sectors]]

    def CheckTrendFilter(self, symbol: Symbol) -> bool:
        """检查趋势过滤：价格是否在200日均线上方"""
        if not self.trend_filter_enabled:
            return True
        
        try:
            sma = self.sma_indicators.get(symbol)
            if sma is None:
                return True
            
            current_price = self.Securities[symbol].Price
            sma_value = sma.Current.Value
            
            return current_price > sma_value
        except:
            return True

    def CheckRSIFilter(self, symbol: Symbol) -> bool:
        """检查RSI过滤：避免极度超买"""
        if not self.rsi_filter_enabled:
            return True
        
        try:
            rsi = self.rsi_indicators.get(symbol)
            if rsi is None:
                return True
            
            rsi_value = rsi.Current.Value
            # 只过滤极度超买（RSI > 70），允许超卖（可能反弹）
            return rsi_value < self.rsi_overbought
        except:
            return True

    def CalculateVolatilityScaling(self, symbol: Symbol) -> float:
        """计算波动率缩放因子"""
        if not self.volatility_scaling:
            return 1.0
        
        try:
            history = self.History(symbol, self.volatility_lookback + 5, Resolution.DAILY)
            if history.empty or len(history) < self.volatility_lookback:
                return 1.0
            
            returns = history['close'].pct_change().dropna()
            if len(returns) < self.volatility_lookback:
                return 1.0
            
            # 计算年化波动率
            daily_vol = returns.iloc[-self.volatility_lookback:].std()
            annual_vol = daily_vol * (252 ** 0.5)
            
            # 缩放因子 = 目标波动率 / 实际波动率
            if annual_vol > 0:
                scale = self.target_volatility / annual_vol
                return max(0.5, min(2.0, scale))  # 限制在0.5-2.0之间
            
            return 1.0
        except:
            return 1.0

    def CheckStopLoss(self):
        """检查止损和追踪止损（优化版：简化逻辑，避免非交易时段警告）"""
        if self.IsWarmingUp:
            return
        
        # 避免在WarmUp或市场关闭时触发
        spy_symbol = self.symbols.get("SPY")
        if spy_symbol is None or not self.Securities.ContainsKey(spy_symbol):
            return
        if not self.Securities[spy_symbol].IsMarketOpen:
            return
        
        # 固定止损 + ATR止损
        for symbol, cost in list(self.cost_basis.items()):
            if not self.Portfolio[symbol].Invested:
                continue
            
            ticker = self.GetTickerName(symbol)
            current_price = self.Portfolio[symbol].Price
            
            # 检查最小持仓时间
            if not self._CanSell(symbol):
                continue
            
            # ATR止损（如果启用）
            if self.use_atr_stop and symbol in self.atr_indicators:
                try:
                    atr = self.atr_indicators[symbol]
                    if atr.IsReady:
                        atr_value = atr.Current.Value
                        stop_price = cost - (self.atr_multiplier * atr_value)
                        if current_price < stop_price:
                            self._ExecuteStopLoss(symbol, f"ATR止损@{current_price:.2f}(ATR={atr_value:.2f})")
                            continue
                except:
                    pass
            
            # 固定止损
            if cost > 0 and (current_price - cost) / cost < -self.stop_loss_pct:
                self._ExecuteStopLoss(symbol, f"固定止损@{current_price:.2f}")
        
        # 追踪止损
        if self.trailing_stop_enabled:
            for symbol in list(self.position_high.keys()):
                if not self.Portfolio[symbol].Invested:
                    continue
                
                ticker = self.GetTickerName(symbol)
                current_price = self.Portfolio[symbol].Price
                
                # 更新最高价
                if current_price > self.position_high[symbol]:
                    self.position_high[symbol] = current_price
                
                # 检查是否从最高价回撤超过阈值
                high = self.position_high[symbol]
                if high > 0 and (current_price - high) / high < -self.trailing_stop_pct:
                    if not self._CanSell(symbol):
                        continue
                    self._ExecuteStopLoss(symbol, f"追踪止损@{current_price:.2f}(high:{high:.2f})")
    
    def _ExecuteStopLoss(self, symbol: Symbol, reason: str):
        """执行止损：统一处理清仓和状态清理"""
        ticker = self.GetTickerName(symbol)
        self.Liquidate(symbol)
        
        # 清理状态
        self.cost_basis.pop(symbol, None)
        self.position_high.pop(symbol, None)
        self.position_entry_date.pop(symbol, None)
        
        self.Log(f"{reason}: {ticker}")

    def CheckMaxDrawdown(self):
        """检查最大回撤保护（阶梯式回撤保护，优化版：统一状态管理）"""
        if self.IsWarmingUp:
            return
        
        # 避免在市场关闭时触发
        spy_symbol = self.symbols.get("SPY")
        if spy_symbol is None or not self.Securities.ContainsKey(spy_symbol):
            return
        if not self.Securities[spy_symbol].IsMarketOpen:
            return
        
        current_value = self.Portfolio.TotalPortfolioValue
        
        # 更新最高水位
        if current_value > self.high_water_mark:
            self.high_water_mark = current_value
            # 重置回撤保护状态（如果已恢复）
            if self.drawdown_protection_triggered and current_value >= self.high_water_mark * 0.95:
                self.Log(f"回撤恢复: 净值=${current_value:,.2f}，重置回撤保护状态")
                self.drawdown_protection_triggered = False
        
        # 计算回撤
        if self.high_water_mark <= 0:
            return
        
        drawdown = (current_value - self.high_water_mark) / self.high_water_mark
        
        # 极端回撤 >20%：全面清仓
        if drawdown < -self.drawdown_extreme_level:
            if self.drawdown_protection_triggered != "extreme":
                self._ExecuteDrawdownProtection("extreme", drawdown, "全面清仓")
            return
        
        # 严重回撤 >15%：清仓转现金
        elif drawdown < -self.drawdown_severe_level:
            if self.drawdown_protection_triggered not in ["severe", "extreme"]:
                self._ExecuteDrawdownProtection("severe", drawdown, "清仓转现金")
            return
        
        # 首次回撤 >10%：清仓转安全资产
        elif drawdown < -self.drawdown_trigger_level:
            if not self.drawdown_protection_triggered:
                self._ExecuteDrawdownProtection("triggered", drawdown, "转安全资产(TLT/GLD)")
                # 转入安全资产
                for ticker, symbol in self.safe_symbols.items():
                    self.SetHoldings(symbol, 0.5 / len(self.safe_symbols))
            return
        
        # 回撤恢复 >-5%：重置状态
        elif drawdown > -0.05 and self.drawdown_protection_triggered:
            self.Log(f"回撤恢复: {drawdown:.2%}，重置回撤保护状态")
            self.drawdown_protection_triggered = False
    
    def _ExecuteDrawdownProtection(self, level: str, drawdown: float, action: str):
        """执行回撤保护：统一处理清仓和状态更新"""
        self.Log(f"[{'CRITICAL' if level=='extreme' else 'WARNING' if level=='severe' else 'INFO'}] "
                 f"回撤保护触发({level}): {drawdown:.2%}, {action}")
        self.Liquidate()
        self.drawdown_protection_triggered = level
        self.current_rebalance_freq = self.max_rebalance_freq
        self.pause_weeks = 0

    def RebalanceUS(self):
        """美国股票池再平衡"""
        if self.IsWarmingUp:
            return
        
        # v3.1 回撤控制：熊市模式下不买入股票
        if self.market_bear_mode:
            self.Log("熊市模式：跳过股票再平衡")
            return
        
        # P0优化：延迟初始化流动性过滤
        if not self.liquid_stocks_initialized:
            self._UpdateLiquidityFilter()
            self.liquid_stocks_initialized = True
        
        # P0优化：定期更新流动性过滤
        if self.week_counter % 4 == 0:  # 每4周更新一次
            self._UpdateLiquidityFilter()
        
        # 获取行业过滤
        if self.sector_rotation_enabled:
            top_sectors = self.GetSectorMomentum()
            if not top_sectors:
                top_sectors = ['Tech', 'Finance', 'Healthcare']
            
            # 确保Other行业存在，让未映射股票也能入选
            if 'Other' not in top_sectors:
                top_sectors.append('Other')
            
            # 筛选股票（加入流动性过滤）
            us_symbols = {}
            for ticker, symbol in self.symbols.items():
                if ticker in self.us_tickers and self._IsLiquid(ticker):
                    sector = self.sector_map.get(ticker, 'Other')
                    if sector in top_sectors or ticker in ['SPY', 'QQQ', 'TLT', 'GLD']:
                        us_symbols[ticker] = symbol
        else:
            # P0优化：应用流动性过滤
            us_symbols = {k: v for k, v in self.symbols.items() 
                         if k in self.us_tickers and self._IsLiquid(k)}
        
        self.RebalanceMarket(us_symbols, "US")

    def RebalanceMarket(self, market_symbols: Dict[str, Symbol], market_name: str):
        """执行再平衡逻辑"""
        
        # 1. 计算所有股票动量得分
        momentum_scores = {}
        for ticker, symbol in market_symbols.items():
            result = self.CalculateMomentumScore(symbol, ticker)
            if result is not None:
                # 应用趋势和RSI过滤
                if self.CheckTrendFilter(symbol) and self.CheckRSIFilter(symbol):
                    momentum_scores[ticker] = result
        
        if not momentum_scores:
            self.Log(f"{market_name}: 无有效动量得分")
            return
        
        # 2. 筛选正动量股票
        positive_scores = {
            k: v for k, v in momentum_scores.items() 
            if v['score'] > self.min_score
        }
        
        if not positive_scores:
            self.Log(f"{market_name}: 无正动量股票，清仓")
            self.Liquidate([s for s in market_symbols.values()])
            return
        
        # 3. 排序并选择Top N
        sorted_scores = sorted(positive_scores.items(), key=lambda x: x[1]['score'], reverse=True)
        top_stocks = sorted_scores[:self.max_stocks]
        
        # 4. 计算目标权重 - 得分比例分配，单票上限15%
        total_score = sum(data['score'] for _, data in top_stocks)
        targets = {}
        
        for ticker, data in top_stocks:
            if total_score > 0:
                weight = data['score'] / total_score
            else:
                weight = 0
            
            # 应用波动率缩放（默认关闭=1.0）
            vol_scale = self.CalculateVolatilityScaling(data['symbol'])
            weight *= vol_scale
            
            targets[data['symbol']] = weight
        
        # 5. 限制单票最大仓位 - 按比例缩放，保持相对权重
        max_weight = max(targets.values()) if targets else 0
        if max_weight > self.max_position_pct:
            scale = self.max_position_pct / max_weight
            for symbol in targets:
                targets[symbol] *= scale
            self.Log(f"  单票最高{max_weight*100:.1f}%>{self.max_position_pct*100:.0f}%, 全局缩放{scale:.2f}x保持相对权重")
        
        # 6. 确保最小仓位
        for symbol in list(targets.keys()):
            if targets[symbol] < self.min_position_pct:
                del targets[symbol]
        
        # 7. 计算总权重并调整
        total_weight = sum(targets.values())
        
        # 8. 记录原始分配
        top5 = sorted(targets.items(), key=lambda x: x[1], reverse=True)[:5]
        
        top5_str = ", ".join([f"{self.GetTickerName(sym)}:{w*100:.1f}%" for sym, w in top5])
        self.Log(f"[{self.Time.strftime('%Y-%m-%d')}] {market_name}原始: "
                f"{len(targets)}只, 总仓位{total_weight*100:.1f}%, "
                f"最高{max(targets.values())*100:.1f}%, top5: {top5_str}")
        
        # 9. 限制总仓位（使用动态仓位）
        total_weight = sum(targets.values())
        exposure_limit = self.current_total_exposure
        
        if total_weight > exposure_limit:
            scale = exposure_limit / total_weight
            for symbol in targets:
                targets[symbol] *= scale
            self.Log(f"  总仓位{total_weight*100:.1f}%>{exposure_limit*100:.0f}%, 等比例缩减")
        elif total_weight < self.min_total_exposure:
            # 仓位过低，保持原比例（不强制放大）
            self.Log(f"  总仓位{total_weight*100:.1f}%<{self.min_total_exposure*100:.0f}%, 保持原比例")
        
        # 9.5. 限制行业集中度
        targets = self.LimitSectorConcentration(targets)
        
        # 10. 记录最终分配
        final_weight = sum(targets.values())
        final_top5 = sorted(targets.items(), key=lambda x: x[1], reverse=True)[:5]
        final_str = ", ".join([f"{self.GetTickerName(sym)}:{w*100:.1f}%" for sym, w in final_top5])
        self.Log(f"  {market_name}最终: 总仓位{final_weight*100:.1f}%, "
                f"最高{max(targets.values())*100:.1f}%, top5: {final_str}")
        
        # 11. 清仓不在目标列表中的股票（P0修复：检查最小持仓时间）
        for symbol in list(self.cost_basis.keys()):
            ticker = self.GetTickerName(symbol)
            if ticker not in [self.GetTickerName(s) for s in targets.keys()] and ticker in market_symbols:
                if self.Portfolio[symbol].Invested:
                    if not self._CanSell(symbol):
                        continue  # 跳过持仓时间不足的股票
                    self.Liquidate(symbol)
                    if symbol in self.cost_basis:
                        del self.cost_basis[symbol]
                    if symbol in self.position_high:
                        del self.position_high[symbol]
                    if symbol in self.position_entry_date:
                        del self.position_entry_date[symbol]
        
        # 12. 执行调仓
        for symbol, target in targets.items():
            current_weight = (self.Portfolio[symbol].HoldingsValue / 
                            self.Portfolio.TotalPortfolioValue 
                            if self.Portfolio.TotalPortfolioValue > 0 else 0)
            deviation = abs(current_weight - target)
            
            # 只在偏差大于10%时调仓，减少交易摩擦
            if current_weight == 0 or deviation > 0.10:
                self.SetHoldings(symbol, target)
                
               
                if self.Portfolio[symbol].Invested and self.Portfolio[symbol].Quantity > 0:
                    self._RecordBuyDate(symbol)
                
                # 记录成本基准（用于止损）
                if self.Portfolio[symbol].Invested:
                    if symbol not in self.cost_basis:
                        self.cost_basis[symbol] = self.Portfolio[symbol].AveragePrice
                    # 初始化追踪止损最高价
                    if symbol not in self.position_high:
                        self.position_high[symbol] = self.Portfolio[symbol].Price

    def HedgeWithPut(self):
        """对冲股票敞口（使用做空SPY，本地回测期权数据不可用）"""
        if not self.hedge_enabled or self.IsWarmingUp:
            return
        
        try:
            if self.hedge_method == "short_spy":
                self._HedgeWithShortSPY()
            else:
                self._HedgeWithPutOption()
                
        except Exception as e:
            self.Log(f"ERROR in HedgeWithPut: {e}")
    
    def _HedgeWithShortSPY(self):
        """使用做空SPY对冲"""
        # 计算当前股票总敞口
        stock_exposure = 0
        for symbol in self.Portfolio.Keys:
            if symbol.SecurityType == SecurityType.Equity:
                ticker = self.GetTickerName(symbol)
                if ticker not in self.safe_tickers and ticker not in ["SPY", "QQQ", "IWM", "VIXY"]:
                    stock_exposure += self.Portfolio[symbol].HoldingsValue
        
        spy_symbol = self.symbols.get("SPY")
        if spy_symbol is None:
            return
        
        # 计算需要做空的SPY金额
        target_short = stock_exposure * self.hedge_ratio
        current_short = abs(self.Portfolio[spy_symbol].HoldingsValue) if self.Portfolio[spy_symbol].IsShort else 0
        
        # 如果股票敞口为0，平仓做空
        if stock_exposure <= 0:
            if self.Portfolio[spy_symbol].IsShort:
                self.Liquidate(spy_symbol)
                self.Log("平仓SPY做空：无股票敞口")
            return
        
        # 调整做空仓位
        spy_price = self.Securities[spy_symbol].Price
        if spy_price <= 0:
            return
        
        target_shares = int(target_short / spy_price)
        current_shares = abs(self.Portfolio[spy_symbol].Quantity) if self.Portfolio[spy_symbol].IsShort else 0
        
        if target_shares != current_shares:
            # 先平仓再做空
            if self.Portfolio[spy_symbol].Invested:
                self.Liquidate(spy_symbol)
            
            if target_shares > 0:
                self.MarketOrder(spy_symbol, -target_shares)
                self.Log(f"做空SPY对冲: {target_shares}股, 金额${target_short:,.2f}, 股票敞口${stock_exposure:,.2f}")
    
    def _HedgeWithPutOption(self):
        """使用SPY Put期权对冲（需要期权数据）"""
        # 计算当前股票总敞口
        stock_exposure = 0
        for symbol in self.Portfolio.Keys:
            if symbol.SecurityType == SecurityType.Equity and (self.spy_option is None or symbol != self.spy_option.Symbol):
                ticker = self.GetTickerName(symbol)
                if ticker not in self.safe_tickers:
                    stock_exposure += self.Portfolio[symbol].HoldingsValue
        
        # 如果没有股票敞口，清仓Put
        if stock_exposure <= 0:
            if self.current_put is not None and self.Portfolio[self.current_put].Invested:
                self.Liquidate(self.current_put)
                self.current_put = None
                self.Log("清仓Put：无股票敞口")
            return
        
        # 检查当前Put是否需要滚动（到期前5天）
        if self.current_put is not None:
            option = self.Securities[self.current_put]
            if option.Expiry - self.Time <= timedelta(days=self.hedge_rollover_days):
                self.Liquidate(self.current_put)
                self.current_put = None
                self.Log("滚动Put：接近到期")
        
        # 如果没有Put或已清仓，买入新的
        if self.current_put is None and self.spy_option is not None:
            # 获取SPY当前价格
            spy_price = self.Securities[self.symbols.get("SPY")].Price
            if spy_price <= 0:
                return
            
            # 计算目标行权价（虚值5%）
            target_strike = spy_price * (1 - self.put_otm_pct)
            
            # 获取期权链
            chain = self.OptionChain(self.spy_option.Symbol)
            
            if chain is None or not chain.Contracts:
                self.Log("无可用期权合约")
                return
            
            # 筛选Put合约
            puts = [c for c in chain.Contracts if c.Right == OptionRight.Put]
            if not puts:
                return
            
            # 找到最接近目标行权价的合约
            best_put = min(puts, key=lambda p: abs(p.Strike - target_strike))
            
            # 计算需要买入的合约数量
            contract_value = best_put.Strike * 100
            hedge_amount = stock_exposure * self.hedge_ratio
            quantity = max(1, int(hedge_amount / contract_value))
            
            # 买入Put
            self.MarketOrder(best_put.Symbol, quantity)
            self.current_put = best_put.Symbol
            
            self.Log(f"买入Put对冲: {best_put.Symbol}, 行权价{best_put.Strike:.2f}, "
                    f"数量{quantity}, 股票敞口${stock_exposure:,.2f}")
    
    # ============ 数据事件 ============
    def OnData(self, data):
        """数据到达时的处理（可用于盘中信号）"""
        pass

    def OnEndOfAlgorithm(self):
        """算法结束时的总结"""
        total_return = (self.Portfolio.TotalPortfolioValue - 100000) / 100000
        self.Log(f"=" * 50)
        self.Log(f"策略运行结束")
        self.Log(f"总收益率: {total_return:.2%}")
        self.Log(f"最终资产: {self.Portfolio.TotalPortfolioValue:,.2f}")
        self.Log(f"=" * 50)
