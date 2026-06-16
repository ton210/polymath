import httpx
import respx

from polymath.signals.resolution import winner_from_raw
from polymath.clients.gamma import GammaClient


def test_winner_yes_when_first_price_is_one():
    raw = {"closed": True, "umaResolutionStatus": "resolved",
           "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"1\", \"0\"]"}
    assert winner_from_raw(raw) == "Yes"


def test_winner_no_when_second_price_is_one():
    raw = {"closed": True, "umaResolutionStatus": "resolved",
           "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0\", \"1\"]"}
    assert winner_from_raw(raw) == "No"


def test_none_when_not_resolved():
    raw = {"closed": False, "umaResolutionStatus": "", "outcomes": "[\"Yes\",\"No\"]",
           "outcomePrices": "[\"0.5\",\"0.5\"]"}
    assert winner_from_raw(raw) is None


def test_winner_with_rounded_resolved_prices():
    raw = {"closed": True, "umaResolutionStatus": "resolved",
           "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.999\", \"0.001\"]"}
    assert winner_from_raw(raw) == "Yes"


def test_none_when_void_double_zero():
    raw = {"closed": True, "umaResolutionStatus": "resolved",
           "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0\", \"0\"]"}
    assert winner_from_raw(raw) is None


@respx.mock
async def test_fetch_market_raw_by_id():
    respx.get("https://gamma-api.polymarket.com/markets/42").mock(
        return_value=httpx.Response(200, json={"id": "42", "closed": True})
    )
    async with GammaClient("https://gamma-api.polymarket.com") as c:
        raw = await c.fetch_market_raw("42")
    assert raw["closed"] is True
