from __future__ import annotations

import json
from datetime import datetime

import httpx

from polymath.model import Market, Token

_PAGE = 500


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_market(raw: dict) -> Market | None:
    try:
        token_ids = json.loads(raw["clobTokenIds"])
        outcomes = json.loads(raw["outcomes"])
    except (KeyError, json.JSONDecodeError, TypeError):
        return None
    if len(token_ids) != len(outcomes) or len(token_ids) < 2:
        return None
    tokens = [Token(str(tid), str(o)) for tid, o in zip(token_ids, outcomes)]
    return Market(
        condition_id=str(raw.get("conditionId")),
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
        while True:
            resp = await self._client.get(
                "/markets",
                params={"active": "true", "closed": "false",
                        "limit": _PAGE, "offset": offset},
            )
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
