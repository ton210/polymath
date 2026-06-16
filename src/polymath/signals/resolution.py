from __future__ import annotations

import json

# A resolved market's winning token redeems at $1; tolerate minor rounding (e.g.
# 0.999) so a genuinely-resolved winner still settles rather than hanging "open".
_WIN_THRESHOLD = 0.99


def winner_from_raw(raw: dict) -> str | None:
    """Return the winning outcome label, or None if the market is unresolved or
    void/ambiguous (no single outcome priced at ~1)."""
    if not raw.get("closed") or raw.get("umaResolutionStatus") != "resolved":
        return None
    try:
        outcomes = json.loads(raw["outcomes"])
        prices = [float(p) for p in json.loads(raw["outcomePrices"])]
    except (KeyError, json.JSONDecodeError, ValueError, TypeError):
        return None
    winners = [i for i, p in enumerate(prices) if p >= _WIN_THRESHOLD]
    if len(winners) != 1 or winners[0] >= len(outcomes):
        return None
    return str(outcomes[winners[0]])
