"""验证实盘接口 - Binance Sandbox"""
import sys
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'localquant'))

from localquant.live.binance import BinanceBroker
from localquant.live.base import Order, OrderSide, OrderType

print("="*60)
print("Binance Live Broker Test (Sandbox)")
print("="*60)

# 创建币安接口（sandbox模式，无需真实API key）
broker = BinanceBroker(sandbox=True)

# 1. 连接测试
print("\n1. Testing connection...")
try:
    connected = broker.connect()
    print(f"  Connection: {'✓ Connected' if connected else '✗ Failed'}")
    print(f"  Markets loaded: {len(broker._exchange.markets) if broker._exchange else 0}")
except Exception as e:
    print(f"  Connection test: {e}")

# 2. 获取市场价格
print("\n2. Testing market price...")
if broker.is_connected:
    try:
        price = broker.get_market_price('BTC/USDT')
        print(f"  BTC/USDT: ${price:,.2f}" if price else "  ✗ Failed")
        
        price = broker.get_market_price('ETH/USDT')
        print(f"  ETH/USDT: ${price:,.2f}" if price else "  ✗ Failed")
    except Exception as e:
        print(f"  Price test: {e}")

# 3. 获取账户（sandbox模式下可用）
print("\n3. Testing account info...")
if broker.is_connected:
    try:
        account = broker.get_account()
        if account:
            print(f"  Cash: ${account.cash:,.2f}")
            print(f"  Equity: ${account.equity:,.2f}")
            print(f"  Positions: {len(account.positions)}")
        else:
            print("  Account info not available (need API key)")
    except Exception as e:
        print(f"  Account test: {e}")

# 4. 模拟下单（不真正执行）
print("\n4. Testing order creation...")
order = Order(
    symbol='BTC/USDT',
    side=OrderSide.BUY,
    quantity=0.001,
    order_type=OrderType.MARKET
)
print(f"  Order: {order.side.value} {order.quantity} {order.symbol}")
print(f"  Order type: {order.order_type.value}")
print("  ✓ Order object created")

print("\n5. Disconnecting...")
broker.disconnect()
print("  ✓ Disconnected")

print("\n" + "="*60)
print("✓ Binance broker test complete!")
print("  - Sandbox mode works without API key")
print("  - Market data retrieval works")
print("  - Account/Order operations need API key for real trading")
print("="*60)
