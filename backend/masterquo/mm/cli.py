"""`python -m masterquo mm ...` - master models CLI (SHADOW / OBSERVE; no command here can send, modify or close an order).

  mm inventory --instrument XAUUSD [--json]          module inventory with evidence-based statuses (latest run merged)
  mm train --dataset DIR --instrument XAUUSD --out DIR [--profile quick|standard] [--only a,b] [--cancel-file F]
  mm status --instrument XAUUSD                      latest run summary + artifacts + SHADOW pointer
  mm buzoa-bench [--budget N]                        BUZOA vs PSO/DE/Random on the benchmark functions
  mm mathbench-export --out DIR                      float64 MLP weights / vectors / float32 ONNX + Python checks (copy to MQL5\\Files\\PMW_MathFidelity)
  mm export-fixtures --out DIR [--parity NATIVE]     frozen inputs + Python reference outputs for the MQL5 self-test (Kalman/GPR/HDC/breakout);
                                                     with --parity compares PMW_MM_NATIVE.txt written by PMW_MM_SelfTest.mq5
  mm rollback --instrument XAUUSD --model MODEL_ID   previous SHADOW artifact back (pointer only)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INSTR = ("XAUUSD", "BTC")      # instrument ids of the allowlist (never an MT5 broker symbol); always explicit, no default


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="masterquo mm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inventory")
    i.add_argument("--instrument", choices=INSTR, required=True)
    i.add_argument("--json", action="store_true")
    t = sub.add_parser("train")
    t.add_argument("--dataset", required=True)
    t.add_argument("--instrument", choices=INSTR, required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--profile", default="standard", choices=["quick", "standard"])
    t.add_argument("--only", default="")
    t.add_argument("--seed", type=int, default=20261025)
    t.add_argument("--cancel-file")
    s = sub.add_parser("status")
    s.add_argument("--instrument", choices=INSTR, required=True)
    b = sub.add_parser("buzoa-bench")
    b.add_argument("--budget", type=int, default=2000)
    m = sub.add_parser("mathbench-export")
    m.add_argument("--out", required=True)
    f = sub.add_parser("export-fixtures")
    f.add_argument("--out", required=True)
    f.add_argument("--parity", default="")
    r = sub.add_parser("rollback")
    r.add_argument("--instrument", choices=INSTR, required=True)
    r.add_argument("--model", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "inventory":
        from . import inventory
        rows = inventory.merge_run(inventory.latest_report(a.instrument))
        if a.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False, default=str))
        else:
            for x in rows:
                print(f"{x['n']:>2} {x['id']:<16} {x['category']:<24} {x['status']:<20} {x.get('blocked') or ''}")
        return 0
    if a.cmd == "train":
        from . import orchestrator
        rep = orchestrator.run(a.dataset, a.instrument, a.out, a.profile, [x for x in a.only.split(",") if x] or None, a.seed, a.cancel_file)
        print(json.dumps({"run_id": rep.get("run_id"), "status": rep.get("status"), "jobs": {k: v["status"] for k, v in (rep.get("jobs") or {}).items()}},
                         ensure_ascii=False))
        return 0 if rep.get("status") == "FINISHED" else 1
    if a.cmd == "status":
        from . import artifacts, inventory
        print(json.dumps({"latest_run": inventory.latest_report(a.instrument), "shadow_pointer": artifacts.read_pointer(a.instrument),
                          "artifacts": artifacts.list_artifacts(a.instrument)}, indent=1, ensure_ascii=False, default=str))
        return 0
    if a.cmd == "buzoa-bench":
        from . import buzoa
        print(json.dumps(buzoa.benchmark(budget=a.budget), indent=1))
        return 0
    if a.cmd == "mathbench-export":
        from . import mathbench
        man = mathbench.export(Path(a.out))
        print(json.dumps({"manifest": man["files_sha256"], "checks": mathbench.python_checks(Path(a.out))}, indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "export-fixtures":
        from . import fixtures
        if a.parity:
            if not (Path(a.out) / "mm_ref_kalman.csv").exists():
                fixtures.export(Path(a.out))
            res = fixtures.parity(Path(a.parity), Path(a.out))
            print(json.dumps(res, indent=1))
            return 0 if res["status"] in ("NATIVE_PARITY_PASS", "NATIVE_NOT_EXECUTED") else 1
        print(json.dumps(fixtures.export(Path(a.out)), indent=1))
        return 0
    if a.cmd == "rollback":
        from . import artifacts
        print(json.dumps(artifacts.rollback(a.instrument, a.model), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
