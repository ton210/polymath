# News-Signal Directional Pilot ("polymath bet")

**Date:** 2026-06-16
**Status:** Design approved, pending spec review

## 1. Overview

A second tool in the Polymath repo (reusing the existing ledger + report
infrastructure) that runs a **7-day forward paper pilot** of *directional*
betting on short-horizon Polymarket events. Unlike the arb scanner (hedged,
risk-free), this takes deliberate directional risk: each day it finds markets
resolving within ~48 hours, has Claude research each one via web search, estimates
a probability and logs the signals it used, then **diversely samples 5–10 paper
bets of $100 each** on the side it judges mispriced. After events resolve it
scores the bets, and after 7 days produces a calibration + signal-attribution
report.

It is **paper-only** — no wallet, no order placement — and **research-first**:
the goal of week 1 is to discover *whether and where* a signal-driven edge exists,
not to assume one.

## 2. The betting math this is built around (read first)

The single most important fact, stated so the tool never quietly chases a losing
target:

> **Break-even win rate = the price you pay.** Buying a contract at $0.71 (a "40%
> return if you win") requires winning **more than 71%** of such bets just to
> break even. Profit comes only from **edge** — your probability estimate being
> better-calibrated than the market price — never from the headline return number.

Per-bet PnL on a flat $100 stake at entry price `p` on the chosen side:
- Win: `+$100 · (1 − p) / p`
- Loss: `−$100`

So the report's headline metric is **calibration and win-rate-vs-entry-price**,
not raw return. A 2/3 win rate is excellent at avg price $0.50 and a loser at $0.80.

## 3. Goals & non-goals

**Goals (v1):**
- Stand up a daily select → research → paper-bet → settle → analyze loop.
- Log rich per-bet signal data so post-hoc analysis can find what predicts winners.
- Measure honestly: calibration, win-rate vs price, ROI, signal attribution.

**Non-goals (v1):**
- No real-money execution, no wallet.
- No paid social/news APIs — signal source is **LLM + web search only**.
- No claim of proven edge from one week (sample too small; the report says so).
- No automated daily scheduling — the operator runs `bet`/`settle` each day (a
  cron/loop wrapper is a trivial later add).

## 4. Strategy: research-first, diverse sampling

- **Edge thesis:** discovered empirically. We do not commit to one signal type;
  we log many signal features + an LLM estimate per bet and learn after the fact.
- **Selection:** diverse stratified sampling of the 5–10 daily bets across
  category (sports / politics / world-news), edge magnitude (including small
  edges), and dominant signal type — maximizing what we learn, knowingly
  sacrificing week-1 return versus a pure max-edge rule.
- **Direction:** bet the side (YES or NO) our estimate says is underpriced, flat
  $100, only when |our_prob − market_price| ≥ `min_edge` (default 0.10).

## 5. Components (each one purpose, testable in isolation)

New code lives under `src/polymath/signals/`; ledger + report are reused.

```
src/polymath/signals/
  nearterm.py     # select markets resolving within the window (Gamma)
  research.py     # Researcher protocol; ClaudeCliResearcher (claude CLI + web search); StubResearcher
  estimate.py     # Estimate dataclass: prob, confidence, category, signals{}, rationale, side
  select.py       # diverse stratified sampling of daily bets
  directional.py  # build flat-$100 directional bet rows for the ledger
  settle.py       # fetch resolved outcomes, compute directional PnL
  analyze.py      # calibration + win-vs-price + ROI + signal attribution
  cli.py          # bet / settle / analyze commands (registered on the main app)
```

Reused unchanged: `ledger.py` (JSONL), `clients/gamma.py` (markets + resolution),
`config.py` (new fields), and the `report` patterns.

### 5.1 nearterm.py
Query Gamma for active, order-accepting markets with `endDate` within
`max_hours` (default 48) and `liquidity ≥ min_liquidity`. Returns candidate
`Market`s. Caps candidate count (`max_candidates`, default 40) to bound research
cost, preferring the most liquid.

### 5.2 research.py + estimate.py
`Researcher` protocol: `research(market) -> Estimate`.
- `ClaudeCliResearcher`: shells out to the **local Claude Code CLI in headless
  mode** (`claude -p <prompt> --output-format json --allowedTools WebSearch`),
  which is already authenticated on the operator's machine — **no API key, no
  separate billing** (uses the existing Claude Code session/subscription). The
  prompt asks Claude to (a) web-search current state, (b) output a probability for
  the YES outcome, (c) a confidence 0–1, (d) a category, (e) a structured
  `signals` dict (e.g. `latest_news_age_hours`, `news_direction`,
  `consensus_strength`, `source_count`), and (f) a one-line rationale, returning a
  single strict JSON object. The CLI's JSON envelope is parsed, the embedded JSON
  estimate extracted and validated into an `Estimate`.
  - **Injectable runner:** `ClaudeCliResearcher(runner=...)` takes a
    `runner(cmd: list[str]) -> str` callable (default: `subprocess.run`), so the
    prompt-building and JSON-parsing logic is fully unit-testable with a fake
    runner returning canned CLI output — no real CLI in tests.
  - Configurable: `claude_cli_path` (default `claude`), `research_model` (passed
    as `--model`), `research_timeout`.
- `StubResearcher`: returns canned `Estimate`s for offline pipeline tests.

`Estimate.side`/edge are derived against the live market price by the caller.

### 5.3 select.py
Given scored candidates (each with edge = |prob − price| ≥ `min_edge`), pick up to
`bets_per_day` (default 8) maximizing diversity: round-robin across category, then
across edge-magnitude buckets, then signal type, so no single stratum dominates.
Deterministic given inputs (seedless; uses ordering, not RNG).

### 5.4 directional.py
For each selected bet, write a ledger row tagged `module="news_directional"`,
`profile=<active profile>`, with: timestamp, market id, side, entry_price,
our_prob, confidence, edge, category, signals{}, stake=$100, status="open",
and `realized_pnl=null` until settled.

### 5.5 settle.py
`polymath settle` re-fetches each open bet's market from Gamma; if resolved
(closed with a determined outcome), set status `won`/`lost` and compute
`realized_pnl` per §2. Unresolved bets stay `open`. Idempotent (re-runnable).

### 5.6 analyze.py
`polymath analyze` reads settled rows and reports:
- **Calibration:** bucket bets by our_prob (deciles); predicted vs actual win freq.
- **Win-rate vs entry-price:** observed win rate against the break-even price line.
- **ROI:** total and per-bet on the $100 stake; by category and by signal bucket.
- **Signal attribution:** for each logged signal feature, win rate / ROI split by
  feature value (e.g. high vs low `consensus_strength`) — what predicted winners.
- A blunt verdict + the honest caveat that N is too small to be conclusive.

## 6. Data flow

`bet` → nearterm → research each candidate → derive edge vs price → diverse-select
→ log $100 paper bets. (Operator repeats daily.) → `settle` (after events resolve)
→ score. → `analyze` → 7-day report.

## 7. Configuration (new `config.py` fields)

`bet_window_hours` (48), `bet_min_liquidity`, `max_candidates` (40),
`bets_per_day` (8), `bet_stake` (100.0), `min_edge` (0.10),
`claude_cli_path` (`claude`), `research_model` (passed as `--model`),
`research_timeout` (180s). Reuses `ledger_path`, `profiles`.

## 8. Error handling & cost control

- Research failures (CLI non-zero exit, timeout, or unparseable output) skip that
  candidate and log a warning; a run never aborts on one bad market.
- `max_candidates` bounds Claude-CLI invocations per `bet` run (~20–40); these use
  the existing Claude Code session, not separate API billing.
- Gamma calls reuse the existing retry/pagination-hardened client.
- `settle` tolerates markets that resolve late or ambiguously (left `open`).

## 9. Testing

- `StubResearcher` drives all selection/logging/settle/analyze tests — no CLI.
- `ClaudeCliResearcher` is unit-tested with a **fake runner** returning canned CLI
  output, verifying prompt construction and JSON parsing/validation — no real CLI.
- Unit-test: directional PnL math (§2), calibration bucketing, selection
  diversity (no stratum over-represented), settle idempotency and win/loss logic.
- Gamma near-term filter tested against recorded fixtures.
- A single live smoke test (manual, documented) confirms `ClaudeCliResearcher`
  returns a valid `Estimate` by invoking the real `claude` CLI once.

## 10. Honest caveats (surfaced in the report)

- Beating liquid 24–48h markets is hard; the pilot may simply show no edge — a
  valid, useful result.
- LLM probability estimates may be miscalibrated; that is measured, not assumed.
- 35–70 bets cannot distinguish skill from luck; treat week 1 as hypothesis
  generation, not proof.
- Diverse sampling deliberately includes weak-edge bets, lowering week-1 ROI.

## 11. Build order

1. `estimate` + `StubResearcher` + `nearterm` (fixture-tested) — candidate pipeline.
2. `directional` + ledger wiring + `polymath bet` (with stub) end-to-end.
3. `settle` + directional PnL.
4. `analyze` (calibration, win-vs-price, attribution).
5. `ClaudeCliResearcher` (local `claude` CLI + web search) behind the protocol,
   unit-tested via a fake runner; manual live smoke test.
6. Run the 7-day pilot.

## 12. Relationship to the rest of Polymath

Independent of the arb scanner and the deferred longshot / logical-RV detectors.
Shares only the ledger, Gamma client, config, and report conventions. The
`(module, profile)` ledger schema means `analyze` and the existing `report` can
coexist over one ledger without collision.
