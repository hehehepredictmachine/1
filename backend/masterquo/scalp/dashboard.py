"""MTFContextSnapshot (PMW-UPD-05 Multi TimeFrame Scalping Dashboard) - adapter of the EXISTING scalp state, not a new engine.

build()     after every recompute of ScalpService (new closed M1 / reconnect): one snapshot of the SAME bar set the strategy just
            used (one instrument, one session epoch, one as_of = close of the last closed M1, per-TF revisions), the machine state
            (range, directions, journal), the stored gate results of the evaluated candidates and the compatible model outputs.
heartbeat() once per second WITHOUT recomputing indicators: connection, quote age, per-TF freshness against the expected next close
            -> live_health (a green status can never stay forever without a new M1). The stored analysis is never rewritten.
chart()     bars of one TF for a snapshot (cutoff = as_of, closed bars only) + separate forming preview + overlays with ids / source TF /
            available_at. Live snapshots live in a short cache (10 / 60 s); the compact snapshot (no series) is archived in the database
            (mtf_snapshots) - an archived snapshot is never replaced by "latest".
The dashboard roles of the TFs come from the profile (context filter mode BOTH / ANY / ANY_PLUS_H1), not from a TF vote.
"""
from __future__ import annotations

import collections
import hashlib
import json
import threading
import time
from datetime import datetime, timezone

from ..timeutil import iso, utcnow
from . import indicators as ind
from . import strategy as st

SCHEMA = "PMW-MTF-SNAPSHOT-1"
TFS = (("H1", 3600), ("M30", 1800), ("M15", 900), ("M5", 300), ("M1", 60))
CACHE_N, CACHE_S = 10, 60
RECEIVE_GRACE_S = 15


def roles(prof: dict) -> dict:
    mode = st.V(prof, "context_filter", "mode", default="BOTH")
    enabled = st.V(prof, "context_filter", "enabled")
    filt = ("M30", "M15", "H1") if mode == "ANY_PLUS_H1" else ("M30", "M15")
    ctx_txt = lambda tf: (f"filtr kontekstu ({mode})" if enabled and tf in filt else "kontekst informacyjny (nie bierze udziału w filtrze profilu)")  # noqa: E731
    return {"H1": {"role": "KONTEKST_SZERSZY", "label": "Szerszy kontekst", "required": tf_required("H1", prof), "use": ctx_txt("H1")},
            "M30": {"role": "KONTEKST_FILTR", "label": "Kontekst i ograniczenia", "required": tf_required("M30", prof), "use": ctx_txt("M30")},
            "M15": {"role": "KONTEKST_LOKALNY", "label": "Kontekst lokalny", "required": tf_required("M15", prof), "use": ctx_txt("M15")},
            "M5": {"role": "ZAKRES", "label": "Zakres i setup", "required": True, "use": "zamrożony range, strefy, ATR(M5)"},
            "M1": {"role": "TRIGGER", "label": "Trigger i potwierdzenie", "required": True, "use": "sweep / reclaim / potwierdzenie / retest"}}


def tf_required(tf: str, prof: dict) -> bool:
    if not st.V(prof, "context_filter", "enabled"):
        return False
    mode = st.V(prof, "context_filter", "mode", default="BOTH")
    return tf in (("M30", "M15", "H1") if mode == "ANY_PLUS_H1" else ("M30", "M15"))


def _r(x, n=5):
    return None if x is None else round(float(x), n)


