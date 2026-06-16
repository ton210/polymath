from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from polymath.clients.clob import ClobClient
from polymath.clients.gamma import GammaClient
from polymath.config import Config, default_config, load_config
from polymath.ledger import Ledger
from polymath.paper import PaperBook
from polymath.report import build_scorecard
from polymath.scanner import build_snapshot, run_detectors

app = typer.Typer(add_completion=False, help="Polymarket arbitrage scanner")
console = Console()

_BADGE = {"risk-free": "🔒", "structural": "🟡", "directional": "⚠️"}


def _load(config_path: str | None) -> Config:
    return load_config(config_path) if config_path else default_config()


async def _scan_once(cfg: Config, profile: str, only: str | None):
    async with GammaClient(cfg.gamma_base) as gamma, ClobClient(cfg.clob_base) as clob:
        snap = await build_snapshot(gamma, clob, cfg)
    opps = run_detectors(snap, cfg, profile=profile, only=only)
    return snap, opps


def _render(snap, opps) -> None:
    age = (datetime.now(timezone.utc) - snap.timestamp).total_seconds()
    table = Table(title=f"Opportunities (snapshot age {age:.0f}s)")
    for col in ("", "kind", "markets", "size", "net $", "roi %", "realizability"):
        table.add_column(col)
    for o in opps:
        table.add_row(
            _BADGE.get(o.risk_tier, "?"), o.kind, ",".join(o.market_ids),
            f"{o.fillable_size:g}", f"{o.net_profit:.2f}", f"{o.roi * 100:.2f}",
            o.realizability,
        )
    console.print(table)
    if not opps:
        console.print("[dim]no qualifying opportunities[/dim]")


@app.command()
def scan(
    profile: str = typer.Option("default"),
    only: str = typer.Option(None, help="pure_arb"),
    record: bool = typer.Option(False, "--record"),
    ledger: str = typer.Option(None, help="ledger path override"),
    config: str = typer.Option(None, help="config TOML path"),
):
    cfg = _load(config)
    snap, opps = asyncio.run(_scan_once(cfg, profile, only))
    _render(snap, opps)
    if record:
        eff = cfg.effective(profile)
        led = Ledger(ledger or eff.ledger_path)
        book = PaperBook(bankroll=eff.bankroll, max_position_pct=eff.max_position_pct,
                         assumed_slippage=eff.assumed_slippage)
        for o in opps:
            led.append(book.consider(o, snap.timestamp))
        console.print(f"[green]recorded {len(opps)} signals to {led.path}[/green]")


@app.command()
def watch(
    interval: int = typer.Option(None, help="seconds between scans"),
    profile: str = typer.Option("default"),
    only: str = typer.Option(None),
    ledger: str = typer.Option(None),
    config: str = typer.Option(None),
    iterations: int = typer.Option(0, help="0 = forever; >0 for testing"),
):
    cfg = _load(config)
    eff = cfg.effective(profile)
    delay = interval or eff.watch_interval_seconds
    n = 0
    while True:
        snap, opps = asyncio.run(_scan_once(cfg, profile, only))
        led = Ledger(ledger or eff.ledger_path)
        book = PaperBook(bankroll=eff.bankroll, max_position_pct=eff.max_position_pct,
                         assumed_slippage=eff.assumed_slippage)
        for o in opps:
            led.append(book.consider(o, snap.timestamp))
        console.print(f"[{snap.timestamp.isoformat()}] recorded {len(opps)} signals")
        n += 1
        if iterations and n >= iterations:
            break
        time.sleep(delay)


@app.command()
def report(
    ledger: str = typer.Option(None),
    module: str = typer.Option(None, help="filter by module"),
    min_entered: int = typer.Option(10),
    config: str = typer.Option(None),
):
    cfg = _load(config)
    led = Ledger(ledger or cfg.ledger_path)
    rows = led.read_all()
    if module:
        rows = [r for r in rows if r.get("module") == module]
    cards = build_scorecard(rows, min_entered=min_entered)
    table = Table(title="Experiment scorecard")
    for col in ("module", "profile", "signals", "entered", "total $", "hit %",
                "sharpe", "verdict"):
        table.add_column(col)
    for c in sorted(cards, key=lambda c: c.total_pnl, reverse=True):
        table.add_row(c.module, c.profile, str(c.signals), str(c.entered),
                      f"{c.total_pnl:.2f}", f"{c.hit_rate * 100:.0f}",
                      f"{c.sharpe:.2f}", c.verdict)
    console.print(table)


if __name__ == "__main__":
    app()
