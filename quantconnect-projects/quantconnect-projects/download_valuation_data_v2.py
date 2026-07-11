#!/usr/bin/env python3
"""
 - 
PEForward PEPSPB
"""
import os
import json
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# 
OUTPUT_DIR = os.path.expanduser("~/.openclaw/workspace/quantconnect-projects/data/valuation")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 
US_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "INTC", "CRM",
    "ORCL", "ADBE", "CSCO", "AVGO", "QCOM", "TXN", "AMAT", "MU", "NFLX", "INTU",
    "JPM", "BAC", "GS", "MS", "WFC", "BLK", "C", "AXP", "SCHW", "PNC",
    "SPGI", "MCO", "ICE", "CME", "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV",
    "ABT", "TMO", "DHR", "BMY", "AMGN", "GILD", "REGN", "VRTX", "MRNA",
    "HD", "COST", "NKE", "MCD", "SBUX", "LOW", "TJX", "PG", "KO", "PEP",
    "WMT", "MDLZ", "XOM", "CVX", "COP", "SLB", "OXY", "CAT", "HON", "UPS",
    "BA", "GE", "RTX", "LMT", "VZ", "T", "CMCSA", "SPY", "QQQ", "IWM",
    "TLT", "GLD", "VIXY", "PLTR", "DDOG", "NET", "NOW"
]

# 
HK_TICKERS = [
    "0001.HK", "0005.HK", "0700.HK", "0762.HK", "0857.HK", "0883.HK", 
    "0941.HK", "0981.HK", "0992.HK", "1088.HK", "1099.HK", "1109.HK", 
    "1171.HK", "1211.HK", "1299.HK", "1378.HK", "1398.HK", "1658.HK", 
    "1801.HK", "1876.HK", "1928.HK", "2015.HK", "2020.HK", "2121.HK", 
    "2269.HK", "2318.HK", "2319.HK", "2331.HK", "2333.HK", "2359.HK",
    "2382.HK", "2388.HK", "2628.HK", "2899.HK", "3690.HK", "6862.HK", 
    "9618.HK", "9988.HK", "9999.HK"
]

def safe_format(value, fmt=".1f"):
    """"""
    if value is None or (isinstance(value, float) and (value != value or value == float('inf') or value == float('-inf'))):
        return "N/A"
    try:
        return f"{value:{fmt}}"
    except:
        return str(value)

