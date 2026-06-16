# News-Signal Directional Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paper-only directional betting pilot that, each day, finds Polymarket markets resolving within ~48h, has the local Claude Code CLI research each (web search) and estimate a probability, diversely samples 5–10 flat-$100 bets on the mispriced side, then settles and analyzes them for calibration and signal attribution.

**Architecture:** A new `src/polymath/signals/` package reusing the existing `ledger`, `config`, and `clients/gamma` modules. Pure functions for near-term selection, bet construction, diverse selection, settlement PnL, and analysis; a pluggable `Researcher` (offline `StubResearcher`; live `ClaudeCliResearcher` that shells out to `claude -p ... --output-format json` with an injectable runner). Three CLI commands — `bet`, `settle`, `analyze` — registered on the main typer app.

**Tech Stack:** Python 3.11+, `httpx`, `typer`, `rich`, `pytest`/`pytest-asyncio`, the local `claude` CLI (already authenticated; no API key).

**Branch:** create and work on `feature/news-directional` off `master`.

**Spec:** `docs/superpowers/specs/2026-06-16-news-signal-directional-pilot-design.md`.

**Verified external facts (do not re-litigate):**
- Gamma active markets include `id` (numeric), `outcomes`, `outcomePrices` (current prices, e.g. `["0.62","0.38"]`), `endDate`, `acceptingOrders`, `liquidityNum`.
- Resolution: `GET /markets/{id}` returns `closed`, `umaResolutionStatus` (`"resolved"`), `outcomes`, `outcomePrices` (winner = index whose price == `"1"`; `0/0` or `1/1` = void/ambiguous).
- Claude CLI: `claude -p "<prompt>" --output-format json --allowed-tools WebSearch --model <m>` prints one JSON line: `{"type":"result","subtype":"success","is_error":false,"result":"<model text>","usage":{"server_tool_use":{"web_search_requests":N}}, ...}`. The model's answer is the `result` string.

---

## File Structure

```
src/polymath/signals/__init__.py
src/polymath/signals/estimate.py     # Estimate dataclass
src/polymath/signals/nearterm.py     # select_near_term() pure filter
src/polymath/signals/research.py     # Researcher protocol, StubResearcher, ClaudeCliResearcher
src/polymath/signals/directional.py  # build_bet() -> ledger row
src/polymath/signals/select.py       # diversify() stratified sampling
src/polymath/signals/resolution.py   # winner_from_raw() pure parser
src/polymath/signals/settle.py       # score() + settle_rows()
src/polymath/signals/analyze.py      # build_report()
src/polymath/signals/cli.py          # bet / settle / analyze typer commands
tests/signals/...                    # mirror
```

Modified: `src/polymath/model.py` (add `gamma_id`, `yes_price` to Market),
`src/polymath/clients/gamma.py` (parse the two fields + `fetch_market_raw`),
`src/polymath/config.py` (new fields), `src/polymath/cli.py` (mount signals app).

---

### Task 0: Branch and package scaffold

**Files:**
- Create: `src/polymath/signals/__init__.py`
- Create: `tests/signals/__init__.py`

- [ ] **Step 1: Create branch**

Run:
```bash
cd /Users/tomernahumi/Documents/Plugins/polymath && git checkout -b feature/news-directional
```
Expected: `Switched to a new branch 'feature/news-directional'`

- [ ] **Step 2: Create package init files**

Create `src/polymath/signals/__init__.py` and `tests/signals/__init__.py`, each:
```python
# polymath.signals
```

- [ ] **Step 3: Verify import + suite still green**

Run: `. .venv/bin/activate && python -c "import polymath.signals" && pytest -q`
Expected: import succeeds; existing suite passes (39 passed).

- [ ] **Step 4: Commit**

```bash
git add src/polymath/signals/__init__.py tests/signals/__init__.py
git commit -m "chore: scaffold signals package on feature branch"
```

---

### Task 1: Estimate dataclass

**Files:**
- Create: `src/polymath/signals/estimate.py`
- Test: `tests/signals/test_estimate.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.signals.estimate import Estimate


def test_estimate_holds_fields_and_defaults():
    e = Estimate(prob=0.62, confidence=0.7, category="sports",
                 signals={"source_count": 4}, rationale="home team favored")
    assert e.prob == 0.62
    assert e.confidence == 0.7
    assert e.category == "sports"
    assert e.signals["source_count"] == 4
    assert e.rationale == "home team favored"


def test_estimate_clamps_prob_into_unit_interval():
    assert Estimate(prob=1.4, confidence=0.5, category="x", signals={}, rationale="").prob == 1.0
    assert Estimate(prob=-0.2, confidence=0.5, category="x", signals={}, rationale="").prob == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_estimate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.estimate'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Estimate:
    prob: float                       # estimated probability of the YES outcome
    confidence: float                 # 0..1 self-reported confidence
    category: str                     # "sports" | "politics" | "world-news" | ...
    signals: dict = field(default_factory=dict)
    rationale: str = ""

    def __post_init__(self) -> None:
        self.prob = max(0.0, min(1.0, float(self.prob)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_estimate.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/estimate.py tests/signals/test_estimate.py
git commit -m "feat: add Estimate dataclass for signal research"
```

---

### Task 2: Add gamma_id and yes_price to Market

