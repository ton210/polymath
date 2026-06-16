from polymath.config import Config, default_config, load_config


def test_default_config_has_sane_values():
    c = default_config()
    assert c.min_roi >= 0.0
    assert c.fee_bps == 0.0
    assert c.bankroll == 10_000.0
    assert "default" in c.profiles


def test_profile_overrides_thresholds():
    c = default_config()
    c.profiles["roi-2pct"] = {"min_roi": 0.02}
    eff = c.effective("roi-2pct")
    assert eff.min_roi == 0.02
    assert eff.fee_bps == c.fee_bps   # untouched fields inherit base


def test_load_config_from_toml(tmp_path):
    p = tmp_path / "polymath.toml"
    p.write_text(
        "min_roi = 0.01\nbankroll = 5000\n\n[profiles.aggressive]\nmin_roi = 0.005\n"
    )
    c = load_config(p)
    assert c.min_roi == 0.01
    assert c.bankroll == 5000
    assert c.effective("aggressive").min_roi == 0.005
