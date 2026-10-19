"""`python -m masterquo ml-scalp <cmd>` (24_SCALP_ML.bat) for SCALP_NET_PROFIT_MARKET_V1. Exit: 0 ok, 1 error, 2 blocked, 4 insufficient."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INSTR = ("XAUUSD", "BTC")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="masterquo ml-scalp", description="Scalp ML: P(dodatni wynik netto cyklu) + net_R (XGBoost, LONG/SHORT)")
    sub = ap.add_subparsers(dest="c", required=True)
    for n in ("doctor", "status", "prepare", "train", "report", "rollback", "select"):
        s = sub.add_parser(n)
        s.add_argument("--asset", choices=INSTR, default="XAUUSD")
        if n in ("prepare", "train"):
            s.add_argument("--dataset", help="eksport treningowy (domyślnie najnowszy REAL_USER_DATA)")
            s.add_argument("--manifest", default="latest")
            s.add_argument("--commission", type=float)
            s.add_argument("--activate", default="none", choices=("none",), help="nowy model nigdy nie jest aktywowany automatycznie")
            s.add_argument("--allow-synthetic-fixture", action="store_true")
            s.add_argument("--out")
            s.add_argument("--months", type=int, help="(eksport wykonuje 00_TRENING_START.bat; tu informacyjnie)")
        if n == "report":
            s.add_argument("--latest", action="store_true")
            s.add_argument("--run")
        if n in ("rollback", "select"):
            s.add_argument("--side", choices=("BUY", "SELL"), required=True)
        if n == "select":
            s.add_argument("--run", required=True)
            s.add_argument("--role", choices=("OBSERVE", "SHADOW_GATE"), required=True)
    a = ap.parse_args(argv)
    from ..db.database import Database
    from ..extind.cli import _latest_real
    from . import scalp_task as stk
    from .router import ml_store
    if a.c in ("doctor", "status"):
        db, _ = ml_store(a.asset)
        ds = _latest_real(a.asset)
        out = {"task_id": stk.TASK_ID, "instrument": a.asset, "latest_real_export": str(ds) if ds else None,
               "blocked": None if ds else "BLOCKED_NO_REAL_DATA – eksport historii przez 00_TRENING_START.bat (MT5)"}
        try:
            import xgboost
            out["xgboost"] = xgboost.__version__
        except ImportError:
            out["xgboost"] = "BRAK"
        out["live_samples"] = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) AS n FROM ml_scalp_samples WHERE instrument=? GROUP BY status", (a.asset,))}
        p = stk.root(a.asset) / "registry.json"
        out["registry"] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
        return 0 if ds else 2
    if a.c == "report":
        p = stk.root(a.asset) / "registry.json"
        reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": {}}
        rid = a.run or (sorted(reg["runs"])[-1] if reg["runs"] else None)
        if not rid:
            print("[BLAD] brak runów")
            return 2
        print((Path(reg["runs"][rid]["run_dir"]) / "report.json").read_text(encoding="utf-8"))
        return 0
    if a.c == "rollback":
        try:
            print(stk.rollback(a.asset, a.side))
            return 0
        except (ValueError, OSError) as exc:
            print(f"[BLAD] {exc}")
            return 2
    if a.c == "select":
        try:
            print(stk.select(a.asset, a.run, a.side, a.role))
            return 0
        except (ValueError, OSError, KeyError) as exc:
            print(f"[BLAD] {exc}")
            return 2
    ds = Path(a.dataset) if a.dataset else _latest_real(a.asset)
    if ds is None or not (ds / "source_metadata.json").exists():
        print("[BLAD] BLOCKED_NO_REAL_DATA: brak eksportu REAL_USER_DATA (00_TRENING_START.bat) – podaj --dataset")
        return 2
    print(f"Manifest danych: {ds.name}")
    if json.loads((ds / "source_metadata.json").read_text(encoding="utf-8")).get("data_kind") != "REAL_USER_DATA" and not a.allow_synthetic_fixture:
        print("[BLAD] dane syntetyczne nie są źródłem modelu użytkownika")
        return 2
    try:
        if a.c == "prepare":
            d = stk.build_dataset(a.asset, ds, a.commission)
            sides = {s: sum(1 for r in d["rows"] if r["side"] == s) for s in ("BUY", "SELL")}
            print(json.dumps({"candidates": len(d["rows"]), "per_side": sides, "blocked_by_strategy": d["blocked"], "costs": d["costs"],
                              "precision": d["precision"]}, indent=1))
            return 0
        rep = stk.train(a.asset, ds, commission=a.commission, db=Database())     # eval_ledger: one shared ledger (main database) for every task
    except ValueError as exc:
        print(f"[BLAD] {exc}")
        return 2
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"run_id": rep["run_id"], "status": rep["status"], "role": rep["role"],
                      "sides": {k: v.get("status") for k, v in rep["sides"].items()}}, indent=1))
    return 0 if rep["status"] == "EVALUATED" else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
