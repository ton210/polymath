from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from polymath import cli as main_cli
from polymath.signals import cli as signals_cli
from polymath.model import Token, Market
from polymath.signals.estimate import Estimate
from polymath.signals.research import StubResearcher
from polymath.ledger import Ledger

runner = CliRunner()
NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def _m(cid, gid, yes_price):
    return Market(cid, f"Will {cid} happen?", cid,
                  [Token(f"{cid}y", "Yes"), Token(f"{cid}n", "No")],
                  neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                  end_date=NOW + timedelta(hours=10), liquidity=5000, volume=5000,
                  gamma_id=gid, yes_price=yes_price)


class FakeGamma:
    def __init__(self, markets, raw_by_id=None):
        self._markets = markets
        self._raw = raw_by_id or {}

    async def __aenter__(self): return self
    async def __aexit__(self, *e): return None

    async def fetch_active_markets(self, *, min_liquidity, min_volume):
        return self._markets

    async def fetch_market_raw(self, gamma_id):
        return self._raw.get(gamma_id)


def _patch(monkeypatch, markets, estimates, raw_by_id=None):
    monkeypatch.setattr(signals_cli, "GammaClient", lambda *a, **k: FakeGamma(markets, raw_by_id))
    monkeypatch.setattr(signals_cli, "_now", lambda: NOW)
    monkeypatch.setattr(signals_cli, "_make_researcher", lambda cfg: StubResearcher(estimates))


def test_bet_then_settle_then_analyze(monkeypatch, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    markets = [_m("c1", "11", 0.50), _m("c2", "22", 0.50)]
    estimates = {"c1": Estimate(0.75, 0.8, "sports", {"source_count": 3}, "r"),
                 "c2": Estimate(0.70, 0.7, "politics", {"source_count": 2}, "r")}
    _patch(monkeypatch, markets, estimates)

    r1 = runner.invoke(main_cli.app, ["bet", "--ledger", str(ledger), "--min-edge", "0.1"])
    assert r1.exit_code == 0, r1.output
    rows = Ledger(ledger).read_all()
    assert len(rows) == 2 and all(r["status"] == "open" for r in rows)

    raw = {"11": {"closed": True, "umaResolutionStatus": "resolved",
                  "outcomes": "[\"Yes\",\"No\"]", "outcomePrices": "[\"1\",\"0\"]"},
           "22": {"closed": True, "umaResolutionStatus": "resolved",
                  "outcomes": "[\"Yes\",\"No\"]", "outcomePrices": "[\"0\",\"1\"]"}}
    _patch(monkeypatch, markets, estimates, raw_by_id=raw)
    r2 = runner.invoke(main_cli.app, ["settle", "--ledger", str(ledger)])
    assert r2.exit_code == 0, r2.output
    statuses = sorted(r["status"] for r in Ledger(ledger).read_all())
    assert statuses == ["lost", "won"]

    r3 = runner.invoke(main_cli.app, ["analyze", "--ledger", str(ledger)])
    assert r3.exit_code == 0, r3.output
    assert "win" in r3.output.lower()
