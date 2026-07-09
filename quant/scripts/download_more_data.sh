#!/bin/bash
# Download more sample data from QuantConnect GitHub

set -e

DATA_DIR="/home/pc/.openclaw/workspace/quant/data"
BASE_URL="https://raw.githubusercontent.com/QuantConnect/Lean/master/Data"

# Download additional tickers
TICKERS=("aapl" "goog" "ibm" "qqq" "iwm" "eem")

echo "Downloading additional equity data..."
for ticker in "${TICKERS[@]}"; do
    dest="$DATA_DIR/equity/usa/daily/${ticker}.zip"
    if [ ! -f "$dest" ]; then
        echo "Downloading ${ticker}.zip..."
        curl -sL "${BASE_URL}/equity/usa/daily/${ticker}.zip" -o "$dest" 2>/dev/null || echo "  Failed: ${ticker}"
        if [ -f "$dest" ]; then
            echo "  ✓ ${ticker} downloaded"
        fi
    else
        echo "  ✓ ${ticker} already exists"
    fi
done

# Download map files
echo "Downloading map_files..."
mkdir -p "$DATA_DIR/equity/usa/map_files"
curl -sL "${BASE_URL}/equity/usa/map_files/spy.csv" -o "$DATA_DIR/equity/usa/map_files/spy.csv" 2>/dev/null || echo "  map_files not available via raw"

# Download factor files
echo "Downloading factor_files..."
mkdir -p "$DATA_DIR/equity/usa/factor_files"
curl -sL "${BASE_URL}/equity/usa/factor_files/spy.csv" -o "$DATA_DIR/equity/usa/factor_files/spy.csv" 2>/dev/null || echo "  factor_files not available via raw"

echo "Done!"
ls -la "$DATA_DIR/equity/usa/daily/"
