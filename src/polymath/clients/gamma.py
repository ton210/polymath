from __future__ import annotations

import asyncio
import json
from datetime import datetime

import httpx

from polymath.model import Market, Token

_PAGE = 500
_MAX_PAGES = 200   # safety cap: 100k markets, far beyond Polymarket's live count


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_market(raw: dict) -> Market | None:
    condition_id = raw.get("conditionId")
    if not condition_id:
        return None
    try:
        token_ids = json.loads(raw["clobTokenIds"])
        outcomes = json.loads(raw["outcomes"])
    except (KeyError, json.JSONDecodeError, TypeError):
        return None
    if len(token_ids) != len(outcomes) or len(token_ids) < 2:
        return None
    tokens = [Token(str(tid), str(o)) for tid, o in zip(token_ids, outcomes)]
    events = raw.get("events") or []
    event_id = str(events[0]["id"]) if events and events[0].get("id") is not None else None
    prices_raw = raw.get("outcomePrices")
    yes_price = None
    if prices_raw:
        try:
            yes_price = float(json.loads(prices_raw)[0])
        except (json.JSONDecodeError, ValueError, IndexError, TypeError):
            yes_price = None
    gamma_id = str(raw["id"]) if raw.get("id") is not None else None
    return Market(
        condition_id=str(condition_id),
        question=raw.get("question", ""),
        slug=raw.get("slug", ""),
        tokens=tokens,
        neg_risk=bool(raw.get("negRisk", False)),
        neg_risk_market_id=raw.get("negRiskMarketID"),
        accepting_orders=bool(raw.get("acceptingOrders", False)),
        end_date=_parse_dt(raw.get("endDate")),
        liquidity=float(raw.get("liquidityNum") or 0.0),
        volume=float(raw.get("volumeNum") or 0.0),
        event_id=event_id,
        gamma_id=gamma_id,
        yes_price=yes_price,
    )


class GammaClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def __aenter__(self) -> "GammaClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def fetch_active_markets(
        self, *, min_liquidity: float, min_volume: float
    ) -> list[Market]:
        markets: list[Market] = []
        offset = 0
        for _ in range(_MAX_PAGES):
            params: dict = {"active": "true", "closed": "false",
                            "limit": _PAGE, "offset": offset}
            # Filter server-side so we page through only liquid/active markets
            # instead of every market then discarding most.
            if min_liquidity > 0:
                params["liquidity_num_min"] = min_liquidity
            if min_volume > 0:
                params["volume_num_min"] = min_volume
            resp = await self._client.get("/markets", params=params)
            # Gamma returns 422 for offsets past the end of the result set rather
            # than an empty page; treat that as end-of-data once we've started.
            if resp.status_code == 422 and offset > 0:
                break
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for raw in batch:
                m = _parse_market(raw)
                if m is None:
                    continue
                if m.liquidity < min_liquidity or m.volume < min_volume:
                    continue
                markets.append(m)
            offset += _PAGE
        return markets

    async def _fetch_event(self, event_id: str) -> tuple[str, list[Market]] | None:
        """Authoritative full membership of one event (no liquidity filter), so a
        neg-risk set is never silently truncated by the market-level filter."""
        resp = await self._client.get(f"/events/{event_id}")
        if resp.status_code != 200:
            return None
        data = resp.json()
        members = [m for m in (_parse_market(raw) for raw in data.get("markets", []))
                   if m is not None]
        return str(data.get("title") or event_id), members

    async def fetch_events(
        self, event_ids: list[str]
    ) -> dict[str, tuple[str, list[Market]]]:
        results = await asyncio.gather(*(self._fetch_event(e) for e in event_ids))
        return {eid: res for eid, res in zip(event_ids, results) if res is not None}

    async def fetch_market_raw(self, gamma_id: str) -> dict | None:
        """Fetch a single market by its numeric Gamma id (works for closed markets,
        unlike the active-filtered list endpoint). Returns the raw JSON dict."""
        resp = await self._client.get(f"/markets/{gamma_id}")
        if resp.status_code != 200:
            return None
        return resp.json()
