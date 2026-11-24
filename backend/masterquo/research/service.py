"""ResearchModulesService (1.41) - one owner of the six MQL5-derived modules in the running bot.

Lifecycle: created in Runtime, started by Runtime.start (autostart, DIRECT_USER_REQUEST), stopped with the app (state persisted).
Per market context (FOREX_MT5 main symbol from the existing bridge; further contexts registered by the market profiles) on every new
CLOSED M5 bar of the context:
  ETC      snapshot (M5 + H1) - FEATURE_VECTOR, the active parameter version
  G7       radar (M5 / M15 / H1, DXY from the bridge's DXY_H1 buffer when configured) - STRUCTURE_CONTEXT, rule confluence (no probability)
  graph    NEXT_BAR_DIRECTION and BPC10 states: matured labels first (each prediction updated once), then the new prediction
           (DIRECTION_SCORE_RAW)
  SDformerFlow  on a new closed H1 bar: inference with the ACTIVE compatible checkpoint (subprocess, isolated); no checkpoint ->
           ONE deduplicated bootstrap training job on the real H1 history (direct_train) - the rest works meanwhile
  optimisers (COA -> BChimp) every >= 300 s once >= 64 matured graph labels (>= 16 new): the analytical weights of the research
           composite (graph / ETC / G7 roles) on the frozen objective (Brier score of the BPC10 event), applied on the next snapshot
Published: features_for(inst, t) (as-of the decision time, for Quant / TabICL), PMW-PRED-2 records (ModelHub, decision trace),
status with the four separate state axes (enabled, runtime, artifact, contribution). Nothing here sends an order.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import paths
from . import etc as ETC
from . import g7 as G7
from . import graph_ca as GR
from . import optim as OP
from .sources import SOURCES

log = logging.getLogger("masterquo.research")
VERSION = "PMW-RESEARCH-1"
MODULES = ("sdformerflow", "cellular_feature_graph", "coa_coyote", "bchimp", "g7_smc_radar", "exponential_trend_channel")
DEFAULT_SETTINGS = {
    "activation_policy": "DIRECT_USER_REQUEST", "enabled": True, "autostart": True,
    "modules": {m: {"enabled": True, "autostart": True, "use": "ACTIVE"} for m in MODULES},
    "etc": {"price": "CLOSE", "window_set": "SHORT", "width": 2.0, "param_version": "ETC-INITIAL"},
    "g7": {"ob_lookback": 50, "impulse_factor": 1.5, "corr_periods": 24},
    "graph": {"cells": 10000, "ticks": 6},
    "optimizer": {"enabled": True, "min_interval_seconds": 300, "min_mature_examples": 64, "min_new_mature_examples": 16, "coa_evals": 240,
                  "bchimp_evals": 160, "deadline_s": 10.0, "max_changed": 3, "max_norm_change": 0.1, "seed": 20261116},
    "composite": {"version": "COMPOSITE-INITIAL", "weights": [0.0, 1.0, 0.0, 0.0], "status": "INITIAL"},
    "sdformer": {"auto_bootstrap": True, "epochs": 6, "minutes": 20.0, "batch": 32, "threads": 2, "active_run": None},
    "cycle_s": 5.0,
}
COMPOSITE_NAMES = ["bias", "graph_bpc10_raw", "etc_position_z_closed", "g7_score_div100"]
RUN_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")          # 1.46: an SDformerFlow version is a folder NAME directly in research/sdformer


def rdir() -> Path:
    p = paths.data_dir() / "research"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _merge(a: dict, b: dict) -> dict:
    out = json.loads(json.dumps(a))
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _atomic(p: Path, obj) -> None:
    # 1.46: the temp name is unique per writer thread - two threads writing the same file shared "<file>.tmp" (one os.replace failed
    # with FileNotFoundError, the other could publish a half-written file)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _is_num(v, lo: float, hi: float, *, integer: bool = False) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return False
    return lo <= float(v) <= hi and (not integer or float(v).is_integer())


def check_settings(s: dict, patch: dict, sdf_dir: Path) -> None:
    """1.46: PUT research-modules/settings checked etc.* and graph.cells only (None / a non-object was a TypeError -> 500), g7.ob_lookback
    < 15 gave an IndexError in every cycle, sdformer numbers broke the training start (governor slot kept) and sdformer.active_run was any
    path given to the worker. Raises ValueError (400). etc and graph.cells are always checked (as before); every other value only when the
    change sets it, so a legacy value elsewhere never blocks e.g. a module switch. `s` = DEFAULT_SETTINGS merged with the new file."""
    def need(ok: bool, code: str) -> None:
        if not ok:
            raise ValueError(code)
    for k in ("etc", "graph"):
        need(isinstance(s.get(k), dict), f"SETTINGS_SECTION_NOT_AN_OBJECT:{k}")
    e = s["etc"]
    need(isinstance(e.get("window_set"), str) and e["window_set"] in ("SHORT", "LONG") and isinstance(e.get("price"), str)
         and e["price"] in ETC.PRICES and _is_num(e.get("width"), 0.1, 10), "ETC_PARAMETERS_INVALID")
    need(_is_num(s["graph"].get("cells"), 100, 40000, integer=True), "GRAPH_CELLS_OUT_OF_RANGE (100..40000)")
    for sec, sub in patch.items():
        if sec == "enabled":
            need(isinstance(sub, bool), "SETTINGS_ENABLED_NOT_BOOL")
            continue
        need(isinstance(sub, dict), f"SETTINGS_SECTION_NOT_AN_OBJECT:{sec}")
        for k in sub:
            v = s[sec].get(k)
            if sec == "modules":
                need(k in MODULES and isinstance(v, dict), f"MODULE_UNKNOWN:{k}")
                need(all(isinstance(v.get(f), bool) for f in ("enabled", "autostart") if f in v), f"MODULE_FLAGS_NOT_BOOL:{k}")
                need(isinstance(v.get("use", ""), str), f"MODULE_USE_INVALID:{k}")
            elif (sec, k) in _SETTING_RANGES:
                lo, hi, integer = _SETTING_RANGES[(sec, k)]
                need(_is_num(v, lo, hi, integer=integer), f"{sec.upper()}_{k.upper()}_OUT_OF_RANGE ({lo}..{hi})")
            elif (sec, k) in (("optimizer", "enabled"), ("sdformer", "auto_bootstrap")):
                need(isinstance(v, bool), f"{sec.upper()}_{k.upper()}_NOT_BOOL")
            elif (sec, k) in (("etc", "param_version"), ("etc", "previous_version")):
                need(v is None or isinstance(v, str), f"ETC_{k.upper()}_INVALID")
            elif (sec, k) in (("sdformer", "active_run"), ("sdformer", "previous_run")):
                need(v is None or (isinstance(v, str) and bool(RUN_ID.match(v))), f"SDFORMER_{k.upper()}_INVALID")
                need(k != "active_run" or v is None or (sdf_dir / v / "last.pt").is_file(), "SDFORMER_ACTIVE_RUN_NOT_FOUND")


# 1.46: (section, key) -> (min, max, integer). g7: CheckOB reads the series up to index 14 and the radar gets the last 80 H1 bars (15..80);
# the DXY correlation needs 3..80 common H1 bars.
_SETTING_RANGES = {
    ("g7", "ob_lookback"): (15, 80, True), ("g7", "impulse_factor"): (0.01, 100, False), ("g7", "corr_periods"): (3, 80, True),
    ("graph", "cells"): (100, 40000, True), ("graph", "ticks"): (1, 1000, True),
    ("optimizer", "min_interval_seconds"): (0, 30 * 86400, False), ("optimizer", "min_mature_examples"): (1, 1_000_000, True),
    ("optimizer", "min_new_mature_examples"): (0, 1_000_000, True), ("optimizer", "coa_evals"): (1, 1_000_000, True),
    ("optimizer", "bchimp_evals"): (1, 1_000_000, True), ("optimizer", "deadline_s"): (0.1, 3600, False),
    ("optimizer", "max_changed"): (1, len(COMPOSITE_NAMES), True), ("optimizer", "max_norm_change"): (1e-6, 100, False),
    ("optimizer", "seed"): (0, 2**32 - 1, True),
    ("sdformer", "epochs"): (1, 1000, True), ("sdformer", "minutes"): (0.1, 24 * 60, False), ("sdformer", "batch"): (1, 4096, True),
    ("sdformer", "threads"): (1, 256, True),
}


def _iso(t) -> str | None:
    return datetime.fromtimestamp(float(t), timezone.utc).isoformat(timespec="seconds") if t else None


def _ts(s) -> float | None:
    if s is None:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def torch_python() -> str | None:
    """Any model environment with torch 2.14.1 (SDformerFlow has no environment of its own)."""
    root = paths.ROOT_DIR
    for v in (".venv_deep", ".venv_tirex2", ".venv_tabicl", ".venv_chronos2", ".venv_kronos", ".venv_granite"):
        for p in (root / v / "Scripts" / "python.exe", root / v / "bin" / "python"):
            if p.is_file():
                return str(p)
    return os.environ.get("MQ_SDF_PYTHON")


class Context:
    """State of ONE market context (profile + venue + product + native instrument): never shared with another context."""

    def __init__(self, key: str, inst: str, bars_fn, profile: str = "FOREX_MT5"):
        self.key, self.inst, self.bars_fn, self.profile = key, inst, bars_fn, profile
        self.last_m5: float | None = None
        self.last_h1: float | None = None
        self.snaps: list[dict] = []                       # as-of snapshots (newest last, bounded)
        self.gen = 0                                      # 1.46: snapshots made (generation was len(snaps) + 1 - stuck at 3001 after the cap)
        self.etc_prev: dict | None = None
        self.zones = G7.ZoneBook(inst)
        self.graph = {t: GR.TargetState(t) for t in GR.TARGETS}
        self.sdf: dict | None = None
        self.labels_new = 0


class ResearchModulesService:
    def __init__(self, rt, *, data_dir: Path | None = None):
        self.rt = rt
        self.base = Path(data_dir) if data_dir else rdir()
        self.base.mkdir(parents=True, exist_ok=True)
        self.contexts: dict[str, Context] = {}
        self._lock = threading.RLock()
        # 1.46: one lock for every read-modify-write of settings.json / parameter_history.json / optimizer_jobs.json (API thread, research
        # loop, etc-optimize and sdformer-train threads wrote them concurrently - lost updates, e.g. a module switched off came back on)
        self._settings_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.loop = {"cycles": 0, "errors": 0, "last_error": None, "last_cycle_at": None}
        self.jobs: dict[str, dict] = {}
        self.opt_last = 0.0
        self.param_history: list[dict] = self._read(self.base / "parameter_history.json", [])
        self.governor = None
        self._sdf_proc: subprocess.Popen | None = None
        from .components import Components
        self.components = Components(self)

    # ------------------------------------------------------------------ settings
    def _read(self, p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _raw_settings(self) -> dict:
        raw = self._read(self.base / "settings.json", {})
        return raw if isinstance(raw, dict) else {}

    def settings(self) -> dict:
        return _merge(DEFAULT_SETTINGS, self._raw_settings())

    def update_settings(self, patch: dict, who: str = "panel") -> dict:
        allowed = {"enabled", "modules", "etc", "g7", "graph", "optimizer", "sdformer"}
        bad = [k for k in patch if k not in allowed] if isinstance(patch, dict) else [f"<{type(patch).__name__}>"]   # 1.46: not an object = 400
        if bad:
            raise ValueError(f"SETTINGS_KEYS_NOT_ALLOWED:{bad}")
        with self._settings_lock:
            cur = self._raw_settings()
            new = _merge(cur, patch)
            s = _merge(DEFAULT_SETTINGS, new)
            check_settings(s, patch, self._sdf_dir())
            _atomic(self.base / "settings.json", new)
            self._history("SETTINGS", who, patch)
        return s

    def _history(self, kind: str, who: str, change) -> None:
        with self._settings_lock:
            self.param_history.append({"at": _iso(time.time()), "kind": kind, "who": who, "change": change})
            self.param_history = self.param_history[-500:]
            _atomic(self.base / "parameter_history.json", self.param_history)

    def module_on(self, m: str) -> bool:
        s = self.settings()
        return bool(s.get("enabled", True)) and bool(((s.get("modules") or {}).get(m) or {}).get("enabled", True))

    # ------------------------------------------------------------------ contexts
    def _bridge_symbol(self) -> str | None:
        return getattr(getattr(getattr(self.rt, "bridge", None), "cfg", None), "symbol", None)

    def _bridge_bars(self, tf: str, n: int = 1500) -> list[dict]:
        br = getattr(self.rt, "bridge", None)
        if br is None:
            return []
        try:
            raw = br.bars(tf, include_forming=False)[-n:]
        except Exception:  # noqa: BLE001 - a timeframe the bridge does not keep: no bars (state WAITING_FOR_DATA)
            return []
        out = []
        for b in raw:
            t = _ts(b.get("open_utc"))
            if t is None:
                continue
            out.append({"t": t, "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"]), "tv": float(b.get("tv") or 0.0)})
        return out

    def ensure_main_context(self) -> Context | None:
        try:
            inst = self.rt.sh.instrument()
        except Exception:  # noqa: BLE001
            inst = "XAUUSD"
        sym = self._bridge_symbol() or inst
        key = f"FOREX_MT5|MT5|{'SYNTHETIC' if getattr(self.rt, 'demo', False) else 'LIVE'}|ACCOUNT|CFD|{sym}"
        with self._lock:
            if key not in self.contexts:
                # 1.46: a main context reads ONLY its own symbol - after an asset switch the old context waits (no bars) instead of learning
                # from the new symbol's candles (move = new close - stored close of the old symbol corrupted weights / cell PnL)
                c = Context(key, inst, lambda tf, n=1500, _sym=sym: self._bridge_bars(tf, n) if (self._bridge_symbol() or inst) == _sym else [])
                self._load_ctx(c)
                self.contexts[key] = c
            return self.contexts[key]

    def register_context(self, key: str, inst: str, bars_fn, profile: str) -> None:
        with self._lock:
            if key not in self.contexts:
                c = Context(key, inst, bars_fn, profile)
                self._load_ctx(c)
                self.contexts[key] = c

    def _ctx_file(self, c: Context) -> Path:
        import hashlib
        return self.base / f"ctx_{hashlib.sha256(c.key.encode()).hexdigest()[:12]}.json"

    def _load_ctx(self, c: Context) -> None:
        d = self._read(self._ctx_file(c), None)
        if not d or d.get("key") != c.key:
            return
        try:
            for t, gs in (d.get("graph") or {}).items():
                if t in GR.TARGETS and gs.get("order_hash") == GR.ORDER_HASH:
                    c.graph[t] = GR.TargetState.from_dict(gs)
            c.zones.zones = d.get("zones") or {}
            c.sdf = d.get("sdf")
        except Exception:  # noqa: BLE001 - an unreadable state starts INITIAL (reported), never half-loaded
            log.exception("research state of %s unreadable - INITIAL", c.key)

    def _save_ctx(self, c: Context) -> None:
        d = {"key": c.key, "saved_at": _iso(time.time()), "graph": {t: s.to_dict() for t, s in c.graph.items()},
             "zones": dict(list(c.zones.zones.items())[-500:]), "sdf": c.sdf}
        _atomic(self._ctx_file(c), d)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not self.settings().get("autostart", True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="research-modules", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for c in self.contexts.values():
                try:
                    self._save_ctx(c)
                except Exception:  # noqa: BLE001
                    pass
        p = self._sdf_proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def _run(self) -> None:
        saved = time.time()
        while not self._stop.is_set():
            try:
                self.cycle()
                if time.time() - saved > 120:
                    with self._lock:
                        for c in self.contexts.values():
                            self._save_ctx(c)
                    saved = time.time()
            except Exception as exc:  # noqa: BLE001 - the loop never dies; the error is visible in status
                self.loop["errors"] += 1
                self.loop["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
                log.exception("research cycle failed")
            self._stop.wait(float(self.settings().get("cycle_s") or 5.0))

    # ------------------------------------------------------------------ cycle
    def cycle(self) -> dict:
        self.ensure_main_context()
        out = {}
        with self._lock:
            ctxs = list(self.contexts.values())
        for c in ctxs:
            out[c.key] = self._cycle_ctx(c)
        self.loop["cycles"] += 1
        self.loop["last_cycle_at"] = time.time()
        self._maybe_optimise()
        return out

    def _cycle_ctx(self, c: Context) -> dict:
        s = self.settings()
        m5 = c.bars_fn("M5", 1500)
        if len(m5) < 30 or m5[-1]["t"] == c.last_m5:
            return {"state": "WAITING_FOR_DATA" if len(m5) < 30 else "NO_NEW_BAR"}
        c.last_m5 = m5[-1]["t"]
        h1 = c.bars_fn("H1", 1100)
        m15 = c.bars_fn("M15", 300)
        c.gen += 1
        snap = {"t": m5[-1]["t"] + 300, "bar_t": m5[-1]["t"], "context": c.key, "generation": c.gen, "modules": {}}
        if self.module_on("exponential_trend_channel"):
            p = {k: s["etc"][k] for k in ("price", "window_set", "width")}
            e5 = ETC.snapshot(m5, len(m5) - 1, p, c.etc_prev)
            c.etc_prev = e5
            e1 = ETC.snapshot(h1, len(h1) - 1, p) if len(h1) > 25 else None
            snap["modules"]["exponential_trend_channel"] = {"result_type": "FEATURE_VECTOR", "M5": e5, "H1": e1, "parameter_version": s["etc"]["param_version"],
                                                            "feature_schema_id": ETC.schema_hash(p)}
        if self.module_on("g7_smc_radar"):
            dxy = self._bridge_bars("DXY_H1", 200) if c.profile == "FOREX_MT5" else None
            r = G7.radar(m5[-60:], m15[-60:], h1[-80:], dxy, s["g7"])
            for tf, bs in (("M5", m5[-10:]), ("M15", m15[-10:])):
                c.zones.observe(tf, bs)
            snap["modules"]["g7_smc_radar"] = {"result_type": "STRUCTURE_CONTEXT", **r, "zones_active": len([z for z in c.zones.asof(snap["t"]) if z["state"] in ("ACTIVE", "TOUCHED")])}
        if self.module_on("cellular_feature_graph"):
            ex = GR.extract(m5)
            if ex is not None:
                raw, mask = ex
                closes = {b["t"]: b["c"] for b in m5}
                times = [b["t"] for b in m5]
                gres = {}
                for t, st in c.graph.items():
                    n_up = st.mature(closes, times)
                    c.labels_new += n_up
                    pr = st.predict(f"{c.key}|{m5[-1]['t']}", m5[-1]["t"], m5[-1]["c"], raw)
                    gres[t] = {"raw_score": pr["raw_score"], "model_update_version": st.version, "matured_now": n_up, "pending": len(st.pending)}
                snap["modules"]["cellular_feature_graph"] = {"result_type": "DIRECTION_SCORE_RAW", "targets": gres, "feature_schema_id": f"{GR.SCHEMA}:{GR.ORDER_HASH}",
                                                             "masked": [GR.NAMES[i] for i in np.nonzero(mask)[0]], "cells": c.graph["BPC10"].cells.n,
                                                             "initialization": "DETERMINISTIC_INITIAL_NOT_PRETRAINED"}
        if self.module_on("sdformerflow") and h1 and h1[-1]["t"] != c.last_h1:
            c.last_h1 = h1[-1]["t"]
            self._sdformer(c, h1)
        if c.sdf and c.sdf.get("result"):
            snap["modules"]["sdformerflow"] = {"result_type": "DIRECTION_SCORE_RAW", **c.sdf["result"]}
        comp = self._composite(snap, s)
        if comp is not None:
            snap["composite"] = comp
        c.snaps.append(snap)
        c.snaps = c.snaps[-3000:]
        return {"state": "UPDATED", "modules": list(snap["modules"])}

    def _composite(self, snap: dict, s: dict) -> dict | None:
        w = s["composite"]["weights"]
        g = ((snap["modules"].get("cellular_feature_graph") or {}).get("targets") or {}).get("BPC10", {}).get("raw_score")
        e = (((snap["modules"].get("exponential_trend_channel") or {}).get("M5") or {}).get("features") or {}).get("etc_position_z_closed")
        r7 = (snap["modules"].get("g7_smc_radar") or {}).get("rule_confluence_score")
        x = [1.0, g if g is not None else 0.0, e if e is not None else 0.0, (r7 / 100.0) if r7 is not None else 0.0]
        if g is None:
            return None
        z = sum(wi * xi for wi, xi in zip(w, x))
        return {"p_event_raw": 1 / (1 + math.exp(-max(-30, min(30, z)))), "event": "BPC10_UP (kierunek ruchu w 10 świecach M5)",
                "weights_version": s["composite"]["version"], "weights_status": s["composite"]["status"], "inputs": dict(zip(COMPOSITE_NAMES, x)),
                "calibration_status": "UNCALIBRATED", "correlation_group": "RESEARCH_COMPOSITE (graf + ETC + G7 – jedna grupa pochodzenia)"}

    # ------------------------------------------------------------------ SDformerFlow
    def _sdf_dir(self) -> Path:
        p = self.base / "sdformer"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _sdformer(self, c: Context, h1: list[dict]) -> None:
        s = self.settings()["sdformer"]
        py = torch_python()
        st = c.sdf or {}
        run = s.get("active_run") or st.get("active_run")
        if not py:
            c.sdf = {**st, "state": "WAITING_DEPENDENCY", "reason": "brak środowiska z torch 2.14.1 (np. .venv_tirex2 po instalacji modeli 1.41)"}
            return
        if run and not (isinstance(run, str) and RUN_ID.match(run)):    # 1.46: a legacy settings.json may hold a path - never given to the worker
            c.sdf = {**st, "state": "ERROR", "reason": "nieprawidłowa aktywna wersja SDformerFlow w ustawieniach (dozwolona tylko nazwa wersji)"}
            return
        if run and (self._sdf_dir() / run / "last.pt").exists():
            self._sdf_infer(c, h1, py, run)
            return
        if not s.get("auto_bootstrap", True):
            c.sdf = {**st, "state": "MISSING", "reason": "brak zgodnego checkpointu; automatyczny bootstrap wyłączony"}
            return
        j = self.jobs.get("sdformer_bootstrap")
        if j and j.get("state") in ("RUNNING", "QUEUED"):
            c.sdf = {**st, "state": "TRAINING", "job": j}
            return
        if j and j.get("state") == "CANCELLED":           # 1.46: the user's cancel is final for the automatic bootstrap (manual start only)
            c.sdf = {**st, "state": "MISSING", "reason": "bootstrap anulowany przez użytkownika – trening tylko ręcznie (panel)", "job": j}
            return
        failed = j and (j.get("state") == "FAILED" or (j.get("state") == "DONE" and not run))      # DONE without an active run = activation failed
        if failed and time.time() - j.get("finished_at", 0) < 6 * 3600:
            c.sdf = {**st, "state": "ERROR", "reason": j.get("error") or "trening zakończony bez aktywnego checkpointu", "job": j}
            return
        if len(h1) < 600:
            c.sdf = {**st, "state": "NO_DATA", "reason": f"za mało zamkniętych świec H1 ({len(h1)} < 600) do bootstrap treningu"}
            return
        r = self.start_training(c, h1, op="from_scratch", reason="BOOTSTRAP (brak checkpointu – DIRECT_USER_REQUEST)")
        if not r.get("ok"):                               # 1.46: refused (Memory Governor, AUTO trading, ...) was shown as TRAINING without a job
            c.sdf = {**st, "state": "MISSING", "reason": f"bootstrap treningu odłożony: {r.get('reason')}"[:300]}
            return
        c.sdf = {**st, "state": "TRAINING", "job": self.jobs.get("sdformer_bootstrap")}

    def start_training(self, c: Context, h1: list[dict], *, op: str = "from_scratch", checkpoint: str | None = None, reason: str = "panel",
                       force: bool = False) -> dict:
        py = torch_python()
        if not py:
            return {"ok": False, "reason": "WAITING_DEPENDENCY: brak środowiska z torch"}
        if self._sdf_proc and self._sdf_proc.poll() is None:
            return {"ok": False, "reason": "trening SDformerFlow już trwa (jedno ciężkie zadanie naraz)"}
        s = self.settings()["sdformer"]
        try:                                              # 1.46: numbers checked BEFORE the governor slot is taken (it was kept until restart)
            nums = [str(int(s["epochs"])), str(float(s["minutes"])), str(int(s["batch"])), str(int(s["threads"]))]
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "reason": f"SETTINGS_INVALID: ustawienia sdformer ({type(exc).__name__}: {exc})"[:300]}
        gov = self.governor
        if gov is not None:
            # 1.46: the REAL trading state (trading_active was hard-coded False - "no background training during AUTO trading" never applied)
            # and the profile's heavy_allowed (LOW_MEMORY_8GB: SDformerFlow training off); force = explicit confirmation from the panel
            mode = getattr(getattr(getattr(self, "rt", None), "modes", None), "mode", "SIGNALS")
            allowed = (gov.profile() or {}).get("heavy_allowed") if hasattr(gov, "profile") else None
            if allowed is not None and "sdformerflow" not in allowed:
                return {"ok": False, "reason": f"RESOURCE: profil pamięci – trening sdformerflow wyłączony (dozwolone ciężkie: {', '.join(allowed) or 'brak'})"}
            ok, why = gov.admit_training("sdformerflow", "heavy", trading_active=mode in ("AUTO_DEMO", "AUTO_LIVE"), force=bool(force))
            if not ok:
                return {"ok": False, "reason": f"RESOURCE: {why}"}
        job = None
        try:                                              # 1.46: any error before the process runs releases the governor slot
            data = self._sdf_dir() / "bootstrap_h1.json"
            _atomic(data, h1)
            run_id = "SDF-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            status = self._sdf_dir() / f"{run_id}.status.json"
            cancel = self._sdf_dir() / "cancel.flag"
            cancel.unlink(missing_ok=True)
            argv = [py, "-m", "sdformer_runtime.train", "--data", str(data), "--out", str(self._sdf_dir()), "--op", op, "--epochs", nums[0],
                    "--minutes", nums[1], "--batch", nums[2], "--threads", nums[3], "--context", c.key,
                    "--cancel-file", str(cancel), "--status-file", str(status), "--run-id", run_id] + (["--checkpoint", checkpoint] if checkpoint else [])
            env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONNOUSERSITE="1")
            env.pop("PYTHONHOME", None)
            job = {"job_id": run_id, "kind": "TRAIN", "op": op, "state": "RUNNING", "started_at": time.time(), "reason": reason, "context": c.key,
                   "status_file": str(status), "component": "TH_SDFORMERFLOW", "profile": "direct_train",
                   "base_active": s.get("active_run")}
            self.jobs["sdformer_bootstrap" if op == "from_scratch" and reason.startswith("BOOTSTRAP") else f"sdformer_{run_id}"] = job
            self.jobs["sdformer_last"] = job
            self._sdf_proc = subprocess.Popen(argv, cwd=str(paths.ROOT_DIR / "backend"), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                              text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:  # noqa: BLE001
            if gov is not None:
                gov.training_done("sdformerflow")
            err = f"nie można uruchomić procesu treningu: {type(exc).__name__}: {exc}"[:300]
            if job is not None:
                job.update(state="FAILED", finished_at=time.time(), error=err)
            return {"ok": False, "reason": err}
        if self.governor is not None:
            p = self._sdf_proc
            self.governor.register("sdformerflow", "heavy", lambda: p.pid if p.poll() is None else None)

        def wait():
            last = ""
            try:
                for line in self._sdf_proc.stdout:
                    last = line.strip() or last
                self._sdf_proc.wait()
            finally:
                if self.governor is not None:                      # 1.42.10: zwolnij „slot” ciężkiego treningu (bez tego Granite / kolejny
                    self.governor.training_done("sdformerflow")    # trening SDformerFlow były odrzucane do restartu bota)
            res = {}
            if last.startswith("RESULT "):
                try:
                    res = json.loads(last[7:])
                except ValueError:
                    res = {}
            job.update(state="DONE" if res.get("ok") else ("CANCELLED" if res.get("code") == "CANCELLED" else "FAILED"), finished_at=time.time(),
                       result={k: res.get(k) for k in ("run_id", "samples", "params", "epochs_done", "steps", "weights_changed", "history", "seconds", "metrics", "code")},
                       error=res.get("error"))
            if res.get("ok"):
                try:
                    self._activate_sdformer(res["run_id"], job)
                except Exception as exc:                  # 1.46: an activation error killed this thread silently (DONE, no 'activation')
                    log.exception("SDformerFlow activation of %s failed", res.get("run_id"))
                    job["activation"] = {"state": "FAILED", "reason": f"{type(exc).__name__}: {exc}"[:300]}
        threading.Thread(target=wait, name="sdformer-train", daemon=True).start()
        return {"ok": True, "job": job}

    def _activate_sdformer(self, run_id: str, job: dict) -> None:
        """Callback after a successful job: technical check (strict load + finite inference) then atomic activation - unless the user
        changed the active version or switched the module off meanwhile (a newer user decision is never overwritten)."""
        s = self.settings()
        if not self.module_on("sdformerflow"):
            job["activation"] = {"state": "SKIPPED", "reason": "moduł wyłączony przez użytkownika w trakcie treningu"}
            return
        if s["sdformer"].get("active_run") not in (None, job.get("base_active")):
            job["activation"] = {"state": "SKIPPED", "reason": "użytkownik zmienił aktywną wersję w trakcie treningu"}
            return
        py = torch_python()
        if not py:
            job["activation"] = {"state": "FAILED", "reason": "WAITING_DEPENDENCY: brak środowiska z torch"}
            return
        data = self._sdf_dir() / "activation_test_h1.json"
        c = self.ensure_main_context()
        h1 = c.bars_fn("H1", 400) if c else []
        if len(h1) < 200 and (self._sdf_dir() / "bootstrap_h1.json").exists():
            data = self._sdf_dir() / "bootstrap_h1.json"
        else:
            _atomic(data, h1)
        # 1.46: TimeoutExpired / an unreadable RESULT line raised (manual activation -> 500, after training the thread died); same
        # environment flags as the live inference (_sdf_infer) and no console window on Windows
        try:
            r = subprocess.run([py, "-m", "sdformer_runtime.infer", "--checkpoint", str(self._sdf_dir() / run_id), "--bars", str(data)],
                               cwd=str(paths.ROOT_DIR / "backend"), env=dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONNOUSERSITE="1"),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            line = (r.stdout.strip().splitlines() or [""])[-1]
            res = json.loads(line[7:]) if line.startswith("RESULT ") else {}
            ok = isinstance(res, dict) and bool(res.get("ok"))
        except subprocess.TimeoutExpired:
            ok, line = False, "TIMEOUT 300 s – proces przerwany"
        except (OSError, ValueError) as exc:
            ok, line = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            job["activation"] = {"state": "FAILED", "reason": "test techniczny checkpointu nieudany – poprzednia wersja zostaje", "detail": line[:300]}
            return
        prev = s["sdformer"].get("active_run")
        try:
            self.update_settings({"sdformer": {"active_run": run_id, "previous_run": prev}}, who=f"job:{job['job_id']}")
        except ValueError as exc:                         # 1.46: e.g. a legacy invalid sdformer value - reported, never a 500 / dead thread
            job["activation"] = {"state": "FAILED", "reason": f"zapis ustawień odrzucony: {exc}"[:300]}
            return
        job["activation"] = {"state": "ACTIVE", "run_id": run_id, "previous": prev, "policy": "DIRECT_USER_REQUEST"}

    def _sdf_infer(self, c: Context, h1: list[dict], py: str, run: str) -> None:
        # 1.46: stable name per context (hash() of a str is salted per process - a new 400-bar file after every restart)
        f = self._sdf_dir() / f"infer_{hashlib.sha256(c.key.encode()).hexdigest()[:12]}.json"
        _atomic(f, h1[-400:])
        try:
            r = subprocess.run([py, "-m", "sdformer_runtime.infer", "--checkpoint", str(self._sdf_dir() / run), "--bars", str(f)],
                               cwd=str(paths.ROOT_DIR / "backend"), env=dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONNOUSERSITE="1"),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            line = (r.stdout.strip().splitlines() or [""])[-1]
            res = json.loads(line[7:]) if line.startswith("RESULT ") else {"ok": False, "error": (r.stderr or "")[-300:]}
        except subprocess.TimeoutExpired:
            res = {"ok": False, "error": "TIMEOUT 180 s – proces przerwany"}
        if res.get("ok"):
            c.sdf = {"state": "PREDICTION_ACTIVE", "active_run": run, "result": {k: res[k] for k in ("direction_score_raw", "forecast_body_6", "atr14", "embedding8", "run_id", "bar_t", "ms")},
                     "computed_at": time.time()}
        else:
            c.sdf = {"state": "ERROR", "active_run": run, "reason": res.get("error") or res.get("code"), "computed_at": time.time()}

    def cancel_training(self) -> dict:
        (self._sdf_dir() / "cancel.flag").write_text("cancel", encoding="utf-8")
        return {"ok": True, "note": "trening zatrzyma się po bieżącej paczce; niepełny zapis nie jest aktywowany"}

    # ------------------------------------------------------------------ optimisers (COA -> BChimp)
    def _maybe_optimise(self) -> None:
        s = self.settings()
        o = s["optimizer"]
        if not o.get("enabled") or not (self.module_on("coa_coyote") or self.module_on("bchimp")):
            return
        if time.time() - self.opt_last < float(o["min_interval_seconds"]):
            return
        c = self.ensure_main_context()
        if c is None or c.labels_new < int(o["min_new_mature_examples"]):
            return
        rows = self._objective_rows(c)
        if len(rows) < int(o["min_mature_examples"]):
            return
        self.opt_last = time.time()
        c.labels_new = 0
        self.optimise(c, rows)

    def _objective_rows(self, c: Context) -> list[tuple]:
        """Matured BPC10 rows: (inputs known at the snapshot, label known 10 bars later) - only snapshots whose label is known now."""
        bars = c.bars_fn("M5", 3000)
        idx = {b["t"]: i for i, b in enumerate(bars)}
        out = []
        for sn in c.snaps:
            comp = sn.get("composite")
            i = idx.get(sn["bar_t"])
            if not comp or i is None or i + 10 >= len(bars):
                continue
            y = 1.0 if bars[i + 10]["c"] > bars[i]["c"] else 0.0
            out.append((comp["inputs"], y, sn["bar_t"]))
        return out

    def optimise(self, c: Context, rows: list[tuple]) -> dict:
        s = self.settings()
        o = s["optimizer"]
        X = np.asarray([[r[0][n] for n in COMPOSITE_NAMES] for r in rows], float)
        y = np.asarray([r[1] for r in rows], float)

        def brier(w):
            z = np.clip(X @ np.asarray(w, float), -30, 30)
            return float(((1 / (1 + np.exp(-z)) - y) ** 2).mean())
        space = OP.ParameterSpace(["w_bias", "w_graph_bpc10", "w_etc_position", "w_g7_score"], [-1.0, -3.0, -3.0, -3.0], [1.0, 3.0, 3.0, 3.0],
                                  [0.01, 0.01, 0.01, 0.01], s["composite"]["version"], group="analytical_model_role_weights")
        obj = OP.ObjectiveSnapshot("RESEARCH_COMPOSITE_BRIER", "BPC10_UP_M5", [f"{c.key}|{int(r[2])}" for r in rows], "brak (kierunek, bez kosztów)",
                                   float(rows[-1][2]), "minimize", fn=brier)
        prop = OP.run_job(space, obj, s["composite"]["weights"], base_version=s["composite"]["version"],
                          budgets={"coa_evals": o["coa_evals"], "bchimp_evals": o["bchimp_evals"], "deadline_s": o["deadline_s"]},
                          max_changed=int(o["max_changed"]), max_norm_change=float(o["max_norm_change"]), seed=int(o["seed"]))
        job = {"job_id": "OPT-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"), "kind": "OPTIMIZE", "state": "DONE", "proposal": prop, "finished_at": time.time()}
        self.jobs["optimizer_last"] = job
        cur = self.settings()["composite"]
        if cur["version"] != prop["base_version"]:
            job["publication"] = "STALE_PROPOSAL"
        elif prop["decision"] == "APPLY":
            nv = "COMPOSITE-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            self._set_composite({"version": nv, "weights": prop["candidate"], "status": "OPTIMIZED_RAW", "previous": cur,
                                 "objective_hash": prop["objective_hash"], "algorithm": prop["winner_algorithm"]}, who=job["job_id"])
            job["publication"] = f"APPLIED {nv} (następna generacja snapshotu)"
        else:
            job["publication"] = "KEEP_INCUMBENT: " + ",".join(prop["reasons"])
        with self._settings_lock:
            hist = self._read(self.base / "optimizer_jobs.json", [])
            hist.append({k: job[k] for k in ("job_id", "kind", "state", "finished_at", "publication")} | {"proposal": {k: prop[k] for k in (
                "objective_hash", "base_version", "incumbent", "incumbent_fitness", "candidate", "candidate_fitness", "winner_algorithm", "change_set",
                "decision", "reasons", "seconds")} | {"evaluations": [r["evaluations"] for r in prop["runs"]], "data_count": prop["objective"]["data_count"]}})
            _atomic(self.base / "optimizer_jobs.json", hist[-200:])
        return job

    def _set_composite(self, comp: dict, who: str) -> None:
        with self._settings_lock:                        # 1.46: read-modify-write under the settings lock (see __init__)
            cur = self._raw_settings()
            cur["composite"] = comp
            _atomic(self.base / "settings.json", cur)
            self._history("PARAMETERS", who, {"composite": {k: comp.get(k) for k in ("version", "weights", "status")}})

    def rollback_parameters(self) -> dict:
        cur = self.settings()["composite"]
        prev = cur.get("previous")
        if not prev:
            return {"ok": False, "reason": "brak poprzedniej wersji parametrów"}
        self._set_composite(prev, who="rollback")
        return {"ok": True, "version": prev.get("version")}

    # ------------------------------------------------------------------ publication
    def latest(self, inst: str | None = None) -> dict | None:
        c = self.ensure_main_context()
        if inst and c is not None and c.inst != inst:   # 1.46: inst was ignored - the main context's snapshot answered for any instrument
            return None
        return c.snaps[-1] if c and c.snaps else None

    def features_for(self, inst: str, t: float | None) -> dict:
        """Research features as known at decision time t (the newest snapshot with time <= t) - never a later snapshot."""
        c = self.ensure_main_context()
        if c is None or not c.snaps or (inst and c.inst != inst):
            return {}
        sn = None
        for x in reversed(c.snaps):
            if t is None or x["t"] <= float(t) + 1e-6:
                sn = x
                break
        if sn is None:
            return {}
        f = {}
        e = ((sn["modules"].get("exponential_trend_channel") or {}).get("M5") or {}).get("features") or {}
        f.update({k: v for k, v in e.items() if v is not None})
        g = sn["modules"].get("g7_smc_radar") or {}
        if g:
            f["g7_rule_confluence"] = g["rule_confluence_score"] / 100.0
            f["g7_net_fvg"] = float(g["components"]["net_fvg"])
            f["g7_ob_h1"] = float(g["components"]["ob_h1"])
        gr = (sn["modules"].get("cellular_feature_graph") or {}).get("targets") or {}
        for t_, r in gr.items():
            f[f"graph_{t_.lower()}_raw"] = r["raw_score"]
        sd = sn["modules"].get("sdformerflow") or {}
        if sd.get("direction_score_raw") is not None:
            f["sdf_direction_raw"] = sd["direction_score_raw"]
            for i, v in enumerate(sd.get("embedding8") or []):
                f[f"sdf_emb{i}"] = v
        if sn.get("composite"):
            f["research_composite_p_raw"] = sn["composite"]["p_event_raw"]
        return f

    def predictions(self, inst: str) -> list[dict]:
        from ..modelhub import contract as C
        c = self.ensure_main_context()
        if c is not None and inst and c.inst != inst:
            # 1.46: research results of the main context (its own symbol's candles) were published READY under ANY requested instrument
            # (BTC got XAUUSD scores in /models/predictions and /models/evidence); like features_for / forecast_predictions: DISABLED
            return [C.make(instrument=inst, symbol=None, timeframe="M5", model_name="research", model_version=VERSION, task_type="SCORE",
                           task="RESEARCH_MODULES", horizon_bars=None, unit="ratio", state="DISABLED",
                           unavailable_reason=f"moduły badawcze liczone dla aktywnego instrumentu ({c.inst})")]
        sn = self.latest(inst)
        out = []
        common = dict(instrument=inst, symbol=None, model_version=VERSION, data_kind="SYNTHETIC" if getattr(self.rt, "demo", False) else "REAL",
                      calibration={"method": None, "status": "UNCALIBRATED"})
        gr = ((sn or {}).get("modules", {}).get("cellular_feature_graph") or {}).get("targets") or {}
        for t, r in gr.items():
            out.append(C.make(**common, timeframe="M5", model_name=f"research:graph50:{t}", task_type="SCORE", task=f"GRAPH50_{t}", horizon_bars=GR.TARGETS[t],
                              unit="ratio", state="READY", result={"raw_score": r["raw_score"]}, data_time=_iso(sn["t"]), available_at=_iso(sn["t"]),
                              extra={"canonical_id": f"research:graph50:{t}", "family": "research:graph50", "correlation_group": "RESEARCH_GRAPH"}))
        g = ((sn or {}).get("modules", {}).get("g7_smc_radar") or {})
        if g:
            out.append(C.make(**{**common, "calibration": {"method": None, "status": "NOT_APPLICABLE"}}, timeframe="M5", model_name="research:g7_smc_radar",
                              task_type="SCORE", task="G7_RULE_CONFLUENCE", horizon_bars=None, unit="score_0_100", state="READY",
                              result={"raw_score": g["rule_confluence_score"], "coverage": g["coverage"]}, data_time=_iso(sn["t"]), available_at=_iso(sn["t"]),
                              extra={"canonical_id": "research:g7_smc_radar", "family": "research:g7", "correlation_group": "STRUCTURE_FVG_OB"}))
        sd = ((sn or {}).get("modules", {}).get("sdformerflow") or {})
        if sd.get("direction_score_raw") is not None:
            out.append(C.make(**common, timeframe="H1", model_name="research:sdformerflow", task_type="SCORE", task="SDF_STFS_DIRECTION_H6", horizon_bars=6,
                              unit="ratio", state="READY", result={"raw_score": sd["direction_score_raw"]}, data_time=_iso(sn["t"]), available_at=_iso(sn["t"]),
                              extra={"canonical_id": "research:sdformerflow", "family": "research:sdformerflow", "correlation_group": "RESEARCH_SDFORMER"}))
        return out

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        s = self.settings()
        c = self.ensure_main_context()
        sn = (c.snaps[-1] if c and c.snaps else None)
        mods = {}
        for m in MODULES:
            on = self.module_on(m)
            res = (sn or {}).get("modules", {}).get(m)
            runtime = "STOPPED" if not on else ("RUNNING" if res else "WAITING_FOR_DATA")
            art, contrib = "NOT_REQUIRED", "FEATURES_ACTIVE" if res else "NOT_APPLICABLE"
            if m == "cellular_feature_graph":
                art = "COLD_START" if c and all(x.version == 0 for x in c.graph.values()) else "COMPATIBLE"
                contrib = "RAW_SCORE_ACTIVE" if res else "WAITING_FOR_LABELS"
            elif m == "sdformerflow":
                st = (c.sdf or {}).get("state") if c else None
                art = {"PREDICTION_ACTIVE": "COMPATIBLE", "TRAINING": "TRAINING", "ERROR": "INCOMPATIBLE"}.get(st, "MISSING")
                contrib = "PREDICTION_ACTIVE" if st == "PREDICTION_ACTIVE" else "NOT_APPLICABLE"
                runtime = "STOPPED" if not on else {"WAITING_DEPENDENCY": "DEGRADED", "ERROR": "ERROR", "NO_DATA": "WAITING_FOR_DATA"}.get(st, runtime if st != "TRAINING" else "RUNNING")
            elif m in ("coa_coyote", "bchimp"):
                j = self.jobs.get("optimizer_last")
                contrib = "OPTIMIZING" if j else "WAITING_FOR_LABELS"
                runtime = "RUNNING" if on else "STOPPED"
            elif m == "g7_smc_radar":
                contrib = "FEATURES_ACTIVE" if res else "NOT_APPLICABLE"
            mods[m] = {"module_id": m, "implementation_id": SOURCES[m]["implementation_id"], "source": SOURCES[m]["url"], "author": SOURCES[m]["author"],
                       "enabled": on, "autostart": bool(((s["modules"].get(m) or {}).get("autostart", True))), "runtime_state": runtime, "artifact_state": art,
                       "contribution_state": contrib, "last_update": _iso((sn or {}).get("t")), "detail": self._detail(m, res, c),
                       "license_verified": SOURCES[m]["license_verified"], "checkpoint_verified": SOURCES[m]["checkpoint_verified"]}
        return {"version": VERSION, "activation_policy": s["activation_policy"], "contexts": list(self.contexts), "modules": mods, "loop": dict(self.loop),
                "composite": s["composite"] | {"names": COMPOSITE_NAMES}, "jobs": {k: {x: v.get(x) for x in ("job_id", "kind", "state", "op", "reason", "activation", "result", "error", "publication")}
                                                                                 for k, v in self.jobs.items()},
                "semantics": "wyniki modułów to cechy / surowe oceny / kontekst regułowy – nie prawdopodobieństwa skuteczności; COA/BChimp nie głosują"}

    def _detail(self, m: str, res: dict | None, c: Context | None) -> dict:
        if not res and m != "sdformerflow":
            return {}
        if m == "exponential_trend_channel":
            e = res.get("M5") or {}
            return {"state": e.get("state"), "channel": e.get("channel"), "parameter_version": res.get("parameter_version"), "schema": res.get("feature_schema_id")}
        if m == "g7_smc_radar":
            return {k: res.get(k) for k in ("rule_confluence_score", "components", "coverage", "reason", "conflict", "zones_active", "asymmetric_dxy_term")}
        if m == "cellular_feature_graph":
            return {"targets": res.get("targets"), "cells": res.get("cells"), "masked": res.get("masked"), "initialization": res.get("initialization")}
        if m == "sdformerflow":
            return dict((c.sdf or {}) if c else {})
        return {}

    def feature_graph(self, target: str = "BPC10") -> dict:
        c = self.ensure_main_context()
        if c is None or target not in c.graph:
            return {"edges": [], "reason": "brak kontekstu"}
        st = c.graph[target]
        return {"target": target, "version": st.version, "edges": st.top_edges(20), "nodes": GR.NAMES, "self_loops": False, "pending_labels": len(st.pending)}

    def optimizer_jobs(self) -> list[dict]:
        return self._read(self.base / "optimizer_jobs.json", [])[-50:]
