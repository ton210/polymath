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

## Directional news pilot (paper)

```bash
polymath bet                 # research near-term markets, log 5-10 paper bets
polymath settle              # score resolved bets
polymath analyze             # calibration + ROI + signal attribution
```

Directional, paper-only, research-driven via the local Claude Code CLI (no API
key). Break-even win rate equals the price you pay — profit comes from edge, not
from the headline return. A 7-day, 35-70 bet run is hypothesis generation, not
proof of edge. See `docs/superpowers/specs/2026-06-16-news-signal-directional-pilot-design.md`.

## Risk badges
- 🔒 risk-free arbitrage (this release)
- 🟡 structural / logical-RV (follow-on)
- ⚠️ directional / longshot (follow-on)

This tool **detects and records only** — it never holds keys or places orders.
