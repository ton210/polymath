# Polymath — Polymarket Arbitrage & Relative-Value Scanner

**Date:** 2026-06-16
**Status:** Design approved, pending spec review

## 1. Overview

Polymath is a Python **command-line scanner** that finds short-term, hedged
opportunities on Polymarket. It is **detect-and-alert only**: it pulls live
market data, walks real order books, computes opportunities, and prints a ranked
table. It never holds wallet keys and never places orders — the user executes
manually.

A single `polymath scan` pulls one market+order-book snapshot and runs three
detector modules over it, all sharing one data-fetch and one depth-aware pricing
core.

## 2. Goals & non-goals

**Goals (v1):**
- Surface genuinely fillable, depth-aware opportunities, not top-of-book mirages.
- Rank by *realizable* value (what can be locked now vs held to resolution).
- Be honest about risk: clearly separate risk-free arbitrage from structural and
  directional bets.
- Record every signal so the edges can be validated before real capital scales in.

**Non-goals (v1):**
- No automated or semi-automated order placement (no wallet integration).
- No cross-venue comparison (Kalshi / sportsbooks) — that is the natural v2.
- No continuous daemon / push alerts — on-demand CLI only (clean upgrade later).
- No portfolio/position management or Kelly sizing — the per-opportunity max
  fillable size is the cap we report.

## 3. Strategy: three detector modules and their risk tiers

Output rows are tiered by risk and visually distinct so they are never confused:

| Badge | Tier | Meaning |
|-------|------|---------|
| 🔒 | Risk-free | True arbitrage; lockable now (or guaranteed at resolution). |
| 🟡 | Structural | Hedged by a logical constraint but with timing/convergence risk; **verify before trading**. |
| ⚠️ | Directional | Diversification-hedged only; real downside on any single bet. |

### Module 1 — Pure arbitrage (`detectors/pure_arb.py`) — 🔒
- **Binary YES+NO < $1:** within one market, buy matched YES + NO; merge to $1.
- **Neg-risk sum < $1:** across the N mutually-exclusive outcomes of an event,
  buy one YES of each; exactly one pays $1 (full set merges to $1).
- **Complementary bids > $1 (sell-side):** flagged informationally — requires
  holding or minting a set, so it is an FYI row, not an actionable buy.

### Module 2 — Logical / nested relative value (`detectors/logical_rv.py`) — 🟡
Detects semantically-linked markets whose prices violate a logical constraint
(e.g. `P(wins presidency) ≤ P(wins nomination)`; `P(by July) ≤ P(by December)`).
Relationship discovery is **tiered** (Section 7). Never badged 🔒 — an
LLM-inferred relationship can be wrong, so these always require human confirmation.

### Module 3 — Longshot-bias harvesting (`detectors/longshot.py`) — ⚠️ **UNVALIDATED**
Flags markets in a configurable extreme-price band (e.g. YES ≤ 5¢ or ≥ 95¢),
filtered by min volume/liquidity and a max-days-to-resolution window, ranked by a
simple expected-edge heuristic. **The "longshots are overpriced" bias is
documented for sportsbooks but unproven on Polymarket.** Every longshot row is
tagged `UNVALIDATED — backtest first`. The signal ledger (Section 9) is what will
eventually prove or kill this module.

## 4. Core concepts

- **Tokens & books:** each binary market has two ERC-1155 outcome tokens (YES, NO),
  each with its own CLOB order book.
- **Merge / realizability:** holding a complete complementary set (YES+NO of one
  market, or one of every neg-risk outcome) can be **merged back to $1 USDC
  immediately** via the conditional-tokens contract — no need to wait for
  resolution. Every opportunity carries a `realizability` field:
  - `instant-merge` — profit lockable now; capital recyclable.
  - `hold-to-resolution` — capital tied up until the market resolves.
  Ranking favors `instant-merge` because recyclable capital is worth far more than
  a larger edge locked for months.
