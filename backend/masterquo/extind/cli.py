"""`python -m masterquo indicator-context <cmd>` (MODULY_IQ_PAL_SAR.bat). Exit codes: 0 ok, 1 error, 2 blocked (no data / identity),
4 insufficient data. `record` never opens its own terminal session: the running bot's ExtIndService reads the exporter files."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INSTR = ("XAUUSD", "BTC")


def _latest_real(inst: str) -> Path | None:
    import mq_instruments as mi
    cands = sorted((mi.data_dir() / "training" / "datasets" / inst).glob("*/source_metadata.json"))
    for m in reversed(cands):
        if json.loads(m.read_text(encoding="utf-8")).get("data_kind") == "REAL_USER_DATA":
            return m.parent
    return None


def _dataset(a) -> Path | None:
    if a.dataset:
        return Path(a.dataset)
    return _latest_real(a.asset)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="masterquo indicator-context", description="Moduły IQ Gold Gann / IQ Star Lines / PAL02M / SAR")
    sub = ap.add_subparsers(dest="c", required=True)
    sub.add_parser("status")
    r = sub.add_parser("record")
    r.add_argument("--asset", choices=INSTR, default="XAUUSD")
    for n in ("dataset", "calibrate-sar", "train"):
        s = sub.add_parser(n)
        s.add_argument("--asset", choices=INSTR, default="XAUUSD")
        s.add_argument("--dataset", help="katalog eksportu treningowego (domyślnie najnowszy REAL_USER_DATA)")
        s.add_argument("--latest-real", action="store_true")
        s.add_argument("--commission", type=float)
        s.add_argument("--allow-synthetic-fixture", action="store_true", help="tylko testy: dane syntetyczne -> fixture_runs, nigdy aktywne")
        s.add_argument("--groups", nargs="*", default=None)
        s.add_argument("--out")
    e = sub.add_parser("evaluate")
    e.add_argument("--asset", choices=INSTR, default="XAUUSD")
    e.add_argument("--run", required=True)
    act = sub.add_parser("activate")
    act.add_argument("--asset", choices=INSTR, default="XAUUSD")
    act.add_argument("--run", required=True)
    act.add_argument("--variant", required=True)
    rb = sub.add_parser("rollback")
    rb.add_argument("--asset", choices=INSTR, default="XAUUSD")
    a = ap.parse_args(argv)
    from ..db.database import Database
    from . import trainer
    from .service import ExtIndService
    if a.c == "status":
        print(json.dumps(ExtIndService(None, Database()).status(), indent=1, ensure_ascii=False, default=str))
        return 0
    if a.c == "record":
        st = ExtIndService(None, Database()).status()
        print("Rejestracja działa w uruchomionym bocie (ExtIndService) – czyta pliki eksportera z:")
        for d in st["inbox_dirs"]:
            print("  " + d)
        for k, v in st["adapters"].items():
            print(f"  {k}: źródło {v['source_status']}, mapping {v['mapping_status']}, archiwum {v['archived_approved']} odczytów")
        return 0
    if a.c == "evaluate":
        p = trainer.root(a.asset) / "runs" / a.run / "report.json"
        if not p.exists():
            p = trainer.root(a.asset) / "fixture_runs" / a.run / "report.json"
        if not p.exists():
            print(f"[BLAD] brak raportu {a.run}")
            return 1
        print(p.read_text(encoding="utf-8"))           # saved report only - labels are not touched again
        return 0
    if a.c == "activate":
        try:
            print(trainer.activate(a.asset, a.run, a.variant))
            return 0
        except (ValueError, OSError, KeyError) as exc:
            print(f"[BLAD] {exc}")
            return 2
    if a.c == "rollback":
        print(trainer.rollback(a.asset))
        return 0
    ds = _dataset(a)
    if ds is None or not (ds / "source_metadata.json").exists():
        print("[BLAD] BLOCKED_NO_DATA: brak eksportu REAL_USER_DATA – uruchom trening (00_TRENING_START.bat) albo podaj --dataset")
        return 2
    kind = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8")).get("data_kind")
    if kind != "REAL_USER_DATA" and not a.allow_synthetic_fixture:
        print("[BLAD] dane syntetyczne nie są źródłem artefaktów produkcyjnych (--allow-synthetic-fixture tylko w testach)")
        return 2
    db = Database()
    try:
        if a.c == "dataset":
            d = trainer.build_dataset(a.asset, ds, a.commission, db)
            print(json.dumps({"cycles": len(d["rows"]), "dataset_id": d["dataset_id"], "costs": d["costs"],
                              "ext_coverage": {g: sum(1 for r in d["rows"] if r["ext"].get(g)) for g in ("IQ_GOLD_GANN", "IQ_STAR_LINES")}}, indent=1))
            return 0
        if a.c == "calibrate-sar":
            d = trainer.build_dataset(a.asset, ds, a.commission, db)
            res = trainer.calibrate_sar(d, trainer.split(d["rows"]))
            print(json.dumps(res, indent=1))
            return 0 if res["status"] == "OK" else 4
        rep = trainer.train(a.asset, ds, commission=a.commission, db=db)
    except ValueError as exc:
        print(f"[BLAD] {exc}")
        return 2
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"run_id": rep["run_id"], "status": rep["status"], "role": rep["role"],
                      "variants": {k: v["status"] for k, v in rep["variants"].items()}}, indent=1))
    return 0 if rep["status"] == "EVALUATED" else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