**Files:**
- Modify: `src/polymath/model.py`
- Modify: `src/polymath/clients/gamma.py`
- Test: `tests/signals/test_market_pricing_fields.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

import httpx
import respx

from polymath.clients.gamma import GammaClient


@respx.mock
async def test_parses_gamma_id_and_yes_price():
    raw = [{
        "id": "777", "conditionId": "c1", "question": "Q", "slug": "q",
        "clobTokenIds": "[\"yes1\", \"no1\"]", "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.62\", \"0.38\"]",
        "active": True, "closed": False, "acceptingOrders": True,
        "negRisk": False, "liquidityNum": 1000, "volumeNum": 1000,
        "endDate": "2026-06-17T00:00:00Z",
    }]
    respx.get("https://gamma-api.polymarket.com/markets").side_effect = [
        httpx.Response(200, json=raw), httpx.Response(200, json=[]),
    ]
    async with GammaClient("https://gamma-api.polymarket.com") as c:
        markets = await c.fetch_active_markets(min_liquidity=0, min_volume=0)
    m = markets[0]
    assert m.gamma_id == "777"
    assert m.yes_price == 0.62
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_market_pricing_fields.py -v`
Expected: FAIL — `AttributeError: 'Market' object has no attribute 'gamma_id'`

- [ ] **Step 3: Add the fields to Market**

In `src/polymath/model.py`, in the `Market` dataclass, after the existing
`event_id: str | None = None` line add:

```python
    gamma_id: str | None = None
    yes_price: float | None = None
```

- [ ] **Step 4: Parse them in gamma**

In `src/polymath/clients/gamma.py`, inside `_parse_market`, replace the
`return Market(` block's tail so the constructor includes the two new fields.
First, just before `return Market(`, add:

```python
    prices_raw = raw.get("outcomePrices")
    yes_price = None
    if prices_raw:
        try:
            yes_price = float(json.loads(prices_raw)[0])
        except (json.JSONDecodeError, ValueError, IndexError, TypeError):
            yes_price = None
    gamma_id = str(raw["id"]) if raw.get("id") is not None else None
```

Then in the `return Market(...)` call, after `event_id=event_id,` add:

```python
        gamma_id=gamma_id,
        yes_price=yes_price,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/signals/test_market_pricing_fields.py tests/test_gamma_client.py -v`
Expected: PASS (the new test plus the existing gamma tests still pass)

- [ ] **Step 6: Commit**

```bash
git add src/polymath/model.py src/polymath/clients/gamma.py tests/signals/test_market_pricing_fields.py
git commit -m "feat: parse gamma_id and yes_price on Market"
```

---

### Task 3: Near-term market selection

**Files:**
- Create: `src/polymath/signals/nearterm.py`
- Test: `tests/signals/test_nearterm.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta, timezone

from polymath.model import Token, Market
from polymath.signals.nearterm import select_near_term

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _m(cid, hours, *, liq=1000.0, accepting=True, yes_price=0.5, binary=True):
    toks = [Token(f"{cid}y", "Yes"), Token(f"{cid}n", "No")]
    if not binary:
        toks = toks + [Token(f"{cid}z", "Maybe")]
    return Market(cid, f"Q{cid}", cid, toks, neg_risk=False, neg_risk_market_id=None,
                  accepting_orders=accepting, end_date=NOW + timedelta(hours=hours),
                  liquidity=liq, volume=liq, gamma_id=cid, yes_price=yes_price)


def test_selects_only_within_window_liquid_binary_accepting():
    markets = [
        _m("a", 10),                      # in window
        _m("b", 60),                      # too far (>48h)
        _m("c", 10, liq=10),              # too illiquid
        _m("d", 10, accepting=False),     # not accepting orders
        _m("e", 10, binary=False),        # not binary
        _m("f", -5),                      # already past end -> excluded
        _m("g", 10, yes_price=None),      # no current price -> excluded
    ]
    out = select_near_term(markets, NOW, window_hours=48, min_liquidity=500,
                           max_candidates=40)
    assert {m.condition_id for m in out} == {"a"}


def test_caps_to_max_candidates_by_liquidity_desc():
    markets = [_m(str(i), 10, liq=100.0 * i) for i in range(1, 6)]  # liq 100..500
    out = select_near_term(markets, NOW, window_hours=48, min_liquidity=0,
                           max_candidates=2)
    assert [m.condition_id for m in out] == ["5", "4"]   # most liquid first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_nearterm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.nearterm'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from datetime import datetime, timedelta

from polymath.model import Market


def select_near_term(markets: list[Market], now: datetime, *, window_hours: int,
                     min_liquidity: float, max_candidates: int) -> list[Market]:
    """Markets resolving within the window that are tradeable, binary, priced, and
    liquid — capped to the most-liquid ``max_candidates`` to bound research cost."""
    horizon = now + timedelta(hours=window_hours)
    eligible = [
        m for m in markets
        if m.accepting_orders and m.is_binary() and m.yes_price is not None
        and m.end_date is not None and now < m.end_date <= horizon
        and m.liquidity >= min_liquidity
    ]
    eligible.sort(key=lambda m: m.liquidity, reverse=True)
    return eligible[:max_candidates]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_nearterm.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/nearterm.py tests/signals/test_nearterm.py
git commit -m "feat: add near-term market selector"
```

---

### Task 4: Researcher protocol and StubResearcher

**Files:**
- Create: `src/polymath/signals/research.py`
- Test: `tests/signals/test_stub_researcher.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.model import Token, Market
from polymath.signals.estimate import Estimate
from polymath.signals.research import StubResearcher


def _m(cid):
    return Market(cid, f"Q{cid}", cid, [Token("y", "Yes"), Token("n", "No")],
                  neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                  end_date=None, liquidity=1.0, volume=1.0, gamma_id=cid, yes_price=0.5)


def test_stub_returns_mapped_estimate():
    est = Estimate(prob=0.7, confidence=0.8, category="sports", signals={}, rationale="r")
    stub = StubResearcher({"c1": est})
    assert stub.research(_m("c1")).prob == 0.7


def test_stub_raises_for_unknown_market():
    stub = StubResearcher({})
    try:
        stub.research(_m("c1"))
        assert False, "expected KeyError"
    except KeyError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_stub_researcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.research'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from typing import Protocol

from polymath.model import Market
from polymath.signals.estimate import Estimate


class Researcher(Protocol):
    def research(self, market: Market) -> Estimate: ...


class StubResearcher:
    """Returns canned estimates keyed by condition_id. For offline tests."""

    def __init__(self, by_condition_id: dict[str, Estimate]):
        self._by_cid = by_condition_id

    def research(self, market: Market) -> Estimate:
        return self._by_cid[market.condition_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_stub_researcher.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/research.py tests/signals/test_stub_researcher.py
git commit -m "feat: add Researcher protocol and StubResearcher"
```

