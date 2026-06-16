from __future__ import annotations

import json
import re
import subprocess
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


_PROMPT = (
    "You are estimating the probability of a Polymarket YES outcome.\n"
    "Question: {question}\n"
    "Use web search to gather the most recent, relevant facts, then respond with "
    "ONLY a single JSON object (no prose) of the form:\n"
    '{{"prob": <0..1 probability of YES>, "confidence": <0..1>, '
    '"category": "sports|politics|world-news|other", '
    '"signals": {{"latest_news_age_hours": <number>, "news_direction": "yes|no|mixed", '
    '"consensus_strength": <0..1>, "source_count": <int>}}, '
    '"rationale": "<one sentence>"}}'
)


class ResearchError(RuntimeError):
    pass


def _default_runner(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise ResearchError(f"claude CLI exited {proc.returncode}: {proc.stderr[:200]}")
    return proc.stdout


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ResearchError("no JSON object in CLI result")
        return json.loads(match.group(0))


class ClaudeCliResearcher:
    """Shells out to the local Claude Code CLI in headless mode with web search."""

    def __init__(self, runner=_default_runner, *, cli_path: str = "claude",
                 model: str | None = None):
        self._runner = runner
        self._cli = cli_path
        self._model = model

    def _build_cmd(self, market: Market) -> list[str]:
        prompt = _PROMPT.format(question=market.question)
        cmd = [self._cli, "-p", prompt, "--output-format", "json",
               "--allowed-tools", "WebSearch"]
        if self._model:
            cmd += ["--model", self._model]
        return cmd

    def research(self, market: Market) -> Estimate:
        raw = self._runner(self._build_cmd(market))
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ResearchError(f"CLI did not return JSON: {e}") from e
        if envelope.get("is_error") or envelope.get("subtype") != "success":
            raise ResearchError(f"CLI research failed: {envelope.get('subtype')}")
        result_text = str(envelope.get("result", ""))
        payload = _extract_json_object(result_text)
        signals = dict(payload.get("signals") or {})
        # Claude Code's native WebSearch tool does NOT increment the API's
        # server_tool_use counter, so detect real grounding from cited source URLs
        # in the response. This is the signal that tells us whether the estimate
        # was actually informed by live data vs answered from priors.
        signals["grounded"] = "http" in result_text.lower()
        searches = (envelope.get("usage") or {}).get("server_tool_use", {})
        if searches.get("web_search_requests"):
            signals["web_search_requests"] = searches["web_search_requests"]
        return Estimate(
            prob=payload.get("prob", 0.5),
            confidence=payload.get("confidence", 0.0),
            category=str(payload.get("category", "other")),
            signals=signals,
            rationale=str(payload.get("rationale", "")),
        )
