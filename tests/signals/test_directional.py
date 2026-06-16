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


def _est(prob, category="sports", rationale="r"):
    return Estimate(prob=prob, confidence=0.7, category=category,
                    signals={"source_count": 3}, rationale=rationale)


def test_bets_yes_when_estimate_above_price():
    row = build_bet(_m(yes_price=0.50), _est(0.70), min_edge=0.10,
                    stake=100.0, profile="default", timestamp=TS)
    assert row["side"] == "Yes"
    assert row["entry_price"] == 0.50
    assert round(row["edge"], 4) == 0.20
    assert row["our_prob"] == 0.70
    assert row["status"] == "open"
    assert row["stake"] == 100.0
    assert row["module"] == "news_directional"
    assert row["gamma_id"] == "42"
    assert row["signals"]["source_count"] == 3


def test_bets_no_when_estimate_below_price():
    row = build_bet(_m(yes_price=0.80), _est(0.55), min_edge=0.10,
                    stake=100.0, profile="default", timestamp=TS)
    assert row["side"] == "No"
    assert row["entry_price"] == 0.20
    assert round(row["our_prob"], 4) == 0.45
    assert round(row["edge"], 4) == 0.25


def test_returns_none_below_min_edge():
    assert build_bet(_m(yes_price=0.52), _est(0.55), min_edge=0.10,
                     stake=100.0, profile="default", timestamp=TS) is None


def test_returns_none_without_price():
    assert build_bet(_m(yes_price=None), _est(0.7), min_edge=0.10,
                     stake=100.0, profile="default", timestamp=TS) is None


def test_persists_rationale():
    row = build_bet(_m(yes_price=0.50), _est(0.70, rationale="home team favored"),
                    min_edge=0.10, stake=100.0, profile="default", timestamp=TS)
    assert row["rationale"] == "home team favored"


def test_skips_implausibly_large_edge_as_misread():
    # market priced 0.04, model says 0.97 -> edge 0.93: almost surely a misread.
    row = build_bet(_m(yes_price=0.04), _est(0.97), min_edge=0.05, max_edge=0.25,
                    stake=100.0, profile="default", timestamp=TS)
    assert row is None


def test_keeps_edge_at_max_boundary():
    row = build_bet(_m(yes_price=0.50), _est(0.75), min_edge=0.05, max_edge=0.25,
                    stake=100.0, profile="default", timestamp=TS)
    assert row is not None and round(row["edge"], 4) == 0.25
