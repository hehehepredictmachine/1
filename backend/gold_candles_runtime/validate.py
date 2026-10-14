"""Re-validation of a saved run (default: the active one): artifact checksum, contract hash against the CURRENT code,
reference loader, runtime inference on the holdout of the same dataset, and the quality table per horizon."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import RunLog, activatable, read_registry, sha256_file, write_json_atomic


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Walidacja zapisanych modeli prognoz XAUUSD.")
    ap.add_argument("--run-id")
    args = ap.parse_args(argv)
    reg = read_registry()
    rid = args.run_id or reg.get("active") or (sorted(reg["runs"])[-1] if reg["runs"] else None)
    if not rid:
        print("[BLAD] BLOCKED_NO_REAL_DATA: w rejestrze nie ma żadnego runu – najpierw eksport i trening.")
        return 3
    e = reg["runs"][rid]
    from gold_candles.data import Config
    from gold_candles.model import load_model
    from .plan_train import load_dataset, runtime_check
    out = Path(e["validation_path"]).parent
    log = RunLog(out / "validate_log.jsonl")
    cur = Config(symbol=e["symbol"], tick_size=e["tick_size"]).contract_hash()
    ok, why = activatable(e, cur)
    res = {"run_id": rid, "checksum_ok": sha256_file(Path(e["model_path"])) == e["artifact_sha256"], "contract_hash_matches_current_code": e["contract_hash"] == cur,
           "activatable": ok, "not_activatable_reason": why, "overall_status": e.get("overall_status"), "horizon_status": e.get("horizon_status")}
    load_model(e["model_path"])
    if e.get("data_dir") and Path(e["data_dir"]).exists() and len(e.get("horizons_trained") or []) == 3:
        m5, m30, config, *_ = load_dataset(Path(e["data_dir"]), e["data_kind"])
        plan = json.loads((out / "TRAINING_PLAN.json").read_text(encoding="utf-8"))
        res["runtime_check"] = runtime_check(Path(e["model_path"]), m5, m30, config, plan, log)
    val = json.loads(Path(e["validation_path"]).read_text(encoding="utf-8"))
    print(f"Run {rid}: {e.get('overall_status')} · kontrakt {'zgodny' if res['contract_hash_matches_current_code'] else 'NIEZGODNY'} · checksum {'OK' if res['checksum_ok'] else 'BŁĄD'}")
    print(f"{'h':>4} {'status':<20} {'Brier':>8} {'base':>8} {'bez form.':>9} {'logloss':>8} {'base':>8} {'maxECE':>7} {'q10-q90':>8} {'dni':>4}")
    for hm, r in (val.get("horizons") or {}).items():
        if "calibrated" not in r:
            print(f"{hm:>4} {r.get('status', '?'):<20} {'; '.join(r.get('reasons', []))}")
            continue
        c, b, n = r["calibrated"], r["baseline"], r["no_pattern_model"]
        print(f"{hm:>4} {r['status']:<20} {c['brier_multiclass_sum']:8.4f} {b['brier_multiclass_sum']:8.4f} {n['brier_multiclass_sum']:9.4f} "
              f"{c['log_loss']:8.4f} {b['log_loss']:8.4f} {max(c['per_class_ece'].values()):7.3f} {r['quantiles']['central_80pct_empirical_coverage']:8.3f} {r['holdout_days']:4d}")
    write_json_atomic(out / "revalidation.json", res)
    return 0 if res["checksum_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