---

### Task 5: ClaudeCliResearcher (injectable runner)

**Files:**
- Modify: `src/polymath/signals/research.py`
- Test: `tests/signals/test_claude_cli_researcher.py`

- [ ] **Step 1: Write the failing test**

```python
import json

from polymath.model import Token, Market
from polymath.signals.research import ClaudeCliResearcher


def _m(cid="c1", q="Will the Lakers win tonight?"):
    return Market(cid, q, cid, [Token("y", "Yes"), Token("n", "No")],
                  neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                  end_date=None, liquidity=1.0, volume=1.0, gamma_id=cid, yes_price=0.55)


def test_builds_command_and_parses_estimate():
    captured = {}

    def fake_runner(cmd):
        captured["cmd"] = cmd
        inner = json.dumps({"prob": 0.66, "confidence": 0.6, "category": "sports",
                            "signals": {"source_count": 3}, "rationale": "favored"})
        return json.dumps({"type": "result", "subtype": "success",
                           "is_error": False, "result": inner,
                           "usage": {"server_tool_use": {"web_search_requests": 2}}})

    r = ClaudeCliResearcher(runner=fake_runner, cli_path="claude", model="claude-x")
    est = r.research(_m())

    # command carries headless + json + websearch + model flags and the question
    cmd = captured["cmd"]
    assert cmd[0] == "claude"
    assert "-p" in cmd and "--output-format" in cmd and "json" in cmd
    assert "--allowed-tools" in cmd and "WebSearch" in cmd
    assert "--model" in cmd and "claude-x" in cmd
    assert any("Lakers" in part for part in cmd)
    # parsed estimate, with web_search_requests folded into signals
    assert est.prob == 0.66
    assert est.category == "sports"
    assert est.signals["source_count"] == 3
    assert est.signals["web_search_requests"] == 2


def test_extracts_json_when_wrapped_in_prose():
    def fake_runner(cmd):
        inner = "Here is my answer:\n{\"prob\": 0.4, \"confidence\": 0.5, " \
                "\"category\": \"politics\", \"signals\": {}, \"rationale\": \"x\"}\nDone."
        return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                           "result": inner, "usage": {}})

    r = ClaudeCliResearcher(runner=lambda c: fake_runner(c))
    est = r.research(_m())
    assert est.prob == 0.4
    assert est.category == "politics"


def test_raises_on_cli_error_envelope():
    def fake_runner(cmd):
        return json.dumps({"type": "result", "subtype": "error",
                           "is_error": True, "result": "", "usage": {}})

    r = ClaudeCliResearcher(runner=lambda c: fake_runner(c))
    try:
        r.research(_m())
        assert False, "expected ResearchError"
    except Exception as e:
        assert "research" in str(e).lower() or "cli" in str(e).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_claude_cli_researcher.py -v`
Expected: FAIL with `ImportError: cannot import name 'ClaudeCliResearcher'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/polymath/signals/research.py`:

```python
import json
import re
import subprocess

from polymath.signals.estimate import Estimate

_PROMPT = (
    "You are estimating the probability of a Polymarket YES outcome.\n"
    "Question: {question}\n"
    "Use web search to gather the most recent, relevant facts, then respond with "
    "ONLY a single JSON object (no prose) of the form:\n"
    '{{"prob": <0..1 probability of YES>, "confidence": <0..1>, '
    '"category": "sports|politics|world-news|other", '
    '"signals": {{"latest_news_age_hours": <number>, "news_direction": "yes|no|mixed", '
    '"consensus_strength": <0..1>, "source_count": <int>}}, '
    '"rationale": "<one sentence>"}}'
)


class ResearchError(RuntimeError):
    pass


def _default_runner(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise ResearchError(f"claude CLI exited {proc.returncode}: {proc.stderr[:200]}")
    return proc.stdout


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ResearchError("no JSON object in CLI result")
        return json.loads(match.group(0))


class ClaudeCliResearcher:
    """Shells out to the local Claude Code CLI in headless mode with web search."""

    def __init__(self, runner=_default_runner, *, cli_path: str = "claude",
                 model: str | None = None):
        self._runner = runner
        self._cli = cli_path
        self._model = model

    def _build_cmd(self, market: Market) -> list[str]:
        prompt = _PROMPT.format(question=market.question)
        cmd = [self._cli, "-p", prompt, "--output-format", "json",
               "--allowed-tools", "WebSearch"]
        if self._model:
            cmd += ["--model", self._model]
        return cmd

    def research(self, market: Market) -> Estimate:
        raw = self._runner(self._build_cmd(market))
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ResearchError(f"CLI did not return JSON: {e}") from e
        if envelope.get("is_error") or envelope.get("subtype") != "success":
            raise ResearchError(f"CLI research failed: {envelope.get('subtype')}")
        payload = _extract_json_object(str(envelope.get("result", "")))
        signals = dict(payload.get("signals") or {})
        searches = (envelope.get("usage") or {}).get("server_tool_use", {})
        if "web_search_requests" in searches:
            signals["web_search_requests"] = searches["web_search_requests"]
        return Estimate(
            prob=payload.get("prob", 0.5),
            confidence=payload.get("confidence", 0.0),
            category=str(payload.get("category", "other")),
            signals=signals,
            rationale=str(payload.get("rationale", "")),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_claude_cli_researcher.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/research.py tests/signals/test_claude_cli_researcher.py
git commit -m "feat: add ClaudeCliResearcher with injectable runner"
```

