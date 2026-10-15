"""Analytics worker (runs in .venv_candles). Protocol: one JSON object per line on stdin, one JSON answer per line on stdout.

  {"cmd": "hello"}                         -> versions, runtime version
  {"cmd": "analyze", "m5": [...], "m30": [...], "symbol": "XAUUSD-", "tick_size": 0.01, "as_of": "...Z", "quote": {...}}
  {"cmd": "reload"}                        -> forget the cached model (re-read the registry on the next analyze)

The worker never opens MetaTrader 5: bars come from the bot's own session. The active model is read from the registry once
and cached (by run_id + artifact checksum); a missing / incompatible model gives NO_MODEL / CONTRACT_MISMATCH, never a
fallback to another artifact. Every answer has execution_permission=false."""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone

from . import RUNTIME_VERSION
from .common import activatable, bars_frame, peak_rss_mb, read_registry, sha256_file, versions

_cache: dict = {"key": None, "model": None, "entry": None}


def _active_model(symbol: str, tick_size: float):
    """(model | None, entry | None, status, reason)."""
    from gold_candles.data import Config
    from gold_candles.model import load_model
    reg = read_registry()
    rid = reg.get("active")
    if not rid:
        return None, None, "NO_MODEL", "brak aktywnego, zgodnego modelu w rejestrze (trening nie został wykonany na danych rzeczywistych)"
    entry = reg["runs"].get(rid)
    if not entry:
        return None, None, "NO_MODEL", f"aktywny run {rid} nie istnieje w rejestrze"
    if entry.get("symbol") != symbol or abs(float(entry.get("tick_size", 0)) - float(tick_size)) > 1e-12:
        return None, entry, "CONTRACT_MISMATCH", f"model dla {entry.get('symbol')} tick {entry.get('tick_size')}, feed {symbol} tick {tick_size}"
    ok, why = activatable(entry, Config(symbol=symbol, tick_size=tick_size).contract_hash())
    if not ok:
        return None, entry, "CONTRACT_MISMATCH" if why == "CONTRACT_MISMATCH" else "NO_MODEL", why
    key = (rid, entry["artifact_sha256"])
    if _cache["key"] != key:
        model = load_model(entry["model_path"])
        if sha256_file(__import__("pathlib").Path(entry["model_path"])) != entry["artifact_sha256"]:
            return None, entry, "NO_MODEL", "ARTIFACT_CHECKSUM_MISMATCH"
        _cache.update(key=key, model=model, entry=entry)
    return _cache["model"], _cache["entry"], "OK", None


def session_check(feature_close_utc: str, horizon_minutes: int) -> str:
    """The reference module does not know the broker's sessions. Known weekly break of spot gold (Fri 21:00 UTC - Sun 22:00 UTC,
    conservative window) -> BLOCKED_SESSION_BREAK; otherwise NOT_VERIFIED_BROKER_SESSIONS (daily breaks / holidays unknown)."""
    t = datetime.fromisoformat(feature_close_utc.replace("Z", "+00:00"))
    end = t.timestamp() + horizon_minutes * 60
    for ts in range(int(t.timestamp()), int(end) + 1, 60):
        d = datetime.fromtimestamp(ts, timezone.utc)
        wd, hm = d.weekday(), d.hour * 60 + d.minute
        if (wd == 4 and hm >= 21 * 60) or wd == 5 or (wd == 6 and hm < 22 * 60):
            return "BLOCKED_SESSION_BREAK"
    return "NOT_VERIFIED_BROKER_SESSIONS"


