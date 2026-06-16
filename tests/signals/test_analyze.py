from polymath.signals.analyze import build_report


def _settled(side, entry, our_prob, won, category="sports", signals=None):
    stake = 100.0
    pnl = stake * (1 - entry) / entry if won else -stake
    return {"module": "news_directional", "side": side, "entry_price": entry,
            "our_prob": our_prob, "category": category, "stake": stake,
            "status": "won" if won else "lost", "realized_pnl": pnl,
            "signals": signals or {}}


def test_report_aggregates_winrate_roi_and_calibration():
    rows = [
        _settled("Yes", 0.50, 0.70, True),
        _settled("Yes", 0.50, 0.70, False),
        _settled("Yes", 0.50, 0.65, True),
        {"status": "open", "module": "news_directional", "realized_pnl": None},
    ]
    rep = build_report(rows)
    assert rep["settled"] == 3
    assert round(rep["win_rate"], 4) == round(2 / 3, 4)
    assert round(rep["total_pnl"], 2) == 100.00
    assert rep["total_staked"] == 300.0
    assert any(b["n"] > 0 for b in rep["calibration"])


def test_calibration_includes_prob_one_in_top_bucket():
    # a NO bet with estimate.prob 0.0 -> our_prob 1.0 must not vanish from calibration
    rows = [_settled("No", 0.30, 1.0, True), _settled("No", 0.30, 1.0, False)]
    rep = build_report(rows)
    top = [b for b in rep["calibration"] if b["bucket"] == "0.9-1.0"][0]
    assert top["n"] == 2


def test_signal_attribution_splits_by_feature_median():
    rows = [
        _settled("Yes", 0.5, 0.7, True, signals={"consensus_strength": 0.9}),
        _settled("Yes", 0.5, 0.7, True, signals={"consensus_strength": 0.8}),
        _settled("Yes", 0.5, 0.7, False, signals={"consensus_strength": 0.2}),
        _settled("Yes", 0.5, 0.7, False, signals={"consensus_strength": 0.1}),
    ]
    rep = build_report(rows)
    attr = rep["attribution"]["consensus_strength"]
    assert attr["high"]["win_rate"] == 1.0
    assert attr["low"]["win_rate"] == 0.0
