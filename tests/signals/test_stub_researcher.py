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
