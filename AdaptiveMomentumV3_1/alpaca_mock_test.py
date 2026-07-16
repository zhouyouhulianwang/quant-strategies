#!/usr/bin/env python3
"""
Alpaca 模拟交易 - Mock 演示版
无需 API Key 即可演示完整交易流程
"""
import json
import time
from datetime import datetime, timedelta
import random

class MockAlpacaAPI:
    """模拟 Alpaca API 响应"""
    
    def __init__(self, initial_cash=100000.0):
        self.cash = initial_cash
        self.positions = {}
        self.orders = []
        self.order_id_counter = 1
        self.market_prices = {
            'AAPL': 185.50, 'MSFT': 420.25, 'GOOGL': 175.80, 'AMZN': 180.30,
            'META': 500.15, 'NVDA': 890.40, 'TSLA': 245.60, 'JPM': 195.30,
            'JNJ': 155.80, 'V': 280.50, 'WMT': 165.20, 'PG': 155.60,
            'MA': 450.80, 'UNH': 520.30, 'HD': 350.20, 'BAC': 38.50,
            'ABBV': 175.40, 'PFE': 28.90, 'KO': 62.40, 'PEP': 168.30
        }
    
    def _update_prices(self):
        """模拟价格波动"""
        for symbol in self.market_prices:
            change = random.uniform(-0.02, 0.02)
            self.market_prices[symbol] *= (1 + change)
    
    def get_account(self):
        """获取模拟账户"""
        portfolio_value = self.cash
        for symbol, pos in self.positions.items():
            portfolio_value += pos['qty'] * self.market_prices[symbol]
        
        return {
            'id': 'mock-account-001',
            'status': 'ACTIVE',
            'cash': self.cash,
            'portfolio_value': portfolio_value,
            'equity': portfolio_value,
            'buying_power': self.cash * 2,  # 2x margin
            'daytrade_count': 0,
            'currency': 'USD'
        }
    
    def list_positions(self):
        """获取模拟持仓"""
        positions = []
        for symbol, pos in self.positions.items():
            current_price = self.market_prices[symbol]
            market_value = pos['qty'] * current_price
            unrealized_pl = market_value - pos['cost_basis']
            unrealized_plpc = (unrealized_pl / pos['cost_basis']) * 100
            
            positions.append({
                'symbol': symbol,
                'qty': pos['qty'],
                'market_value': market_value,
                'avg_entry_price': pos['avg_entry_price'],
                'unrealized_pl': unrealized_pl,
                'unrealized_plpc': unrealized_plpc,
                'current_price': current_price
            })
        return positions
    
    def list_orders(self, status='all', limit=50):
        """获取模拟订单"""
        return self.orders[-limit:]
    
    def submit_order(self, symbol, qty, side, type='market', limit_price=None):
        """提交模拟订单"""
        self._update_prices()
        
        order_id = f"mock-order-{self.order_id_counter}"
        self.order_id_counter += 1
        
        price = self.market_prices.get(symbol, 100.0)
        
        if side == 'buy':
            cost = qty * price
            if cost > self.cash:
                raise Exception(f"Insufficient funds: ${self.cash:.2f} < ${cost:.2f}")
            
            self.cash -= cost
            if symbol in self.positions:
                old_qty = self.positions[symbol]['qty']
                old_cost = self.positions[symbol]['cost_basis']
                self.positions[symbol]['qty'] += qty
                self.positions[symbol]['cost_basis'] += cost
                self.positions[symbol]['avg_entry_price'] = self.positions[symbol]['cost_basis'] / self.positions[symbol]['qty']
            else:
                self.positions[symbol] = {
                    'qty': qty,
                    'avg_entry_price': price,
                    'cost_basis': cost
                }
        else:  # sell
            if symbol not in self.positions or self.positions[symbol]['qty'] < qty:
                raise Exception(f"Insufficient shares: {self.positions.get(symbol, {}).get('qty', 0)} < {qty}")
            
            proceeds = qty * price
            self.cash += proceeds
            self.positions[symbol]['qty'] -= qty
            if self.positions[symbol]['qty'] == 0:
                del self.positions[symbol]
        
        order = {
            'id': order_id,
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': type,
            'status': 'filled',
            'submitted_at': str(datetime.now()),
            'filled_at': str(datetime.now()),
            'filled_avg_price': price
        }
        self.orders.append(order)
        return order
    
    def get_bars(self, symbol, limit=100):
        """生成模拟K线"""
        bars = []
        base_price = self.market_prices.get(symbol, 100.0)
        
        for i in range(limit):
            date = datetime.now() - timedelta(days=limit-i)
            change = random.uniform(-0.03, 0.03)
            close = base_price * (1 + change)
            open_price = close * (1 + random.uniform(-0.01, 0.01))
            high = max(open_price, close) * (1 + random.uniform(0, 0.02))
            low = min(open_price, close) * (1 - random.uniform(0, 0.02))
            volume = random.randint(1000000, 10000000)
            
            bars.append({
                'timestamp': str(date.date()),
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume
            })
        
        return bars
    
    def get_clock(self):
        """获取市场状态"""
        now = datetime.now()
        hour = now.hour
        
        # 模拟美股时间 (ET 9:30-16:00)
        is_open = 9 <= hour < 16
        
        if is_open:
            next_close = now.replace(hour=16, minute=0, second=0)
            next_open = now + timedelta(days=1)
            next_open = next_open.replace(hour=9, minute=30, second=0)
        else:
            if hour < 9:
                next_open = now.replace(hour=9, minute=30, second=0)
                next_close = now.replace(hour=16, minute=0, second=0)
            else:
                next_open = (now + timedelta(days=1)).replace(hour=9, minute=30, second=0)
                next_close = next_open.replace(hour=16, minute=0, second=0)
        
        return {
            'is_open': is_open,
            'next_open': str(next_open),
            'next_close': str(next_close)
        }


