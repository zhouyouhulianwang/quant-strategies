<!-- Heartbeat template for multifactor trading system. -->
<!-- Keep comments-only to skip heartbeat API calls. Add tasks below for periodic checks. -->

# Multifactor Trading System — Daily Heartbeat Checklist

## Routine checks (rotate 2–4 per day, skip 23:00–08:00 UTC unless urgent)
- [ ] **Git status**: `multifactor/` has no uncommitted critical fixes? Pull/push up to date?
- [ ] **Test status**: `pytest test_suite.py` still green? If not, halt paper/live and investigate.
- [ ] **Risk status**: `trading_halted` false? If true, check `alerts/` and follow `RISK_RUNBOOK.md`. No unacknowledged emergency liquidation?
- [ ] **Kill switch**: `data/kill_switch` absent and `MULTIFACTOR_KILL_SWITCH` not set? If either present, trading must be halted.
- [ ] **Data freshness**: latest bar/date in cache/feed not stale? Any corporate actions announced? VIX/price data < 1 trading day old?
- [ ] **Position reconciliation**: run `reconcile()` against broker; local PDT lots match broker positions? Cash diff < $1?
- [ ] **Backup status**: run `python3 backup_state.py` after any config/risk change; verify latest backup has restrictive permissions and is not stale.
- [ ] **Disk / log cleanup**: check `logs/`, `orders/`, `alerts/`, `charts/` not growing out of control; cleanup if >80% disk or >30 days old.

## When to reach out immediately
- Trading halted, emergency liquidation, or repeated order rejection.
- Backtest metrics deviate >20% from baseline without code change.
- Paper/live process crash or heartbeat missing >1 expected interval.
- API key / .env / credential issue detected.
- Position reconciliation mismatch that cannot be explained by pending orders.

## When to stay quiet
- No new alerts, all tests green, and last check was <30 minutes ago.
- Late-night quiet hours with no urgent signals.

_If you update this checklist, run `python3 backup_state.py` so the runbook stays backed up._
