from __future__ import annotations

from polymath.model import Level, OrderBook

_EPS = 1e-9


def effective_ask_ladder(own: OrderBook, complement: OrderBook | None) -> list[Level]:
    """Ascending price ladder for BUYING this outcome.

    Combines the outcome's own asks with synthetic asks created by selling the
    complement token into its bids: a complement bid at price q (size s) lets us
    acquire this outcome at price (1 - q) for size s.
    """
    levels = list(own.asks)
    if complement is not None:
        for bid in complement.bids:
            levels.append(Level(round(1.0 - bid.price, 10), bid.size))
    return sorted(levels, key=lambda l: l.price)


def walk_matched_sets(
    leg_ladders: list[list[Level]], payout: float = 1.0
) -> tuple[float, float]:
    """Buy equal quantity across every leg while the marginal cost of the next
    matched set (sum of each leg's current price) stays below ``payout``.

    Returns (total_size, total_cost). Ladders must be ascending by price.
    """
    if any(len(l) == 0 for l in leg_ladders):
        return 0.0, 0.0

    idx = [0] * len(leg_ladders)
    rem = [ladder[0].size for ladder in leg_ladders]
    total_size = 0.0
    total_cost = 0.0

    while all(idx[i] < len(leg_ladders[i]) for i in range(len(leg_ladders))):
        marginal = sum(leg_ladders[i][idx[i]].price for i in range(len(leg_ladders)))
        if marginal >= payout - _EPS:
            break
        step = min(rem)
        total_size += step
        for i in range(len(leg_ladders)):
            total_cost += leg_ladders[i][idx[i]].price * step
            rem[i] -= step
            if rem[i] <= _EPS:
                idx[i] += 1
                if idx[i] < len(leg_ladders[i]):
                    rem[i] = leg_ladders[i][idx[i]].size
    return total_size, total_cost
