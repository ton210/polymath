from __future__ import annotations

from datetime import datetime, timedelta

from polymath.model import Market


def select_near_term(markets: list[Market], now: datetime, *, window_hours: int,
                     min_liquidity: float, max_candidates: int) -> list[Market]:
    """Markets resolving within the window that are tradeable, binary, priced, and
    liquid — capped to the most-liquid ``max_candidates`` to bound research cost."""
    horizon = now + timedelta(hours=window_hours)
    eligible = [
        m for m in markets
        if m.accepting_orders and m.is_binary() and m.yes_price is not None
        and m.end_date is not None and now < m.end_date <= horizon
        and m.liquidity >= min_liquidity
    ]
    eligible.sort(key=lambda m: m.liquidity, reverse=True)
    return eligible[:max_candidates]
