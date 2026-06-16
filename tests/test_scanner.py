from datetime import datetime, timezone

from polymath.model import Level, OrderBook, Token, Market
from polymath.config import default_config
from polymath.scanner import build_snapshot, run_detectors


class FakeGamma:
    def __init__(self, markets, events=None):
        self._markets = markets
        self._events = events or {}   # event_id -> (title, [Market])

    async def fetch_active_markets(self, *, min_liquidity, min_volume):
        return self._markets

    async def fetch_events(self, event_ids):
        return {e: self._events[e] for e in event_ids if e in self._events}


class FakeClob:
    def __init__(self, books):
        self._books = books

    async def fetch_books(self, token_ids):
        return {t: self._books[t] for t in token_ids if t in self._books}


def _m(cid, yes, no, event_id=None):
    return Market(cid, f"Q{cid}", cid, [Token(yes, "Yes"), Token(no, "No")],
                  neg_risk=event_id is not None, neg_risk_market_id="NRM",
                  accepting_orders=True, end_date=None, liquidity=9999, volume=9999,
                  event_id=event_id)


async def test_build_snapshot_groups_events_from_authoritative_membership():
    # Filter returned only c1, c2 — but the full event E has c1, c2, c3.
    m1, m2, m3 = _m("c1", "y1", "n1", "E"), _m("c2", "y2", "n2", "E"), _m("c3", "y3", "n3", "E")
    events = {"E": ("race", [m1, m2, m3])}
    books = {tid: OrderBook(tid) for tid in ["y1", "n1", "y2", "n2", "y3", "n3"]}
    snap = await build_snapshot(FakeGamma([m1, m2], events), FakeClob(books), default_config())
    # c3 (filtered out of the main scan) is added back from authoritative membership.
    assert set(snap.events["E"].market_condition_ids) == {"c1", "c2", "c3"}
    assert "c3" in snap.markets
    assert {"y3", "n3"} <= set(snap.books)   # books fetched for the recovered member
    assert snap.timestamp.tzinfo == timezone.utc


async def test_truncated_negrisk_set_is_not_a_false_arb():
    # YES asks of c1+c2 sum to 0.40 (<$1) — looks like a juicy arb — but the full
    # event has a third outcome c3 with NO book (can't complete the hedge).
    m1, m2, m3 = _m("c1", "y1", "n1", "E"), _m("c2", "y2", "n2", "E"), _m("c3", "y3", "n3", "E")
    events = {"E": ("race", [m1, m2, m3])}
    books = {
        "y1": OrderBook("y1", asks=[Level(0.20, 100)]),
        "y2": OrderBook("y2", asks=[Level(0.20, 100)]),
        "y3": OrderBook("y3"),   # no asks -> outcome not buyable -> set incomplete
        "n1": OrderBook("n1"), "n2": OrderBook("n2"), "n3": OrderBook("n3"),
    }
    snap = await build_snapshot(FakeGamma([m1, m2], events), FakeClob(books), default_config())
    opps = run_detectors(snap, default_config(), profile="default")
    # Must NOT emit a neg-risk arb on the incomplete (truncated) set.
    assert [o for o in opps if o.kind == "neg_risk_set"] == []


async def test_run_detectors_finds_binary_arb():
    markets = [_m("c1", "yes", "no")]
    books = {"yes": OrderBook("yes", asks=[Level(0.45, 100)]),
             "no": OrderBook("no", asks=[Level(0.50, 100)])}
    snap = await build_snapshot(FakeGamma(markets), FakeClob(books), default_config())
    opps = run_detectors(snap, default_config(), profile="default")
    assert any(o.kind == "binary_yes_no" for o in opps)
