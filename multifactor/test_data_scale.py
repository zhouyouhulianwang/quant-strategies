import warnings, json, time, sys
warnings.filterwarnings('ignore')
from quantconnect_data import prepare_backtest_data_qc

with open('data/sp500_tickers.json') as f:
    sp500 = json.load(f)
with open('data/ndx100_tickers.json') as f:
    ndx = json.load(f)
all_tickers = sorted(set(sp500 + ndx))

count = int(sys.argv[1]) if len(sys.argv) > 1 else 300
period = sys.argv[2] if len(sys.argv) > 2 else '1y'
if period == '1y':
    start, end = '2024-01-01', '2025-01-01'
else:
    start, end = '2021-07-18', '2026-07-17'

tickers = all_tickers[:count]
print(f'tickers: {len(tickers)} period: {start}~{end}')
start_t = time.time()
price, market = prepare_backtest_data_qc(tickers, start, end)
print(f'elapsed: {round(time.time()-start_t,1)}s')
print(f'price: {price.shape}')
print(f'market: {market.shape}')
print(f'price cols: {len(price.columns)}')
print(f'price rows all na: {price.isna().all(axis=1).sum()}')
print(f'price cols all na: {price.isna().all().sum()}')