def analyze_request(req: dict) -> dict:
    from gold_candles.analysis import analyze
    from gold_candles.data import Config, DataError
    t0 = time.perf_counter()
    symbol, tick = req.get("symbol") or "XAUUSD-", float(req["tick_size"])
    out: dict = {"execution_permission": False, "mode": "SHADOW"}
    try:
        config = Config(symbol=symbol, tick_size=tick)
        as_of = req["as_of"]
        m5 = bars_frame(req["m5"], 5, as_of, symbol)
        m30 = bars_frame(req["m30"], 30, as_of, symbol) if req.get("m30") else None
        model, entry, mstatus, mreason = _active_model(symbol, tick)
        report = analyze(m5, m30, config, model, as_of, "LIVE", req.get("quote"))
        fc = report.get("forecast") or {}
        status = fc.get("status")
        if mstatus != "OK":
            status = mstatus
        elif status == "FEATURE_WARMUP_OR_STALE_M30":
            status = "WARMUP"
        elif status == "STALE_M5_DATA":
            status = "STALE_DATA"
        elif status == "SHADOW_RESEARCH_FORECAST":
            status = "SHADOW"
            for h in (fc.get("probabilities") or {}).values():
                h["session_check"] = session_check(fc["feature_time_utc"], h["horizon_minutes"])
                if h["session_check"] == "BLOCKED_SESSION_BREAK":
                    h["blocked_reason"] = "horyzont obejmuje przerwę rynku – prognoza niedopuszczalna"
        tail = int(req.get("flags_tail") or 0)
        if tail:
            from gold_candles.patterns import flags as _flags
            fl = _flags(m5, config).tail(tail)
            out["flags_tail"] = [{"time_open_utc": m5.time_open_utc.loc[i].isoformat(), "names": [n for n in fl.columns if bool(fl.loc[i, n])]}
                                 for i in fl.index]
        out.update(status=status, reason=mreason, report=report,
                   model=None if not entry else {k: entry.get(k) for k in ("run_id", "created_at_utc", "knowledge_cutoff_utc", "train_range_utc",
                                                                         "horizon_status", "overall_status", "contract_hash", "m30_source", "data_kind")})
    except DataError as exc:
        msg = str(exc)
        status = ("CONTRACT_MISMATCH" if "CONTRACT" in msg or "MISMATCH" in msg else
                  "WARMUP" if "NO_COMPLETE" in msg or "NO_CLOSED" in msg else
                  "MODEL_FROM_FUTURE" if "FUTURE" in msg and "MODEL" in msg else "FORECAST_UNAVAILABLE")
        out.update(status=status, reason=msg, report=None)
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["peak_rss_mb"] = peak_rss_mb()
    return out


_scalp_cache: dict = {"run_id": None, "model": None}


def scalp_forecast(req: dict) -> dict:
    """Task-A forecast 1/3/5 min on the latest CLOSED M1 (scalp model registry). SHADOW only - never an order permission."""
    import numpy as np
    from datetime import datetime as _dt
    from . import scalp_features as SF
    from .scalp_infer import ScalpModel, activatable, read_registry
    reg = read_registry()
    rid = reg.get("active")
    if not rid:
        return {"status": "UNAVAILABLE", "reason": "NO_MODEL", "execution_permission": False}
    entry = reg["runs"][rid]
    ok, why = activatable(entry, SF.contract_hash(entry["symbol"], entry["tick_size"]))
    if not ok:
        return {"status": "UNAVAILABLE", "reason": why, "execution_permission": False}
    if _scalp_cache["run_id"] != rid:
        _scalp_cache.update(run_id=rid, model=ScalpModel(entry))
    bars = req.get("m1") or []
    t = [int(_dt.fromisoformat(b["open_utc"].replace("Z", "+00:00")).timestamp()) for b in bars]
    X, atr = SF.build(t, [b["o"] for b in bars], [b["h"] for b in bars], [b["l"] for b in bars], [b["c"] for b in bars],
                      [b.get("tv") for b in bars], [b.get("spread_price") for b in bars])
    if not len(X) or np.isnan(X[-1]).any():
        return {"status": "WARMUP", "reason": "za mało zamkniętych M1 do cech", "execution_permission": False}
    pred = _scalp_cache["model"].predict(X[-1:])
    c, a = bars[-1]["c"], atr[-1]
    out = {}
    for hz, r in pred.items():
        P = r["P"][0]
        q = r["Q"][0] if r["Q"] is not None else None
        out[hz] = {"p_down": round(float(P[0]), 4), "p_flat": round(float(P[1]), 4), "p_up": round(float(P[2]), 4),
                   "q10_q50_q90_price": None if q is None else [round(c + float(x) * a, 3) for x in q],
                   "status": entry["horizon_status"].get(hz), "model": entry["models"][hz]["selected"]}
    return {"status": "SHADOW", "run_id": rid, "feature_time_utc": bars[-1]["open_utc"], "horizons": out, "execution_permission": False,
            "note": "P(UP) nie jest P(TP przed SL) ani oceną transakcji"}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "hello":
                ans = {"ok": True, "runtime": RUNTIME_VERSION, "versions": versions()}
            elif cmd == "reload":
                _cache.update(key=None, model=None, entry=None)
                ans = {"ok": True}
            elif cmd == "analyze":
                ans = analyze_request(req)
            elif cmd == "scalp_forecast":
                ans = scalp_forecast(req)
            elif cmd == "quit":
                return 0
            else:
                ans = {"ok": False, "error": "UNKNOWN_COMMAND"}
        except Exception as exc:                 # one bad request never kills the worker
            ans = {"ok": False, "status": "FORECAST_UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc(limit=3), "execution_permission": False}
        sys.stdout.write(json.dumps(ans, ensure_ascii=False, allow_nan=False, default=str) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
