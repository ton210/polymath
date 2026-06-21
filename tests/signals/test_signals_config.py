from polymath.config import default_config


def test_directional_config_defaults():
    c = default_config()
    assert c.bet_window_hours == 48
    assert c.bets_per_day == 8
    assert c.bet_stake == 100.0
    assert c.min_edge == 0.05
    assert c.max_edge == 0.25
    assert c.min_price == 0.10
    assert c.max_price == 0.90
    assert c.claude_cli_path == "claude"
    assert c.bet_min_liquidity >= 0
