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
