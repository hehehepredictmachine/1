"""python -m masterquo families <cmd>
  list      --instrument XAUUSD                      catalog with the three state axes
  train     --instrument XAUUSD --family TS_ARIMA [--profile smoke|research|full]   (separate process not needed: runs here)
  train-all --instrument XAUUSD [--profile smoke]    every runnable family; reports DONE / BLOCKED / DELEGATED separately
  activate  --instrument XAUUSD --family F --run R   integrity + inference-sample check, then use SHADOW
  use       --instrument XAUUSD --family F --use OFF|SHADOW|ASSIST
  rollback  --instrument XAUUSD --family F
Exit codes: 0 ok, 2 bad arguments, 3 nothing trained / blocked."""
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
    jc = {"pairs": c.pairs, "basket": c.basket, "nlp_transformer_path": c.nlp_transformer_path}
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
    if a.cmd == "activate":
        r = svc.activate(a.family, a.instrument, a.run)
    elif a.cmd == "use":
        r = svc.set_use(a.family, a.instrument, a.use)
    else:
        r = svc.rollback(a.family, a.instrument)
    print(json.dumps(r, ensure_ascii=False, default=str, indent=1))
    return 0 if r.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())
