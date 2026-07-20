import os, glob, json
from quantconnect_data import LEAN_DATA_DIR

daily_files = set([os.path.splitext(os.path.basename(f))[0].upper() for f in glob.glob(os.path.join(LEAN_DATA_DIR, 'equity', 'usa', 'daily', '*.zip'))])
print('daily files:', len(daily_files))
with open('data/sp500_tickers.json') as f:
    sp500 = set(json.load(f))
with open('data/ndx100_tickers.json') as f:
    ndx = set(json.load(f))
universe = sp500 | ndx
covered = daily_files & universe
missing = universe - daily_files
print('covered:', len(covered), 'missing:', len(missing))
print('missing sample:', sorted(missing)[:20])
