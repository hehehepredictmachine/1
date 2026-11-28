"""Shared framework of the 1.33 model families (PMW-FAM-1).

Every family implements the same adapter surface (capabilities / validate_config / data_requirements / validate_data / build_features
/ fit / evaluate / save / load / predict / health). Deterministic rules (breakout) and filters (Kalman) do not get a fake training
step: their `fit` is an ESTIMATION (Q/R by likelihood) or a VALIDATION of parameters, and `kind` says so.

Three independent state axes (never collapsed into one READY flag):
  implementation : AVAILABLE | MISSING_DEPENDENCY | NO_SOURCE | ERROR
  artifact       : NOT_TRAINED | TRAINING | CANDIDATE | VALIDATION_FAILED | APPROVED | INCOMPATIBLE | STALE
  use            : OFF | SHADOW | ASSIST      (ASSIST = analytical influence in the role the receiver defines)
New artifacts start as CANDIDATE with use SHADOW; training never activates or promotes. ASSIST requires an APPROVED artifact (its
promotion criteria passed on development data) and an explicit user action.

Artifact store: data/model_families/<family>/<instrument>/<run_id>/ with manifest.json (identity, unique run id, data hash and range,
splits, config, metrics + baseline + promotion criteria, dependency versions, seed, inference sample with tolerance, model card) and
the family's own payload files (statsmodels pickles, arch params, JSON, torch state dicts, joblib). Writes are atomic (tmp dir + rename);
activation re-runs the inference sample; rollback restores the previous active run. Pickle / joblib are loaded only from this
controlled directory (a checksum proves integrity, not trust).
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import shutil
import sys
import time
import threading
import uuid
from pathlib import Path

import numpy as np

from .. import contract as MC

VERSION = "PMW-FAM-1"
IMPL = ("AVAILABLE", "MISSING_DEPENDENCY", "NO_SOURCE", "ERROR")
ARTIFACT = ("NOT_TRAINED", "TRAINING", "CANDIDATE", "VALIDATION_FAILED", "APPROVED", "INCOMPATIBLE", "STALE")
USE = ("OFF", "SHADOW", "ASSIST")
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
# 1.46: one vocabulary for the data kind of an artifact. The marketdata Store writes REAL_USER_DATA / SYNTHETIC_TEST / UNKNOWN_SOURCE, the live
# bridge path MT5_LIVE_BRIDGE (real terminal) or SYNTHETIC_TEST (demo simulator); 1.45.0 compared only with 'REAL' / 'SYNTHETIC'.
_REAL_KINDS = {"REAL", "REAL_USER_DATA", "MT5_LIVE_BRIDGE"}
_SYNTH_KINDS = {"SYNTHETIC", "SYNTHETIC_TEST", "SYNTHETIC_DEMO", "SIMULATED"}
# 1.46 (I0400 / I0468): receivers of a family result that have a reader in the code - SH_CONTEXT (sh/service family_context, ASSIST hold),
# DECISION (decision/coordinator roles), QUANT (quant snapshot features), PANEL (/api/v1/families), MODELHUB (modelhub.adapters.all_predictions
# -> /api/v1/models, Quant), MM_BOARD (MM evidence board)
CONNECTED_RECEIVERS = ("SH_CONTEXT", "DECISION", "QUANT", "PANEL", "MODELHUB", "MM_BOARD")
PLANNED_NOTE = "niepodłączone w 1.46 – brak odbiorcy w kodzie (opis planu, nie ścieżka wyniku)"


def kind_class(data_kind) -> str | None:
    """'REAL' / 'SYNTHETIC' / None (unknown - never treated as real)."""
    k = str(data_kind or "").upper()
    return "REAL" if k in _REAL_KINDS else "SYNTHETIC" if k in _SYNTH_KINDS else None


class Unavailable(Exception):
    """A typed absence: predict() raises it with the reason; the adapter turns it into state BLOCKED_DATA / NOT_TRAINED / ..."""

    def __init__(self, state: str, reason: str):
        super().__init__(reason)
        self.state, self.reason = state, reason


class AssistGate(ValueError):
    """1.46 D5: a change of the active artifact refused because the family has the role ASSIST and the target does not pass
    Store.assist_ok. A ValueError, so the API (_fam) answers 409 as for set_use; nothing is written."""


def missing_deps(mods: tuple[str, ...]) -> list[str]:
    out = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception:  # noqa: BLE001
            out.append(m)
    return out


def dep_versions(mods: tuple[str, ...]) -> dict:
    out = {"python": sys.version.split()[0]}
    for m in ("numpy",) + tuple(mods):
        try:
            out[m] = getattr(importlib.import_module(m), "__version__", "?")
        except Exception:  # noqa: BLE001
            out[m] = None
    return out


def root() -> Path:
    from ...paths import data_dir
    r = Path(os.environ.get("PMW_FAMILIES_DIR") or (data_dir() / "model_families"))
    r.mkdir(parents=True, exist_ok=True)
    return r


def _atomic_json(p: Path, obj) -> None:
    # 1.42.10: unikalny plik tymczasowy na proces/wątek – stan zadania zapisują równolegle proces treningu i wątki bota
    # (wspólne „.json.tmp” dawało FileNotFoundError przy jednoczesnym zapisie).
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=_json_default), encoding="utf-8")
    for i in range(5):
        try:
            tmp.replace(p)
            return
        except PermissionError:                     # Windows: plik chwilowo otwarty do odczytu przez drugi proces
            if i == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (i + 1))


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _read(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def point_of(data: dict) -> float:
    """1.46: the symbol's point size from the training data spec. Missing / not positive -> BLOCKED_DATA (1.45.0 assumed 0.01: on a
    3-digit XAUUSD broker the spread cost of BREAKOUT / SEQ / RL_PPO was 10x too high)."""
    p = data.get("point")
    if not finite(p) or p <= 0:
        raise Unavailable("BLOCKED_DATA", "brak specyfikacji symbolu (rozmiar punktu) – koszt spreadu nie jest liczony na założonym punkcie; "
                                          "wyeksportuj historię z MT5 (manifest magazynu danych)")
    return float(p)


# ------------------------------------------------------------------ data helpers (one code path for training and runtime)
def bars_from_store(store, inst: str, tf: str, n: int | None = None) -> list[dict]:
    cols = store.read(inst, tf)
    t = cols["time"]
    if n:
        sl = slice(max(0, len(t) - n), len(t))
        cols = {k: v[sl] for k, v in cols.items()}
    return [{"t": int(cols["time"][i]), "o": float(cols["open"][i]), "h": float(cols["high"][i]), "l": float(cols["low"][i]),
             "c": float(cols["close"][i]), "tv": int(cols["tick_volume"][i]), "spread": int(cols["spread"][i])} for i in range(len(cols["time"]))]


def bars_from_bridge(rows: list[dict]) -> list[dict]:
    from ...indicators.contract import ts
    return [{"t": int(ts(b["open_utc"])), "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"]), "tv": int(b.get("tv") or 0),
             "spread": int(b.get("spread") or 0)} for b in rows if b.get("open_utc") and b.get("closed", True)]


def closes(bars: list[dict]) -> np.ndarray:
    return np.asarray([b["c"] for b in bars], dtype=float)


def data_hash(bars: list[dict]) -> str:
    h = hashlib.sha256()
    for b in bars:
        h.update(f"{b['t']}|{b['c']:.10g}|{b['h']:.10g}|{b['l']:.10g}".encode())
    return h.hexdigest()[:16]


def chrono_split(n: int, *, holdout_frac: float = 0.2, val_frac: float = 0.2, embargo: int = 0) -> dict:
    """train | (embargo) | validation (development) | (embargo) | holdout. Indices only; the holdout is evaluated ONCE at the end."""
    h0 = int(n * (1 - holdout_frac))
    v0 = int(h0 * (1 - val_frac))
    return {"train": (0, max(0, v0 - embargo)), "val": (v0, max(v0, h0 - embargo)), "holdout": (h0, n), "embargo": embargo, "n": n}


# ------------------------------------------------------------------ artifact store
class Store:
    def __init__(self, base: Path | None = None):
        self.base = Path(base) if base else root()

    def fam_dir(self, family: str, inst: str) -> Path:
        # 1.46: no path separators / '..' in a family or instrument segment (1.45.0: fid '..' wrote state.json outside model_families)
        for seg in (family, inst):
            if not isinstance(seg, str) or not NAME_RX.match(seg):
                raise KeyError("FAMILY_OR_INSTRUMENT_INVALID")
        d = self.base / family / inst
        d.mkdir(parents=True, exist_ok=True)
        return d

    OWNER = ".owner.json"                # 1.46: pid of the training process inside its .tmp-<run> dir (removed before commit)
    ORPHAN_LEGACY_S = 24 * 3600          # a .tmp-<run> without an owner file (1.45.0) counts as orphaned only after a day

    def new_run(self, family: str, inst: str) -> tuple[str, Path]:
        self.sweep_tmp(family, inst)
        rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
        tmp = self.fam_dir(family, inst) / (".tmp-" + rid)
        tmp.mkdir(parents=True, exist_ok=False)
        _atomic_json(tmp / self.OWNER, {"pid": os.getpid(), "created_at": time.time()})
        return rid, tmp

    def sweep_tmp(self, family: str, inst: str) -> list[str]:
        """1.46: .tmp-<run> dirs of a training that never finished (cancel = terminate, crash, out of memory, app closed) stayed forever -
        SEQ left its whole dataset there (seq_data.npz, up to ~200 MB). An unfinished run is never an artifact (runs() skips it, nothing
        loads it); it is removed only when its owner process is no longer alive (a running training keeps its directory)."""
        from ...training.core import _pid_alive
        removed = []
        for p in self.fam_dir(family, inst).glob(".tmp-*"):
            if not p.is_dir():
                continue
            own = _read(p / self.OWNER, None)
            if isinstance(own, dict):
                try:
                    alive = _pid_alive(int(own.get("pid") or 0))
                except (TypeError, ValueError, OSError):
                    alive = True                                     # unknown -> keep
                if alive:
                    continue
            else:
                try:
                    if time.time() - p.stat().st_mtime < self.ORPHAN_LEGACY_S:
                        continue
                except OSError:
                    continue
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name)
        return removed

    def commit(self, family: str, inst: str, rid: str, tmp: Path, manifest: dict) -> Path:
        (tmp / self.OWNER).unlink(missing_ok=True)                   # 1.46: the owner marker is not a part of the artifact
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tmp.iterdir()) if p.is_file()}
        manifest = dict(manifest, files=files, run_id=rid, family=family, instrument=inst, framework=VERSION, created_at=time.time())
        _atomic_json(tmp / "manifest.json", manifest)
        final = self.fam_dir(family, inst) / rid
        tmp.replace(final)
        return final

    def runs(self, family: str, inst: str) -> list[dict]:
        d = self.fam_dir(family, inst)
        out = []
        for p in sorted(d.iterdir()):
            if p.is_dir() and not p.name.startswith(".tmp-"):
                m = _read(p / "manifest.json")
                if m:
                    out.append(m)
        return sorted(out, key=lambda m: m.get("created_at") or 0)

    def run_dir(self, family: str, inst: str, rid: str) -> Path:
        return self.fam_dir(family, inst) / rid

    def verify(self, family: str, inst: str, rid: str) -> tuple[bool, str | None]:
        d = self.run_dir(family, inst, rid)
        m = _read(d / "manifest.json")
        if not m:
            return False, "brak manifest.json"
        for name, h in (m.get("files") or {}).items():
            p = d / name
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
                return False, f"suma kontrolna {name} niezgodna"
        return True, None

    # ---- state (active run + use role)
    def _state_path(self, family: str, inst: str) -> Path:
        return self.fam_dir(family, inst) / "state.json"

    def state(self, family: str, inst: str) -> dict:
        return _read(self._state_path(family, inst), None) or {"active": None, "use": "OFF", "history": []}

    def _save_state(self, family: str, inst: str, st: dict) -> None:
        _atomic_json(self._state_path(family, inst), st)

    def assist_guard(self, family: str, inst: str, rid: str | None, what: str, st: dict | None = None) -> None:
        """1.46 D5: the ASSIST gate also on a change of the active artifact (it was checked only in set_use - activate / rollback left
        ASSIST on an artifact without APPROVED or not on REAL data, or on no artifact). At the role ASSIST the target `rid` must pass
        assist_ok, else AssistGate and no state write. Tightening only: the role is never lowered here and a state saved earlier is left
        as it is (nothing lifts the holds of the approved artifact); the user sets SHADOW first."""
        st = self.state(family, inst) if st is None else st
        if st.get("use") != "ASSIST":
            return
        ok, why = self.assist_ok(family, inst, rid)
        if not ok:
            raise AssistGate(f"ASSIST_GATE: {what} odrzucone przy roli ASSIST – {why}. Najpierw ustaw rolę SHADOW (albo OFF).")

    def set_active(self, family: str, inst: str, rid: str | None, why: str) -> dict:
        st = self.state(family, inst)
        self.assist_guard(family, inst, rid, f"aktywowanie artefaktu {rid}" if rid else "dezaktywowanie artefaktu", st)
        st["history"] = (st.get("history") or [])[-50:] + [{"at": time.time(), "action": "ACTIVATE" if rid else "DEACTIVATE", "run_id": rid,
                                                             "previous": st.get("active"), "reason": why}]
        st["active"] = rid
        if rid and st.get("use") == "OFF":
            st["use"] = "SHADOW"                                     # a newly activated artifact starts observing, never influencing
        self._save_state(family, inst, st)
        return st

    def assist_ok(self, family: str, inst: str, rid: str | None) -> tuple[bool, str | None]:
        """1.46: THE ASSIST gate (one place): an active artifact with validation APPROVED, trained on data verified as REAL."""
        m = _read(self.run_dir(family, inst, rid) / "manifest.json") if rid else None
        if not m or (m.get("validation") or {}).get("status") != "APPROVED":
            return False, "ASSIST wymaga aktywnego artefaktu ze statusem APPROVED (kryteria promocji spełnione na danych rozwojowych)"
        if kind_class(m.get("data_kind")) != "REAL":
            return False, f"artefakt na danych {m.get('data_kind') or 'NIEZNANYCH'} (nie REAL) nie uzyskuje roli ASSIST"
        return True, None

    def rollback(self, family: str, inst: str) -> dict:
        st = self.state(family, inst)
        acts = [h for h in st.get("history") or [] if h["action"] == "ACTIVATE"]
        prev = acts[-1]["previous"] if acts and acts[-1]["run_id"] == st.get("active") else None
        self.assist_guard(family, inst, prev, f"cofnięcie do artefaktu {prev}" if prev else "cofnięcie do braku artefaktu", st)
        st["history"].append({"at": time.time(), "action": "ROLLBACK", "run_id": prev, "previous": st.get("active")})
        st["active"] = prev
        self._save_state(family, inst, st)
        return st

    def set_use(self, family: str, inst: str, use: str) -> dict:
        if use not in USE:
            raise ValueError(f"USE_INVALID:{use}")
        st = self.state(family, inst)
        if use == "ASSIST":
            ok, why = self.assist_ok(family, inst, st.get("active"))     # 1.46: allowlist REAL (1.45.0 refused only the literal 'SYNTHETIC')
            if not ok:
                raise ValueError(why)
        st["use"] = use
        st.setdefault("history", []).append({"at": time.time(), "action": "USE", "use": use})
        self._save_state(family, inst, st)
        return st

    def remove(self, family: str, inst: str, rid: str) -> None:
        if self.state(family, inst).get("active") == rid:
            raise ValueError("nie można usunąć aktywnego artefaktu")
        shutil.rmtree(self.run_dir(family, inst, rid), ignore_errors=True)


# ------------------------------------------------------------------ adapter base
class Family:
    ID = "?"
    NAME = "?"
    KIND = "TRAINED"                 # TRAINED | ESTIMATED | VALIDATED_RULES | MEASUREMENT | PRETRAINED_ADAPTER
    TASK_TYPE = "REGRESSION"
    UNIT = "log_return"
    TASK = "?"
    DEPS: tuple[str, ...] = ()
    RUNTIME = "MAIN"                 # MAIN = bot process (outside the MT5 thread) | DEEP = .venv_deep worker process
    TF = "M5"
    HORIZONS = (1,)
    # 1.46 (I0400 / I0468): RECEIVERS = only receivers with a reader in the code (prefix in CONNECTED_RECEIVERS); a declared but unconnected
    # one (agent context, risk, strategy, portfolio - nothing in agent/ risk/ strategies/ engine/ baskets/ reads a family result) is listed
    # in PLANNED_RECEIVERS and shown apart (capabilities 'planned_receivers'), never as a receiver of the record / model card
    RECEIVERS: tuple[str, ...] = ()
    PLANNED_RECEIVERS: tuple[str, ...] = ()
    DATA = {"kind": "BARS", "tf": "M5", "min_bars": 500}
    FIT_LABEL = "trening"
    NEEDS_POINT = False              # 1.46: True = fit converts the bar spread (points) to price - the symbol's point size must be known

    def capabilities(self) -> dict:
        return {"id": self.ID, "name": self.NAME, "kind": self.KIND, "task_type": self.TASK_TYPE, "unit": self.UNIT, "task": self.TASK,
                "runtime": self.RUNTIME, "deps": list(self.DEPS), "tf": self.TF, "horizons": list(self.HORIZONS), "receivers": list(self.RECEIVERS),
                "planned_receivers": list(self.PLANNED_RECEIVERS), "planned_receivers_note": PLANNED_NOTE if self.PLANNED_RECEIVERS else None,
                "fit_label": self.FIT_LABEL, "data": self.DATA}

    def data_requirements(self) -> dict:
        return dict(self.DATA)

    def validate_config(self, cfg: dict) -> dict:
        return dict(cfg or {})

    def implementation(self) -> tuple[str, str | None]:
        if self.RUNTIME == "DEEP":
            from . import deep
            ok, why = deep.available(self.DEPS)
            return ("AVAILABLE", None) if ok else ("MISSING_DEPENDENCY", why)
        miss = missing_deps(self.DEPS)
        return ("AVAILABLE", None) if not miss else ("MISSING_DEPENDENCY", "brak bibliotek: " + ", ".join(miss))

    def validate_data(self, data: dict) -> tuple[bool, str | None]:
        bars = data.get("bars") or []
        need = int(self.DATA.get("min_bars", 0))
        if len(bars) < need:
            return False, f"za mało świec {self.TF}: {len(bars)} < {need}"
        c = closes(bars)
        if not np.all(np.isfinite(c)) or np.any(c <= 0):
            return False, "ceny nieskończone lub niedodatnie"
        t = np.asarray([b["t"] for b in bars])
        if np.any(np.diff(t) <= 0):
            return False, "czas niemonotoniczny / duplikaty"
        if self.NEEDS_POINT:
            try:
                point_of(data)
            except Unavailable as u:
                return False, u.reason
        return True, None

    # to implement
    def fit(self, data: dict, cfg: dict, tmp: Path, budget: dict) -> dict:  # returns manifest parts (metrics, validation, sample, ...)
        raise NotImplementedError

    def load(self, d: Path) -> dict:
        raise NotImplementedError

    def predict(self, art: dict, live: dict) -> dict:
        raise NotImplementedError

    # helpers
    def promotion(self, metrics: dict, criteria: dict) -> dict:
        """criteria: {metric: ('<'|'>', threshold)} evaluated on DEVELOPMENT (validation) metrics only - never the holdout."""
        res, ok = [], True
        for k, (op, thr) in criteria.items():
            v = metrics.get(k)
            passed = finite(v) and ((v < thr) if op == "<" else (v > thr))
            ok &= passed
            res.append({"metric": k, "op": op, "threshold": thr, "value": v, "passed": bool(passed)})
        return {"status": "APPROVED" if ok else "VALIDATION_FAILED", "criteria": res, "evaluated_on": "development (validation) only"}

    def pred(self, *, inst: str, symbol: str | None, state: str, result=None, reason: str | None = None, run_id: str | None = None,
             horizon_bars: int | None = None, horizon_seconds: int | None = None, data_time=None, data_kind: str | None = None,
             calibration: dict | None = None, extra: dict | None = None, unit: str | None = None, task_type: str | None = None,
             available_at=None, ttl_s: float | None = None) -> dict:
        from ...indicators.contract import iso
        tt = task_type or self.TASK_TYPE
        hb = horizon_bars if horizon_bars is not None else (self.HORIZONS[0] if tt in MC.FORECAST_TASKS else None)
        return MC.make(instrument=inst, symbol=symbol, timeframe=self.TF, model_name=self.ID, model_version=run_id, task_type=tt, task=self.TASK,
                       horizon_bars=hb, horizon_seconds=horizon_seconds, unit=unit or self.UNIT, state=state, result=result,
                       data_time=iso(data_time) if isinstance(data_time, (int, float)) else data_time, run_id=run_id, source=f"family:{self.ID}",
                       data_kind=data_kind, calibration=calibration, unavailable_reason=reason, ttl_s=ttl_s,
                       available_at=iso(available_at) if isinstance(available_at, (int, float)) else available_at,
                       extra={"family": self.ID, "kind": self.KIND, "receivers": list(self.RECEIVERS), **(extra or {})})
