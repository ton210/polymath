from __future__ import annotations

from typing import Protocol

from polymath.model import Market
from polymath.signals.estimate import Estimate


class Researcher(Protocol):
    def research(self, market: Market) -> Estimate: ...


class StubResearcher:
    """Returns canned estimates keyed by condition_id. For offline tests."""

    def __init__(self, by_condition_id: dict[str, Estimate]):
        self._by_cid = by_condition_id

    def research(self, market: Market) -> Estimate:
        return self._by_cid[market.condition_id]
