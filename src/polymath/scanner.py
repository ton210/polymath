from __future__ import annotations

from datetime import datetime, timezone

from polymath.config import Config
from polymath.detectors import pure_arb
from polymath.model import Event, Snapshot


async def build_snapshot(gamma, clob, config: Config) -> Snapshot:
    markets = await gamma.fetch_active_markets(
        min_liquidity=config.min_liquidity, min_volume=config.min_volume)
    by_cid = {m.condition_id: m for m in markets}

    # Neg-risk arbs need the COMPLETE outcome set, but the liquidity filter above
    # can drop low-liquidity outcomes. Re-fetch each referenced event's full
    # membership authoritatively, add any missing members, and build events from
    # that — so a truncated set is never mistaken for a complete (risk-free) one.
    event_ids = sorted({m.event_id for m in markets if m.neg_risk and m.event_id})
    events: dict[str, Event] = {}
    if event_ids:
        full = await gamma.fetch_events(event_ids)
        for eid, (title, members) in full.items():
            if len(members) < 2:
                continue
            for mm in members:
                by_cid.setdefault(mm.condition_id, mm)
            events[eid] = Event(id=eid, title=title, neg_risk=True,
                                market_condition_ids=[mm.condition_id for mm in members])

    token_ids = [t.token_id for m in by_cid.values() for t in m.tokens]
    books = await clob.fetch_books(token_ids)
    return Snapshot(
        timestamp=datetime.now(timezone.utc),
        markets=by_cid,
        books=books,
        events=events,
    )


def run_detectors(snap: Snapshot, config: Config, *, profile: str,
                  only: str | None = None) -> list:
    eff = config.effective(profile)
    opps = []
    if only in (None, "pure_arb"):
        opps += pure_arb.detect(
            snap, min_roi=eff.min_roi, min_profit_usd=eff.min_profit_usd,
            fee_bps=eff.fee_bps, gas_per_redeem=eff.gas_per_redeem, profile=profile)
    return sorted(opps, key=lambda o: o.net_profit, reverse=True)
