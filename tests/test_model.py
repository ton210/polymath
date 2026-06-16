from polymath.model import Level, OrderBook, Token, Market


def test_orderbook_best_prices_and_sorting():
    book = OrderBook(
        token_id="t1",
        bids=[Level(0.40, 100), Level(0.42, 50)],   # unsorted on purpose
        asks=[Level(0.45, 80), Level(0.44, 30)],
    )
    book = book.normalized()
    assert book.best_bid().price == 0.42   # bids: highest first
    assert book.best_ask().price == 0.44   # asks: lowest first
    assert book.bids[0].price >= book.bids[1].price
    assert book.asks[0].price <= book.asks[1].price


def test_market_yes_no_token_lookup():
    m = Market(
        condition_id="c1",
        question="Will X happen?",
        slug="x",
        tokens=[Token("yes_tok", "Yes"), Token("no_tok", "No")],
        neg_risk=False,
        neg_risk_market_id=None,
        accepting_orders=True,
        end_date=None,
        liquidity=1000.0,
        volume=5000.0,
    )
    assert m.token_for("Yes").token_id == "yes_tok"
    assert m.complement_of("yes_tok").token_id == "no_tok"
    assert m.is_binary()
