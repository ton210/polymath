from polymath.signals.select import diversify


def _row(cid, category, edge):
    return {"condition_id": cid, "category": category, "edge": edge, "signals": {}}


def test_spreads_across_categories_before_repeating():
    rows = [
        _row("a", "sports", 0.40), _row("b", "sports", 0.35),
        _row("c", "politics", 0.30), _row("d", "world-news", 0.25),
    ]
    out = diversify(rows, bets_per_day=3)
    cats = [r["category"] for r in out]
    assert set(cats) == {"sports", "politics", "world-news"}
    assert len(out) == 3


def test_respects_bets_per_day_cap():
    rows = [_row(str(i), "sports", 0.5) for i in range(10)]
    assert len(diversify(rows, bets_per_day=4)) == 4


def test_deterministic_for_same_input():
    rows = [_row("a", "sports", 0.4), _row("b", "politics", 0.3)]
    assert diversify(rows, bets_per_day=2) == diversify(rows, bets_per_day=2)
