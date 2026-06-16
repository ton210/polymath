from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass
class Config:
    min_roi: float = 0.0
    min_profit_usd: float = 1.0
    fee_bps: float = 0.0
    gas_per_redeem: float = 0.0
    min_liquidity: float = 500.0
    min_volume: float = 0.0
    bankroll: float = 10_000.0
    max_position_pct: float = 0.10
    assumed_slippage: float = 0.0
    watch_interval_seconds: int = 300
    ledger_path: str = "ledger.jsonl"
    gamma_base: str = "https://gamma-api.polymarket.com"
    clob_base: str = "https://clob.polymarket.com"
    # News-signal directional pilot
    bet_window_hours: int = 48
    bet_min_liquidity: float = 500.0
    max_candidates: int = 40
    bets_per_day: int = 8
    bet_stake: float = 100.0
    min_edge: float = 0.10
    claude_cli_path: str = "claude"
    research_model: str | None = None
    research_timeout: int = 180
    profiles: dict[str, dict] = field(default_factory=lambda: {"default": {}})

    def effective(self, profile: str) -> "Config":
        overrides = self.profiles.get(profile, {})
        valid = {k: v for k, v in overrides.items() if k in self.__dataclass_fields__}
        return replace(self, **valid)


def default_config() -> Config:
    return Config()


def load_config(path: str | Path) -> Config:
    data = tomllib.loads(Path(path).read_text())
    profiles = data.pop("profiles", {}) or {}
    profiles.setdefault("default", {})
    fields = Config.__dataclass_fields__
    valid = {k: v for k, v in data.items() if k in fields}
    return Config(profiles=profiles, **valid)
