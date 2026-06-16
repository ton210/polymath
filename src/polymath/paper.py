from __future__ import annotations

import math
from datetime import datetime

from polymath.model import Opportunity


class PaperBook:
    """In-memory simulated trading state. One instance per scan run.

    Sizes each opportunity to min(fillable depth, max_position budget, remaining
    bankroll), dedups recurring opportunities, and records locked PnL for
    instant-merge arbs. Every decision is returned as a ledger-ready dict.
    """

    def __init__(self, *, bankroll: float, max_position_pct: float,
                 assumed_slippage: float):
        self.bankroll = bankroll
        self.remaining = bankroll
        self.max_position_pct = max_position_pct
        self.assumed_slippage = assumed_slippage
        self._seen: set[str] = set()

    def _row(self, opp: Opportunity, ts: datetime, status: str,
             entered_size: float, realized_pnl: float) -> dict:
        return {
            "timestamp": ts.isoformat(),
            "module": opp.module,
            "profile": opp.profile,
            "kind": opp.kind,
            "market_ids": opp.market_ids,
            "dedup_key": opp.dedup_key(),
            "predicted_net_profit": opp.net_profit,
            "predicted_roi": opp.roi,
            "fillable_size": opp.fillable_size,
            "realizability": opp.realizability,
            "risk_tier": opp.risk_tier,
            "status": status,
            "entered_size": entered_size,
            "realized_pnl": realized_pnl,
        }

    def consider(self, opp: Opportunity, ts: datetime) -> dict:
        key = opp.dedup_key()
        if key in self._seen:
            return self._row(opp, ts, "deduped", 0.0, 0.0)

        if opp.fillable_size <= 0 or opp.cost <= 0:
            return self._row(opp, ts, "skipped", 0.0, 0.0)

        cost_per_set = opp.cost / opp.fillable_size
        position_budget = min(self.max_position_pct * self.bankroll, self.remaining)
        affordable = math.floor(position_budget / cost_per_set) if cost_per_set else 0
        size = min(opp.fillable_size, affordable)

        if size <= 0:
            return self._row(opp, ts, "capital-constrained", 0.0, 0.0)

        fraction = size / opp.fillable_size
        spent = opp.cost * fraction
        gross_pnl = opp.net_profit * fraction
        slip = self.assumed_slippage * spent
        realized = gross_pnl - slip

        self.remaining -= spent
        self._seen.add(key)
        return self._row(opp, ts, "entered", size, realized)
