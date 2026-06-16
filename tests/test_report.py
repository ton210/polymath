from polymath.report import build_scorecard


def _row(module, profile, status, pnl):
    return {"module": module, "profile": profile, "status": status,
            "realized_pnl": pnl}


def test_groups_by_module_and_profile():
    rows = [
        _row("pure_arb", "default", "entered", 5.0),
        _row("pure_arb", "default", "entered", 3.0),
        _row("pure_arb", "aggressive", "entered", -1.0),
        _row("pure_arb", "default", "deduped", 0.0),   # ignored in PnL stats
    ]
    cards = {(c.module, c.profile): c for c in build_scorecard(rows, min_entered=2)}
    d = cards[("pure_arb", "default")]
    assert d.entered == 2
    assert round(d.total_pnl, 4) == 8.0
    assert d.hit_rate == 1.0
    assert d.verdict == "consistent"

    a = cards[("pure_arb", "aggressive")]
    assert a.entered == 1
    assert a.verdict == "insufficient-data"   # below min_entered


def test_negative_total_marks_negative_verdict():
    rows = [
        _row("pure_arb", "default", "entered", -2.0),
        _row("pure_arb", "default", "entered", -3.0),
    ]
    card = build_scorecard(rows, min_entered=2)[0]
    assert card.total_pnl == -5.0
    assert card.hit_rate == 0.0
    assert card.verdict == "negative"
