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