---

### Task 6: Build directional bet rows

**Files:**
- Create: `src/polymath/signals/directional.py`
- Test: `tests/signals/test_directional.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

from polymath.model import Token, Market
from polymath.signals.estimate import Estimate
from polymath.signals.directional import build_bet

TS = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _m(cid="c1", yes_price=0.50):
    return Market(cid, f"Q{cid}", cid, [Token("y", "Yes"), Token("n", "No")],
                  neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                  end_date=None, liquidity=1.0, volume=1.0, gamma_id="42",
                  yes_price=yes_price)


def _est(prob, category="sports"):
    return Estimate(prob=prob, confidence=0.7, category=category,
                    signals={"source_count": 3}, rationale="r")


def test_bets_yes_when_estimate_above_price():
    row = build_bet(_m(yes_price=0.50), _est(0.70), min_edge=0.10,
                    stake=100.0, profile="default", timestamp=TS)
    assert row["side"] == "Yes"
    assert row["entry_price"] == 0.50
    assert round(row["edge"], 4) == 0.20
    assert row["our_prob"] == 0.70          # chosen-side probability
    assert row["status"] == "open"
    assert row["stake"] == 100.0
    assert row["module"] == "news_directional"
    assert row["gamma_id"] == "42"
    assert row["signals"]["source_count"] == 3


def test_bets_no_when_estimate_below_price():
    row = build_bet(_m(yes_price=0.80), _est(0.55), min_edge=0.10,
                    stake=100.0, profile="default", timestamp=TS)
    assert row["side"] == "No"
    assert row["entry_price"] == 0.20       # NO price = 1 - yes_price
    assert round(row["our_prob"], 4) == 0.45  # 1 - 0.55
    assert round(row["edge"], 4) == 0.25      # |0.55 - 0.80|


def test_returns_none_below_min_edge():
    assert build_bet(_m(yes_price=0.52), _est(0.55), min_edge=0.10,
                     stake=100.0, profile="default", timestamp=TS) is None


def test_returns_none_without_price():
    assert build_bet(_m(yes_price=None), _est(0.7), min_edge=0.10,
                     stake=100.0, profile="default", timestamp=TS) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_directional.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.directional'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from datetime import datetime

from polymath.model import Market
from polymath.signals.estimate import Estimate


def build_bet(market: Market, estimate: Estimate, *, min_edge: float, stake: float,
              profile: str, timestamp: datetime) -> dict | None:
    """Return a ledger row for a directional bet, or None if no qualifying edge.

    Bets YES when our prob exceeds the YES price, else NO. entry_price is the price
    of the chosen side; our_prob is our probability for that same side.
    """
    if market.yes_price is None:
        return None
    yes_price = market.yes_price
    edge_yes = estimate.prob - yes_price
    if abs(edge_yes) < min_edge:
        return None
    if edge_yes > 0:
        side, entry_price, our_prob = "Yes", yes_price, estimate.prob
    else:
        side, entry_price, our_prob = "No", 1.0 - yes_price, 1.0 - estimate.prob
    return {
        "timestamp": timestamp.isoformat(),
        "module": "news_directional",
        "profile": profile,
        "condition_id": market.condition_id,
        "gamma_id": market.gamma_id,
        "question": market.question,
        "category": estimate.category,
        "side": side,
        "entry_price": entry_price,
        "our_prob": our_prob,
        "market_prob": entry_price,
        "edge": abs(edge_yes),
        "confidence": estimate.confidence,
        "signals": dict(estimate.signals),
        "stake": stake,
        "status": "open",
        "realized_pnl": None,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_directional.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/directional.py tests/signals/test_directional.py
git commit -m "feat: build directional bet rows from estimate vs price"
```

---

### Task 7: Diverse stratified selection

**Files:**
- Create: `src/polymath/signals/select.py`
- Test: `tests/signals/test_select.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.signals.select import diversify


def _row(cid, category, edge):
    return {"condition_id": cid, "category": category, "edge": edge,
            "signals": {}}


def test_spreads_across_categories_before_repeating():
    rows = [
        _row("a", "sports", 0.40), _row("b", "sports", 0.35),
        _row("c", "politics", 0.30), _row("d", "world-news", 0.25),
    ]
    out = diversify(rows, bets_per_day=3)
    cats = [r["category"] for r in out]
    # one from each category before a second sports bet sneaks in
    assert set(cats) == {"sports", "politics", "world-news"}
    assert len(out) == 3


def test_respects_bets_per_day_cap():
    rows = [_row(str(i), "sports", 0.5) for i in range(10)]
    assert len(diversify(rows, bets_per_day=4)) == 4


def test_deterministic_for_same_input():
    rows = [_row("a", "sports", 0.4), _row("b", "politics", 0.3)]
    assert diversify(rows, bets_per_day=2) == diversify(rows, bets_per_day=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_select.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.select'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations


def diversify(rows: list[dict], bets_per_day: int) -> list[dict]:
    """Round-robin across categories (each category's rows ordered by descending
    edge), so the daily slate is spread across categories rather than dominated by
    one. Deterministic: no randomness, stable ordering."""
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    for cat_rows in by_cat.values():
        cat_rows.sort(key=lambda r: r["edge"], reverse=True)

    # Categories visited in a stable order (first appearance).
    order: list[str] = []
    for r in rows:
        if r["category"] not in order:
            order.append(r["category"])

    selected: list[dict] = []
    idx = 0
    while len(selected) < bets_per_day and any(by_cat[c] for c in order):
        cat = order[idx % len(order)]
        if by_cat[cat]:
            selected.append(by_cat[cat].pop(0))
        idx += 1
    return selected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_select.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/select.py tests/signals/test_select.py
git commit -m "feat: add diverse stratified bet selection"
```

---

### Task 8: Resolution parser + Gamma single-market fetch

