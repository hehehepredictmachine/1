"""1.41 TabICLv2 confidence estimator of the Quant layer (estimator kind `tabicl_v2`; `legacy_logistic` artifacts are untouched).

What it is: the official pretrained TabICLv2 classifier (tabicl 2.2.0, checkpoint tabicl-classifier-v2-20260212.ckpt) answering
predict_proba for ONE concrete candidate, given a labelled REFERENCE CONTEXT of earlier candidates of the same event definition.
No gradient training, no pretraining, no fine-tuning: "fit" = TabICL's in-context fit on the reference rows.

Event definition (context key) = instrument | event_id (e.g. TP2_BEFORE_STOP) | label version | ambiguity policy | BE rule | timeout rule.
Strategies with the same event definition share a context; the strategy / engine identity is a FEATURE and stays in every record.
TP1, TP2, NET_R_POSITIVE, next-bar direction are different events and are never mixed.

Reference rows (chronological, deterministic, natural class proportions, newest first up to the RAM limits 512 target / 1024 max):
  1. LIVE_LEDGER  - matured, labelled rows of quant/ledger.sqlite (the label was known: resolve_ts <= now);
  2. RECONSTRUCTED_HISTORY - when the ledger has too few rows: historical candidates of the SAME live detectors (SH pack v2 replay,
     plans_only) on closed M1 history, features computed only from what was known at the decision (models had no forecast then ->
     their columns are missing = NaN mask, never today's forecast), labelled by quant.events.simulate (SL_FIRST, the live policy).
Nothing is synthesised: no labels, no wins, no fill-ins. Without either source the estimator says so (NO_CONTEXT) and the rest works.

Output: p_event_raw for the candidate's event and confidence_score = 100 x p_event_raw, calibration UNCALIBRATED (raw model estimate,
NOT a measured win rate); no fixed bonus, no 50 % for a missing model, no minimum. Published asynchronously keyed by plan_hash: a late
answer never becomes the answer of another plan / generation and never rewrites an old decision.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .. import paths
from . import events as EV
from . import features as F

log = logging.getLogger(__name__)
VERSION = "PMW-QUANT-TABICL-1"
MAX_COLUMNS = 48
MIN_ROWS = 24                      # technical minimum for an in-context classifier (both classes needed) - NOT a validation gate
RESULTS_MAX = 500                  # plan_hash -> newest results kept in memory
# 1.46: one vocabulary for the quant ledger (REAL / SYNTHETIC / UNKNOWN) and the market-data store (REAL_USER_DATA / SYNTHETIC_TEST /
# UNKNOWN_SOURCE); anything else or missing = UNKNOWN (never assumed REAL)
_KINDS = {"REAL": "REAL", "REAL_USER_DATA": "REAL", "SYNTHETIC": "SYNTHETIC", "SYNTHETIC_TEST": "SYNTHETIC"}


def kind_of(x) -> str:
    return _KINDS.get(str(x or "").upper(), "UNKNOWN")


def _pos(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def event_key(spec: EV.EventSpec) -> str:
    return "|".join(str(x) for x in (spec.instrument, spec.event_id, spec.label_version, spec.ambiguity, spec.be_after, spec.timeout_rule))


def tdir() -> Path:
    p = paths.data_dir() / "quant" / "tabicl"
    p.mkdir(parents=True, exist_ok=True)
    return p


def weights_root() -> Path:
    from ..tsfm.settings import default_weights_root
    return default_weights_root()


def find_python() -> str | None:
    # 1.46 arch (I0117): MQ_TABICL_PYTHON -> .venv_tabicl (is_file), as before
    from .. import runtimes
    return runtimes.find_python("tabicl")


_INST_CACHE: dict = {}     # process cache (TTL max_age_s) of installed(); reset_install_cache() is the hook (1.46 arch I0104)


def reset_install_cache() -> None:
    """Forget the cached installation state (tests; after an install / removal of the TabICL environment)."""
    _INST_CACHE.clear()


def installed(max_age_s: float = 300.0) -> dict:
    """Cached (the checkpoint SHA-256 of 110 MB is not recomputed on every status poll; the worker verifies it again at load)."""
    hit = _INST_CACHE.get("v")
    if hit and time.time() - hit[0] < max_age_s:
        return hit[1]
    r = _installed()
    _INST_CACHE["v"] = (time.time(), r)
    return r


def _installed() -> dict:
    try:
        bp = str(paths.ROOT_DIR / "backend")
        if bp not in sys.path:                     # 1.46: was inserted on every cache miss (sys.path grew ~288 entries a day)
            sys.path.insert(0, bp)
        from tabicl_runtime import install as TI
        v = TI.verify(weights_root())
        return {"weights": v["ok"], "problems": v["problems"], "python": find_python()}
    except Exception as exc:  # noqa: BLE001
        return {"weights": False, "problems": [f"{type(exc).__name__}: {exc}"[:200]], "python": find_python()}


# ---------------------------------------------------------------------------------------------------------------- reference rows
def strategy_features(engine: str | None, strategy: str | None) -> dict:
    """Provenance of the row as features (the identity stays in the record): engine one-hot is already in FEAT-1; the strategy id becomes
    a stable small integer code + family flags so different rules are not merged silently."""
    s = str(strategy or "")
    return {"ctx:strategy_code": float(int(hashlib.sha256(s.encode()).hexdigest()[:4], 16) % 997),
            "ctx:family_hedging": 1.0 if "HG" in s or "HEDG" in s.upper() else 0.0}


def _current(r: dict) -> bool:
    """A ledger row of the CURRENT feature semantics (QuantLedger.training_rows names the version of every row; LEGACY_ROWS = pre-1.46)."""
    return r.get("feature_version", F.CURRENT) == F.CURRENT


def live_rows(ledger, inst: str, key: str, now: float, *, real_only: bool = False) -> list[dict]:
    """now = the as-of time (the candidate's decision): only rows whose label was resolved by then. real_only: REAL rows only.
    1.46: rows of the CURRENT feature semantics only (features.CURRENT, as the candidate's features from QuantService.assess) - a
    pre-1.46 row (LEGACY_ROWS) has the same column names with another meaning (Kalman candidate, stale DXY)."""
    out = []
    for r in ledger.training_rows(inst):
        if not _current(r):
            continue
        if real_only and kind_of(r.get("data_kind")) != "REAL":
            continue                                   # 1.46: a REAL candidate never gets SYNTHETIC / UNKNOWN reference rows
        try:
            spec = EV.EventSpec(**{k: (tuple(map(tuple, v)) if k == "targets" else v) for k, v in r["spec"].items() if k not in ("task_hash", "plan_hash")})
        except Exception:  # noqa: BLE001
            continue
        if event_key(spec) != key or r.get("resolve_ts") is None or float(r["resolve_ts"]) > now or r.get("y") is None:
            continue
        f = dict(r["features"])
        f.update(strategy_features(None, spec.strategy))
        out.append({"id": r["row_id"], "decision_ts": float(r["decision_ts"]), "resolve_ts": float(r["resolve_ts"]), "y": int(r["y"]),
                    "features": f, "strategy": spec.strategy, "provenance": "LIVE_LEDGER", "data_kind": r.get("data_kind")})
    return out


def recon_path(inst: str) -> Path:
    return tdir() / f"reconstructed_{inst}.jsonl"


def recon_rows(inst: str, key: str, now: float, *, real_only: bool = False) -> list[dict]:
    p = recon_path(inst)
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as fh:
        for ln in fh:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if real_only and kind_of(r.get("data_kind")) != "REAL":
                continue                               # 1.46: same data-kind rule as the live ledger rows
            if r.get("event_key") == key and r.get("resolve_ts") is not None and float(r["resolve_ts"]) <= now and r.get("y") in (0, 1):
                out.append(r)
    return out


def select(rows: list[dict], target: int, cap: int) -> list[dict]:
    """Deterministic: newest first (by decision time, then id), natural class proportions, no oversampling; duplicates by id dropped."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (-float(r["decision_ts"]), str(r["id"]))):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
        if len(out) >= min(target, cap):
            break
    return sorted(out, key=lambda r: (float(r["decision_ts"]), str(r["id"])))


def columns(rows: list[dict], max_cols: int = MAX_COLUMNS) -> list[str]:
    cnt: dict[str, int] = {}
    for r in rows:
        for k in r["features"]:
            if not k.startswith("m:"):
                cnt[k] = cnt.get(k, 0) + 1
    min_n = max(1, int(0.05 * len(rows)))
    names = sorted((k for k, n in cnt.items() if n >= min_n), key=lambda k: (-cnt[k], k))[:max_cols]
    return sorted(names)


def vector(feats: dict, names: list[str]) -> list[float]:
    out = []
    for n in names:
        v = feats.get(n)
        out.append(float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else float("nan"))
    return out


def build_context(ledger, inst: str, key: str, now: float, *, target: int = 512, cap: int = 1024, real_only: bool = False) -> dict:
    """now = as-of time (1.46: the candidate's decision time, never the wall clock of the scoring - no look-ahead)."""
    live = live_rows(ledger, inst, key, now, real_only=real_only)
    recon = recon_rows(inst, key, now, real_only=real_only) if len(live) < target else []
    rows = select(live + recon, target, cap)
    names = columns(rows)
    ys = [int(r["y"]) for r in rows]
    cid = hashlib.sha256(json.dumps([key, names, [(r["id"], r["y"]) for r in rows]], sort_keys=True).encode()).hexdigest()[:16]
    prov = {"LIVE_LEDGER": sum(1 for r in rows if r["provenance"] == "LIVE_LEDGER"),
            "RECONSTRUCTED_HISTORY": sum(1 for r in rows if r["provenance"] == "RECONSTRUCTED_HISTORY")}
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[kind_of(r.get("data_kind"))] = kinds.get(kind_of(r.get("data_kind")), 0) + 1
    return {"context_id": cid, "event_key": key, "instrument": inst, "names": names, "feature_schema": F.schema2(names), "n": len(rows),
            "positives": sum(ys), "classes": sorted(set(ys)), "provenance": prov, "first_ts": rows[0]["decision_ts"] if rows else None,
            "last_ts": rows[-1]["decision_ts"] if rows else None, "X": [vector(r["features"], names) for r in rows], "y": ys,
            "row_ids": [r["id"] for r in rows], "built_at": time.time(),
            # 1.46 (additive): as-of time, data kinds of the rows, REAL-only filter, labelled live rows of this event before selection
            "as_of": now, "data_kinds": kinds, "real_only": real_only, "live_rows": len(live)}


# ---------------------------------------------------------------------------------------------------------------- reconstruction
def store_bars(inst: str, days: int) -> tuple[dict, dict] | dict | None:
    """M1 closed history of the market-data store -> the replay format (SH pack features). None = no history.
    1.46: point / tick size = the broker's symbol_info written by the export into the store manifest (symbol_spec, costs.spread.point;
    the instrument profile only if it ever declares them) - without it {"ok": False, "code": "NO_SPEC"}, never an assumed 0.01;
    data_kind from the manifest (missing = UNKNOWN_SOURCE, never relabelled REAL_USER_DATA)."""
    from ..marketdata.store import Store
    st = Store()
    last = st.last_time(inst, "M1")
    if last is None:
        return None
    d = st.read(inst, "M1", start=last - days * 86400)
    if len(d.get("time") or []) < 3000:
        return None
    man = st.manifest(inst) or {}
    sspec = man.get("symbol_spec") or {}
    point = _pos(sspec.get("point")) or _pos(((man.get("costs") or {}).get("spread") or {}).get("point"))
    if point is None:
        try:
            prof = json.loads((paths.ROOT_DIR / "config" / "instruments_v1.json").read_text(encoding="utf-8"))["instruments"][inst]
            point = _pos(prof.get("point")) or _pos(prof.get("tick_size"))
        except Exception:  # noqa: BLE001
            point = None
    if point is None:
        return {"ok": False, "code": "NO_SPEC", "reason": f"brak rozmiaru punktu {inst} (symbol_spec w manifeście magazynu danych) – "
                                                          "wyeksportuj historię z MT5 ponownie; spread nie jest przeliczany na założonym punkcie"}
    tick = _pos(sspec.get("trade_tick_size")) or point
    from datetime import datetime, timezone
    m1 = [{"open_utc": datetime.fromtimestamp(int(t), timezone.utc).isoformat().replace("+00:00", "Z"), "o": float(o), "h": float(h), "l": float(l_),
           "c": float(c), "tv": float(tv or 0), "spread_price": (float(sp) * point if sp not in (None, "") else None), "closed": True}
          for t, o, h, l_, c, tv, sp in zip(d["time"], d["open"], d["high"], d["low"], d["close"], d["tick_volume"], d["spread"])]
    from ..sh.pack import replay as RP
    bars = {"M1": m1}
    for tf in ("M3", "M5", "M15", "H1"):
        bars[tf] = RP.aggregate(m1, RP.TF_S[tf])
    meta = {"instrument": inst, "symbol": inst, "data_kind": man.get("data_kind") or "UNKNOWN_SOURCE", "spec": {"point": point, "trade_tick_size": tick},
            "tf_sources": {"M1": "NATIVE"}}
    return bars, meta


def reconstruct(inst: str, *, days: int = 30, cancel=None, progress=None, bars_meta: tuple | None = None) -> dict:
    """Historical candidates of the live SH pack detectors (causal replay, plans only) labelled with the live EventSpec simulator.
    Written to reconstructed_<inst>.jsonl (provenance RECONSTRUCTED_HISTORY). Idempotent: rows are keyed by (variant, tf, t, side)."""
    from ..sh.pack import replay as RP
    bm = bars_meta or store_bars(inst, days)
    if bm is None:
        return {"ok": False, "code": "NO_HISTORY", "reason": f"brak zamkniętej historii M1 {inst} w magazynie danych (min. ~3000 świec)"}
    if isinstance(bm, dict):
        return bm                                          # 1.46: NO_SPEC (point size unknown) - nothing reconstructed on a guess
    bars, meta = bm
    from ..sh.pack.features import ts as _ts
    m1 = [{"t": _ts(b["open_utc"]), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "spread_price": b.get("spread_price")} for b in bars["M1"]]
    last_close = m1[-1]["t"] + 60
    rows = []

    def on_ready(t, vid, tf, su):
        side = "LONG" if su.get("side") == "BUY" else "SHORT"
        tps = su.get("tps") or []
        if len(tps) < 2 or su.get("sl") is None or su.get("entry_ref") is None:
            return
        fam = "SH_HEDGING" if vid.startswith("PMW_HG") else "SH_SCALPING"
        cd = {"instrument": inst, "engine": fam, "strategy_id": vid, "direction": side, "entry_price": float(su["entry_ref"]),
              "stop_loss": float(su["sl"]), "targets": [{"price": float(x["price"]), "weight": float(x["share"])} for x in tps],
              "horizon_s": 60.0 * float(su.get("position_max_minutes") or su.get("horizon_minutes") or 60), "decision_ts": float(t),
              "score": (su.get("score") or {}).get("value"), "entry_type": "MARKET",
              "execution_context": {"cost_price": (su.get("costs") or {}).get("round_trip_price"),
                                    "commission_known": (su.get("costs") or {}).get("commission_known")},
              "features": {"atr_m5": ((su.get("pack") or {}).get("features") or {}).get("atr_m5")}}
        try:
            spec = EV.spec_from_candidate(cd)
        except (EV.EventError, KeyError, TypeError, ValueError):
            return
        rows.append((cd, spec, tf))

    RP.run(bars, meta, on_ready=on_ready, plans_only=True, cancel=cancel, progress=progress)
    if cancel is not None and cancel():
        # 1.46: an interrupted replay covers only part of the history - the previous complete file stays (no partial overwrite and no
        # fresh mtime that would block the next automatic reconstruction for 24 h)
        return {"ok": False, "code": "CANCELLED", "reason": "rekonstrukcja przerwana (zamykanie) – poprzedni plik kontekstu bez zmian",
                "candidates": len(rows)}
    out, n_lab = [], 0
    for cd, spec, tf in rows:
        lab = EV.simulate(spec, m1, cd["decision_ts"], available_until=last_close)
        if not lab.get("mature") or lab.get("y_event") is None:
            continue                                       # unfinished / no bars: not a loss, simply not a reference row
        fills = lab.get("fills") or []
        resolve = max([float(f["t"]) + 60 for f in fills] or [cd["decision_ts"] + spec.horizon_s])
        feats = F.build2(cd, [])                           # no historical model forecast existed -> those columns are missing
        feats.update(strategy_features(cd["engine"], spec.strategy))
        # 1.46: the TF is part of the id - a variant with several signal TFs can publish two different plans at the same t
        # (the same id made select() drop one of them silently)
        out.append({"id": f"R:{cd['strategy_id']}:{tf}:{int(cd['decision_ts'])}:{cd['direction']}", "tf": tf, "decision_ts": cd["decision_ts"], "resolve_ts": resolve,
                    "y": int(lab["y_event"]), "features": feats, "strategy": spec.strategy, "event_key": event_key(spec), "task_hash": spec.task_hash(),
                    "provenance": "RECONSTRUCTED_HISTORY", "data_kind": meta.get("data_kind")})
        n_lab += 1
    p = recon_path(inst)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r) + "\n")
    tmp.replace(p)
    keys: dict[str, int] = {}
    for r in out:
        keys[r["event_key"]] = keys.get(r["event_key"], 0) + 1
    return {"ok": True, "candidates": len(rows), "labelled": n_lab, "event_keys": keys, "first": bars["M1"][0]["open_utc"], "last": bars["M1"][-1]["open_utc"],
            "source": "marketdata store M1 + SH pack v2 detectors (plans_only) + quant.events.simulate"}