def run_mock_paper_test():
    """运行模拟纸交易测试"""
    print("=" * 70)
    print("🚀 Alpaca 模拟交易 - Mock 演示")
    print("=" * 70)
    print("\n⚠️  使用模拟数据，无需 API Key")
    
    api = MockAlpacaAPI(initial_cash=100000.0)
    
    # 1. 账户信息
    print("\n1. 账户信息")
    print("-" * 70)
    account = api.get_account()
    print(f"  账户 ID: {account['id']}")
    print(f"  状态: {account['status']}")
    print(f"  现金: ${account['cash']:,.2f}")
    print(f"  组合价值: ${account['portfolio_value']:,.2f}")
    print(f"  购买力: ${account['buying_power']:,.2f}")
    
    # 2. 市场状态
    print("\n2. 市场状态")
    print("-" * 70)
    clock = api.get_clock()
    status = "🟢 开盘" if clock['is_open'] else "🔴 收盘"
    print(f"  状态: {status}")
    print(f"  下次开盘: {clock['next_open']}")
    print(f"  下次收盘: {clock['next_close']}")
    
    # 3. 历史数据
    print("\n3. 历史数据 (AAPL)")
    print("-" * 70)
    bars = api.get_bars('AAPL', limit=5)
    print(f"  {'日期':<12} {'开盘':<10} {'最高':<10} {'最低':<10} {'收盘':<10} {'成交量':<12}")
    for bar in bars[-5:]:
        print(f"  {bar['timestamp']:<12} ${bar['open']:<9.2f} ${bar['high']:<9.2f} ${bar['low']:<9.2f} ${bar['close']:<9.2f} {bar['volume']:<12,}")
    
    # 4. 提交买入订单
    print("\n4. 买入订单")
    print("-" * 70)
    
    buy_signals = [
        ('AAPL', 10),
        ('MSFT', 5),
        ('NVDA', 3)
    ]
    
    for symbol, qty in buy_signals:
        try:
            order = api.submit_order(symbol, qty, 'buy', 'market')
            print(f"  ✅ BUY {qty} {symbol} @ ${order['filled_avg_price']:.2f}")
        except Exception as e:
            print(f"  ❌ BUY {qty} {symbol}: {e}")
    
    time.sleep(0.5)  # 模拟延迟
    
    # 5. 查看持仓
    print("\n5. 当前持仓")
    print("-" * 70)
    positions = api.list_positions()
    if positions:
        print(f"  {'标的':<8} {'数量':<8} {'成本价':<10} {'现价':<10} {'市值':<12} {'盈亏':<12}")
        for p in positions:
            pl_color = "🟢" if p['unrealized_pl'] > 0 else "🔴"
            print(f"  {p['symbol']:<8} {p['qty']:<8} ${p['avg_entry_price']:<9.2f} ${p['current_price']:<9.2f} ${p['market_value']:<11.2f} {pl_color} ${p['unrealized_pl']:<+10.2f}")
    else:
        print("  无持仓")
    
    # 6. 查看账户（买入后）
    print("\n6. 账户信息（买入后）")
    print("-" * 70)
    account = api.get_account()
    print(f"  现金: ${account['cash']:,.2f}")
    print(f"  组合价值: ${account['portfolio_value']:,.2f}")
    print(f"  购买力: ${account['buying_power']:,.2f}")
    
    # 7. 卖出测试
    print("\n7. 卖出订单")
    print("-" * 70)
    try:
        order = api.submit_order('AAPL', 5, 'sell', 'market')
        print(f"  ✅ SELL 5 AAPL @ ${order['filled_avg_price']:.2f}")
    except Exception as e:
        print(f"  ❌ SELL 5 AAPL: {e}")
    
    # 8. 查看订单历史
    print("\n8. 订单历史")
    print("-" * 70)
    orders = api.list_orders()
    print(f"  {'ID':<20} {'标的':<8} {'方向':<6} {'数量':<6} {'价格':<10} {'状态':<10}")
    for order in orders:
        print(f"  {order['id']:<20} {order['symbol']:<8} {order['side']:<6} {order['qty']:<6} ${order['filled_avg_price']:<9.2f} {order['status']:<10}")
    
    # 9. 最终持仓
    print("\n9. 最终持仓")
    print("-" * 70)
    positions = api.list_positions()
    if positions:
        total_value = 0
        for p in positions:
            total_value += p['market_value']
            print(f"  {p['symbol']}: {p['qty']} 股 @ ${p['current_price']:.2f} = ${p['market_value']:,.2f}")
        print(f"\n  持仓总市值: ${total_value:,.2f}")
    else:
        print("  无持仓")
    
    print("\n" + "=" * 70)
    print("✅ Mock 模拟交易完成!")
    print("=" * 70)
    print("\n📊 总结:")
    account = api.get_account()
    print(f"  初始资金: $100,000.00")
    print(f"  最终现金: ${account['cash']:,.2f}")
    print(f"  组合价值: ${account['portfolio_value']:,.2f}")
    print(f"  总盈亏: ${account['portfolio_value'] - 100000:+.2f}")
    print(f"  订单数量: {len(orders)}")
    print(f"  当前持仓: {len(positions)} 只")
    
    print("\n💡 下一步:")
    print("  1. 获取 Alpaca API Key (https://alpaca.markets)")
    print("  2. 设置环境变量: ALPACA_API_KEY, ALPACA_API_SECRET")
    print("  3. 运行: python3 alpaca_paper_test.py")
    print("  4. 策略实盘: python3 alpaca_paper_test.py strategy")


