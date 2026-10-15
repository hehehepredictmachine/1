"""ScalpService - the scalp profile running in SHADOW inside the bot (observation only, never an order).

On every new CLOSED M1 (same MarketBridge session - no second MT5 connection): feeds the shared ScalpMachine in event
order (M30/M15 -> M5 -> M1), builds the MTF dashboard, indicators, session boxes and adapter statuses, evaluates every
ENTRY_CANDIDATE through the explicit AND of gates and records READY_SHADOW / BLOCKED / MISSED in `scalp_shadow` BEFORE the
outcome is known. The hypothetical outcome is settled later from closed M1 with the same walk() as the replay.
READY_EXECUTION is unreachable: EXECUTION_AUTHORIZED is false (config switches are Literal[False]).
A failure here sets ERROR_RECOVERY and never touches existing positions or their protection.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import paths
from ..timeutil import iso, utcnow
from . import adapters, hedge as hedge_mod, indicators as ind, replay, sessions, strategy as st

TFS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}


class ScalpService:
    def __init__(self, cfg_store, bridge, db, bus, log, news=None, forecast=None):
        self.cfg_store, self.bridge, self.db, self.bus, self.log, self.news, self.forecast = cfg_store, bridge, db, bus, log, news, forecast
        self.prof = st.load_profile()
        self.hedge = hedge_mod.HedgeController(self.prof)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.machine: st.ScalpMachine | None = None
        self.fed: dict[str, int] = {}
        self.epoch = None
        self.last_key = None
        self.latency: list[float] = []
        self.state: dict = {"status": "STARTING", "mode": "SHADOW", "execution_permission": False, "profile_id": self.prof["profile_id"],
                            "profile_hash": st.profile_hash(self.prof), "updated_at": None}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scalp-shadow", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:                          # analytics never affect the bot or position protection
                self.machine, self.fed = None, {}
                self._set("ERROR_RECOVERY", f"{type(exc).__name__}: {exc}"[:300])
            self._stop.wait(2.0)

    def _set(self, status: str, reason: str | None, **kw) -> None:
        self.state.update(status=status, reason=reason, updated_at=iso(utcnow()), **kw)
        self.bus.publish("scalp", self.public())

    def public(self) -> dict:
        return dict(self.state)

    # ------------------------------------------------------------ main step
    def tick(self) -> None:
        cfg = self.cfg_store.get()
        if not cfg.scalp.enabled:
            if self.state["status"] != "DISABLED":
                self._set("DISABLED", "wyłączone w konfiguracji")
            return
        bars = {tf: [b for b in self.bridge.bars(tf, cfg.scalp.m1_bars if tf == "M1" else 400, include_forming=False) if b.get("open_utc")]
                for tf in TFS}
        if not bars["M1"] or not bars["M5"]:
            if self.state["status"] != "NO_DATA":
                self._set("NO_DATA", "brak zamkniętych M1/M5 z bieżącej sesji MT5")
            return
        key = f"{bars['M1'][-1]['open_utc']}|{bars['M1'][-1].get('revision')}"
        epoch = getattr(self.bridge, "session_epoch", None)
        if key == self.last_key and epoch == self.epoch:
            return
        t0 = time.perf_counter()
        info = self.bridge.symbol_info or {}
        tick = float(info.get("trade_tick_size") or 0) or 0.01
        point = float(info.get("point") or tick)
        if self.machine is None or epoch != self.epoch:
            self.machine, self.fed, self.epoch = st.ScalpMachine(self.prof, tick), {}, epoch     # restart / reconnect: rebuild from history
        self._feed(bars, point)
        self.last_key = key
        cands = self.machine.candidates
        self.machine.candidates = []
        for plan in cands:
            if time.time() - plan["decision_ts"] > 120:          # warm-up from history: not a live decision, not recorded
                self.machine.close_direction(plan["direction"], "EXPIRED", "kandydat z historii (rozgrzewka) – nie rejestrowany", plan["decision_ts"])
                continue
            self._evaluate(plan, cfg, info, tick)
        self.settle(bars["M1"], point)
        self.latency.append((time.perf_counter() - t0) * 1000)
        self.latency = self.latency[-200:]
        self._set("SHADOW", None, mtf=self.mtf(bars), indicators=self.indicators(bars), sessions=sessions.boxes_as_of(bars["M5"], 5, iso(utcnow())),
                  adapters=adapters.all_snapshots(cfg.mt5.symbol), setup=self.machine.public(), forecasts=self.forecasts(),
                  hedge_risk=self.hedge_view(cfg), recent=self.recent(20), summary=self.summary(), statuses=self.statuses(),
                  training=self.training_status(), latency_ms=self._lat())

    def _feed(self, bars: dict, point: float) -> None:
        ev = []
        for tf, mins in TFS.items():
            pri = {"H1": 0, "M30": 0, "M15": 1, "M5": 2, "M1": 3}[tf]
            last = self.fed.get(tf, -1)
            for b in bars[tf]:
                t = st.ts(b["open_utc"])
                if t > last:
                    x = {k: b.get(k) for k in ("open_utc", "o", "h", "l", "c", "tv")}
                    x["spread_price"] = b["spread"] * point if b.get("spread") is not None else None
                    ev.append((t + mins * 60, pri, tf, x, t))
        ev.sort(key=lambda e: (e[0], e[1]))
        for _, _, tf, x, t in ev:
            if tf in ("M15", "M30", "H1"):
                self.machine.add_context(TFS[tf], x)
            elif tf == "M5":
                self.machine.on_m5_close(x)
            else:
                self.machine.on_m1_close(x)
            self.fed[tf] = t

    # ------------------------------------------------------------ gates (logical AND; missing information = BLOCKED)
    def _evaluate(self, plan: dict, cfg, info: dict, tick: float) -> None:
        sgn = 1 if plan["direction"] == "BUY" else -1
        g: list[dict] = []

        def gate(name, ok, detail=None):
            g.append({"name": name, "ok": ok, "detail": detail})
            return ok
        gate("symbol XAU/USD", info.get("currency_base") in (None, "XAU") and info.get("currency_profit") in (None, "USD"),
             f"{info.get('currency_base')}/{info.get('currency_profit')}")
        q = self.bridge.quote_status() or {}
        age = q.get("age_seconds")
        fresh = bool(q.get("bid") and q.get("ask") and q["bid"] <= q["ask"] and age is not None and age <= st.V(self.prof, "risk", "quote_ttl_s"))
        gate("świeże Bid/Ask ≤ TTL", fresh, f"wiek {age}s")
        blk, why = st.entry_filters(self.machine, plan, self.prof)
        gate("trend M30/M15/H1 i sesja", blk is False, why)
        decision_age = time.time() - plan["decision_ts"]
        gate("decyzja na świeżym zamknięciu M1", decision_age <= 60, f"{decision_age:.0f}s po zamknięciu retestu")
        limit = plan.get("entry_mode") == "LIMIT_EDGE"
        fill = (plan["limit_price"] if limit else q.get("ask") if sgn > 0 else q.get("bid")) if fresh else None
        sp = (q["ask"] - q["bid"]) if fresh else None
        missed = False
        if fill is not None and not limit:
            ref_exec = plan["ref_close_bid"] + ((plan["spread_at_signal"] or sp) if sgn > 0 else 0.0)
            missed = sgn * (fill - ref_exec) > plan["chase_limit"]
            gate("limit pogoni", not missed, f"{sgn * (fill - ref_exec):.3f} vs {plan['chase_limit']:.3f}")
        cs = float(info.get("trade_contract_size") or 0)
        com = cfg.scalp.commission_per_lot_side
        gate("prowizja znana", com is not None, "ustaw scalp.commission_per_lot_side (Zero ≠ 0 kosztów)" if com is None else f"{com}/lot/stronę")
        eco = None
        if fill is not None and cs > 0:
            extra = 2 * (com or 0.0) / cs + 2 * cfg.scalp.slippage_ticks * tick
            eco = st.economics(plan, fill, sp, extra, self.prof)
            gate("koszt i RR (filtr geometrii)", eco["ok"], eco["reason"])
            sp_ok = sp <= cfg.scalp.max_spread_atr_m1 * plan["atr_m1"] and (cfg.scalp.max_spread_price is None or sp <= cfg.scalp.max_spread_price)
            gate("spread", sp_ok, f"{sp:.3f}")
        acc = self.bridge.account_status() or {}
        sz = None
        if eco and acc.get("equity"):
            sz = st.size(eco["risk_per_unit"], cs, float(acc["equity"]), self.prof, float(info.get("volume_min") or 0.01),
                         float(info.get("volume_step") or 0.01), float(info.get("volume_max") or 100))
            gate("wielkość pozycji", sz["ok"], sz.get("reason") or f"{sz['lots']} lot ({sz['exit_variant']})")
        else:
            gate("wielkość pozycji", False, "brak equity / kosztu")
        gate("limity dzienny/tygodniowy", *self._loss_limits(acc))
        gate("kalendarz makro", *self._calendar())
        busy = self.db.one("SELECT COUNT(*) AS n FROM scalp_shadow WHERE status='READY_SHADOW' AND outcome_status='PENDING'")["n"]
        last_end = self.db.one("SELECT MAX(settled_at) AS t FROM scalp_shadow WHERE status='READY_SHADOW' AND outcome_status='SETTLED'")["t"]
        cool = bool(last_end) and (utcnow() - datetime.fromisoformat(last_end.replace("Z", "+00:00"))).total_seconds() < \
            st.V(self.prof, "risk", "cooldown_after_cycle_min") * 60
        gate("jeden cykl / cooldown", busy == 0 and not cool, f"otwarte hipotetyczne cykle {busy}, cooldown {cool}")
        mq = self.setup_quality(plan)
        plan["model_b"] = mq
        if st.V(self.prof, "ml_filter", "enabled", default=False):
            gate("filtr modelu jakości setupu (B)", bool(mq.get("pass")), mq.get("reason") or f"P(TP1 przed SL) {mq.get('p')} vs próg {mq.get('threshold')}")
        else:
            gate("model ML", True, "filtr modelu B wyłączony w profilu (ml_filter.enabled=false) – P(TP1 przed SL) tylko informacyjnie")
        gate("uprawnienie wykonania", False, "EXECUTION_AUTHORIZED=false (SHADOW)")
        core_ok = all(x["ok"] for x in g if x["name"] != "uprawnienie wykonania")
        status = "MISSED" if missed else "READY_SHADOW" if core_ok else "BLOCKED"
        reasons = [f"{x['name']}: {x['detail']}" for x in g if not x["ok"] and x["name"] != "uprawnienie wykonania"]
        plan = dict(plan, fill_shadow=fill, spread_fill=sp, economics=eco, sizing=sz)
        hd = self.hedge.decide(margin_mode=acc.get("margin_mode"), base={"lots": (sz or {}).get("lots") or 0.0}, setup_valid=True,
                               adverse_signal=None, policy_model=None, hedges_used=0, budget_ok=True,
                               vmin=float(info.get("volume_min") or 0.01), vstep=float(info.get("volume_step") or 0.01))
        self.db.execute("""INSERT OR IGNORE INTO scalp_shadow(created_at, setup_id, profile_id, direction, decision_time_utc, status, reasons, plan, gates, hedge,
                           outcome_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (iso(utcnow()), plan["setup_id"], self.prof["profile_id"], plan["direction"], plan["decision_time"], status,
                         json.dumps(reasons, ensure_ascii=False), json.dumps(plan, ensure_ascii=False, default=str), json.dumps(g, ensure_ascii=False),
                         json.dumps(hd, ensure_ascii=False), "PENDING" if status == "READY_SHADOW" else "NOT_APPLICABLE"))
        self.machine.close_direction(plan["direction"], status, "; ".join(reasons) or "wszystkie bramki SHADOW spełnione", plan["decision_ts"])
        self.log.info("SCALP", status, f"{plan['direction']} {plan['setup_id']}: {status}" + (f" – {reasons[0]}" if reasons else ""))

    def _loss_limits(self, acc: dict) -> tuple[bool, str]:
        eq = acc.get("equity")
        if not eq:
            return False, "brak equity"
        p = paths.data_dir() / "scalp" / "risk_reference.json"
        now = utcnow()
        day, week = now.strftime("%Y-%m-%d"), now.strftime("%G-W%V")
        try:
            ref = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ref = {}
        if ref.get("day") != day:
            ref.update(day=day, day_equity=eq)
        if ref.get("week") != week:
            ref.update(week=week, week_equity=eq)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(ref), encoding="utf-8")                    # persisted: a restart does not reset the counters
        dl = (ref["day_equity"] - eq) / ref["day_equity"] * 100
        wl = (ref["week_equity"] - eq) / ref["week_equity"] * 100
        ok = dl < st.V(self.prof, "risk", "daily_loss_pct") and wl < st.V(self.prof, "risk", "weekly_loss_pct")
        return ok, f"dzień {dl:.2f}% / tydzień {wl:.2f}% (equity całego konta, reset 00:00 UTC; wpłaty/wypłaty nie są korygowane)"

    def _calendar(self) -> tuple[bool, str]:
        if not self.news:
            return False, "brak serwisu kalendarza"
        m = self.news.macro()
        if m.get("status") not in ("PARTIAL",):
            return False, f"kalendarz {m.get('status')} – brak świeżego kalendarza blokuje nowe wejścia"
        if m.get("active_events"):
            return False, "wydarzenie high-impact w oknie blokady"
        return True, f"kalendarz {m.get('status')} (częściowy)"

    # ------------------------------------------------------------ hypothetical outcomes
    def settle(self, m1: list[dict], point: float) -> None:
        rows = self.db.query("SELECT * FROM scalp_shadow WHERE outcome_status='PENDING' LIMIT 50")
        if not rows:
            return
        bars = [dict({k: b.get(k) for k in ("open_utc", "o", "h", "l", "c")}, spread_price=(b["spread"] * point if b.get("spread") is not None else None))
                for b in m1]
        P = replay.Path(bars, None)
        for r in rows:
            plan = json.loads(r["plan"])
            T = plan["decision_ts"]
            i = P.index.get(T)
            if i is None:
                if P.t and P.t[-1] > T + 120:
                    self.db.execute("UPDATE scalp_shadow SET outcome_status='NO_DATA', settled_at=? WHERE id=?", (iso(utcnow()), r["id"]))
                continue
            sgn = 1 if plan["direction"] == "BUY" else -1
            sz = plan.get("sizing") or {}
            f1 = st.V(self.prof, "exits", "tp1_fraction") if sz.get("split", True) else 1.0
            tp2 = plan["tp2"] if f1 < 1 else None
            costs = self._costs(plan)
            if plan.get("entry_mode") == "LIMIT_EDGE":
                fl = replay.get_fill(plan, P, T, costs["slippage_price"])
                if not fl["ok"]:
                    if fl["reason"] == "MISSED_LIMIT_NOT_FILLED" and P.t[-1] >= T + 60 * (plan.get("limit_wait_m1") or 3):
                        self.db.execute("UPDATE scalp_shadow SET outcome_status='MISSED_LIMIT', settled_at=? WHERE id=?", (iso(utcnow()), r["id"]))
                    continue
                i, fill = fl["i"], fl["fill"]
            else:
                fill = plan.get("fill_shadow") or (P.o[i] + ((P.sp[i] or 0) if sgn > 0 else 0))
            risk = (plan.get("economics") or {}).get("risk_per_unit") or abs(fill - plan["sl"])
            res = replay.walk(P, i, sgn, 1.0, plan["sl"], plan["tp1"], tp2, f1, P.t[i] + st.V(self.prof, "exits", "max_hold_minutes") * 60, costs,
                              entry=fill, **replay.exit_params(self.prof, costs, risk))
            if res.get("open_at_end") or not res["exits"]:
                continue
            net = replay.pnl(sgn, fill, 1.0, res["exits"], costs)
            out = {"exits": [{"vol": v, "price": px, "time": st.iso_ts(t), "reason": rs} for (v, px, t, rs) in res["exits"]],
                   "ambiguous": res["ambiguous"], "precision": "OHLC_APPROX", "costs": {k: round(v, 5) for k, v in costs.items()},
                   "note": "wynik po prowizji i poślizgu (te same zasady co replay)"}
            self.db.execute("UPDATE scalp_shadow SET outcome_status='SETTLED', outcome=?, net_r=?, settled_at=? WHERE id=?",
                            (json.dumps(out), net / risk if risk else None, st.iso_ts(res["exits"][-1][2]), r["id"]))

    def _costs(self, plan: dict) -> dict:
        cfg = self.cfg_store.get()
        info = self.bridge.symbol_info or {}
        cs = float(info.get("trade_contract_size") or 100.0)
        tick = float(info.get("trade_tick_size") or 0.01)
        return {"commission_price_side": (cfg.scalp.commission_per_lot_side or 0.0) / cs, "slippage_price": cfg.scalp.slippage_ticks * tick}

    def setup_quality(self, plan: dict) -> dict:
        """Task-B model (P(TP1 before SL)) for this setup through the analytics worker - only when a compatible model is active."""
        reg = self.registry()
        act = (reg.get("runs") or {}).get(reg.get("active") or "", {})
        if not act.get("setup_model"):
            return {"status": "UNAVAILABLE", "reason": "brak aktywnego modelu jakości setupu (zadanie B) – trening na danych rzeczywistych", "pass": False}
        if not self.forecast or not self.forecast.proc:
            return {"status": "UNAVAILABLE", "reason": "proces analityki (.venv_candles) nie działa", "pass": False}
        try:
            return self.forecast._ask({"cmd": "setup_quality", "features": plan.get("features") or {}}, 10)
        except Exception as exc:
            return {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"[:200], "pass": False}

    def recent(self, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT * FROM scalp_shadow ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            for k in ("reasons", "plan", "gates", "hedge", "outcome"):
                if r.get(k):
                    r[k] = json.loads(r[k])
        return rows

    def summary(self) -> dict:
        rows = self.db.query("SELECT status, outcome_status, net_r, decision_time_utc FROM scalp_shadow")
        st_ = {}
        for r in rows:
            st_[r["status"]] = st_.get(r["status"], 0) + 1
        settled = [r["net_r"] for r in rows if r["outcome_status"] == "SETTLED" and r["net_r"] is not None]
        return {"by_status": st_, "settled": len(settled), "win_rate": round(sum(1 for x in settled if x > 0) / len(settled), 3) if settled else None,
                "mean_r_after_costs": round(sum(settled) / len(settled), 3) if settled else None,
                "days": len({r["decision_time_utc"][:10] for r in rows}), "note": "SHADOW na żywo – za mało cykli to INSUFFICIENT_EVIDENCE, nie wynik"}

    # ------------------------------------------------------------ views
    def mtf(self, bars: dict) -> list[dict]:
        out = []
        now = utcnow().timestamp()
        for tf, mins in TFS.items():
            b = bars.get(tf) or []
            if not b:
                out.append({"tf": tf, "status": "MISSING"})
                continue
            s = st.Series(mins)
            for x in b[-300:]:
                s.append(x)
            ctx = st.context(s, self.prof)
            close = st.ts(b[-1]["open_utc"]) + mins * 60
            age = now - close
            out.append({"tf": tf, "last_close_utc": st.iso_ts(close), "age_s": round(age), "bars": len(b),
                        "status": "STALE" if age > mins * 60 * 2 + 60 else "OK" if ctx["status"] == "OK" else "WARMUP",
                        "regime": None if ctx["status"] != "OK" else ("TREND_UP" if ctx["sar_trend"] == "UP" and ctx["slope"] > 0.1 else
                                                                      "TREND_DOWN" if ctx["sar_trend"] == "DOWN" and ctx["slope"] < -0.1 else "MIXED/RANGE"),
                        "sar_trend": ctx.get("sar_trend"), "slope_atr": _r(ctx.get("slope")), "bw_pct": _r(ctx.get("bw_pct"))})
        return out

    def indicators(self, bars: dict) -> dict:
        out = {}
        for tf in ("M1", "M5"):
            b = bars[tf][-300:]
            c, h, lo = [x["c"] for x in b], [x["h"] for x in b], [x["l"] for x in b]
            a = ind.atr(h, lo, c)
            bb = ind.bollinger(c, a)[-1] if len(c) >= 20 else None
            sr = ind.sar(h, lo)[-1] if len(c) >= 2 else None
            out[tf] = {"close": c[-1] if c else None, "atr14": _r(a[-1] if a else None), "bb": {k: _r(v) for k, v in (bb or {}).items()} or None,
                       "sar": sr, "variant": "BB SMA20 ±2σ (populacyjne, jak MT5 iBands); SAR 0.02/0.2 – do porównania z MT5"}
        return out

    def forecasts(self) -> dict:
        reg = self.registry()
        if not reg.get("active"):
            return {"status": "UNAVAILABLE", "reason": "NO_MODEL – brak wytrenowanego modelu zadania A (1/3/5 min); trening: 17_TRENING_SCALP_ML.bat",
                    "trade_assessment": {"status": "UNAVAILABLE", "reason": "model B (jakość setupu) – brak danych z replayu na rzeczywistej historii"}}
        if not self.forecast or not self.forecast.proc:
            return {"status": "UNAVAILABLE", "reason": "proces analityki (.venv_candles) nie działa"}
        try:
            m1 = self.bridge.bars("M1", 400, include_forming=False)
            pt = float((self.bridge.symbol_info or {}).get("point") or 0.01)
            ans = self.forecast._ask({"cmd": "scalp_forecast", "m1": [dict({k: b[k] for k in ("open_utc", "o", "h", "l", "c", "tv")},
                                                                         spread_price=b["spread"] * pt if b.get("spread") is not None else None) for b in m1]}, 20)
            return ans
        except Exception as exc:
            return {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"[:200]}

    def hedge_view(self, cfg) -> dict:
        acc = self.bridge.account_status() or {}
        mm = hedge_mod.margin_mode_name(acc.get("margin_mode"))
        return {"policy": "SHADOW", "hedge_execution": False, "margin_mode": mm,
                "netting_note": "NETTING: HEDGE_PARTIAL zastąpione częściowym zamknięciem (REDUCE)" if mm == "NETTING" else None,
                "limits": {"max_fraction_of_base": st.V(self.prof, "hedge", "max_fraction_of_base"), "max_hedges_per_cycle": 1,
                           "ttl_m1": st.V(self.prof, "hedge", "ttl_m1"), "cycle_risk_pct": st.V(self.prof, "risk", "cycle_risk_pct_equity")},
                "equity": acc.get("equity"), "free_margin": acc.get("free_margin"),
                "open_cycle": None, "note": "SHADOW: brak rzeczywistych ticketów; porównanie HEDGE_PARTIAL vs REDUCE pochodzi z replayu (zadanie C)"}

    def registry(self) -> dict:
        p = paths.data_dir() / "scalp" / "registry.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"active": None, "runs": {}}

    def training_status(self) -> dict:
        d = paths.data_dir() / "scalp"
        hist = sorted((d / "history").glob("*/source_metadata.json"))
        stf = d / "TRAINING_STATUS.json"
        runs = sorted((d / "runs").glob("*/report.json"))
        rep = sorted((d / "replay").glob("*/summary.json"))
        return {"history_exports": [h.parent.name for h in hist[-5:]],
                "status_file": json.loads(stf.read_text(encoding="utf-8")) if stf.exists() else None,
                "last_run": json.loads(runs[-1].read_text(encoding="utf-8")).get("summary") if runs else None,
                "last_replay": json.loads(rep[-1].read_text(encoding="utf-8")) if rep else None,
                "last_variants": _load_last(d / "replay", "variants.json"),
                "last_task_b": (_load_last(d / "runs", "report.json") or {}).get("task_B"),
                "blocked": None if hist else "BLOCKED_NO_REAL_DATA – brak eksportu M1/M5/M15/M30/H1 (16_EKSPORT_HISTORII_SCALP.bat przy działającym MT5)"}

    def statuses(self) -> dict:
        tr = self.training_status()
        reg = self.registry()
        rp = (tr.get("last_replay") or {}).get("strategy") or {}
        return {"CODE_VALID": {"value": True, "basis": "testy jednostkowe/integracyjne wydania (RAPORT_TESTOW.md) – nie dowodzą jakości modelu"},
                "DATA_VALID": {"value": bool(tr["history_exports"]), "basis": tr["blocked"] or "eksport z raportem jakości"},
                "MODEL_VALID": {"value": bool(reg.get("active")), "basis": "brak aktywnego modelu" if not reg.get("active") else "rejestr scalp"},
                "STRATEGY_VALID": {"value": rp.get("status") == "PASSED_RESEARCH_GATE_PENDING_COST_STRESS",
                                   "basis": rp.get("status") or "brak replayu OOS na rzeczywistych danych"},
                "HEDGE_VALID": {"value": False, "basis": ((tr.get("last_replay") or {}).get("hedge_vs_reduce") or {}).get("status") or "NOT_EVALUATED"},
                "EXECUTION_AUTHORIZED": {"value": False, "basis": "MODE=SHADOW, LIVE_TRADING=false, ML_EXECUTION=false, HEDGE_EXECUTION=false"}}

    def _lat(self) -> dict:
        v = sorted(self.latency)
        if not v:
            return {}
        return {"p50": round(v[len(v) // 2], 1), "p95": round(v[int(0.95 * (len(v) - 1))], 1), "n": len(v)}


def _load_last(base: Path, name: str):
    f = sorted(base.glob(f"*/{name}"))
    try:
        return json.loads(f[-1].read_text(encoding="utf-8")) if f else None
    except (OSError, ValueError):
        return None


def _r(x, n=4):
    return round(x, n) if isinstance(x, float) else x
