from polymath.ledger import Ledger


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = Ledger(path)
    led.append({"id": "a", "net_profit": 1.0})
    led.append({"id": "b", "net_profit": -0.5})
    rows = led.read_all()
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[1]["net_profit"] == -0.5


def test_read_all_missing_file_returns_empty(tmp_path):
    led = Ledger(tmp_path / "nope.jsonl")
    assert led.read_all() == []
