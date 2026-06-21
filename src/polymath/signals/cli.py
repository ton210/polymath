from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from polymath.clients.gamma import GammaClient
from polymath.config import Config, default_config, load_config
from polymath.ledger import Ledger
from polymath.signals.analyze import build_report
from polymath.signals.directional import build_bet
from polymath.signals.nearterm import select_near_term
from polymath.signals.research import ClaudeCliResearcher
from polymath.signals.resolution import winner_from_raw
from polymath.signals.select import diversify
from polymath.signals.settle import score_bet

app = typer.Typer(add_completion=False, help="News-signal directional pilot")
console = Console()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_researcher(cfg: Config):
    return ClaudeCliResearcher(cli_path=cfg.claude_cli_path, model=cfg.research_model)


def _cfg(config_path: str | None, profile: str) -> Config:
    base = load_config(config_path) if config_path else default_config()
    return base.effective(profile)


@app.command()
def bet(profile: str = typer.Option("default"), ledger: str = typer.Option(None),
        min_edge: float = typer.Option(None), config: str = typer.Option(None)):
    cfg = _cfg(config, profile)
    edge = min_edge if min_edge is not None else cfg.min_edge
    led = Ledger(ledger or cfg.ledger_path)
    researcher = _make_researcher(cfg)

    # Don't re-bet a market we've already bet on an earlier day: a market resolving
    # within the window reappears in the candidate pool until it resolves.
    already_bet = {r.get("condition_id") for r in led.read_all()
                   if r.get("module") == "news_directional"}

    async def _markets():
        async with GammaClient(cfg.gamma_base) as g:
            return await g.fetch_active_markets(
                min_liquidity=cfg.bet_min_liquidity, min_volume=0)

    markets = asyncio.run(_markets())
    candidates = select_near_term(
        markets, _now(), window_hours=cfg.bet_window_hours,
        min_liquidity=cfg.bet_min_liquidity, max_candidates=cfg.max_candidates,
        max_per_event=cfg.max_per_event)
    candidates = [m for m in candidates if m.condition_id not in already_bet]

    rows = []
    for m in candidates:
        try:
            est = researcher.research(m)
        except Exception as exc:   # research failures skip one market, never abort
            console.print(f"[yellow]skip {m.condition_id}: {exc}[/yellow]")
            continue
        row = build_bet(m, est, min_edge=edge, max_edge=cfg.max_edge,
                        min_price=cfg.min_price, max_price=cfg.max_price,
                        stake=cfg.bet_stake, profile=profile, timestamp=_now())
        if row:
            rows.append(row)

    chosen = diversify(rows, cfg.bets_per_day)
    for row in chosen:
        led.append(row)
    console.print(f"[green]logged {len(chosen)} bets (from {len(candidates)} "
                  f"candidates) to {led.path}[/green]")


@app.command()
def settle(profile: str = typer.Option("default"), ledger: str = typer.Option(None),
           config: str = typer.Option(None)):
    cfg = _cfg(config, profile)
    led = Ledger(ledger or cfg.ledger_path)
    rows = led.read_all()
    directional = [r for r in rows if r.get("module") == "news_directional"]
    open_ids = [r["gamma_id"] for r in directional
                if r.get("status") == "open" and r.get("gamma_id")]

    async def _resolve_all(ids: list[str]) -> dict:
        uniq = [i for i in dict.fromkeys(ids)]   # de-dup, preserve order
        async with GammaClient(cfg.gamma_base) as g:
            raws = await asyncio.gather(*(g.fetch_market_raw(i) for i in uniq))
        return dict(zip(uniq, raws))

    resolved = asyncio.run(_resolve_all(open_ids)) if open_ids else {}

    settled = 0
    updated = []
    for r in rows:
        if r.get("module") == "news_directional" and r.get("status") == "open":
            raw = resolved.get(r.get("gamma_id"))
            winner = winner_from_raw(raw) if raw else None
            new = score_bet(r, winner)
            if new.get("status") != "open":
                settled += 1
            updated.append(new)
        else:
            updated.append(r)

    # Atomic write: serialize to a temp file in the same dir, then rename, so an
    # interrupted settle can never truncate the ledger (which holds arb rows too).
    tmp = led.path.with_name(led.path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in updated))
    os.replace(tmp, led.path)
    console.print(f"[green]settled {settled} of {len(directional)} directional bets[/green]")


@app.command()
def analyze(profile: str = typer.Option("default"), ledger: str = typer.Option(None),
            config: str = typer.Option(None)):
    cfg = _cfg(config, profile)
    led = Ledger(ledger or cfg.ledger_path)
    rows = [r for r in led.read_all() if r.get("module") == "news_directional"]
    rep = build_report(rows)

    t = Table(title="Directional pilot")
    for col in ("settled", "win rate", "total $", "ROI %"):
        t.add_column(col)
    t.add_row(str(rep["settled"]), f"{rep['win_rate'] * 100:.0f}%",
              f"{rep['total_pnl']:.2f}", f"{rep['roi'] * 100:.1f}")
    console.print(t)

    cal = Table(title="Calibration (predicted vs actual win rate)")
    for col in ("our prob", "n", "predicted", "actual"):
        cal.add_column(col)
    for b in rep["calibration"]:
        if b["n"]:
            cal.add_row(b["bucket"], str(b["n"]),
                        f"{b['predicted']:.2f}", f"{b['actual']:.2f}")
    console.print(cal)
    console.print("[dim]Note: a 7-day, 35-70 bet sample cannot prove edge; "
                  "treat as hypothesis generation.[/dim]")
