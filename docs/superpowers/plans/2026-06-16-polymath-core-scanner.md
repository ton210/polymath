# Polymath Core Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a trustworthy, depth-aware Polymarket pure-arbitrage scanner that paper-trades its own signals and scores them per experiment, as the stable core that the longshot and logical-RV detectors will later plug into.

**Architecture:** A Python CLI fetches active markets (Gamma API) and full order books (CLOB API) into one timestamped `Snapshot`, runs pure-arbitrage detectors over depth-aware *synthetic* order books, and feeds qualifying opportunities into a capital-aware paper-trading harness whose append-only ledger is summarized by a per-`(module, profile)` scorecard. All math lives in pure, unit-tested functions; all I/O lives in thin clients tested against recorded fixtures.

**Tech Stack:** Python 3.11+, `httpx` (async HTTP), `typer` (CLI), `rich` (tables), `pytest` + `pytest-asyncio` + `respx` (tests), `pyproject.toml` (hatchling).

**Scope note:** This plan delivers spec build-order phases 1–2 (foundational core + Module 1 pure arb + paper harness + `scan`/`watch`/`report`). The longshot (Module 3) and logical-RV (Module 2) detectors are deliberately deferred to follow-on plans; they add new files under `detectors/` and reuse this core unchanged. Spec: `docs/superpowers/specs/2026-06-16-polymath-arbitrage-scanner-design.md`.

---

## File Structure

```
pyproject.toml                      # project + deps
src/polymath/__init__.py
src/polymath/model.py               # dataclasses: Level, OrderBook, Token, Market, Event, Snapshot, Leg, Opportunity
src/polymath/pricing.py             # synthetic ask ladders + depth-aware matched-set walk (PURE)
src/polymath/config.py              # Config + Profile, load from TOML, defaults
src/polymath/clients/__init__.py
src/polymath/clients/gamma.py       # GammaClient: active markets -> Market[]
src/polymath/clients/clob.py        # ClobClient: token_ids -> {token_id: OrderBook}
src/polymath/detectors/__init__.py
src/polymath/detectors/pure_arb.py  # binary / neg-risk / sell-set detectors (PURE over Snapshot)
src/polymath/scanner.py             # build_snapshot (async) + run_detectors
src/polymath/ledger.py              # append-only JSONL Ledger
src/polymath/paper.py               # PaperBook: sizing, dedup, capital, PnL
src/polymath/report.py              # scorecard aggregation
src/polymath/cli.py                 # typer app: scan / watch / report
tests/...                           # mirror of the above
```

---

### Task 0: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/polymath/__init__.py`
- Create: `src/polymath/clients/__init__.py`
- Create: `src/polymath/detectors/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "polymath"
version = "0.1.0"
description = "Depth-aware Polymarket arbitrage scanner with paper-trading harness"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "typer>=0.12",
    "rich>=13.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
]

[project.scripts]
polymath = "polymath.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/polymath"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package + test init files**

Create `src/polymath/__init__.py`, `src/polymath/clients/__init__.py`, `src/polymath/detectors/__init__.py`, `tests/__init__.py` each containing a single comment line:

```python
# polymath
```

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
```

- [ ] **Step 3: Create the venv and install**

Run:
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```
Expected: ends with `Successfully installed ... polymath-0.1.0 ...`

- [ ] **Step 4: Verify pytest collects nothing yet (no error)**

Run: `. .venv/bin/activate && pytest -q`
Expected: `no tests ran` (exit code 5) — confirms config is valid.

- [ ] **Step 5: Commit**

```bash
printf '.venv/\n__pycache__/\n*.pyc\n.pytest_cache/\nledger.jsonl\nllm_cache.json\n' > .gitignore
git add pyproject.toml src tests .gitignore
git commit -m "chore: scaffold polymath package and test config"
```

---

### Task 1: Data model

**Files:**
- Create: `src/polymath/model.py`
- Test: `tests/test_model.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.model import Level, OrderBook, Token, Market


def test_orderbook_best_prices_and_sorting():
    book = OrderBook(
        token_id="t1",
        bids=[Level(0.40, 100), Level(0.42, 50)],   # unsorted on purpose
        asks=[Level(0.45, 80), Level(0.44, 30)],
    )
    book = book.normalized()
    assert book.best_bid().price == 0.42   # bids: highest first
    assert book.best_ask().price == 0.44   # asks: lowest first
    assert book.bids[0].price >= book.bids[1].price
    assert book.asks[0].price <= book.asks[1].price


def test_market_yes_no_token_lookup():
    m = Market(
        condition_id="c1",
        question="Will X happen?",
        slug="x",
        tokens=[Token("yes_tok", "Yes"), Token("no_tok", "No")],
        neg_risk=False,
        neg_risk_market_id=None,
        accepting_orders=True,
        end_date=None,
        liquidity=1000.0,
        volume=5000.0,
    )
    assert m.token_for("Yes").token_id == "yes_tok"
    assert m.complement_of("yes_tok").token_id == "no_tok"
    assert m.is_binary()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.model'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass
class OrderBook:
    token_id: str
    bids: list[Level] = field(default_factory=list)  # highest price first
    asks: list[Level] = field(default_factory=list)  # lowest price first

    def normalized(self) -> "OrderBook":
        return OrderBook(
            token_id=self.token_id,
            bids=sorted(self.bids, key=lambda l: l.price, reverse=True),
            asks=sorted(self.asks, key=lambda l: l.price),
        )

    def best_bid(self) -> Level | None:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> Level | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class Token:
    token_id: str
    outcome: str


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    tokens: list[Token]
    neg_risk: bool
    neg_risk_market_id: str | None
    accepting_orders: bool
    end_date: datetime | None
    liquidity: float
    volume: float

    def is_binary(self) -> bool:
        return len(self.tokens) == 2

    def token_for(self, outcome: str) -> Token:
        for t in self.tokens:
            if t.outcome.lower() == outcome.lower():
                return t
        raise KeyError(outcome)

    def complement_of(self, token_id: str) -> Token:
        if not self.is_binary():
            raise ValueError("complement only defined for binary markets")
        for t in self.tokens:
            if t.token_id != token_id:
                return t
        raise KeyError(token_id)


@dataclass
class Event:
    id: str
    title: str
    neg_risk: bool
    market_condition_ids: list[str]


@dataclass
class Snapshot:
    timestamp: datetime
    markets: dict[str, Market]            # condition_id -> Market
    books: dict[str, OrderBook]           # token_id -> OrderBook
    events: dict[str, Event]              # event id -> Event


@dataclass(frozen=True)
class Leg:
    token_id: str
    outcome: str
    side: str                             # "buy" | "sell"
    limit_price: float
    market_id: str


