from polymath.signals.settle import score_bet


def _bet(side="Yes", entry=0.50, status="open"):
    return {"side": side, "entry_price": entry, "stake": 100.0, "status": status,
            "realized_pnl": None}


def test_winning_bet_pnl():
    row = score_bet(_bet(side="Yes", entry=0.50), winner="Yes")
    assert row["status"] == "won"
    assert round(row["realized_pnl"], 4) == 100.0


def test_losing_bet_pnl():
    row = score_bet(_bet(side="Yes", entry=0.50), winner="No")
    assert row["status"] == "lost"
    assert row["realized_pnl"] == -100.0


def test_no_side_winner_pnl():
    row = score_bet(_bet(side="No", entry=0.20), winner="No")
    assert row["status"] == "won"
    assert round(row["realized_pnl"], 4) == 400.0


def test_unresolved_leaves_open():
    row = score_bet(_bet(status="open"), winner=None)
    assert row["status"] == "open"
    assert row["realized_pnl"] is None


def test_idempotent_skips_already_settled():
    settled = {"side": "Yes", "entry_price": 0.5, "stake": 100.0,
               "status": "won", "realized_pnl": 100.0}
    assert score_bet(settled, winner="No") == settled
