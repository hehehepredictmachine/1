"""Pipeline validation of the 15 model families on CONTROLLED SYNTHETIC data (data_kind = SYNTHETIC) - 1.33 release check.

What it proves: every family trains -> saves (manifest + checksums) -> loads -> predicts a valid PMW-PRED-2 result with the real
dependencies, and its validation gate gives the expected verdict on data with a KNOWN structure (AR(1)+GARCH returns, a cointegrated
pair, a 3-series basket, an order book whose imbalance leads the mid, a labelled headline corpus). It does NOT measure profitability
and its numbers are not a forecast of results on real XAUUSD/BTC data (SYNTHETIC is never eligible for ASSIST).

  python tools/validate_families_synthetic.py --out docs/RAPORT_WALIDACJI_MODELI.json [--profile smoke] [--deep-python PATH]

Runs in an isolated temporary family store (PMW_FAMILIES_DIR) - the bot's own artifacts are never touched.
TH_RF / TH_SVM / TH_XGB are trained by trainhub (tests/test_trainhub.py); SEQ_GRU_EVENT by the MM centre - reported as DELEGATED.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
T0 = 1_772_409_600


def synth(n, tf_s=300, seed=1, phi=0.25, garch=True, start=2000.0):
    import numpy as np
    rng = np.random.default_rng(seed)
    r, v, out, c = 0.0, 1e-6, [], start
    for i in range(n):
        v = 2e-8 + 0.08 * r * r + 0.9 * v if garch else 1e-6
        r = phi * r + math.sqrt(v) * rng.standard_normal()
        o, c = c, c * math.exp(r)
        h, lo = max(o, c) * (1 + abs(rng.normal(0, 2e-4))), min(o, c) * (1 - abs(rng.normal(0, 2e-4)))
        out.append({"t": T0 + i * tf_s, "o": o, "h": h, "l": lo, "c": c, "tv": int(50 + rng.integers(0, 50)), "spread": 20})
    return out


def datasets() -> dict:
    import numpy as np
    d = {"instrument": "XAUUSD", "point": 0.01, "data_kind": "SYNTHETIC", "symbol": "XAUUSD-"}
    m5 = synth(4000, seed=1, phi=0.25)
    out = {f: dict(d, bars=m5) for f in ("TS_ARIMA", "VOL_GARCH", "KALMAN_LS", "BREAKOUT")}
    out["TS_SARIMAX"] = dict(d, bars=synth(2000, tf_s=3600, seed=2, phi=0.2))
    out["SEQ_LSTM"] = out["SEQ_GRU"] = dict(d, bars=synth(3500, seed=11, phi=0.3))
    out["RL_PPO"] = dict(d, bars=synth(3200, seed=12))
    rng = np.random.default_rng(1)
    x = np.cumsum(rng.normal(0, 0.01, 1200)) + 7.0
    y = 0.5 + 0.8 * x + rng.normal(0, 0.003, 1200)
    out["PAIR_COINT"] = dict(d, pair=["XAUUSD", "BTC"], pair_bars=[[{"t": T0 + i * 3600, "c": float(np.exp(y[i]))} for i in range(1200)],
                                                                   [{"t": T0 + i * 3600, "c": float(np.exp(x[i]))} for i in range(1200)]])
    rng = np.random.default_rng(2)
    f = np.cumsum(rng.normal(0, 0.01, 900))
    out["STATARB"] = dict(d, basket=["A", "B", "C"], basket_bars=[[{"t": T0 + i * 3600, "c": float(np.exp(5 + k * 0.3 * f[i] + rng.normal(0, 0.002)))}
                                                                   for i in range(900)] for k in (1, 2, 3)])
    rng = np.random.default_rng(3)
    books, mid = [], 2000.0
    for i in range(6000):
        qb, qa = float(rng.integers(1, 10)), float(rng.integers(1, 10))
        books.append({"t": float(i), "bids": [(mid - 0.05, qb), (mid - 0.15, 3.0)], "asks": [(mid + 0.05, qa), (mid + 0.15, 3.0)]})
        mid += 0.01 * np.sign(qb - qa) + rng.normal(0, 0.002)
    out["MICROSTRUCTURE"] = dict(d, books=books)
    return out


def corpus(tmp: Path):
    import numpy as np
    from masterquo.modelhub.families import nlp as NL
    rng = np.random.default_rng(4)
    pos, neg, neu = ["gold rallies", "bullion surges", "strong demand lifts"], ["gold plunges", "prices slump", "sell-off deepens"], \
        ["market waits", "traders eye data", "session opens quietly"]
    rows = []
    for i in range(600):
        k = i % 3
        w = (pos, neu, neg)[k][i % 3] + f" item {i} " + " ".join(rng.choice(["today", "again", "now", "on fed"], 2))
        rows.append({"text": w, "label": ("POSITIVE", "NEUTRAL", "NEGATIVE")[k], "first_seen_at": f"2026-01-{1 + i % 28:02d}T00:{i % 60:02d}:00Z"})
    p = tmp / "corpus.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    NL.import_file(p)
    return NL.load_corpus()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--profile", default="smoke", choices=["smoke", "research", "full"])
    ap.add_argument("--deep-python", default=None, help="python of .venv_deep (else MQ_DEEP_PYTHON / default location)")
    a = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="pmw_famval_"))
    os.environ["PMW_FAMILIES_DIR"] = str(tmp)
    if a.deep_python:
        os.environ["MQ_DEEP_PYTHON"] = a.deep_python
    from masterquo.modelhub.families import base as B
    from masterquo.modelhub.families import registry
    from masterquo.modelhub.families import run as RUN
    store = B.Store(tmp)
    ds = datasets()
    ds["NLP_SENTIMENT"] = {"instrument": "XAUUSD", "data_kind": "SYNTHETIC", "corpus": corpus(tmp)}
    rows = []
    for fid, fam in registry().items():
        t0 = time.time()
        if fid not in ds:
            rows.append({"family": fid, "state": "DELEGATED", "reason": "trainhub (test_trainhub) / centrum MM", "seconds": 0})
            continue
        r = RUN.train(fid, "XAUUSD", a.profile, {}, data=ds[fid], store=store)
        row = {"family": fid, "task_type": fam.TASK_TYPE, "task": fam.TASK, "state": r.get("state"), "reason": r.get("reason"), "run_id": r.get("run_id"),
               "seconds": round(time.time() - t0, 1)}
        if r.get("state") == "DONE":
            man = store.runs(fid, "XAUUSD")[-1]
            row["validation"] = man.get("validation")
            row["metrics"] = man.get("metrics")
            row["rows"] = (man.get("data") or {}).get("rows")
            try:
                art = fam.load(store.run_dir(fid, "XAUUSD", r["run_id"]))
                live = {k: v for k, v in ds[fid].items() if k in ("bars", "pair_bars", "basket_bars", "books")}
                if fid == "NLP_SENTIMENT":
                    live = {"news": [{"headline": "Gold rallies on strong demand", "first_seen_at": "2026-11-06T10:00:00Z"}]}
                if fid == "MICROSTRUCTURE":                       # live input = a READY PMW-IND-1 book measurement (as IndicatorService gives)
                    bk = ds[fid]["books"][-1]
                    (bp, bq), (ap_, aq) = bk["bids"][0], bk["asks"][0]
                    mid = (bp + ap_) / 2
                    dq = sum(q for _, q in bk["bids"]), sum(q for _, q in bk["asks"])
                    live = {"spread": ap_ - bp, "micro": {"status": "READY", "values": {
                        "best_imbalance": (bq - aq) / (bq + aq), "depth_imbalance": (dq[0] - dq[1]) / (dq[0] + dq[1]), "ofi_window": 0.0,
                        "microprice_dev": (ap_ * bq + bp * aq) / (bq + aq) - mid, "mid": mid, "bid_levels": len(bk["bids"])}}}
                res = fam.predict(art, live)
                p = fam.pred(inst="XAUUSD", symbol="XAUUSD-", state="READY", result=res, run_id=r["run_id"], data_time="2026-11-06T10:00:00Z",
                             data_kind="SYNTHETIC")
                row["prediction"] = {"contract": p["contract"], "state": p["state"], "result": p["result"]}
            except Exception as exc:  # noqa: BLE001 - reported, never hidden
                row["prediction"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        rows.append(row)
        print(f"{fid:16s} {row['state']:10s} {row['seconds']:7.1f}s {(row.get('validation') or {}).get('status', row.get('reason') or '')}", flush=True)
    rep = {"report": "PMW-FAM-VALIDATION-SYNTHETIC-1", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "profile": a.profile,
           "data_kind": "SYNTHETIC", "python": platform.python_version(), "platform": platform.platform(),
           "deep_python": os.environ.get("MQ_DEEP_PYTHON"), "families": rows,
           "note": "dane syntetyczne o znanej strukturze – sprawdzenie potoku trening→zapis→ładowanie→predykcja i bramki walidacji, nie rentowności"}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
