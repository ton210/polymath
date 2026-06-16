from __future__ import annotations

from datetime import datetime, timezone

from polymath.config import Config
from polymath.detectors import pure_arb
from polymath.model import Event, Snapshot


def _group_events(markets) -> dict[str, Event]:
    events: dict[str, Event] = {}
    for m in markets:
        if m.neg_risk and m.neg_risk_market_id:
            ev = events.get(m.neg_risk_market_id)
            if ev is None:
                ev = Event(id=m.neg_risk_market_id, title=m.neg_risk_market_id,
                           neg_risk=True, market_condition_ids=[])
                events[m.neg_risk_market_id] = ev
            ev.market_condition_ids.append(m.condition_id)
    return {eid: ev for eid, ev in events.items() if len(ev.market_condition_ids) >= 2}


async def build_snapshot(gamma, clob, config: Config) -> Snapshot:
    markets = await gamma.fetch_active_markets(
        min_liquidity=config.min_liquidity, min_volume=config.min_volume)
    token_ids = [t.token_id for m in markets for t in m.tokens]
    books = await clob.fetch_books(token_ids)
    return Snapshot(
        timestamp=datetime.now(timezone.utc),
        markets={m.condition_id: m for m in markets},
        books=books,
        events=_group_events(markets),
    )


def run_detectors(snap: Snapshot, config: Config, *, profile: str,
                  only: str | None = None) -> list:
    eff = config.effective(profile)
    opps = []
    if only in (None, "pure_arb"):
        opps += pure_arb.detect(
            snap, min_roi=eff.min_roi, min_profit_usd=eff.min_profit_usd,
            fee_bps=eff.fee_bps, profile=profile)
    return sorted(opps, key=lambda o: o.net_profit, reverse=True)
