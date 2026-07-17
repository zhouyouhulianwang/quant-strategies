"""
交易成本模型 - 佣金、滑点、冲击成本计算
"""

import logging
import numpy as np
import pandas as pd

# P2修复：统一全链路日志格式

logger = logging.getLogger(__name__)


class TradingCostModel:
    """
    交易成本模型
    
    Alpaca Paper Trading 费用:
    - 美股: $0.005/股 (最低 $1, 最高交易额 1%)
    - 无平台费
    - 无数据费
    """
    
    def __init__(self,
                 commission_per_share=0.005,
                 min_commission=1.0,
                 max_commission_pct=0.01,
                 slippage_bps=10,  # 10 bps = 0.1%
                 market_impact_bps=5):  # 大额交易冲击成本
        """
        初始化成本模型
        
        参数:
            commission_per_share: 每股佣金
            min_commission: 最低佣金
            max_commission_pct: 佣金上限（占交易额比例）
            slippage_bps: 滑点（基点）
            market_impact_bps: 市场冲击成本（基点）
        """
        self.commission_per_share = commission_per_share
        self.min_commission = min_commission
        self.max_commission_pct = max_commission_pct
        self.slippage_pct = slippage_bps / 10000  # 转换为百分比
        self.market_impact_pct = market_impact_bps / 10000
        
        logger.info(f"✅ 成本模型已初始化")
        logger.info(f"   佣金: ${commission_per_share}/股 (最低 ${min_commission})")
        logger.info(f"   滑点: {slippage_bps} bps")
    
    def calculate_cost(self, symbol, qty, price, side='buy', 
                       order_type='market') -> dict:
        """
        计算单笔交易成本
        
        参数:
            symbol: str
            qty: int, 数量
            price: float, 价格
            side: str, 'buy' 或 'sell'
            order_type: str, 'market' 或 'limit'
        
        返回:
            dict: 成本明细
        """
        # P0修复: 价格或数量无效时直接返回0成本, 不硬编码价格
        if price is None or price <= 0 or qty <= 0:
            return {
                'symbol': symbol,
                'qty': qty,
                'price': price if price is not None else 0.0,
                'trade_value': 0.0,
                'commission': 0.0,
                'slippage': 0.0,
                'market_impact': 0.0,
                'total_cost': 0.0,
                'cost_pct': 0.0,
                'side': side,
                'order_type': order_type,
            }
        
        # 交易额
        trade_value = qty * price
        
        # 1. 佣金
        commission = qty * self.commission_per_share
        commission = max(commission, self.min_commission)
        commission = min(commission, trade_value * self.max_commission_pct)
        
        # 2. 滑点 (市价单才有)
        slippage = 0
        if order_type == 'market':
            # 买入时价格上升，卖出时价格下降
            slippage = trade_value * self.slippage_pct
        
        # 3. 市场冲击 (大额交易)
        impact = 0
        if trade_value > 100000:  # 超过10万
            impact = trade_value * self.market_impact_pct
        
        # 总成本
        total_cost = commission + slippage + impact
        cost_pct = total_cost / trade_value if trade_value > 0 else 0
        
        result = {
            'symbol': symbol,
            'qty': qty,
            'price': price,
            'trade_value': trade_value,
            'commission': commission,
            'slippage': slippage,
            'market_impact': impact,
            'total_cost': total_cost,
            'cost_pct': cost_pct,
            'side': side,
            'order_type': order_type,
        }
        
        return result
    
    def estimate_portfolio_cost(self, target_positions: dict, 
                                current_positions: dict = None,
                                total_value: float = None) -> dict:
        """
        估算组合调仓总成本
        
        参数:
            target_positions: dict, {symbol: target_value} 或 {symbol: weight}
            current_positions: dict, {symbol: {'qty': int, 'price': float}}
            total_value: float, 可选，用于将权重转换为金额
        
        返回:
            dict: 总成本估算
        """
        if current_positions is None:
            current_positions = {}
        
        # P1修复: 若 target_positions 是权重（和约 1）则转换为金额
        target_positions = self._rescale_target_positions(target_positions, current_positions, total_value)
        
        total_commission = 0
        total_slippage = 0
        total_trades = 0
        trade_details = []
        
        # 计算需要交易的标的
        all_symbols = set(list(target_positions.keys()) + list(current_positions.keys()))
        
        def _get_current_price(current, symbol):
            """价格缺失保护：依次尝试 price/current_price/avg_entry_price，缺失则默认 0"""
            if isinstance(current, dict):
                for key in ('price', 'current_price', 'avg_entry_price', 'last_price'):
                    price = current.get(key)
                    try:
                        if price is not None and float(price) > 0:
                            return float(price)
                    except (TypeError, ValueError):
                        continue
            logger.warning(f"⚠️ {symbol} 持仓价格缺失，默认价格为 0")
            return 0.0
        
        for symbol in all_symbols:
            target_value = target_positions.get(symbol, 0)
            current = current_positions.get(symbol, {'qty': 0})
            if isinstance(current, dict):
                current_qty = current.get('qty', 0)
            else:
                try:
                    current_qty = int(current)
                except Exception:
                    current_qty = 0
            current_price = _get_current_price(current, symbol)
            
            # P0修复: 价格缺失时跳过，默认 0 成本
            if current_price <= 0:
                logger.warning(f"⚠️ {symbol} 价格无效，跳过成本估算")
                continue
            
            # 目标数量
            if target_value > 0 and current_price > 0:
                target_qty = int(target_value / current_price)
            else:
                target_qty = 0
            
            diff = target_qty - current_qty
            
            if diff != 0:
                side = 'buy' if diff > 0 else 'sell'
                qty = abs(diff)
                
                cost = self.calculate_cost(symbol, qty, current_price, side)
                
                total_commission += cost['commission']
                total_slippage += cost['slippage']
                total_trades += 1
                trade_details.append(cost)
        
        total_cost = total_commission + total_slippage
        
        return {
            'total_commission': total_commission,
            'total_slippage': total_slippage,
            'total_cost': total_cost,
            'total_trades': total_trades,
            'trade_details': trade_details,
        }
    
    def calculate_rebalance_cost(self, target_positions: dict,
                                 current_positions: dict = None,
                                 current_prices: dict = None,
                                 total_value: float = None) -> dict:
        """
        基于 target_positions 和 current_positions 的逐笔成本计算
        
        参数:
            target_positions: dict, {symbol: target_value} 或 {symbol: weight}
            current_positions: dict, {symbol: {'qty': int, 'price': float}} 或 {symbol: qty}
            current_prices: dict, 可选，当前市价 {symbol: price}
            total_value: float, 可选，用于将权重转换为金额
        
        返回:
            dict: 总成本、成交额、换手率、单笔明细
        """
        if current_positions is None:
            current_positions = {}
        if current_prices is None:
            current_prices = {}

        # P1修复: 若 target_positions 是权重（和约 1）则转换为金额
        target_positions = self._rescale_target_positions(target_positions, current_positions, total_value)

        total_cost = 0.0
        total_traded_value = 0.0
        trade_details = []
        total_target_value = sum(v for v in target_positions.values() if isinstance(v, (int, float)) and v > 0)

        all_symbols = set(list(target_positions.keys()) + list(current_positions.keys()))

        def _get_price(current, symbol):
            if isinstance(current, dict):
                for key in ('price', 'current_price', 'avg_entry_price', 'last_price'):
                    price = current.get(key)
                    try:
                        if price is not None and float(price) > 0:
                            return float(price)
                    except (TypeError, ValueError):
                        continue
            try:
                price = float(current_prices.get(symbol, 0.0))
                if price > 0:
                    return price
            except (TypeError, ValueError):
                pass
            logger.warning(f"⚠️ {symbol} 价格缺失，默认价格为 0")
            return 0.0

        for symbol in all_symbols:
            target_value = target_positions.get(symbol, 0)
            current = current_positions.get(symbol, {'qty': 0})
            if isinstance(current, dict):
                current_qty = current.get('qty', 0)
            else:
                try:
                    current_qty = int(current)
                except Exception:
                    current_qty = 0
            current_price = _get_price(current, symbol)

            # P0修复: 价格缺失时跳过，默认 0 成本
            if current_price <= 0:
                logger.warning(f"⚠️ {symbol} 价格无效，跳过成本估算")
                continue

            try:
                target_qty = int(target_value / current_price) if current_price > 0 else 0
            except (TypeError, ValueError):
                target_qty = 0

            diff = target_qty - current_qty
            if diff == 0:
                continue

            side = 'buy' if diff > 0 else 'sell'
            qty = abs(diff)
            cost = self.calculate_cost(symbol, qty, current_price, side)
            total_cost += cost['total_cost']
            total_traded_value += cost['trade_value']
            trade_details.append(cost)

        turnover = (total_traded_value / total_target_value) if total_target_value > 0 else 0.0
        cost_pct = (total_cost / total_target_value) if total_target_value > 0 else 0.0

        return {
            'total_cost': total_cost,
            'total_traded_value': total_traded_value,
            'turnover': turnover,
            'cost_pct': cost_pct,
            'trade_details': trade_details,
        }
    
    def _rescale_target_positions(self, target_positions: dict,
                                  current_positions: dict = None,
                                  total_value: float = None) -> dict:
        """
        检测 target_positions 是权重（和约 1）还是金额，并统一为金额
        
        参数:
            target_positions: dict, {symbol: target_value} 或 {symbol: weight}
            current_positions: dict, 当前持仓
            total_value: float, 可选，组合总价值
        
        返回:
            dict: {symbol: target_value}
        """
        if not target_positions:
            return {}
        
        # 仅处理数值型 value
        values = [v for v in target_positions.values() if isinstance(v, (int, float)) and v > 0]
        if not values:
            return target_positions
        
        total = sum(values)
        # 和约 1 且每个 value <= 1 视为权重
        if total > 0 and abs(total - 1.0) <= 1e-3 and max(values) <= 1.0:
            if total_value is None and current_positions:
                # 从当前持仓市值推导 total_value
                total_value = 0.0
                for s, c in current_positions.items():
                    if isinstance(c, dict):
                        qty = c.get('qty', 0)
                        price = c.get('price', 0) or c.get('current_price', 0) or c.get('avg_entry_price', 0)
                    else:
                        try:
                            qty = int(c)
                            price = 0
                        except Exception:
                            qty = 0
                            price = 0
                    if qty > 0 and price > 0:
                        total_value += qty * price
            if total_value and total_value > 0:
                return {s: (v / total) * total_value for s, v in target_positions.items()}
            else:
                logger.warning("⚠️ target_positions 为权重但无法获取 total_value，按 0 处理")
                return {s: 0.0 for s in target_positions}
        return target_positions

    def apply_cost_to_nav(self, nav, turnover=0.0, cost_per_turnover=0.002):
        """
        按实际换手率估算成本对 NAV 的影响
        
        参数:
            nav: float, 当前 NAV
            turnover: float, 换手率 (0-1)
            cost_per_turnover: float, 每单位换手率对应的成本
        
        返回:
            float: 扣除成本后的 NAV
        """
        monthly_cost = turnover * cost_per_turnover
        adjusted_nav = nav * (1 - monthly_cost)
        return adjusted_nav