def run_mock_momentum_strategy():
    """运行模拟动量策略交易"""
    print("\n" + "=" * 70)
    print("🚀 AdaptiveMomentum 策略 - 模拟执行")
    print("=" * 70)
    
    api = MockAlpacaAPI(initial_cash=100000.0)
    
    # 策略参数
    max_positions = 3
    max_position_pct = 0.20
    
    print(f"\n策略参数:")
    print(f"  最大持仓: {max_positions}")
    print(f"  最大仓位: {max_position_pct*100:.0f}%")
    
    # 模拟动量信号
    print(f"\n📈 生成动量信号...")
    
    # 模拟评分
    momentum_scores = {
        'AAPL': 0.85, 'MSFT': 0.72, 'NVDA': 0.91,
        'GOOGL': 0.65, 'AMZN': 0.58, 'META': 0.45
    }
    
    top_stocks = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)[:max_positions]
    
    print(f"\n🏆 动量 Top {max_positions}:")
    for symbol, score in top_stocks:
        print(f"  {symbol}: {score:.2f}")
    
    # 获取账户
    account = api.get_account()
    portfolio_value = account['portfolio_value']
    max_position_value = portfolio_value * max_position_pct
    
    print(f"\n💰 组合价值: ${portfolio_value:,.2f}")
    print(f"  单仓上限: ${max_position_value:,.2f}")
    
    # 执行买入
    print(f"\n🛒 执行买入...")
    for symbol, score in top_stocks:
        bars = api.get_bars(symbol, limit=1)
        if bars:
            price = bars[-1]['close']
            qty = int(max_position_value / price)
            
            if qty > 0:
                try:
                    order = api.submit_order(symbol, qty, 'buy', 'market')
                    print(f"  ✅ {symbol}: {qty} 股 @ ${order['filled_avg_price']:.2f} (${qty * order['filled_avg_price']:,.2f})")
                except Exception as e:
                    print(f"  ❌ {symbol}: {e}")
    
    # 显示持仓
    print(f"\n📊 策略持仓:")
    positions = api.list_positions()
    if positions:
        total_value = 0
        for p in positions:
            total_value += p['market_value']
            print(f"  {p['symbol']}: {p['qty']} 股 @ ${p['current_price']:.2f} = ${p['market_value']:,.2f}")
        print(f"\n  持仓市值: ${total_value:,.2f}")
    
    print(f"\n💵 剩余现金: ${api.get_account()['cash']:,.2f}")
    
    print(f"\n✅ 策略执行完成!")
    print(f"  共买入 {len(positions)} 只标的")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'strategy':
        run_mock_momentum_strategy()
    else:
        run_mock_paper_test()
