import warnings, json, time, sys
warnings.filterwarnings('ignore')
from quantconnect_data import prepare_backtest_data_qc

with open('data/sp500_tickers.json') as f:
    sp500 = json.load(f)
with open('data/ndx100_tickers.json') as f:
    ndx = json.load(f)
all_tickers = sorted(set(sp500 + ndx))

start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
end = int(sys.argv[2]) if len(sys.argv) > 2 else 100
period = sys.argv[3] if len(sys.argv) > 3 else '1y'
if period == '1y':
    s, e = '2024-01-01', '2025-01-01'
else:
    s, e = '2021-07-18', '2026-07-17'

tickers = all_tickers[start:end]
print(f'tickers: {len(tickers)} range: [{start}:{end}] period: {s}~{e}')
t0 = time.time()
price, market = prepare_backtest_data_qc(tickers, s, e)
print(f'elapsed: {round(time.time()-t0,1)}s')
print(f'price: {price.shape}')
print(f'market: {market.shape}')
print(f'price cols: {len(price.columns)}')
print(f'price rows all na: {price.isna().all(axis=1).sum()}')
print(f'price cols all na: {price.isna().all().sum()}')
print('sample tickers:', tickers[:5])