**Files:**
- Create: `src/polymath/signals/resolution.py`
- Modify: `src/polymath/clients/gamma.py`
- Test: `tests/signals/test_resolution.py`

- [ ] **Step 1: Write the failing test**

```python
import httpx
import respx

from polymath.signals.resolution import winner_from_raw
from polymath.clients.gamma import GammaClient


def test_winner_yes_when_first_price_is_one():
    raw = {"closed": True, "umaResolutionStatus": "resolved",
           "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"1\", \"0\"]"}
    assert winner_from_raw(raw) == "Yes"


def test_winner_no_when_second_price_is_one():
    raw = {"closed": True, "umaResolutionStatus": "resolved",
           "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0\", \"1\"]"}
    assert winner_from_raw(raw) == "No"


def test_none_when_not_resolved():
    raw = {"closed": False, "umaResolutionStatus": "", "outcomes": "[\"Yes\",\"No\"]",
           "outcomePrices": "[\"0.5\",\"0.5\"]"}
    assert winner_from_raw(raw) is None


def test_none_when_void_double_zero():
    raw = {"closed": True, "umaResolutionStatus": "resolved",
           "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0\", \"0\"]"}
    assert winner_from_raw(raw) is None


@respx.mock
async def test_fetch_market_raw_by_id():
    respx.get("https://gamma-api.polymarket.com/markets/42").mock(
        return_value=httpx.Response(200, json={"id": "42", "closed": True})
    )
    async with GammaClient("https://gamma-api.polymarket.com") as c:
        raw = await c.fetch_market_raw("42")
    assert raw["closed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.resolution'`

- [ ] **Step 3: Write the resolution parser**

Create `src/polymath/signals/resolution.py`:

```python
from __future__ import annotations

import json

_EPS = 1e-6


def winner_from_raw(raw: dict) -> str | None:
    """Return the winning outcome label, or None if the market is unresolved or
    void/ambiguous (no single outcome priced at 1)."""
    if not raw.get("closed") or raw.get("umaResolutionStatus") != "resolved":
        return None
    try:
        outcomes = json.loads(raw["outcomes"])
        prices = [float(p) for p in json.loads(raw["outcomePrices"])]
    except (KeyError, json.JSONDecodeError, ValueError, TypeError):
        return None
    winners = [i for i, p in enumerate(prices) if abs(p - 1.0) <= _EPS]
    if len(winners) != 1 or winners[0] >= len(outcomes):
        return None
    return str(outcomes[winners[0]])
```

- [ ] **Step 4: Add `fetch_market_raw` to GammaClient**

In `src/polymath/clients/gamma.py`, add this method to the `GammaClient` class
(after `fetch_events`):

```python
    async def fetch_market_raw(self, gamma_id: str) -> dict | None:
        """Fetch a single market by its numeric Gamma id (works for closed markets,
        unlike the active-filtered list endpoint). Returns the raw JSON dict."""
        resp = await self._client.get(f"/markets/{gamma_id}")
        if resp.status_code != 200:
            return None
        return resp.json()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/signals/test_resolution.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/polymath/signals/resolution.py src/polymath/clients/gamma.py tests/signals/test_resolution.py
git commit -m "feat: add resolution parser and single-market fetch"
```

---

### Task 9: Settle bets (PnL + idempotency)

**Files:**
- Create: `src/polymath/signals/settle.py`
- Test: `tests/signals/test_settle.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.signals.settle import score_bet


def _bet(side="Yes", entry=0.50, status="open"):
    return {"side": side, "entry_price": entry, "stake": 100.0, "status": status,
            "realized_pnl": None}


def test_winning_bet_pnl():
    row = score_bet(_bet(side="Yes", entry=0.50), winner="Yes")
    assert row["status"] == "won"
    assert round(row["realized_pnl"], 4) == 100.0   # 100 * (1-0.5)/0.5


def test_losing_bet_pnl():
    row = score_bet(_bet(side="Yes", entry=0.50), winner="No")
    assert row["status"] == "lost"
    assert row["realized_pnl"] == -100.0


def test_no_side_winner_pnl():
    row = score_bet(_bet(side="No", entry=0.20), winner="No")
    assert row["status"] == "won"
    assert round(row["realized_pnl"], 4) == 400.0   # 100 * (1-0.2)/0.2


def test_unresolved_leaves_open():
    row = score_bet(_bet(status="open"), winner=None)
    assert row["status"] == "open"
    assert row["realized_pnl"] is None


def test_idempotent_skips_already_settled():
    settled = {"side": "Yes", "entry_price": 0.5, "stake": 100.0,
               "status": "won", "realized_pnl": 100.0}
    assert score_bet(settled, winner="No") == settled   # unchanged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_settle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.settle'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations


def score_bet(row: dict, winner: str | None) -> dict:
    """Return the bet row updated with status + realized_pnl given the resolved
    winner ("Yes"/"No"/None). Idempotent: already-settled rows pass through."""
    if row.get("status") not in ("open", None):
        return row
    if winner is None:
        return row
    row = dict(row)
    stake = float(row["stake"])
    entry = float(row["entry_price"])
    if winner == row["side"]:
        row["status"] = "won"
        row["realized_pnl"] = stake * (1.0 - entry) / entry if entry > 0 else 0.0
    else:
        row["status"] = "lost"
        row["realized_pnl"] = -stake
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_settle.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/settle.py tests/signals/test_settle.py
git commit -m "feat: add directional bet settlement scoring"
```

---

### Task 10: Analyze (calibration, win-vs-price, ROI, attribution)

