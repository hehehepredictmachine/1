"""Unified bootstrap orchestrator (Apollo23 TASK 013) - one component DAG, verify-first, heavy model runtimes strictly SEQUENTIAL.

Reuses the existing installers as worker processes (TsfmService.start_install -> tools/tsfm_setup.py, KronosService.start_install ->
tools/kronos_setup.py); never copies their logic and never runs two heavy installs at once. Core components (release files, frontend,
backend, Python env) are verified only - the Go launcher already builds the env (desktop/pyenv.go ensureEnv) before the engine starts.
Feature capabilities are VERIFIED by importing their modules. Profile FULL (default) queues missing heavy runtimes after the engine is up;
CORE only verifies. Disabled in demo / tests (PMW_BOOTSTRAP=0). No model training, no feature activation, no order, no account change.
"""
from __future__ import annotations

import importlib
import json
import os
import threading
import time
from pathlib import Path

from . import paths

STATES = ("PENDING", "VERIFIED", "QUEUED", "INSTALLING", "INSTALLED", "FAILED", "SKIPPED", "NOT_INSTALLED", "BLOCKED")
COMPONENTS = [
    # id, kind, deps, required_for_core, heavy
    ("pmw_release", "RELEASE_FILE", [], True, False),
    ("frontend_assets", "RELEASE_FILE", ["pmw_release"], True, False),
    ("backend_core", "RELEASE_FILE", ["pmw_release"], True, False),
    ("modular_indicator_engine", "FEATURE", ["backend_core"], False, False),
    ("session_context_clock", "FEATURE", ["backend_core"], False, False),
    ("session_range_hud", "FEATURE", ["session_context_clock"], False, False),
    ("multi_market_adapters", "FEATURE", ["backend_core"], False, False),
    ("bookmap_volume_profile", "FEATURE", ["backend_core"], False, False),
    ("orderflow_footprint", "FEATURE", ["bookmap_volume_profile"], False, False),
    ("decision_tree_ranker", "FEATURE", ["backend_core"], False, False),
    ("bat_event_model", "FEATURE", ["backend_core"], False, False),
    ("association_rules", "FEATURE", ["backend_core"], False, False),
    ("pt_directional_skill", "FEATURE", ["backend_core"], False, False),
    ("long_horizon_forecast", "FEATURE", ["backend_core"], False, False),
    ("change_point_engine", "FEATURE", ["backend_core"], False, False),
    ("trader_life_game", "FEATURE", ["backend_core"], False, False),
    ("tsfm_chronos2", "MODEL_RUNTIME", ["backend_core"], False, True),
    ("tsfm_granite_ttm", "MODEL_RUNTIME", ["backend_core"], False, True),
    ("tsfm_tirex2", "MODEL_RUNTIME", ["backend_core"], False, True),
    ("tsfm_tabicl", "MODEL_RUNTIME", ["backend_core"], False, True),
    ("kronos_model", "MODEL_RUNTIME", ["backend_core"], False, True),
]
FEATURE_MODULES = {"modular_indicator_engine": "masterquo.indicators.smoothing", "session_context_clock": "masterquo.analytics.session_context",
                   "session_range_hud": "masterquo.analytics.session_context", "multi_market_adapters": "masterquo.markets.universe",
                   "bookmap_volume_profile": "masterquo.orderflow.analytics", "orderflow_footprint": "masterquo.orderflow.analytics",
                   "decision_tree_ranker": "masterquo.ml.dt_ranker", "bat_event_model": "masterquo.mm.bat_encoder",
                   "association_rules": "masterquo.ml.association_rules", "pt_directional_skill": "masterquo.evaluation.pt_skill",
                   "long_horizon_forecast": "masterquo.forecast.long_horizon", "change_point_engine": "masterquo.lab.change_points.pelt",
                   "trader_life_game": "masterquo.trader_life_game"}


def topo_order(comps=COMPONENTS) -> list[str]:
    ids = {c[0]: c for c in comps}
    seen, out = set(), []

    def visit(i, stack=()):
        if i in stack:
            raise ValueError(f"CYCLE: {stack + (i,)}")
        if i in seen:
            return
        for d in ids[i][2]:
            if d not in ids:
                raise ValueError(f"UNKNOWN_DEPENDENCY: {i} -> {d}")
            visit(d, stack + (i,))
        seen.add(i)
        out.append(i)
    for c in comps:
        visit(c[0])
    return out


