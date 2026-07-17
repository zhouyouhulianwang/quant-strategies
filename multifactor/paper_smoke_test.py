#!/usr/bin/env python3
"""Paper trading smoke test for Alpaca integration.

Usage:
    python paper_smoke_test.py --dry-run       # Validate config and connectivity without orders
    python paper_smoke_test.py --live          # Place a tiny order (requires --confirm-live)

This script is designed to run in CI/CD and locally. It will NEVER place
real money trades unless `--live` is explicitly passed and confirmed.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from alpaca_executor import ALPACA_AVAILABLE, AlpacaExecutor, OrderSide, OrderType, TimeInForce


def _confirm_live() -> bool:
    print("\n⚠️  --live will place a real order in your Alpaca LIVE account.")
    print("This is a smoke test; it buys a tiny number of shares.")
    answer = input("Type 'yes' to proceed: ")
    return answer.strip().lower() == "yes"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Alpaca paper trading smoke test")
    parser.add_argument("--dry-run", action="store_true", help="Validate connectivity without placing orders")
    parser.add_argument("--live", action="store_true", help="Use Alpaca LIVE endpoint (real money)")
    parser.add_argument("--confirm-live", action="store_true", help="Explicitly confirm live trading")
    parser.add_argument("--symbol", default="SPY", help="Symbol for smoke test order")
    parser.add_argument("--qty", type=float, default=1.0, help="Quantity for smoke test order")
    parser.add_argument("--paper", action="store_true", help="Force paper endpoint (default)")
    args = parser.parse_args(argv)

    print(f"[{datetime.now(timezone.utc).isoformat()}] Alpaca smoke test starting")
    print(f"  ALPACA_AVAILABLE: {ALPACA_AVAILABLE}")
    print(f"  dry_run: {args.dry_run}")
    print(f"  live: {args.live}")

    if not ALPACA_AVAILABLE:
        print("ERROR: alpaca-py is not installed. Install requirements.txt first.")
        return 1

    if args.live and not args.confirm_live:
        print("ERROR: --live requires --confirm-live to avoid accidental real-money trading.")
        return 1

    api_key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET")
    if not api_key or not secret_key:
        print("ERROR: Alpaca API credentials not found in environment.")
        print("Expected: APCA_API_KEY_ID / APCA_API_SECRET_KEY (or ALPACA_API_KEY / ALPACA_API_SECRET)")
        return 1

    # 当 --live 被指定时，强制使用实盘域名并将 paper 设为 False
    if args.live:
        paper = False
        base_url = "https://api.alpaca.markets"
    else:
        paper = True  # 默认纸交易，安全优先
        base_url = "https://paper-api.alpaca.markets"

    print(f"  Using base_url: {base_url}")
    print(f"  Using paper: {paper}")

    executor = AlpacaExecutor(
        api_key=api_key,
        api_secret=secret_key,
        paper=paper,
        risk_monitor=None,  # smoke test bypasses risk monitor
    )

    try:
        account = executor.get_account()
        print(f"  Account status: {account.get('status') if isinstance(account, dict) else account.status}")
        print(f"  Account equity: {account.get('equity') if isinstance(account, dict) else account.equity}")
        print(f"  Buying power: {account.get('buying_power') if isinstance(account, dict) else account.buying_power}")
    except Exception as e:
        print(f"ERROR: Failed to get account: {e}")
        return 1

    if args.dry_run:
        print("  Dry-run: connectivity OK. No orders placed.")
        return 0

    if not args.live:
        print("  No --live specified. Use --live --confirm-live to place a tiny order (or --dry-run to validate).")
        return 0

    if not args.confirm_live:
        print("ERROR: --live requires --confirm-live flag.")
        return 1

    if not _confirm_live():
        print("  Aborted by user.")
        return 1

    symbol = args.symbol
    qty = args.qty
    print(f"  Placing MARKET BUY order for {qty} share(s) of {symbol} on LIVE account...")

    try:
        order = executor.submit_order(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )
        order_id = order.get('id') if isinstance(order, dict) else getattr(order, 'id', None)
        order_status = order.get('status') if isinstance(order, dict) else getattr(order, 'status', None)
        print(f"  Order submitted: {order_id} status={order_status}")
    except Exception as e:
        print(f"ERROR: Order submission failed: {e}")
        return 1

    print("\nSmoke test completed. Check Alpaca dashboard and local PDT/orders files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
