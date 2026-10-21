"""Test helper: a training-format dataset (CSV per TF + source_metadata.json) built from the SIMULATED terminal and clearly marked
SYNTHETIC_TEST. Only for tests of the pipeline mechanics - never a basis for any statement about strategy quality."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def build(out: Path, m1_bars: int = 4000, seed: int = 7) -> Path:
    from masterquo.mt5.fake import FakeMT5
    f = FakeMT5(seed=seed)
    f.initialize()
    out.mkdir(parents=True, exist_ok=True)
    info = f.symbol_info("XAUUSD-")
    off = 3 * 3600
    counts = {"M1": m1_bars, "M5": m1_bars // 5 + 500, "M15": m1_bars // 15 + 400, "H1": m1_bars // 60 + 400}
    tfc = {"M1": f.TIMEFRAME_M1, "M5": f.TIMEFRAME_M5, "M15": f.TIMEFRAME_M15, "H1": f.TIMEFRAME_H1}
    rng = {}
    for tf, n in counts.items():
        r = f.copy_rates_from_pos("XAUUSD-", tfc[tf], 1, n)
        with (out / f"XAUUSD_{tf}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["time_open_utc", "open", "high", "low", "close", "tick_volume", "symbol", "spread_points", "time_server_raw", "dst_ambiguous"])
            for x in r:
                t = datetime.fromtimestamp(int(x["time"]) - off, tz=timezone.utc).isoformat().replace("+00:00", "Z")
                w.writerow([t, x["open"], x["high"], x["low"], x["close"], int(x["tick_volume"]), "XAUUSD-", int(x["spread"]), int(x["time"]), 0])
        rng[tf] = (r[0]["time"], r[-1]["time"])
    spec = {k: getattr(info, k) for k in ("name", "digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size", "currency_base",
                                          "currency_profit", "volume_min", "volume_step", "volume_max")}
    meta = {"symbol": "XAUUSD-", "instrument": "XAUUSD", "file_prefix": "XAUUSD", "dataset_id": f"SYNTH-{seed}-{m1_bars}", "data_kind": "SYNTHETIC_TEST",
            "spec": spec, "tick_size": info.trade_tick_size, "costs": {"commission_per_lot_side": None, "source": "UNKNOWN"},
            "range_utc": [str(rng["M1"][0]), str(rng["M1"][1])], "spread_unit": "points (x spec.point = price)"}
    (out / "source_metadata.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    (out / "DATA_QUALITY_REPORT.json").write_text(json.dumps({"timeframes": {tf: {"rows": n} for tf, n in counts.items()}}), encoding="utf-8")
    return out
