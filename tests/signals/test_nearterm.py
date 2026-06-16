from datetime import datetime, timedelta, timezone

from polymath.model import Token, Market
from polymath.signals.nearterm import select_near_term

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _m(cid, hours, *, liq=1000.0, accepting=True, yes_price=0.5, binary=True,
       event_id=None):
    toks = [Token(f"{cid}y", "Yes"), Token(f"{cid}n", "No")]
    if not binary:
        toks = toks + [Token(f"{cid}z", "Maybe")]
    return Market(cid, f"Q{cid}", cid, toks, neg_risk=False, neg_risk_market_id=None,
                  accepting_orders=accepting, end_date=NOW + timedelta(hours=hours),
                  liquidity=liq, volume=liq, gamma_id=cid, yes_price=yes_price,
                  event_id=event_id)


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
                           max_candidates=2, max_per_event=2)
    assert [m.condition_id for m in out] == ["5", "4"]   # most liquid first


def test_caps_markets_per_event():
    # One event "E" has 5 sub-markets (high liquidity); two other distinct events.
    markets = (
        [_m(f"e{i}", 10, liq=1000.0 - i, event_id="E") for i in range(5)]
        + [_m("solo1", 10, liq=10.0, event_id="X")]
        + [_m("solo2", 10, liq=9.0, event_id="Y")]
    )
    out = select_near_term(markets, NOW, window_hours=48, min_liquidity=0,
                           max_candidates=40, max_per_event=2)
    from_e = [m.condition_id for m in out if m.condition_id.startswith("e")]
    assert len(from_e) == 2                       # event E capped at 2
    assert {"solo1", "solo2"} <= {m.condition_id for m in out}   # distinct events kept
