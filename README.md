# Polymath

Depth-aware Polymarket arbitrage scanner with a paper-trading harness.

## Install
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```

## Use
```bash
polymath scan                          # one-shot ranked opportunities
polymath scan --record                 # also paper-trade into the ledger
polymath watch --interval 300          # unattended capture loop (the week-long dry run)
polymath report --min-entered 5        # per-(module, profile) scorecard
```

Configure thresholds and profiles in a TOML file passed via `--config`. See
`docs/superpowers/specs/2026-06-16-polymath-arbitrage-scanner-design.md` for the
design and `docs/superpowers/plans/` for the build plan.

## Risk badges
- 🔒 risk-free arbitrage (this release)
- 🟡 structural / logical-RV (follow-on)
- ⚠️ directional / longshot (follow-on)

This tool **detects and records only** — it never holds keys or places orders.
