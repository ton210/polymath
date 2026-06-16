from __future__ import annotations

from datetime import datetime, timedelta

from polymath.model import Market


def select_near_term(markets: list[Market], now: datetime, *, window_hours: int,
                     min_liquidity: float, max_candidates: int,
                     max_per_event: int = 2) -> list[Market]:
    """Markets resolving within the window that are tradeable, binary, priced, and
    liquid — capped to the most-liquid ``max_candidates``.

    At most ``max_per_event`` markets per event are kept, so one event's many
    sub-markets (e.g. a match's exact-score lines) can't crowd out distinct events
    and waste research calls on near-duplicates. Markets without an event_id are
    each treated as their own event.
    """
    horizon = now + timedelta(hours=window_hours)
    eligible = [
        m for m in markets
        if m.accepting_orders and m.is_binary() and m.yes_price is not None
        and m.end_date is not None and now < m.end_date <= horizon
        and m.liquidity >= min_liquidity
    ]
    eligible.sort(key=lambda m: m.liquidity, reverse=True)

    per_event: dict[str, int] = {}
    chosen: list[Market] = []
    for m in eligible:
        key = m.event_id or f"__solo__{m.condition_id}"
        if per_event.get(key, 0) >= max_per_event:
            continue
        per_event[key] = per_event.get(key, 0) + 1
        chosen.append(m)
        if len(chosen) >= max_candidates:
            break
    return chosen
