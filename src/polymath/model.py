from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass
class OrderBook:
    token_id: str
    bids: list[Level] = field(default_factory=list)  # highest price first
    asks: list[Level] = field(default_factory=list)  # lowest price first

    def normalized(self) -> "OrderBook":
        return OrderBook(
            token_id=self.token_id,
            bids=sorted(self.bids, key=lambda l: l.price, reverse=True),
            asks=sorted(self.asks, key=lambda l: l.price),
        )

    def best_bid(self) -> Level | None:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> Level | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class Token:
    token_id: str
    outcome: str


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    tokens: list[Token]
    neg_risk: bool
    neg_risk_market_id: str | None
    accepting_orders: bool
    end_date: datetime | None
    liquidity: float
    volume: float
    event_id: str | None = None
    gamma_id: str | None = None
    yes_price: float | None = None

    def is_binary(self) -> bool:
        return len(self.tokens) == 2

    def token_for(self, outcome: str) -> Token:
        for t in self.tokens:
            if t.outcome.lower() == outcome.lower():
                return t
        raise KeyError(outcome)

    def complement_of(self, token_id: str) -> Token:
        if not self.is_binary():
            raise ValueError("complement only defined for binary markets")
        for t in self.tokens:
            if t.token_id != token_id:
                return t
        raise KeyError(token_id)


@dataclass
class Event:
    id: str
    title: str
    neg_risk: bool
    market_condition_ids: list[str]


@dataclass
class Snapshot:
    timestamp: datetime
    markets: dict[str, Market]            # condition_id -> Market
    books: dict[str, OrderBook]           # token_id -> OrderBook
    events: dict[str, Event]              # event id -> Event


@dataclass(frozen=True)
class Leg:
    token_id: str
    outcome: str
    side: str                             # "buy" | "sell"
    limit_price: float
    market_id: str


@dataclass
class Opportunity:
    module: str                           # "pure_arb"
    profile: str
    kind: str                             # "binary_yes_no" | "neg_risk_set" | "sell_set"
    market_ids: list[str]
    legs: list[Leg]
    fillable_size: float
    cost: float
    net_profit: float
    roi: float
    realizability: str                    # "instant-merge" | "hold-to-resolution"
    risk_tier: str                        # "risk-free" | "structural" | "directional"
    end_date: datetime | None
    explain: str

    def dedup_key(self) -> str:
        return f"{self.module}:{self.kind}:" + ",".join(sorted(self.market_ids))
