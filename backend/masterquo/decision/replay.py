"""Replay OLD (1.32) vs NEW (1.33 PMW-ARC-1) decision logic (python -m masterquo.decision.replay).

1. Stored decisions (table `decisions`, main path) and SH signals (`sh_signals`): the old verdict is what 1.32 stored; the new verdict is
   what the coordinator gives for the SAME inputs and the configured model roles (models are replayed from `--preds` JSON when given,
   otherwise none: with no REQUIRED model and no ASSIST family the new verdict must equal the old one - any difference is reported).
2. Race scenario (deterministic): K entry requests of both paths inside one send window against max_open_positions = N.
   OLD = each path checks risk/portfolio.check() and sends on its own (check-then-act) -> all K pass when the book is empty;
   NEW = RiskBook.reserve() in one serialised transaction -> exactly N pass, the rest PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED.
Nothing here places an order or touches a terminal.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from . import contracts as K
from .coordinator import evaluate_models, final_verdict


def _old_active(rec: dict) -> str:
    return "ENTER" if rec.get("execution_permission") == "ALLOWED" else ("WAIT" if rec.get("decision") == "WAIT" else "NO_TRADE")


def replay_decisions(db, *, required: set[str] | None = None, preds: list[dict] | None = None, assist_threshold: float = 0.6,
                     max_age_s: float = 900.0, limit: int = 5000, now: float | None = None) -> dict:
    required = required or set()
    now = time.time() if now is None else now
    rows = db.query("SELECT decision_id, created_at, record_json FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,))
    out = {"active": {"n": 0, "old": {}, "new": {}, "changed": []}, "sh": {"n": 0, "old": {}, "new": {}, "changed": []}}
    for r in rows:
        try:
            d = json.loads(r["record_json"])
        except (TypeError, ValueError):
            continue
        old = _old_active(d)
        side = {"LONG": "BUY", "SHORT": "SELL"}.get(d.get("analysis_direction"), "NONE")
        _, mr = evaluate_models(preds or [], side, required=required, assist_threshold=assist_threshold, max_age_s=max_age_s, now=now) \
            if old == "ENTER" else ([], [])
        new = final_verdict(old, [], mr)
        _count(out["active"], old, new, r["decision_id"], mr)
    try:
        sigs = db.query("SELECT signal_id, strategy, side, status, payload FROM sh_signals ORDER BY created_at DESC LIMIT ?", (limit,))
    except Exception:  # noqa: BLE001 - database without the SH tables
        sigs = []
    for s in sigs:
        old = "ENTER" if s["status"] == "READY" else ("WAIT" if s["status"] == "WAIT" else "NO_TRADE")
        try:
            pl = json.loads(s["payload"] or "{}")
        except ValueError:
            pl = {}
        fc = [{"family": x.get("family"), "state": x.get("state"), "use": x.get("use"), "task_type": x.get("task_type"), "result": x.get("result")}
              for x in ((pl.get("family_context") or {}).get("context") or [])]
        _, mr = evaluate_models(preds if preds is not None else fc, s["side"] or "NONE", required=required, assist_threshold=assist_threshold,
                                max_age_s=max_age_s, now=now) if old == "ENTER" else ([], [])
        _count(out["sh"], old, final_verdict(old, [], mr), s["signal_id"], mr)
    return out


def _count(bucket, old, new, sid, reasons) -> None:
    bucket["n"] += 1
    bucket["old"][old] = bucket["old"].get(old, 0) + 1
    bucket["new"][new] = bucket["new"].get(new, 0) + 1
    if old != new and len(bucket["changed"]) < 200:
        bucket["changed"].append({"id": sid, "old": old, "new": new, "reasons": reasons})


def race_scenario(cap: int = 2, requests: int = 6, mode: str = "AUTO_DEMO", account: str = "DEMO:1") -> dict:
    """Both paths, `requests` entries inside one send window, max_open_positions = cap. Uses the real portfolio guard and RiskBook."""
    from ..config import AppConfig
    from ..db.database import Database
    from ..risk import portfolio as PF
    from .ledger import RiskBook
    cfg = AppConfig()
    cfg.risk.max_open_positions = cap
    store = SimpleNamespace(get=lambda: cfg)
    with tempfile.TemporaryDirectory() as td:
        db = Database(Path(td) / "replay.sqlite")
        # OLD: every request checks the guard before any of them has filled (the window between check and the fill)
        st = PF.state(db, mode, account, time.time())
        old_pass = sum(1 for _ in range(requests) if not PF.check(st, equity=10000.0, legacy_limits=cfg.risk, sh_limits={}))
        # NEW: one serialised reservation per request (alternating ACTIVE / SH)
        book = RiskBook(db, store, sh_limits=lambda: {})
        res = [book.reserve(path=("ACTIVE", "SH")[i % 2], subject=f"S{i}", mode=mode, account_key=account, risk_money=10.0, equity=10000.0)
               for i in range(requests)]
        new_pass = sum(1 for r in res if r["ok"])
        reasons = sorted({x for r in res for x in r["reasons"]})
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass
    return {"cap": cap, "requests": requests, "old_passed": old_pass, "new_passed": new_pass, "old_exceeds_cap": old_pass > cap,
            "new_exceeds_cap": new_pass > cap, "new_refusals": reasons}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replay starej (1.32) i nowej (1.33) logiki decyzji – bez zleceń")
    ap.add_argument("--db", help="masterquo.sqlite (kopia); bez --db tylko scenariusz wyścigu")
    ap.add_argument("--required", default="", help="rodziny w roli REQUIRED, np. ARIMA,GARCH")
    ap.add_argument("--preds", help="JSON z listą prognoz PMW-PRED-2 do odtworzenia (opcjonalnie)")
    ap.add_argument("--cap", type=int, default=2)
    ap.add_argument("--requests", type=int, default=6)
    ap.add_argument("--out", help="zapis raportu JSON")
    a = ap.parse_args(argv)
    rep = {"version": K.VERSION, "race": race_scenario(a.cap, a.requests)}
    if a.db:
        from ..db.database import Database
        preds = json.loads(Path(a.preds).read_text(encoding="utf-8")) if a.preds else None
        rep["decisions"] = replay_decisions(Database(Path(a.db)), required={x for x in a.required.split(",") if x}, preds=preds)
    txt = json.dumps(rep, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
