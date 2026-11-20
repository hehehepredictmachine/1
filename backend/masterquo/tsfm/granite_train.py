"""1.40 Granite TTM in the Training Center: dataset export, fine-tuning job, versions, activation, rollback to the base model.

  export(inst, tf)      closed bars of the existing candle store (filled by "Eksportuj dane" of the Training Center - the same MT5 history
                        the other models use; no second download) -> validation (sorted, unique, finite, OHLC geometry, gaps reported,
                        minimum length) -> data/tsfm/granite_data/<inst>_<tf>_<ts>.json + sha256.
  start(svc, ...)       separate process of .venv_granite (tsfm_runtime.granite_finetune) with the CPU threads of the resource profile;
                        refused by the Memory Governor while another heavy training runs, while AUTO trading runs (unless confirmed) or
                        under memory pressure. Never started with the bot, cancellable (terminate -> nothing saved).
  runs()                fine-tuned versions with their test metrics (data/tsfm/finetuned/granite_ttm/<run>/granite_finetune.json).
  activate(svc, run)    explicit: checksums + base fingerprint verified, the TEST verdict must be IMPROVED_VS_BASE (else refused), then
                        settings.models.granite_ttm.checkpoint = run (written to settings_history.jsonl; the worker reloads).
  rollback(svc)         checkpoint = BASE (pretrained pinned revision).
A new checkpoint starts with NO approval: validation / roles of the previous binding become stale (the binding contains the checkpoint).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from .settings import find_python, tsfm_dir

MIN_BARS = 5000                     # with an embargo of context + horizon between train / validation / test (15 % each must exceed it)


def data_dir() -> Path:
    p = tsfm_dir() / "granite_data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def finetune_dir() -> Path:
    p = tsfm_dir() / "finetuned" / "granite_ttm"
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_bars(cols: dict) -> dict:
    t, o, h, l, c = (cols.get(k) or [] for k in ("time", "open", "high", "low", "close"))
    n = len(t)
    issues = []
    if n < MIN_BARS:
        issues.append(f"za mało świec: {n} < {MIN_BARS} (kontekst 512 + horyzont + część walidacyjna i testowa)")
    if any(t[i] <= t[i - 1] for i in range(1, n)):
        issues.append("czasy nie rosną ściśle (duplikaty / zła kolejność)")
    bad = sum(1 for i in range(n) if not all(math.isfinite(float(x)) and float(x) > 0 for x in (o[i], h[i], l[i], c[i])))
    if bad:
        issues.append(f"{bad} świec z nieprawidłową ceną (NaN / ≤ 0)")
    geo = sum(1 for i in range(n) if not (l[i] <= min(o[i], c[i]) and h[i] >= max(o[i], c[i])))
    if geo:
        issues.append(f"{geo} świec z błędną geometrią OHLC")
    steps = sorted(t[i] - t[i - 1] for i in range(1, n)) if n > 1 else []
    tf_s = steps[len(steps) // 2] if steps else None
    gaps = sum(1 for d in steps if tf_s and d > tf_s * 3) if steps else 0
    return {"ok": not issues, "issues": issues, "bars": n, "gaps_over_3_bars": gaps, "step_s": tf_s,
            "note": "luki (weekendy, przerwy sesji) są zachowane – świece nie są uzupełniane ani przesuwane"}


def export(inst: str, tf: str, store=None) -> dict:
    from ..marketdata.store import Store
    st = store or Store()
    cols = st.read(inst, tf)
    v = validate_bars(cols)
    if not v["ok"]:
        return {"ok": False, "reason": "; ".join(v["issues"]), "validation": v}
    man = st.manifest(inst) or {}
    t = [int(x) for x in cols["time"]]
    ds = {"schema": "PMW-GRANITE-DATA-1", "instrument": inst, "symbol": man.get("symbol"), "timeframe": tf, "data_kind": man.get("data_kind"),
          "source": "magazyn świec Centrum treningu (eksport MT5, zamknięte świece)",
          "times": t, "open": cols["open"], "high": cols["high"], "low": cols["low"], "close": cols["close"],
          "first": datetime.fromtimestamp(t[0], tz=timezone.utc).isoformat(), "last": datetime.fromtimestamp(t[-1], tz=timezone.utc).isoformat(),
          "bars": len(t), "validation": v}
    ds["sha256"] = hashlib.sha256(json.dumps([t, cols["close"]]).encode()).hexdigest()
    p = data_dir() / f"{inst}_{tf}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    p.write_text(json.dumps(ds), encoding="utf-8")
    return {"ok": True, "file": str(p), "bars": len(t), "first": ds["first"], "last": ds["last"], "sha256": ds["sha256"], "validation": v,
            "data_kind": ds["data_kind"]}


def runs() -> list[dict]:
    out = []
    for d in sorted(finetune_dir().iterdir(), reverse=True) if finetune_dir().exists() else []:
        try:
            m = json.loads((d / "granite_finetune.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({k: m.get(k) for k in ("run_id", "created_at", "data", "metrics", "train", "base_fingerprint")})
    return out


def start(svc, inst: str, tf: str, *, epochs: int = 6, confirm_during_trading: bool = False, trading_active: bool = False) -> dict:
    s = svc.settings.get()
    H = int(s.horizon_bars.get(tf, 12))
    py = find_python("granite_ttm", s.models["granite_ttm"])
    if not py:
        return {"ok": False, "reason": "brak środowiska .venv_granite – najpierw zainstaluj Granite TTM"}
    gov = getattr(svc, "governor", None)
    if gov is not None:
        ok, why = gov.admit_training("granite_train", "heavy", trading_active=trading_active, force=confirm_during_trading)
        if not ok:
            return {"ok": False, "reason": why}
    ex = export(inst, tf)
    if not ex["ok"]:
        if gov is not None:
            gov.training_done("granite_train")
        return {"ok": False, "reason": f"zbiór danych odrzucony: {ex['reason']}", "validation": ex.get("validation")}
    threads = gov.threads_for("chronos2") if gov is not None else max(1, (os.cpu_count() or 2) // 2)
    argv = [py, "-m", "tsfm_runtime.granite_finetune", "--data", ex["file"], "--weights-root", str(svc.weights_root()), "--out",
            str(finetune_dir()), "--horizon", str(H), "--epochs", str(int(epochs)), "--threads", str(threads)]
    env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1",
               OMP_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads))

    def done(ok, job):
        if gov is not None:
            gov.training_done("granite_train")
        svc.applog.info("TSFM", "GRANITE_TRAIN", f"Trening Granite TTM {inst} {tf}: {'OK ' + str((job.get('result') or {}).get('run_id')) if ok else 'BŁĄD ' + str(job.get('code'))}.")
    r = svc._run_job_proc("granite_train", argv, env=env, on_done=done)
    if not r.get("ok") and gov is not None:
        gov.training_done("granite_train")
    return {**r, "dataset": {k: ex[k] for k in ("bars", "first", "last", "sha256", "data_kind")}, "horizon": H, "threads": threads}


def cancel(svc) -> dict:
    p = svc._job_procs.get("granite_train")
    if p is None or p.poll() is not None:
        return {"ok": False, "reason": "trening nie trwa"}
    p.terminate()
    return {"ok": True}


def activate(svc, run_id: str) -> dict:
    from tsfm_runtime import lock as L
    from tsfm_runtime import manifest as M
    d = finetune_dir() / run_id
    try:
        man = json.loads((d / "granite_finetune.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "reason": f"brak checkpointu {run_id}"}
    if man.get("base_fingerprint") != L.fingerprint("granite_ttm"):
        return {"ok": False, "reason": "checkpoint powstał z innego modelu bazowego – nie zostanie aktywowany"}
    for f in man.get("files") or []:
        if not (d / f["name"]).is_file() or M.sha256_file(d / f["name"]) != f["sha256"]:
            return {"ok": False, "reason": f"{f['name']}: suma SHA-256 niezgodna – plik zmieniony"}
    verdict = ((man.get("metrics") or {}).get("verdict"))
    if verdict != "IMPROVED_VS_BASE":
        return {"ok": False, "reason": f"werdykt testu {verdict}: dotrenowany model nie jest lepszy od bazowego na niewidzianych danych"}
    if (man.get("train") or {}).get("horizon") != int(svc.settings.get().horizon_bars.get((man.get("data") or {}).get("timeframe") or "M5", 0)):
        return {"ok": False, "reason": "checkpoint trenowany dla innego horyzontu niż obecne ustawienia"}
    svc.settings.update({"models": {"granite_ttm": {"checkpoint": run_id}}}, who="granite_activate")
    svc.workers["granite_ttm"].kill()                                    # reload with the new checkpoint on the next forecast
    svc.applog.info("TSFM", "GRANITE_ACTIVATE", f"Granite TTM: aktywny checkpoint {run_id} (powrót: BASE).")
    return {"ok": True, "checkpoint": run_id, "metrics": man.get("metrics")}


def rollback(svc) -> dict:
    svc.settings.update({"models": {"granite_ttm": {"checkpoint": "BASE"}}}, who="granite_rollback")
    svc.workers["granite_ttm"].kill()
    svc.applog.info("TSFM", "GRANITE_ROLLBACK", "Granite TTM: powrót do modelu bazowego (BASE).")
    return {"ok": True, "checkpoint": "BASE"}
