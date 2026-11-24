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
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from ..timeutil import iso, parse_iso, utcnow
from . import adapters, hedge as hedge_mod, indicators as ind, replay, sessions, strategy as st

TFS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}
RISK_REF_MAX_LAG_S = 600            # 1.46 arch (I0810): the day reference must be observed within 10 min after 00:00 UTC


class ScalpService:
    def __init__(self, cfg_store, bridge, db, bus, log, news=None, forecast=None):
        self.cfg_store, self.bridge, self.db, self.bus, self.log, self.news, self.forecast = cfg_store, bridge, db, bus, log, news, forecast
        self.inst = "XAUUSD"                          # profile / registry / SHADOW rows of this instrument
        self.extind = None                            # runtime sets the ExtIndService (PMW-UPD-02)
        self.ml = None                                # runtime sets the ML router (PMW-UPD-03 candidate collector)
        self.nss = None                               # runtime sets the NeuralScalpService (PMW-UPD-04)
        self.dashboard = None                         # runtime sets the MTFDashboard (PMW-UPD-05)
        self.liquidity = None                         # runtime sets the LiquidityService (PMW-UPD-06)
        self.listeners: list = []                     # read-only observers of every recorded candidate (evaluation ledger, O6)
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
        import mq_instruments
        if cfg.assets.active not in mq_instruments.profiles():
            if self.state["status"] != "UNSUPPORTED_ASSET":
                self._set("UNSUPPORTED_ASSET", f"brak profilu scalp dla {cfg.assets.active}")
            return
        if cfg.assets.active != self.inst:            # own profile, registry and state per instrument - nothing carried over
            self.inst = cfg.assets.active
            self.prof = st.load_profile(instrument=self.inst)
            self.hedge = hedge_mod.HedgeController(self.prof)
            self.machine, self.fed, self.last_key = None, {}, None
            self.state.update(instrument=self.inst, profile_id=self.prof["profile_id"], profile_hash=st.profile_hash(self.prof))
            if self.dashboard is not None:
                self.dashboard.last = None                  # no snapshot of the previous instrument under the new one
        try:                                                # 1.46 arch (I0810): loss-limit references from the first equity of the UTC day / week
            self._risk_reference(self.bridge.account_status() or {})
        except Exception:                                 # a reference file problem is reported by the gate, never stops the SHADOW machine
            import logging
            logging.getLogger("masterquo.scalp").warning("risk reference update failed", exc_info=True)
        bars = {tf: [b for b in self.bridge.bars(tf, cfg.scalp.m1_bars if tf == "M1" else 400, include_forming=False) if b.get("open_utc")]
                for tf in TFS}
        if not bars["M1"] or not bars["M5"]:
            if self.state["status"] != "NO_DATA":
                self._set("NO_DATA", "brak zamkniętych M1/M5 z bieżącej sesji MT5")
            return
        m1_key = f"{bars['M1'][-1]['open_utc']}|{bars['M1'][-1].get('revision')}"
        # 1.46 arch (I0737): the key covers the last closed bar of EVERY TF - an M5 / M15 / M30 / H1 bar that arrives one poll after the
        # M1 of its close is fed at once (before: only with the next M1); candidates still come only from a new M1
        key = m1_key + "".join(f"|{tf}:{bars[tf][-1]['open_utc']}:{bars[tf][-1].get('revision')}" for tf in TFS if tf != "M1" and bars[tf])
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
        self._bars = bars
        new_m1 = m1_key != getattr(self, "_last_m1_key", None) or epoch != getattr(self, "_last_m1_epoch", None)
        if getattr(self, "nss", None) is not None and new_m1:  # PMW-UPD-04: context telemetry on every new closed M1 (latest wins)
            self.nss.on_m1(bars, instrument=self.inst, epoch=epoch, point=point)
        self.last_key, self._last_m1_key, self._last_m1_epoch = key, m1_key, epoch
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
                  adapters=adapters.all_snapshots(cfg.mt5.symbol, ext=self.extind, instrument=self.inst), setup=self.machine.public(), forecasts=self.forecasts(),
                  hedge_risk=self.hedge_view(cfg), recent=self.recent(20), summary=self.summary(), statuses=self.statuses(),
                  training=self.training_status(), latency_ms=self._lat())
        if self.dashboard is not None:                     # PMW-UPD-05: one MTFContextSnapshot of exactly this bar set and state
            try:
                self.dashboard.build(bars, info=info, epoch=epoch, recent=[r for r in self.recent(40) if r.get("instrument") == self.inst][:10],
                                     nss_last=self.nss.last if self.nss is not None else None, t0=t0)
            except Exception as exc:  # noqa: BLE001 - presentation only, never stops the strategy
                self.log.error("SCALP", "MTF_SNAPSHOT", f"{type(exc).__name__}: {exc}"[:300])

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
        race = getattr(self, "_race", None)
        if race is None:
            race = self._race = {}
        m1_open = {st.ts(b["open_utc"]) for b in bars["M1"]}
        for _, _, tf, x, t in ev:
            if tf in ("M15", "M30", "H1"):
                self.machine.add_context(TFS[tf], x)
            elif tf == "M5":
                # 1.46 arch (I0737): an M5 fed AFTER the M1 of its close (polling race) arms its range with that M1 inside the zone search,
                # unlike the replay (M5 before M1 at a common close) - such a range gives no candidates (NOT_VERIFIED, never a new one)
                late = len(self.machine.m1) > 0 and self.machine.m1.close_time() >= t + 300
                before = self.machine.range
                self.machine.on_m5_close(x)
                if late and self.machine.range is not None and self.machine.range is not before:
                    for d in ("BUY", "SELL"):
                        self.machine.close_direction(d, "BLOCKED", "NOT_VERIFIED – zakres uzbrojony po spóźnionej M5 (M1 z tym samym zamknięciem "
                                                     "już podana): strefa niezgodna z replay", t + 300)
            else:
                lag = _tf_lag(bars, t + 60, m1_open)
                if lag:
                    race[t + 60] = lag                          # a higher TF bar closing at or before this M1's close is not there yet
                self.machine.on_m1_close(x)
            self.fed[tf] = t
        for k in sorted(race)[:-50]:
            race.pop(k, None)

    # ------------------------------------------------------------ gates (logical AND; missing information = BLOCKED)
    def _evaluate(self, plan: dict, cfg, info: dict, tick: float) -> None:
        sgn = 1 if plan["direction"] == "BUY" else -1
        g: list[dict] = []

        def gate(name, ok, detail=None):
            g.append({"name": name, "ok": ok, "detail": detail})
            return ok
        import mq_instruments
        gate(f"symbol {self.inst}", info.get("currency_base") is None or mq_instruments.check_metadata(self.inst, info)[0],
             f"{info.get('currency_base')}/{info.get('currency_profit')}")
        lag = (getattr(self, "_race", None) or {}).get(plan["decision_ts"])
        gate("komplet TF w chwili decyzji", not lag,           # 1.46 arch (I0737): the M1 of the decision was fed before a higher TF bar of its close
             ("NOT_VERIFIED – brak zamkniętej świecy " + "/".join(lag) + " z zamknięciem ≤ decyzji (wyścig pollingu; replay podaje ją przed M1)")
             if lag else "M5/M15/M30/H1 zamknięte w chwili decyzji")
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
        acc = self.bridge.account_status() or {}
        # 1.46 arch (I0738): budget and commission are in the ACCOUNT currency, contract_size converts into the QUOTE currency. MT5's
        # money per price unit (trade_tick_value / trade_tick_size) converts into the account currency; another account currency without
        # it cannot be verified -> blocked. Costs and lots use the more conservative of both conversions (never fewer costs / more lots).
        mpp = money_per_price(info)
        acc_ccy, q_ccy = acc.get("currency"), info.get("currency_profit")
        cross = bool(acc_ccy and q_ccy and str(acc_ccy).upper() != str(q_ccy).upper())
        gate("wartość ticka (waluta konta)", mpp is not None or not cross,
             f"{mpp:.4g} {acc_ccy or '?'} / 1.0 ceny / lot" if mpp is not None else
             f"NOT_VERIFIED – konto {acc_ccy}, kwotowanie {q_ccy}, brak trade_tick_value" if cross else "waluta konta = waluta kwotowania")
        eco = extra = None
        if fill is not None and cs > 0:
            eco, extra, eco_ok, eco_detail = economics_gate(plan, fill, sp, com or 0.0, cs, mpp, cfg.scalp.slippage_ticks, tick, self.prof)
            gate("koszt i RR (filtr geometrii)", eco_ok, eco_detail)
            sp_ok = sp <= cfg.scalp.max_spread_atr_m1 * plan["atr_m1"] and (cfg.scalp.max_spread_price is None or sp <= cfg.scalp.max_spread_price)
            gate("spread", sp_ok, f"{sp:.3f}")
        sz = None
        if eco and acc.get("equity"):
            sz = st.size(eco["risk_per_unit"], cs, float(acc["equity"]), self.prof, float(info.get("volume_min") or 0.01),
                         float(info.get("volume_step") or 0.01), float(info.get("volume_max") or 100), money_per_price=mpp)
            gate("wielkość pozycji", sz["ok"], sz.get("reason") or f"{sz['lots']} lot ({sz['exit_variant']})")
        else:
            gate("wielkość pozycji", False, "brak equity / kosztu")
        gate("limity dzienny/tygodniowy", *self._loss_limits(acc))
        gate("kalendarz makro", *self._calendar())
        busy = self.db.one("SELECT COUNT(*) AS n FROM scalp_shadow WHERE status='READY_SHADOW' AND outcome_status='PENDING' AND instrument=?", (self.inst,))["n"]
        last_end = self.db.one("SELECT MAX(settled_at) AS t FROM scalp_shadow WHERE status='READY_SHADOW' AND outcome_status='SETTLED' AND instrument=?",
                               (self.inst,))["t"]
        cool = bool(last_end) and (utcnow() - datetime.fromisoformat(last_end.replace("Z", "+00:00"))).total_seconds() < \
            st.V(self.prof, "risk", "cooldown_after_cycle_min") * 60
        gate("jeden cykl / cooldown", busy == 0 and not cool, f"otwarte hipotetyczne cykle {busy}, cooldown {cool}")
        mq = self.setup_quality(plan)
        plan["model_b"] = mq
        plan["indicator_context"] = self.indicator_context(plan)      # PMW-UPD-02 reaction model - SHADOW observation, never a gate
        # 1.46: the ML / NSS snapshots were taken before fill_shadow / economics were added to the plan (both None in every sample), so
        # their labels settled at a cost-free fill and risk; the values are already known here (model features are not affected)
        priced = dict(plan, fill_shadow=fill, spread_fill=sp, economics=eco, sizing=sz)
        plan["ml_scalp"] = self.ml_scalp(priced)                       # PMW-UPD-03: candidate stored BEFORE any model filter + inference
        plan["neural"] = self.neural(dict(priced, ml_scalp=plan["ml_scalp"]))   # PMW-UPD-04: frozen snapshot to the NSS worker (OBSERVE)
        plan["liquidity_context"] = self.liquidity_context(plan)       # PMW-UPD-06: session boxes / heatmap reading (OBSERVE, never a gate)
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
                           outcome_status, instrument) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (iso(utcnow()), plan["setup_id"], self.prof["profile_id"], plan["direction"], plan["decision_time"], status,
                         json.dumps(reasons, ensure_ascii=False), json.dumps(plan, ensure_ascii=False, default=str), json.dumps(g, ensure_ascii=False),
                         json.dumps(hd, ensure_ascii=False), "PENDING" if status == "READY_SHADOW" else "NOT_APPLICABLE", self.inst))
        self.machine.close_direction(plan["direction"], status, "; ".join(reasons) or "wszystkie bramki SHADOW spełnione", plan["decision_ts"])
        self.log.info("SCALP", status, f"{plan['direction']} {plan['setup_id']}: {status}" + (f" – {reasons[0]}" if reasons else ""))
        for fn in list(self.listeners):
            try:
                fn(plan, status=status, reasons=reasons, instrument=self.inst, symbol=info.get("name") or "",
                   f1=st.V(self.prof, "exits", "tp1_fraction") if (sz or {}).get("split", True) else 1.0,
                   horizon_s=st.V(self.prof, "exits", "max_hold_minutes") * 60, extra_cost=extra if eco else None, commission_known=com is not None)
            except Exception:  # noqa: BLE001 - an observer never stops the SHADOW machine
                import logging
                logging.getLogger("masterquo.scalp").exception("scalp listener failed")

    def _risk_reference(self, acc: dict, now: datetime | None = None, candidate: bool = False) -> dict | None:
        """Equity references of the daily / weekly loss limits (risk_reference.json, persisted: a restart does not reset them).
        1.46 arch (I0810): the reference of a UTC day / ISO week is the FIRST equity observed in it - tick() calls this on every poll,
        so a running bot records it right after 00:00 UTC (before: the equity at the first CANDIDATE of the day, hours later). The
        first-candidate equity is kept too (candidate=True) and the gate uses the higher of both (never a looser limit than before).
        Unreadable JSON -> a new reference marked unreadable_day (the gate blocks that day; before: a fresh baseline that passed);
        another read error -> None (the gate blocks, the file is left as it is for the next poll)."""
        eq = acc.get("equity")
        now = now or utcnow()
        day, week = now.strftime("%Y-%m-%d"), now.strftime("%G-W%V")
        p = self._root() / "risk_reference.json"
        cached = getattr(self, "_risk_ref", None)
        changed = False
        if cached is not None and cached[0] == str(p):
            ref = cached[1]
        else:
            try:
                ref = json.loads(p.read_text(encoding="utf-8"))
            except FileNotFoundError:
                ref = {}
            except ValueError:
                ref = None
            except OSError:
                return None
            if not isinstance(ref, dict):
                ref, changed = {"unreadable_day": day, "unreadable_at": iso(now)}, True
        if eq:
            if ref.get("day") != day:
                ref.update(day=day, day_equity=eq, day_observed_at=iso(now))
                changed = True
            if ref.get("week") != week:
                ref.update(week=week, week_equity=eq, week_observed_at=iso(now))
                changed = True
            if candidate and ref.get("day_candidate") != day:
                ref.update(day_candidate=day, day_candidate_equity=eq)
                changed = True
            if candidate and ref.get("week_candidate") != week:
                ref.update(week_candidate=week, week_candidate_equity=eq)
                changed = True
        if changed:
            p.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(p, json.dumps(ref))                         # 1.46: tmp + replace (an interrupted write_text left a broken file)
        self._risk_ref = (str(p), ref)
        return ref

    def _loss_limits(self, acc: dict, now: datetime | None = None) -> tuple[bool, str]:
        eq = acc.get("equity")
        if not eq:
            return False, "brak equity"
        now = now or utcnow()
        ref = self._risk_reference(acc, now, candidate=True)
        if ref is None:
            return False, "UNAVAILABLE – risk_reference.json nie daje się odczytać – limity strat niezweryfikowane"
        day_ref = max(float(ref["day_equity"]), float(ref.get("day_candidate_equity") or 0.0))
        week_ref = max(float(ref["week_equity"]), float(ref.get("week_candidate_equity") or 0.0))
        dl = (day_ref - eq) / day_ref * 100
        wl = (week_ref - eq) / week_ref * 100
        ok = dl < st.V(self.prof, "risk", "daily_loss_pct") and wl < st.V(self.prof, "risk", "weekly_loss_pct")
        why = f"dzień {dl:.2f}% / tydzień {wl:.2f}% (equity całego konta, reset 00:00 UTC; wpłaty/wypłaty nie są korygowane)"
        if ref.get("unreadable_day") == now.strftime("%Y-%m-%d"):
            return False, "UNAVAILABLE – risk_reference.json był nieczytelny, odniesienie dnia nieznane (do 00:00 UTC); " + why
        obs = ref.get("day_observed_at")
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        lag = (parse_iso(obs) - midnight).total_seconds() if obs else None
        if lag is None or lag > RISK_REF_MAX_LAG_S:                        # started during the day: the loss since 00:00 is unknown
            # 1.46 arch (I0810, review): a bot started after 00:10 UTC has no READY_SHADOW (no scalp signal, no SHADOW settlement) until
            # 00:00 UTC; reconstructing the day reference from the MT5 deal history is a separate item (not implemented)
            return False, (f"NOT_VERIFIED – brak equity z początku dnia (pierwsza obserwacja {obs[11:16] if obs else '?'} UTC, start w trakcie dnia); "
                           f"do 00:00 UTC żaden kandydat nie dostanie READY_SHADOW – bot działający o północy UTC (do 00:{RISK_REF_MAX_LAG_S // 60:02d}) "
                           "zapisze odniesienie następnego dnia; " + why)
        return ok, why

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
    def _outcome(self, P, plan: dict) -> tuple[str, dict | None]:
        """Full-cycle outcome of ONE plan with the replay rules (shared by SHADOW settlement and the ML scalp labels).
        Returns (status, outcome): PENDING (bars not yet available / cycle open), NO_DATA, MISSED_LIMIT or SETTLED."""
        T = plan["decision_ts"]
        i = P.index.get(T)
        if i is None:
            return ("NO_DATA" if P.t and P.t[-1] > T + 120 else "PENDING"), None
        sgn = 1 if plan["direction"] == "BUY" else -1
        sz = plan.get("sizing") or {}
        f1 = st.V(self.prof, "exits", "tp1_fraction") if sz.get("split", True) else 1.0
        tp2 = plan["tp2"] if f1 < 1 else None
        costs = self._costs(plan)
        slip = costs["slippage_price"]
        at_open = True
        if plan.get("entry_mode") == "LIMIT_EDGE":
            fl = replay.get_fill(plan, P, T, slip)
            if not fl["ok"]:
                if fl["reason"] == "SPREAD_UNKNOWN":
                    return "NO_DATA", None                             # 1.46: was PENDING forever (blocked the one-cycle gate)
                if fl["reason"] == "MISSED_LIMIT_NOT_FILLED" and P.t[-1] >= T + 60 * (plan.get("limit_wait_m1") or 3):
                    return "MISSED_LIMIT", None
                return "PENDING", None
            i, fill, at_open = fl["i"], fl["fill"], fl.get("at_open", True)
        elif plan.get("fill_shadow") is not None:
            fill = plan["fill_shadow"] + sgn * slip                     # 1.46: adverse slippage on the entry, as replay.get_fill
        else:
            # 1.46: no live quote in the snapshot (ML / NSS candidates): next M1 open with the replay rules - Ask needs the spread
            # (unknown = no label, was 0 -> BUY filled at Bid), slippage, and the chase limit when the plan carries it
            if P.sp[i] is None:
                return "NO_DATA", None
            fill = P.o[i] + (P.sp[i] if sgn > 0 else 0.0) + sgn * slip
            if plan.get("ref_close_bid") is not None and plan.get("chase_limit") is not None:
                ref_exec = plan["ref_close_bid"] + ((plan.get("spread_at_signal") or P.sp[i]) if sgn > 0 else 0.0)
                if sgn * (fill - ref_exec) > plan["chase_limit"]:
                    return "MISSED_LIMIT", None
        # 1.46: risk with the round-trip costs (as st.economics) when the snapshot has no economics (was the bare price distance)
        risk = (plan.get("economics") or {}).get("risk_per_unit") or (abs(fill - plan["sl"]) + 2 * costs["commission_price_side"] + 2 * slip)
        res = replay.walk(P, i, sgn, 1.0, plan["sl"], plan["tp1"], tp2, f1, P.t[i] + st.V(self.prof, "exits", "max_hold_minutes") * 60, costs,
                          entry=fill, open_in_first_bar=at_open, **replay.exit_params(self.prof, costs, risk))
        if res.get("spread_unknown"):
            return "NO_DATA", None                                     # 1.46: a bar without spread on the exit side - no guessed outcome
        if res.get("open_at_end") or not res["exits"]:
            return "PENDING", None
        net = replay.pnl(sgn, fill, 1.0, res["exits"], costs)
        return "SETTLED", {"exits": [{"vol": v, "price": px, "time": st.iso_ts(t), "reason": rs} for (v, px, t, rs) in res["exits"]],
                           "ambiguous": res["ambiguous"], "precision": "OHLC_APPROX", "costs": {k: round(v, 5) for k, v in costs.items()},
                           "net_r": net / risk if risk else None, "label_end": st.iso_ts(res["exits"][-1][2]),
                           "note": "wynik po prowizji i poślizgu (te same zasady co replay)"}

    def settle(self, m1: list[dict], point: float) -> None:
        rows = self.db.query("SELECT * FROM scalp_shadow WHERE outcome_status='PENDING' AND instrument=? LIMIT 50", (self.inst,))
        mlrows = self.ml.scalp_pending(self.inst) if self.ml is not None else []
        nrows = self.nss.pending() if getattr(self, "nss", None) is not None else []
        if not rows and not mlrows and not nrows:
            return
        bars = [dict({k: b.get(k) for k in ("open_utc", "o", "h", "l", "c")}, spread_price=(b["spread"] * point if b.get("spread") is not None else None))
                for b in m1]
        P = replay.Path(bars, None)
        for r in rows:
            stt, out = self._outcome(P, json.loads(r["plan"]))
            if stt in ("NO_DATA", "MISSED_LIMIT"):
                self.db.execute("UPDATE scalp_shadow SET outcome_status=?, settled_at=? WHERE id=?", (stt, iso(utcnow()), r["id"]))
            elif stt == "SETTLED":
                self.db.execute("UPDATE scalp_shadow SET outcome_status='SETTLED', outcome=?, net_r=?, settled_at=? WHERE id=?",
                                (json.dumps(out), out["net_r"], out["label_end"], r["id"]))
        for r in nrows:                                    # NSS inference labels (first exit + net_R of the cycle), after maturity
            stt, out = self._outcome(P, json.loads(r["plan"]))
            if stt != "PENDING":
                self.nss.label(r["inference_id"], stt, out)
        for r in mlrows:                                   # ML scalp labels: every candidate, same policy, written after maturity
            stt, out = self._outcome(P, json.loads(r["plan"]))
            if stt != "PENDING":
                self.ml.scalp_label(r["sample_id"], stt, out)

    def _costs(self, plan: dict) -> dict:
        cfg = self.cfg_store.get()
        info = self.bridge.symbol_info or {}
        cs = float(info.get("trade_contract_size") or 100.0)
        tick = float(info.get("trade_tick_size") or 0.01)
        # 1.46 arch (I0738): commission (account currency) -> price with the same conservative conversion as the live economics gate
        return {"commission_price_side": commission_price(cfg.scalp.commission_per_lot_side or 0.0, cs, money_per_price(info)),
                "slippage_price": cfg.scalp.slippage_ticks * tick}

    def liquidity_context(self, plan: dict) -> dict:
        if self.liquidity is None:
            return {"status": "NOT_INSTALLED"}
        try:
            from ..analytics import liquidity_context as lc
            T = plan["decision_ts"]
            tf = self.liquidity.cfg.sessions_base_tf
            bars = (getattr(self, "_bars", {}) or {}).get(tf) or []
            sess = self.liquidity.sessions(bars, 60 if tf == "M1" else 300, self.inst, T)
            from datetime import datetime as _dt, timezone as _tz
            D = _dt.fromtimestamp(T, _tz.utc).isoformat()
            hm = self.liquidity.heatmap_public(self.inst, D, max_cells=0)
            hm.pop("grid", None)
            return lc.evaluate(boxes=sess["boxes"], heatmap=hm, price=plan.get("ref_close_bid"), atr_m5=(plan.get("range") or {}).get("atr_m5"),
                               setup={"side": plan["direction"], "setup_id": plan["setup_id"]}, as_of=D)
        except Exception as exc:  # noqa: BLE001 - observation only
            return {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}

    def neural(self, plan: dict) -> dict:
        if getattr(self, "nss", None) is None:
            return {"status": "NOT_INSTALLED"}
        try:
            info = self.bridge.symbol_info or {}
            point = float(info.get("point") or info.get("trade_tick_size") or 0.01)
            return self.nss.submit(plan, getattr(self, "_bars", {}) or {}, instrument=self.inst, profile_hash=st.profile_hash(self.prof),
                                   epoch=getattr(self.bridge, "session_epoch", None), point=point)
        except Exception as exc:  # noqa: BLE001 - observation only
            return {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}

    def ml_scalp(self, plan: dict) -> dict:
        if self.ml is None:
            return {"status": "NOT_INSTALLED"}
        try:
            return self.ml.on_scalp_candidate(dict(plan), instrument=self.inst, profile_hash=st.profile_hash(self.prof),
                                              session_epoch=getattr(self.bridge, "session_epoch", None), costs=self._costs(plan),
                                              entry_mode=plan.get("entry_mode", "MARKET"))
        except Exception as exc:  # noqa: BLE001 - observation only
            return {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}

    def indicator_context(self, plan: dict) -> dict:
        """SCALP_INDICATOR_CONTEXT_V2 for THIS setup (same composer as training). No active model -> NO_MODEL (no percentage).
        1.46 arch: the model comes from the injected ExtIndService (I0077 - scalp does not import extind); the SAR window gets its
        own fetch of closed M5 / M15 (I0165 - the 400 bars of tick() lose one bar to _closed when an M5 closed after the decision)."""
        try:
            why: list = []
            m = self.extind.active_model(self.inst, why) if self.extind is not None else None
            if m is None:
                return {"status": "NO_MODEL", "task_id": "SCALP_TP1_FIRST_WITHIN_FROZEN_POLICY_V1",
                        "reason": (f"aktywny model kontekstu wskaźników nie daje się wczytać: {why[0]}" if why else
                                   "brak aktywnego modelu kontekstu wskaźników (indicator-context train + activate)")}
            from datetime import datetime as _dt, timezone as _tz
            t = _dt.fromtimestamp(plan["decision_ts"], _tz.utc)
            need = int(getattr(m, "bars_needed", 404))
            bars = {k: [b for b in self.bridge.bars(k, need, include_forming=False) if b.get("open_utc")] for k in ("M5", "M15")}
            ext = {a: self.extind.as_of(a, self.inst, t) for a in ("IQ_GOLD_GANN", "IQ_STAR_LINES")}
            return dict(m.predict({"decision_time": t, "side": plan["direction"], "price": plan["ref_close_bid"], "atr_m5": plan["range"]["atr_m5"],
                                   "base": plan.get("features") or {}, "bars": bars, "ext": ext}, self.inst),
                        setup_id=plan["setup_id"], as_of=plan["decision_time"])
        except Exception as exc:  # noqa: BLE001 - observation only
            return {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:200]}

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
        rows = self.db.query("SELECT status, outcome_status, net_r, decision_time_utc FROM scalp_shadow WHERE instrument=?", (self.inst,))
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
            # 1.46 arch (I0025): no symbol spec = no forecast (it guessed point 0.01 for the spread scale; training uses the export's point)
            pt = float((self.bridge.symbol_info or {}).get("point") or 0)
            if pt <= 0:
                return {"status": "UNAVAILABLE", "reason": "brak specyfikacji symbolu (point) z MT5 – prognoza bez zgadywania skali spreadu"}
            m1 = self.bridge.bars("M1", 400, include_forming=False)
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

    def _root(self) -> Path:
        import mq_instruments
        return mq_instruments.root("scalp", getattr(self, "inst", "XAUUSD"))

    def registry(self) -> dict:
        p = self._root() / "registry.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"active": None, "runs": {}}

    def training_status(self) -> dict:
        d = self._root()
        hist = sorted((d / "history").glob("*/source_metadata.json"))
        stf = d / "TRAINING_STATUS.json"
        runs = sorted((d / "runs").glob("*/report.json"))
        rep = sorted((d / "replay").glob("*/summary.json"))
        # 1.46: these three were parsed without error handling - one damaged file (interrupted write) raised in every tick ->
        # ERROR_RECOVERY and a rebuild of the machine on each M1. Unreadable = None + listed, never an exception.
        bad: list[str] = []
        status_file = _read_json(stf, bad) if stf.exists() else None
        last_run = _read_json(runs[-1], bad) if runs else None
        last_replay = _read_json(rep[-1], bad) if rep else None
        return {"history_exports": [h.parent.name for h in hist[-5:]],
                "status_file": status_file,
                "last_run": last_run.get("summary") if isinstance(last_run, dict) else None,
                "last_replay": last_replay if isinstance(last_replay, dict) else None,
                "unreadable_files": bad,
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


def _tf_lag(bars: dict, T: int, m1_open: set) -> list[str]:
    """Higher TFs whose bar closing at or before T is not in the poll although the market traded in its last minute (an M1 opened
    at its close - 60 s is there): the M1 of T would reach the machine before it (1.46 arch I0737)."""
    out = []
    for tf in ("M5", "M15", "M30", "H1"):
        b = bars.get(tf) or []
        if not b:
            continue                                        # no bars at all: the context filter reports WARMUP
        due = st.ts(b[-1]["open_utc"]) + 2 * TFS[tf] * 60   # close of the bar after the newest one received
        if due <= T and (due - 60) in m1_open:
            out.append(tf)
    return out


def money_per_price(info: dict) -> float | None:
    """Account currency per 1.0 of price per 1 lot from MT5 (trade_tick_value / trade_tick_size), None when MT5 did not give both."""
    try:
        tv, ts_ = float(info.get("trade_tick_value") or 0), float(info.get("trade_tick_size") or 0)
    except (TypeError, ValueError):
        return None
    return tv / ts_ if tv > 0 and ts_ > 0 else None


def commission_price(com: float, contract_size: float, mpp: float | None) -> float:
    """Commission per lot side (account currency) in price units per unit volume - the larger of com / contract size (quote currency =
    account currency, the value before 1.46 arch) and com / money_per_price (MT5 conversion): never a smaller cost than before."""
    old = com / contract_size if contract_size > 0 else 0.0
    return max(old, com / mpp) if mpp else old


def economics_gate(plan: dict, fill: float, spread: float, com: float, contract_size: float, mpp: float | None, slippage_ticks: float,
                   tick: float, prof: dict) -> tuple[dict, float, bool, str]:
    """The live 'koszt i RR' gate: (economics at the account-currency cost, that cost, ok, detail).
    1.46 arch (I0738, review): a higher cost alone is not monotonic in economics (risk = side + cost crosses 0 for an entry at / beyond the
    SL), so the gate also requires the economics at the cost before 1.46 arch (2 x com / contract size + slippage, the same formula) -
    by construction never a pass that the code before did not give. economics() itself rejects an execution price at / beyond the SL."""
    extra = 2 * commission_price(com, contract_size, mpp) + 2 * slippage_ticks * tick
    eco = st.economics(plan, fill, spread, extra, prof)
    extra0 = 2 * com / contract_size + 2 * slippage_ticks * tick
    eco0 = eco if extra0 == extra else st.economics(plan, fill, spread, extra0, prof)
    ok = bool(eco["ok"] and eco0["ok"])
    detail = eco["reason"] if ok or not eco["ok"] else f"{eco0['reason']} (koszt sprzed 1.46: prowizja / rozmiar kontraktu)"
    return eco, extra, ok, detail


def _read_json(p: Path, bad: list[str]):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        bad.append(f"{p.parent.name}/{p.name}" if p.parent.name else p.name)
        return None


def _atomic_write_text(p: Path, text: str) -> None:
    tmp = p.with_name(f"{p.name}.tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def _load_last(base: Path, name: str):
    f = sorted(base.glob(f"*/{name}"))
    try:
        return json.loads(f[-1].read_text(encoding="utf-8")) if f else None
    except (OSError, ValueError):
        return None


def _r(x, n=4):
    return round(x, n) if isinstance(x, float) else x
