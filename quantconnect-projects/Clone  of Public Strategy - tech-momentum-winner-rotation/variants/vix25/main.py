#region imports
from AlgorithmImports import *
#endregion

class AdaptiveMomentumStrategy(QCAlgorithm):
    """
    自适应多维度动量策略 - 终极版
    
    核心特性:
    1. 六维度动量: 1d/1w/2w/1m/3m/6m
    2. 动态权重: 根据市场波动率自适应调整
    3. VIX过滤: VIX>30时降低整体仓位
    4. 行业轮动: 只选最强行业的Top股票
    5. 双市场: 美股(周一) + 港股(周二)
    6. 止损: 单票15%止损
    """
    
    def Initialize(self):
        # === 基本设置 ===
        self.SetStartDate(2022, 1, 1)
        self.SetEndDate(2025, 6, 1)
        self.SetCash(100000)
        
        # === 动量参数（基础权重，会被动态调整）===
        self.lookback_1d = 1
        self.lookback_1w = 5
        self.lookback_2w = 10
        self.lookback_1m = 21
        self.lookback_3m = 63
        self.lookback_6m = 126
        
        # 基础权重
        self.base_weight_1d = 0.1
        self.base_weight_1w = 0.5
        self.base_weight_2w = 1.0
        self.base_weight_1m = 1.0
        self.base_weight_3m = 1.0
        self.base_weight_6m = 1.0
        
        # 当前动态权重（会随波动率变化）
        self.current_weights = {
            '1d': self.base_weight_1d,
            '1w': self.base_weight_1w,
            '2w': self.base_weight_2w,
            '1m': self.base_weight_1m,
            '3m': self.base_weight_3m,
            '6m': self.base_weight_6m
        }
        
        # === 估值参数（动态权重 + 多指标）===
        self.valuation_data = {}  # 存储估值数据（包含PE、Forward PE、PB、PS、PEG）
        self.enable_valuation_filter = True  # 启用估值过滤
        
        # 动态估值权重：根据市场环境自动调整
        self.valuation_weight_min = 0.2  # 牛市时最小估值权重
        self.valuation_weight_max = 0.5  # 熊市时最大估值权重
        self.valuation_weight = 0.3  # 当前估值权重（会被动态调整）
        self.momentum_weight = 0.7   # 动量权重
        
        # 估值倍数范围
        self.valuation_multiplier_min = 0.5  # 高估时最小仓位倍数
        self.valuation_multiplier_max = 1.5  # 低估时最大仓位倍数
        
        # 加载估值数据（包含PE、Forward PE、PB、PS、PEG）
        self.LoadValuationData()
        
        # === 波动率参数 ===
        self.volatility_lookback = 20  # 20日波动率
        self.high_vol_threshold = 0.025  # 日波动率 > 2.5% 视为高波动
        self.low_vol_threshold = 0.01   # 日波动率 < 1% 视为低波动
        
        # === VIX参数 ===
        self.vix_symbol = self.AddEquity("VIXY", Resolution.Daily).Symbol  # VIX ETF代理
        self.vix_threshold = 30.0  # VIX > 30 视为高风险
        self.vix_high_position_scale = 0.5  # 高风险时仓位减半
        
        # === 仓位管理 ===
        self.max_position_per_stock = 0.15
        self.top_n_stocks = 15  # 增加持仓数量到15只
        self.min_momentum_score = 0.0
        self.global_position_scale = 1.0  # 全局仓位缩放（由VIX控制）
        
        # === 行业轮动参数 ===
        self.enable_sector_rotation = True
        self.top_n_sectors = 3  # 所有行业都选（禁用轮动）
        self.sector_lookback = 63  # 用3月收益率计算行业动量
        
        # 美股行业分类（简化版）
        self.sector_map = {
            # 科技
            'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech', 'META': 'Tech',
            'AMZN': 'Tech', 'TSLA': 'Tech', 'AMD': 'Tech', 'INTC': 'Tech', 'CRM': 'Tech',
            'ORCL': 'Tech', 'ADBE': 'Tech', 'CSCO': 'Tech', 'AVGO': 'Tech', 'QCOM': 'Tech',
            'TXN': 'Tech', 'AMAT': 'Tech', 'MU': 'Tech', 'NFLX': 'Tech', 'INTU': 'Tech',
            'ANET': 'Tech', 'FSLR': 'Tech', 'FTNT': 'Tech', 'SNPS': 'Tech', 'KLAC': 'Tech',
            'MRVL': 'Tech', 'NXPI': 'Tech', 'SWKS': 'Tech', 'MCHP': 'Tech', 'CDNS': 'Tech',
            'DDOG': 'Tech', 'NET': 'Tech', 'PLTR': 'Tech', 'CRM': 'Tech', 'NOW': 'Tech',
            # 金融
            'JPM': 'Finance', 'BAC': 'Finance', 'GS': 'Finance', 'MS': 'Finance', 'WFC': 'Finance',
            'BLK': 'Finance', 'C': 'Finance', 'AXP': 'Finance', 'SCHW': 'Finance', 'PNC': 'Finance',
            'TFC': 'Finance', 'USB': 'Finance', 'COF': 'Finance', 'SPGI': 'Finance', 'MCO': 'Finance',
            'BK': 'Finance', 'STT': 'Finance', 'ICE': 'Finance', 'CME': 'Finance', 'NDAQ': 'Finance',
            # 医疗
            'JNJ': 'Healthcare', 'UNH': 'Healthcare', 'LLY': 'Healthcare', 'PFE': 'Healthcare',
            'MRK': 'Healthcare', 'ABBV': 'Healthcare', 'ABT': 'Healthcare', 'TMO': 'Healthcare',
            'DHR': 'Healthcare', 'BMY': 'Healthcare', 'AMGN': 'Healthcare', 'GILD': 'Healthcare',
            'VRTX': 'Healthcare', 'REGN': 'Healthcare', 'BIIB': 'Healthcare', 'MRNA': 'Healthcare',
            # 消费
            'HD': 'Consumer', 'COST': 'Consumer', 'NKE': 'Consumer', 'MCD': 'Consumer',
            'SBUX': 'Consumer', 'LOW': 'Consumer', 'TJX': 'Consumer', 'PG': 'Consumer',
            'KO': 'Consumer', 'PEP': 'Consumer', 'WMT': 'Consumer', 'MDLZ': 'Consumer',
            'CL': 'Consumer', 'KMB': 'Consumer', 'GIS': 'Consumer', 'CPB': 'Consumer',
            # 能源
            'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'EOG': 'Energy', 'SLB': 'Energy',
            'OXY': 'Energy', 'MPC': 'Energy', 'VLO': 'Energy', 'PSX': 'Energy', 'KMI': 'Energy',
            # 工业
            'CAT': 'Industrial', 'HON': 'Industrial', 'UPS': 'Industrial', 'BA': 'Industrial',
            'GE': 'Industrial', 'RTX': 'Industrial', 'LMT': 'Industrial', 'NOC': 'Industrial',
            'GD': 'Industrial', 'ITW': 'Industrial', 'MMM': 'Industrial', 'EMR': 'Industrial',
            # 通信
            'VZ': 'Telecom', 'T': 'Telecom', 'CMCSA': 'Telecom', 'CHTR': 'Telecom', 
            'TMUS': 'Telecom', 'CCI': 'Telecom', 'AMT': 'Telecom',
        }
        
        # === 港股特殊参数 ===
        self.hk_max_position = 0.05       # 港股单票上限5%（低于美股的15%）
        self.hk_market_timing = True      # 启用港股市场择时
        self.hk_min_market_momentum = 0.0 # 港股市场动量>0时才配置
        self.enable_hk = True             # 启用港股
        
        # === 固定基础调仓周期（每2周） ===
        self.base_rebalance_freq = 2   # 基础每2周调仓一次
        self.min_rebalance_freq = 1    # 最小每周调仓（VIX低时临时增加）
        self.max_rebalance_freq = 8    # 最大每8周调仓（VIX高时暂停）
        self.week_counter = 0  # 周计数器
        self.current_rebalance_freq = 2  # 当前实际调仓周期
        self.consecutive_pause_weeks = 0  # 连续暂停周数
        
        # 暂停和临时增加条件
        self.vix_pause_threshold = 25   # VIX > 25：暂停调仓（延长周期）
        self.vix_boost_threshold = 18   # VIX < 18：临时增加调仓（缩短周期）
        self.valuation_extreme_threshold = 0.8  # 估值分位 > 80% 或 < 20%：暂停
        self.max_pause_weeks = 4  # 最长暂停4周
        
        # === 纯美股模式配置 ===
        self.us_allocation_base = 1.0     # 美股100%
        self.hk_allocation_base = 0.0     # 港股0%（禁用）
        self.enable_relative_strength = False  # 禁用相对强度（纯美股不需要）
        self.enable_hk = False             # 禁用港股
        
        # === 止损设置 ===
        self.stop_loss_pct = 0.15
        
        # === 股票池 ===
        self.us_tickers = [
            "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "INTC", "CRM",
            "ORCL", "ADBE", "CSCO", "AVGO", "QCOM", "TXN", "AMAT", "MU", "NFLX", "INTU",
            "ANET", "FSLR", "FTNT", "SNPS", "KLAC", "MRVL", "NXPI", "SWKS", "MCHP", "CDNS",
            "DDOG", "PLTR", "NOW", "NET", "JPM", "BAC", "GS", "MS", "WFC", "BLK",
            "C", "AXP", "SCHW", "PNC", "SPGI", "MCO", "ICE", "CME", "JNJ", "UNH",
            "LLY", "PFE", "MRK", "ABBV", "ABT", "TMO", "DHR", "BMY", "AMGN", "GILD",
            "REGN", "VRTX", "MRNA", "HD", "COST", "NKE", "MCD", "SBUX", "LOW", "TJX",
            "PG", "KO", "PEP", "WMT", "MDLZ", "XOM", "CVX", "COP", "SLB", "OXY",
            "CAT", "HON", "UPS", "BA", "GE", "RTX", "LMT", "VZ", "T", "CMCSA",
            "SPY", "QQQ", "IWM", "TLT", "GLD", "VIXY"
        ]
        
        # === 纯美股模式 ===
        self.hk_tickers = []  # 禁用港股
        self.tickers = self.us_tickers[:]  # 只使用美股
        
        # 避险资产
        self.safe_tickers = ["TLT", "GLD"]
        self.safe_symbols = {}
        
        self.symbols = {}
        valid_tickers = []
        
        for ticker in self.tickers:
            try:
                self.symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
                valid_tickers.append(ticker)
            except:
                pass
        
        self.tickers = valid_tickers
        
        for ticker in self.safe_tickers:
            self.safe_symbols[ticker] = self.AddEquity(ticker, Resolution.Daily).Symbol
        
        # 记录成本价
        self.cost_basis = {}
        
        # === 调度 - 双市场时区处理（改为每2周）===
        # 每周一检查，但每2周执行一次
        self.Schedule.On(
            self.DateRules.Every(DayOfWeek.Monday),
            self.TimeRules.AfterMarketOpen("SPY", 5),
            self.WeeklyUpdate
        )
        
        self.Schedule.On(
            self.DateRules.Every(DayOfWeek.Tuesday),
            self.TimeRules.AfterMarketOpen("0700", 30),
            self.WeeklyHKUpdate
        )
        
        # 每日检查止损
        self.Schedule.On(
            self.DateRules.EveryDay("SPY"),
            self.TimeRules.AfterMarketOpen("SPY", 60),
            self.CheckStopLoss
        )
        
        # Warm up
        warmup_days = max(self.lookback_6m, self.sector_lookback) + 20
        self.SetWarmUp(timedelta(days=warmup_days))
        
        # 图表
        portfolio_chart = Chart("Portfolio")
        portfolio_chart.AddSeries(Series("Value", SeriesType.Line, "$"))
        self.AddChart(portfolio_chart)
        
        vol_chart = Chart("Volatility")
        vol_chart.AddSeries(Series("DailyVol", SeriesType.Line, "%"))
        vol_chart.AddSeries(Series("VIXY", SeriesType.Line, "$"))
        self.AddChart(vol_chart)
    
    def WeeklyUpdate(self):
        """每周一检查，固定周期调仓 + 根据VIX/估值暂停或临时增加"""
        self.week_counter += 1
        
        # 根据VIX和估值调整当前调仓周期
        self.AdjustRebalanceFrequency()
        
        # 判断是否到调仓日
        if self.week_counter % self.current_rebalance_freq == 1:
            self.Debug(f"🔄 执行调仓（第{self.week_counter}周，周期{self.current_rebalance_freq}周）")
            self.UpdateAdaptiveWeights()
            self.RebalanceUS()
        else:
            self.Debug(f"⏸ 跳过调仓（第{self.week_counter}周，周期{self.current_rebalance_freq}周）")
    
    def AdjustRebalanceFrequency(self):
        """根据VIX和估值动态调整调仓频率"""
        try:
            vixy_price = self.Portfolio[self.vix_symbol].Price if self.Portfolio[self.vix_symbol].Price > 0 else 25
            
            # 获取SPY估值水平（3月动量作为代理）
            spy_valuation = 0.5
            try:
                spy_history = self.History(self.symbols.get("SPY"), 63, Resolution.Daily)
                if not spy_history.empty and len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[-63]) - 1
                    spy_valuation = 0.5 + spy_3m_return * 2  # 映射到0-1
                    spy_valuation = max(0, min(1, spy_valuation))
            except:
                pass
            
            # 判断市场状态
            is_extreme_valuation = spy_valuation > self.valuation_extreme_threshold or spy_valuation < (1 - self.valuation_extreme_threshold)
            
            # 根据VIX和估值调整周期
            if vixy_price > self.vix_pause_threshold or is_extreme_valuation:
                # 高VIX或极端估值：暂停调仓（延长周期）
                new_freq = min(self.current_rebalance_freq + 1, self.max_rebalance_freq)
                if new_freq != self.current_rebalance_freq:
                    self.consecutive_pause_weeks += 1
                    self.Debug(f"⏸ 市场极端（VIX={vixy_price:.1f}），调仓周期延长至{new_freq}周")
                else:
                    self.Debug(f"⏸ 市场极端（VIX={vixy_price:.1f}），维持最大周期{new_freq}周")
                self.current_rebalance_freq = new_freq
            elif vixy_price < self.vix_boost_threshold and not is_extreme_valuation:
                # 低VIX + 正常估值：临时增加调仓（缩短周期）
                new_freq = max(self.current_rebalance_freq - 1, self.min_rebalance_freq)
                if new_freq != self.current_rebalance_freq:
                    self.Debug(f"⚡ 市场平静（VIX={vixy_price:.1f}），调仓周期缩短至{new_freq}周")
                self.current_rebalance_freq = new_freq
                self.consecutive_pause_weeks = 0
            else:
                # 正常市场：回归基础周期
                if self.current_rebalance_freq != self.base_rebalance_freq:
                    self.Debug(f"📊 市场正常（VIX={vixy_price:.1f}），回归基础周期{self.base_rebalance_freq}周")
                self.current_rebalance_freq = self.base_rebalance_freq
                self.consecutive_pause_weeks = 0
            
            # 限制最长暂停时间
            if self.consecutive_pause_weeks >= self.max_pause_weeks:
                self.current_rebalance_freq = self.base_rebalance_freq
                self.consecutive_pause_weeks = 0
                self.Debug(f"⚠️ 暂停已达{self.max_pause_weeks}周，强制回归基础周期")
                
        except Exception as e:
            self.Debug(f"调仓频率调整失败: {e}")
            self.current_rebalance_freq = self.base_rebalance_freq
    
    def WeeklyHKUpdate(self):
        """每周二检查 - 纯美股模式下不执行港股调仓"""
        if not self.enable_hk:
            return
        if self.week_counter % self.current_rebalance_freq == 1:
            self.RebalanceHK()
    
    def RebalanceUS(self, adjustment_type='medium'):
        """美股调仓 - 支持行业轮动 + 相对强度 + 三级调整"""
        if self.IsWarmingUp:
            return
        
        self.Debug(f"\n{'='*60}")
        self.Debug(f"🇺🇸 美股调仓 - {self.Time.strftime('%Y-%m-%d')} - {adjustment_type}调整")
        self.Debug(f"{'='*60}")
        
        # 获取行业轮动筛选
        if self.enable_sector_rotation:
            top_sectors = self.GetSectorMomentum()
            us_symbols = {}
            for k, v in self.symbols.items():
                if k in self.us_tickers:
                    sector = self.sector_map.get(k, 'Other')
                    if sector in top_sectors or k in ['SPY', 'QQQ', 'TLT', 'GLD']:
                        us_symbols[k] = v
        else:
            us_symbols = {k: v for k, v in self.symbols.items() if k in self.us_tickers}
        
        # 使用美股比例进行仓位缩放
        self.us_position_scale = 1.0
        self.RebalanceMarket(us_symbols, "US", is_hk=False, adjustment_type=adjustment_type)
    
    def WeeklyHKUpdate(self):
        """每周二检查 - 纯美股模式下不执行港股调仓"""
        if not self.enable_hk:
            return
        if self.week_counter % self.rebalance_large_freq == 1:
            self.RebalanceHK()
    
    def UpdateAdaptiveWeights(self):
        """根据市场波动率动态调整动量权重"""
        if self.IsWarmingUp:
            return
        
        try:
            # 计算SPY的20日实现波动率
            spy_history = self.History(self.symbols.get("SPY"), self.volatility_lookback + 5, Resolution.Daily)
            if not spy_history.empty and len(spy_history) >= self.volatility_lookback:
                spy_returns = spy_history['close'].pct_change().dropna()
                current_vol = spy_returns.iloc[-self.volatility_lookback:].std()
                
                # 获取VIXY价格（VIX代理）
                vixy_price = 0
                if self.Portfolio[self.vix_symbol].Price > 0:
                    vixy_price = self.Portfolio[self.vix_symbol].Price
                
                self.Debug(f"\n📊 波动率分析 - {self.Time.strftime('%Y-%m-%d')}")
                self.Debug(f"  SPY 20日波动率: {current_vol:.4f} ({current_vol*100:.2f}%)")
                self.Debug(f"  VIXY 价格: {vixy_price:.2f}")
                
                # 获取估值水平（使用SPY 3月动量作为代理）
                spy_3m_return = 0
                if not spy_history.empty and len(spy_history) >= 63:
                    spy_3m_return = (spy_history['close'].iloc[-1] / spy_history['close'].iloc[-63]) - 1
                
                # 判断估值水平
                if spy_3m_return > 0.15:
                    valuation_level = 'high'  # 高估值
                elif spy_3m_return < -0.15:
                    valuation_level = 'low'   # 低估值
                else:
                    valuation_level = 'medium'  # 中等估值
                
                self.Debug(f"  SPY 3月动量: {spy_3m_return:.2%} (估值: {valuation_level})")
                
                # 动态权重调整逻辑（根据估值+VIX交互）
                if current_vol > self.high_vol_threshold or vixy_price > self.vix_threshold:
                    if valuation_level == 'low':
                        # 低估值+VIX高：不过滤，恐慌时贪婪
                        self.current_weights = {
                            '1d': 0.0,
                            '1w': 0.2,
                            '2w': 0.5,
                            '1m': 1.0,
                            '3m': 1.5,
                            '6m': 2.0
                        }
                        self.global_position_scale = 1.0  # 不过滤
                        self.Debug(f"  ✅ 低估+VIX高: 不过滤，保持仓位")
                    elif valuation_level == 'high':
                        # 高估值+VIX高：严格过滤，恐慌时恐惧
                        self.current_weights = {
                            '1d': 0.0,
                            '1w': 0.2,
                            '2w': 0.5,
                            '1m': 1.0,
                            '3m': 1.5,
                            '6m': 2.0
                        }
                        self.global_position_scale = 0.3  # 大幅降低仓位
                        self.Debug(f"  ⚠️ 高估+VIX高: 严格过滤，仓位降至30%")
                    else:
                        # 中等估值+VIX高：正常过滤
                        self.current_weights = {
                            '1d': 0.0,
                            '1w': 0.2,
                            '2w': 0.5,
                            '1m': 1.0,
                            '3m': 1.5,
                            '6m': 2.0
                        }
                        self.global_position_scale = self.vix_high_position_scale
                        self.Debug(f"  ⚠️ 中估+VIX高: 正常过滤，仓位降至{self.global_position_scale:.0%}")
                    
                elif current_vol < self.low_vol_threshold:
                    # 低波动：增加短期权重
                    self.current_weights = {
                        '1d': 0.2,
                        '1w': 0.8,
                        '2w': 1.2,
                        '1m': 1.0,
                        '3m': 0.8,
                        '6m': 0.5
                    }
                    self.global_position_scale = 1.0
                    self.Debug(f"  ✅ 低波动模式: 增加短期权重")
                    
                else:
                    # 正常波动：使用基础权重
                    self.current_weights = {
                        '1d': self.base_weight_1d,
                        '1w': self.base_weight_1w,
                        '2w': self.base_weight_2w,
                        '1m': self.base_weight_1m,
                        '3m': self.base_weight_3m,
                        '6m': self.base_weight_6m
                    }
                    self.global_position_scale = 1.0
                    self.Debug(f"  ✓ 正常波动模式: 使用基础权重")
                
                # 动态估值权重调整（根据市场环境）
                if self.enable_valuation_filter:
                    # 根据市场动量和波动率调整估值权重
                    if spy_3m_return > 0.15 and current_vol < self.low_vol_threshold:
                        # 强牛市（高动量+低波动）：降低估值权重，更依赖动量
                        self.valuation_weight = self.valuation_weight_min  # 0.2
                        self.momentum_weight = 1.0 - self.valuation_weight_min  # 0.8
                        self.Debug(f"  📈 强牛市: 估值权重降至{self.valuation_weight:.0%}，动量权重{self.momentum_weight:.0%}")
                    elif spy_3m_return < -0.15 or current_vol > self.high_vol_threshold:
                        # 熊市或高波动：提高估值权重，更依赖估值保护
                        self.valuation_weight = self.valuation_weight_max  # 0.5
                        self.momentum_weight = 1.0 - self.valuation_weight_max  # 0.5
                        self.Debug(f"  📉 熊市/高波动: 估值权重升至{self.valuation_weight:.0%}，动量权重{self.momentum_weight:.0%}")
                    else:
                        # 正常市场：使用默认权重
                        self.valuation_weight = 0.3
                        self.momentum_weight = 0.7
                        self.Debug(f"  📊 正常市场: 估值权重{self.valuation_weight:.0%}，动量权重{self.momentum_weight:.0%}")
                
                # 动态估值权重调整（根据市场环境）
                if self.enable_valuation_filter:
                    # 根据市场动量和波动率调整估值权重
                    if spy_3m_return > 0.15 and current_vol < self.low_vol_threshold:
                        # 强牛市（高动量+低波动）：降低估值权重，更依赖动量
                        self.valuation_weight = self.valuation_weight_min  # 0.2
                        self.momentum_weight = 1.0 - self.valuation_weight_min  # 0.8
                        self.Debug(f"  📈 强牛市: 估值权重降至{self.valuation_weight:.0%}，动量权重{self.momentum_weight:.0%}")
                    elif spy_3m_return < -0.15 or current_vol > self.high_vol_threshold:
                        # 熊市或高波动：提高估值权重，更依赖估值保护
                        self.valuation_weight = self.valuation_weight_max  # 0.5
                        self.momentum_weight = 1.0 - self.valuation_weight_max  # 0.5
                        self.Debug(f"  📉 熊市/高波动: 估值权重升至{self.valuation_weight:.0%}，动量权重{self.momentum_weight:.0%}")
                    else:
                        # 正常市场：使用默认权重
                        self.valuation_weight = 0.3
                        self.momentum_weight = 0.7
                        self.Debug(f"  📊 正常市场: 估值权重{self.valuation_weight:.0%}，动量权重{self.momentum_weight:.0%}")
                
                # === 动态调仓频率调整（根据VIX） ===
                self.Plot("Volatility", "DailyVol", current_vol * 100)
                self.Plot("Volatility", "VIXY", vixy_price)
        except Exception as e:
            self.Debug(f"波动率计算错误: {e}")
    
    def CalculateMomentumScore(self, symbol, name):
        """计算动量分数（使用动态权重）"""
        try:
            history_days = self.lookback_6m + 20
            history = self.History(symbol, history_days, Resolution.Daily)
            
            if history.empty or len(history) < self.lookback_6m:
                return None
            
            closes = history['close']
            current_price = closes.iloc[-1]
            
            returns = {}
            for period, days in [
                ('1d', self.lookback_1d), ('1w', self.lookback_1w), 
                ('2w', self.lookback_2w), ('1m', self.lookback_1m),
                ('3m', self.lookback_3m), ('6m', self.lookback_6m)
            ]:
                if len(closes) >= days:
                    past_price = closes.iloc[-days]
                    returns[period] = (current_price - past_price) / past_price
                else:
                    returns[period] = 0
            
            # 使用动态权重
            score = sum(returns[p] * self.current_weights[p] for p in returns)
            
            return {
                'symbol': symbol,
                'score': score,
                'returns': returns,
                'current_price': current_price
            }
            
        except Exception as e:
            return None
    
    def GetSectorMomentum(self):
        """计算各行业动量，返回最强行业列表"""
        sector_returns = {}
        
        for ticker, sector in self.sector_map.items():
            if ticker in self.symbols:
                try:
                    history = self.History(self.symbols[ticker], self.sector_lookback + 5, Resolution.Daily)
                    if not history.empty and len(history) >= self.sector_lookback:
                        returns = (history['close'].iloc[-1] - history['close'].iloc[-self.sector_lookback]) / history['close'].iloc[-self.sector_lookback]
                        if sector not in sector_returns:
                            sector_returns[sector] = []
                        sector_returns[sector].append(returns)
                except:
                    pass
        
        # 计算行业平均动量
        sector_momentum = {}
        for sector, returns_list in sector_returns.items():
            if returns_list:
                sector_momentum[sector] = sum(returns_list) / len(returns_list)
        
        # 排序取Top N
        sorted_sectors = sorted(sector_momentum.items(), key=lambda x: x[1], reverse=True)
        top_sectors = [s[0] for s in sorted_sectors[:self.top_n_sectors]]
        
        self.Debug(f"\n🏭 行业动量排名:")
        for sector, momentum in sorted_sectors[:5]:
            mark = "✓" if sector in top_sectors else " "
            self.Debug(f"  [{mark}] {sector:12s}: {momentum:7.2%}")
        
        return top_sectors
    
    def CheckStopLoss(self):
        """检查止损"""
        if self.IsWarmingUp:
            return
            
        for symbol, cost in list(self.cost_basis.items()):
            if self.Portfolio[symbol].Invested:
                current_price = self.Portfolio[symbol].Price
                if cost > 0 and (current_price - cost) / cost < -self.stop_loss_pct:
                    ticker = self.GetTickerName(symbol)
                    self.Debug(f"🛑 止损: {ticker}")
                    self.Liquidate(symbol)
                    if symbol in self.cost_basis:
                        del self.cost_basis[symbol]
    
    def LoadValuationData(self):
        """加载估值数据"""
        try:
            import json
            import os
            
            # 尝试从项目目录加载（Docker容器内可访问）
            valuation_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "valuation_data.json")
            if os.path.exists(valuation_file):
                with open(valuation_file, 'r') as f:
                    data = json.load(f)
                for item in data:
                    ticker = item.get('ticker')
                    if ticker:
                        self.valuation_data[ticker] = {
                            'score': item.get('valuation_score', 0.5),
                            'pe': item.get('pe_trailing'),
                            'pe_forward': item.get('pe_forward'),
                            'peg': item.get('peg_ratio'),
                            'ps': item.get('price_to_sales')
                        }
                self.Debug(f"✅ 估值数据加载完成: {len(self.valuation_data)} 只股票")
            else:
                self.Debug("⚠️ 估值数据文件不存在，使用默认中性评分")
        except Exception as e:
            self.Debug(f"估值数据加载失败: {e}")
    
    def GetValuationScore(self, ticker):
        """获取单只股票的估值评分（0-1）"""
        if not self.enable_valuation_filter:
            return 0.5
        
        # 从预加载数据中获取
        if ticker in self.valuation_data:
            return self.valuation_data[ticker]['score']
        
        # 如果无法获取，返回中性评分
        return 0.5
    
    def CalculateCombinedScore(self, momentum_score, ticker):
        """结合动量和估值的综合评分"""
        if not self.enable_valuation_filter or not self.valuation_data:
            return momentum_score
        
        valuation_score = self.GetValuationScore(ticker)
        
        # 综合评分 = 动量 * 权重 + 估值 * 权重
        combined = (momentum_score * self.momentum_weight + 
                   valuation_score * self.valuation_weight)
        
        return combined
    
    def GetValuationMultiplier(self, ticker):
        """根据估值获取仓位倍数"""
        if not self.enable_valuation_filter or not self.valuation_data:
            return 1.0
        
        valuation_score = self.GetValuationScore(ticker)
        
        # 估值分数映射到仓位倍数
        # 0.0 = 极度高估 -> 0.5x
        # 0.5 = 合理 -> 1.0x
        # 1.0 = 极度低估 -> 1.5x
        multiplier = (self.valuation_multiplier_min + 
                     valuation_score * (self.valuation_multiplier_max - self.valuation_multiplier_min))
        
        return multiplier
    
    def GetMarketRelativeStrength(self):
        """计算美股 vs 港股的相对强度，动态调整资金分配"""
        # 纯美股模式：直接返回100%美股
        if not self.enable_hk or len(self.hk_tickers) == 0:
            return 1.0, 0.0
        
        try:
            # 计算SPY（美股）和0700（腾讯，港股代理）的1月动量
            spy_history = self.History(self.symbols.get("SPY"), self.lookback_1m + 5, Resolution.Daily)
            hk_history = self.History(self.symbols.get("0700"), self.lookback_1m + 5, Resolution.Daily) if "0700" in self.symbols else None
            
            spy_momentum = 0
            hk_momentum = 0
            
            if not spy_history.empty and len(spy_history) >= self.lookback_1m:
                spy_momentum = (spy_history['close'].iloc[-1] - spy_history['close'].iloc[-self.lookback_1m]) / spy_history['close'].iloc[-self.lookback_1m]
            
            if hk_history is not None and not hk_history.empty and len(hk_history) >= self.lookback_1m:
                hk_momentum = (hk_history['close'].iloc[-1] - hk_history['close'].iloc[-self.lookback_1m]) / hk_history['close'].iloc[-self.lookback_1m]
            
            # 相对强度调整
            total_momentum = abs(spy_momentum) + abs(hk_momentum)
            if total_momentum > 0 and self.enable_relative_strength:
                # 根据相对动量分配资金
                us_ratio = abs(spy_momentum) / total_momentum
                # 限制在 50%-90% 之间
                us_ratio = max(0.5, min(0.9, us_ratio))
                hk_ratio = 1.0 - us_ratio
            else:
                us_ratio = self.us_allocation_base
                hk_ratio = self.hk_allocation_base
            
            self.Debug(f"\n🌍 市场相对强度:")
            self.Debug(f"  SPY动量: {spy_momentum:.2%}")
            self.Debug(f"  HK动量: {hk_momentum:.2%}")
            self.Debug(f"  资金分配: 美股 {us_ratio:.0%} / 港股 {hk_ratio:.0%}")
            
            return us_ratio, hk_ratio
            
        except Exception as e:
            self.Debug(f"相对强度计算错误: {e}")
            return self.us_allocation_base, self.hk_allocation_base
    
    def CheckHKMarketTiming(self):
        """检查港股市场趋势，决定是否配置港股"""
        if not self.hk_market_timing:
            return True
        
        try:
            # 使用0700(腾讯)作为港股代理，计算3月动量
            if "0700" not in self.symbols:
                return True
                
            hk_proxy = self.symbols["0700"]
            history = self.History(hk_proxy, self.lookback_3m + 5, Resolution.Daily)
            
            if history.empty or len(history) < self.lookback_3m:
                return True
            
            momentum = (history['close'].iloc[-1] - history['close'].iloc[-self.lookback_3m]) / history['close'].iloc[-self.lookback_3m]
            
            should_trade = momentum > self.hk_min_market_momentum
            
            self.Debug(f"  港股市场择时: 3月动量={momentum:.2%}, 交易={'✓' if should_trade else '✗'}")
            
            return should_trade
            
        except Exception as e:
            return True
    
    def RebalanceHK(self):
        """港股调仓 - 纯美股模式下不执行"""
        if not self.enable_hk or self.IsWarmingUp:
            return
        
        # 港股市场择时检查
        if not self.CheckHKMarketTiming():
            self.Debug(f"\n{'='*60}")
            self.Debug(f"🇭🇰 港股调仓 - {self.Time.strftime('%Y-%m-%d')}")
            self.Debug(f"  ⚠️ 港股市场趋势向下，清仓所有港股")
            self.Debug(f"{'='*60}")
            # 清仓所有港股
            for symbol in list(self.cost_basis.keys()):
                if self.GetTickerName(symbol) in self.hk_tickers:
                    self.Liquidate(symbol)
                    del self.cost_basis[symbol]
            return
        
        # 获取市场相对强度
        us_ratio, hk_ratio = self.GetMarketRelativeStrength()
        
        self.Debug(f"\n{'='*60}")
        self.Debug(f"🇭🇰 港股调仓 - {self.Time.strftime('%Y-%m-%d')}")
        self.Debug(f"  港股资金比例: {hk_ratio:.0%}")
        self.Debug(f"  港股单票上限: {self.hk_max_position:.0%}")
        self.Debug(f"  全局仓位缩放: {self.global_position_scale:.0%}")
        self.Debug(f"{'='*60}")
        
        hk_symbols = {k: v for k, v in self.symbols.items() if k in self.hk_tickers}
        
        # 使用港股比例进行仓位缩放
        self.hk_position_scale = hk_ratio
        self.RebalanceMarket(hk_symbols, "HK", is_hk=True)
    
    def RebalanceMarket(self, market_symbols, market_name, is_hk=False, adjustment_type='medium'):
        """通用调仓逻辑（含VIX过滤 + 港股特殊处理）"""
        
        # 根据调整类型确定阈值
        if adjustment_type == 'small':
            threshold = 0.05
        elif adjustment_type == 'medium':
            threshold = 0.10
        else:  # large
            threshold = 0.15
        
        momentum_scores = {}
        for name, symbol in market_symbols.items():
            result = self.CalculateMomentumScore(symbol, name)
            if result is not None:
                momentum_scores[name] = result
        
        if not momentum_scores:
            return
        
        positive = {k: v for k, v in momentum_scores.items() if v['score'] > self.min_momentum_score}
        
        if not positive:
            self.Debug(f"⚠️ {market_name}无正动量，转入避险")
            self.Liquidate([s for s in market_symbols.values()])
            return
        
        sorted_stocks = sorted(positive.items(), key=lambda x: x[1]['score'], reverse=True)
        top_stocks = sorted_stocks[:self.top_n_stocks]
        
        self.Debug(f"\n🏆 {market_name} Top {len(top_stocks)}:")
        for name, data in top_stocks:
            returns = data['returns']
            self.Debug(f"  {name:6s}: Score={data['score']:7.4f}")
        
        # 计算目标仓位
        total_score = sum(data['score'] for _, data in top_stocks)
        target_holdings = {}
        
        # 确定市场特定的参数
        if is_hk:
            max_pos = self.hk_max_position  # 港股5%
            market_scale = getattr(self, 'hk_position_scale', self.hk_allocation_base)
        else:
            max_pos = self.max_position_per_stock  # 美股15%
            market_scale = getattr(self, 'us_position_scale', self.us_allocation_base)
        
        for name, data in top_stocks:
            weight = (data['score'] / total_score) if total_score > 0 else 0
            weight = min(weight, max_pos)  # 使用市场特定的上限
            
            # 应用估值调整
            if self.enable_valuation_filter and self.valuation_data:
                valuation_multiplier = self.GetValuationMultiplier(name)
                weight *= valuation_multiplier
                if valuation_multiplier != 1.0:
                    self.Debug(f"  📊 {name} 估值调整: {valuation_multiplier:.2f}x")
            
            # 应用VIX全局缩放 * 市场比例缩放
            weight *= self.global_position_scale * market_scale
            target_holdings[data['symbol']] = weight
        
        # 重新归一化（因为估值调整可能改变了总权重）
        total_weight = sum(target_holdings.values())
        if total_weight > 0:
            target_holdings = {k: v / total_weight for k, v in target_holdings.items()}
        
        self.Debug(f"\n📊 {market_name} {adjustment_type}调整目标仓位:")
        for symbol, weight in target_holdings.items():
            self.Debug(f"  {self.GetTickerName(symbol)}: {weight:.2%}")
        
        # 清仓：大调整时清仓所有不在top的，小调整时只清仓大幅偏离的
        if adjustment_type == 'large':
            # 大调整：清仓所有不在target的股票
            for symbol in list(self.cost_basis.keys()):
                if symbol not in target_holdings and self.GetTickerName(symbol) in market_symbols:
                    self.Liquidate(symbol)
                    del self.cost_basis[symbol]
        else:
            # 小/中调整：只清仓不在target且当前有持仓的
            for symbol in list(self.cost_basis.keys()):
                if symbol not in target_holdings and self.GetTickerName(symbol) in market_symbols and self.Portfolio[symbol].Invested:
                    self.Liquidate(symbol)
                    del self.cost_basis[symbol]
        
        # 调整仓位：根据调整类型决定阈值
        self.Debug(f"\n🔄 执行{adjustment_type}调整（阈值{threshold:.0%}）:")
        for symbol, target in target_holdings.items():
            current_weight = self.Portfolio[symbol].HoldingsValue / self.Portfolio.TotalPortfolioValue
            deviation = abs(current_weight - target)
            
            # 如果当前无持仓（首次建仓）或偏差超过阈值，执行调仓
            if current_weight == 0 or deviation > threshold:
                self.SetHoldings(symbol, target)
                if self.Portfolio[symbol].Invested and symbol not in self.cost_basis:
                    self.cost_basis[symbol] = self.Portfolio[symbol].average_price
                action = "建仓" if current_weight == 0 else "调整"
                self.Debug(f"  ✓ {self.GetTickerName(symbol)} {action}: {current_weight:.2%} → {target:.2%}")
            else:
                self.Debug(f"  ⏸ {self.GetTickerName(symbol)}: {current_weight:.2%} ≈ {target:.2%} (偏差{deviation:.2%} < {threshold:.0%})")
        
        self.Plot("Portfolio", "Value", self.Portfolio.TotalPortfolioValue)
    
    def GetTickerName(self, symbol):
        for name, sym in self.symbols.items():
            if sym == symbol:
                return name
        for name, sym in self.safe_symbols.items():
            if sym == symbol:
                return name
        return str(symbol)
    
    def OnData(self, data):
        pass
    
    def OnEndOfAlgorithm(self):
        self.Debug(f"\n{'='*60}")
        self.Debug("策略总结")
        self.Debug(f"{'='*60}")
        self.Debug(f"回测区间: {self.StartDate.strftime('%Y-%m-%d')} ~ {self.EndDate.strftime('%Y-%m-%d')}")
        self.Debug(f"初始资金: $100,000")
        self.Debug(f"最终资金: ${self.Portfolio.TotalPortfolioValue:,.2f}")
        total_return = (self.Portfolio.TotalPortfolioValue - 100000) / 100000
        self.Debug(f"总收益率: {total_return:.2%}")
        
        self.Debug(f"\n最终持仓:")
        for symbol in self.Portfolio.Keys:
            if self.Portfolio[symbol].Invested:
                ticker = self.GetTickerName(symbol)
                weight = self.Portfolio[symbol].HoldingsValue / self.Portfolio.TotalPortfolioValue
                self.Debug(f"  {ticker}: {weight:.2%}")
        
        self.Debug(f"{'='*60}\n")
