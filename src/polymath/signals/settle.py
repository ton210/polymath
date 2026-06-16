from __future__ import annotations


def score_bet(row: dict, winner: str | None) -> dict:
    """Return the bet row updated with status + realized_pnl given the resolved
    winner ("Yes"/"No"/None). Idempotent: already-settled rows pass through."""
    if row.get("status") not in ("open", None):
        return row
    if winner is None:
        return row
    row = dict(row)
    stake = float(row["stake"])
    entry = float(row["entry_price"])
    if winner == row["side"]:
        row["status"] = "won"
        row["realized_pnl"] = stake * (1.0 - entry) / entry if entry > 0 else 0.0
    else:
        row["status"] = "lost"
        row["realized_pnl"] = -stake
    return row
