"""`python -m masterquo montecarlo <cmd>` - validation of the Monte Carlo variants on an export, rollback of the calibration.

  validate --dataset DIR [--horizon 60] [--stride 30] [--n-paths 500] [--max-points 600] [--out report.json]
  rollback --instrument XAUUSD
  status   --instrument XAUUSD
Nothing here connects to MT5 or sends orders; it reads the exported files only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str]) -> int:
    from . import validate as V
    ap = argparse.ArgumentParser(prog="masterquo montecarlo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--dataset", required=True)
    v.add_argument("--horizon", type=int, default=60)
    v.add_argument("--stride", type=int, default=30)
    v.add_argument("--window", type=int, default=3000)
    v.add_argument("--n-paths", type=int, default=500)
    v.add_argument("--max-points", type=int, default=600)
    v.add_argument("--out")
    for n in ("rollback", "status"):
        s = sub.add_parser(n)
        s.add_argument("--instrument", default="XAUUSD")
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        try:
            rep = V.validate(Path(a.dataset), horizon=a.horizon, stride=a.stride, window=a.window, n_paths=a.n_paths, max_points=a.max_points,
                             log=lambda m: print(m, flush=True))
        except (ValueError, FileNotFoundError) as exc:
            print(f"[BLAD] {exc}")
            return 2
        saved = V.save(rep.get("instrument") or "XAUUSD", rep)
        rep["saved"] = saved
        if a.out:
            V._write(Path(a.out), rep)
        print(f"[OK] Monte Carlo: {rep['status']} {rep.get('reason') or ''} wariant {rep.get('chosen_variant')} werdykt {rep.get('verdict')} "
              f"(run {saved['run_id']}, aktywny: {saved['activated']})")
        if rep.get("status") == "DONE":
            t = rep["test"]
            print(f"     TEST n={t['n']} Brier skalibrowany {t['calibrated']['brier']:.4f} vs bazowy {t['base']['brier']:.4f}, "
                  f"95% CI różnicy {rep['brier_diff_calibrated_minus_base_ci95']}, niejednoznaczne {t['ambiguous_share']:.1%}")
        return 0 if rep.get("status") in ("DONE", "INSUFFICIENT_DATA") else 1
    if a.cmd == "rollback":
        print(json.dumps(V.rollback(a.instrument), ensure_ascii=False))
        return 0
    print(json.dumps({"active": V.active_calibrator(a.instrument)}, ensure_ascii=False, default=str))
    return 0