# ---------------------------------------------------------------------------------------------------------------- worker client
class Worker:
    """One .venv_tabicl process (JSON lines). A request that exceeds its timeout KILLS the process (a Python future cannot stop a
    running inference); the next request restarts it, with a bounded backoff.
    1.46: the Memory Governor (another thread) releases it through kill(), which never kills a request in flight: every call - and a
    whole scoring session load + fit + predict - holds the lock and counts as busy; while busy the idle time is 0."""

    def __init__(self, svc):
        self.svc = svc
        self.proc: subprocess.Popen | None = None
        self.lock = threading.RLock()                  # 1.46: re-entrant - session() holds it across the calls of one scoring
        self.loaded_ctx: str | None = None
        self.info: dict | None = None
        self.state, self.reason = "STOPPED", None
        self.restarts, self.retry_at = 0, 0.0
        self._busy = 0
        self._last_used = time.monotonic()
        self._n = 0

    @property
    def busy(self) -> bool:
        return self._busy > 0

    @property
    def last_used(self) -> float:
        """1.46: monotonic time of the last use; NOW while a request runs (runtime.py: governor idle = monotonic() - last_used was growing
        through a 300 s load / fit, and the process was released mid-request -> false TIMEOUT, restarts, backoff)."""
        return time.monotonic() if self._busy else self._last_used

    @last_used.setter
    def last_used(self, v: float) -> None:
        self._last_used = float(v)

    @contextmanager
    def session(self):
        with self.lock:
            self._busy += 1
            self._last_used = time.monotonic()
            try:
                yield self
            finally:
                self._busy -= 1
                self._last_used = time.monotonic()

    def _spawn(self) -> None:
        py = find_python()
        if not py:
            raise RuntimeError("NOT_INSTALLED: brak środowiska .venv_tabicl (instalacja: 41_AI_TABICL_TIREX_INSTALUJ.bat)")
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", PYTHONUTF8="1", HF_HUB_OFFLINE="1",
                   PYTHONNOUSERSITE="1")
        env.pop("PYTHONHOME", None)
        self.proc = subprocess.Popen([py, "-m", "tabicl_runtime.worker"], cwd=str(paths.ROOT_DIR / "backend"), env=env, text=True, encoding="utf-8",
                                     errors="replace", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.loaded_ctx, self.info = None, None
        self._last_used = time.monotonic()             # 1.46: a fresh process is not "idle since the previous one"

    def _kill(self) -> bool:
        p = self.proc
        self.proc, self.loaded_ctx, self.info = None, None, None
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass
            return True
        return False

    def kill(self, force: bool = False) -> bool:
        """Governor release / shutdown. 1.46: without force the lock is taken WITHOUT waiting and a busy worker (load / fit / predict in
        flight, possibly in another thread) is left alone -> False; force=True (shutdown) kills at once."""
        if force:
            return self._kill()
        if not self.lock.acquire(blocking=False):
            return False
        try:
            return False if self._busy else self._kill()
        finally:
            self.lock.release()

    def _fail(self, msg: str):
        self._kill()
        self.restarts += 1
        self.retry_at = time.monotonic() + min(300.0, 15.0 * self.restarts)
        self.reason = msg                              # 1.46: shown by WORKER_BACKOFF (was always None)
        raise RuntimeError(msg)

    def call(self, req: dict, timeout: float, *, spawn: bool = True) -> dict:
        with self.session():
            if self.proc is None or self.proc.poll() is not None:
                if not spawn:
                    raise RuntimeError("WORKER_EXITED: proces TabICL nie działa")
                if time.monotonic() < self.retry_at:
                    raise RuntimeError(f"WORKER_BACKOFF: {self.reason}")
                self._spawn()
            p = self.proc                              # 1.46: local handle (a forced kill sets self.proc = None mid-call)
            self._n += 1
            req = {**req, "id": self._n}
            out: dict = {}

            def rd():
                try:
                    out["line"] = p.stdout.readline()
                except Exception as exc:  # noqa: BLE001
                    out["err"] = str(exc)
            th = threading.Thread(target=rd, daemon=True)
            try:
                p.stdin.write(json.dumps(req) + "\n")
                p.stdin.flush()
            except (OSError, ValueError) as exc:
                self._fail(f"WORKER_EXITED: proces TabICL zakończył się ({type(exc).__name__})")
            th.start()
            th.join(timeout)
            if th.is_alive():
                self._fail(f"TIMEOUT: brak odpowiedzi w {timeout:.0f} s – proces zatrzymany")
            if not out.get("line"):
                # 1.46: EOF = the process ended (crash / killed from outside) - not a timeout
                self._fail("WORKER_EXITED: proces TabICL zakończył się bez odpowiedzi")
            r = json.loads(out["line"])
            if not r.get("ok"):
                raise RuntimeError(f"{r.get('code')}: {r.get('error')}")
            return r


class TabICLService:
    def __init__(self, qsvc):
        self.q = qsvc
        self.worker = Worker(self)
        self.jobs: "queue.Queue" = queue.Queue(maxsize=16)
        self.results: dict[str, dict] = {}                 # plan_hash -> result (newest RESULTS_MAX, written only by _put_result)
        self._res_lock = threading.Lock()
        self.contexts: dict[str, dict] = {}                # event_key -> context summary (without X / y)
        self.recon = {"state": "IDLE", "result": None, "started_at": None}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.governor = None
        self._ctx_cache: dict[str, tuple[float, dict]] = {}   # event_key#REAL|ANY -> (as_of, context)
        self._live_n: dict[str, int] = {}                   # 1.46: event_key -> labelled live rows at the last context build
        self._recon_keys: dict[str, set] = {}               # 1.46: instrument -> event keys the last reconstruction produced
        self._recon_check_at = 0.0

    def settings(self) -> dict:
        return (self.q.settings.get().get("tabicl") or {})

    def register_with(self, governor) -> None:
        """1.46 arch (I0089/I0102): register the TabICL worker with the Memory Governor (heavy slot, idle release) - was a lambda on
        worker.proc / jobs / worker.last_used in runtime._wire_governor. Same callables, evaluated lazily; never released while a job
        waits in the queue."""
        import time as _time
        governor.register("tabicl", "heavy", lambda: self.worker.proc.pid if (self.worker.proc and self.worker.proc.poll() is None) else None,
                          release=lambda: self.jobs.empty() and self.worker.kill(), idle=lambda: _time.monotonic() - self.worker.last_used)

    def active(self) -> bool:
        s = self.q.settings.get()
        return s.get("estimator") == "tabicl_v2" and bool((s.get("tabicl") or {}).get("enabled", True))

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="quant-tabicl", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass
        # 1.46: 'quit' only to a process that RUNS (none is spawned just to be quit) and no waiting behind an in-flight load / fit (up to
        # 300 s): after 1 s it is killed, so the rest of Runtime.stop() still runs inside the desktop's shutdown window
        w = self.worker
        if w.lock.acquire(timeout=1.0):
            try:
                p = w.proc
                if p is not None and p.poll() is None:
                    try:
                        w.call({"cmd": "quit"}, 5, spawn=False)
                        p.wait(2)
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                w.lock.release()
        w.kill(force=True)

    def _put_result(self, plan_hash: str, r: dict) -> dict:
        """1.46: every state (QUEUED, DROPPED_STALE, ERROR, NOT_INSTALLED, NO_CONTEXT, READY) is stored here and only the newest RESULTS_MAX
        are kept (was trimmed after READY only - without TabICL installed the dict grew with every new plan_hash)."""
        with self._res_lock:
            self.results.pop(plan_hash, None)          # re-inserted = newest
            self.results[plan_hash] = r
            while len(self.results) > RESULTS_MAX:
                self.results.pop(next(iter(self.results)))
        return r

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.jobs.get(timeout=5.0)
            except queue.Empty:
                try:
                    self._maybe_reconstruct()
                except Exception as exc:  # noqa: BLE001 - 1.46: an idle-tick error (ledger locked, disk) no longer kills the thread
                    self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                    log.warning("TabICL: auto-rekonstrukcja: %s", self.last_error)
                continue
            if job is None:
                break
            if time.time() - job["enqueued_at"] > float(self.settings().get("max_queue_age_s", 120)):
                self._put_result(job["plan_hash"], {**job["ident"], "state": "DROPPED_STALE", "reason": "zadanie przeterminowane w kolejce (nowszy setup ma pierwszeństwo)"})
                continue
            try:
                self._score(job)
            except Exception as exc:  # noqa: BLE001 - never kills the loop; the reason is published for THIS plan only
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                self._put_result(job["plan_hash"], {**job["ident"], "state": "ERROR", "reason": self.last_error, "computed_at": time.time()})

    # ------------------------------------------------------------------ context + scoring
    def context(self, inst: str, key: str, *, force: bool = False, as_of: float | None = None, real_only: bool = False) -> dict:
        """Reference context of one event definition as known at `as_of` (1.46: the candidate's decision time, never later than now - rows
        resolved after the decision are not in its context). The cache is reused only for a context built as of a time NOT after this
        one (no look-ahead) and not older than context_refresh_s; REAL candidates and the others have separate contexts."""
        now = time.time()
        t = now if as_of is None or not math.isfinite(float(as_of)) else min(now, float(as_of))
        lim = self.settings()
        target = int(lim.get("context_target", 512))
        ck = f"{key}#{'REAL' if real_only else 'ANY'}"
        hit = self._ctx_cache.get(ck)
        if hit and not force and hit[0] <= t and t - hit[0] < float(lim.get("context_refresh_s", 900)):
            return hit[1]
        ctx = build_context(self.q.ledger, inst, key, t, target=target, cap=int(lim.get("context_max", 1024)), real_only=real_only)
        self._ctx_cache[ck] = (t, ctx)
        self.contexts[key] = {k: v for k, v in ctx.items() if k not in ("X", "y", "row_ids")}
        prev = self._live_n.get(key)
        self._live_n[key] = ctx["live_rows"]
        if ctx["live_rows"] < target and (prev is None or prev >= target):
            self._recon_check_at = 0.0                 # 1.46: a newly short event -> the next idle tick checks the reconstruction
        return ctx

    def _snapshot_kind(self) -> str:
        """1.46: data kind of the published snapshot the candidate is assessed on (the ledger row gets the same value); missing = UNKNOWN."""
        try:
            pub = self.q.pub.current() or {}
        except Exception:  # noqa: BLE001
            return "UNKNOWN"
        return kind_of((pub.get("snapshot") or {}).get("data_kind"))

    def _ensure_loaded(self) -> None:
        if self.governor is not None:
            ok, why = self.governor.admit("tabicl", loaded=self.worker.info is not None)
            if not ok:
                raise RuntimeError(f"RESOURCE_PAUSED: {why}")
        if self.worker.info is None:
            r = self.worker.call({"cmd": "load", "weights_root": str(weights_root()), "threads": int(self.settings().get("threads", 2))}, 300)
            self.worker.info = r["info"]

    def _score(self, job: dict) -> None:
        if find_python() is None:
            self._put_result(job["plan_hash"], {**job["ident"], "state": "NOT_INSTALLED", "computed_at": time.time(),
                                                "reason": "TabICLv2 nie jest zainstalowany (.venv_tabicl + wagi) – 41_AI_TABICL_TIREX_INSTALUJ.bat"})
            return
        # 1.46: context as of the candidate's decision (was the wall clock of the scoring = look-ahead) and REAL rows only for a REAL one
        dts = job["ident"].get("decision_ts")
        try:
            as_of = float(dts) if dts is not None else None
        except (TypeError, ValueError):
            as_of = None
        ctx = self.context(job["instrument"], job["event_key"], as_of=as_of, real_only=job.get("data_kind") == "REAL")
        if ctx["n"] < MIN_ROWS or len(ctx["classes"]) < 2:
            self._put_result(job["plan_hash"], {**job["ident"], "state": "NO_CONTEXT",
                                                "context": {k: ctx[k] for k in ("n", "positives", "provenance", "event_key", "data_kinds", "as_of")},
                                                "reason": f"za mało oznaczonych przykładów tego zdarzenia ({ctx['n']}, klasy {ctx['classes']}) – kontekst "
                                                          "uzupełni się z ledgeru / rekonstrukcji historii", "computed_at": time.time()})
            return
        with self.worker.session():                    # 1.46: load + fit + predict = one busy unit for the Memory Governor
            self._ensure_loaded()
            if self.worker.loaded_ctx != ctx["context_id"]:
                self.worker.call({"cmd": "fit", "context_id": ctx["context_id"], "X": ctx["X"], "y": ctx["y"], "names": ctx["names"]}, 300)
                self.worker.loaded_ctx = ctx["context_id"]
            x = vector(job["features"], ctx["names"])
            t0 = time.perf_counter()
            r = self.worker.call({"cmd": "predict", "context_id": ctx["context_id"], "X": [x]}, 120)
        p = float(r["p_event_raw"][0])
        missing = [n for n, v in zip(ctx["names"], x) if not math.isfinite(v)]
        self._put_result(job["plan_hash"], {**job["ident"], "state": "READY", "p_event_raw": p, "confidence_score": round(100.0 * p, 1),
                                            "calibration_status": "UNCALIBRATED", "estimator_kind": "tabicl_v2", "context_id": ctx["context_id"],
                                            "context": {k: ctx[k] for k in ("n", "positives", "provenance", "first_ts", "last_ts", "feature_schema",
                                                                            "data_kinds", "as_of")},
                                            "missing_features": missing[:20], "coverage": round(1 - len(missing) / max(1, len(ctx["names"])), 3),
                                            "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "computed_at": time.time(),
                                            "model": (self.worker.info or {}).get("fingerprint")})

    def submit(self, cd: dict, spec: EV.EventSpec, feats: dict, gen) -> dict:
        """Enqueue the candidate (non-blocking). Returns the current state for THIS plan_hash (READY only when computed for it)."""
        ph = spec.plan_hash()
        cur = self.results.get(ph)
        if cur:
            return cur
        ident = {"plan_hash": ph, "task_hash": spec.task_hash(), "event_id": spec.event_id, "event_key": event_key(spec), "generation": gen,
                 "decision_ts": cd.get("decision_ts"), "strategy": cd.get("strategy_id"), "engine": cd.get("engine")}
        if not self.active():
            return {**ident, "state": "OFF", "reason": "estymator TabICLv2 wyłączony (Quant: estimator = legacy_logistic)"}
        f = dict(feats)
        f.update(strategy_features(cd.get("engine"), spec.strategy))
        job = {"plan_hash": ph, "instrument": spec.instrument, "event_key": event_key(spec), "features": f, "ident": ident, "enqueued_at": time.time(),
               "data_kind": self._snapshot_kind()}
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            try:
                old = self.jobs.get_nowait()                     # bounded queue: the oldest pending job gives way to the fresh setup
                if old:
                    self._put_result(old["plan_hash"], {**old["ident"], "state": "DROPPED_STALE", "reason": "kolejka pełna – nowszy setup ma pierwszeństwo"})
                self.jobs.put_nowait(job)
            except (queue.Empty, queue.Full):
                return {**ident, "state": "QUEUE_FULL"}
        return self._put_result(ph, {**ident, "state": "QUEUED", "reason": "ocena TabICLv2 w kolejce (asynchronicznie)"})

    def lookup(self, plan_hash: str) -> dict | None:
        return self.results.get(plan_hash)

    def _results_snapshot(self) -> list[dict]:
        with self._res_lock:
            return list(self.results.values())

    # ------------------------------------------------------------------ reconstruction (background, once per day at most)
    def _maybe_reconstruct(self) -> None:
        if not self.active() or self.recon["state"] == "RUNNING":
            return
        s = self.settings()
        if not s.get("auto_reconstruct", True):
            return
        inst = self.q.instrument()
        p = recon_path(inst)
        if p.exists() and time.time() - p.stat().st_mtime < 86400:
            return
        if self.recon.get("last_try") and time.time() - self.recon["last_try"] < 3600:
            return
        # 1.46: decided per EVENT from the contexts' own live counts (was the sum of all labelled rows of the instrument: 512 ACTIVE TP1
        # rows blocked the SH TP2 context forever) and checked at most once per context_refresh_s (was a full ledger read + JSON parse
        # every 5 s idle tick); a newly short event resets the throttle (context())
        now = time.time()
        if now - self._recon_check_at < float(s.get("context_refresh_s", 900)):
            return
        self._recon_check_at = now
        target = int(s.get("context_target", 512))
        made = self._recon_keys.get(inst) or None        # keys the reconstruction can supply (known after a run that produced rows)
        short = [k for k, n in self._live_n.items() if k.split("|", 1)[0] == inst and n < target and (made is None or k in made)]
        known = any(k.split("|", 1)[0] == inst for k in self._live_n)
        if known and not short:
            return
        if not known and sum(1 for r in self.q.ledger.training_rows(inst) if _current(r)) >= target:
            return                                       # no candidate scored yet: the 1.41 rule (labelled rows usable as context, 1.46: CURRENT)
        self.run_reconstruction(inst, days=int(s.get("reconstruct_days", 30)))

    def run_reconstruction(self, inst: str, days: int = 30, background: bool = True) -> dict:
        if self.recon["state"] == "RUNNING":
            return {"ok": False, "reason": "rekonstrukcja już trwa"}
        self.recon.update(state="RUNNING", started_at=time.time(), last_try=time.time(), result=None)

        def work():
            try:
                r = reconstruct(inst, days=days, cancel=self._stop.is_set)
            except Exception as exc:  # noqa: BLE001
                r = {"ok": False, "code": "EXCEPTION", "reason": f"{type(exc).__name__}: {exc}"[:300]}
            self.recon.update(state="DONE" if r.get("ok") else "FAILED", result=r, finished_at=time.time())
            if r.get("ok"):
                self._recon_keys[inst] = set(r.get("event_keys") or {})
            self._ctx_cache.clear()
        if background:
            threading.Thread(target=work, name="tabicl-reconstruct", daemon=True).start()
            return {"ok": True, "job": "reconstruction"}
        work()
        return self.recon["result"] or {}

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        ins = installed()
        w = self.worker
        return {"version": VERSION, "estimator": self.q.settings.get().get("estimator"), "active": self.active(),
                "activation_policy": self.settings().get("activation_policy", "DIRECT_USER_REQUEST"),
                "weights": {"installed": ins["weights"], "problems": ins["problems"], "python": ins["python"]},
                "worker": {"running": bool(w.proc and w.proc.poll() is None), "loaded": w.info is not None, "info": w.info, "restarts": w.restarts,
                           "context_in_process": w.loaded_ctx},
                "contexts": self.contexts, "reconstruction": {k: v for k, v in self.recon.items() if k != "last_try"},
                "queue": self.jobs.qsize(), "last_error": self.last_error,
                "last_results": sorted(self._results_snapshot(), key=lambda r: -(r.get("computed_at") or 0))[:10],
                "semantics": "confidence_score = 100 × p_event_raw (surowa estymata TabICLv2 dla zdarzenia planu, NIESKALIBROWANA – nie jest "
                             "zmierzonym win rate); brak wyniku ≠ 50 %"}
