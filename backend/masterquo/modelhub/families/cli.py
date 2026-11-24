"""python -m masterquo families <cmd>
  list      --instrument XAUUSD                      catalog with the three state axes
  train     --instrument XAUUSD --family TS_ARIMA [--profile smoke|research|full]   (separate process not needed: runs here)
  train-all --instrument XAUUSD [--profile smoke]    every runnable family; reports DONE / BLOCKED / DELEGATED separately
  activate  --instrument XAUUSD --family F --run R   integrity + inference-sample check, then use SHADOW
  use       --instrument XAUUSD --family F --use OFF|SHADOW|ASSIST
  rollback  --instrument XAUUSD --family F
At the role ASSIST activate / rollback accept only a target that passes the ASSIST gate (APPROVED, REAL data) - otherwise ASSIST_GATE
(set the role SHADOW first).
Exit codes: 0 ok, 2 bad arguments (unknown --family, activate without --run, use without a valid --use), 3 nothing trained /
blocked / refused."""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="masterquo families")
    ap.add_argument("cmd", choices=["list", "train", "train-all", "activate", "use", "rollback"])
    ap.add_argument("--instrument", required=True, type=str.upper, choices=["XAUUSD", "BTC"])
    ap.add_argument("--family")
    ap.add_argument("--profile", default="smoke", choices=["smoke", "research", "full"])
    ap.add_argument("--run")
    ap.add_argument("--use", type=str.upper)
    a = ap.parse_args(argv)
    from ...config import ConfigStore
    from . import registry
    from . import run as RUN
    from .service import FamilyService
    cfg = ConfigStore()
    svc = FamilyService(cfg)
    c = cfg.get().families
    from ...paths import data_dir
    # 1.46: the book archive as FamilyService._job_config passes it (IndicatorService default dir) - without it MICROSTRUCTURE from the CLI
    # always read 0 snapshots and reported "the collector is still running"
    jc = {"pairs": c.pairs, "basket": c.basket, "indicators_db": str(data_dir() / "indicators" / "indicators.sqlite"),
          "nlp_transformer_path": c.nlp_transformer_path}
    if a.cmd == "list":
        for it in svc.catalog(a.instrument):
            st = it["status"]
            print(f"{it['id']:16s} {it['kind']:18s} impl={st['implementation']:18s} artifact={st['artifact']:18s} use={st['use']}")
        return 0
    if a.cmd == "train":
        if a.family not in registry():
            print("--family wymagane: " + ", ".join(registry()), file=sys.stderr)
            return 2
        r = RUN.train(a.family, a.instrument, a.profile, jc)
        print(json.dumps({k: v for k, v in r.items() if k != "trace"}, ensure_ascii=False, indent=1))
        return 0 if r["state"] in ("DONE", "DELEGATED") else 3
    if a.cmd == "train-all":
        out = {}
        for fid in registry():
            if fid == "SEQ_GRU_EVENT":
                out[fid] = {"state": "DELEGATED", "reason": "Centrum MM"}
                continue
            r = RUN.train(fid, a.instrument, a.profile, jc)
            out[fid] = {k: v for k, v in r.items() if k in ("state", "reason", "run_id", "validation")}
            print(f"{fid:16s} {out[fid]['state']:10s} {out[fid].get('validation') or out[fid].get('reason') or ''}", flush=True)
        done = sum(1 for v in out.values() if v["state"] == "DONE")
        print(json.dumps({"done": done, "blocked": [k for k, v in out.items() if v["state"] == "BLOCKED"],
                          "failed": [k for k, v in out.items() if v["state"] == "FAILED"]}, ensure_ascii=False))
        return 0 if done else 3
    from . import base as B
    # bad arguments -> 2 before anything runs (activate without --run ended in a TypeError traceback, use without / with a wrong --use
    # in REFUSED USE_INVALID:None with 3)
    if a.family not in registry():
        print("FAMILY_UNKNOWN – --family wymagane: " + ", ".join(registry()), file=sys.stderr)
        return 2
    if a.cmd == "activate" and not a.run:
        print("--run wymagane (identyfikator artefaktu rodziny)", file=sys.stderr)
        return 2
    if a.cmd == "use" and a.use not in B.USE:
        print(f"--use wymagane: {'|'.join(B.USE)} (podano {a.use})", file=sys.stderr)
        return 2
    try:
        if a.cmd == "activate":
            r = svc.activate(a.family, a.instrument, a.run)
        elif a.cmd == "use":
            r = svc.set_use(a.family, a.instrument, a.use)
        else:
            r = svc.rollback(a.family, a.instrument)
    except KeyError as exc:
        code = str(exc.args[0]) if exc.args else ""
        if code not in ("FAMILY_UNKNOWN", "FAMILY_OR_INSTRUMENT_INVALID"):
            raise                                                # an internal KeyError is a bug, not "unknown family"
        print(code + " – --family wymagane: " + ", ".join(registry()), file=sys.stderr)
        return 2
    except ValueError as exc:
        # 1.46 D5: a refusal (ASSIST gate on activate / rollback, set_use) is an answer, not a traceback
        r = {"ok": False, "status": "ASSIST_GATE" if isinstance(exc, B.AssistGate) else "REFUSED", "reason": str(exc)}
    print(json.dumps(r, ensure_ascii=False, default=str, indent=1))
    return 0 if r.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
