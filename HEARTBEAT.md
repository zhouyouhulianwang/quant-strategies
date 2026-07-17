<!-- Heartbeat template for multifactor trading system. -->
<!-- Keep comments-only to skip heartbeat API calls. Add tasks below for periodic checks. -->

# Multifactor Trading System — Daily Heartbeat Checklist

## Routine checks (rotate 2–4 per day, skip 23:00–08:00 UTC unless urgent)
- [ ] **Git status**: `multifactor/` has no uncommitted critical fixes? Pull/push up to date?
- [ ] **Last test run**: `pytest test_suite.py` still green? If not, halt paper/live and investigate.
- [ ] **Backtest sanity** (weekly): run daily backtest; CAGR/Sharpe/MaxDD within expected bands.
- [ ] **Runtime disk**: check `logs/`, `orders/`, `alerts/`, `charts/` not growing out of control; cleanup if >80% disk.
- [ ] **Backup state**: run `python3 multifactor/backup_state.py` after any config/risk change; verify latest backup has restrictive permissions.
- [ ] **Alpaca paper health** (if enabled): last rebalance succeeded? Any rejected/filled-with-warning orders? PDT count safe?
- [ ] **Risk monitor**: `trading_halted` false? If true, check `alerts/` and follow `RISK_RUNBOOK.md`.
- [ ] **Market data freshness**: latest bar/date in cache/feed not stale? Any corporate actions announced?

## When to reach out immediately
- Trading halted, emergency liquidation, or repeated order rejection.
- Backtest metrics deviate >20% from baseline without code change.
- Paper/live process crash or heartbeat missing >1 expected interval.
- API key / .env / credential issue detected.

## When to stay quiet
- No new alerts, all tests green, and last check was <30 minutes ago.
- Late-night quiet hours with no urgent signals.

_If you update this checklist, run `python3 multifactor/backup_state.py` so the runbook stays backed up._