- **Synthetic complementary pricing:** buying NO ≡ selling YES at `1 − price`.
  The effective best price for a leg is therefore
  `min(that token's best ask, 1 − the complement token's best bid)`, walked at
  depth. Ignoring this leaves fillable arbs invisible, so all pricing uses the
  combined synthetic book.

## 5. Architecture & components

Each unit has one purpose, a clear interface, and is testable in isolation.

```
polymath/
  clients/
    gamma.py     # active markets + event/neg-risk groupings (paginated)
    clob.py      # batch + async order-book fetch by token id
    llm.py       # thin Claude client for relationship classification
  model.py       # dataclasses: Market, Event, OrderBook, Level, Opportunity, Snapshot
  pricing.py     # synthetic complementary book + depth-aware ladder walk (pure)
  detectors/
    pure_arb.py  # 🔒  pure functions over a Snapshot
    logical_rv.py# 🟡  tiered relationship engine + LLM
    longshot.py  # ⚠️  extreme-price candidates
  relationships.py # candidate-pair gating, clustering, LLM cache
  ledger.py      # append-only JSONL signal log + replay/backtest
  scanner.py     # orchestrates: fetch -> snapshot -> run detectors -> collect
  config.py      # thresholds & settings
  cli.py         # typer entrypoint, rich table rendering
```

**Data flow:** `scan` → Gamma (active markets grouped into events) → liquidity
filter → CLOB async batch order-book fetch → build `Snapshot` (timestamped) →
run all three detectors over the snapshot → threshold filter → write to ledger →
rank → render.

## 6. Edge math (`pricing.py`, pure, the risky core)

To stay hedged we buy equal quantity on every leg. We build each leg's effective
ask ladder using synthetic complementary pricing (Section 4), then walk all legs
together by cumulative size:

