import httpx
import respx

from polymath.clients.gamma import GammaClient


@respx.mock
async def test_parses_gamma_id_and_yes_price():
    raw = [{
        "id": "777", "conditionId": "c1", "question": "Q", "slug": "q",
        "clobTokenIds": "[\"yes1\", \"no1\"]", "outcomes": "[\"Yes\", \"No\"]",
        "outcomePrices": "[\"0.62\", \"0.38\"]",
        "active": True, "closed": False, "acceptingOrders": True,
        "negRisk": False, "liquidityNum": 1000, "volumeNum": 1000,
        "endDate": "2026-06-17T00:00:00Z",
    }]
    respx.get("https://gamma-api.polymarket.com/markets").side_effect = [
        httpx.Response(200, json=raw), httpx.Response(200, json=[]),
    ]
    async with GammaClient("https://gamma-api.polymarket.com") as c:
        markets = await c.fetch_active_markets(min_liquidity=0, min_volume=0)
    m = markets[0]
    assert m.gamma_id == "777"
    assert m.yes_price == 0.62
