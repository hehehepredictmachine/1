"""Model registry (table ml_models + files in data/ml/models/<model_id>/): champion / challenger, promotion, rollback.

* Promotion rules are taken from config BEFORE the evaluation and stored with the result.
* A weaker challenger never replaces a better champion; complexity is not a criterion.
* The swap is atomic: the new bundle (model + preprocessor + calibrator) is fully loaded first, then one DB
  transaction moves the CHAMPION status; the in-memory pointer is replaced under a lock.
* Rollback restores the previous champion bundle as a whole (including its preprocessing and calibrator).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from ..db.database import dumps
from ..timeutil import iso, utcnow
from .models import Bundle


class Registry:
    def __init__(self, db, root: Path):
        self.db = db
        self.root = root
        self._lock = threading.RLock()
        self.champion: Bundle | None = None
        self.champion_id: str | None = None
        self.challengers: dict[str, Bundle] = {}
        self.load_error: str | None = None
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self.champion, self.champion_id, self.load_error = None, None, None
            row = self.db.one("SELECT * FROM ml_models WHERE status='CHAMPION' ORDER BY promoted_at DESC LIMIT 1")
            if row:
                try:
                    self.champion, self.champion_id = Bundle.load(Path(row["path"])), row["model_id"]
                except Exception as exc:  # corrupt files -> explicit fallback, no fake model
                    self.load_error = f"CHAMPION_LOAD_FAILED:{type(exc).__name__}"
            self.challengers = {}
            for r in self.db.query("SELECT * FROM ml_models WHERE status='CHALLENGER' ORDER BY created_at DESC LIMIT 2"):
                try:
                    self.challengers[r["model_id"]] = Bundle.load(Path(r["path"]))
                except Exception:
                    pass

    def models(self, limit: int = 30) -> list[dict]:
        out = []
        for r in self.db.query("SELECT * FROM ml_models ORDER BY created_at DESC LIMIT ?", (limit,)):
            m = json.loads(r["metrics_json"])
            out.append({k: r[k] for k in ("model_id", "family", "version", "status", "created_at", "snapshot_id", "feature_schema_version", "promoted_at", "retired_at")}
                       | {"test": {k: m.get("test", {}).get(k) for k in ("n", "pos", "neg", "brier", "log_loss", "pr_auc", "ece")}, "policy": m.get("policy"),
                          "threshold": m.get("threshold"), "calibration": m.get("calibration"), "promotion": json.loads(r["promotion_json"] or "null")})
        return out

    def events(self, limit: int = 30) -> list[dict]:
        return self.db.query("SELECT * FROM ml_events ORDER BY id DESC LIMIT ?", (limit,))

    def last_test_end(self) -> str | None:
        r = self.db.query("SELECT metrics_json FROM ml_models ORDER BY created_at DESC LIMIT 20")
        ends = [json.loads(x["metrics_json"]).get("test_window", [None, None])[1] for x in r]
        ends = [e for e in ends if e]
        return max(ends) if ends else None

    # ------------------------------------------------------------ register + promote
    def register(self, result: dict, snapshot_id: str, promotion_cfg: dict) -> dict:
        decisions = {}
        version = (self.db.one("SELECT MAX(version) AS v FROM ml_models") or {}).get("v") or 0
        cand = []
        for fam, m in result["models"].items():
            version += 1
            ok, why = self._rules(m, result, promotion_cfg)
            metrics = {k: m[k] for k in ("train", "threshold", "calibration", "test", "policy", "policy_bootstrap", "by_strategy", "by_direction",
                                          "by_session", "by_regime", "raw_test_brier")}
            metrics["test_window"] = result["validation"]["windows"]["test"]
            metrics["baselines"] = result["baselines"]
            self.db.execute("""INSERT INTO ml_models(model_id, family, version, status, created_at, snapshot_id, feature_schema_version, path, metrics_json, promotion_json)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (m["model_id"], fam, version, "CANDIDATE", iso(utcnow()), snapshot_id, result["feature_schema_version"], m["path"], dumps(metrics),
                             dumps({"passed": ok, "reasons": why, "rules": promotion_cfg})))
            decisions[m["model_id"]] = {"family": fam, "passed": ok, "reasons": why}
            if ok:
                cand.append((m["test"]["brier"], m["model_id"]))
        # champion comparison on the SAME new test block
        best = min(cand) if cand else None
        if best and self.champion is not None and promotion_cfg.get("must_beat_champion_brier", True):
            champ_brier = self._champion_brier_on(result)
            if champ_brier is not None and best[0] >= champ_brier:
                decisions[best[1]]["passed"] = False
                decisions[best[1]]["reasons"].append(f"NOT_BETTER_THAN_CHAMPION_BRIER_{champ_brier:.4f}")
                best = None
        for mid, d in decisions.items():
            status = "REJECTED" if not d["passed"] else ("CHALLENGER" if not best or mid != best[1] else "CANDIDATE")
            self.db.execute("UPDATE ml_models SET status=?, promotion_json=? WHERE model_id=?",
                            (status, dumps({"passed": d["passed"], "reasons": d["reasons"], "rules": promotion_cfg}), mid))
            self.event("REJECT" if status == "REJECTED" else "EVALUATED", mid, d)
        if best:
            self.promote(best[1], "PASSED_RULES_AND_BEAT_CHAMPION" if self.champion else "PASSED_RULES_FIRST_CHAMPION")
        self.reload()
        return decisions

    def _champion_brier_on(self, result: dict) -> float | None:
        if self.champion is None:
            return None
        try:
            from .dataset import load_snapshot
            from . import features as fe
            rows = load_snapshot(result["snapshot"])
            w = result["validation"]["windows"]["test"]
            test = [r for r in rows if w and w[0] <= r["asof_utc"] <= w[1]]
            if not test:
                return None
            f = [fe.from_json(json.loads(r["features_json"])) for r in test]
            raw = self.champion.raw(f)
            p = self.champion.calib.apply(raw)
            p = raw if p is None else p
            y = np.array([r["label"] for r in test])
            return float(np.mean((p - y) ** 2))
        except Exception:
            return None

    @staticmethod
    def _rules(m: dict, result: dict, rules: dict) -> tuple[bool, list[str]]:
        why = []
        t = m["test"]
        if t["n"] < rules["min_test_samples"]:
            why.append(f"TEST_SAMPLES_{t['n']}<{rules['min_test_samples']}")
        if min(t["pos"], t["neg"]) < rules["min_test_per_class"]:
            why.append(f"TEST_CLASS_COUNT_POS{t['pos']}_NEG{t['neg']}")
        base = result["baselines"]["base_rate"]["brier"]
        if t["brier"] - base > rules["max_brier_vs_baseline"]:
            why.append(f"BRIER_{t['brier']}_NOT_BETTER_THAN_BASE_RATE_{base}")
        if m["calibration"] == "NONE":
            why.append("NOT_CALIBRATED")
        if isinstance(t.get("ece"), (int, float)) and t["ece"] > rules["max_calibration_error"]:
            why.append(f"ECE_{t['ece']}>{rules['max_calibration_error']}")
        nm = result["baselines"]["no_ml_policy"]
        pol = m["policy"]
        if isinstance(pol.get("avg_r"), (int, float)) and isinstance(nm.get("avg_r"), (int, float)):
            if pol["avg_r"] - nm["avg_r"] < rules["min_net_r_vs_no_ml"]:
                why.append(f"AVG_R_{pol['avg_r']}_VS_NO_ML_{nm['avg_r']}")
            if pol["max_dd_r"] - nm["max_dd_r"] > rules["max_drawdown_increase_r"]:
                why.append(f"DRAWDOWN_INCREASE_{pol['max_dd_r']}_VS_{nm['max_dd_r']}")
        else:
            why.append("POLICY_NOT_EVALUABLE")
        return not why, why

    def promote(self, model_id: str, reason: str) -> None:
        row = self.db.one("SELECT * FROM ml_models WHERE model_id=?", (model_id,))
        bundle = Bundle.load(Path(row["path"]))              # load fully BEFORE switching
        now = iso(utcnow())
        with self.db.tx() as c:
            c.execute("UPDATE ml_models SET status='RETIRED', retired_at=? WHERE status='CHAMPION'", (now,))
            c.execute("UPDATE ml_models SET status='CHAMPION', promoted_at=? WHERE model_id=?", (now, model_id))
        with self._lock:
            self.champion, self.champion_id = bundle, model_id
        self.event("PROMOTE", model_id, {"reason": reason})

    def rollback(self) -> dict:
        cur = self.db.one("SELECT * FROM ml_models WHERE status='CHAMPION'")
        prev = self.db.one("SELECT * FROM ml_models WHERE status='RETIRED' AND promoted_at IS NOT NULL ORDER BY retired_at DESC LIMIT 1")
        if not prev:
            raise ValueError("NO_PREVIOUS_CHAMPION")
        bundle = Bundle.load(Path(prev["path"]))
        now = iso(utcnow())
        with self.db.tx() as c:
            if cur:
                c.execute("UPDATE ml_models SET status='ROLLED_BACK', retired_at=? WHERE model_id=?", (now, cur["model_id"]))
            c.execute("UPDATE ml_models SET status='CHAMPION', promoted_at=?, retired_at=NULL WHERE model_id=?", (now, prev["model_id"]))
        with self._lock:
            self.champion, self.champion_id = bundle, prev["model_id"]
        self.event("ROLLBACK", prev["model_id"], {"from": cur["model_id"] if cur else None})
        return {"champion": prev["model_id"], "previous": cur["model_id"] if cur else None}

    def event(self, kind: str, model_id: str | None, detail: dict) -> None:
        self.db.execute("INSERT INTO ml_events(at, kind, model_id, detail_json) VALUES (?,?,?,?)", (iso(utcnow()), kind, model_id, dumps(detail)))
