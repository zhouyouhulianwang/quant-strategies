#!/usr/bin/env python3
"""
Alpaca 模拟交易测试
Paper Trading API 集成
"""
import os
import json
import time
from datetime import datetime, timedelta

try:
    import alpaca_trade_api as tradeapi
except ImportError:
    print("错误: 未安装 alpaca-trade-api")
    print("运行: .venv/bin/pip install alpaca-trade-api")
    exit(1)

# Alpaca Paper Trading API (模拟环境)
# 从环境变量读取 API Key，如果没有则使用示例配置
API_KEY = os.environ.get('ALPACA_API_KEY', 'YOUR_API_KEY')
API_SECRET = os.environ.get('ALPACA_API_SECRET', 'YOUR_SECRET')
BASE_URL = 'https://paper-api.alpaca.markets'  # 纸交易环境

class AlpacaPaperTrader:
    """Alpaca 纸交易模拟器"""
    
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or API_KEY
        self.api_secret = api_secret or API_SECRET
        self.base_url = BASE_URL
        self.api = None
        self.is_connected = False
    
    def connect(self):
        """连接 Alpaca API"""
        if self.api_key == 'YOUR_API_KEY':
            print("⚠️  未配置 API Key")
            print("请设置环境变量: ALPACA_API_KEY 和 ALPACA_API_SECRET")
            return False
        
        try:
            self.api = tradeapi.REST(
                self.api_key,
                self.api_secret,
                self.base_url,
                api_version='v2'
            )
            # 测试连接
            account = self.api.get_account()
            self.is_connected = True
            print(f"✅ 连接成功 - 账户: {account.id}")
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def get_account(self):
        """获取账户信息"""
        if not self.is_connected:
            return None
        
        try:
            account = self.api.get_account()
            return {
                'id': account.id,
                'status': account.status,
                'cash': float(account.cash),
                'portfolio_value': float(account.portfolio_value),
                'equity': float(account.equity),
                'buying_power': float(account.buying_power),
                'daytrade_count': int(account.daytrade_count),
                'currency': account.currency
            }
        except Exception as e:
            print(f"获取账户信息失败: {e}")
            return None
    
    def get_positions(self):
        """获取持仓"""
        if not self.is_connected:
            return []
        
        try:
            positions = self.api.list_positions()
            result = []
            for p in positions:
                result.append({
                    'symbol': p.symbol,
                    'qty': int(p.qty),
                    'market_value': float(p.market_value),
                    'avg_entry_price': float(p.avg_entry_price),
                    'unrealized_pl': float(p.unrealized_pl),
                    'unrealized_plpc': float(p.unrealized_plpc) * 100,
                    'current_price': float(p.current_price)
                })
            return result
        except Exception as e:
            print(f"获取持仓失败: {e}")
            return []
    
    def get_orders(self, status='all', limit=50):
        """获取订单列表"""
        if not self.is_connected:
            return []
        
        try:
            orders = self.api.list_orders(status=status, limit=limit)
            result = []
            for o in orders:
                result.append({
                    'id': o.id,
                    'symbol': o.symbol,
                    'side': o.side,
                    'qty': int(o.qty),
                    'type': o.type,
                    'status': o.status,
                    'submitted_at': str(o.submitted_at),
                    'filled_at': str(o.filled_at) if o.filled_at else None,
                    'filled_avg_price': float(o.filled_avg_price) if o.filled_avg_price else None
                })
            return result
        except Exception as e:
            print(f"获取订单失败: {e}")
            return []
    
    def submit_order(self, symbol, qty, side, order_type='market', limit_price=None):
        """提交订单"""
        if not self.is_connected:
            return None
        
        try:
            if order_type == 'market':
                order = self.api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side=side,
                    type='market',
                    time_in_force='day'
                )
            elif order_type == 'limit':
                order = self.api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side=side,
                    type='limit',
                    limit_price=limit_price,
                    time_in_force='day'
                )
            else:
                return None
            
            print(f"✅ 订单提交: {side.upper()} {qty} {symbol} @ {order_type}")
            return {
                'id': order.id,
                'symbol': order.symbol,
                'qty': int(order.qty),
                'side': order.side,
                'status': order.status
            }
        except Exception as e:
            print(f"❌ 订单提交失败: {e}")
            return None
    
    def get_bars(self, symbol, timeframe='1D', limit=100):
        """获取历史K线"""
        if not self.is_connected:
            return []
        
        try:
            # Alpaca v2 API 获取历史数据
            bars = self.api.get_bars(
                symbol,
                tradeapi.TimeFrame.Day if timeframe == '1D' else tradeapi.TimeFrame.Hour,
                limit=limit
            ).df
            
            result = []
            for index, row in bars.iterrows():
                result.append({
                    'timestamp': str(index),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume'])
                })
            return result
        except Exception as e:
            print(f"获取历史数据失败: {e}")
            return []
    
    def get_clock(self):
        """获取市场状态"""
        if not self.is_connected:
            return None
        
        try:
            clock = self.api.get_clock()
            return {
                'is_open': clock.is_open,
                'next_open': str(clock.next_open),
                'next_close': str(clock.next_close)
            }
        except Exception as e:
            print(f"获取市场状态失败: {e}")
            return None