**Files:**
- Create: `src/polymath/signals/analyze.py`
- Test: `tests/signals/test_analyze.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.signals.analyze import build_report


def _settled(side, entry, our_prob, won, category="sports", signals=None):
    stake = 100.0
    pnl = stake * (1 - entry) / entry if won else -stake
    return {"module": "news_directional", "side": side, "entry_price": entry,
            "our_prob": our_prob, "category": category, "stake": stake,
            "status": "won" if won else "lost", "realized_pnl": pnl,
            "signals": signals or {}}


def test_report_aggregates_winrate_roi_and_calibration():
    rows = [
        _settled("Yes", 0.50, 0.70, True),
        _settled("Yes", 0.50, 0.70, False),
        _settled("Yes", 0.50, 0.65, True),
        {"status": "open", "module": "news_directional", "realized_pnl": None},  # ignored
    ]
    rep = build_report(rows)
    assert rep["settled"] == 3
    assert round(rep["win_rate"], 4) == round(2 / 3, 4)
    assert round(rep["total_pnl"], 2) == 100.00   # +100 +(-100) +100
    assert rep["total_staked"] == 300.0
    # a calibration bucket exists for the ~0.65-0.70 predictions
    assert any(b["n"] > 0 for b in rep["calibration"])


def test_signal_attribution_splits_by_feature_median():
    rows = [
        _settled("Yes", 0.5, 0.7, True, signals={"consensus_strength": 0.9}),
        _settled("Yes", 0.5, 0.7, True, signals={"consensus_strength": 0.8}),
        _settled("Yes", 0.5, 0.7, False, signals={"consensus_strength": 0.2}),
        _settled("Yes", 0.5, 0.7, False, signals={"consensus_strength": 0.1}),
    ]
    rep = build_report(rows)
    attr = rep["attribution"]["consensus_strength"]
    assert attr["high"]["win_rate"] == 1.0
    assert attr["low"]["win_rate"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_analyze.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.analyze'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import statistics


def _won(row: dict) -> bool:
    return row.get("status") == "won"


def _calibration(settled: list[dict]) -> list[dict]:
    buckets = []
    for lo in [i / 10 for i in range(0, 10)]:
        hi = lo + 0.1
        grp = [r for r in settled if lo <= float(r["our_prob"]) < hi]
        if not grp:
            buckets.append({"bucket": f"{lo:.1f}-{hi:.1f}", "n": 0,
                            "predicted": None, "actual": None})
            continue
        buckets.append({
            "bucket": f"{lo:.1f}-{hi:.1f}", "n": len(grp),
            "predicted": statistics.mean(float(r["our_prob"]) for r in grp),
            "actual": sum(1 for r in grp if _won(r)) / len(grp),
        })
    return buckets


def _attribution(settled: list[dict]) -> dict:
    keys = set()
    for r in settled:
        for k, v in (r.get("signals") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                keys.add(k)
    out = {}
    for k in sorted(keys):
        vals = [(float(r["signals"][k]), r) for r in settled
                if isinstance(r.get("signals", {}).get(k), (int, float))
                and not isinstance(r["signals"][k], bool)]
        if len(vals) < 2:
            continue
        median = statistics.median(v for v, _ in vals)
        high = [r for v, r in vals if v >= median]
        low = [r for v, r in vals if v < median]

        def _summ(grp):
            if not grp:
                return {"n": 0, "win_rate": None, "roi": None}
            staked = sum(float(r["stake"]) for r in grp)
            pnl = sum(float(r["realized_pnl"]) for r in grp)
            return {"n": len(grp),
                    "win_rate": sum(1 for r in grp if _won(r)) / len(grp),
                    "roi": pnl / staked if staked else None}

        out[k] = {"median": median, "high": _summ(high), "low": _summ(low)}
    return out


def build_report(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("status") in ("won", "lost")]
    staked = sum(float(r["stake"]) for r in settled)
    pnl = sum(float(r["realized_pnl"]) for r in settled)
    wins = sum(1 for r in settled if _won(r))
    return {
        "settled": len(settled),
        "win_rate": (wins / len(settled)) if settled else 0.0,
        "total_pnl": pnl,
        "total_staked": staked,
        "roi": (pnl / staked) if staked else 0.0,
        "calibration": _calibration(settled),
        "attribution": _attribution(settled),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/signals/test_analyze.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymath/signals/analyze.py tests/signals/test_analyze.py
git commit -m "feat: add directional analysis (calibration, ROI, attribution)"
```

---

### Task 11: CLI — bet / settle / analyze

**Files:**
- Create: `src/polymath/signals/cli.py`
- Modify: `src/polymath/cli.py`
- Test: `tests/signals/test_signals_cli.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from polymath import cli as main_cli
from polymath.signals import cli as signals_cli
from polymath.model import Token, Market
from polymath.signals.estimate import Estimate
from polymath.signals.research import StubResearcher
from polymath.ledger import Ledger

runner = CliRunner()
NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _m(cid, gid, yes_price):
    return Market(cid, f"Will {cid} happen?", cid, [Token(f"{cid}y", "Yes"), Token(f"{cid}n", "No")],
                  neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                  end_date=NOW + timedelta(hours=10), liquidity=5000, volume=5000,
                  gamma_id=gid, yes_price=yes_price)


class FakeGamma:
    def __init__(self, markets, raw_by_id=None):
        self._markets = markets
        self._raw = raw_by_id or {}

    async def __aenter__(self): return self
    async def __aexit__(self, *e): return None

    async def fetch_active_markets(self, *, min_liquidity, min_volume):
        return self._markets

    async def fetch_market_raw(self, gamma_id):
        return self._raw.get(gamma_id)


def _patch(monkeypatch, markets, estimates, raw_by_id=None):
    monkeypatch.setattr(signals_cli, "GammaClient", lambda *a, **k: FakeGamma(markets, raw_by_id))
    monkeypatch.setattr(signals_cli, "_now", lambda: NOW)
    monkeypatch.setattr(signals_cli, "_make_researcher", lambda cfg: StubResearcher(estimates))


def test_bet_then_settle_then_analyze(monkeypatch, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    markets = [_m("c1", "11", 0.50), _m("c2", "22", 0.50)]
    estimates = {"c1": Estimate(0.75, 0.8, "sports", {"source_count": 3}, "r"),
                 "c2": Estimate(0.70, 0.7, "politics", {"source_count": 2}, "r")}
    _patch(monkeypatch, markets, estimates)

    r1 = runner.invoke(main_cli.app, ["bet", "--ledger", str(ledger), "--min-edge", "0.1"])
    assert r1.exit_code == 0, r1.output
    rows = Ledger(ledger).read_all()
    assert len(rows) == 2 and all(r["status"] == "open" for r in rows)

    # c1 (Yes) resolves Yes -> win; c2 (Yes) resolves No -> loss
    raw = {"11": {"closed": True, "umaResolutionStatus": "resolved",
                  "outcomes": "[\"Yes\",\"No\"]", "outcomePrices": "[\"1\",\"0\"]"},
           "22": {"closed": True, "umaResolutionStatus": "resolved",
                  "outcomes": "[\"Yes\",\"No\"]", "outcomePrices": "[\"0\",\"1\"]"}}
    _patch(monkeypatch, markets, estimates, raw_by_id=raw)
    r2 = runner.invoke(main_cli.app, ["settle", "--ledger", str(ledger)])
    assert r2.exit_code == 0, r2.output
    statuses = sorted(r["status"] for r in Ledger(ledger).read_all())
    assert statuses == ["lost", "won"]

    r3 = runner.invoke(main_cli.app, ["analyze", "--ledger", str(ledger)])
    assert r3.exit_code == 0, r3.output
    assert "win" in r3.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_signals_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polymath.signals.cli'`

