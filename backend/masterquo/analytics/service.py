"""AnalyticsService - feeds the shared analytics from the bot's own CLOSED bars (MarketBridge, same session; never a second
MT5 connection). Observational only: no reference to the executor, the risk engine or the execution permission.

Flow per TF on a new closed bar (key = last bar open + revision + config hash):
  BB + MAs (inline, cheap) -> Double Bottom causal scan (configured TFs) -> FFT / EMD / VMD queued to ONE worker thread
  (latest job per TF wins; a result computed for an older key or configuration is discarded, never shown as current).
Every new result is archived in `analytics_snapshots` (decision-time history; a later, longer computation never rewrites it)
and every new Double Bottom state is an event in `pattern_events` (first state per pattern_id and status).
Explanations are generated only from these structured results.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

from ..timeutil import iso, utcnow
from . import contract, double_bottom as DB, signal as SG, ta
from .library import PatternLibrary

HEAVY = ("fft", "emd", "vmd")
LIGHT = ("bollinger", "moving_averages", "double_bottom")


def _strip(r: dict) -> dict:
    """Result without long arrays (for WS / list views and DB snapshots)."""
    v = dict(r.get("values") or {})
    for k in ("series", "spectrum"):
        v.pop(k, None)
    return {**r, "values": v}


class AnalyticsService:
    def __init__(self, cfg_store, bridge, db, bus, log):
        self.cfg_store, self.bridge, self.db, self.bus, self.log = cfg_store, bridge, db, bus, log
        self.library = PatternLibrary(db, self.db_cfg)
        self.library.mark_interrupted()                 # a job RUNNING before a restart is INTERRUPTED (resumable), never complete
        self.state: dict[str, dict] = {}
        self.keys: dict[str, str] = {}
        self.pending: dict[str, tuple] = {}
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self.lat: dict[str, list[float]] = {}
        self.errors: list[dict] = []
        self.counters = {"computed": 0, "discarded_stale": 0, "cache_hits": 0, "timeouts": 0}
        self.cache: dict[tuple, dict] = {}

    # ------------------------------------------------------------ config
    def cfg(self):
        return self.cfg_store.get().analytics

    def db_cfg(self) -> dict:
        a = self.cfg()
        return {**DB.DEFAULT, "mode": a.db_mode, "min_separation": a.db_min_separation, "max_separation": a.db_max_separation,
                "max_bottom_diff_frac": a.db_max_bottom_diff_frac, "min_depth_pct": a.db_min_depth_pct}

    def sig_cfg(self) -> dict:
        a = self.cfg()
        return {**SG.DEFAULT, "window": a.signal_window, "min_window": min(128, a.signal_window), "fft_input": a.fft_input, "vmd_k": a.vmd_k,
                "vmd_alpha": a.vmd_alpha, "vmd_max_iter": a.vmd_max_iter, "emd_max_imfs": a.emd_max_imfs}

    def bb_cfg(self) -> dict:
        a = self.cfg()
        return {**ta.DEFAULT_BB, "period": a.bb_period, "k": a.bb_k, "squeeze_lookback": a.bb_squeeze_lookback, "squeeze_pct": a.bb_squeeze_pct}

    def config_hash(self) -> str:
        return contract.config_hash(self.cfg().model_dump())

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        threading.Thread(target=self._loop, name="analytics", daemon=True).start()
        threading.Thread(target=self._worker, name="analytics-heavy", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:                       # analytics never affect the bot
                self._err("loop", exc)
            self._stop.wait(2.0)

    def _err(self, where: str, exc: Exception) -> None:
        self.errors.append({"at": iso(utcnow()), "where": where, "error": f"{type(exc).__name__}: {exc}"[:300]})
        self.errors = self.errors[-50:]

    def _lat(self, module: str, ms: float | None) -> None:
        if ms is not None:
            v = self.lat.setdefault(module, [])
            v.append(ms)
            del v[:-200]

    # ------------------------------------------------------------ main step
    def tick(self, now: datetime | None = None) -> None:
        a = self.cfg()
        if not a.enabled:
            return
        sym = self.cfg_store.get().mt5.symbol
        if getattr(self, "_sym", None) != sym:              # asset switch: nothing of the previous symbol survives
            self.state.clear()
            self.keys.clear()
            self.cache.clear()
            self.pending.clear()
            self._sym = sym
        h = self.config_hash() + "|" + sym
        changed = False
        for tf in a.timeframes:
            bars = [b for b in self.bridge.bars(tf, a.bars, include_forming=False) if b.get("open_utc")]
            st = self.state.setdefault(tf, {})
            if not bars:
                st.update(status="unavailable", reason="brak zamkniętych świec z MT5")
                continue
            key = f"{bars[-1]['open_utc']}|{bars[-1].get('revision')}|{h}"
            stale = self._stale(bars, tf, now)
            st.update(status="stale" if stale else "ready", reason="dane nieaktualne (brak nowych zamknięć)" if stale else None,
                      last_close_utc=ta.TF_SEC.get(tf) and _close(bars[-1]["open_utc"], tf), bars=len(bars))
            if self.keys.get(tf) == key:
                continue
            self.keys[tf] = key
            changed = True
            bb = ta.bb_analysis(bars, self.bb_cfg(), symbol=sym, tf=tf)
            ma = ta.ma_analysis(bars, a.mas, symbol=sym, tf=tf, bb_period=a.bb_period)
            st["bollinger"], st["moving_averages"] = bb, ma
            self._lat("bollinger", bb.get("latency_ms"))
            self._lat("moving_averages", ma.get("latency_ms"))
            self._archive(bb)
            self._archive(ma)
            if tf in a.db_timeframes:
                d = DB.scan_causal(bars, self.db_cfg(), symbol=sym, tf=tf)
                st["double_bottom"] = d
                self._lat("double_bottom", d.get("latency_ms"))
                self._archive(d)
                self._pattern_event(d)
            if a.signal_enabled and tf in a.signal_timeframes:
                with self._cv:
                    self.pending[tf] = (key, bars, sym, self.sig_cfg(), a.timeout_seconds)
                    self._cv.notify()
        if changed:
            self.bus.publish("analytics", self.summary())

    def _stale(self, bars, tf, now) -> bool:
        now = now or datetime.now(timezone.utc)
        last_close = datetime.fromisoformat(_close(bars[-1]["open_utc"], tf).replace("Z", "+00:00"))
        return (now - last_close).total_seconds() > 3 * ta.TF_SEC.get(tf, 60) + 120

    def _worker(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self.pending and not self._stop.is_set():
                    self._cv.wait(1.0)
                if self._stop.is_set():
                    return
                tf, job = self.pending.popitem()
            key, bars, sym, cfg, timeout = job
            for mod, fn in (("fft", SG.fft_analysis), ("emd", SG.emd_analysis), ("vmd", SG.vmd_analysis)):
                ck = (mod, tf, key)
                try:
                    if ck in self.cache:
                        r = self.cache[ck]
                        self.counters["cache_hits"] += 1
                    else:
                        t0 = time.perf_counter()
                        r = fn(bars, tf, cfg, sym, timeout) if mod == "vmd" else fn(bars, tf, cfg, sym)
                        if (time.perf_counter() - t0) > timeout:
                            self.counters["timeouts"] += 1
                            r = {**r, "status": "error", "reason": f"TIMEOUT > {timeout}s", "values": None}
                        self.cache[ck] = r
                        if len(self.cache) > 300:
                            self.cache.pop(next(iter(self.cache)))
                except Exception as exc:
                    self._err(mod, exc)
                    r = contract.result(mod, "?", cfg, symbol=sym, tf=tf, bars=bars, status="error", reason=f"{type(exc).__name__}: {exc}"[:200])
                if self.keys.get(tf) != key:                   # late result of an older bar / configuration: never shown as current
                    self.counters["discarded_stale"] += 1
                    continue
                self.state.setdefault(tf, {})[mod] = r
                self.counters["computed"] += 1
                self._lat(mod, r.get("latency_ms"))
                self._archive(r)
            self.bus.publish("analytics", self.summary())

    # ------------------------------------------------------------ persistence
    def _archive(self, r: dict) -> None:
        if not r.get("as_of"):
            return
        try:
            self.db.execute("""INSERT OR IGNORE INTO analytics_snapshots(created_at, snapshot_id, module, symbol, timeframe, as_of, available_at, status, payload)
                               VALUES (?,?,?,?,?,?,?,?,?)""", (iso(utcnow()), r["snapshot_id"], r["module"], r["symbol"], r["timeframe"], r["as_of"],
                                                              r["available_at"], r["status"], json.dumps(_strip(r), default=str)))
            self.counters["archived"] = self.counters.get("archived", 0) + 1
            if self.counters["archived"] % 500 == 0:
                keep = self.cfg().snapshot_retention
                self.db.execute("DELETE FROM analytics_snapshots WHERE id <= (SELECT MAX(id) FROM analytics_snapshots) - ?", (keep,))
        except Exception as exc:
            self._err("archive", exc)

    def _pattern_event(self, d: dict) -> None:
        v = d.get("values") or {}
        if d.get("status") != "ready" or v.get("status") in (None, "INVALID"):
            return
        self.db.execute("""INSERT OR IGNORE INTO pattern_events(created_at, pattern_id, symbol, timeframe, status, available_at, payload)
                           VALUES (?,?,?,?,?,?,?)""", (iso(utcnow()), v["pattern_id"], d["symbol"], d["timeframe"], v["status"], d["available_at"],
                                                      json.dumps(_strip(d), default=str)))
        # v2 history (PMW-UPD-07 R07): every status CHANGE per (pattern, rules version, config) is kept, incl. later cycles
        ver, ch = d.get("algorithm_version") or "?", d.get("config_hash") or "?"
        last = self.db.one("SELECT status FROM pattern_events_v2 WHERE pattern_id=? AND rules_version=? ORDER BY id DESC LIMIT 1", (v["pattern_id"], ver))
        if not last or last["status"] != v["status"]:
            n = self.db.one("SELECT COUNT(*) AS n FROM pattern_events_v2 WHERE pattern_id=? AND rules_version=?", (v["pattern_id"], ver))["n"]
            self.db.execute("""INSERT OR IGNORE INTO pattern_events_v2(created_at, event_key, pattern_id, rules_version, symbol, timeframe, status, available_at, payload)
                               VALUES (?,?,?,?,?,?,?,?,?)""", (iso(utcnow()), f"{v['pattern_id']}|{ver}|{ch}|{n}|{v['status']}", v["pattern_id"], ver,
                                                             d["symbol"], d["timeframe"], v["status"], d["available_at"], json.dumps(_strip(d), default=str)))

    # ------------------------------------------------------------ views
    def tf_state(self, tf: str, full: bool = False) -> dict:
        st = self.state.get(tf) or {}
        return {k: (v if full or not isinstance(v, dict) else _strip(v)) for k, v in st.items()}

    def summary(self) -> dict:
        return {"enabled": self.cfg().enabled, "influence": self.cfg().influence, "config_hash": self.config_hash(),
                "timeframes": {tf: self.tf_state(tf) for tf in self.cfg().timeframes}, "support": self.support(), "updated_at": iso(utcnow())}

    def history(self, module: str | None, tf: str | None, limit: int = 100) -> list[dict]:
        q, a = "SELECT * FROM analytics_snapshots WHERE 1=1", []
        if module:
            q += " AND module=?"
            a.append(module)
        if tf:
            q += " AND timeframe=?"
            a.append(tf)
        rows = self.db.query(q + " ORDER BY id DESC LIMIT ?", (*a, limit))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def events(self, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT id, created_at, pattern_id, symbol, timeframe, status, available_at FROM pattern_events ORDER BY id DESC LIMIT ?", (limit,))
        return rows

    def diagnostics(self) -> dict:
        def pct(v, q):
            s = sorted(v)
            return round(s[int(q * (len(s) - 1))], 2) if s else None
        return {"latency_ms": {m: {"p50": pct(v, .5), "p95": pct(v, .95), "n": len(v)} for m, v in self.lat.items()}, "counters": self.counters,
                "queue": len(self.pending), "errors": self.errors[-10:], "keys": self.keys, "cache_size": len(self.cache),
                "versions": {"ta": ta.VERSION, "fft": SG.FFT_VERSION, "emd": SG.EMD_VERSION, "vmd": SG.VMD_VERSION, "double_bottom": DB.VERSION,
                             "double_bottom_ext": DB.VERSION_EXT}}

    def support(self, main_tf: str = "M5", ctx_tf: str = "H1") -> dict:
        """'Co wspiera analizę' - grouped by phenomenon, built ONLY from structured results. No probability, no direction vote."""
        m, c = self.state.get(main_tf) or {}, self.state.get(ctx_tf) or {}
        groups: list[dict] = []
        lines: list[str] = []
        d = (m.get("double_bottom") or {}).get("values") or {}
        if d.get("status") in ("CANDIDATE", "CONFIRMED", "FAILED"):
            neck = d["coordinates"]["neckline"]["price"]
            groups.append({"group": "struktura", "source": f"Double Bottom {main_tf}", "state": d["status"], "detail": f"neckline {neck}"})
            lines.append({"CANDIDATE": f"Struktura podwójnego dna wykryta na {main_tf}; czekamy na zamknięcie świecy ponad neckline {neck}.",
                          "CONFIRMED": f"Podwójne dno na {main_tf} potwierdzone pierwszym zamknięciem ponad neckline {neck}.",
                          "FAILED": f"Podwójne dno na {main_tf} nieudane – pierwsze rozstrzygające zamknięcie pod dołkami."}[d["status"]])
        else:
            groups.append({"group": "struktura", "source": f"Double Bottom {main_tf}", "state": "BRAK", "detail": d.get("reason") or "brak danych"})
        for tf, st in ((main_tf, m), (ctx_tf, c)):
            mv = (st.get("moving_averages") or {}).get("values")
            if mv:
                groups.append({"group": "trend", "source": f"MAs {tf}", "state": mv["context"], "detail": mv["context_rule"]})
        mc = ((c.get("moving_averages") or {}).get("values") or {}).get("context")
        if mc in ("TREND_DOWN", "TREND_UP"):
            lines.append(f"Średnie na {ctx_tf} wskazują {'trend spadkowy' if mc == 'TREND_DOWN' else 'trend wzrostowy'} – kontekst wymaga uwagi przy scenariuszu przeciwnym.")
        bv = (m.get("bollinger") or {}).get("values")
        if bv:
            st = "SQUEEZE" if bv["squeeze"] else "EXPANDING" if bv["expanding"] else "NORMAL"
            groups.append({"group": "zmienność", "source": f"BB {main_tf}", "state": st, "detail": "; ".join(bv["interpretation"])})
            if bv.get("trend_walk"):
                lines.append(f"Cena na {main_tf} porusza się wzdłuż {'górnego' if bv['trend_walk'] == 'UP' else 'dolnego'} pasma Bollingera – w trendzie nie jest to sygnał odwrotu.")
        cyc = []
        for mod in HEAVY:
            r = m.get(mod) or {}
            ok = r.get("status") == "ready" and (r.get("values") or {}).get("quality_ok")
            cyc.append(f"{mod.upper()}: {'stabilny' if ok else (r.get('reason') or ', '.join(r.get('quality_flags') or []) or r.get('status') or 'brak')}")
            if r and not ok:
                lines.append(f"{mod.upper()} nie dostarczyło stabilnego wyniku na {main_tf}, więc nie wpływa na opis scenariusza.")
        groups.append({"group": "cykliczność", "source": f"FFT/EMD/VMD {main_tf}", "state": "OPISOWO", "detail": "; ".join(cyc),
                       "note": "trzy transformacje tej samej ceny – nie trzy niezależne potwierdzenia"})
        dq = [tf for tf, st in self.state.items() if st.get("status") in ("stale", "unavailable")]
        groups.append({"group": "jakość danych", "source": "MT5", "state": "OK" if not dq else "PROBLEM", "detail": ", ".join(dq) or "wszystkie TF aktualne"})
        if dq:
            lines.append(f"Analiza wstrzymana dla {', '.join(dq)} – brak świeżych danych.")
        return {"main_tf": main_tf, "context_tf": ctx_tf, "groups": groups, "explanation": lines,
                "influence": "OBSERVE – opis analizy; nie zmienia decyzji, ryzyka ani blokady wykonania"}


def _close(open_utc: str, tf: str) -> str:
    t = datetime.fromisoformat(open_utc.replace("Z", "+00:00")).timestamp() + ta.TF_SEC.get(tf, 60)
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
