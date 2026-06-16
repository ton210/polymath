from __future__ import annotations

from datetime import datetime

from polymath.model import Market
from polymath.signals.estimate import Estimate


def build_bet(market: Market, estimate: Estimate, *, min_edge: float, stake: float,
              profile: str, timestamp: datetime) -> dict | None:
    """Return a ledger row for a directional bet, or None if no qualifying edge.

    Bets YES when our prob exceeds the YES price, else NO. entry_price is the price
    of the chosen side; our_prob is our probability for that same side.
    """
    if market.yes_price is None:
        return None
    yes_price = market.yes_price
    edge_yes = estimate.prob - yes_price
    if abs(edge_yes) < min_edge:
        return None
    if edge_yes > 0:
        side, entry_price, our_prob = "Yes", yes_price, estimate.prob
    else:
        # round to shed float noise (1.0 - 0.80 == 0.19999...) before it reaches PnL
        side = "No"
        entry_price = round(1.0 - yes_price, 6)
        our_prob = round(1.0 - estimate.prob, 6)
    return {
        "timestamp": timestamp.isoformat(),
        "module": "news_directional",
        "profile": profile,
        "condition_id": market.condition_id,
        "gamma_id": market.gamma_id,
        "question": market.question,
        "category": estimate.category,
        "side": side,
        "entry_price": entry_price,
        "our_prob": our_prob,
        "market_prob": entry_price,
        "edge": abs(edge_yes),
        "confidence": estimate.confidence,
        "signals": dict(estimate.signals),
        "stake": stake,
        "status": "open",
        "realized_pnl": None,
    }