@dataclass
class Opportunity:
    module: str                           # "pure_arb"
    profile: str
    kind: str                             # "binary_yes_no" | "neg_risk_set" | "sell_set"
    market_ids: list[str]
    legs: list[Leg]
    fillable_size: float
    cost: float
    net_profit: float
    roi: float
    realizability: str                    # "instant-merge" | "hold-to-resolution"
    risk_tier: str                        # "risk-free" | "structural" | "directional"
    end_date: datetime | None
    explain: str

    def dedup_key(self) -> str:
        return f"{self.module}:{self.kind}:" + ",".join(sorted(self.market_ids))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_model.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/model.py tests/test_model.py
git commit -m "feat: add core data model dataclasses"
```

---

### Task 2: Depth-aware pricing core

This is the riskiest math — test it hard. Two pieces: building a leg's *effective* ask ladder (direct asks plus synthetic asks from the complement's bids), and walking equal-quantity matched sets while marginal cost stays below payout.

**Files:**
- Create: `src/polymath/pricing.py`
- Test: `tests/test_pricing.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.model import Level, OrderBook
from polymath.pricing import effective_ask_ladder, walk_matched_sets


def test_effective_ask_ladder_merges_synthetic_from_complement_bids():
    # Direct asks for buying X.
    own = OrderBook("X", asks=[Level(0.60, 10)]).normalized()
    # Complement Y has a bid at 0.50 for 5 -> selling Y at 0.50 == buying X at 0.50.
    comp = OrderBook("Y", bids=[Level(0.50, 5)]).normalized()
    ladder = effective_ask_ladder(own, comp)
    # Cheapest first: synthetic 0.50 (size 5), then direct 0.60 (size 10).
    assert (round(ladder[0].price, 4), ladder[0].size) == (0.50, 5)
    assert (round(ladder[1].price, 4), ladder[1].size) == (0.60, 10)


def test_walk_matched_sets_two_legs_stops_at_payout():
    # Leg A asks: 0.40 x100. Leg B asks: 0.55 x100 then 0.70 x100.
    a = [Level(0.40, 100)]
    b = [Level(0.55, 100), Level(0.70, 100)]
    size, cost = walk_matched_sets([a, b], payout=1.0)
    # First 100 sets: marginal 0.40+0.55=0.95 < 1.0 -> taken.
    # Next sets: marginal 0.40+0.70=1.10 >= 1.0 -> stop.
    assert size == 100
    assert round(cost, 4) == round(100 * 0.40 + 100 * 0.55, 4)


def test_walk_matched_sets_no_profitable_depth():
    a = [Level(0.60, 50)]
    b = [Level(0.55, 50)]   # marginal 1.15 >= 1.0
    size, cost = walk_matched_sets([a, b], payout=1.0)
    assert size == 0
    assert cost == 0.0


