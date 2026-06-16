from __future__ import annotations

import json
from pathlib import Path


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, row: dict) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as fh:
            return [json.loads(line) for line in fh if line.strip()]
