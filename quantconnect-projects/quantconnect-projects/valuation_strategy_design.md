# 估值动态调整策略设计文档

## 1. 估值数据获取

### 1.1 数据来源
- **yfinance**: 获取实时PE、Forward PE、PB、PS
- **历史数据**: 计算历史估值分位数

### 1.2 关键指标
```python
valuation_metrics = {
    'pe_trailing': ' trailing PE',
    'pe_forward': 'Forward PE (未来12个月预期)',
    'price_to_book': 'PB Ratio',
    'price_to_sales': 'PS Ratio',
    'peg_ratio': 'PEG Ratio',
    'eps_growth': 'EPS增长率',
    'revenue_growth': '营收增长率'
}
```

### 1.3 历史分位数计算
- 1年分位数：当前估值在过去1年中的位置
- 2年分位数：当前估值在过去2年中的位置
- 3年分位数：当前估值在过去3年中的位置

## 2. 估值评分系统

### 2.1 综合估值分数 (0-1)
```python
def calculate_valuation_score(metrics):
    """
    计算综合估值分数
    1.0 = 极度低估 (增加仓位)
    0.5 = 合理估值 (正常仓位)
    0.0 = 极度高估 (减少仓位)
    """
    scores = []
    weights = []
    
    # Forward PE 折扣 (权重30%)
    if pe_forward and pe_trailing:
        discount = 1 - (pe_forward / pe_trailing)
        score = clip(discount + 0.5, 0, 1)
        scores.append(score)
        weights.append(0.30)
    
    # 历史PE分位数 (权重40%)
    if pe_percentile:
        score = 1 - pe_percentile  # 低分位=低估=高分
        scores.append(score)
        weights.append(0.40)
    
    # PEG Ratio (权重20%)
    if peg_ratio:
        score = clip(1.5 - peg_ratio/2, 0, 1)
        scores.append(score)
        weights.append(0.20)
    
    # PS Ratio (权重10%)
    if ps_ratio:
        score = clip(1.5 - ps_ratio/10, 0, 1)
        scores.append(score)
        weights.append(0.10)
    
    return weighted_average(scores, weights)
```

### 2.2 估值等级划分
```python
def get_valuation_level(score):
    if score >= 0.8: return '极度低估'
    elif score >= 0.6: return '低估'
    elif score >= 0.4: return '合理'
    elif score >= 0.2: return '高估'
    else: return '极度高估'
```

## 3. 动态仓位调整规则

### 3.1 个股层面调整
```python
def adjust_position_by_valuation(base_weight, valuation_score):
    """
    根据估值分数调整个股仓位
    """
    # 估值分数映射到仓位倍数
    # 极度低估(1.0) -> 1.5x 仓位
    # 合理(0.5) -> 1.0x 仓位
    # 极度高估(0.0) -> 0.5x 仓位
    
    multiplier = 0.5 + valuation_score  # 范围: 0.5 - 1.5
    adjusted_weight = base_weight * multiplier
    
    # 限制最大仓位
    return min(adjusted_weight, max_position_per_stock)
```

### 3.2 行业层面调整
```python
def adjust_sector_by_valuation(sector_momentum, sector_valuation):
    """
    结合行业动量和估值调整行业配置
    """
    # 强动量 + 低估 = 重仓
    # 强动量 + 高估 = 中等仓位
    # 弱动量 + 低估 = 小仓位
    # 弱动量 + 高估 = 清仓
    
    combined_score = sector_momentum * 0.6 + sector_valuation * 0.4
    return combined_score
```

### 3.3 市场层面调整（美股vs港股）
```python
def adjust_market_by_valuation(us_valuation, hk_valuation):
    """
    根据市场估值水平调整美股/港股配置比例
    """
    # 计算相对估值吸引力
    total = us_valuation + hk_valuation
    if total > 0:
        us_ratio = us_valuation / total
        hk_ratio = hk_valuation / total
    else:
        us_ratio = 0.7
        hk_ratio = 0.3
    
    # 限制在合理范围内
    us_ratio = clip(us_ratio, 0.5, 0.9)
    hk_ratio = 1.0 - us_ratio
    
    return us_ratio, hk_ratio
```

## 4. 策略整合方案

### 4.1 在现有策略中插入估值模块

