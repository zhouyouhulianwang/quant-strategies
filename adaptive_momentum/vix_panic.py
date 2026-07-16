"""
VIX Panic Signal Module - 可被主策略调用的VIX恐慌信号模块

提供VIX恐慌信号检测功能，用于主策略的风险管理和择时叠加。
使用VIX指数（而非VXX ETF）直接检测市场恐慌。

使用方式:
    from vix_panic import VixPanicSignal
    
    # 在Initialize中初始化（只添加VIX指数）
    self.vix_panic = VixPanicSignal(self)
    self.vix_panic.initialize_vix()  # 添加VIX指数
    
    # 主策略筛选个股后传入
    selected_symbols = {'AAPL': self.aapl, 'MSFT': self.msft, ...}
    self.vix_panic.set_symbols(selected_symbols)
    
    # 在OnData或定时调度中检查信号
    signal = self.vix_panic.get_signal()
    if signal['signal'] == 'buy_panic':
        # 执行恐慌抄底逻辑（对selected_symbols中的标的操作）
    elif signal['signal'] == 'sell_overbought':
        # 执行止盈/避险逻辑
"""
from AlgorithmImports import *
from collections import defaultdict


class VixPanicSignal:
    """
    VIX恐慌信号检测器 - 使用VIX指数直接检测
    
    检测VIX盘中冲高（VIX>30）时的恐慌/超买信号，提供交易建议。
    可独立于主策略运行统计，也可作为信号源被主策略调用。
    
    标的不固定：由主策略筛选后传入，VIX_PANIC只负责信号检测和
    对传入标的进行统一仓位管理。
    """
    
    # 默认参数配置
    DEFAULT_CONFIG = {
        'vix_thresh': 30.0,            # VIX恐慌阈值（直接检测VIX>30）
        'rsi_period': 14,              # RSI计算周期（使用SPY的RSI作为大盘RSI）
        'rsi_oversold': 30,            # RSI超卖阈值
        'rsi_overbought': 70,          # RSI超买阈值
        'take_profit': 0.015,          # 1.5%止盈
        'stop_loss': -0.015,           # -1.5%止损
        'max_hold_days': 5,            # 最长持有5日
    }
    
    def __init__(self, algorithm, config=None):
        """
        初始化VIX恐慌信号模块
        
        Args:
            algorithm: QCAlgorithm实例 (主策略的self)
            config: 可选，自定义参数字典，覆盖默认参数
        """
        self.algo = algorithm
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        
        # 参数快捷访问
        self.vix_thresh = self.config['vix_thresh']
        self.rsi_oversold = self.config['rsi_oversold']
        self.rsi_overbought = self.config['rsi_overbought']
        self.take_profit = self.config['take_profit']
        self.stop_loss = self.config['stop_loss']
        self.max_hold_days = self.config['max_hold_days']
        
        # 标的管理（由外部传入）
        self.symbols = {}        # 主策略传入的标的字典，如 {'AAPL': symbol, ...}
        self.vix_symbol = None   # VIX指数Symbol
        self.rsi_indicator = None  # 使用SPY或传入的基准标的计算RSI
        
        # 状态追踪
        self.hold_long = False
        self.entry_prices = {}   # 记录入场价 {symbol_name: price}
        self.entry_date = None
        self.last_processed_date = None
        
        # 统计记录
        self.stats = {}          # 动态生成统计字段
        self.trades = []
        
        # 信号缓存
        self.last_signal = None
        self.last_signal_time = None
    
    def initialize_vix(self, rsi_benchmark='SPY'):
        """
        初始化VIX指数和RSI基准（在主策略Initialize中调用）
        
        Args:
            rsi_benchmark: 用于计算RSI的基准标的，默认 'SPY'
        """
        algo = self.algo
        
        # 添加VIX指数
        try:
            self.vix_symbol = algo.AddIndex('VIX', Resolution.DAILY).Symbol
            algo.Log("[VIX_PANIC] VIX index added successfully")
        except:
            self.vix_symbol = algo.AddEquity('VIXY', Resolution.DAILY).Symbol
            algo.Log("[VIX_PANIC] VIX unavailable, using VIXY fallback")
        
        # 添加RSI基准（用于判断大盘超买/超卖）
        benchmark_sym = algo.AddEquity(rsi_benchmark, Resolution.DAILY).Symbol
        self.rsi_indicator = algo.RSI(benchmark_sym, self.config['rsi_period'], MovingAverageType.SIMPLE)
        
        algo.Log(f"[VIX_PANIC] VIX threshold: {self.vix_thresh}, RSI benchmark: {rsi_benchmark}")
        return self
    
    def set_symbols(self, symbols_dict):
        """
        设置要监控/交易的标的（由主策略筛选后传入）
        
        Args:
            symbols_dict: 标的字典，如 {'AAPL': symbol_obj, 'MSFT': symbol_obj}
                         key为标的名称，value为Symbol对象
        """
        self.symbols = dict(symbols_dict)
        
        # 动态初始化统计字段
        self.stats = defaultdict(lambda: {
            "count": 0,
            **{f"{name}_D{d}": [] for name in self.symbols.keys() for d in range(6)}
        })
        
        self.algo.Log(f"[VIX_PANIC] Monitoring {len(self.symbols)} symbols: {list(self.symbols.keys())}")
        return self
    
    def use_existing_vix(self, vix_symbol, rsi_indicator):
        """
        使用主策略已有的VIX和RSI指标（避免重复添加）
        
        Args:
            vix_symbol: VIX Symbol对象（已通过 algo.AddIndex('VIX') 添加）
            rsi_indicator: RSI指标对象（如主策略已有的SPY RSI）
        """
        self.vix_symbol = vix_symbol
        self.rsi_indicator = rsi_indicator
        self.algo.Log("[VIX_PANIC] Using existing VIX and RSI from main strategy")
        return self
    
    # ==================== 核心信号接口 ====================
    
    def get_signal(self, data=None):
        """
        获取当前VIX恐慌信号
        
        Args:
            data: 可选，传入Slice数据
            
        Returns:
            dict: 信号字典，包含:
                - 'signal': 'buy_panic'/'sell_overbought'/'neutral'/'none'
                - 'rsi': 当前RSI值
                - 'vix_high': VIX最高价
                - 'vix_close': VIX收盘价
                - 'rsi_group': 'Oversold'/'Neutral'/'Overbought'
                - 'vix_type': 'A' (收盘>=阈值) / 'B' (仅盘中冲高)
                - 'target_weight': 建议仓位 (0.0-1.0)
                - 'reason': 信号原因描述
        """
        algo = self.algo
        
        # 检查是否已初始化
        if not self.vix_symbol:
            return {'signal': 'none', 'reason': 'VIX_PANIC not initialized (call initialize_vix first)'}
        
        # 防重复处理（同一天只产生一次信号）
        if self.last_processed_date == algo.Time.date():
            return self.last_signal or {'signal': 'none', 'reason': 'Already processed today'}
        self.last_processed_date = algo.Time.date()
        
        # 获取VIX数据
        vix_sec = algo.Securities[self.vix_symbol]
        vix_high = vix_sec.High
        vix_close = vix_sec.Close
        
        # VIX未冲高（VIX <= 30）-> 无信号
        if vix_high <= self.vix_thresh:
            self.last_signal = {'signal': 'neutral', 'vix_high': vix_high, 'reason': f'VIX not spiked (VIX {vix_high:.1f} <= {self.vix_thresh})'}
            return self.last_signal
        
        # 获取RSI
        rsi_val = self.rsi_indicator.Current.Value if self.rsi_indicator and self.rsi_indicator.IsReady else 50
        
        # 分类
        rsi_group = "Oversold" if rsi_val < self.rsi_oversold else ("Overbought" if rsi_val > self.rsi_overbought else "Neutral")
        vix_type = "A" if vix_close >= self.vix_thresh else "B"
        
        # 构建信号
        signal = {
            'rsi': rsi_val,
            'vix_high': vix_high,
            'vix_close': vix_close,
            'rsi_group': rsi_group,
            'vix_type': vix_type,
            'timestamp': algo.Time,
        }
        
        # 超卖 + VIX冲高（VIX>30）= 恐慌抄底信号
        if rsi_group == "Oversold":
            # A类: VIX收盘>=30，满仓信号
            # B类: VIX仅盘中冲高，半仓信号
            weight = 1.0 if vix_type == "A" else 0.5
            signal.update({
                'signal': 'buy_panic',
                'target_weight': weight,
                'reason': f'VIX{vix_type} spike ({vix_high:.1f}/{vix_close:.1f} > {self.vix_thresh}) + RSI oversold ({rsi_val:.1f}) -> panic buy',
            })
        
        # 超买 + VIX冲高 = 止盈/避险信号
        elif rsi_group == "Overbought":
            signal.update({
                'signal': 'sell_overbought',
                'target_weight': 0.0,
                'reason': f'VIX{vix_type} spike ({vix_high:.1f}/{vix_close:.1f} > {self.vix_thresh}) + RSI overbought ({rsi_val:.1f}) -> take profit/hedge',
            })
        
        # 中性 = 观望
        else:
            signal.update({
                'signal': 'neutral',
                'target_weight': 0.0,
                'reason': f'VIX{vix_type} spike ({vix_high:.1f}/{vix_close:.1f} > {self.vix_thresh}) but RSI neutral ({rsi_val:.1f}) -> no action',
            })
        
        self.last_signal = signal
        self.last_signal_time = algo.Time
        
        # 记录统计
        self._record_stats(signal)
        
        return signal
    
    def check_position_exit(self):
        """
        检查持仓是否需要止盈止损
        
        Returns:
            list: 需要平仓的标的列表，每个元素为 {'symbol': sym, 'name': str, 'reason': str, 'pnl': float}
        """
        algo = self.algo
        exits = []
        
        if not self.hold_long or not self.entry_date or not self.symbols:
            return exits
        
        hold_days = (algo.Time.date() - self.entry_date).days
        
        for sym_name, sym in self.symbols.items():
            if not algo.Portfolio[sym].Invested:
                continue
            
            entry_price = self.entry_prices.get(sym_name, 0)
            if entry_price <= 0:
                continue
            
            current_price = algo.Securities[sym].Close
            pnl = (current_price - entry_price) / entry_price
            
            # 止盈
            if pnl >= self.take_profit:
                exits.append({'symbol': sym, 'name': sym_name, 'reason': 'take_profit', 'pnl': pnl})
                continue
            
            # 止损
            if pnl <= self.stop_loss:
                exits.append({'symbol': sym, 'name': sym_name, 'reason': 'stop_loss', 'pnl': pnl})
                continue
            
            # 最长持有期
            if hold_days >= self.max_hold_days:
                exits.append({'symbol': sym, 'name': sym_name, 'reason': 'time_exit', 'pnl': pnl})
        
        # 检查是否全部平仓
        if exits and not any(algo.Portfolio[s].Invested for s in self.symbols.values() if s not in [e['symbol'] for e in exits]):
            self.hold_long = False
            self.entry_date = None
            self.entry_prices = {}
        
        return exits
    
    def record_entry(self, symbol_name, price):
        """记录入场价格和日期"""
        self.entry_prices[symbol_name] = price
        self.entry_date = self.algo.Time.date()
        self.hold_long = True
    
    def record_exit(self, symbol_name, reason='manual'):
        """记录平仓"""
        if symbol_name in self.entry_prices:
            del self.entry_prices[symbol_name]
        if not self.entry_prices:
            self.hold_long = False
            self.entry_date = None
    
    # ==================== 统计功能 ====================
    
    def _record_stats(self, signal):
        """记录信号统计"""
        key = (signal['vix_type'], signal['rsi_group'])
        rec = self.stats[key]
        rec["count"] += 1
        
        # 获取未来收益用于统计（仅在回测时有效）
        forward_ret = self._get_forward_returns()
        for name in self.symbols.keys():
            for d in range(6):
                rec[f"{name}_D{d}"].append(forward_ret.get(name, {}).get(f"D{d}", 0))
    
    def _get_forward_returns(self):
        """获取未来6日收益（用于统计）"""
        ret = {}
        algo = self.algo
        
        for name, sym in self.symbols.items():
            ret[name] = {}
            try:
                hist = algo.History(sym, 10, Resolution.DAILY)
                if hist.empty or len(hist) < 2:
                    for d in range(6):
                        ret[name][f"D{d}"] = 0.0
                    continue
                hist = hist.sort_index()
                closes = hist["close"].values
                for d in range(6):
                    if d >= len(closes):
                        ret[name][f"D{d}"] = 0.0
                    elif d == 0:
                        ret[name][f"D{d}"] = 0.0
                    else:
                        ret[name][f"D{d}"] = (closes[d] / closes[0] - 1) * 100
            except:
                for d in range(6):
                    ret[name][f"D{d}"] = 0.0
        
        return ret
    
    def get_stats_report(self):
        """
        获取统计报告
        
        Returns:
            str: 格式化的统计报告
        """
        lines = ["\n==================== VIX恐慌信號統計報表 ===================="]
        group_order = [
            ("A", "Oversold"), ("A", "Neutral"), ("A", "Overbought"),
            ("B", "Oversold"), ("B", "Neutral"), ("B", "Overbought")
        ]
        
        for key in group_order:
            vt, rg = key
            data = self.stats[key]
            cnt = data["count"]
            if cnt == 0:
                lines.append(f"\n【{vt}類-{rg}】樣本數: 0")
                continue
            
            lines.append(f"\n===== 分組：VIX{vt}類 | RSI:{rg} | 樣本數={cnt} =====")
            
            for sym_name in self.symbols.keys():
                d0_avg, d0_win = self._calc_stats(data.get(f"{sym_name}_D0", []))
                d1_avg, d1_win = self._calc_stats(data.get(f"{sym_name}_D1", []))
                d5_avg, d5_win = self._calc_stats(data.get(f"{sym_name}_D5", []))
                lines.append(f"{sym_name} D0:{d0_avg}%/{d0_win}% D1:{d1_avg}%/{d1_win}% D5:{d5_avg}%/{d5_win}%")
        
        lines.append(f"\n總信號次數: {len(self.trades)}")
        return "\n".join(lines)
    
    def _calc_stats(self, arr):
        """计算统计指标"""
        if not arr:
            return (0, 0)
        avg = sum(arr) / len(arr)
        win = sum(1 for x in arr if x > 0) / len(arr) * 100
        return round(avg, 3), round(win, 1)
    
    def log_stats(self):
        """输出统计报告到日志"""
        self.algo.Log(self.get_stats_report())
    
    # ==================== 便捷属性 ====================
    
    @property
    def has_position(self):
        """是否有持仓"""
        return self.hold_long
    
    @property
    def hold_days(self):
        """当前持仓天数"""
        if not self.entry_date:
            return 0
        return (self.algo.Time.date() - self.entry_date).days
    
    def is_in_position(self, symbol_name):
        """检查某个标的是否在持仓中"""
        return symbol_name in self.entry_prices


