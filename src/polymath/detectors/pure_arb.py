from __future__ import annotations

from polymath.model import Leg, Market, OrderBook, Opportunity, Snapshot
from polymath.pricing import effective_ask_ladder, walk_matched_sets, worst_fill_price


def _book(snap: Snapshot, token_id: str) -> OrderBook:
    return snap.books.get(token_id, OrderBook(token_id))


def _finalize(size, cost, fee_bps, gas_per_redeem, payout_per_set):
    gross = size * payout_per_set
    fees = cost * (fee_bps / 10_000.0)
    net = gross - cost - fees - gas_per_redeem
    roi = (net / cost) if cost > 0 else 0.0
    return net, roi


def _binary(snap, m: Market, min_roi, min_profit_usd, fee_bps, gas_per_redeem, profile):
    yes, no = m.tokens[0], m.tokens[1]
    yes_book, no_book = _book(snap, yes.token_id), _book(snap, no.token_id)
    yes_ladder = effective_ask_ladder(yes_book, no_book)
    no_ladder = effective_ask_ladder(no_book, yes_book)
    size, cost = walk_matched_sets([yes_ladder, no_ladder], payout=1.0)
    if size <= 0:
        return None
    net, roi = _finalize(size, cost, fee_bps, gas_per_redeem, 1.0)
    if net < min_profit_usd or roi < min_roi:
        return None
    return Opportunity(
        module="pure_arb", profile=profile, kind="binary_yes_no",
        market_ids=[m.condition_id],
        legs=[
            # limit = worst level walked, so an order can fill the full size.
            Leg(yes.token_id, "Yes", "buy",
                worst_fill_price(yes_ladder, size), m.condition_id),
            Leg(no.token_id, "No", "buy",
                worst_fill_price(no_ladder, size), m.condition_id),
        ],
        fillable_size=size, cost=cost, net_profit=net, roi=roi,
        realizability="instant-merge", risk_tier="risk-free",
        end_date=m.end_date,
        explain=f"buy {size:g} YES+NO @ blended {cost/size:.4f}, redeem $1/set",
    )


def _neg_risk(snap, event, min_roi, min_profit_usd, fee_bps, gas_per_redeem, profile):
    # A valid hedge needs every mutually-exclusive outcome to be tradeable; if
    # any member is missing, non-binary, or closed, the set is incomplete -> skip.
    members = []
    for c in event.market_condition_ids:
        m = snap.markets.get(c)
        if m is None or not m.accepting_orders or not m.is_binary():
            return None
        members.append(m)
    if len(members) < 2:
        return None
    ladders, yes_tokens = [], []
    for m in members:
        yes, no = m.tokens[0], m.tokens[1]
        ladder = effective_ask_ladder(_book(snap, yes.token_id), _book(snap, no.token_id))
        if not ladder:
            return None
        ladders.append(ladder)
        yes_tokens.append((yes, m.condition_id))
    size, cost = walk_matched_sets(ladders, payout=1.0)
    if size <= 0:
        return None
    net, roi = _finalize(size, cost, fee_bps, gas_per_redeem, 1.0)
    if net < min_profit_usd or roi < min_roi:
        return None
    legs = [
        # limit = worst level walked, so the full size is fillable per leg.
        Leg(yes.token_id, "Yes", "buy", worst_fill_price(ladder, size), cid)
        for (yes, cid), ladder in zip(yes_tokens, ladders)
    ]
    return Opportunity(
        module="pure_arb", profile=profile, kind="neg_risk_set",
        market_ids=[m.condition_id for m in members], legs=legs,
        fillable_size=size, cost=cost, net_profit=net, roi=roi,
        realizability="instant-merge", risk_tier="risk-free",
        end_date=min((m.end_date for m in members if m.end_date), default=None),
        explain=f"buy 1 YES of each of {len(members)} outcomes, sum<$1",
    )


def _binary_sell(snap, m: Market, min_profit_usd, profile):
    # Informational flag only (selling a set requires minting/holding), so it is
    # scored on top-of-book and filtered by min_profit_usd; fee_bps is not modeled
    # here because there is no executable buy leg to charge fees against.
    yes, no = m.tokens[0], m.tokens[1]
    yb, nb = _book(snap, yes.token_id).best_bid(), _book(snap, no.token_id).best_bid()
    if yb is None or nb is None or (yb.price + nb.price) <= 1.0:
        return None
    size = min(yb.size, nb.size)
    if size <= 0:
        return None
    proceeds = size * (yb.price + nb.price)
    net = proceeds - size  # cost to mint a set is $1/set
    if net < min_profit_usd:
        return None
    return Opportunity(
        module="pure_arb", profile=profile, kind="sell_set",
        market_ids=[m.condition_id],
        legs=[
            Leg(yes.token_id, "Yes", "sell", yb.price, m.condition_id),
            Leg(no.token_id, "No", "sell", nb.price, m.condition_id),
        ],
        fillable_size=size, cost=size, net_profit=net,
        roi=(net / size if size else 0.0),
        realizability="hold-to-resolution", risk_tier="risk-free",
        end_date=m.end_date,
        explain=f"sell a minted set for {yb.price + nb.price:.4f} (>$1, FYI: needs mint/hold)",
    )


def detect(snap: Snapshot, *, min_roi: float, min_profit_usd: float,
           fee_bps: float, profile: str, gas_per_redeem: float = 0.0) -> list[Opportunity]:
    out: list[Opportunity] = []
    for m in snap.markets.values():
        if not m.accepting_orders or not m.is_binary():
            continue
        b = _binary(snap, m, min_roi, min_profit_usd, fee_bps, gas_per_redeem, profile)
        if b:
            out.append(b)
        s = _binary_sell(snap, m, min_profit_usd, profile)
        if s:
            out.append(s)
    for event in snap.events.values():
        if event.neg_risk:
            n = _neg_risk(snap, event, min_roi, min_profit_usd, fee_bps,
                          gas_per_redeem, profile)
            if n:
                out.append(n)
    return out
