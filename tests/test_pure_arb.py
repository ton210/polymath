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


def test_binary_limit_price_is_worst_level_walked():
    # YES fills across two levels (0.40 x60 then 0.42 x60); NO single level 0.50.
    m = _binary_market("c1", "yes", "no")
    snap = _snap(
        [m],
        [OrderBook("yes", asks=[Level(0.40, 60), Level(0.42, 60)]),
         OrderBook("no", asks=[Level(0.50, 200)])],
    )
    opps = detect(snap, min_roi=0.0, min_profit_usd=0.0, fee_bps=0.0, profile="default")
    o = [o for o in opps if o.kind == "binary_yes_no"][0]
    # Profitable depth: marginal 0.40+0.50=0.90, then 0.42+0.50=0.92, both < 1 -> 120 sets.
    assert o.fillable_size == 120
    yes_leg = [l for l in o.legs if l.outcome == "Yes"][0]
    assert yes_leg.limit_price == 0.42   # worst level walked, not 0.40


def test_neg_risk_skips_event_with_nonbinary_member():
    m1 = _binary_market("c1", "y1", "n1", neg_risk=True, nrm="E")
    # c2 is non-binary (3 tokens) -> event must be skipped, not crash.
    m2 = Market("c2", "Q c2", "c2",
                tokens=[Token("a", "A"), Token("b", "B"), Token("c", "C")],
                neg_risk=True, neg_risk_market_id="E", accepting_orders=True,
                end_date=None, liquidity=1.0, volume=1.0)
    event = Event(id="E", title="race", neg_risk=True,
                  market_condition_ids=["c1", "c2"])
    snap = _snap(
        [m1, m2],
        [OrderBook("y1", asks=[Level(0.10, 100)]), OrderBook("n1")],
        events={"E": event},
    )
    opps = detect(snap, min_roi=0.0, min_profit_usd=0.0, fee_bps=0.0, profile="default")
    assert [o for o in opps if o.kind == "neg_risk_set"] == []


def test_binary_sell_set_respects_min_profit():
    m = _binary_market("c1", "yes", "no")
    snap = _snap(
        [m],
        [OrderBook("yes", bids=[Level(0.52, 100)]),
         OrderBook("no", bids=[Level(0.50, 100)])],   # sum 1.02 -> net 2.0 on 100
    )
    # net = 100 * 0.02 = 2.0; threshold 5.0 filters it out.
    opps = detect(snap, min_roi=0.0, min_profit_usd=5.0, fee_bps=0.0, profile="default")
    assert [o for o in opps if o.kind == "sell_set"] == []


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
