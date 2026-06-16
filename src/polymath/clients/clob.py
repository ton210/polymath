from __future__ import annotations

import asyncio

import httpx

from polymath.model import Level, OrderBook


def _levels(raw: list[dict]) -> list[Level]:
    return [Level(float(x["price"]), float(x["size"])) for x in raw]


def _parse_book(raw: dict) -> OrderBook:
    return OrderBook(
        token_id=str(raw.get("asset_id")),
        bids=_levels(raw.get("bids", [])),
        asks=_levels(raw.get("asks", [])),
    ).normalized()


class ClobClient:
    def __init__(self, base_url: str, *, chunk_size: int = 100, timeout: float = 30.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._chunk = chunk_size

    async def __aenter__(self) -> "ClobClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _fetch_chunk(self, token_ids: list[str]) -> list[OrderBook]:
        body = [{"token_id": t} for t in token_ids]
        resp = await self._client.post("/books", json=body)
        resp.raise_for_status()
        return [_parse_book(b) for b in resp.json()]

    async def fetch_books(self, token_ids: list[str]) -> dict[str, OrderBook]:
        chunks = [token_ids[i:i + self._chunk]
                  for i in range(0, len(token_ids), self._chunk)]
        results = await asyncio.gather(*(self._fetch_chunk(c) for c in chunks))
        books: dict[str, OrderBook] = {}
        for group in results:
            for book in group:
                books[book.token_id] = book
        return books