# 全局成本模型实例
cost_model = TradingCostModel()


def apply_costs_to_backtest(result_df, cost_model_instance=None, cost_per_turnover=0.002, spread_bps=5.0):
    """
    将交易成本应用到回测结果，按实际换手率（turnover）计算

    参数:
        result_df: DataFrame, 回测结果（可包含 holdings/weights 列）
        cost_model_instance: TradingCostModel
        cost_per_turnover: float, 每单位换手率成本（佣金+冲击）
        spread_bps: float, 双边买卖 bid-ask spread 基点（默认 5 bps = 0.05%）

    返回:
        DataFrame: 扣除成本后的结果
    """
    # 统一使用 ExecutionParameters，确保回测与 live 成本假设一致
    from matching_engine import ExecutionParameters
    params = ExecutionParameters(
        cost_per_turnover=cost_per_turnover,
        spread_bps=spread_bps,
    )

    if cost_model_instance is None:
        cost_model_instance = cost_model

    result = result_df.copy()
    if len(result) == 0:
        return result

    # 默认换手率
    default_turnover = 0.5

    # 若存在 weights 列，则按实际权重变化计算换手率（dollar turnover）
    if 'weights' in result.columns:
        turnovers = []
        prev_weights = {}
        for _, row in result.iterrows():
            curr_weights = row.get('weights', {}) or {}
            all_symbols = set(prev_weights.keys()) | set(curr_weights.keys())
            if all_symbols:
                # 总买入 turnover = 所有正权重变化之和
                turnover = sum(
                    max(0.0, curr_weights.get(s, 0.0) - prev_weights.get(s, 0.0))
                    for s in all_symbols
                )
            else:
                turnover = 0.0
            turnovers.append(turnover)
            prev_weights = curr_weights
    # 若仅有 holdings 列，则退回到持仓集合的 Jaccard 距离
    elif 'holdings' in result.columns:
        turnovers = []
        prev = set()
        for _, row in result.iterrows():
            curr = set(row.get('holdings', []))
            avg = (len(prev) + len(curr)) / 2
            if avg > 0:
                t = (len(prev - curr) + len(curr - prev)) / (2 * avg)
            else:
                t = 0.0
            turnovers.append(t)
            prev = curr
    else:
        turnovers = [default_turnover] * len(result)

    result['turnover'] = turnovers

    # 总交易成本 = 佣金/冲击 + spread
    total_cost_per_turnover = params.total_cost_per_turnover

    # 应用成本
    result['nav_after_cost'] = result['nav'].copy()
    if len(result) > 0:
        result.iloc[0, result.columns.get_loc('nav_after_cost')] = (
            result.iloc[0]['nav'] * (1 - turnovers[0] * total_cost_per_turnover)
        )
    for i in range(1, len(result)):
        cost_pct = result.iloc[i]['turnover'] * total_cost_per_turnover
        result.iloc[i, result.columns.get_loc('nav_after_cost')] = (
            result.iloc[i-1]['nav_after_cost'] * (1 + result.iloc[i]['mr'] - cost_pct)
        )

    return result


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    model = TradingCostModel()
    
    # 单笔交易
    cost = model.calculate_cost('AAPL', 100, 150.0)
    print(f"\n单笔交易成本:")
    print(f"  交易额: ${cost['trade_value']:,.2f}")
    print(f"  佣金: ${cost['commission']:.2f}")
    print(f"  滑点: ${cost['slippage']:.2f}")
    print(f"  总成本: ${cost['total_cost']:.2f}")
    print(f"  成本率: {cost['cost_pct']:.4%}")
    
    # 组合估算
    targets = {'AAPL': 20000, 'MSFT': 20000, 'NVDA': 20000}
    current = {
        'AAPL': {'qty': 50, 'price': 150},
        'GOOGL': {'qty': 20, 'price': 140},
    }
    
    portfolio_cost = model.estimate_portfolio_cost(targets, current)
    print(f"\n组合调仓成本:")
    print(f"  交易笔数: {portfolio_cost['total_trades']}")
    print(f"  总佣金: ${portfolio_cost['total_commission']:.2f}")
    print(f"  总滑点: ${portfolio_cost['total_slippage']:.2f}")
    print(f"  总成本: ${portfolio_cost['total_cost']:.2f}")
