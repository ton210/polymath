import httpx
import respx

from polymath.clients.clob import ClobClient


@respx.mock
async def test_fetch_books_parses_and_sorts():
    payload = [
        {"asset_id": "yes1",
         "bids": [{"price": "0.40", "size": "100"}, {"price": "0.42", "size": "50"}],
         "asks": [{"price": "0.46", "size": "80"}, {"price": "0.45", "size": "30"}]},
        {"asset_id": "no1", "bids": [], "asks": [{"price": "0.50", "size": "10"}]},
    ]
    respx.post("https://clob.polymarket.com/books").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with ClobClient("https://clob.polymarket.com") as client:
        books = await client.fetch_books(["yes1", "no1"])

    assert set(books) == {"yes1", "no1"}
    yes = books["yes1"]
    assert yes.best_bid().price == 0.42    # sorted desc
    assert yes.best_ask().price == 0.45    # sorted asc
    assert books["no1"].best_bid() is None


@respx.mock
async def test_fetch_books_chunks_large_requests():
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        return httpx.Response(200, json=[])

    respx.post("https://clob.polymarket.com/books").mock(side_effect=responder)
    async with ClobClient("https://clob.polymarket.com", chunk_size=2) as client:
        await client.fetch_books(["a", "b", "c", "d", "e"])
    assert calls["n"] == 3   # ceil(5/2)