def test_walk_matched_sets_binding_thin_leg():
    # Leg A only has 20 of depth; leg B has 100. Matched size capped at 20.
    a = [Level(0.30, 20)]
    b = [Level(0.40, 100)]
    size, cost = walk_matched_sets([a, b], payout=1.0)
    assert size == 20
    assert round(cost, 4) == round(20 * 0.30 + 20 * 0.40, 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pricing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.pricing'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from polymath.model import Level, OrderBook

_EPS = 1e-9


def effective_ask_ladder(own: OrderBook, complement: OrderBook | None) -> list[Level]:
    """Ascending price ladder for BUYING this outcome.

    Combines the outcome's own asks with synthetic asks created by selling the
    complement token into its bids: a complement bid at price q (size s) lets us
    acquire this outcome at price (1 - q) for size s.
    """
    levels = list(own.asks)
    if complement is not None:
        for bid in complement.bids:
            levels.append(Level(round(1.0 - bid.price, 10), bid.size))
    return sorted(levels, key=lambda l: l.price)


def walk_matched_sets(
    leg_ladders: list[list[Level]], payout: float = 1.0
) -> tuple[float, float]:
    """Buy equal quantity across every leg while the marginal cost of the next
    matched set (sum of each leg's current price) stays below ``payout``.

    Returns (total_size, total_cost). Ladders must be ascending by price.
    """
    if any(len(l) == 0 for l in leg_ladders):
        return 0.0, 0.0

    idx = [0] * len(leg_ladders)
    rem = [ladder[0].size for ladder in leg_ladders]
    total_size = 0.0
    total_cost = 0.0

    while all(idx[i] < len(leg_ladders[i]) for i in range(len(leg_ladders))):
        marginal = sum(leg_ladders[i][idx[i]].price for i in range(len(leg_ladders)))
        if marginal >= payout - _EPS:
            break
        step = min(rem)
        total_size += step
        for i in range(len(leg_ladders)):
            total_cost += leg_ladders[i][idx[i]].price * step
            rem[i] -= step
            if rem[i] <= _EPS:
                idx[i] += 1
                if idx[i] < len(leg_ladders[i]):
                    rem[i] = leg_ladders[i][idx[i]].size
    return total_size, total_cost
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pricing.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/pricing.py tests/test_pricing.py
git commit -m "feat: add synthetic ask ladder and depth-aware matched-set walk"
```

---

### Task 3: Pure-arbitrage detectors

**Files:**
- Create: `src/polymath/detectors/pure_arb.py`
- Test: `tests/test_pure_arb.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

from polymath.model import Level, OrderBook, Token, Market, Event, Snapshot
from polymath.detectors.pure_arb import detect


def _binary_market(cid, yes_tok, no_tok, neg_risk=False, nrm=None):
    return Market(
        condition_id=cid, question=f"Q {cid}", slug=cid,
        tokens=[Token(yes_tok, "Yes"), Token(no_tok, "No")],
        neg_risk=neg_risk, neg_risk_market_id=nrm,
        accepting_orders=True, end_date=None, liquidity=9999.0, volume=9999.0,
    )


def _snap(markets, books, events=None):
    return Snapshot(
        timestamp=datetime.now(timezone.utc),
        markets={m.condition_id: m for m in markets},
        books={b.token_id: b for b in books},
        events=events or {},
    )


def test_detects_binary_yes_no_under_one():
    m = _binary_market("c1", "yes", "no")
    snap = _snap(
        [m],
        [OrderBook("yes", asks=[Level(0.45, 100)]),
         OrderBook("no", asks=[Level(0.50, 100)])],
    )
    opps = detect(snap, min_roi=0.0, min_profit_usd=0.0, fee_bps=0.0, profile="default")
    binary = [o for o in opps if o.kind == "binary_yes_no"]
    assert len(binary) == 1
    o = binary[0]
    assert o.fillable_size == 100
    assert round(o.cost, 2) == 95.0
    assert round(o.net_profit, 2) == 5.0   # 100 payout - 95 cost
    assert o.realizability == "instant-merge"
    assert o.risk_tier == "risk-free"


def test_no_binary_opportunity_when_sum_over_one():
    m = _binary_market("c1", "yes", "no")
    snap = _snap(
        [m],
        [OrderBook("yes", asks=[Level(0.55, 100)]),
         OrderBook("no", asks=[Level(0.55, 100)])],
    )
    opps = detect(snap, min_roi=0.0, min_profit_usd=0.0, fee_bps=0.0, profile="default")
    assert [o for o in opps if o.kind == "binary_yes_no"] == []


def test_min_profit_threshold_filters_small_edges():
    m = _binary_market("c1", "yes", "no")
    snap = _snap(
        [m],
        [OrderBook("yes", asks=[Level(0.49, 10)]),
         OrderBook("no", asks=[Level(0.50, 10)])],   # profit = 10 * 0.01 = 0.10
    )
    opps = detect(snap, min_roi=0.0, min_profit_usd=1.0, fee_bps=0.0, profile="default")
    assert [o for o in opps if o.kind == "binary_yes_no"] == []


def test_detects_neg_risk_set_under_one():
    m1 = _binary_market("c1", "y1", "n1", neg_risk=True, nrm="E")
    m2 = _binary_market("c2", "y2", "n2", neg_risk=True, nrm="E")
    m3 = _binary_market("c3", "y3", "n3", neg_risk=True, nrm="E")
    event = Event(id="E", title="race", neg_risk=True,
                  market_condition_ids=["c1", "c2", "c3"])
    snap = _snap(
        [m1, m2, m3],
        [OrderBook("y1", asks=[Level(0.30, 100)]),
         OrderBook("y2", asks=[Level(0.30, 100)]),
         OrderBook("y3", asks=[Level(0.30, 100)]),
         OrderBook("n1"), OrderBook("n2"), OrderBook("n3")],
        events={"E": event},
    )
    opps = detect(snap, min_roi=0.0, min_profit_usd=0.0, fee_bps=0.0, profile="default")
    neg = [o for o in opps if o.kind == "neg_risk_set"]
    assert len(neg) == 1
    assert neg[0].fillable_size == 100
    assert round(neg[0].net_profit, 2) == 10.0   # 100 - 3*0.30*100
    assert neg[0].risk_tier == "risk-free"


def test_flags_binary_sell_set_over_one():
    m = _binary_market("c1", "yes", "no")
    snap = _snap(
        [m],
        [OrderBook("yes", bids=[Level(0.60, 100)]),
         OrderBook("no", bids=[Level(0.55, 100)])],   # bids sum 1.15 > 1
    )
    opps = detect(snap, min_roi=0.0, min_profit_usd=0.0, fee_bps=0.0, profile="default")
    sells = [o for o in opps if o.kind == "sell_set"]
    assert len(sells) == 1
    assert sells[0].legs[0].side == "sell"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pure_arb.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.detectors.pure_arb'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from polymath.model import Leg, Market, OrderBook, Opportunity, Snapshot
from polymath.pricing import effective_ask_ladder, walk_matched_sets

_EMPTY = OrderBook("__empty__")


def _book(snap: Snapshot, token_id: str) -> OrderBook:
    return snap.books.get(token_id, OrderBook(token_id))


def _finalize(size, cost, fee_bps, payout_per_set):
    gross = size * payout_per_set
    fees = cost * (fee_bps / 10_000.0)
    net = gross - cost - fees
    roi = (net / cost) if cost > 0 else 0.0
    return net, roi


def _binary(snap, m: Market, min_roi, min_profit_usd, fee_bps, profile):
    yes, no = m.tokens[0], m.tokens[1]
    yes_book, no_book = _book(snap, yes.token_id), _book(snap, no.token_id)
    yes_ladder = effective_ask_ladder(yes_book, no_book)
    no_ladder = effective_ask_ladder(no_book, yes_book)
    size, cost = walk_matched_sets([yes_ladder, no_ladder], payout=1.0)
    if size <= 0:
        return None
    net, roi = _finalize(size, cost, fee_bps, 1.0)
    if net < min_profit_usd or roi < min_roi:
        return None
    return Opportunity(
        module="pure_arb", profile=profile, kind="binary_yes_no",
        market_ids=[m.condition_id],
        legs=[
            Leg(yes.token_id, "Yes", "buy", yes_ladder[0].price, m.condition_id),
            Leg(no.token_id, "No", "buy", no_ladder[0].price, m.condition_id),
        ],
        fillable_size=size, cost=cost, net_profit=net, roi=roi,
        realizability="instant-merge", risk_tier="risk-free",
        end_date=m.end_date,
        explain=f"buy {size:g} YES+NO @ blended {cost/size:.4f}, redeem $1/set",
    )


def _neg_risk(snap, event, min_roi, min_profit_usd, fee_bps, profile):
    members = [snap.markets[c] for c in event.market_condition_ids if c in snap.markets]
    if len(members) < 2:
        return None
    ladders, legs = [], []
    for m in members:
        yes, no = m.tokens[0], m.tokens[1]
        ladder = effective_ask_ladder(_book(snap, yes.token_id), _book(snap, no.token_id))
        if not ladder:
            return None
        ladders.append(ladder)
        legs.append(Leg(yes.token_id, "Yes", "buy", ladder[0].price, m.condition_id))
    size, cost = walk_matched_sets(ladders, payout=1.0)
    if size <= 0:
        return None
    net, roi = _finalize(size, cost, fee_bps, 1.0)
    if net < min_profit_usd or roi < min_roi:
        return None
    return Opportunity(
        module="pure_arb", profile=profile, kind="neg_risk_set",
        market_ids=[m.condition_id for m in members], legs=legs,
        fillable_size=size, cost=cost, net_profit=net, roi=roi,
        realizability="instant-merge", risk_tier="risk-free",
        end_date=min((m.end_date for m in members if m.end_date), default=None),
        explain=f"buy 1 YES of each of {len(members)} outcomes, sum<$1",
    )


def _binary_sell(snap, m: Market, profile):
    yes, no = m.tokens[0], m.tokens[1]
    yb, nb = _book(snap, yes.token_id).best_bid(), _book(snap, no.token_id).best_bid()
    if yb is None or nb is None or (yb.price + nb.price) <= 1.0:
        return None
    size = min(yb.size, nb.size)
    proceeds = size * (yb.price + nb.price)
    net = proceeds - size  # cost to mint a set is $1/set
    return Opportunity(
        module="pure_arb", profile=profile, kind="sell_set",
        market_ids=[m.condition_id],
        legs=[
            Leg(yes.token_id, "Yes", "sell", yb.price, m.condition_id),
            Leg(no.token_id, "No", "sell", nb.price, m.condition_id),
        ],
        fillable_size=size, cost=size, net_profit=net,
        roi=(net / size if size else 0.0),
        realizability="hold-to-resolution", risk_tier="risk-free",
        end_date=m.end_date,
        explain=f"sell a minted set for {yb.price + nb.price:.4f} (>$1, FYI: needs mint/hold)",
    )


def detect(snap: Snapshot, *, min_roi: float, min_profit_usd: float,
           fee_bps: float, profile: str) -> list[Opportunity]:
    out: list[Opportunity] = []
    for m in snap.markets.values():
        if not m.accepting_orders or not m.is_binary():
            continue
        b = _binary(snap, m, min_roi, min_profit_usd, fee_bps, profile)
        if b:
            out.append(b)
        s = _binary_sell(snap, m, profile)
        if s:
            out.append(s)
    for event in snap.events.values():
        if event.neg_risk:
            n = _neg_risk(snap, event, min_roi, min_profit_usd, fee_bps, profile)
            if n:
                out.append(n)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pure_arb.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/detectors/pure_arb.py tests/test_pure_arb.py
git commit -m "feat: add pure-arb detectors (binary, neg-risk, sell-set)"
```

---

### Task 4: Configuration

**Files:**
- Create: `src/polymath/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.config import Config, default_config, load_config


def test_default_config_has_sane_values():
    c = default_config()
    assert c.min_roi >= 0.0
    assert c.fee_bps == 0.0
    assert c.bankroll == 10_000.0
    assert "default" in c.profiles


def test_profile_overrides_thresholds():
    c = default_config()
    c.profiles["roi-2pct"] = {"min_roi": 0.02}
    eff = c.effective("roi-2pct")
    assert eff.min_roi == 0.02
    assert eff.fee_bps == c.fee_bps   # untouched fields inherit base


def test_load_config_from_toml(tmp_path):
    p = tmp_path / "polymath.toml"
    p.write_text(
        "min_roi = 0.01\nbankroll = 5000\n\n[profiles.aggressive]\nmin_roi = 0.005\n"
    )
    c = load_config(p)
    assert c.min_roi == 0.01
    assert c.bankroll == 5000
    assert c.effective("aggressive").min_roi == 0.005
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.config'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass
class Config:
    min_roi: float = 0.0
    min_profit_usd: float = 1.0
    fee_bps: float = 0.0
    gas_per_redeem: float = 0.0
    min_liquidity: float = 500.0
    min_volume: float = 0.0
    bankroll: float = 10_000.0
    max_position_pct: float = 0.10
    assumed_slippage: float = 0.0
    watch_interval_seconds: int = 300
    ledger_path: str = "ledger.jsonl"
    gamma_base: str = "https://gamma-api.polymarket.com"
    clob_base: str = "https://clob.polymarket.com"
    profiles: dict[str, dict] = field(default_factory=lambda: {"default": {}})

    def effective(self, profile: str) -> "Config":
        overrides = self.profiles.get(profile, {})
        valid = {k: v for k, v in overrides.items() if k in self.__dataclass_fields__}
        return replace(self, **valid)


def default_config() -> Config:
    return Config()


def load_config(path: str | Path) -> Config:
    data = tomllib.loads(Path(path).read_text())
    profiles = data.pop("profiles", {}) or {}
    profiles.setdefault("default", {})
    fields = Config.__dataclass_fields__
    valid = {k: v for k, v in data.items() if k in fields}
    return Config(profiles=profiles, **valid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/config.py tests/test_config.py
git commit -m "feat: add config with named threshold profiles"
```

---

### Task 5: Gamma client

**Files:**
- Create: `src/polymath/clients/gamma.py`
- Test: `tests/test_gamma_client.py`
- Create: `tests/fixtures/gamma_markets_page1.json`
- Create: `tests/fixtures/gamma_markets_empty.json`

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/gamma_markets_page1.json`:
```json
[
  {
    "conditionId": "c1",
    "question": "Will X win?",
    "slug": "will-x-win",
    "clobTokenIds": "[\"yes1\", \"no1\"]",
    "outcomes": "[\"Yes\", \"No\"]",
    "active": true,
    "closed": false,
    "acceptingOrders": true,
    "negRisk": true,
    "negRiskMarketID": "E1",
    "liquidityNum": 12000,
    "volumeNum": 50000,
    "endDate": "2026-11-03T00:00:00Z"
  },
  {
    "conditionId": "c2",
    "question": "Will Y win?",
    "slug": "will-y-win",
    "clobTokenIds": "[\"yes2\", \"no2\"]",
    "outcomes": "[\"Yes\", \"No\"]",
    "active": true,
    "closed": false,
    "acceptingOrders": true,
    "negRisk": true,
    "negRiskMarketID": "E1",
    "liquidityNum": 8000,
    "volumeNum": 30000,
    "endDate": "2026-11-03T00:00:00Z"
  }
]
```

`tests/fixtures/gamma_markets_empty.json`:
```json
[]
```

- [ ] **Step 2: Write the failing test**

```python
import json
from pathlib import Path

import httpx
import respx

from polymath.clients.gamma import GammaClient

FIX = Path(__file__).parent / "fixtures"


@respx.mock
async def test_fetch_active_markets_paginates_and_parses():
    page1 = json.loads((FIX / "gamma_markets_page1.json").read_text())
    empty = json.loads((FIX / "gamma_markets_empty.json").read_text())
    route = respx.get("https://gamma-api.polymarket.com/markets")
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=empty),
    ]

    async with GammaClient("https://gamma-api.polymarket.com") as client:
        markets = await client.fetch_active_markets(min_liquidity=0, min_volume=0)

    assert {m.condition_id for m in markets} == {"c1", "c2"}
    m = markets[0]
    assert [t.token_id for t in m.tokens] == ["yes1", "no1"]
    assert [t.outcome for t in m.tokens] == ["Yes", "No"]
    assert m.neg_risk is True
    assert m.neg_risk_market_id == "E1"
    assert m.liquidity == 12000


@respx.mock
async def test_fetch_active_markets_filters_low_liquidity():
    page1 = json.loads((FIX / "gamma_markets_page1.json").read_text())
    empty = json.loads((FIX / "gamma_markets_empty.json").read_text())
    respx.get("https://gamma-api.polymarket.com/markets").side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=empty),
    ]
    async with GammaClient("https://gamma-api.polymarket.com") as client:
        markets = await client.fetch_active_markets(min_liquidity=10000, min_volume=0)
    assert {m.condition_id for m in markets} == {"c1"}   # c2 has 8000 < 10000
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_gamma_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.clients.gamma'`

- [ ] **Step 4: Write minimal implementation**

```python
from __future__ import annotations

import json
from datetime import datetime

import httpx

from polymath.model import Market, Token

_PAGE = 500


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_market(raw: dict) -> Market | None:
    try:
        token_ids = json.loads(raw["clobTokenIds"])
        outcomes = json.loads(raw["outcomes"])
    except (KeyError, json.JSONDecodeError, TypeError):
        return None
    if len(token_ids) != len(outcomes) or len(token_ids) < 2:
        return None
    tokens = [Token(str(tid), str(o)) for tid, o in zip(token_ids, outcomes)]
    return Market(
        condition_id=str(raw.get("conditionId")),
        question=raw.get("question", ""),
        slug=raw.get("slug", ""),
        tokens=tokens,
        neg_risk=bool(raw.get("negRisk", False)),
        neg_risk_market_id=raw.get("negRiskMarketID"),
        accepting_orders=bool(raw.get("acceptingOrders", False)),
        end_date=_parse_dt(raw.get("endDate")),
        liquidity=float(raw.get("liquidityNum") or 0.0),
        volume=float(raw.get("volumeNum") or 0.0),
    )


class GammaClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def __aenter__(self) -> "GammaClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def fetch_active_markets(
        self, *, min_liquidity: float, min_volume: float
    ) -> list[Market]:
        markets: list[Market] = []
        offset = 0
        while True:
            resp = await self._client.get(
                "/markets",
                params={"active": "true", "closed": "false",
                        "limit": _PAGE, "offset": offset},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for raw in batch:
                m = _parse_market(raw)
                if m is None:
                    continue
                if m.liquidity < min_liquidity or m.volume < min_volume:
                    continue
                markets.append(m)
            offset += _PAGE
        return markets
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_gamma_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/polymath/clients/gamma.py tests/test_gamma_client.py tests/fixtures/gamma_markets_page1.json tests/fixtures/gamma_markets_empty.json
git commit -m "feat: add Gamma client for active markets"
```

---

### Task 6: CLOB client

**Files:**
- Create: `src/polymath/clients/clob.py`
- Test: `tests/test_clob_client.py`

- [ ] **Step 1: Write the failing test**

```python
import httpx
import respx

from polymath.clients.clob import ClobClient


@respx.mock
async def test_fetch_books_parses_and_sorts():
    payload = [
        {"asset_id": "yes1",
         "bids": [{"price": "0.40", "size": "100"}, {"price": "0.42", "size": "50"}],
         "asks": [{"price": "0.46", "size": "80"}, {"price": "0.45", "size": "30"}]},
        {"asset_id": "no1", "bids": [], "asks": [{"price": "0.50", "size": "10"}]},
    ]
    respx.post("https://clob.polymarket.com/books").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with ClobClient("https://clob.polymarket.com") as client:
        books = await client.fetch_books(["yes1", "no1"])

    assert set(books) == {"yes1", "no1"}
    yes = books["yes1"]
    assert yes.best_bid().price == 0.42    # sorted desc
    assert yes.best_ask().price == 0.45    # sorted asc
    assert books["no1"].best_bid() is None


@respx.mock
async def test_fetch_books_chunks_large_requests():
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        return httpx.Response(200, json=[])

    respx.post("https://clob.polymarket.com/books").mock(side_effect=responder)
    async with ClobClient("https://clob.polymarket.com", chunk_size=2) as client:
        await client.fetch_books(["a", "b", "c", "d", "e"])
    assert calls["n"] == 3   # ceil(5/2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clob_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.clients.clob'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import asyncio

import httpx

from polymath.model import Level, OrderBook


def _levels(raw: list[dict]) -> list[Level]:
    return [Level(float(x["price"]), float(x["size"])) for x in raw]


def _parse_book(raw: dict) -> OrderBook:
    return OrderBook(
        token_id=str(raw.get("asset_id")),
        bids=_levels(raw.get("bids", [])),
        asks=_levels(raw.get("asks", [])),
    ).normalized()


class ClobClient:
    def __init__(self, base_url: str, *, chunk_size: int = 100, timeout: float = 30.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._chunk = chunk_size

    async def __aenter__(self) -> "ClobClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _fetch_chunk(self, token_ids: list[str]) -> list[OrderBook]:
        body = [{"token_id": t} for t in token_ids]
        resp = await self._client.post("/books", json=body)
        resp.raise_for_status()
        return [_parse_book(b) for b in resp.json()]

    async def fetch_books(self, token_ids: list[str]) -> dict[str, OrderBook]:
        chunks = [token_ids[i:i + self._chunk]
                  for i in range(0, len(token_ids), self._chunk)]
        results = await asyncio.gather(*(self._fetch_chunk(c) for c in chunks))
        books: dict[str, OrderBook] = {}
        for group in results:
            for book in group:
                books[book.token_id] = book
        return books
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_clob_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/clients/clob.py tests/test_clob_client.py
git commit -m "feat: add async CLOB client with batch book fetch"
```

---

### Task 7: Scanner orchestration

**Files:**
- Create: `src/polymath/scanner.py`
- Test: `tests/test_scanner.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

from polymath.model import Level, OrderBook, Token, Market
from polymath.config import default_config
from polymath.scanner import build_snapshot, run_detectors


class FakeGamma:
    def __init__(self, markets):
        self._markets = markets

    async def fetch_active_markets(self, *, min_liquidity, min_volume):
        return self._markets


class FakeClob:
    def __init__(self, books):
        self._books = books

    async def fetch_books(self, token_ids):
        return {t: self._books[t] for t in token_ids if t in self._books}


def _m(cid, yes, no, nrm=None):
    return Market(cid, f"Q{cid}", cid, [Token(yes, "Yes"), Token(no, "No")],
                  neg_risk=nrm is not None, neg_risk_market_id=nrm,
                  accepting_orders=True, end_date=None, liquidity=9999, volume=9999)


async def test_build_snapshot_collects_books_and_groups_events():
    markets = [_m("c1", "y1", "n1", nrm="E"), _m("c2", "y2", "n2", nrm="E")]
    books = {tid: OrderBook(tid) for tid in ["y1", "n1", "y2", "n2"]}
    snap = await build_snapshot(FakeGamma(markets), FakeClob(books), default_config())
    assert set(snap.markets) == {"c1", "c2"}
    assert set(snap.books) == {"y1", "n1", "y2", "n2"}
    assert "E" in snap.events
    assert snap.events["E"].neg_risk is True
    assert set(snap.events["E"].market_condition_ids) == {"c1", "c2"}
    assert snap.timestamp.tzinfo == timezone.utc


async def test_run_detectors_finds_binary_arb():
    markets = [_m("c1", "yes", "no")]
    books = {"yes": OrderBook("yes", asks=[Level(0.45, 100)]),
             "no": OrderBook("no", asks=[Level(0.50, 100)])}
    snap = await build_snapshot(FakeGamma(markets), FakeClob(books), default_config())
    opps = run_detectors(snap, default_config(), profile="default")
    assert any(o.kind == "binary_yes_no" for o in opps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scanner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.scanner'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from datetime import datetime, timezone

from polymath.config import Config
from polymath.detectors import pure_arb
from polymath.model import Event, Snapshot


def _group_events(markets) -> dict[str, Event]:
    events: dict[str, Event] = {}
    for m in markets:
        if m.neg_risk and m.neg_risk_market_id:
            ev = events.get(m.neg_risk_market_id)
            if ev is None:
                ev = Event(id=m.neg_risk_market_id, title=m.neg_risk_market_id,
                           neg_risk=True, market_condition_ids=[])
                events[m.neg_risk_market_id] = ev
            ev.market_condition_ids.append(m.condition_id)
    return {eid: ev for eid, ev in events.items() if len(ev.market_condition_ids) >= 2}


async def build_snapshot(gamma, clob, config: Config) -> Snapshot:
    markets = await gamma.fetch_active_markets(
        min_liquidity=config.min_liquidity, min_volume=config.min_volume)
    token_ids = [t.token_id for m in markets for t in m.tokens]
    books = await clob.fetch_books(token_ids)
    return Snapshot(
        timestamp=datetime.now(timezone.utc),
        markets={m.condition_id: m for m in markets},
        books=books,
        events=_group_events(markets),
    )


def run_detectors(snap: Snapshot, config: Config, *, profile: str,
                  only: str | None = None) -> list:
    eff = config.effective(profile)
    opps = []
    if only in (None, "pure_arb"):
        opps += pure_arb.detect(
            snap, min_roi=eff.min_roi, min_profit_usd=eff.min_profit_usd,
            fee_bps=eff.fee_bps, profile=profile)
    return sorted(opps, key=lambda o: o.net_profit, reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scanner.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/scanner.py tests/test_scanner.py
git commit -m "feat: add scanner snapshot builder and detector runner"
```

---

### Task 8: Ledger

**Files:**
- Create: `src/polymath/ledger.py`
- Test: `tests/test_ledger.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.ledger import Ledger


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = Ledger(path)
    led.append({"id": "a", "net_profit": 1.0})
    led.append({"id": "b", "net_profit": -0.5})
    rows = led.read_all()
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[1]["net_profit"] == -0.5


def test_read_all_missing_file_returns_empty(tmp_path):
    led = Ledger(tmp_path / "nope.jsonl")
    assert led.read_all() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ledger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.ledger'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
from pathlib import Path


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, row: dict) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as fh:
            return [json.loads(line) for line in fh if line.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ledger.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/ledger.py tests/test_ledger.py
git commit -m "feat: add append-only JSONL ledger"
```

---

### Task 9: Paper-trading harness

Capital-aware simulated execution: position sizing, dedup of recurring opportunities, capital constraint, and locked PnL for instant-merge arbs. Each entered (or skipped) signal becomes a ledger row.

**Files:**
- Create: `src/polymath/paper.py`
- Test: `tests/test_paper.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

from polymath.model import Leg, Opportunity
from polymath.paper import PaperBook


def _opp(kind="binary_yes_no", mids=("c1",), size=100.0, cost=95.0, net=5.0):
    return Opportunity(
        module="pure_arb", profile="default", kind=kind, market_ids=list(mids),
        legs=[Leg("y", "Yes", "buy", 0.45, mids[0])],
        fillable_size=size, cost=cost, net_profit=net,
        roi=net / cost, realizability="instant-merge", risk_tier="risk-free",
        end_date=None, explain="x")


def test_entry_sizes_to_max_position_and_locks_pnl():
    book = PaperBook(bankroll=1000.0, max_position_pct=0.10, assumed_slippage=0.0)
    ts = datetime.now(timezone.utc)
    row = book.consider(_opp(size=100, cost=95.0, net=5.0), ts)
    # cost per set = 0.95; cap = 100 budget -> 105 sets affordable but fillable=100,
    # and max_position = 10% * 1000 = 100 budget -> ~105 sets, so fillable (100) binds.
    assert row["status"] == "entered"
    assert row["entered_size"] == 100
    # locked pnl scales with entered fraction (here full): 5.0
    assert round(row["realized_pnl"], 4) == 5.0


def test_max_position_caps_spend():
    book = PaperBook(bankroll=1000.0, max_position_pct=0.05, assumed_slippage=0.0)
    ts = datetime.now(timezone.utc)
    # cost/set = 0.95; budget = 5% * 1000 = 50 -> floor(50/0.95) = 52 sets
    row = book.consider(_opp(size=100, cost=95.0, net=5.0), ts)
    assert row["status"] == "entered"
    assert row["entered_size"] == 52
    assert round(row["realized_pnl"], 4) == round(52 * (5.0 / 100), 4)


def test_dedup_same_opportunity_not_reentered():
    book = PaperBook(bankroll=10_000.0, max_position_pct=1.0, assumed_slippage=0.0)
    ts = datetime.now(timezone.utc)
    first = book.consider(_opp(), ts)
    second = book.consider(_opp(), ts)
    assert first["status"] == "entered"
    assert second["status"] == "deduped"


def test_capital_constraint_when_bankroll_exhausted():
    book = PaperBook(bankroll=50.0, max_position_pct=1.0, assumed_slippage=0.0)
    ts = datetime.now(timezone.utc)
    book.consider(_opp(mids=("c1",), size=100, cost=95.0, net=5.0), ts)  # spends ~50
    row = book.consider(_opp(mids=("c2",), size=100, cost=95.0, net=5.0), ts)
    assert row["status"] == "capital-constrained"
    assert row["entered_size"] == 0


def test_slippage_reduces_realized_pnl():
    book = PaperBook(bankroll=10_000.0, max_position_pct=1.0, assumed_slippage=0.01)
    ts = datetime.now(timezone.utc)
    row = book.consider(_opp(size=100, cost=95.0, net=5.0), ts)
    # slippage adds 1% of cost to the cost side: extra 0.95 cost on 100 sets
    assert round(row["realized_pnl"], 4) == round(5.0 - 0.95, 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.paper'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import math
from datetime import datetime

from polymath.model import Opportunity


class PaperBook:
    """In-memory simulated trading state. One instance per scan run.

    Sizes each opportunity to min(fillable depth, max_position budget, remaining
    bankroll), dedups recurring opportunities, and records locked PnL for
    instant-merge arbs. Every decision is returned as a ledger-ready dict.
    """

    def __init__(self, *, bankroll: float, max_position_pct: float,
                 assumed_slippage: float):
        self.bankroll = bankroll
        self.remaining = bankroll
        self.max_position_pct = max_position_pct
        self.assumed_slippage = assumed_slippage
        self._seen: set[str] = set()

    def _row(self, opp: Opportunity, ts: datetime, status: str,
             entered_size: float, realized_pnl: float) -> dict:
        return {
            "timestamp": ts.isoformat(),
            "module": opp.module,
            "profile": opp.profile,
            "kind": opp.kind,
            "market_ids": opp.market_ids,
            "dedup_key": opp.dedup_key(),
            "predicted_net_profit": opp.net_profit,
            "predicted_roi": opp.roi,
            "fillable_size": opp.fillable_size,
            "realizability": opp.realizability,
            "risk_tier": opp.risk_tier,
            "status": status,
            "entered_size": entered_size,
            "realized_pnl": realized_pnl,
        }

    def consider(self, opp: Opportunity, ts: datetime) -> dict:
        key = opp.dedup_key()
        if key in self._seen:
            return self._row(opp, ts, "deduped", 0.0, 0.0)

        if opp.fillable_size <= 0 or opp.cost <= 0:
            return self._row(opp, ts, "skipped", 0.0, 0.0)

        cost_per_set = opp.cost / opp.fillable_size
        position_budget = min(self.max_position_pct * self.bankroll, self.remaining)
        affordable = math.floor(position_budget / cost_per_set) if cost_per_set else 0
        size = min(opp.fillable_size, affordable)

        if size <= 0:
            return self._row(opp, ts, "capital-constrained", 0.0, 0.0)

        fraction = size / opp.fillable_size
        spent = opp.cost * fraction
        gross_pnl = opp.net_profit * fraction
        slip = self.assumed_slippage * spent
        realized = gross_pnl - slip

        self.remaining -= spent
        self._seen.add(key)
        return self._row(opp, ts, "entered", size, realized)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paper.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/paper.py tests/test_paper.py
git commit -m "feat: add capital-aware paper-trading harness"
```

---

### Task 10: Experiment scorecard

**Files:**
- Create: `src/polymath/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.report import build_scorecard


def _row(module, profile, status, pnl):
    return {"module": module, "profile": profile, "status": status,
            "realized_pnl": pnl}


def test_groups_by_module_and_profile():
    rows = [
        _row("pure_arb", "default", "entered", 5.0),
        _row("pure_arb", "default", "entered", 3.0),
        _row("pure_arb", "aggressive", "entered", -1.0),
        _row("pure_arb", "default", "deduped", 0.0),   # ignored in PnL stats
    ]
    cards = {(c.module, c.profile): c for c in build_scorecard(rows, min_entered=2)}
    d = cards[("pure_arb", "default")]
    assert d.entered == 2
    assert round(d.total_pnl, 4) == 8.0
    assert d.hit_rate == 1.0
    assert d.verdict == "consistent"

    a = cards[("pure_arb", "aggressive")]
    assert a.entered == 1
    assert a.verdict == "insufficient-data"   # below min_entered


def test_negative_total_marks_negative_verdict():
    rows = [
        _row("pure_arb", "default", "entered", -2.0),
        _row("pure_arb", "default", "entered", -3.0),
    ]
    card = build_scorecard(rows, min_entered=2)[0]
    assert card.total_pnl == -5.0
    assert card.hit_rate == 0.0
    assert card.verdict == "negative"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.report'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class ExperimentScore:
    module: str
    profile: str
    signals: int
    entered: int
    total_pnl: float
    hit_rate: float
    sharpe: float
    max_drawdown: float
    verdict: str


def _max_drawdown(pnls: list[float]) -> float:
    cum = 0.0
    peak = 0.0
    worst = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return worst


def _verdict(entered: int, total: float, sharpe: float, min_entered: int) -> str:
    if entered < min_entered:
        return "insufficient-data"
    if total < 0:
        return "negative"
    if sharpe >= 1.0:
        return "consistent"
    return "marginal"


def build_scorecard(rows: list[dict], *, min_entered: int = 10) -> list[ExperimentScore]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["module"], r["profile"]), []).append(r)

    cards: list[ExperimentScore] = []
    for (module, profile), grp in groups.items():
        entered = [r for r in grp if r["status"] == "entered"]
        pnls = [float(r["realized_pnl"]) for r in entered]
        total = sum(pnls)
        hit = (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else 0.0
        if len(pnls) >= 2 and statistics.pstdev(pnls) > 0:
            sharpe = statistics.mean(pnls) / statistics.pstdev(pnls)
        elif pnls and total > 0:
            sharpe = float("inf")
        else:
            sharpe = 0.0
        cards.append(ExperimentScore(
            module=module, profile=profile, signals=len(grp), entered=len(entered),
            total_pnl=total, hit_rate=hit, sharpe=sharpe,
            max_drawdown=_max_drawdown(pnls),
            verdict=_verdict(len(entered), total, sharpe, min_entered),
        ))
    return cards
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/report.py tests/test_report.py
git commit -m "feat: add per-experiment scorecard aggregation"
```

---

### Task 11: CLI (scan / watch / report)

**Files:**
- Create: `src/polymath/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

from typer.testing import CliRunner

from polymath import cli
from polymath.model import Level, OrderBook, Token, Market

runner = CliRunner()


class FakeGamma:
    def __init__(self, markets):
        self._markets = markets

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch_active_markets(self, *, min_liquidity, min_volume):
        return self._markets


class FakeClob:
    def __init__(self, books):
        self._books = books

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch_books(self, token_ids):
        return {t: self._books[t] for t in token_ids if t in self._books}


def _patch_clients(monkeypatch):
    market = Market("c1", "Will X?", "x", [Token("yes", "Yes"), Token("no", "No")],
                    neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                    end_date=None, liquidity=9999, volume=9999)
    books = {"yes": OrderBook("yes", asks=[Level(0.45, 100)]),
             "no": OrderBook("no", asks=[Level(0.50, 100)])}
    monkeypatch.setattr(cli, "GammaClient", lambda *a, **k: FakeGamma([market]))
    monkeypatch.setattr(cli, "ClobClient", lambda *a, **k: FakeClob(books))


def test_scan_prints_opportunity(monkeypatch):
    _patch_clients(monkeypatch)
    result = runner.invoke(cli.app, ["scan"])
    assert result.exit_code == 0
    assert "binary_yes_no" in result.stdout


def test_scan_record_writes_ledger_then_report(monkeypatch, tmp_path):
    _patch_clients(monkeypatch)
    ledger = tmp_path / "ledger.jsonl"
    r1 = runner.invoke(cli.app, ["scan", "--record", "--ledger", str(ledger)])
    assert r1.exit_code == 0
    assert ledger.exists()
    r2 = runner.invoke(cli.app, ["report", "--ledger", str(ledger), "--min-entered", "1"])
    assert r2.exit_code == 0
    assert "pure_arb" in r2.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from polymath.clients.clob import ClobClient
from polymath.clients.gamma import GammaClient
from polymath.config import Config, default_config, load_config
from polymath.ledger import Ledger
from polymath.paper import PaperBook
from polymath.report import build_scorecard
from polymath.scanner import build_snapshot, run_detectors

app = typer.Typer(add_completion=False, help="Polymarket arbitrage scanner")
console = Console()

_BADGE = {"risk-free": "🔒", "structural": "🟡", "directional": "⚠️"}


def _load(config_path: str | None) -> Config:
    return load_config(config_path) if config_path else default_config()


async def _scan_once(cfg: Config, profile: str, only: str | None):
    async with GammaClient(cfg.gamma_base) as gamma, ClobClient(cfg.clob_base) as clob:
        snap = await build_snapshot(gamma, clob, cfg)
    opps = run_detectors(snap, cfg, profile=profile, only=only)
    return snap, opps


def _render(snap, opps) -> None:
    age = (datetime.now(timezone.utc) - snap.timestamp).total_seconds()
    table = Table(title=f"Opportunities (snapshot age {age:.0f}s)")
    for col in ("", "kind", "markets", "size", "net $", "roi %", "realizability"):
        table.add_column(col)
    for o in opps:
        table.add_row(
            _BADGE.get(o.risk_tier, "?"), o.kind, ",".join(o.market_ids),
            f"{o.fillable_size:g}", f"{o.net_profit:.2f}", f"{o.roi * 100:.2f}",
            o.realizability,
        )
    console.print(table)
    if not opps:
        console.print("[dim]no qualifying opportunities[/dim]")


@app.command()
def scan(
    profile: str = typer.Option("default"),
    only: str = typer.Option(None, help="pure_arb"),
    record: bool = typer.Option(False, "--record"),
    ledger: str = typer.Option(None, help="ledger path override"),
    config: str = typer.Option(None, help="config TOML path"),
):
    cfg = _load(config)
    snap, opps = asyncio.run(_scan_once(cfg, profile, only))
    _render(snap, opps)
    if record:
        eff = cfg.effective(profile)
        led = Ledger(ledger or eff.ledger_path)
        book = PaperBook(bankroll=eff.bankroll, max_position_pct=eff.max_position_pct,
                         assumed_slippage=eff.assumed_slippage)
        for o in opps:
            led.append(book.consider(o, snap.timestamp))
        console.print(f"[green]recorded {len(opps)} signals to {led.path}[/green]")


@app.command()
def watch(
    interval: int = typer.Option(None, help="seconds between scans"),
    profile: str = typer.Option("default"),
    only: str = typer.Option(None),
    ledger: str = typer.Option(None),
    config: str = typer.Option(None),
    iterations: int = typer.Option(0, help="0 = forever; >0 for testing"),
):
    cfg = _load(config)
    eff = cfg.effective(profile)
    delay = interval or eff.watch_interval_seconds
    n = 0
    while True:
        snap, opps = asyncio.run(_scan_once(cfg, profile, only))
        led = Ledger(ledger or eff.ledger_path)
        book = PaperBook(bankroll=eff.bankroll, max_position_pct=eff.max_position_pct,
                         assumed_slippage=eff.assumed_slippage)
        for o in opps:
            led.append(book.consider(o, snap.timestamp))
        console.print(f"[{snap.timestamp.isoformat()}] recorded {len(opps)} signals")
        n += 1
        if iterations and n >= iterations:
            break
        time.sleep(delay)


@app.command()
def report(
    ledger: str = typer.Option(None),
    module: str = typer.Option(None, help="filter by module"),
    min_entered: int = typer.Option(10),
    config: str = typer.Option(None),
):
    cfg = _load(config)
    led = Ledger(ledger or cfg.ledger_path)
    rows = led.read_all()
    if module:
        rows = [r for r in rows if r.get("module") == module]
    cards = build_scorecard(rows, min_entered=min_entered)
    table = Table(title="Experiment scorecard")
    for col in ("module", "profile", "signals", "entered", "total $", "hit %",
                "sharpe", "verdict"):
        table.add_column(col)
    for c in sorted(cards, key=lambda c: c.total_pnl, reverse=True):
        table.add_row(c.module, c.profile, str(c.signals), str(c.entered),
                      f"{c.total_pnl:.2f}", f"{c.hit_rate * 100:.0f}",
                      f"{c.sharpe:.2f}", c.verdict)
    console.print(table)


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/cli.py tests/test_cli.py
git commit -m "feat: add scan/watch/report CLI commands"
```

---

### Task 12: Full suite, smoke run, and README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run the whole test suite**

Run: `. .venv/bin/activate && pytest -q`
Expected: all tests pass (roughly 24 tests, 0 failed).

- [ ] **Step 2: Smoke-test the CLI help**

Run: `. .venv/bin/activate && polymath --help && polymath scan --help`
Expected: usage text listing `scan`, `watch`, `report` and the `--record`/`--profile` options. Exit code 0.

- [ ] **Step 3: Write `README.md`**

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add README and verify full suite green"
```

---

## Self-Review

**Spec coverage check (against `2026-06-16-polymath-arbitrage-scanner-design.md`):**
- §3 Module 1 pure arb (binary, neg-risk, sell-set) → Task 3 ✓
- §3 Modules 2 (logical RV) & 3 (longshot) → intentionally deferred to follow-on plans (stated in scope note) ✓
- §4 synthetic complementary pricing → Task 2 `effective_ask_ladder` ✓
- §4 realizability field + ranking → Task 1 model, Task 3 sets `instant-merge`/`hold-to-resolution`, Task 7 ranks by net profit ✓
- §5 components → Tasks 1–11 map 1:1 to the file structure ✓
- §6 depth-aware matched-set math + fees → Task 2 + `_finalize` in Task 3 ✓
- §9 paper harness: capture (`scan --record`, `watch`) → Task 11; experiment identity `(module, profile)` → Tasks 9/10; capital-aware sizing + dedup + capital constraint → Task 9; ledger schema → Task 9 `_row`; scorecard (hit rate, sharpe, drawdown, verdict) → Task 10 ✓
- §10 CLI commands + flags + risk badges + snapshot age → Task 11 ✓
- §11 config + named profiles → Task 4 ✓
- §12 pagination, async batch, skip-missing-book (detectors treat missing books as empty via `_book`) → Tasks 5/6/7/3 ✓
- §13 testing strategy (pure-fn TDD, respx fixtures, paper/report unit tests) → every task ✓

**Deferred-but-noted (not gaps — out of this plan's stated scope):** predicted-vs-realized edge calibration and mark-to-market/resolution scoring become meaningful only for the structural/directional modules; the harness records `predicted_*` fields now (Task 9 `_row`) so the calibration column can be computed once those modules and resolution-fetching land in their follow-on plans.

**Placeholder scan:** no TBD/TODO; every code step contains complete code. ✓

**Type consistency:** `Opportunity` fields (`fillable_size`, `net_profit`, `roi`, `realizability`, `risk_tier`, `dedup_key()`) used identically across Tasks 1, 3, 9, 11. `Config.effective()` used in Tasks 7 and 11. Ledger row keys written in Task 9 (`module`, `profile`, `status`, `realized_pnl`) match those read in Task 10. ✓
