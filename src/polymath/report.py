from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class ExperimentScore:
    module: str
    profile: str
    signals: int
    entered: int
    total_pnl: float
    hit_rate: float
    sharpe: float
    max_drawdown: float
    verdict: str


def _max_drawdown(pnls: list[float]) -> float:
    cum = 0.0
    peak = 0.0
    worst = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return worst


def _verdict(entered: int, total: float, sharpe: float, min_entered: int) -> str:
    if entered < min_entered:
        return "insufficient-data"
    if total < 0:
        return "negative"
    if sharpe >= 1.0:
        return "consistent"
    return "marginal"


def build_scorecard(rows: list[dict], *, min_entered: int = 10) -> list[ExperimentScore]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["module"], r["profile"]), []).append(r)

    cards: list[ExperimentScore] = []
    for (module, profile), grp in groups.items():
        entered = [r for r in grp if r["status"] == "entered"]
        pnls = [float(r["realized_pnl"]) for r in entered]
        total = sum(pnls)
        hit = (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else 0.0
        if len(pnls) >= 2 and statistics.pstdev(pnls) > 0:
            sharpe = statistics.mean(pnls) / statistics.pstdev(pnls)
        elif pnls and total > 0:
            sharpe = float("inf")
        else:
            sharpe = 0.0
        cards.append(ExperimentScore(
            module=module, profile=profile, signals=len(grp), entered=len(entered),
            total_pnl=total, hit_rate=hit, sharpe=sharpe,
            max_drawdown=_max_drawdown(pnls),
            verdict=_verdict(len(entered), total, sharpe, min_entered),
        ))
    return cards