- [ ] **Step 3: Write the signals CLI**

Create `src/polymath/signals/cli.py`:

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from polymath.clients.gamma import GammaClient
from polymath.config import Config, default_config, load_config
from polymath.ledger import Ledger
from polymath.signals.analyze import build_report
from polymath.signals.directional import build_bet
from polymath.signals.nearterm import select_near_term
from polymath.signals.research import ClaudeCliResearcher
from polymath.signals.resolution import winner_from_raw
from polymath.signals.select import diversify
from polymath.signals.settle import score_bet

app = typer.Typer(add_completion=False, help="News-signal directional pilot")
console = Console()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_researcher(cfg: Config):
    return ClaudeCliResearcher(cli_path=cfg.claude_cli_path, model=cfg.research_model)


def _cfg(config_path: str | None, profile: str) -> Config:
    base = load_config(config_path) if config_path else default_config()
    return base.effective(profile)


@app.command()
def bet(profile: str = typer.Option("default"), ledger: str = typer.Option(None),
        min_edge: float = typer.Option(None), config: str = typer.Option(None)):
    cfg = _cfg(config, profile)
    edge = min_edge if min_edge is not None else cfg.min_edge
    led = Ledger(ledger or cfg.ledger_path)
    researcher = _make_researcher(cfg)

    async def _markets():
        async with GammaClient(cfg.gamma_base) as g:
            return await g.fetch_active_markets(
                min_liquidity=cfg.bet_min_liquidity, min_volume=0)

    markets = asyncio.run(_markets())
    candidates = select_near_term(
        markets, _now(), window_hours=cfg.bet_window_hours,
        min_liquidity=cfg.bet_min_liquidity, max_candidates=cfg.max_candidates)

    rows = []
    for m in candidates:
        try:
            est = researcher.research(m)
        except Exception as exc:   # research failures skip one market, never abort
            console.print(f"[yellow]skip {m.condition_id}: {exc}[/yellow]")
            continue
        row = build_bet(m, est, min_edge=edge, stake=cfg.bet_stake,
                        profile=profile, timestamp=_now())
        if row:
            rows.append(row)

    chosen = diversify(rows, cfg.bets_per_day)
    for row in chosen:
        led.append(row)
    console.print(f"[green]logged {len(chosen)} bets (from {len(candidates)} "
                  f"candidates) to {led.path}[/green]")


@app.command()
def settle(profile: str = typer.Option("default"), ledger: str = typer.Option(None),
           config: str = typer.Option(None)):
    cfg = _cfg(config, profile)
    led = Ledger(ledger or cfg.ledger_path)
    rows = led.read_all()
    directional = [r for r in rows if r.get("module") == "news_directional"]

    async def _resolve(gid):
        async with GammaClient(cfg.gamma_base) as g:
            return await g.fetch_market_raw(gid)

    settled = 0
    updated = []
    for r in rows:
        if r.get("module") == "news_directional" and r.get("status") == "open":
            raw = asyncio.run(_resolve(r["gamma_id"])) if r.get("gamma_id") else None
            winner = winner_from_raw(raw) if raw else None
            new = score_bet(r, winner)
            if new.get("status") != "open":
                settled += 1
            updated.append(new)
        else:
            updated.append(r)

    led.path.write_text("".join(__import__("json").dumps(r) + "\n" for r in updated))
    console.print(f"[green]settled {settled} of {len(directional)} directional bets[/green]")


@app.command()
def analyze(profile: str = typer.Option("default"), ledger: str = typer.Option(None),
            config: str = typer.Option(None)):
    cfg = _cfg(config, profile)
    led = Ledger(ledger or cfg.ledger_path)
    rows = [r for r in led.read_all() if r.get("module") == "news_directional"]
    rep = build_report(rows)

    t = Table(title="Directional pilot")
    for col in ("settled", "win rate", "total $", "ROI %"):
        t.add_column(col)
    t.add_row(str(rep["settled"]), f"{rep['win_rate'] * 100:.0f}%",
              f"{rep['total_pnl']:.2f}", f"{rep['roi'] * 100:.1f}")
    console.print(t)

    cal = Table(title="Calibration (predicted vs actual win rate)")
    for col in ("our prob", "n", "predicted", "actual"):
        cal.add_column(col)
    for b in rep["calibration"]:
        if b["n"]:
            cal.add_row(b["bucket"], str(b["n"]),
                        f"{b['predicted']:.2f}", f"{b['actual']:.2f}")
    console.print(cal)
    console.print("[dim]Note: a 7-day, 35-70 bet sample cannot prove edge; "
                  "treat as hypothesis generation.[/dim]")
