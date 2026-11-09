"""Walk-forward comparison of Kronos-base, Chronos-2 and FinCast on the SAME forecast origins (PMW-TSFM-WF-1).

Data: closed bars of the user's MT5 history through the existing bridge (quality-checked, no filling). Origins every H bars (the label
windows never overlap: no leakage across the DEV / TEST boundary), chronological split DEV (first 60 %) / TEST (last 40 %); the target
bar must be exactly the H-th next bar of the broker's session calendar built ONLY from history up to the end of DEV (a session break or a
data hole skips the origin for ALL models). Nothing is fitted or chosen on TEST: the neutral band k is the configured one (the same for
every model), there is no ensemble weight. Every model sees exactly the same context window and target.

Metrics per model, on (a) its own answered origins and (b) the COMMON subset where all models answered (coverage is reported - a model
that refuses difficult periods does not get an easier test): MAE / RMSE of the close at H vs the "last price" baseline, direction
accuracy outside the neutral band vs the momentum baseline + binomial p vs 50 %, for quantile models pinball loss (levels 0.1 / 0.5 / 0.9),
empirical 80 % coverage (q0.1..q0.9) and mean width. No probability of a trade outcome is computed here.

Pretraining overlap: the authors do not publish exact date ranges of their pretraining corpora for XAUUSD / BTC at the broker's
resolution; leakage of public prices into pretraining therefore cannot be excluded and is stated in every report.
Verdict (per model, required for ASSIST / REQUIRED): REAL data, >= 100 direction observations in TEST, MAE below the last-price baseline,
direction accuracy above momentum and p < 0.05. A positive verdict is a necessary condition - not proof of a trading edge.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from ..kronos import calendar as CAL
from ..kronos import quality as Q
from ..timeutil import TF_SECONDS, iso, utcnow
from .settings import MODEL_IDS, tsfm_dir

SCHEMA = "PMW-TSFM-WF-1"
BINDING_SCHEMA = "PMW-TSFM-BINDING-1"
CAVEAT = ("Zakres danych pretreningu modeli (Kronos, Chronos-2, FinCast) nie jest znany z dokładnością do instrumentu i dnia – nie można "
          "wykluczyć, że publiczne notowania z okresu testu były w danych treningowych autorów. Wyniki dotyczą prognozy ceny, nie wyniku transakcji.")


def reports_dir() -> Path:
    p = tsfm_dir() / "reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def binding(svc, mid: str, inst: str, tf: str) -> dict:
    """Everything an approval is valid for: model fingerprint, symbol / data source, TF, horizon, context, profile, band, quantiles."""
    from tsfm_runtime import lock as L
    s = svc.settings.get()
    c = s.models[mid]
    sym, _ = svc.symbol(inst)
    kind, _ = svc.data_kind()
    return {"schema": BINDING_SCHEMA, "model": mid, "fingerprint": L.fingerprint(mid), "instrument": inst, "symbol": sym, "data_kind": kind,
            "timeframe": tf, "horizon_bars": int(s.horizon_bars[tf]), "context_len": c.context_len, "profile": c.profile,
            "direction_band_atr": s.direction_band_atr, "direction_band_min_points": s.direction_band_min_points, "quantiles": s.quantiles,
            "validation_code": SCHEMA}


def binding_diff(stored: dict | None, current: dict) -> list[str]:
    if not stored:
        return ["raport bez powiązania dla tego modelu – wymagana nowa walidacja"]
    return [f"{k}: {stored.get(k)!r} → {current.get(k)!r}" for k in current if k != "schema" and stored.get(k) != current.get(k)]


def report_by_id(rid: str) -> dict | None:
    for f in sorted(reports_dir().glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("report_id") == rid:
            return r
    return None


def latest_report(inst: str, tf: str) -> dict | None:
    for f in reversed(sorted(reports_dir().glob(f"{inst}_{tf}_*.json"))):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def binom_p_greater(k: int, n: int) -> float | None:
    if n <= 0:
        return None
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2.0 ** n


def _mean(it) -> float | None:
    xs = [float(x) for x in it if x is not None]
    return sum(xs) / len(xs) if xs else None


def _metrics(rows: list[dict], key: str, band_k: float) -> dict:
    """rows: dicts with last, actual, atr, momentum and per-model {key: {"point", "q"}}; only rows where `key` answered."""
    got = [r for r in rows if r["pred"].get(key) is not None]
    if not got:
        return {"n": 0}
    err = [r["pred"][key]["point"] - r["actual"] for r in got]
    naive = [r["last"] - r["actual"] for r in got]
    hits = n = mom_hits = 0
    for r in got:
        band = band_k * r["atr"]
        act = r["actual"] - r["last"]
        prd = r["pred"][key]["point"] - r["last"]
        if abs(act) <= band or abs(prd) <= band or r["momentum"] == 0:
            continue
        n += 1
        hits += int((prd > 0) == (act > 0))
        mom_hits += int((r["momentum"] > 0) == (act > 0))
    out = {"n": len(got), "mae": _mean(abs(e) for e in err), "rmse": math.sqrt(_mean(e * e for e in err) or 0.0),
           "mae_naive_last_price": _mean(abs(e) for e in naive), "direction_n": n, "direction_accuracy": (hits / n) if n else None,
           "momentum_accuracy_same_cases": (mom_hits / n) if n else None, "binomial_p_vs_50pct": binom_p_greater(hits, n) if n else None}
    out["skill_vs_naive"] = (1 - out["mae"] / out["mae_naive_last_price"]) if out["mae_naive_last_price"] else None
    qrows = [r for r in got if r["pred"][key].get("q")]
    if qrows:
        pin, cov, width = [], [], []
        for r in qrows:
            q = r["pred"][key]["q"]
            y = r["actual"]
            pin.append(_mean(max(float(lv) * (y - v), (float(lv) - 1) * (y - v)) for lv, v in q.items()))
            if "0.1" in q and "0.9" in q:
                cov.append(int(q["0.1"] <= y <= q["0.9"]))
                width.append(q["0.9"] - q["0.1"])
        out.update({"pinball": _mean(pin), "coverage_80": _mean(cov), "width_80": _mean(width), "quantile_n": len(qrows)})
    return out


class _KronosClient:
    """Kronos through its own validation client (a separate .venv_kronos process - live forecasts keep running)."""

    def __init__(self, kr):
        from ..kronos import validation as KV
        from ..kronos.settings import find_python as kpy
        self.kr = kr
        s = kr.settings.get()
        self.s = s
        py = kpy(s)
        if not py:
            raise RuntimeError("brak środowiska .venv_kronos")
        self.cli = KV._Client(py, s.cpu_threads or 2)
        self.cli.ask({"cmd": "hello"}, 120)
        r = self.cli.ask({"cmd": "load", "weights_dir": str(kr.weights_dir()), "device": s.device, "max_context": s.max_context,
                          "threads": s.cpu_threads or 2, "verify_files": True}, s.load_timeout_s)
        if not r.get("ok"):
            self.close()
            raise RuntimeError(f"{r.get('code')}: {r.get('error')}")
        self.info = r["info"]

    def predict(self, ctx, y_raw, H, vol_src) -> dict | None:
        s = self.s
        off = int(ctx[-1]["t_raw"]) - int(datetime.fromisoformat(ctx[-1]["open_utc"].replace("Z", "+00:00")).timestamp())

        def fmt(raw):
            sec = raw if s.timestamp_basis == "SERVER" else raw - off
            return datetime.fromtimestamp(sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        L = min(len(ctx), s.lookback)
        c = ctx[-L:]
        vol = [float(b.get("tv") or 0) for b in c] if vol_src == "TICK_VOLUME" else [float(b.get("rv") or 0) for b in c] if vol_src == "REAL_VOLUME" else None
        req = {"cmd": "predict", "candles": {"t": [fmt(int(b["t_raw"])) for b in c], "open": [b["o"] for b in c], "high": [b["h"] for b in c],
                                             "low": [b["l"] for b in c], "close": [b["c"] for b in c], "volume": vol},
               "y_t": [fmt(x) for x in y_raw], "pred_len": H, "T": s.temperature, "top_k": s.top_k, "top_p": s.top_p,
               "seed": (int(ctx[-1]["t_raw"]) * 31 + H) & 0x7FFFFFFF, "paths": 0}
        r = self.cli.ask(req, s.request_timeout_s)
        if not r.get("ok"):
            return None
        return {"point": float(r["pred"]["close"][-1]), "q": None, "ms": r.get("ms")}

    def close(self):
        self.cli.close()


def run(svc, inst: str, tf: str, *, max_origins: int = 200, progress=None, include_kronos: bool = True) -> dict:
    s = svc.settings.get()
    sym, why = svc.symbol(inst)
    kind, kind_pl = svc.data_kind()
    started = iso(utcnow())
    H = int(s.horizon_bars[tf])
    ctx_len = max(c.context_len for c in s.models.values())
    tf_sec = TF_SECONDS[tf]
    base = {"schema": SCHEMA, "instrument": inst, "symbol": sym, "timeframe": tf, "horizon_bars": H, "context_len": ctx_len, "started_at": started,
            "data_kind": kind, "data_source": kind_pl, "caveat": CAVEAT, "band_k": s.direction_band_atr,
            "bindings": {m: binding(svc, m, inst, tf) for m in MODEL_IDS}}
    if not sym:
        return _save({**base, "status": "BLOCKED", "reason": why, "models": {}})
    need = min(9000, max(ctx_len + H * (max_origins + 2) + 50, 28 * 86400 // tf_sec))
    bars = [b for b in svc.bridge.symbol_bars(sym, tf, need) if b.get("closed")]
    q = Q.check(bars, tf_sec, now_utc=time.time(), lookback=len(bars), min_context=ctx_len + 2 * H, volume_setting="AUTO", max_staleness_bars=1e9)
    if q["status"] in ("BLOCK", "WARMUP"):
        return _save({**base, "status": "BLOCKED", "reason": "; ".join(i["reason"] for i in q["issues"]), "models": {}})
    bars = q["bars"]
    origins = list(range(ctx_len, len(bars) - H + 1, H))[-max_origins:]
    if len(origins) < 20:
        return _save({**base, "status": "BLOCKED", "reason": f"za mało punktów startu ({len(origins)}) – potrzebna dłuższa historia", "models": {}})
    n_dev = int(len(origins) * 0.6)
    dev_end_raw = int(bars[origins[n_dev] - 1]["t_raw"]) if n_dev < len(origins) else int(bars[-1]["t_raw"])
    cal = CAL.Calendar([int(b["t_raw"]) for b in bars if int(b["t_raw"]) <= dev_end_raw], CAL.slot_seconds(tf_sec))
    models = [m for m in MODEL_IDS if s.models[m].enabled]
    ready = {}
    for m in models:
        with svc.exec_lock:
            ok = svc.workers[m].ensure()
        ready[m] = ok or svc.workers[m].state.get("reason")
    kr = None
    kr_note = None
    if include_kronos and svc.kronos is not None:
        try:
            kr = _KronosClient(svc.kronos)
        except Exception as exc:  # noqa: BLE001
            kr_note = f"Kronos pominięty: {type(exc).__name__}: {exc}"[:200]
    rows, skipped = [], {"calendar": 0, "calendar_reasons": {}}
    errors = {m: 0 for m in [*models, "kronos"]}
    t0 = time.time()
    try:
        for j, i in enumerate(origins):
            ctx = bars[i - ctx_len:i]
            fut = bars[i:i + H]
            y_raw, info = cal.future(int(ctx[-1]["t_raw"]), tf_sec, H)
            if y_raw is None or [int(b["t_raw"]) for b in fut] != y_raw:
                skipped["calendar"] += 1
                w = info["status"] if y_raw is None else "REAL_BARS_NOT_ON_CALENDAR_TIMES"
                skipped["calendar_reasons"][w] = skipped["calendar_reasons"].get(w, 0) + 1
                continue
            last = float(ctx[-1]["c"])
            prev = float(bars[i - 1 - H]["c"]) if i - 1 - H >= 0 else last
            row = {"t": ctx[-1]["open_utc"], "split": "DEV" if j < n_dev else "TEST", "last": last, "actual": float(fut[-1]["c"]),
                   "atr": Q.atr(ctx, 14) or 0.0, "momentum": last - prev, "pred": {}}
            for m in models:
                if ready[m] is not True:
                    row["pred"][m] = None
                    continue
                c = s.models[m]
                req = {"cmd": "predict", "close": [float(b["c"]) for b in ctx[-c.context_len:]], "pred_len": H, "context_len": min(c.context_len, len(ctx)),
                       "profile": "CLOSE_V1", "quantiles": s.quantiles, "freq_tf": tf}
                with svc.exec_lock:                                       # never interleaved with a live forecast of the same process
                    try:
                        r = svc.workers[m].ask(req, c.request_timeout_s)
                    except (TimeoutError, RuntimeError) as exc:
                        r = {"ok": False, "error": str(exc)}
                        svc.workers[m].fail("VALIDATION", str(exc))
                        ready[m] = svc.workers[m].ensure() or str(exc)
                if not r.get("ok"):
                    errors[m] += 1
                    row["pred"][m] = None
                    continue
                qv = (r.get("quantiles") or {}).get("values") or {}
                row["pred"][m] = {"point": float(r["point"][-1]), "q": {k: float(v[-1]) for k, v in qv.items()}, "ms": r.get("ms")}
            if kr is not None:
                try:
                    row["pred"]["kronos"] = kr.predict(ctx, y_raw, H, q["volume_source"])
                except Exception:  # noqa: BLE001
                    row["pred"]["kronos"] = None
                if row["pred"]["kronos"] is None:
                    errors["kronos"] += 1
            rows.append(row)
            if progress:
                progress(j + 1, len(origins))
    finally:
        if kr is not None:
            kr.close()
    keys = models + (["kronos"] if kr is not None else [])
    test = [r for r in rows if r["split"] == "TEST"]
    common = [r for r in test if all(r["pred"].get(k) is not None for k in keys)]
    out_models = {}
    for k in keys:
        own = _metrics(test, k, s.direction_band_atr)
        com = _metrics(common, k, s.direction_band_atr)
        reasons = []
        if kind == "SYNTHETIC":
            reasons.append("dane SYNTETYCZNE (symulator) – walidacja nie dotyczy rynku")
        if (own.get("direction_n") or 0) < 100:
            reasons.append(f"za mało obserwacji kierunku w teście ({own.get('direction_n') or 0} < 100)")
        if own.get("mae") is None or own.get("mae_naive_last_price") is None or own["mae"] >= own["mae_naive_last_price"]:
            reasons.append("MAE nie jest niższe od prognozy ostatniej ceny")
        acc, mom = own.get("direction_accuracy"), own.get("momentum_accuracy_same_cases")
        if acc is None or (mom is not None and acc <= mom):
            reasons.append("trafność kierunku nie przewyższa bazowego momentum")
        p = own.get("binomial_p_vs_50pct")
        if p is None or p >= 0.05:
            reasons.append(f"trafność kierunku nieistotna statystycznie (p = {p if p is None else round(p, 4)})")
        answered = sum(1 for r in test if r["pred"].get(k) is not None)
        out_models[k] = {"coverage": {"answered": answered, "test_origins": len(test), "share": (answered / len(test)) if test else None,
                                      "errors": errors.get(k, 0)},
                         "test_own": own, "test_common": com,
                         "verdict": {"positive": not reasons, "reason": "; ".join(reasons) if reasons else
                                     "pozytywna w teście końcowym (warunek konieczny dopuszczenia – nie dowód przewagi handlowej)"},
                         "ready": True if k == "kronos" else ready.get(k)}
    summary = ", ".join(f"{k}: MAE {_fmt(v['test_own'].get('mae'))} vs ostatnia cena {_fmt(v['test_own'].get('mae_naive_last_price'))}"
                        for k, v in out_models.items())
    rep = {**base, "status": "DONE", "finished_at": iso(utcnow()), "duration_s": round(time.time() - t0, 1), "bars_used": len(bars),
           "first_bar": bars[0]["open_utc"], "last_bar": bars[-1]["open_utc"], "origins": len(origins),
           "evaluated": {"dev": len(rows) - len(test), "test": len(test), "common_test": len(common)}, "skipped": skipped,
           "kronos_note": kr_note, "kronos_load": getattr(kr, "info", None) if kr else None, "models": out_models, "summary_text": summary,
           "combination": "brak – łączenie modeli wymaga osobnej walidacji (wagi z danych DEV z uwzględnieniem korelacji błędów); prognozy pokazywane osobno",
           "rows": [{**r, "pred": {k: (v and {"point": v["point"]}) for k, v in r["pred"].items()}} for r in rows[-300:]]}
    return _save(rep)


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.4f}"


def _save(rep: dict) -> dict:
    rid = f"{rep['instrument']}_{rep['timeframe']}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    rep["report_id"] = rid
    (reports_dir() / f"{rid}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return rep
