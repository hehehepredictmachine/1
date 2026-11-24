"""Training Center components of 1.41 (dispatch by component kind - the loader never forces model.joblib / proba3 on these):

  TH_SDFORMERFLOW  TRAINABLE_SEQUENCE_MODEL  real checkpoint (last.pt) - prepare_dataset / from_scratch / fine_tune / resume / cancel /
                                             import / export / activate / rollback
  ETC_LOG_CHANNEL  FEATURE_TRANSFORM         versioned transform configuration (no weights) - prepare_features / optimize_parameters
                                             (OPTIMIZE job: COA -> BChimp ports on a frozen objective) / import / export / activate / rollback

Activation policy DIRECT_USER_REQUEST: a finished job is registered, technically checked (load + finite output) and activated
atomically by the supervisor callback - never when cancelled, never over a newer user decision. Job results report computation,
artifact and activation separately. Metrics that were not run are null with status NOT_RUN (no efficacy claim).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import etc as ETC
from . import optim as OP
from .sources import SOURCES

COMPONENTS = {
    "TH_SDFORMERFLOW": {"module_id": "sdformerflow", "kind": "TRAINABLE_SEQUENCE_MODEL", "implementation_id": SOURCES["sdformerflow"]["implementation_id"],
                        "runtime_backend": "torch 2.14.1 CPU (subprocess, 2 wątki)", "artifact": "REAL_CHECKPOINT", "raw_output_not_calibrated": True,
                        "operations": ["prepare_dataset", "train_from_scratch", "fine_tune", "resume", "cancel", "import", "export", "activate", "rollback"],
                        "target_id": "STFS_NEXT24_DESCRIPTORS", "horizon": "24 x H1"},
    "ETC_LOG_CHANNEL": {"module_id": "exponential_trend_channel", "kind": "FEATURE_TRANSFORM", "implementation_id": SOURCES["exponential_trend_channel"]["implementation_id"],
                        "runtime_backend": "python (as-of, przyczynowe)", "artifact": "VERSIONED_TRANSFORM_CONFIGURATION", "weights_required": False,
                        "fit_quality_is_probability": False,
                        "operations": ["prepare_features", "optimize_parameters", "cancel", "import", "export", "activate", "rollback"],
                        "target_id": "CHANNEL_CONTAINMENT_H10 (|udział zamknięć +10 świec w kanale − 0.90|)", "horizon": "10 x M5"},
}
PRICE_IDX = list(ETC.PRICES)
WS_IDX = ["SHORT", "LONG"]
ETC_TARGET_COVERAGE = 0.90
# 1.46: import limits AFTER decompression (the endpoint only limits the compressed upload to 200 MB - a ZIP bomb unpacked to many GB
# in the bot's process); declared sizes are checked before anything is read and every read is capped while streaming
MAX_IMPORT_UNPACKED = 1024 * 1024 * 1024
MAX_IMPORT_JSON = 8 * 1024 * 1024
RUN_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Components:
    """Owned by ResearchModulesService (svc): uses its settings, contexts, SDformerFlow runner and governor."""

    def __init__(self, svc):
        self.svc = svc
        self.jobs: dict[str, dict] = {}
        self._cancel = threading.Event()
        self._lock = threading.RLock()        # 1.46: ETC job start (check + registration) and etc_versions.json read-modify-write

    # ------------------------------------------------------------------ ETC versions
    def _etc_file(self) -> Path:
        return self.svc.base / "etc_versions.json"

    def etc_versions(self) -> list[dict]:
        v = self.svc._read(self._etc_file(), [])
        if not any(x["version"] == "ETC-INITIAL" for x in v):
            p = {k: ETC.DEFAULT[k] for k in ("price", "window_set", "width")}
            v.insert(0, {"version": "ETC-INITIAL", "params": p, "schema_hash": ETC.schema_hash(p), "params_hash": ETC.params_hash(p), "created_at": None,
                         "source": "konfiguracja bazowa źródła (działa przed pierwszą optymalizacją)"})
        return v

    def _save_etc(self, v: list[dict]) -> None:
        from .service import _atomic
        _atomic(self._etc_file(), v[-100:])

    def _add_etc_version(self, entry: dict, replace: str | None = None) -> None:
        with self._lock:                                  # 1.46: one writer at a time (optimisation thread vs import from the API)
            vs = [x for x in self.etc_versions() if replace is None or x["version"] != replace]
            vs.append(entry)
            self._save_etc(vs)

    def etc_activate(self, version: str, who: str = "panel") -> dict:
        vs = {x["version"]: x for x in self.etc_versions()}
        if version not in vs:
            return {"ok": False, "reason": "nieznana wersja"}
        p = vs[version]["params"]
        cur = self.svc.settings()["etc"]
        try:
            self.svc.update_settings({"etc": {**p, "param_version": version, "previous_version": cur.get("param_version")}}, who=who)
        except ValueError as exc:                         # 1.46: e.g. a version imported by 1.45 with a non-numeric width - 409, not 500
            return {"ok": False, "reason": f"parametry wersji odrzucone: {exc}"}
        return {"ok": True, "active": version, "previous": cur.get("param_version"), "note": "nowe parametry obowiązują od następnej generacji snapshotu"}

    def etc_rollback(self) -> dict:
        prev = self.svc.settings()["etc"].get("previous_version")
        if not prev:
            return {"ok": False, "reason": "brak poprzedniej wersji"}
        return self.etc_activate(prev, who="rollback")

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        s = self.svc.settings()
        sd = self.svc._sdf_dir()
        runs = []
        for d in sorted(p for p in sd.iterdir() if p.is_dir()):
            meta = self.svc._read(d / "sdformer_run.json", {})
            if not isinstance(meta, dict):                # 1.46: a 1.45 import could store any JSON ("[]" -> AttributeError -> 500 for good)
                meta = {}
            runs.append({"version": d.name, "has_checkpoint": (d / "last.pt").exists(), "epochs_done": meta.get("epochs_done"), "steps": meta.get("steps"),
                         "dataset_hash": meta.get("dataset_hash"), "samples": meta.get("samples"), "history": meta.get("history"), "ok": meta.get("ok"),
                         "code": meta.get("code")})
        c = self.svc.ensure_main_context()
        ctxkey = c.key if c else None
        sdf_state = ((c.sdf or {}) if c else {})
        return {
            "activation_policy": "DIRECT_USER_REQUEST", "profile": "direct_train", "one_heavy_job_at_a_time": True,
            "components": [
                {"component_id": "TH_SDFORMERFLOW", **COMPONENTS["TH_SDFORMERFLOW"], "market_context_key": ctxkey, "enabled": self.svc.module_on("sdformerflow"),
                 "active_version": s["sdformer"].get("active_run"), "previous_version": s["sdformer"].get("previous_run"), "versions": runs,
                 "runtime_state": sdf_state.get("state") or "WAITING_FOR_DATA", "last_inference": sdf_state.get("result"),
                 "job": self.svc.jobs.get("sdformer_last"), "metrics": {"holdout": None, "accuracy": None, "calibration": None, "status": "NOT_RUN"}},
                {"component_id": "ETC_LOG_CHANNEL", **COMPONENTS["ETC_LOG_CHANNEL"], "market_context_key": ctxkey, "enabled": self.svc.module_on("exponential_trend_channel"),
                 "active_version": s["etc"].get("param_version"), "active_params": {k: s["etc"][k] for k in ("price", "window_set", "width")},
                 "previous_version": s["etc"].get("previous_version"), "versions": self.etc_versions(), "feature_order": list(ETC.FEATURES),
                 "job": self.jobs.get("etc_last")},
            ], "jobs": {k: {x: v.get(x) for x in ("job_id", "kind", "component_id", "state", "computation", "artifact", "activation", "error")} for k, v in self.jobs.items()}}

    # ------------------------------------------------------------------ jobs
    def start_job(self, component_id: str, kind: str, body: dict) -> dict:
        if component_id not in COMPONENTS:
            raise ValueError("UNKNOWN_COMPONENT")
        c = self.svc.ensure_main_context()
        if component_id == "TH_SDFORMERFLOW":
            if kind == "DATASET":
                h1 = c.bars_fn("H1", 6000) if c else []
                from .service import _atomic
                f = self.svc._sdf_dir() / "dataset_h1.json"
                _atomic(f, h1)
                dh = hashlib.sha256(f.read_bytes()).hexdigest()[:20]
                return {"ok": True, "kind": "DATASET", "bars": len(h1), "file_hash": dh, "context": c.key if c else None,
                        "state": "READY" if len(h1) >= 600 else "NO_DATA"}
            if kind != "TRAIN":
                raise ValueError("TH_SDFORMERFLOW: kind TRAIN | DATASET")
            op = str(body.get("op") or "from_scratch")
            if op not in ("from_scratch", "fine_tune", "resume"):
                raise ValueError("op: from_scratch | fine_tune | resume")
            ck = body.get("checkpoint") or (self.svc.settings()["sdformer"].get("active_run") if op != "from_scratch" else None)
            if op != "from_scratch" and not ck:
                raise ValueError("fine_tune / resume wymaga checkpointu")
            # 1.46: the checkpoint (body or a legacy settings.json) is a version folder directly in research/sdformer with last.pt -
            # an absolute / '..' path made the worker load and write checkpoints anywhere on the disk
            if ck and (not isinstance(ck, str) or not RUN_ID.match(ck) or not (self.svc._sdf_dir() / ck / "last.pt").is_file()):
                raise ValueError("CHECKPOINT_INVALID: dozwolona tylko istniejąca wersja SDformerFlow (nazwa katalogu z last.pt)")
            h1 = c.bars_fn("H1", 6000) if c else []
            if len(h1) < 600:
                return {"ok": False, "state": "NO_DATA", "reason": f"za mało zamkniętych świec H1 ({len(h1)} < 600)"}
            return self.svc.start_training(c, h1, op=op, checkpoint=str(self.svc._sdf_dir() / ck) if ck else None, reason="panel (DIRECT_USER_REQUEST)",
                                           force=bool(body.get("confirm_during_trading")))
        # ETC
        if kind == "DATASET":
            m5 = c.bars_fn("M5", 3000) if c else []
            p = {k: self.svc.settings()["etc"][k] for k in ("price", "window_set", "width")}
            ser = ETC.series_asof(m5, p, start=max(0, len(m5) - 300)) if m5 else []
            return {"ok": True, "kind": "DATASET", "rows": len(ser), "schema_hash": ETC.schema_hash(p), "feature_order": list(ETC.FEATURES),
                    "masked_rows": sum(1 for r in ser if any((r.get("masks") or {}).values())), "state": "READY" if ser else "NO_DATA"}
        if kind != "OPTIMIZE":
            raise ValueError("ETC_LOG_CHANNEL: kind OPTIMIZE | DATASET")
        with self._lock:          # 1.46: check-then-act was split by the candle read - a double click started two optimisations
            if self.jobs.get("etc_last", {}).get("state") == "RUNNING":
                return {"ok": False, "reason": "optymalizacja ETC już trwa"}
            m5 = c.bars_fn("M5", 3000) if c else []
            if len(m5) < 700:
                return {"ok": False, "state": "NO_OPTIMIZATION_TARGET", "reason": f"za mało zamkniętych świec M5 z dojrzałą etykietą (+10) – {len(m5)} < 700; analiza bazowa działa"}
            job = {"job_id": "ETC-OPT-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), "kind": "OPTIMIZE", "component_id": "ETC_LOG_CHANNEL",
                   "state": "RUNNING", "started_at": time.time(), "context": c.key, "base_version": self.svc.settings()["etc"].get("param_version")}
            self.jobs["etc_last"] = job
            self._cancel.clear()
            threading.Thread(target=self._etc_optimize, args=(job, m5, body), name="etc-optimize", daemon=True).start()
        return {"ok": True, "job": job}

    def cancel(self, component_id: str) -> dict:
        if component_id == "TH_SDFORMERFLOW":
            return self.svc.cancel_training()
        self._cancel.set()
        return {"ok": True, "note": "optymalizacja zatrzyma się po bieżącej ocenie; nic nie zostanie aktywowane"}

    # ------------------------------------------------------------------ ETC optimisation
    def _etc_optimize(self, job: dict, m5: list[dict], body: dict) -> None:
        try:
            H = 10
            n = len(m5)
            eval_idx = list(range(max(300, n - 600), n - H, 2))             # frozen dataset: closed bars with a matured +10 label
            closes = np.array([float(b["c"]) for b in m5])
            cache: dict[tuple, list] = {}

            def channels(price: str, ws: str):
                key = (price, ws)
                if key not in cache:
                    logs = ETC._logs(m5, price)
                    out = []
                    for i in eval_idx:
                        best, _ = ETC.scan(logs, i, ws)
                        out.append(best)
                    cache[key] = out
                return cache[key]

            def loss(x):
                if self._cancel.is_set():
                    raise InterruptedError
                price, ws, width = PRICE_IDX[int(round(x[0]))], WS_IDX[int(round(x[1]))], float(x[2])
                ch = channels(price, ws)
                inside, cnt = 0, 0
                for i, c in zip(eval_idx, ch):
                    if c is None:
                        continue
                    k = i + H
                    mid_k = c["level"] + c["slope"] * H                       # channel frozen at i, projected H bars ahead (as of i)
                    y = math.log(closes[k])
                    inside += abs(y - mid_k) <= width * c["spread"]
                    cnt += 1
                if cnt < 50:
                    return math.inf
                return abs(inside / cnt - ETC_TARGET_COVERAGE)

            cur = self.svc.settings()["etc"]
            space = OP.ParameterSpace(["etc_price_source_idx", "etc_window_set_idx", "etc_channel_width"], [0, 0, 0.5], [len(PRICE_IDX) - 1, 1, 4.0],
                                      [1, 1, 0.05], job["base_version"], group="feature_transform_parameters")
            obj = OP.ObjectiveSnapshot("ETC_CHANNEL_CONTAINMENT", f"close+{H} w kanale (cel {ETC_TARGET_COVERAGE})", [f"{job['context']}|{int(m5[i]['t'])}" for i in eval_idx],
                                       "brak (geometria kanału)", float(m5[eval_idx[-1] + H]["t"]), "minimize", fn=loss)
            inc = [PRICE_IDX.index(cur["price"]), WS_IDX.index(cur["window_set"]), float(cur["width"])]
            o = self.svc.settings()["optimizer"]
            prop = OP.run_job(space, obj, inc, base_version=job["base_version"], budgets={"coa_evals": int(body.get("coa_evals", 80)),
                              "bchimp_evals": int(body.get("bchimp_evals", 60)), "deadline_s": float(body.get("deadline_s", 120))},
                              max_changed=3, max_norm_change=1.0, seed=int(o["seed"]))
            cand = {"price": PRICE_IDX[int(round(prop["candidate"][0]))], "window_set": WS_IDX[int(round(prop["candidate"][1]))], "width": round(float(prop["candidate"][2]), 2)}
            job["computation"] = {"state": "DONE", "objective_hash": prop["objective_hash"], "incumbent_loss": -prop["incumbent_fitness"],
                                  "candidate_loss": -prop["candidate_fitness"], "evaluations": [r["evaluations"] for r in prop["runs"]], "seconds": prop["seconds"],
                                  "winner": prop["winner_algorithm"], "seed": int(o["seed"]), "decision": prop["decision"], "reasons": prop["reasons"],
                                  "note": "wynik optymalizacji na tych danych – nie potwierdzony zysk"}
            if prop["decision"] != "APPLY":
                job.update(state="DONE", artifact={"state": "NOT_CREATED", "reason": "KEEP_INCUMBENT"}, activation={"state": "SKIPPED"})
                return
            ver = "ETC-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            self._add_etc_version({"version": ver, "params": cand, "schema_hash": ETC.schema_hash(cand), "params_hash": ETC.params_hash(cand),
                                   "created_at": _now(), "source": job["job_id"], "objective": job["computation"]})
            job["artifact"] = {"state": "SAVED", "version": ver, "params": cand}
            # technical check: the transform runs, finite features
            test = ETC.snapshot(m5, len(m5) - 1, cand)
            finite = all(v is None or math.isfinite(v) for v in test["features"].values())
            now = self.svc.settings()["etc"]
            if not self.svc.module_on("exponential_trend_channel"):
                job["activation"] = {"state": "SKIPPED", "reason": "moduł wyłączony w trakcie joba"}
            elif now.get("param_version") != job["base_version"]:
                job["activation"] = {"state": "SKIPPED", "reason": "STALE_PROPOSAL – wersja zmieniona w trakcie joba"}
            elif not finite or test["state"] != "READY":
                job["activation"] = {"state": "FAILED", "reason": "test techniczny transformacji nieudany – poprzednia wersja zostaje"}
            else:
                job["activation"] = {"state": "ACTIVE", **self.etc_activate(ver, who=job["job_id"])}
            job["state"] = "DONE"
        except InterruptedError:
            job.update(state="CANCELLED", activation={"state": "SKIPPED", "reason": "anulowano – brak aktywacji"})
        except Exception as exc:  # noqa: BLE001
            job.update(state="FAILED", error=f"{type(exc).__name__}: {exc}"[:300])
        finally:
            job["finished_at"] = time.time()

    # ------------------------------------------------------------------ import / export
    def export_zip(self, component_id: str, version: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if component_id == "TH_SDFORMERFLOW":
                d = self.svc._sdf_dir() / version
                if not (d / "last.pt").exists() or d.parent != self.svc._sdf_dir():
                    raise FileNotFoundError(version)
                for name in ("last.pt", "sdformer_run.json"):
                    if (d / name).exists():
                        z.write(d / name, name)
            else:
                v = {x["version"]: x for x in self.etc_versions()}.get(version)
                if not v:
                    raise FileNotFoundError(version)
                z.writestr("etc_transform.json", json.dumps(v, indent=1))
            z.writestr("manifest.json", json.dumps({"component_id": component_id, **{k: COMPONENTS[component_id][k] for k in ("kind", "implementation_id")},
                                                    "version": version, "exported_at": _now()}, indent=1))
        return buf.getvalue()

    def import_zip(self, component_id: str, data: bytes) -> dict:
        """Validated import: only the declared files, no paths, no scripts; the checkpoint must load strictly in the worker env.
        1.46: unpacked sizes limited (checked before reading, enforced while streaming), last.pt streamed to disk with the hash computed on
        the fly (it was unpacked into memory twice), every JSON must be an object of the expected shape - a malformed archive is a
        ValueError (400), never AttributeError / TypeError (500) or a stored file that breaks the component status for good."""
        if component_id not in COMPONENTS:
            raise ValueError("UNKNOWN_COMPONENT")
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
        names = {i.filename for i in infos}
        allowed = {"manifest.json", "last.pt", "sdformer_run.json"} if component_id == "TH_SDFORMERFLOW" else {"manifest.json", "etc_transform.json"}
        if not names <= allowed or any("/" in n or "\\" in n for n in names):
            raise ValueError(f"niedozwolone pliki w archiwum: {sorted(names - allowed)}")
        if len(infos) != len(names):
            raise ValueError("powtórzone nazwy plików w archiwum")
        if sum(i.file_size for i in infos) > MAX_IMPORT_UNPACKED or any(i.file_size > MAX_IMPORT_JSON for i in infos if i.filename != "last.pt"):
            raise ValueError(f"archiwum po rozpakowaniu przekracza limit ({MAX_IMPORT_UNPACKED // 2**20} MB, pliki JSON {MAX_IMPORT_JSON // 2**20} MB)")
        man = self._zip_json(z, "manifest.json")
        if man.get("component_id") != component_id or man.get("implementation_id") != COMPONENTS[component_id]["implementation_id"]:
            raise ValueError("INCOMPATIBLE: inny komponent / implementacja")
        if component_id == "ETC_LOG_CHANNEL":
            v = self._zip_json(z, "etc_transform.json")
            p = v.get("params")
            w = p.get("width") if isinstance(p, dict) else None
            ok = (isinstance(p, dict) and isinstance(p.get("price"), str) and p["price"] in ETC.PRICES and isinstance(p.get("window_set"), str)
                  and p["window_set"] in WS_IDX and isinstance(w, (int, float)) and not isinstance(w, bool) and 0.1 <= float(w) <= 10)
            if not ok:
                raise ValueError("parametry poza zakresem")
            ver = "ETC-IMP-" + _hash(p)[:8]
            self._add_etc_version({**v, "version": ver, "source": "IMPORT", "created_at": _now()}, replace=ver)
            return {"ok": True, "version": ver, "activation": "ręczna (Aktywuj wersję)"}
        if "last.pt" not in names:
            raise ValueError("brak last.pt w archiwum")
        meta = self._zip_json(z, "sdformer_run.json") if "sdformer_run.json" in names else None
        sd = self.svc._sdf_dir()
        tmp = sd / f".import-{uuid.uuid4().hex}.part"
        try:
            h, n = hashlib.sha256(), 0
            with z.open("last.pt") as src, open(tmp, "wb") as dst:
                while chunk := src.read(1 << 20):
                    n += len(chunk)
                    if n > MAX_IMPORT_UNPACKED:
                        raise ValueError("last.pt po rozpakowaniu przekracza limit")
                    h.update(chunk)
                    dst.write(chunk)
            ver = "SDF-IMP-" + h.hexdigest()[:10]
            d = sd / ver
            d.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, d / "last.pt")
        finally:
            tmp.unlink(missing_ok=True)                   # our own partial file only (after os.replace it no longer exists)
        if meta is not None:
            (d / "sdformer_run.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "version": ver, "activation": "ręczna – przy aktywacji test ładowania i skończoności wyjścia"}

    @staticmethod
    def _zip_json(z: zipfile.ZipFile, name: str) -> dict:
        try:
            with z.open(name) as f:
                raw = f.read(MAX_IMPORT_JSON + 1)
        except KeyError:
            raise ValueError(f"brak {name} w archiwum") from None
        if len(raw) > MAX_IMPORT_JSON:
            raise ValueError(f"{name}: plik za duży")
        try:
            v = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{name}: nieprawidłowy JSON ({exc})"[:200]) from None
        if isinstance(v, dict):
            return v
        raise ValueError(f"{name}: oczekiwany obiekt JSON")         # 400 at the API (TypeError would be a 500)

    def activate_sdf(self, version: str) -> dict:
        d = self.svc._sdf_dir() / version
        if not (d / "last.pt").exists() or d.parent != self.svc._sdf_dir():
            return {"ok": False, "reason": "brak checkpointu"}
        job = {"job_id": f"activate:{version}", "base_active": self.svc.settings()["sdformer"].get("active_run")}
        self.svc._activate_sdformer(version, job)
        return {"ok": job.get("activation", {}).get("state") == "ACTIVE", **job.get("activation", {})}

    def rollback_sdf(self) -> dict:
        prev = self.svc.settings()["sdformer"].get("previous_run")
        if not prev:
            return {"ok": False, "reason": "brak poprzedniej wersji"}
        return self.activate_sdf(prev)