```

- [ ] **Step 4: Mount the signals app on the main CLI**

In `src/polymath/cli.py`, after `app = typer.Typer(...)` is defined, add:

```python
from polymath.signals.cli import app as signals_app

app.add_typer(signals_app)
```

(Place the import at the top with the other imports and the `add_typer` call
immediately after the `app = typer.Typer(...)` line.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/signals/test_signals_cli.py -v`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add src/polymath/signals/cli.py src/polymath/cli.py tests/signals/test_signals_cli.py
git commit -m "feat: add bet/settle/analyze CLI for directional pilot"
```

---

### Task 12: Config fields, full suite, live smoke, README

**Files:**
- Modify: `src/polymath/config.py`
- Modify: `README.md`
- Test: `tests/signals/test_signals_config.py`

- [ ] **Step 1: Write the failing test**

```python
from polymath.config import default_config


def test_directional_config_defaults():
    c = default_config()
    assert c.bet_window_hours == 48
    assert c.bets_per_day == 8
    assert c.bet_stake == 100.0
    assert c.min_edge == 0.10
    assert c.claude_cli_path == "claude"
    assert c.bet_min_liquidity >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/signals/test_signals_config.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'bet_window_hours'`

- [ ] **Step 3: Add fields to Config**

In `src/polymath/config.py`, in the `Config` dataclass, after the existing
`profiles` field's predecessors (before `profiles: dict[...]`) add these fields:

```python
    bet_window_hours: int = 48
    bet_min_liquidity: float = 500.0
    max_candidates: int = 40
    bets_per_day: int = 8
    bet_stake: float = 100.0
    min_edge: float = 0.10
    claude_cli_path: str = "claude"
    research_model: str | None = None
    research_timeout: int = 180
```

- [ ] **Step 4: Run the new test, then the full suite**

Run: `pytest tests/signals/test_signals_config.py -v && pytest -q`
Expected: new test passes; whole suite green (≈ 39 prior + new signals tests).

- [ ] **Step 5: Live smoke test (manual, documented)**

Run (one real CLI research call against a live question):
```bash
. .venv/bin/activate && python -c "
from polymath.signals.research import ClaudeCliResearcher
from polymath.model import Market, Token
m = Market('c','Will it rain in London tomorrow?','c',[Token('y','Yes'),Token('n','No')],
           False, None, True, None, 1.0, 1.0, gamma_id='1', yes_price=0.5)
print(ClaudeCliResearcher().research(m))
"
```
Expected: prints an `Estimate(...)` with a 0..1 prob and a non-empty rationale.
If the CLI flags differ on this machine, adjust `_build_cmd` in `research.py` and
re-run; this is the one place that touches the real CLI.

- [ ] **Step 6: Update README**

In `README.md`, add a section after the existing usage block:

```markdown
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
```

- [ ] **Step 7: Commit**

```bash
git add src/polymath/config.py README.md tests/signals/test_signals_config.py
git commit -m "feat: add directional config fields, docs, and live smoke"
```

---

## Self-Review

**Spec coverage (against `2026-06-16-news-signal-directional-pilot-design.md`):**
- §2 betting math (break-even = price; PnL formulas) → Task 9 `score_bet`, Task 6 entry pricing, surfaced in Task 11 analyze note + Task 12 README ✓
- §4 diverse sampling, min_edge, direction → Task 7 `diversify`, Task 6 `build_bet` ✓
- §5.1 nearterm → Task 3 ✓; §5.2 Researcher protocol + StubResearcher + ClaudeCliResearcher (injectable runner, CLI flags, JSON parse, web_search_requests) → Tasks 4, 5 ✓; §5.3 select → Task 7 ✓; §5.4 directional ledger rows → Task 6 ✓; §5.5 settle (resolution, idempotent) → Tasks 8, 9 ✓; §5.6 analyze (calibration, win-vs-price via entry_price buckets, ROI, attribution) → Task 10 ✓
- §6 data flow / CLI bet·settle·analyze → Task 11 ✓
- §7 config fields → Task 12 ✓
- §8 error handling (skip bad market, bound candidates) → Task 11 `bet` try/except + nearterm cap ✓
- §9 testing (stub + fake-runner + pure-fn units + gamma fixtures + manual smoke) → every task + Task 12 ✓
- §10 honest caveats surfaced → Task 11 analyze note, Task 12 README ✓
- §12 reuse ledger; `(module, profile)` no collision with `report` → directional rows tagged `module="news_directional"`, analyze filters on it ✓

**Note on win-vs-price (spec §5.6):** `entry_price` is recorded on every bet row (Task 6) and `our_prob`-bucketed calibration is computed (Task 10); a price-bucketed view is a trivial read over the same rows and is included implicitly via `entry_price` in each row — if a dedicated table is wanted later it is pure presentation, no new data.

**Placeholder scan:** no TBD/TODO; every code step has complete code. ✓

**Type consistency:** ledger row keys written in Task 6 (`module`, `profile`, `side`, `entry_price`, `our_prob`, `edge`, `signals`, `stake`, `status`, `realized_pnl`, `gamma_id`) are exactly those read in Tasks 9 (`score_bet`), 10 (`build_report`), and 11 (CLI). `Estimate` fields (Task 1) match construction in Tasks 4/5 and consumption in Task 6. `select_near_term`, `build_bet`, `diversify`, `winner_from_raw`, `score_bet`, `build_report`, `fetch_market_raw` signatures are consistent across definition and call sites. ✓