class MTFDashboard:
    def __init__(self, scalp, bridge, bus, db=None):
        self.scalp, self.bridge, self.bus, self.db = scalp, bridge, bus, db
        self.cache: collections.OrderedDict = collections.OrderedDict()      # snapshot_id -> (created monotonic, snapshot, bars)
        self.seq = 0
        self.last = None
        self.si = None                    # PMW-UPD-07 Structure Intelligence (cells on the SAME bar set, parent = this snapshot)
        self.health = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._th = None

    # -------------------------------------------------- lifecycle (heartbeat thread)
    def start(self) -> None:
        self._th = threading.Thread(target=self._loop, name="mtf-heartbeat", daemon=True)
        self._th.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        last_pub = None
        while not self._stop.is_set():
            try:
                h = self.heartbeat()
                key = (h.get("overall"), h.get("connection"), tuple(r["data_status"] for r in h.get("timeframes", [])), h.get("quote_status"))
                if key != last_pub or int(time.time()) % 5 == 0:
                    self.bus.publish("scalp_dashboard_health", h)
                    last_pub = key
            except Exception:  # noqa: BLE001 - presentation only
                pass
            self._stop.wait(1.0)

    # -------------------------------------------------- freshness (no recompute)
    def _tf_status(self, tf: str, secs: int, last_open: str | None, now: float, conn: str, required: bool) -> dict:
        if not last_open:
            return {"data_status": "MISSING" if required else "NOT_APPLICABLE", "expected_next_close": None, "freshness_deadline": None,
                    "reasons": ["brak zamkniętych świec"]}
        close = st.ts(last_open) + secs
        nxt = close + secs
        deadline = nxt + RECEIVE_GRACE_S
        reasons = []
        if conn != "CONNECTED":
            status = "DISCONNECTED"
            reasons.append(f"MT5: {conn}")
        elif now > deadline:
            status = "STALE"
            reasons.append(f"brak nowej świecy {tf} od {round(now - close)} s (oczekiwana do {iso(datetime.fromtimestamp(deadline, timezone.utc))})")
        else:
            status = "OK"
        return {"data_status": status, "expected_next_close": iso(datetime.fromtimestamp(nxt, timezone.utc)),
                "freshness_deadline": iso(datetime.fromtimestamp(deadline, timezone.utc)), "reasons": reasons}

    def _session(self, now: float, quote_ok: bool) -> str:
        d = datetime.fromtimestamp(now, timezone.utc)
        if quote_ok:
            return "QUOTES_FLOWING"
        if d.weekday() == 5 or (d.weekday() == 6 and d.hour < 21) or (d.weekday() == 4 and d.hour >= 22):
            return "WEEKEND_TYPICAL_CLOSE (harmonogram brokera niezweryfikowany)"
        return "SESSION_UNKNOWN / NO_RECENT_DATA"

    def heartbeat(self) -> dict:
        now = time.time()
        conn = getattr(self.bridge, "state", "UNKNOWN")
        q = self.bridge.quote_status() or {}
        ttl = st.V(self.scalp.prof, "risk", "quote_ttl_s")
        age = q.get("age_seconds")
        q_ok = bool(q.get("bid") and q.get("ask") and age is not None and age <= ttl)
        rl = roles(self.scalp.prof)
        rows = []
        for tf, secs in TFS:
            bb = self.bridge.bars(tf, 1, include_forming=False)
            r = self._tf_status(tf, secs, bb[-1]["open_utc"] if bb else None, now, conn, rl[tf]["required"])
            rows.append({"tf": tf, **r})
        req_bad = [r for r in rows if r["data_status"] not in ("OK", "NOT_APPLICABLE") and (rl[r["tf"]]["required"] or r["tf"] in ("M1", "M5"))]
        overall = "DISCONNECTED" if conn != "CONNECTED" else "STALE" if req_bad else "OK"
        snap = self.last
        h = {"server_now": iso(datetime.fromtimestamp(now, timezone.utc)), "asset": self.scalp.inst, "connection": conn,
             "session_epoch": str(getattr(self.bridge, "session_epoch", None)), "overall": overall, "timeframes": rows,
             "quote": {k: q.get(k) for k in ("bid", "ask", "time_utc")} | {"age_s": age, "ttl_s": ttl, "spread": (q["ask"] - q["bid"]) if q.get("bid") and q.get("ask") else None},
             "quote_status": "OK" if q_ok else "STALE_OR_MISSING", "market_session_status": self._session(now, q_ok),
             "analysis_snapshot_id": snap["snapshot_id"] if snap else None,
             "analysis_valid": bool(snap) and now <= datetime.fromisoformat(snap["expires_at"]).timestamp() and overall == "OK"}
        self.health = h
        return h

    # -------------------------------------------------- snapshot (after a recompute)
    def build(self, bars: dict, *, info: dict, epoch, recent: list[dict], nss_last: dict | None, t0: float | None = None) -> dict:
        t_start = time.perf_counter()
        sc, prof = self.scalp, self.scalp.prof
        now = utcnow()
        m1 = bars.get("M1") or []
        as_of = st.ts(m1[-1]["open_utc"]) + 60 if m1 else None
        rl = roles(prof)
        revs = {tf: {"last_open": (bars.get(tf) or [{}])[-1].get("open_utc"), "revision": (bars.get(tf) or [{}])[-1].get("revision"), "n": len(bars.get(tf) or [])}
                for tf, _ in TFS}
        conn = getattr(self.bridge, "state", "UNKNOWN")
        clock = ((self.bridge.connection_status() or {}).get("clock") or {}) if hasattr(self.bridge, "connection_status") else {}
        ctx_series = {"H1": sc.machine.h1, "M30": sc.machine.m30, "M15": sc.machine.m15} if sc.machine else {}
        s_max, bw_p = st.V(prof, "context_filter", "slope_atr_per_bar"), st.V(prof, "context_filter", "bandwidth_percentile")
        rows = []
        tnow = now.timestamp()
        for tf, secs in TFS:
            b = [x for x in (bars.get(tf) or []) if st.ts(x["open_utc"]) + secs <= (as_of or 0)]
            need = 30 if tf != "M5" else max(st.V(prof, "range", "lookback_m5_bars"), 25)
            fr = self._tf_status(tf, secs, b[-1]["open_utc"] if b else None, tnow, conn, rl[tf]["required"])
            row = {"tf": tf, "seconds": secs, **rl[tf], "source": (b[-1].get("source") if b else None) or ("SYNTHETIC" if getattr(self.bridge, "synthetic", False) else "MT5"),
                   "revision": revs[tf]["revision"], "bars_count": len(b), "required_bars": need,
                   "last_closed_open": b[-1]["open_utc"] if b else None, "last_closed_close": iso(datetime.fromtimestamp(st.ts(b[-1]["open_utc"]) + secs, timezone.utc)) if b else None,
                   "available_at": b[-1].get("available_at") if b else None, "availability_basis": (b[-1].get("basis") if b else None), **fr}
            if len(b) < need and row["data_status"] == "OK":
                row["data_status"] = "WARMING_UP"
                row["reasons"] = row["reasons"] + [f"{len(b)} < {need} zamkniętych świec"]
            if tf in ctx_series:
                c = st.context(ctx_series[tf], prof)
                row["indicators"] = {"sar_trend": c.get("sar_trend"), "slope_atr": _r(c.get("slope"), 4), "bw_pct": _r(c.get("bw_pct"), 3), "status": c.get("status")}
                row["regime_display"] = None if c.get("status") != "OK" else ("TREND_UP" if c["sar_trend"] == "UP" and c["slope"] > 0.1 else
                                                                              "TREND_DOWN" if c["sar_trend"] == "DOWN" and c["slope"] < -0.1 else "MIXED/RANGE")
                conds = []
                for side in ("BUY", "SELL"):
                    if c.get("status") != "OK":
                        conds.append({"side": side, "status": "UNKNOWN", "detail": "kontekst w rozgrzewce"})
                        continue
                    against = "DOWN" if side == "BUY" else "UP"
                    hit = c["sar_trend"] == against and abs(c["slope"]) > s_max and (c["slope"] < 0) == (against == "DOWN") and c["bw_pct"] > bw_p
                    conds.append({"side": side, "status": "CONFLICT" if hit else "MET", "participates": rl[tf]["required"],
                                  "detail": (f"silny trend przeciw {side}: SAR {c['sar_trend']}, nachylenie {c['slope']:.3f} (próg {s_max}), szer. pasm pct {c['bw_pct']:.2f} (próg {bw_p})"
                                             if hit else f"brak silnego trendu przeciw {side} (SAR {c['sar_trend']}, nachylenie {c['slope']:.3f}, pct {c['bw_pct']:.2f})")})
                row["context_conditions"] = conds
                row["regime_note"] = "etykieta wyświetlania (SAR + nachylenie 0.1) – nie jest bramką profilu; bramka = context_conditions wg trybu"
            elif tf in ("M5", "M1") and len(b) >= 20:
                c_, h_, l_ = [x["c"] for x in b[-300:]], [x["h"] for x in b[-300:]], [x["l"] for x in b[-300:]]
                a = ind.atr(h_, l_, c_)
                bbv = ind.bollinger(c_, a)[-1]
                row["indicators"] = {"atr14": _r(a[-1] if a else None), "bb_pct_b": _r(bbv.get("pct_b"), 3) if bbv else None}
            rows.append(row)
        # filter verdict per side exactly as the strategy computes it (BOTH / ANY / ANY_PLUS_H1)
        filt = {}
        if sc.machine:
            for side in ("BUY", "SELL"):
                ctx = {"M30": st.context(sc.machine.m30, prof), "M15": st.context(sc.machine.m15, prof), "H1": st.context(sc.machine.h1, prof)}
                blk, why = st.fade_blocked(ctx, side, prof)
                filt[side] = {"status": "UNKNOWN" if blk is None else "CONFLICT" if blk else "MET", "detail": why,
                              "mode": st.V(prof, "context_filter", "mode", default="BOTH")}
        mp = sc.machine.public() if sc.machine else None
        setups = self._setups(recent, mp, nss_last)
        q = self.bridge.quote_status() or {}
        ttl = st.V(prof, "risk", "quote_ttl_s")
        q_ok = bool(q.get("bid") and q.get("ask") and q.get("age_seconds") is not None and q["age_seconds"] <= ttl)
        body = {"schema_version": SCHEMA, "instrument_id": sc.inst, "asset": sc.inst, "broker_symbol": (info or {}).get("name") or getattr(self.bridge.cfg, "symbol", None),
                "session_epoch": str(epoch), "profile_id": prof["profile_id"], "profile_hash": st.profile_hash(prof), "strategy_id": "SCALP_RANGE_SWEEP_RETEST",
                "source": "SYNTHETIC" if getattr(self.bridge, "synthetic", False) else "MT5",
                "data_mode": "DANE SYNTETYCZNE" if getattr(self.bridge, "synthetic", False) else "LIVE",
                "as_of": iso(datetime.fromtimestamp(as_of, timezone.utc)) if as_of else None, "tf_revisions": revs, "connection": conn,
                "clock_status": clock.get("status") or "CLOCK_UNVERIFIED", "timeframes": rows, "context_filter": filt,
                "machine": mp, "setups": setups, "digits": (info or {}).get("digits"), "tick_size": (info or {}).get("trade_tick_size")}
        sid = "MTF-" + hashlib.sha256(json.dumps({k: body[k] for k in ("asset", "session_epoch", "as_of", "tf_revisions", "profile_hash")}, sort_keys=True,
                                                 default=str).encode() + json.dumps(setups, sort_keys=True, default=str).encode()).hexdigest()[:16]
        with self._lock:
            self.seq += 1
            seq = self.seq
        quality = "DISCONNECTED" if conn != "CONNECTED" else "OK" if all(r["data_status"] in ("OK", "NOT_APPLICABLE") or not (r["required"] or r["tf"] in ("M1", "M5"))
                                                                     for r in rows) else "DEGRADED"
        snap = dict(body, snapshot_id=sid, seq=seq, computed_at=iso(now), server_now=iso(now),
                    expires_at=iso(datetime.fromtimestamp((as_of or tnow) + 60 + RECEIVE_GRACE_S, timezone.utc)),
                    overall_data_quality=quality, market_session_status=self._session(tnow, q_ok),
                    quote={"bid": q.get("bid"), "ask": q.get("ask"), "quote_time": q.get("time_utc"), "age": q.get("age_seconds"), "ttl": ttl,
                           "status": "OK" if q_ok else "STALE_OR_MISSING", "note": "kwotowanie ma własny zegar – nie odmładza analizy"},
                    execution={"permission": False, "status": "SHADOW – EXECUTION_AUTHORIZED=false; Execution Lock bez zmian"},
                    chart_refs=[{"chart_id": f"mtf-{tf}", "tf": tf, "snapshot_id": sid, "revision": revs[tf]["revision"], "cutoff": body["as_of"],
                                 "endpoint": f"/api/v1/scalp/dashboard/chart?tf={tf}&snapshot_id={sid}"} for tf, _ in TFS],
                    warnings=[w for w in (["DANE SYNTETYCZNE"] if body["source"] == "SYNTHETIC" else []) + (["zegar serwera niezweryfikowany"] if clock.get("status") not in (None, "OK", "VERIFIED") else [])],
                    missing_dependencies=[d for d, ok in (("NSS: brak wybranego modelu", any(m.get("task_id") == "SCALP_SETUP_MARKET_V1" and m.get("status") == "READY_INFERENCE" for s_ in setups for m in s_["models"])),) if not ok],
                    timings={"build_ms": round((time.perf_counter() - t_start) * 1000, 2), "since_tick_ms": round((time.perf_counter() - t0) * 1000, 2) if t0 else None})
        if self.si is not None:
            try:
                closed = {tf: [x for x in (bars.get(tf) or []) if st.ts(x["open_utc"]) + secs <= (as_of or 0)] for tf, secs in TFS}
                si = self.si.snapshot(closed, sc.inst, float((info or {}).get("trade_tick_size") or 0.01), body["as_of"])
                snap["structure_intelligence"] = {"snapshot_id": si["snapshot_id"], "parent_snapshot_id": sid, "divergences": si["divergences"],
                                                  "forecast": si["forecast"], "profiles": si["profiles"], "build_ms": si["build_ms"],
                                                  "neutralization": si.get("neutralization"), "quotes": si.get("quotes")}
                for row in rows:
                    row["structure"] = dict(si["cells"].get(row["tf"]) or {}, parent_snapshot_id=sid)
            except Exception as exc:                            # noqa: BLE001 - structure layer failure never blocks the dashboard
                snap["structure_intelligence"] = {"status": "ERROR", "error": type(exc).__name__, "parent_snapshot_id": sid}
        with self._lock:
            self.cache[sid] = (time.monotonic(), snap, {tf: list(bars.get(tf) or []) for tf, _ in TFS})
            self._evict()
        self.last = snap
        self._archive(snap)
        self.bus.publish("scalp_dashboard", {k: snap[k] for k in ("snapshot_id", "seq", "asset", "session_epoch", "as_of", "computed_at", "expires_at", "overall_data_quality")})
        return snap

    def _evict(self) -> None:
        t = time.monotonic()
        while self.cache and (len(self.cache) > CACHE_N or t - next(iter(self.cache.values()))[0] > CACHE_S):
            if len(self.cache) == 1:
                break                                          # the newest live snapshot always stays
            self.cache.popitem(last=False)

    def _archive(self, snap: dict) -> None:
        if self.db is None:
            return
        try:
            self.db.execute("INSERT OR IGNORE INTO mtf_snapshots(snapshot_id, asset, session_epoch, as_of, computed_at, setup_ids, body) VALUES (?,?,?,?,?,?,?)",
                            (snap["snapshot_id"], snap["asset"], snap["session_epoch"], snap["as_of"], snap["computed_at"],
                             ",".join(s["setup_id"] for s in snap["setups"]), json.dumps(snap, default=str)))
        except Exception:  # noqa: BLE001
            snap["warnings"].append("ARCHIVE_WRITE_FAILED")

    # -------------------------------------------------- setups (stored gates of the evaluated candidates + live machine)
    def _setups(self, recent: list[dict], mp: dict | None, nss_last: dict | None) -> list[dict]:
        out = []
        r = (mp or {}).get("range") or {}
        for row in recent[:10]:
            plan = row.get("plan") if isinstance(row.get("plan"), dict) else json.loads(row.get("plan") or "{}")
            gates = row.get("gates") if isinstance(row.get("gates"), list) else json.loads(row.get("gates") or "[]")
            conds = [{"name": g["name"], "status": "MET" if g["ok"] else "MISSING", "detail": g.get("detail")} for g in gates]
            applicable = [c for c in conds if c["name"] != "uprawnienie wykonania"]
            models = self._models(plan, row, nss_last)
            out.append({"setup_id": row["setup_id"], "side": row["direction"], "state": row["status"], "range_id": plan.get("range_id"),
                        "signal_time": plan.get("decision_time"), "evaluated_at": row.get("created_at"), "conditions": conds,
                        "completeness": {"met": sum(c["status"] == "MET" for c in applicable), "of": len(applicable), "label": "Kompletność warunków (nie P(zysk))"},
                        "hard_gates": [c for c in conds if c["status"] != "MET"],
                        "trigger": {"confirmation": (plan.get("confirmation") or {}).get("family"), "zone": plan.get("zone"), "ref_close_bid": plan.get("ref_close_bid")},
                        "invalidation": {"inval_lo": r.get("inval_lo"), "inval_hi": r.get("inval_hi"), "note": "unieważnienie zakresu (M5)"} if r.get("range_id") == plan.get("range_id") else None,
                        "expiry": r.get("ttl_end") if r.get("range_id") == plan.get("range_id") else None,
                        "levels": [{"id": f"{row['setup_id']}:{k}", "kind": k.upper(), "price": plan.get(k), "source_tf": "M1"} for k in ("sl", "tp1", "tp2") if plan.get(k) is not None]
                        + ([{"id": f"{row['setup_id']}:entry", "kind": "ENTRY_SHADOW", "price": plan.get("fill_shadow"), "source_tf": "M1"}] if plan.get("fill_shadow") else []),
                        "outcome": {"status": row.get("outcome_status"), "net_r": row.get("net_r")}, "models": models,
                        "note": "hipotetyczne poziomy oglądanego planu (SHADOW) – to nie jest otwarta transakcja"})
        return out

    @staticmethod
    def _models(plan: dict, row: dict, nss_last: dict | None) -> list[dict]:
        out = []
        mb = plan.get("model_b") or {}
        out.append({"task_id": "SCALP_TASK_B_TP1_BEFORE_SL", "target_definition": "P(TP1 przed SL) – model B (gold_candles)", "status": mb.get("status") or ("READY" if mb.get("p") is not None else "NO_MODEL"),
                    "raw_output": mb.get("p"), "units": "prawdopodobieństwo zdarzenia", "role": "INFORMACYJNY"})
        ms = plan.get("ml_scalp") or {}
        out.append({"task_id": "SCALP_NET_PROFIT_MARKET_V1", "target_definition": "P(net_R cyklu > 0) + E[net_R]", "status": ms.get("status") or "NOT_INSTALLED",
                    "calibrated_output": ms.get("calibrated_probability"), "expected_net_r": ms.get("expected_net_r"), "model_hash": ms.get("model_hash"),
                    "role": ms.get("role"), "prediction_id": ms.get("prediction_id"), "expires_at": ms.get("expires_at"), "units": "prawdopodobieństwo / R"})
        if nss_last and nss_last.get("setup_id") == row["setup_id"] and nss_last.get("side") == row["direction"]:
            co = nss_last.get("candidate_output") or {}
            out.append({"task_id": "SCALP_SETUP_MARKET_V1", "target_definition": "P(TP1_FIRST/SL_FIRST/TIMEOUT) + E[net_R]", "status": nss_last.get("technical_status"),
                        "calibrated_output": co.get("calibrated_probabilities"), "raw_output": co.get("raw_probabilities"), "expected_net_r": co.get("expected_net_R"),
                        "model_hash": nss_last.get("model_hash"), "role": nss_last.get("mode"), "inference_id": nss_last.get("inference_id"),
                        "expires_at": nss_last.get("expires_at"), "units": "rozkład zdarzeń / R"})
        else:
            out.append({"task_id": "SCALP_SETUP_MARKET_V1", "target_definition": "P(TP1_FIRST/SL_FIRST/TIMEOUT) + E[net_R]",
                        "status": "NOT_LINKED" if nss_last else "NO_INFERENCE", "note": "brak wyniku NSS dla tego setupu i strony (nie podstawiono innego)"})
        return out

    # -------------------------------------------------- read side
    def get(self, sid: str | None) -> dict | None:
        if sid is None:
            return self.last
        with self._lock:
            hit = self.cache.get(sid)
        if hit:
            return hit[1]
        if self.db is not None:
            row = self.db.one("SELECT body FROM mtf_snapshots WHERE snapshot_id=?", (sid,))
            if row:
                return dict(json.loads(row["body"]), archived=True)
        return None

    def snapshots(self, setup_id: str | None, limit: int = 50, before: str | None = None) -> list[dict]:
        if self.db is None:
            return []
        q, a = "SELECT snapshot_id, asset, session_epoch, as_of, computed_at, setup_ids FROM mtf_snapshots WHERE asset=?", [self.scalp.inst]
        if setup_id:
            q += " AND (',' || setup_ids || ',') LIKE ?"
            a.append(f"%,{setup_id},%")
        if before:
            q += " AND computed_at < ?"
            a.append(before)
        return self.db.query(q + " ORDER BY computed_at DESC LIMIT ?", (*a, limit))

    def chart(self, tf: str, sid: str, n: int = 400) -> dict:
        secs = dict(TFS).get(tf)
        if secs is None:
            return {"status": "UNKNOWN_TF"}
        with self._lock:
            hit = self.cache.get(sid)
        if hit:
            snap, bars, src = hit[1], hit[2].get(tf) or [], "LIVE_SNAPSHOT_CACHE"
        else:
            snap = self.get(sid)
            if snap is None:
                return {"status": "SNAPSHOT_EXPIRED", "snapshot_id": sid, "reason": "snapshot live wygasł z pamięci podręcznej – pobierz aktualny (resync)"}
            if snap.get("asset") != self.scalp.inst:
                return {"status": "ASSET_MISMATCH", "snapshot_id": sid}
            bars, src = self.bridge.bars(tf, None, include_forming=False), "BRIDGE_BUFFER_CUTOFF"
        cut = st.ts(snap["as_of"]) if snap.get("as_of") else 0
        closed = [b for b in bars if st.ts(b["open_utc"]) + secs <= cut and b.get("closed", True)]
        rev = (snap.get("tf_revisions") or {}).get(tf) or {}
        if src == "BRIDGE_BUFFER_CUTOFF":
            if not closed or closed[-1]["open_utc"] != rev.get("last_open"):
                first = bars[0]["open_utc"] if bars else None
                return {"status": "ARCHIVE_BARS_UNAVAILABLE", "snapshot_id": sid, "tf": tf, "history_from": first,
                        "reason": "bufor MT5 nie zawiera już świec tego snapshotu (lub zostały zrewidowane) – brak archiwum serii"}
        closed = closed[-max(50, min(n, 600)):]
        c, h, lo = [b["c"] for b in closed], [b["h"] for b in closed], [b["l"] for b in closed]
        a = ind.atr(h, lo, c) if len(closed) > 15 else []
        bb = ind.bollinger(c, a) if len(c) >= 20 and a else []
        sar = ind.sar_points(h, lo) if len(closed) >= 2 else []
        forming = None
        if not snap.get("archived") and sid == (self.last or {}).get("snapshot_id"):
            fb = [b for b in self.bridge.bars(tf, 2, include_forming=True) if not b.get("closed")]
            forming = fb[-1] if fb else None
        return {"status": "OK", "snapshot_id": sid, "asset": snap["asset"], "tf": tf, "cutoff": snap.get("as_of"), "bar_revision": rev.get("revision"),
                "bars_source": src, "bars": [{k: b.get(k) for k in ("open_utc", "o", "h", "l", "c", "tv", "revision")} for b in closed],
                "indicators": {"bb": [None if x is None else {"upper": _r(x["upper"]), "mid": _r(x["basis"]), "lower": _r(x["lower"])} for x in bb[-len(closed):]] if bb else [],
                               "sar": [None if p is None else {"sar": _r(p["sar"]), "trend": p["trend"]} for p in sar]},
                "overlays": self._overlays(snap, tf), "forming_preview": forming, "history_from": closed[0]["open_utc"] if closed else None}

    @staticmethod
    def _overlays(snap: dict, tf: str) -> list[dict]:
        out = []
        r = ((snap.get("machine") or {}).get("range") or {})
        if r.get("range_id") and tf in ("M5", "M1"):
            out.append({"overlay_id": f"range:{r['range_id']}", "kind": "RANGE", "producer": "ScalpMachine", "source_tf": "M5", "range_id": r["range_id"],
                        "geometry": {"L": r.get("L"), "H": r.get("H"), "MID": r.get("MID")}, "available_at": r.get("armed_at"), "validity": r.get("ttl_end"),
                        "label": "zakres (źródło M5)"})
        for side, d in ((snap.get("machine") or {}).get("directions") or {}).items():
            z = (d or {}).get("zone")
            if z and tf in ("M5", "M1"):
                out.append({"overlay_id": f"zone:{r.get('range_id')}:{side}", "kind": "ZONE", "producer": "ScalpMachine", "source_tf": "M5", "range_id": r.get("range_id"),
                            "side": side, "geometry": {"low": z.get("z_low"), "high": z.get("z_high")}, "available_at": r.get("armed_at"), "state": d.get("state"),
                            "label": f"strefa {side} (źródło M5)"})
        for s_ in snap.get("setups") or []:
            for lv in s_["levels"]:
                if tf in ("M1", "M5"):
                    out.append({"overlay_id": lv["id"], "kind": lv["kind"], "producer": "ScalpService (SHADOW)", "source_tf": "M1", "setup_id": s_["setup_id"],
                                "side": s_["side"], "geometry": {"price": lv["price"]}, "available_at": s_["evaluated_at"]})
        return out
