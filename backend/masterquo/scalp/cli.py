"""`python -m masterquo scalp-replay` - replay of the scalp profile on an exported MT5 history (data/scalp/history/<cutoff>)."""
from __future__ import annotations

import csv
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from . import replay, report, strategy as st


def latest_history(kind: str = "scalp") -> Path | None:
    h = sorted((paths.data_dir() / kind / "history").glob("*/source_metadata.json"))
    return h[-1].parent if h else None


def load_csv(path: Path, point: float) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sp = r.get("spread_points")
            out.append({"open_utc": r["time_open_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                        "tv": float(r["tick_volume"]) if r.get("tick_volume") not in (None, "") else None,
                        "spread_price": float(sp) * point if sp not in (None, "") else None})
    return out


def replay_cmd(a) -> int:
    hist = Path(a.history) if a.history else latest_history()
    if not hist or not (hist / "source_metadata.json").exists():
        print("[BLAD] BLOCKED_NO_REAL_DATA: brak eksportu historii scalp (16_EKSPORT_HISTORII_SCALP.bat przy działającym MT5).")
        return 3
    meta = json.loads((hist / "source_metadata.json").read_text(encoding="utf-8"))
    spec = meta["spec"]
    if not (hist / "XAUUSD_M1.csv").exists():
        print("[BLAD] eksport bez M1 – użyj export-scalp (M1/M5/M15/M30/H1).")
        return 3
    tick, point, cs = float(spec["trade_tick_size"]), float(spec.get("point") or spec["trade_tick_size"]), float(spec["trade_contract_size"])
    prof = st.load_profile()
    t0 = time.time()
    bars = {tf: load_csv(hist / f"XAUUSD_{tf}.csv", point) for tf in ("M1", "M5", "M15", "M30") if (hist / f"XAUUSD_{tf}.csv").exists()}
    k = a.cost_stress
    costs = {"commission_price_side": k * a.commission_per_lot_side / cs, "slippage_price": k * a.slippage_ticks * tick}
    res = replay.run(bars["M1"], prof, tick, costs, bars.get("M5"), bars.get("M15"), bars.get("M30"), margin_mode=a.margin_mode)
    out = paths.data_dir() / "scalp" / "replay" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    summ = {"data_kind": meta.get("data_kind"), "history": str(hist), "profile_id": prof["profile_id"], "profile_hash": st.profile_hash(prof),
            "costs": {"commission_per_lot_side": a.commission_per_lot_side, "slippage_ticks": a.slippage_ticks, "cost_stress": k,
                      "spread": "per-bar spread z eksportu MT5 (punkty × point)"},
            "margin_mode_assumed": a.margin_mode, "strategy": report.strategy_summary(res["cycles"], st.V(prof, "risk", "cycle_risk_pct_equity")),
            "hedge_vs_reduce": report.hedge_summary(res["decisions"]), "blocked_counts": _count(res["blocked"]),
            "precision": res["precision"], "seconds": round(time.time() - t0, 1),
            "command": " ".join(sys.argv), "python": sys.executable, "python_version": platform.python_version(),
            "note": "Replay OHLC jest przybliżony; nie potwierdza brokerowego wykonania. SYNTHETIC_TEST nie jest wynikiem rynkowym."}
    (out / "summary.json").write_text(json.dumps(summ, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "cycles.json").write_text(json.dumps(res["cycles"], ensure_ascii=False), encoding="utf-8")
    (out / "decisions.json").write_text(json.dumps(res["decisions"], ensure_ascii=False), encoding="utf-8")
    (out / "blocked.json").write_text(json.dumps(res["blocked"], ensure_ascii=False), encoding="utf-8")
    s = summ["strategy"]
    print(f"[OK] cykle {s['cycles']}, dni {s['days']}, status {s['status']} – {s.get('reason', '')}")
    print(f"     hedge vs REDUCE: {summ['hedge_vs_reduce']['status']}")
    print(f"Zapisano: {out}")
    return 0


def _count(rows: list[dict]) -> dict:
    c: dict[str, int] = {}
    for r in rows:
        k = r["reason"].split(":")[0]
        c[k] = c.get(k, 0) + 1
    return c
