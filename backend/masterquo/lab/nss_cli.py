"""`python -m masterquo neural-scalp <cmd>` (23_NEURAL_SCALP.bat) - Neural Scalp System CAUSAL_MTF_TCN_V1 / SCALP_SETUP_MARKET_V1.
Exit: 0 ok, 1 error, 2 blocked, 4 insufficient evidence. Never activates a model, never sends orders."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INSTR = ("XAUUSD", "BTC")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="masterquo neural-scalp", description="Neural Scalp System: TCN M1/M5 + kontekst, P(TP1/SL/TIMEOUT) + net_R")
    sub = ap.add_subparsers(dest="c", required=True)
    for n in ("doctor", "status", "prepare", "train", "report", "rollback", "select"):
        s = sub.add_parser(n)
        s.add_argument("--asset", choices=INSTR, default="XAUUSD")
        if n in ("prepare", "train"):
            s.add_argument("--dataset", help="eksport treningowy (domyślnie najnowszy REAL_USER_DATA instrumentu)")
            s.add_argument("--manifest", default="latest")
            s.add_argument("--months", type=int, default=12, help="eksport wykonuje 00_TRENING_START.bat; tu informacyjnie")
            s.add_argument("--commission", type=float)
            s.add_argument("--activate", default="none", choices=("none",), help="nowy model nigdy nie jest wybierany automatycznie")
            s.add_argument("--allow-synthetic-fixture", action="store_true")
            s.add_argument("--members", help="seedy członków (domyślnie 17,29,43)")
            s.add_argument("--budget-minutes", type=int)
            s.add_argument("--out")
        if n == "report":
            s.add_argument("--latest", action="store_true")
            s.add_argument("--run")
        if n == "select":
            s.add_argument("--run", required=True)
            s.add_argument("--role", choices=("OBSERVE", "SHADOW_GATE"), required=True)
    a = ap.parse_args(argv)
    from ..db.database import Database
    from ..extind.cli import _latest_real
    from . import nss
    if a.c in ("doctor", "status"):
        ds = _latest_real(a.asset)
        out = {"task_id": nss.TASK_ID, "architecture_id": nss.sn.ARCH_ID, "instrument": a.asset, "latest_real_export": str(ds) if ds else None,
               "blocked": None if ds else "BLOCKED_NO_REAL_DATA – eksport historii przez 00_TRENING_START.bat (MT5)",
               "numpy": __import__("numpy").__version__, "torch_required": False}
        if ds:
            meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
            com = (meta.get("costs") or {}).get("commission_per_lot_side")
            out["costs"] = {"commission_per_lot_side": com, "source": (meta.get("costs") or {}).get("source") if com is not None else "BRAK – uzupełnij (konto Zero ≠ 0 kosztów)"}
            out["range"] = {k: meta.get(k) for k in ("range_from", "range_to", "trading_days") if k in meta}
        try:
            reg = json.loads((nss.root(a.asset) / "registry.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            reg = None
        out["registry"] = reg
        out["architecture"] = {k: v for k, v in nss.static_architecture().items() if k != "nodes" and k != "edges"}
        rows = Database().query("SELECT label_status, COUNT(*) AS n FROM nss_inferences WHERE instrument=? GROUP BY label_status", (a.asset,))
        out["live_inferences"] = {r["label_status"]: r["n"] for r in rows}
        print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
        return 0 if ds else 2
    if a.c == "report":
        p = nss.root(a.asset) / "registry.json"
        reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": {}}
        rid = a.run or (sorted(reg["runs"])[-1] if reg["runs"] else None)
        if not rid:
            print("[BLAD] brak runów NSS")
            return 2
        print((Path(reg["runs"][rid]["run_dir"]) / "report.json").read_text(encoding="utf-8"))
        return 0
    if a.c in ("rollback", "select"):
        try:
            print(nss.rollback(a.asset) if a.c == "rollback" else nss.select(a.asset, a.run, a.role))
            return 0
        except (ValueError, OSError, KeyError) as exc:
            print(f"[BLAD] {exc}")
            return 2
    ds = Path(a.dataset) if a.dataset else _latest_real(a.asset)
    if ds is None or not (ds / "source_metadata.json").exists():
        print("[BLAD] BLOCKED_NO_REAL_DATA: brak eksportu REAL_USER_DATA (00_TRENING_START.bat) – podaj --dataset")
        return 2
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    print(f"Manifest danych: {ds.name} ({meta.get('instrument')}, {meta.get('data_kind')}, {meta.get('dataset_id')})")
    if meta.get("data_kind") != "REAL_USER_DATA" and not a.allow_synthetic_fixture:
        print("[BLAD] dane syntetyczne nie są źródłem modelu użytkownika")
        return 2
    tcfg = {}
    if a.members:
        tcfg["members"] = [int(x) for x in a.members.split(",")]
    if a.budget_minutes:
        tcfg["budget_minutes"] = a.budget_minutes
    try:
        if a.c == "prepare":
            d = nss.build_dataset(a.asset, ds, a.commission)
            arr = d["arr"]
            per = {s: {"n": int((arr["side"] == i).sum()), "classes": [int(((arr["side"] == i) & (arr["y"] == k)).sum()) for k in range(3)]}
                   for i, s in enumerate(("BUY", "SELL"))}
            need = nss.CRITERIA["min_fit_tune_per_side"]
            print(json.dumps({"samples": len(d["rows"]), "per_side": per, "skipped": d["skipped"], "content_hash": d["content_hash"], "costs": d["costs"],
                              "precision": "OHLC_APPROX", "class_order": list(nss.sn.CLASSES),
                              "missing_for_minimum": {s: max(0, int(need / 0.75 / 0.8) - v["n"]) for s, v in per.items()}}, indent=1))
            return 0
        rep = nss.train(a.asset, ds, commission=a.commission, db=Database(), train_cfg=tcfg)
    except ValueError as exc:
        print(f"[BLAD] {exc}")
        return 2
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"run_id": rep["run_id"], "status": rep["status"], "role": rep["role"], "model_hash": rep.get("model_hash"),
                      "sides": {k: v.get("status") for k, v in rep["sides"].items()}, "reason": rep.get("reason")}, indent=1))
    return 0 if rep["status"] == "EVALUATED" else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
