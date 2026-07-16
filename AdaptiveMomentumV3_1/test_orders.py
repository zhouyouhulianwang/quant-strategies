import os
os.environ['ALPACA_API_KEY'] = 'PKLEBXJSPMD3KTVWKZ2YCL6TFS'
os.environ['ALPACA_API_SECRET'] = 'CGpoVig4mRPukzszzeiyX2x33WH9AEXxhQtxHDmKNFHT'

import alpaca_trade_api as tradeapi

api = tradeapi.REST(
    os.environ['ALPACA_API_KEY'],
    os.environ['ALPACA_API_SECRET'],
    'https://paper-api.alpaca.markets',
    api_version='v2'
)

# 获取所有订单
orders = api.list_orders(status='all', limit=20)
print("所有订单:")
for o in orders:
    filled = f" @ ${float(o.filled_avg_price):.2f}" if o.filled_avg_price else ""
    print(f"  {o.id}")
    print(f"    标的: {o.symbol}")
    print(f"    方向: {o.side.upper()}")
    print(f"    数量: {o.qty}")
    print(f"    类型: {o.type}")
    print(f"    状态: {o.status}")
    print(f"    已成交: {o.filled_qty}/{o.qty}{filled}")
    print(f"    提交时间: {o.submitted_at}")
    print(f"    成交时间: {o.filled_at or 'N/A'}")
    print()

# 获取市场状态
clock = api.get_clock()
print(f"市场开放: {clock.is_open}")
print(f"下次开盘: {clock.next_open}")
print(f"下次收盘: {clock.next_close}")