- Add the next matched "set" (one share of each leg) while its **marginal cost**
  (sum of each leg's price at the current cumulative depth) stays below
  `payout − threshold`, where `payout = $1`.
- The binding constraint is the thinnest leg's available depth.
- Subtract configurable costs: `fee_bps` (default 0 — Polymarket CLOB currently
  charges no trading fee) and `gas_per_redeem`.

**Per-opportunity output:** optimal fillable size `Q`, total cost, **net profit
$**, **ROI %**, `realizability`, and per-leg "buy X of <market> at ≤ <price>".

## 7. Logical-RV relationship discovery (`relationships.py`)

**Tier 0 — free:** use Polymarket's own neg-risk/event groupings as
mutual-exclusivity constraints. No LLM.

**Tier 1 — LLM, gated and cached:**
1. **Gate (avoid the n² bomb):** only consider market pairs that share an event/tag;
   cluster by detected subject/entity; within a cluster, pre-filter pairs by cheap
   signals (shared entities, embedding similarity, parsed dates) before any LLM
   call. Cap pairs classified per scan (`max_llm_pairs`).
2. **Classify:** Claude labels each surviving pair as
   `subset | temporal-nested | mutually-exclusive | none` and emits the implied
   price inequality. Default `llm_model` is a fast/cheap Claude model
   (`claude-haiku-4-5`), with optional escalation to Sonnet for low-confidence pairs.
3. **Cache:** verdicts are stored on disk keyed by the normalized question pair.
   Relationships are stable, so each pair is classified once; repeat scans are
   near-zero cost.
4. **Check:** if live prices violate the inequality beyond `min_roi`, emit a 🟡
   opportunity with a depth-aware hedge (buy the underpriced leg, sell/offset the
   overpriced one). Always requires human confirmation; never 🔒.

`--no-llm` runs Tier-0 only (free, deterministic).

## 8. Longshot module (`detectors/longshot.py`)

Config-driven band + filters; ranked candidates only. Always ⚠️ and tagged
`UNVALIDATED`. No live edge is asserted until the ledger replay (Section 9) shows
a measured bias on resolved markets. Until then it exists to *collect data*, and
the user may act on it at their own stated risk.

## 9. Signal ledger & replay (`ledger.py`)

Non-optional. Every emitted opportunity is appended to a JSONL ledger with:
snapshot timestamp, module, markets/tokens, prices, computed edge, fillable size,
realizability. A `polymath replay` command later re-fetches outcomes for logged
signals and reports: did logical-RV pairs converge? did faded longshots actually
lose less than priced? what was realized vs predicted edge? This is how the tool
earns the right to trust modules 2 and 3 before scaling capital.

## 10. Output & CLI

Single ranked `rich` table, color-coded by risk badge (🔒/🟡/⚠️) and module.
Columns: badge, structure, markets, action (what/how-much to buy), fillable $,
net profit $, ROI %, realizability, days-to-resolve, snapshot age.

Commands & flags:
- `polymath scan` — main scan.
  - `--only pure_arb|logical|longshot`, `--min-roi`, `--min-profit`,
    `--max-days`, `--category`, `--json`, `--no-llm`, `--explain`.
  - `--explain` shows why candidates were filtered (e.g. "edge 1.2% but only $14
    fillable < min_profit").
- `polymath replay` — backtest logged signals against resolved outcomes.

Before rendering, an opportunity's books are **re-fetched** to confirm it is still
live; snapshot age is shown so the user never acts on a stale mirage.

## 11. Configuration (`config.py`)

`min_roi`, `min_profit_usd`, `fee_bps` (default 0), `gas_per_redeem`,
liquidity/volume filters, `longshot_band`, `max_days_to_resolution`,
`llm_model` (default `claude-haiku-4-5`), `max_llm_pairs`, `llm_cache_path`,
`ledger_path`. Loaded from a config file with CLI-flag overrides.

## 12. Error handling, rate limits, freshness

- Retry with backoff on API errors; throttle to respect Gamma/CLOB rate limits;
  prefer batch + async book fetching so a full scan is seconds, not minutes.
- Skip any market with incomplete/stale book data rather than emit a bad signal.
- Exclude markets not currently accepting orders.
- Every `Snapshot` is timestamped; opportunity age is shown and re-validated at
  render time.

## 13. Testing strategy

- **TDD the math:** `pricing.py` and each detector are pure functions tested with
  hand-built snapshots (incl. synthetic-pricing and depth-binding edge cases).
- **Clients:** tested against recorded JSON fixtures so the suite runs offline.
- **LLM classifier:** tested with a stubbed client returning canned verdicts — no
  live API in tests; cache behavior tested explicitly.
- **Ledger/replay:** tested with synthetic logged signals + fixture outcomes.
- **Scanner:** integration-tested with mocked clients.

## 14. Build order (phased to de-risk)

1. Core: `model`, `clients` (gamma+clob, async), `pricing` (synthetic + depth
   walk), `scanner`, `cli` skeleton, **ledger**. Wire up **Module 1 (pure arb)**
   end-to-end — a tight, trustworthy, fully risk-free tool.
2. **Module 3 (longshot)** — cheap, price-only; starts filling the ledger
   immediately (data-collection value even while unvalidated).
3. **Module 2 (logical RV)** — relationships engine, LLM gating/cache, 🟡 output.
4. `polymath replay` backtest; use it to validate modules 2 & 3.

## 15. Honest caveats

- Pure arbs are rare and small; depth-aware sizing tells you if an edge is worth
  $3 or $300. The other modules are where larger edges *might* live — unproven
  until the ledger says otherwise.
- An on-demand CLI snapshot can be seconds stale by the time you click buy
  (re-validation at render time mitigates, doesn't eliminate). The daemon + push
  version is the real fix once an edge proves out.
- Logical-RV hedges depend on the LLM relationship being correct — a wrong label
  turns a "hedge" into a directional loss. Hence 🟡 + mandatory human confirm.

## 16. v2 / open questions

- Cross-venue arbitrage (Polymarket vs Kalshi/sportsbooks): biggest, most
  persistent edge; adds second-venue data + contract-matching + resolution-basis
  risk.
- Semi-auto / auto execution (wallet integration, partial-fill handling, kill
  switches).
- Continuous daemon + Slack/desktop push alerts.
- Liquidity provision + Polymarket maker-rewards (needs execution; different
  project shape, best risk-adjusted edge).