```python
class AdaptiveMomentumStrategy(QCAlgorithm):
    def Initialize(self):
        # ... 现有初始化代码 ...
        
        # === 估值参数 ===
        self.enable_valuation_filter = True
        self.valuation_weight = 0.3  # 估值在总分中的权重
        self.momentum_weight = 0.7    # 动量在总分中的权重
        
        # 估值调整参数
        self.valuation_multiplier_min = 0.5  # 高估时最小仓位倍数
        self.valuation_multiplier_max = 1.5  # 低估时最大仓位倍数
        
        # 加载估值数据
        self.valuation_data = self.LoadValuationData()
    
    def LoadValuationData(self):
        """加载预计算的估值数据"""
        # 从本地文件或API加载
        pass
    
    def CalculateMomentumScore(self, symbol, name):
        """现有动量计算"""
        # ... 现有代码 ...
        return momentum_score
    
    def CalculateValuationScore(self, name):
        """计算估值分数"""
        if name not in self.valuation_data:
            return 0.5  # 默认中性
        
        data = self.valuation_data[name]
        return calculate_valuation_score(data)
    
    def CalculateCombinedScore(self, symbol, name):
        """
        结合动量和估值的综合评分
        """
        momentum_score = self.CalculateMomentumScore(symbol, name)
        valuation_score = self.CalculateValuationScore(name)
        
        # 综合评分 = 动量 * 权重 + 估值 * 权重
        combined = (momentum_score * self.momentum_weight + 
                   valuation_score * self.valuation_weight)
        
        return {
            'momentum': momentum_score,
            'valuation': valuation_score,
            'combined': combined
        }
    
    def RebalanceMarket(self, market_symbols, market_name, is_hk=False):
        """改进的调仓逻辑，加入估值调整"""
        
        # 1. 计算综合评分（动量+估值）
        combined_scores = {}
        for name, symbol in market_symbols.items():
            result = self.CalculateCombinedScore(symbol, name)
            if result['momentum'] is not None:
                combined_scores[name] = result
        
        # 2. 过滤正动量股票
        positive = {k: v for k, v in combined_scores.items() 
                   if v['momentum'] > self.min_momentum_score}
        
        if not positive:
            self.Liquidate([s for s in market_symbols.values()])
            return
        
        # 3. 按综合评分排序
        sorted_stocks = sorted(positive.items(), 
                              key=lambda x: x[1]['combined'], 
                              reverse=True)
        top_stocks = sorted_stocks[:self.top_n_stocks]
        
        # 4. 计算目标仓位（加入估值调整）
        total_score = sum(data['combined'] for _, data in top_stocks)
        target_holdings = {}
        
        for name, data in top_stocks:
            # 基础权重
            base_weight = data['combined'] / total_score if total_score > 0 else 0
            base_weight = min(base_weight, self.max_position_per_stock)
            
            # 估值调整
            valuation_multiplier = (self.valuation_multiplier_min + 
                                   data['valuation'] * 
                                   (self.valuation_multiplier_max - self.valuation_multiplier_min))
            
            # 应用调整
            adjusted_weight = base_weight * valuation_multiplier
            
            # 应用VIX和市场缩放
            adjusted_weight *= self.global_position_scale
            if is_hk:
                adjusted_weight *= getattr(self, 'hk_position_scale', self.hk_allocation_base)
            else:
                adjusted_weight *= getattr(self, 'us_position_scale', self.us_allocation_base)
            
            target_holdings[market_symbols[name]] = adjusted_weight
        
        # 5. 归一化
        total_weight = sum(target_holdings.values())
        if total_weight > 0:
            target_holdings = {k: v / total_weight for k, v in target_holdings.items()}
        
        # 6. 执行调仓
        # ... 现有执行代码 ...
```

## 5. 回测验证计划

### 5.1 测试版本
1. **纯动量**（基准）
2. **动量+估值（30%权重）**
3. **动量+估值（50%权重）**
4. **动量+估值（70%权重）**

### 5.2 对比指标
- 总收益
- 夏普比率
- 最大回撤
- 估值贡献度（动量选中的股票中，低估vs高估的表现差异）

## 6. 数据更新频率

- **估值数据**：每周更新（与调仓频率一致）
- **历史分位数**：每月重新计算
- **紧急调整**：当市场估值发生重大变化时（如PE突然飙升50%）

## 7. 风险控制

### 7.1 估值陷阱避免
- 低PE不代表低估（可能是价值陷阱）
- 需要结合：
  - 盈利质量（现金流vs净利润）
  - 行业前景
  - 公司治理

### 7.2 极端估值处理
- 当个股估值>历史99%分位：强制减仓50%
- 当个股估值<历史1%分位：允许加仓至20%（突破15%上限）

## 8. 实现步骤

1. 创建估值数据下载脚本
2. 计算历史估值分位数
3. 在策略中加载估值数据
4. 修改评分逻辑（动量+估值）
5. 修改仓位计算逻辑（加入估值倍数）
6. 回测验证
7. 参数优化（估值权重、倍数范围）

## 9. 预期效果

- **降低估值风险**：避免买入高位股票
- **增强收益**：在低估时加仓，提高反弹收益
- **改善夏普比率**：减少极端估值带来的回撤
- **更好的风险调整收益**：长期来看，估值因子应该提供正的风险调整收益
