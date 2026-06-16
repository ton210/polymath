import json

from polymath.model import Token, Market
from polymath.signals.research import ClaudeCliResearcher


def _m(cid="c1", q="Will the Lakers win tonight?"):
    return Market(cid, q, cid, [Token("y", "Yes"), Token("n", "No")],
                  neg_risk=False, neg_risk_market_id=None, accepting_orders=True,
                  end_date=None, liquidity=1.0, volume=1.0, gamma_id=cid, yes_price=0.55)


def test_builds_command_and_parses_estimate():
    captured = {}

    def fake_runner(cmd):
        captured["cmd"] = cmd
        inner = json.dumps({"prob": 0.66, "confidence": 0.6, "category": "sports",
                            "signals": {"source_count": 3}, "rationale": "favored"})
        return json.dumps({"type": "result", "subtype": "success",
                           "is_error": False, "result": inner,
                           "usage": {"server_tool_use": {"web_search_requests": 2}}})

    r = ClaudeCliResearcher(runner=fake_runner, cli_path="claude", model="claude-x")
    est = r.research(_m())

    cmd = captured["cmd"]
    assert cmd[0] == "claude"
    assert "-p" in cmd and "--output-format" in cmd and "json" in cmd
    assert "--allowed-tools" in cmd and "WebSearch" in cmd
    assert "--model" in cmd and "claude-x" in cmd
    assert any("Lakers" in part for part in cmd)
    assert est.prob == 0.66
    assert est.category == "sports"
    assert est.signals["source_count"] == 3
    assert est.signals["web_search_requests"] == 2


def test_grounded_true_when_response_cites_source_urls():
    def fake_runner(cmd):
        inner = (json.dumps({"prob": 0.3, "confidence": 0.5, "category": "world-news",
                             "signals": {"source_count": 2}, "rationale": "r"})
                 + "\n\nSources:\n- https://example.com/news")
        return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                           "result": inner, "usage": {}})

    est = ClaudeCliResearcher(runner=lambda c: fake_runner(c)).research(_m())
    assert est.signals["grounded"] is True


def test_grounded_false_when_no_sources():
    def fake_runner(cmd):
        inner = json.dumps({"prob": 0.3, "confidence": 0.5, "category": "world-news",
                            "signals": {}, "rationale": "answered from priors"})
        return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                           "result": inner, "usage": {}})

    est = ClaudeCliResearcher(runner=lambda c: fake_runner(c)).research(_m())
    assert est.signals["grounded"] is False


def test_extracts_json_when_wrapped_in_prose():
    def fake_runner(cmd):
        inner = "Here is my answer:\n{\"prob\": 0.4, \"confidence\": 0.5, " \
                "\"category\": \"politics\", \"signals\": {}, \"rationale\": \"x\"}\nDone."
        return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                           "result": inner, "usage": {}})

    r = ClaudeCliResearcher(runner=lambda c: fake_runner(c))
    est = r.research(_m())
    assert est.prob == 0.4
    assert est.category == "politics"


def test_extracts_json_despite_prose_braces_around_it():
    def fake_runner(cmd):
        inner = ("I'll call {WebSearch} now. Answer: "
                 "{\"prob\": 0.4, \"confidence\": 0.5, \"category\": \"politics\", "
                 "\"signals\": {\"source_count\": 2}, \"rationale\": \"x\"} "
                 "see {ref:1}")
        return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                           "result": inner, "usage": {}})

    est = ClaudeCliResearcher(runner=lambda c: fake_runner(c)).research(_m())
    assert est.prob == 0.4
    assert est.signals["source_count"] == 2


def test_raises_on_cli_error_envelope():
    def fake_runner(cmd):
        return json.dumps({"type": "result", "subtype": "error",
                           "is_error": True, "result": "", "usage": {}})

    r = ClaudeCliResearcher(runner=lambda c: fake_runner(c))
    try:
        r.research(_m())
        assert False, "expected ResearchError"
    except Exception as e:
        assert "research" in str(e).lower() or "cli" in str(e).lower()