def get_valuation_data(ticker):
    """"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        data = {
            'ticker': ticker,
            'date': datetime.now().strftime('%Y-%m-%d'),
        }
        
        # info
        data['pe_trailing'] = info.get('trailingPE')
        data['pe_forward'] = info.get('forwardPE')
        data['price_to_sales'] = info.get('priceToSalesTrailing12Months')
        data['price_to_book'] = info.get('priceToBook')
        data['peg_ratio'] = info.get('pegRatio')
        data['eps_ttm'] = info.get('trailingEps')
        data['eps_forward'] = info.get('forwardEps')
        data['market_cap'] = info.get('marketCap')
        
        # 
        hist = stock.history(period="3y")
        if not hist.empty and data['eps_ttm'] and data['eps_ttm'] > 0:
            data['current_price'] = hist['Close'].iloc[-1]
            data['current_pe'] = data['current_price'] / data['eps_ttm']
            
            # /EPSPE
            historical_pe = hist['Close'] / data['eps_ttm']
            if len(historical_pe) >= 252:
                data['pe_1y_percentile'] = historical_pe.iloc[-252:].rank(pct=True).iloc[-1]
                data['pe_1y_median'] = historical_pe.iloc[-252:].median()
                data['pe_1y_min'] = historical_pe.iloc[-252:].min()
                data['pe_1y_max'] = historical_pe.iloc[-252:].max()
            if len(historical_pe) >= 504:
                data['pe_2y_percentile'] = historical_pe.iloc[-504:].rank(pct=True).iloc[-1]
            if len(historical_pe) > 0:
                data['pe_3y_percentile'] = historical_pe.rank(pct=True).iloc[-1]
        
        # 
        if ticker.endswith('.HK'):
            data['market_type'] = 'hk'
        else:
            data['market_type'] = 'us'
            
        return data
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def calculate_valuation_score(data):
    """
    0-1
    1.0 = 
    0.0 = 
    """
    scores = []
    weights = []
    
    # Forward PE vs Trailing PE 
    if data.get('pe_forward') and data.get('pe_trailing') and data['pe_trailing'] > 0:
        forward_discount = 1 - (data['pe_forward'] / data['pe_trailing'])
        score = min(max(forward_discount + 0.5, 0), 1)
        scores.append(score)
        weights.append(0.3)
    
    # PE
    pe_pct = data.get('pe_1y_percentile') or data.get('pe_2y_percentile') or data.get('pe_3y_percentile')
    if pe_pct is not None:
        score = 1 - pe_pct  #  =  = 
        scores.append(score)
        weights.append(0.4)
    
    # PEG Ratio
    if data.get('peg_ratio') and data['peg_ratio'] > 0:
        score = max(0, min(1, 1.5 - data['peg_ratio'] / 2))
        scores.append(score)
        weights.append(0.2)
    
    # Price to Sales
    if data.get('price_to_sales') and data['price_to_sales'] > 0:
        score = max(0, min(1, 1.5 - data['price_to_sales'] / 10))
        scores.append(score)
        weights.append(0.1)
    
    if scores:
        total_weight = sum(weights)
        normalized_weights = [w / total_weight for w in weights]
        final_score = sum(s * w for s, w in zip(scores, normalized_weights))
        return final_score
    
    return 0.5  # 

def main():
    print("=" * 60)
    print("...")
    print("=" * 60)
    
    all_data = []
    
    # 
    print("\n ...")
    for i, ticker in enumerate(US_TICKERS):
        data = get_valuation_data(ticker)
        if data:
            data['valuation_score'] = calculate_valuation_score(data)
            all_data.append(data)
            pe_str = safe_format(data.get('pe_trailing'))
            score_str = safe_format(data['valuation_score'], ".2f")
            print(f"  [{i+1}/{len(US_TICKERS)}] {ticker}: PE={pe_str}, Score={score_str}")
        else:
            print(f"  [{i+1}/{len(US_TICKERS)}] {ticker}: ")
    
    # 
    print("\n ...")
    for i, ticker in enumerate(HK_TICKERS):
        data = get_valuation_data(ticker)
        if data:
            data['valuation_score'] = calculate_valuation_score(data)
            all_data.append(data)
            pe_str = safe_format(data.get('pe_trailing'))
            score_str = safe_format(data['valuation_score'], ".2f")
            print(f"  [{i+1}/{len(HK_TICKERS)}] {ticker}: PE={pe_str}, Score={score_str}")
        else:
            print(f"  [{i+1}/{len(HK_TICKERS)}] {ticker}: ")
    
    # JSON
    output_file = os.path.join(OUTPUT_DIR, 'valuation_data.json')
    with open(output_file, 'w') as f:
        json.dump(all_data, f, indent=2, default=str)
    
    print(f"\n : {output_file}")
    print(f"    {len(all_data)} ")
    
    # CSV
    df = pd.DataFrame(all_data)
    csv_file = os.path.join(OUTPUT_DIR, 'valuation_data.csv')
    df.to_csv(csv_file, index=False)
    print(f"   CSV: {csv_file}")
    
    # 
    print("\n :")
    if 'valuation_score' in df.columns:
        print(f"  : {df['valuation_score'].mean():.2f}")
        print(f"  : {df['valuation_score'].median():.2f}")
    
    # /
    if 'valuation_score' in df.columns and not df['valuation_score'].isna().all():
        print("\n 10:")
        undervalued = df.nlargest(10, 'valuation_score')[['ticker', 'pe_trailing', 'pe_forward', 'valuation_score']]
        print(undervalued.to_string(index=False))
        
        print("\n 10:")
        overvalued = df.nsmallest(10, 'valuation_score')[['ticker', 'pe_trailing', 'pe_forward', 'valuation_score']]
        print(overvalued.to_string(index=False))

if __name__ == '__main__':
    main()
