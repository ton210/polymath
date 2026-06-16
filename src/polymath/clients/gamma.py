from __future__ import annotations

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
