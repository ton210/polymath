from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Estimate:
    prob: float                       # estimated probability of the YES outcome
    confidence: float                 # 0..1 self-reported confidence
    category: str                     # "sports" | "politics" | "world-news" | ...
    signals: dict = field(default_factory=dict)
    rationale: str = ""

    def __post_init__(self) -> None:
        self.prob = max(0.0, min(1.0, float(self.prob)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
