import json
from pathlib import Path

import httpx
import respx

from polymath.clients.gamma import GammaClient

FIX = Path(__file__).parent / "fixtures"


@respx.mock
async def test_fetch_active_markets_paginates_and_parses():
    page1 = json.loads((FIX / "gamma_markets_page1.json").read_text())
    empty = json.loads((FIX / "gamma_markets_empty.json").read_text())
    route = respx.get("https://gamma-api.polymarket.com/markets")
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=empty),
    ]

    async with GammaClient("https://gamma-api.polymarket.com") as client:
        markets = await client.fetch_active_markets(min_liquidity=0, min_volume=0)

    assert {m.condition_id for m in markets} == {"c1", "c2"}
    m = markets[0]
    assert [t.token_id for t in m.tokens] == ["yes1", "no1"]
    assert [t.outcome for t in m.tokens] == ["Yes", "No"]
    assert m.neg_risk is True
    assert m.neg_risk_market_id == "E1"
    assert m.liquidity == 12000


@respx.mock
async def test_fetch_active_markets_filters_low_liquidity():
    page1 = json.loads((FIX / "gamma_markets_page1.json").read_text())
    empty = json.loads((FIX / "gamma_markets_empty.json").read_text())
    respx.get("https://gamma-api.polymarket.com/markets").side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=empty),
    ]
    async with GammaClient("https://gamma-api.polymarket.com") as client:
        markets = await client.fetch_active_markets(min_liquidity=10000, min_volume=0)
    assert {m.condition_id for m in markets} == {"c1"}   # c2 has 8000 < 10000
