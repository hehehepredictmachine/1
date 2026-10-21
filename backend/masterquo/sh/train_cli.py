"""`python -m masterquo sh train` - SH event model + validation report from an exported training dataset (runner task sh_models).

1. Replay of SCALPING and HEDGING on the dataset with the live code (sh/replay.py), one plan at a time, conservative bars.
2. Event labels "TP2 before SL within the horizon" of the strategy's OWN setups -> sh_tp_model (chronological split with
   embargo = horizon, Platt calibration, holdout gate with a significance margin, atomic promotion only on real data).
3. Validation report per strategy (whole-cycle metrics, by side/session/mode, folds, baseline, HEDGE vs NO_HEDGE vs REDUCE).
   Real data only -> data/sh/validation/<INST>_<STRATEGY>.json (read by the hedge variant rule); synthetic -> run directory only.
Progress lines `[POSTEP] <strategy> <i>/<n>` are real counters of processed M1 bars (the panel shows them as they are).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .. import paths
from . import config as C
from . import replay as RP
from . import tpmodel as TM
from .units import SymbolSpec


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)


def train(dataset: Path, instrument: str, out: Path, *, allow_synthetic: bool = False, last_m1: int | None = None,
          strategies: tuple = ("SCALPING", "HEDGING"), min_n: int = 200, log=print) -> dict:
    t0 = time.time()
    bars, meta = RP.load_dataset(dataset, last_m1=last_m1)
    if meta.get("instrument") not in (None, instrument):
        raise ValueError(f"INSTRUMENT_MISMATCH {meta.get('instrument')} != {instrument}")
    real = meta.get("data_kind") == "REAL_USER_DATA"
    if not real and not allow_synthetic:
        raise ValueError("SYNTHETIC_DATA_REQUIRES_--allow-synthetic (wynik tylko techniczny)")
    cfg = C.load()
    ic = cfg["instruments"].get(instrument)
    result = {"instrument": instrument, "dataset": str(dataset), "dataset_id": meta.get("dataset_id"), "data_kind": meta.get("data_kind"),
              "symbol": meta.get("symbol"), "m1_bars": len(bars["M1"]), "config_hash": cfg["_hash"], "strategies": {}, "seed": 7,
              "command": f"python -m masterquo sh train --instrument {instrument} --dataset {dataset} --out {out}"
                         + (f" --last-m1 {last_m1}" if last_m1 else "") + (" --allow-synthetic" if allow_synthetic else "")}
    if not ic:
        result["status"] = "BLOCKED"
        result["reason"] = f"brak profilu SH dla {instrument}"
        _write(out, result)
        return result
    if ic.get("enabled") is False:
        result["status"] = "BLOCKED"
        result["reason"] = f"instrument {instrument} wyłączony w konfiguracji SH: {ic.get('status')}"
        _write(out, result)
        return result
    spec = SymbolSpec.from_mt5(meta.get("spec") or {}, None, source="DATASET")
    spec.check_usd(ic.get("unit_conversion"))
    comm = (meta.get("costs") or {}).get("commission_per_lot_side")
    comm = ic.get("commission_per_lot_side") if comm is None else comm
    slip = float(ic.get("slippage_usd") or 0.0)
    market = RP.Market(bars, spread_fallback=float(ic.get("max_spread_usd") or 0.3) / 2)
    profiles = {s: C.profile(cfg, instrument, s) for s in strategies}
    res_all = RP.run(market, spec, profiles, slip=slip, commission_side=comm, progress=lambda i, n: log(f"[POSTEP] replay {i}/{n}"))
    log(f"[POSTEP] replay {len(market.m1)}/{len(market.m1)}")
    for strat in strategies:
        prof, res = profiles[strat], res_all[strat]
        samples = res["samples"]
        model = TM.train(instrument, strat, samples, embargo_s=60.0 * prof["horizon_minutes"], min_n=min_n, log=log,
                         allow_promotion=real, provenance={"dataset_id": meta.get("dataset_id"), "data_kind": meta.get("data_kind"),
                                                           "config_hash": cfg["_hash"], "symbol": meta.get("symbol")})
        rep = RP.report(res, strat, meta=meta, model={k: model.get(k) for k in ("run_id", "verdict", "n", "split", "holdout", "reason", "promoted")})
        rep["commission_source"] = "eksport (terminal)" if (meta.get("costs") or {}).get("commission_per_lot_side") is not None else (
            "profil SH" if comm is not None else "NIEZNANA")
        rep["data_kind"] = meta.get("data_kind")
        _write(out.parent / f"{out.stem}_{strat}_report.json", rep)
        if real:
            _write(paths.data_dir() / "sh" / "validation" / f"{instrument}_{strat}.json", rep)
        result["strategies"][strat] = {"counts": res["counts"], "setups_ready": len(samples), "model": rep["event_model"],
                                       "metrics": rep.get("metrics"), "baseline": rep["baseline"], "variants": rep.get("variants"),
                                       "report": str(out.parent / f"{out.stem}_{strat}_report.json")}
    result["status"] = "DONE"
    result["seconds"] = round(time.time() - t0, 1)
    _write(out, result)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="masterquo sh")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="model zdarzenia SH + raport walidacji z eksportu treningowego")
    t.add_argument("--instrument", required=True, choices=("XAUUSD", "BTC"))
    t.add_argument("--dataset", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--last-m1", type=int, default=None, help="ogranicz replay do ostatnich N świec M1 (test instalacji)")
    t.add_argument("--allow-synthetic", action="store_true")
    t.add_argument("--strategies", default="SCALPING,HEDGING")
    a = ap.parse_args(argv)
    try:
        r = train(Path(a.dataset), a.instrument, Path(a.out), allow_synthetic=a.allow_synthetic, last_m1=a.last_m1,
                  strategies=tuple(s for s in a.strategies.split(",") if s in ("SCALPING", "HEDGING")))
    except Exception as exc:  # noqa: BLE001 - reported to the runner as a technical error with the reason
        print(f"[BLAD] {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps({"status": r.get("status"), "reason": r.get("reason"),
                      "models": {k: (v.get("model") or {}).get("verdict") for k, v in r.get("strategies", {}).items()}}, ensure_ascii=False))
    return 0 if r.get("status") in ("DONE", "BLOCKED") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