# ==================== 独立使用示例 ====================

class VixPanicStrategy(QCAlgorithm):
    """
    VIX恐慌策略独立运行版本（演示用法）
    使用SPY作为基准和交易标的，在QuantConnect上运行
    """
    
    def Initialize(self):
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2026, 7, 10)
        self.SetCash(100000)
        self.SetBrokerageModel(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
        
        # 初始化VIX信号模块（只添加VIX）
        self.vix_panic = VixPanicSignal(self)
        self.vix_panic.initialize_vix(rsi_benchmark='SPY')
        
        # 设置要交易的标的（演示：只交易SPY）
        spy = self.AddEquity('SPY', Resolution.DAILY).Symbol
        self.vix_panic.set_symbols({'SPY': spy})
        
        self.SetWarmUp(self.vix_panic.config['rsi_period'] + 5)
    
    def OnData(self, data):
        # 检查止盈止损
        exits = self.vix_panic.check_position_exit()
        for exit_info in exits:
            self.Liquidate(exit_info['symbol'])
            self.Log(f"[EXIT] {exit_info['name']}: {exit_info['reason']}, PnL={exit_info['pnl']*100:.2f}%")
        
        # 获取信号
        signal = self.vix_panic.get_signal(data)
        
        if signal['signal'] == 'buy_panic':
            weight = signal['target_weight'] / len(self.vix_panic.symbols)
            for sym_name, sym in self.vix_panic.symbols.items():
                self.SetHoldings(sym, weight)
                self.vix_panic.record_entry(sym_name, self.Securities[sym].Close)
            self.Log(f"[BUY PANIC] {signal['reason']}")
            
        elif signal['signal'] == 'sell_overbought':
            if self.vix_panic.has_position:
                for sym in self.vix_panic.symbols.values():
                    self.Liquidate(sym)
                self.vix_panic.hold_long = False
                self.vix_panic.entry_prices = {}
                self.vix_panic.entry_date = None
            self.Log(f"[SELL] {signal['reason']}")
    
    def OnEndOfAlgorithm(self):
        self.vix_panic.log_stats()
