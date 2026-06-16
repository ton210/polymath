from datetime import datetime, timezone

from typer.testing import CliRunner

from polymath import cli
from polymath.model import Level, OrderBook, Token, Market

runner = CliRunner()


class FakeGamma:
    def __init__(self, markets):
        self._markets = markets

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch_active_markets(self, *, min_liquidity, min_volume):
        return self._markets


class FakeClob:
    def __init__(self, books):
        self._books = books

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def fetch_books(self, token_ids):
        return {t: self._books[t] for t in token_ids if t in self._books}


def _patch_clients(monkeypatch):
    market = Market("c1", "Will X?", "x", [Token("yes", "Yes"), Token("no", "No")],
                    neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                    end_date=None, liquidity=9999, volume=9999)
    books = {"yes": OrderBook("yes", asks=[Level(0.45, 100)]),
             "no": OrderBook("no", asks=[Level(0.50, 100)])}
    monkeypatch.setattr(cli, "GammaClient", lambda *a, **k: FakeGamma([market]))
    monkeypatch.setattr(cli, "ClobClient", lambda *a, **k: FakeClob(books))


def test_scan_prints_opportunity(monkeypatch):
    _patch_clients(monkeypatch)
    result = runner.invoke(cli.app, ["scan"])
    assert result.exit_code == 0
    assert "binary_yes_no" in result.stdout


def test_scan_record_writes_ledger_then_report(monkeypatch, tmp_path):
    _patch_clients(monkeypatch)
    ledger = tmp_path / "ledger.jsonl"
    r1 = runner.invoke(cli.app, ["scan", "--record", "--ledger", str(ledger)])
    assert r1.exit_code == 0
    assert ledger.exists()
    r2 = runner.invoke(cli.app, ["report", "--ledger", str(ledger), "--min-entered", "1"])
    assert r2.exit_code == 0
    assert "pure_arb" in r2.stdout