class Bootstrap:
    def __init__(self, rt=None, state_file: Path | None = None, profile: str | None = None, probes: dict | None = None, installers: dict | None = None,
                 poll_s: float = 5.0):
        self.rt = rt
        self.file = Path(state_file) if state_file else paths.data_dir() / "bootstrap_state.json"
        self.state = self._load()
        self.state.setdefault("profile", profile or "FULL")
        self.state.setdefault("components", {})
        self.probes = probes or {}
        self.installers = installers or {}
        self.poll_s = poll_s
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ state
    def _load(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
            tmp.replace(self.file)
        except OSError:
            pass

    def _set(self, cid, st, detail=None):
        with self._lock:
            self.state["components"][cid] = {"state": st, "detail": detail, "at": time.time()}
            self._save()

    def set_profile(self, profile: str) -> dict:
        if profile not in ("FULL", "CORE"):
            raise ValueError("profile: FULL | CORE")
        self.state["profile"] = profile
        self._save()
        return self.status()

    # ------------------------------------------------------------ probes
    def _probe(self, cid: str) -> tuple[bool, str]:
        if cid in self.probes:
            return self.probes[cid]()
        root = paths.ROOT_DIR
        if cid == "pmw_release":
            return (root / "backend" / "masterquo" / "__init__.py").exists(), "pliki programu"
        if cid == "frontend_assets":
            return (root / "frontend" / "dist" / "index.html").exists(), "frontend/dist"
        if cid == "backend_core":
            return True, "silnik działa (ten proces)"
        if cid in FEATURE_MODULES:
            try:
                importlib.import_module(FEATURE_MODULES[cid])
                return True, FEATURE_MODULES[cid]
            except Exception as exc:  # noqa: BLE001
                return False, f"{type(exc).__name__}: {exc}"[:200]
        if cid.startswith("tsfm_"):
            svc = getattr(self.rt, "tsfm", None)
            if svc is None:
                return False, "TSFM niedostępny"
            mid = cid[5:]
            try:
                info = svc.env_status(mid) if hasattr(svc, "env_status") else None
            except Exception:  # noqa: BLE001
                info = None
            if info is None:
                from tsfm_runtime import manifest as M
                return bool(M.summary(svc.weights_root(), mid)["installed"]), "wagi"
            return bool(info.get("python_found") and info.get("weights_installed")), "venv + wagi"
        if cid == "kronos_model":
            k = getattr(self.rt, "kronos", None)
            if k is None:
                return False, "Kronos niedostępny"
            return k.state.get("status") not in ("NOT_INSTALLED", "NO_WEIGHTS"), k.state.get("status")
        return False, "UNKNOWN_COMPONENT"

    def _installer(self, cid: str):
        if cid in self.installers:
            return self.installers[cid]
        if cid.startswith("tsfm_") and getattr(self.rt, "tsfm", None) is not None:
            svc, mid = self.rt.tsfm, cid[5:]
            return (lambda: svc.start_install(mid)), (lambda: (svc.jobs.get(f"install_{mid}") or {}).get("state"))
        if cid == "kronos_model" and getattr(self.rt, "kronos", None) is not None:
            k = self.rt.kronos
            return (lambda: k.start_install()), (lambda: (k.jobs.get("install") or {}).get("state"))
        return None

    # ------------------------------------------------------------ run
    def verify_all(self) -> dict:
        comps = {c[0]: c for c in COMPONENTS}
        for cid in topo_order():
            deps_ok = all(self.state["components"].get(d, {}).get("state") in ("VERIFIED", "INSTALLED") for d in comps[cid][2])
            if not deps_ok:
                self._set(cid, "BLOCKED", "zależność niegotowa")
                continue
            ok, detail = self._probe(cid)
            self._set(cid, "VERIFIED" if ok else ("NOT_INSTALLED" if comps[cid][4] else "FAILED"), detail)
        return self.status()

    def queue(self) -> list[str]:
        if self.state["profile"] != "FULL":
            return []
        return [c[0] for c in COMPONENTS if c[4] and self.state["components"].get(c[0], {}).get("state") in ("NOT_INSTALLED", "FAILED_RETRY")]

    def run_heavy(self, timeout_s: float = 6 * 3600) -> list[dict]:
        """Strictly sequential: each install must finish (DONE / FAILED) before the next one starts."""
        done = []
        for cid in self.queue():
            if self._stop.is_set():
                break
            inst = self._installer(cid)
            if inst is None:
                self._set(cid, "SKIPPED", "brak instalatora w tym środowisku")
                continue
            start, poll = inst
            r = start() or {}
            if not r.get("ok", True):
                self._set(cid, "FAILED", str(r.get("reason") or r))
                done.append({"id": cid, "state": "FAILED"})
                continue
            self._set(cid, "INSTALLING", "instalacja w toku (proces instalatora)")
            t0 = time.time()
            st = None
            while time.time() - t0 < timeout_s and not self._stop.is_set():
                st = poll()
                if st in ("DONE", "FAILED", "CANCELLED"):
                    break
                self._stop.wait(self.poll_s)
            ok = st == "DONE" and self._probe(cid)[0]
            self._set(cid, "INSTALLED" if ok else "FAILED", st)
            done.append({"id": cid, "state": "INSTALLED" if ok else "FAILED"})
        return done

    def start(self, delay_s: float = 60.0):
        if os.environ.get("PMW_BOOTSTRAP", "1") == "0" or getattr(self.rt, "demo", False) or self._thread:
            return False

        def run():
            if self._stop.wait(delay_s):
                return
            self.verify_all()
            self.run_heavy()
        self._thread = threading.Thread(target=run, name="bootstrap", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        comps = {c[0]: c for c in COMPONENTS}
        return {"profile": self.state.get("profile"), "order": topo_order(),
                "components": [{"id": cid, "kind": comps[cid][1], "deps": comps[cid][2], "required_for_core": comps[cid][3], "heavy": comps[cid][4],
                                **self.state["components"].get(cid, {"state": "PENDING"})} for cid in topo_order()],
                "policy": {"heavy_parallel": False, "training": "MANUAL_ONLY", "windows_resolution_change": False, "execution_changes": False}}
