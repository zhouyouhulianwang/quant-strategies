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

# 获取账户
account = api.get_account()
print(f"账户状态: {account.status}")
print(f"现金: ${float(account.cash):,.2f}")
print(f"组合价值: ${float(account.portfolio_value):,.2f}")
print(f"权益: ${float(account.equity):,.2f}")
print(f"购买力: ${float(account.buying_power):,.2f}")

print("\n当前持仓:")
positions = api.list_positions()
for p in positions:
    print(f"  {p.symbol}: {p.qty} 股 @ ${float(p.current_price):.2f} = ${float(p.market_value):,.2f}")

print("\n最近订单:")
orders = api.list_orders(status='all', limit=10)
for o in orders:
    print(f"  {o.symbol} {o.side} {o.qty} @ {o.type} - {o.status}")
