from polymath.signals.estimate import Estimate


def test_estimate_holds_fields_and_defaults():
    e = Estimate(prob=0.62, confidence=0.7, category="sports",
                 signals={"source_count": 4}, rationale="home team favored")
    assert e.prob == 0.62
    assert e.confidence == 0.7
    assert e.category == "sports"
    assert e.signals["source_count"] == 4
    assert e.rationale == "home team favored"


def test_estimate_clamps_prob_into_unit_interval():
    assert Estimate(prob=1.4, confidence=0.5, category="x", signals={}, rationale="").prob == 1.0
    assert Estimate(prob=-0.2, confidence=0.5, category="x", signals={}, rationale="").prob == 0.0
