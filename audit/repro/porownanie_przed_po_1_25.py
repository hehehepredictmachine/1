"""Before / after 1.25 (prompt MC §4A, §3, §8) - reproducible on the terminal SIMULATOR, data SYNTHETIC_TEST only.

  export   --backend DIR --out FILE   the same export scenarios against ANY backend folder: the code before the changes
                                      (`git archive 0a57370 backend | tar -x -C <dir>`) and the current `backend/`
  scalping --dataset DIR --out FILE   SCALPING replay (same code as live) with TP3 = 5 / 7.5 / 10 USD on one export
                                      [--last-m1 N] limits the replay to the last N closed M1 bars

Scenarios of `export` (E-numbers = docs/AUDYT_MC_STREFY_EKSPORT_PL.md):
  S1 complete export M1/M5/M15            - files, real_volume column (E6), status file, model readiness (E10)
  S2 failed re-export into a used folder  - does the folder still look complete? (E5)
  S3 crash, damaged checkpoint, resume    - does the resume finish? (E4)
  S4 date range from-to (E8), S5 Bid/Ask ticks (E7) - supported or not
Nothing here connects to a real terminal or sends orders."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("MQ_FAKE_MARKET_ALWAYS_OPEN", "1")


def _setup(backend: Path):
    sys.path.insert(0, str(backend))
    os.environ["MASTERQUO_DATA_DIR"] = tempfile.mkdtemp(prefix="mq_cmp_data_")
    from masterquo.mt5 import fake as F
    markets = dict(F.SYN_MARKETS, **getattr(F, "BTCUSDT_SYN", {}))
    mt5 = F.FakeMT5(markets=markets)
    sys.modules["MetaTrader5"] = mt5
    return mt5


def _call(fn, *a, **k) -> dict:
    t0 = time.time()
    try:
        rc = fn(*a, **k)
        return {"rc": rc, "exception": None, "seconds": round(time.time() - t0, 1)}
    except Exception as exc:  # noqa: BLE001 - the point is to record what the user would see
        return {"rc": None, "exception": f"{type(exc).__name__}: {str(exc)[:200]}", "where": traceback.format_exc().strip().splitlines()[-3][:200],
                "seconds": round(time.time() - t0, 1)}


def _folder(out: Path) -> dict:
    st = out / "EXPORT_STATUS.json"
    meta = out / "source_metadata.json"
    r = {"status_file": json.loads(st.read_text(encoding="utf-8")).get("status") if st.exists() else None, "source_metadata": meta.exists(),
         "csv": sorted(p.name for p in out.glob("*.csv")), "readiness_file": (out / "MODEL_DATA_READINESS.json").exists()}
    # what a reader that only looks for the metadata (the training runner before 1.25) concludes
    r["looks_complete_to_old_reader"] = r["source_metadata"]
    try:
        from masterquo.forecast.export import dataset_state
        s = dataset_state(out)
        r["dataset_state"] = {"state": s.get("state"), "usable": s.get("usable")}
    except ImportError:
        r["dataset_state"] = "brak funkcji (kod przed zmianami)"
    return r


def _crash_on(mt5, tf: str = "M15"):
    """The first request of `tf` fails: M1 and M5 are already saved (checkpoints), the export stops half way - the same point in
    the code before and after the changes."""
    orig = mt5.copy_rates_range
    const = getattr(mt5, "TIMEFRAME_" + tf)

    def crashing(sym, timeframe, *a, **k):
        if timeframe == const:
            raise OSError("symulowana awaria w trakcie eksportu (zanik zasilania / zamknięcie terminala)")
        return orig(sym, timeframe, *a, **k)
    mt5.copy_rates_range = crashing
    return lambda: setattr(mt5, "copy_rates_range", orig)


def cmd_export(backend: Path) -> dict:
    mt5 = _setup(backend)
    from masterquo.forecast.export import export_candles
    root = Path(tempfile.mkdtemp(prefix="mq cmp ąę "))
    res = {"backend": str(backend), "data": "SYNTHETIC_TEST (FakeMT5)", "scenarios": {}}

    def ex(out, months=1, **kw):
        return _call(export_candles, months, str(out), "AUTO", ("M1", "M5", "M15"), "training", "XAUUSD", "XAUUSD-", **kw)

    try:
        # S1
        out = root / "S1 pełny"
        r = ex(out)
        f = _folder(out)
        head = (out / "XAUUSD_M5.csv").read_text(encoding="utf-8").splitlines()[0].split(",") if (out / "XAUUSD_M5.csv").exists() else []
        res["scenarios"]["S1_complete"] = dict(r, **f, real_volume_column="real_volume" in head)
        # S2: a complete folder, then a re-export of a longer range into it fails half way
        restore = _crash_on(mt5)
        r = ex(out, months=2)
        restore()
        res["scenarios"]["S2_failed_reexport_into_used_folder"] = dict(r, **_folder(out))
        # S3: crash during the first export, a checkpoint damaged by the interrupted write, then a plain resume
        out3 = root / "S3 wznowienie"
        restore = _crash_on(mt5)
        r1 = ex(out3)
        restore()
        cks = sorted((out3 / "chunks").glob("M5_*.json"))
        damaged = None
        if cks:
            damaged = cks[0].name
            cks[0].write_text(cks[0].read_text(encoding="utf-8")[:300], encoding="utf-8")
        mt5.initialize()
        r2 = ex(out3)
        res["scenarios"]["S3_crash_damaged_checkpoint_resume"] = {"crash_run": r1, "damaged_checkpoint": damaged, "resume_run": r2, **_folder(out3)}
        # S4 / S5: options of the new export
        mt5.initialize()
        r = ex(root / "S4 zakres", date_from="2026-03-02", date_to="2026-03-13T00:00Z")
        res["scenarios"]["S4_date_range"] = dict(r, supported=r["exception"] is None or "unexpected keyword" not in (r["exception"] or ""))
        mt5.initialize()
        out5 = root / "S5 ticki"
        r = _call(export_candles, 1, str(out5), "AUTO", ("M1",), "training", "XAUUSD", "XAUUSD-", tick_days=0.1)
        man = out5 / "ticks" / "TICKS_MANIFEST.json"
        res["scenarios"]["S5_bid_ask_ticks"] = dict(r, supported=r["exception"] is None or "unexpected keyword" not in (r["exception"] or ""),
                                                    manifest=json.loads(man.read_text(encoding="utf-8")) if man.exists() else None)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(os.environ["MASTERQUO_DATA_DIR"], ignore_errors=True)
    return res


def cmd_scalping(backend: Path, dataset: Path, last_m1: int | None) -> dict:
    sys.path.insert(0, str(backend))
    os.environ["MASTERQUO_DATA_DIR"] = tempfile.mkdtemp(prefix="mq_cmp_data_")
    from masterquo.sh import config as C
    from masterquo.sh import replay as RP
    from masterquo.sh.units import SymbolSpec
    bars, meta = RP.load_dataset(dataset, last_m1=last_m1)
    cfg = C.load()
    ic = cfg["instruments"]["XAUUSD"]
    spec = SymbolSpec.from_mt5(meta.get("spec") or {}, None, source="DATASET")
    comm = (meta.get("costs") or {}).get("commission_per_lot_side")
    comm = ic.get("commission_per_lot_side") if comm is None else comm
    slip = float(ic.get("slippage_usd") or 0.0)
    out = {"dataset": meta.get("dataset_id"), "data_kind": meta.get("data_kind"), "m1_bars": len(bars["M1"]), "commission_per_lot_side": comm,
           "slippage_usd": slip, "unit": "R = wynik całego cyklu / ryzyko planu; wynik netto po spreadzie i poślizgu" +
                                         ("" if comm is not None else " (prowizja NIEZNANA – nieuwzględniona)"), "variants": {}}
    for tp3 in (5.0, 7.5, 10.0):
        prof = C.profile(cfg, "XAUUSD", "SCALPING")
        prof["tp_usd"] = [prof["tp_usd"][0], prof["tp_usd"][1], tp3]
        market = RP.Market(bars, spread_fallback=float(ic.get("max_spread_usd") or 0.3) / 2)
        t0 = time.time()
        res = RP.run(market, spec, {"SCALPING": prof}, slip=slip, commission_side=comm)["SCALPING"]
        rep = RP.report(res, "SCALPING", meta=meta)
        out["variants"][f"TP3={tp3:g}"] = {"counts": res["counts"], "trades": len(res["trades"]), "metrics_R": rep.get("metrics"),
                                          "metrics_price_usd": rep.get("metrics_price"), "hit_rates": rep.get("hit_rates"),
                                          "by_exit": rep.get("by_exit"), "baseline_R": RP.metrics(res["baseline"]), "seconds": round(time.time() - t0, 1)}
    shutil.rmtree(os.environ["MASTERQUO_DATA_DIR"], ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--backend", required=True)
    e.add_argument("--out", required=True)
    s = sub.add_parser("scalping")
    s.add_argument("--backend", default=str(Path(__file__).resolve().parents[2] / "backend"))
    s.add_argument("--dataset", required=True)
    s.add_argument("--last-m1", type=int, default=None)
    s.add_argument("--out", required=True)
    a = ap.parse_args()
    res = cmd_export(Path(a.backend).resolve()) if a.cmd == "export" else cmd_scalping(Path(a.backend).resolve(), Path(a.dataset), a.last_m1)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