def run_paper_test():
    """运行 Alpaca 纸交易测试"""
    print("=" * 60)
    print("Alpaca 模拟交易测试 (Paper Trading)")
    print("=" * 60)
    
    trader = AlpacaPaperTrader()
    
    # 1. 连接测试
    print("\n1. API 连接测试")
    print("-" * 60)
    if not trader.connect():
        print("\n未配置 API Key，演示模式结束")
        print("\n获取 API Key 步骤:")
        print("1. 访问 https://alpaca.markets")
        print("2. 注册账户并登录")
        print("3. 进入 Paper Trading Dashboard")
        print("4. 生成 API Key ID 和 Secret Key")
        print("5. 设置环境变量:")
        print("   export ALPACA_API_KEY='your-key'")
        print("   export ALPACA_API_SECRET='your-secret'")
        return
    
    # 2. 账户信息
    print("\n2. 账户信息")
    print("-" * 60)
    account = trader.get_account()
    if account:
        print(f"  状态: {account['status']}")
        print(f"  现金: ${account['cash']:,.2f}")
        print(f"  组合价值: ${account['portfolio_value']:,.2f}")
        print(f"  购买力: ${account['buying_power']:,.2f}")
        print(f"  日内交易次数: {account['daytrade_count']}")
    
    # 3. 持仓信息
    print("\n3. 当前持仓")
    print("-" * 60)
    positions = trader.get_positions()
    if positions:
        print(f"  {'标的':<8} {'数量':<8} {'当前价':<10} {'市值':<12} {'未实现盈亏':<12}")
        for p in positions:
            print(f"  {p['symbol']:<8} {p['qty']:<8} ${p['current_price']:<9.2f} ${p['market_value']:<11.2f} {p['unrealized_pl']:>+10.2f}")
    else:
        print("  无持仓")
    
    # 4. 市场状态
    print("\n4. 市场状态")
    print("-" * 60)
    clock = trader.get_clock()
    if clock:
        status = "开盘" if clock['is_open'] else "收盘"
        print(f"  状态: {status}")
        print(f"  下次开盘: {clock['next_open']}")
        print(f"  下次收盘: {clock['next_close']}")
    
    # 5. 历史数据
    print("\n5. 历史数据 (AAPL)")
    print("-" * 60)
    bars = trader.get_bars('AAPL', '1D', 5)
    if bars:
        for bar in bars:
            print(f"  {bar['timestamp'][:10]} O:{bar['open']:.2f} H:{bar['high']:.2f} L:{bar['low']:.2f} C:{bar['close']:.2f} V:{bar['volume']}")
    
    # 6. 订单测试
    print("\n6. 提交模拟订单")
    print("-" * 60)
    print("  ⚠️  注意: 这是纸交易，不会使用真实资金")
    
    # 检查是否有足够现金
    if account and account['cash'] > 1000:
        # 提交市价单买入 1 股 AAPL
        order = trader.submit_order('AAPL', 1, 'buy', 'market')
        if order:
            print(f"  订单 ID: {order['id']}")
            print(f"  状态: {order['status']}")
    else:
        print(f"  现金不足 (${account['cash']:.2f})，跳过订单测试")
    
    # 7. 订单查询
    print("\n7. 最近订单")
    print("-" * 60)
    orders = trader.get_orders('all', 10)
    if orders:
        print(f"  {'ID':<36} {'标的':<8} {'方向':<6} {'数量':<6} {'状态':<10}")
        for o in orders[:5]:
            print(f"  {o['id']:<36} {o['symbol']:<8} {o['side']:<6} {o['qty']:<6} {o['status']:<10}")
    else:
        print("  无订单")
    
    print("\n" + "=" * 60)
    print("Alpaca 测试完成!")
    print("=" * 60)
    print("\n提示:")
    print("- 纸交易使用模拟资金，不会损失真实资产")
    print("- API 调用频率限制: 200/分钟")
    print("- 交易时间: 美股开盘 9:30-16:00 ET")
    print(f"- 交易 URL: {BASE_URL}")


def run_momentum_strategy():
    """运行动量策略模拟交易"""
    print("\n" + "=" * 60)
    print("AdaptiveMomentum 策略 - Alpaca 模拟执行")
    print("=" * 60)
    
    trader = AlpacaPaperTrader()
    
    if not trader.connect():
        print("未配置 API Key，跳过策略执行")
        return
    
    # 模拟动量策略信号
    print("\n策略参数:")
    print(f"  最大持仓: 3")
    print(f"  最大仓位: 20%")
    print(f"  再平衡: 月度")
    
    # 获取账户信息
    account = trader.get_account()
    if not account:
        return
    
    cash = account['cash']
    portfolio_value = account['portfolio_value']
    max_position_value = portfolio_value * 0.20
    
    print(f"\n当前资金:")
    print(f"  现金: ${cash:,.2f}")
    print(f"  组合价值: ${portfolio_value:,.2f}")
    print(f"  最大单仓位: ${max_position_value:,.2f}")
    
    # 模拟买入信号
    signals = ['AAPL', 'MSFT', 'NVDA']  # 模拟动量 top 3
    print(f"\n买入信号: {signals}")
    
    for symbol in signals:
        # 获取最新价格
        bars = trader.get_bars(symbol, '1D', 1)
        if bars:
            price = bars[-1]['close']
            qty = int(max_position_value / price)
            
            if qty > 0 and cash >= qty * price:
                print(f"\n  {symbol}:")
                print(f"    价格: ${price:.2f}")
                print(f"    计划买入: {qty} 股 (${qty * price:.2f})")
                
                # 实际提交订单 (取消注释以执行)
                # order = trader.submit_order(symbol, qty, 'buy', 'market')
                # if order:
                #     print(f"    ✅ 订单已提交: {order['id']}")
                #     cash -= qty * price
            else:
                print(f"  {symbol}: 资金不足或数量为0")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'strategy':
        run_momentum_strategy()
    else:
        run_paper_test()
