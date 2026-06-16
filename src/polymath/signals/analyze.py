from __future__ import annotations

import statistics


def _won(row: dict) -> bool:
    return row.get("status") == "won"


def _calibration(settled: list[dict]) -> list[dict]:
    buckets = []
    for lo in [i / 10 for i in range(0, 10)]:
        hi = lo + 0.1
        last = lo >= 0.9 - 1e-9   # include our_prob == 1.0 in the final bucket
        grp = [r for r in settled
               if lo <= float(r["our_prob"]) < hi
               or (last and float(r["our_prob"]) == 1.0)]
        if not grp:
            buckets.append({"bucket": f"{lo:.1f}-{hi:.1f}", "n": 0,
                            "predicted": None, "actual": None})
            continue
        buckets.append({
            "bucket": f"{lo:.1f}-{hi:.1f}", "n": len(grp),
            "predicted": statistics.mean(float(r["our_prob"]) for r in grp),
            "actual": sum(1 for r in grp if _won(r)) / len(grp),
        })
    return buckets


def _attribution(settled: list[dict]) -> dict:
    keys = set()
    for r in settled:
        for k, v in (r.get("signals") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                keys.add(k)
    out = {}
    for k in sorted(keys):
        vals = [(float(r["signals"][k]), r) for r in settled
                if isinstance(r.get("signals", {}).get(k), (int, float))
                and not isinstance(r["signals"][k], bool)]
        if len(vals) < 2:
            continue
        median = statistics.median(v for v, _ in vals)
        high = [r for v, r in vals if v >= median]
        low = [r for v, r in vals if v < median]

        def _summ(grp):
            if not grp:
                return {"n": 0, "win_rate": None, "roi": None}
            staked = sum(float(r["stake"]) for r in grp)
            pnl = sum(float(r["realized_pnl"]) for r in grp)
            return {"n": len(grp),
                    "win_rate": sum(1 for r in grp if _won(r)) / len(grp),
                    "roi": pnl / staked if staked else None}

        out[k] = {"median": median, "high": _summ(high), "low": _summ(low)}
    return out


def build_report(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("status") in ("won", "lost")]
    staked = sum(float(r["stake"]) for r in settled)
    pnl = sum(float(r["realized_pnl"]) for r in settled)
    wins = sum(1 for r in settled if _won(r))
    return {
        "settled": len(settled),
        "win_rate": (wins / len(settled)) if settled else 0.0,
        "total_pnl": pnl,
        "total_staked": staked,
        "roi": (pnl / staked) if staked else 0.0,
        "calibration": _calibration(settled),
        "attribution": _attribution(settled),
    }
