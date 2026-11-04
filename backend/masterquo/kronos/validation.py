"""Walk-forward check of Kronos on the user's own closed bars (MT5 history through the bridge) - honest comparison with simple baselines.

Procedure (one instrument, one timeframe):
* bars: closed bars from the bridge (one call, up to `max_bars`), quality-checked (order, duplicates, OHLC geometry);
* origins every H bars (horizons do NOT overlap): context = the `lookback` bars before the origin, target = the close H bars later;
  future candle times come from the session calendar measured on the DEV part only (no knowledge of the test period), and an origin
  whose real next H bars do not sit on those times (session break the calendar did not foresee) is skipped and counted;
* chronological split: first 60 % of origins = DEV (the only place a setting is chosen: the neutral-band multiplier k of the direction
  rule, from a small grid), last 40 % = final TEST, reported once with k frozen;
* metrics on TEST: MAE of the close after H bars - Kronos vs "last price" (naive), skill = 1 - MAE_K / MAE_naive; direction accuracy on
  origins where both the forecast and the real move are outside the band, vs a momentum baseline (sign of the last H-bar move) on the SAME
  origins, one-sided binomial p-value vs 50 %, number of observations;
* verdict "positive" (needed to allow REQUIRED in a strategy) only with real data (not SYNTHETIC), >= 100 directional test observations,
  MAE below naive, accuracy above the momentum baseline and p < 0.05. Otherwise the reasons are listed.
Caveat always reported: the period and composition of Kronos' pre-training data are not known in detail (public crypto / equity / FX
candles from many exchanges) - the test period may overlap with pre-training; a split of the user's bars does not prove independence.
No trading result is computed here (no costs model) - this is forecast quality, not profit.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from ..timeutil import TF_SECONDS, iso, utcnow
from . import calendar as CAL
from . import quality as Q
from .settings import find_python, kronos_dir

GRID = (0.0, 0.1, 0.25, 0.5, 1.0)
CAVEAT = ("Okres i skład danych pretreningu Kronos nie są znane szczegółowo (publiczne świece wielu giełd i rynków) – okres testu może "
          "nakładać się z pretreningiem; podział świec użytkownika na DEV/TEST nie dowodzi niezależności od pretreningu. Wynik dotyczy jakości "
          "prognozy ceny, nie zysku: koszty, spread, poślizg i wolumen pozycji nie są tu liczone.")


def reports_dir() -> Path:
    p = kronos_dir() / "validation"
    p.mkdir(parents=True, exist_ok=True)
    return p


def latest_report(inst: str, tf: str) -> dict | None:
    files = sorted(reports_dir().glob(f"{inst}_{tf}_*.json"))
    for f in reversed(files):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def binom_p_greater(k: int, n: int) -> float | None:
    """P(X >= k), X ~ Bin(n, 0.5) - exact (n is a few hundred at most)."""
    if n <= 0:
        return None
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2.0 ** n


class _Client:
    def __init__(self, py: str, threads: int):
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
        self.p = subprocess.Popen([py, "-m", "kronos_runtime.worker"], cwd=str(paths.ROOT_DIR / "backend"), env=env, text=True, encoding="utf-8",
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.threads = threads

    def ask(self, req: dict, timeout: float) -> dict:
        self.p.stdin.write(json.dumps(req, allow_nan=False) + "\n")
        self.p.stdin.flush()
        box: dict = {}
        th = threading.Thread(target=lambda: box.update(line=self.p.stdout.readline()), daemon=True)
        th.start()
        th.join(timeout)
        if th.is_alive() or not box.get("line"):
            self.close()
            raise TimeoutError("WORKER_TIMEOUT")
        return json.loads(box["line"])

    def close(self) -> None:
        if self.p.poll() is None:
            try:
                self.p.stdin.write('{"cmd":"quit"}\n')
                self.p.stdin.flush()
                self.p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.p.kill()


def run(svc, inst: str, tf: str, *, max_origins: int = 300, progress=None, client_factory=None) -> dict:
    s = svc.settings.get()
    sym, why = svc.symbol(inst)
    started = iso(utcnow())
    kind, kind_pl = svc.data_kind()
    base = {"schema": "PMW-KRONOS-WF-1", "instrument": inst, "symbol": sym, "timeframe": tf, "started_at": started, "data_kind": kind,
            "data_source": kind_pl, "caveat": CAVEAT, "settings": {k: getattr(s, k) for k in ("lookback", "temperature", "top_k", "top_p",
                                                                                               "volume_source", "timestamp_basis")}}
    if not sym:
        return _save({**base, "status": "BLOCKED", "verdict": {"positive": False, "reason": why}})
    H, L = int(s.horizon_bars[tf]), int(s.lookback)
    tf_sec = TF_SECONDS[tf]
    need = min(8000, L + H * (max_origins + 2) + 50)
    bars = [b for b in svc.bridge.symbol_bars(sym, tf, need) if b.get("closed")]
    q = Q.check(bars, tf_sec, now_utc=time.time(), lookback=len(bars), min_context=L + 2 * H, volume_setting=s.volume_source,
                max_staleness_bars=1e9)
    if q["status"] in ("BLOCK", "WARMUP"):
        return _save({**base, "status": "BLOCKED", "verdict": {"positive": False, "reason": "; ".join(i["reason"] for i in q["issues"])}})
    bars = q["bars"]
    origins = list(range(L, len(bars) - H + 1, H))[-max_origins:]
    n_dev = int(len(origins) * 0.6)
    if len(origins) < 20:
        return _save({**base, "status": "BLOCKED", "verdict": {"positive": False, "reason": f"za mało punktów startu ({len(origins)}) – potrzebna dłuższa historia"}})
    dev_end_raw = int(bars[origins[n_dev] - 1]["t_raw"]) if n_dev < len(origins) else int(bars[-1]["t_raw"])
    cal = CAL.Calendar([int(b["t_raw"]) for b in bars if int(b["t_raw"]) <= dev_end_raw], CAL.slot_seconds(tf_sec))
    py = find_python(s)
    if not py and client_factory is None:
        return _save({**base, "status": "BLOCKED", "verdict": {"positive": False, "reason": "brak środowiska .venv_kronos"}})
    cli = client_factory() if client_factory else _Client(py, s.cpu_threads or 2)
    rows, skipped = [], {"calendar": 0, "error": 0}
    t0 = time.time()
    try:
        cli.ask({"cmd": "hello"}, 120)
        r = cli.ask({"cmd": "load", "weights_dir": str(svc.weights_dir()), "device": s.device, "max_context": s.max_context,
                     "threads": s.cpu_threads or 2, "verify_files": True}, s.load_timeout_s)
        if not r.get("ok"):
            return _save({**base, "status": "BLOCKED", "verdict": {"positive": False, "reason": f"model: {r.get('code')}: {r.get('error')}"}})
        load_info = r["info"]
        for j, i in enumerate(origins):
            ctx = bars[i - L:i]
            fut = bars[i:i + H]
            y_raw, info = cal.future(int(ctx[-1]["t_raw"]), tf_sec, H)
            if y_raw is None or [int(b["t_raw"]) for b in fut] != y_raw:
                skipped["calendar"] += 1
                continue
            off = int(ctx[-1]["t_raw"]) - int(datetime.fromisoformat(ctx[-1]["open_utc"].replace("Z", "+00:00")).timestamp())

            def fmt(raw):
                sec = raw if s.timestamp_basis == "SERVER" else raw - off
                return datetime.fromtimestamp(sec, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            vol = None
            if q["volume_source"] == "REAL_VOLUME":
                vol = [float(b.get("rv") or 0) for b in ctx]
            elif q["volume_source"] == "TICK_VOLUME":
                vol = [float(b.get("tv") or 0) for b in ctx]
            req = {"cmd": "predict", "candles": {"t": [fmt(int(b["t_raw"])) for b in ctx], "open": [b["o"] for b in ctx], "high": [b["h"] for b in ctx],
                                                 "low": [b["l"] for b in ctx], "close": [b["c"] for b in ctx], "volume": vol},
                   "y_t": [fmt(x) for x in y_raw], "pred_len": H, "T": s.temperature, "top_k": s.top_k, "top_p": s.top_p,
                   "seed": (int(ctx[-1]["t_raw"]) * 31 + H) & 0x7FFFFFFF, "paths": 0}
            r = cli.ask(req, s.request_timeout_s)
            if not r.get("ok"):
                skipped["error"] += 1
                continue
            last = float(ctx[-1]["c"])
            prev = float(bars[i - 1 - H]["c"]) if i - 1 - H >= 0 else last
            rows.append({"t": ctx[-1]["open_utc"], "split": "DEV" if j < n_dev else "TEST", "last": last, "pred": float(r["pred"]["close"][-1]),
                         "actual": float(fut[-1]["c"]), "atr": Q.atr(ctx, 14) or 0.0, "momentum": last - prev, "ms": r.get("ms")})
            if progress:
                progress(j + 1, len(origins))
    finally:
        cli.close()
    dev = [x for x in rows if x["split"] == "DEV"]
    test = [x for x in rows if x["split"] == "TEST"]
    k_best, dev_scores = 0.25, []
    for k in GRID:
        acc, n = _dir_acc(dev, k)
        dev_scores.append({"k": k, "accuracy": acc, "n": n})
    good = [d for d in dev_scores if d["n"] >= 30 and d["accuracy"] is not None]
    if good:
        k_best = max(good, key=lambda d: (d["accuracy"], -d["k"]))["k"]
    acc, n_dir = _dir_acc(test, k_best)
    mom_acc, _ = _dir_acc(test, k_best, momentum=True)
    mae_k = _mean(abs(x["pred"] - x["actual"]) for x in test)
    mae_n = _mean(abs(x["last"] - x["actual"]) for x in test)
    hits = round(acc * n_dir) if acc is not None else 0
    p = binom_p_greater(hits, n_dir) if n_dir else None
    reasons = []
    if kind == "SYNTHETIC":
        reasons.append("dane SYNTETYCZNE (symulator) – walidacja nie dotyczy rynku")
    if n_dir < 100:
        reasons.append(f"za mało obserwacji kierunku w teście ({n_dir} < 100)")
    if mae_k is None or mae_n is None or mae_k >= mae_n:
        reasons.append("MAE Kronos nie jest niższe od prognozy ostatniej ceny")
    if acc is None or mom_acc is not None and acc <= mom_acc:
        reasons.append("trafność kierunku nie przewyższa bazowego momentum")
    if p is None or p >= 0.05:
        reasons.append(f"trafność kierunku nieistotna statystycznie (p = {p if p is None else round(p, 4)})")
    rep = {**base, "status": "DONE", "finished_at": iso(utcnow()), "duration_s": round(time.time() - t0, 1), "horizon_bars": H, "lookback": L,
           "bars_used": len(bars), "first_bar": bars[0]["open_utc"], "last_bar": bars[-1]["open_utc"], "origins": len(origins),
           "evaluated": {"dev": len(dev), "test": len(test)}, "skipped": skipped, "load": load_info,
           "dev": {"grid": dev_scores, "chosen_band_k": k_best, "note": "jedyny wybierany parametr – tylko na DEV"},
           "test": {"n": len(test), "mae_kronos": mae_k, "mae_naive_last_price": mae_n,
                    "skill_vs_naive": (1 - mae_k / mae_n) if (mae_k is not None and mae_n) else None,
                    "direction_n": n_dir, "direction_accuracy": acc, "momentum_accuracy_same_cases": mom_acc, "binomial_p_vs_50pct": p,
                    "first": test[0]["t"] if test else None, "last": test[-1]["t"] if test else None,
                    "mean_compute_ms": _mean(x["ms"] for x in test)},
           "verdict": {"positive": not reasons, "reason": "; ".join(reasons) if reasons else
                       "pozytywna w teście końcowym (warunek konieczny do włączenia jako warunku strategii – nie dowód przewagi handlowej)"},
           "rows": rows[-400:]}
    return _save(rep)


def _dir_acc(rows: list[dict], k: float, momentum: bool = False) -> tuple[float | None, int]:
    hits = n = 0
    for x in rows:
        band = k * x["atr"]
        act = x["actual"] - x["last"]
        prd = x["pred"] - x["last"]
        if abs(act) <= band or abs(prd) <= band:
            continue
        guess = x["momentum"] if momentum else prd
        if guess == 0:
            continue
        n += 1
        hits += 1 if (guess > 0) == (act > 0) else 0
    return (hits / n if n else None), n


def _mean(it) -> float | None:
    xs = [float(x) for x in it if x is not None]
    return sum(xs) / len(xs) if xs else None


def _save(rep: dict) -> dict:
    rid = f"{rep['instrument']}_{rep['timeframe']}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    rep["report_id"] = rid
    (reports_dir() / f"{rid}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return rep
