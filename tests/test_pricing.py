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
