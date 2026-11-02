"""python -m masterquo trainhub <command>  (also 32_CENTRUM_TRENINGU.bat)

  export        --instrument XAUUSD|BTC [--mode incremental|historical] [--from ISO] [--to ISO] [--lookback-days 90] [--tf M1,M5,M15,M30]
                (own MT5 connection - Windows with a logged-in terminal; --demo = terminal simulator, SYNTHETIC data)
  import-data   --instrument X <folder|zip>     merge candles exported on another machine (checksums verified first)
  dataset       --instrument X [--base-tf M5] [--horizon 6] [--k-atr 0.25] [--from] [--to]
  train         --instrument X [--models TH_BASELINE,TH_LOGREG,TH_HGB] [same options]     (never activates)
  evaluate      --instrument X --model-key KEY --version V        (forward check on data after the training range)
  full          --instrument X [...]       export -> validation -> dataset -> train -> evaluation -> packages
  list          --instrument X             versions, metrics, active version
  activate      --instrument X --model-key KEY --version V        (compatibility + prediction test, else refused)
  rollback      --instrument X --model-key KEY
  package-zip   --instrument X --model-key KEY --version V [--out file.zip]
Exit codes: 0 ok, 1 error, 2 insufficient data / bad arguments, 3 refused (incompatible), 4 MT5 unavailable.
"""
from __future__ import annotations

import argparse
import json
import sys


def _p(o) -> None:
    print(json.dumps(o, indent=1, ensure_ascii=False, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="masterquo trainhub", description="Centrum treningu – eksport, dataset, trening, ocena, aktywacja")
    ap.add_argument("cmd", choices=["export", "import-data", "dataset", "train", "evaluate", "full", "list", "activate", "rollback", "package-zip"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--instrument", default="XAUUSD")
    ap.add_argument("--mode", default="incremental", choices=["incremental", "historical"])
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--lookback-days", type=float, default=90.0)
    ap.add_argument("--tf", default="M1,M5,M15,M30")
    ap.add_argument("--base-tf", default=None)
    ap.add_argument("--horizon", type=int, default=None)
    ap.add_argument("--k-atr", type=float, default=None)
    ap.add_argument("--models", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--commission-price", type=float, default=None, help="prowizja round-trip na 1 lot w jednostkach ceny (zastępuje historię transakcji)")
    ap.add_argument("--model-key")
    ap.add_argument("--version")
    ap.add_argument("--out")
    ap.add_argument("--demo", action="store_true", help="symulator terminala (dane SYNTETYCZNE – tylko test mechaniki)")
    a = ap.parse_args(argv)
    inst = a.instrument.upper()
    if inst not in ("XAUUSD", "BTC"):
        print("Instrument: XAUUSD albo BTC (trenowane i oceniane osobno).", file=sys.stderr)
        return 2
    from ..config import ConfigStore
    from ..marketdata import export as EX
    from ..marketdata.store import Store
    from . import dataset as DS
    from . import pipeline as P
    from . import registry as R
    cfg_all = ConfigStore().get()
    store = Store()
    params = {k: v for k, v in {"base_tf": a.base_tf, "horizon": a.horizon, "k_atr": a.k_atr, "seed": a.seed, "start": a.start, "end": a.end,
                                "commission_price": a.commission_price,
                                "models": a.models.split(",") if a.models else None}.items() if v is not None}
    try:
        if a.cmd in ("export", "full"):
            from ..marketdata.sources import DirectSource, SourceError, open_direct
            if a.demo:
                from ..mt5.fake import FakeMT5
                fake = FakeMT5(history_days=int(max(a.lookback_days, 30)) + 10)
                fake.initialize()
                src, sym = DirectSource(fake, offset=fake.offset, offset_basis="SIMULATOR"), "XAUUSD-" if inst == "XAUUSD" else "BTCUSD-"
            else:
                try:
                    src = open_direct(cfg_all)
                except SourceError as exc:
                    print(f"[BŁĄD] {exc}", file=sys.stderr)
                    return 4
                m = cfg_all.assets.mappings.get(inst)
                sym = m.broker_symbol if m and m.broker_symbol else None
                if not sym:
                    print(f"[BŁĄD] brak symbolu brokera dla {inst} (Ustawienia → Instrumenty)", file=sys.stderr)
                    return 2
            print(f"Eksport {inst} ({sym}) {a.mode} – partie po {EX.CHUNK_BARS} świec, wznowienie po przerwaniu")
            res = EX.run(src, store, inst, sym, timeframes=tuple(a.tf.split(",")), mode=a.mode, start=a.start, end=a.end,
                         lookback_days=a.lookback_days, cfg=cfg_all,
                         progress=lambda p: print(f"  {p['tf']} partia {p['chunk']}/{p['chunks']} +{p['rows_added']}", flush=True))
            _p({tf: {k: v[k] for k in ("requested_from_utc", "requested_to_utc", "added", "duplicates", "conflicts", "invalid")}
                for tf, v in res["timeframes"].items()})
            print(f"Status: {res['status']} {res.get('reason') or ''}")
            if res["status"] != "COMPLETE":
                return 1
            if a.cmd == "export":
                return 0
        if a.cmd == "import-data":
            if not a.path:
                print("Podaj folder albo zip", file=sys.stderr)
                return 2
            _p(EX.import_folder(store, inst, a.path))
            return 0
        if a.cmd in ("dataset", "train", "full"):
            cfg = P.config(params, store.manifest(inst), cfg_all.costs)
            print(f"Koszty w etykietach: {cfg['cost_status']}")
            _p(P.stage_validate(store, inst))
            ds, desc = P.stage_dataset(store, inst, cfg, progress=lambda p: print("  " + p.get("stage", "")))
            _p({k: desc[k] for k in ("rows_total", "rows_usable", "dropped", "class_counts", "range_utc", "data_kind", "hash")})
            if a.cmd == "dataset":
                return 0
            out = P.stage_train(store, inst, cfg, progress=lambda p: print("  " + " ".join(str(p.get(k, "")) for k in ("stage", "model", "fold"))),
                                ds=ds, desc=desc)
            for pk in out["packages"]:
                h = pk["holdout"]
                print(f"{pk['model_key']} {pk['version']}: holdout log loss {h['log_loss']} (bazowy {h['baseline_log_loss']}, skill "
                      f"{h['skill_vs_baseline']}), Brier {h['brier']}, ECE {h['ece']}; WF lepszy od bazowego {pk['walk_forward']['folds_beating_baseline']}; "
                      f"dane {pk['data_kind']}")
            for sk in out["skipped"]:
                print(f"pominięto {sk['model']}: {sk['reason']}")
            print(out["note"])
            return 0
        if a.cmd == "evaluate":
            _p(P.stage_evaluate(store, inst, a.model_key, a.version))
            return 0
        if a.cmd == "list":
            _p(R.summary(inst))
            return 0
        if a.cmd == "activate":
            r = R.activate(inst, a.model_key, a.version, reason="CLI")
            _p(r)
            return 0 if r["ok"] else 3
        if a.cmd == "rollback":
            _p(R.rollback(inst, a.model_key))
            return 0
        if a.cmd == "package-zip":
            from pathlib import Path
            out = Path(a.out or f"{inst}_{a.model_key}_{a.version}.zip")
            print(R.export_zip(inst, a.model_key, a.version, out))
            return 0
    except DS.InsufficientData as exc:
        print(f"[ZA MAŁO DANYCH] {exc}", file=sys.stderr)
        return 2
    except (ValueError, R.IncompatiblePackage) as exc:
        print(f"[BŁĄD] {exc}", file=sys.stderr)
        return 2
    return 1
