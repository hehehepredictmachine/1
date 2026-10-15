"""SYNTHETIC_TEST data for code tests only (never a market result): mean-reverting M1 random walk with occasional
wick spikes, per-bar spread, written in the bot's export format (data_kind SYNTHETIC_TEST)."""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def m1_bars(days: int = 20, seed: int = 1, start=datetime(2026, 3, 2, tzinfo=timezone.utc)) -> list[dict]:
    r = random.Random(seed)
    p, center, out = 2000.0, 2000.0, []
    t = start
    n = 0
    while len(out) < days * 1440:
        if t.weekday() >= 5:                                   # weekend gap: no bars
            t += timedelta(minutes=1)
            continue
        if n % 240 == 0:
            center = p
        o = p
        c = o - (p - center) * 0.05 + r.gauss(0, 0.6)
        h = max(o, c) + abs(r.gauss(0, 0.4))
        lo = min(o, c) - abs(r.gauss(0, 0.4))
        if r.random() < 0.02:
            lo -= r.uniform(0.5, 2.0)
        if r.random() < 0.02:
            h += r.uniform(0.5, 2.0)
        out.append({"open_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": round(o, 2), "h": round(h, 2), "l": round(lo, 2), "c": round(c, 2),
                    "tv": r.randint(50, 200), "spread_price": 0.12})
        p = c
        t += timedelta(minutes=1)
        n += 1
    return out


def write_export(out: Path, bars: list[dict]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "XAUUSD_M1.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time_open_utc", "open", "high", "low", "close", "tick_volume", "symbol", "spread_points", "time_server_raw", "dst_ambiguous"])
        for b in bars:
            w.writerow([b["open_utc"], b["o"], b["h"], b["l"], b["c"], b["tv"], "XAUUSD-", round(b["spread_price"] / 0.01), 0, 0])
    meta = {"symbol": "XAUUSD-", "data_kind": "SYNTHETIC_TEST", "tick_size": 0.01, "cutoff_utc": bars[-1]["open_utc"],
            "spec": {"point": 0.01, "trade_tick_size": 0.01, "trade_contract_size": 100.0, "volume_min": 0.01, "volume_step": 0.01},
            "timeframes": ["M1"], "source": "SYNTHETIC_TEST_GENERATOR"}
    (out / "source_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return out
