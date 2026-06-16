from __future__ import annotations


def diversify(rows: list[dict], bets_per_day: int) -> list[dict]:
    """Round-robin across categories (each category's rows ordered by descending
    edge), so the daily slate is spread across categories rather than dominated by
    one. Deterministic: no randomness, stable ordering."""
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    for cat_rows in by_cat.values():
        cat_rows.sort(key=lambda r: r["edge"], reverse=True)

    order: list[str] = []
    for r in rows:
        if r["category"] not in order:
            order.append(r["category"])

    selected: list[dict] = []
    idx = 0
    while len(selected) < bets_per_day and any(by_cat[c] for c in order):
        cat = order[idx % len(order)]
        if by_cat[cat]:
            selected.append(by_cat[cat].pop(0))
        idx += 1
    return selected
