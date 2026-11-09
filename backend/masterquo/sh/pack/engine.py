"""Pack engine: evaluates the 20 variants inside the EXISTING SH cycle (one shared feature generation per symbol / TF / closed bar) and
returns setup-shaped candidates that go through the SAME coordinator -> risk -> DecisionCoordinator -> IntentLedger/RiskBook ->
executor path as the legacy SCALPING / HEDGING strategies. Nothing here sends an order.

Per (variant, signal TF): the rule is run for BUY and for the mirrored SELL. A setup becomes a plan only after the two-target solver
(solver.py) and the hedge bound (policies.py) accept it; the result keeps three things apart: the analytical state (READY / WAIT /
NO_TRADE / INVALIDATED / EXPIRED with reason codes), the permission to execute (risk + coordination + mode, decided later) and an actual
position (plan bound to fills). A READY setup is kept until its TTL (3 trigger-TF bars, max 10 min SC / 30 min HG; the earliest limit
wins), its pre-fill invalidation, or a price departure larger than 0.25 ATR from the trigger close. Signal ids are idempotent:
instrument / variant / version / config hash / TF / side / structure key / trigger-bar close - a refresh never creates a new id.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import deque

from . import catalog as CAT
from . import detectors as D
from . import features as F
from . import policies as P
from . import solver as SV

PLAN_CONTRACT = "PMW-PLAN-2"
TF_ORDER = ("M1", "M3", "M5", "M15", "H1")
NEEDED_BARS = {"M1": 900, "M3": 500, "M5": 700, "M15": 400, "H1": 1050}


def _sid(*parts) -> str:
    return "SH-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:14]


class PackEngine:
    def __init__(self, *, clock=time.time):
        self.clock = clock
        self.active: dict = {}           # (vid, tf, side) -> READY candidate kept until TTL / invalidation / departure / plan
        self.last: dict = {}             # (vid, tf) -> latest evaluation (any state) for the panel
        self.timings = deque(maxlen=500)
        self.cfg_hash = None
        self.ctx: F.Context | None = None

    # ------------------------------------------------------------------ public
    def evaluate(self, *, bars: dict, quote: dict | None, spec, inst: str, ic: dict, now: float, cfg: dict | None = None,
                 account_currency: str | None = None) -> list[dict]:
        t0 = time.perf_counter()
        cfg = cfg or CAT.load()
        self.cfg_hash = cfg["hash"]
        pipdef = (cfg["instruments"] or {}).get(inst)
        X = F.Context(bars, tick=spec.tick_size, common=cfg["common"], as_of=now, symbol=spec.symbol, instrument=inst)
        gp = getattr(self, "garch_provider", None)
        if gp is not None:
            try:
                X.garch = gp(inst)
            except Exception as exc:  # noqa: BLE001 - an unreadable artifact = not ready (never another method)
                X.garch = {"status": f"ERROR {type(exc).__name__}"}
        self.ctx = X
        out = []
        try:
            mpp = spec.money_per_price(1.0)
        except Exception:  # noqa: BLE001 - unknown tick value: costs stay a scenario, sizing is refused later by the risk engine
            mpp = None
        for vid in CAT.IDS:
            v = cfg["variants"][vid]
            for tf in v["signal_tfs"]:
                if not v["enabled"]:
                    su = self._shell(v, tf, inst, spec, now, "WAIT", "DISABLED", "wariant wyłączony w konfiguracji pakietu")
                elif not pipdef:
                    su = self._shell(v, tf, inst, spec, now, "NO_TRADE", "PIP_DEFINITION_UNRESOLVED",
                                     f"brak jawnej definicji pipsa dla {inst} – wykonanie nowych profili niedostępne")
                else:
                    su = self._one(X, v, tf, inst, spec, ic, quote, now, pipdef, cfg, mpp, account_currency)
                self.last[(vid, tf)] = su
                out.append(su)
        self._group_peers(out)
        self.timings.append(round((time.perf_counter() - t0) * 1000, 2))
        return out

    def timing(self) -> dict:
        xs = sorted(self.timings)
        if not xs:
            return {"n": 0}
        pick = lambda q: xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]  # noqa: E731
        return {"n": len(xs), "p50_ms": pick(0.5), "p95_ms": pick(0.95), "max_ms": xs[-1]}

    def consumed(self, su: dict) -> None:
        """A plan was created from this candidate: it is no longer a pending READY (the plan owns it now)."""
        p = su.get("pack") or {}
        self.active.pop((su.get("strategy_id"), p.get("signal_tf"), su.get("side")), None)

    # ------------------------------------------------------------------ one variant / TF
    def _shell(self, v, tf, inst, spec, now, status, code, reason, **kw) -> dict:
        return {"strategy": v["family"], "strategy_id": v["strategy_id"], "signal_id": _sid(inst, v["strategy_id"], tf, status, code),
                "instrument": inst, "symbol": spec.symbol, "side": kw.pop("side", None), "status": status, "status_reason": reason,
                "created_at": now, "valid_until": None, "config_hash": v["config_hash"], "setup_version": v["strategy_version"],
                "checklist": kw.pop("checklist", []), "score": {"value": None, "definition": "heurystyka 0–100 z checklisty – NIE prawdopodobieństwo"},
                "probability": {"value": None, "status": "BRAK_MODELU_ZDARZENIA"},
                "pack": {"contract": PLAN_CONTRACT, "strategy_id": v["strategy_id"], "name": v["name"], "family": v["family"], "cluster": v["cluster"],
                         "setup_group_id": v["setup_group_id"], "signal_tf": tf, "context_tfs": v["context_tfs"],
                         "management_policy_id": v["management_policy_id"], "strategy_version": v["strategy_version"], "config_hash": v["config_hash"],
                         "validation": CAT.validation_status(v["strategy_id"]), "reason_code": code, "analytical_state": status, **kw}}

    def _one(self, X, v, tf, inst, spec, ic, quote, now, pipdef, cfg, mpp, ccy) -> dict:
        vid = v["strategy_id"]
        dets = {side: D.detect(X, v, tf, side) for side in ("BUY", "SELL")}
        setups = {s: d for s, d in dets.items() if d.get("status") == "SETUP"}
        # keep / re-check READY candidates of earlier bars
        kept = None
        for side in ("BUY", "SELL"):
            k = (vid, tf, side)
            if k in self.active:
                st = self._recheck(self.active[k], X, quote, now)
                if st["status"] != "READY":
                    self.active.pop(k, None)
                    if side not in setups:
                        kept = kept or st
                else:
                    kept = st
        if len(setups) == 2:
            return self._shell(v, tf, inst, spec, now, "WAIT", "CONFLICT_BOTH_SIDES", "reguła spełniona dla BUY i SELL w tym samym cyklu – WAIT")
        if setups:
            side, det = next(iter(setups.items()))
            if kept is not None and kept.get("side") == side and kept["status"] == "READY" and \
                    kept["pack"].get("trigger_bar_open") == F.iso(X.tf(tf, side == "SELL").t[det["trigger_i"]]):
                return kept                                               # same trigger bar: the frozen plan, not a re-solve at a new quote
            cand = self._plan(X, v, tf, side, det, inst, spec, ic, quote, now, pipdef, cfg, mpp, ccy)
            if cand["status"] == "READY":
                self.active[(vid, tf, side)] = cand
            return cand
        if kept is not None:
            return kept
        # no setup: the most advanced rejection (most PASS items) explains why
        best = max(dets.values(), key=lambda d: sum(1 for x in d.get("checklist") or [] if x["status"] == "PASS"))
        st = {"WARMING_UP": "WAIT", "NO_DATA": "WAIT", "NO_SETUP": "WAIT"}.get(best.get("status"), "WAIT")
        return self._shell(v, tf, inst, spec, now, st, best.get("reason_code") or "NO_SETUP", best.get("reason") or "warunki niespełnione",
                           checklist=best.get("checklist") or [], data_state=best.get("status"))

    def _recheck(self, su: dict, X: F.Context, quote, now) -> dict:
        p = su["pack"]
        if now > float(su.get("valid_until") or 0):
            return {**su, "status": "EXPIRED", "status_reason": "TTL minął przed wykonaniem", "pack": {**p, "analytical_state": "EXPIRED",
                                                                                                        "reason_code": "TTL"}}
        v = X.tf(p["signal_tf"], su["side"] == "SELL")
        inv = p["invalidation_pre_fill_view"]
        after = range(v.since(F.ts(p["trigger_bar_open"]) + 1.0), v.n)
        if any(v.c[i] < inv for i in after):
            return {**su, "status": "INVALIDATED", "status_reason": "zamknięcie za poziomem unieważnienia przed wejściem",
                    "pack": {**p, "analytical_state": "INVALIDATED", "reason_code": "PRE_FILL_INVALIDATION"}}
        if quote:
            dep = abs(quote["bid"] - p["trigger_close"])                  # MT5 bars are Bid: departure measured on the same basis
            if dep > p["max_departure_price"]:
                return {**su, "status": "WAIT", "status_reason": f"cena odeszła {dep:.2f} od zamknięcia triggera (limit {p['max_departure_price']:.2f}) – brak pogoni",
                        "pack": {**p, "analytical_state": "WAIT", "reason_code": "ENTRY_DEPARTED"}}
        return su

    def _obstacle(self, X: F.Context, v: F.TF, ctx_tfs: list, mir: bool, E: float) -> tuple[float | None, str | None]:
        """Nearest opposite level known at entry, in view units above E: confirmed swing highs (signal TF, last 120 bars; context TFs, last
        60 bars) and the previous trading day's high."""
        cands = []
        for p in v.swings("H", v.n - 1):
            if p["i"] >= v.n - 120 and p["price"] > E:
                cands.append((p["price"], f"swing {v.name}"))
        for tf in ctx_tfs:
            w = X.tf(tf, mir)
            for p in w.swings("H", w.n - 1):
                if p["i"] >= w.n - 60 and p["price"] > E:
                    cands.append((p["price"], f"swing {tf}"))
        hi, _lo = X.prev_day_range(mir)
        if hi is not None and hi > E:
            cands.append((hi, "maksimum poprzedniej doby"))
        if not cands:
            return None, None
        return min(cands)

    def _plan(self, X, v, tf, side, det, inst, spec, ic, quote, now, pipdef, cfg, mpp, ccy) -> dict:
        vid, fam = v["strategy_id"], v["family"]
        rules, cm = v["rules"], cfg["common"]
        mir = side == "SELL"
        sg = -1.0 if mir else 1.0
        view = X.tf(tf, mir)
        i = det["trigger_i"]
        a = view.atr()[i]
        trig_open, trig_close_t = view.t[i], view.close_t(i)
        raw = X.raw.get(tf) or []
        raw_bar = next((b for b in reversed(raw[:view.n + view.excluded + 2]) if b.get("open_utc") and abs(F.ts(b["open_utc"]) - trig_open) < 1), {})
        available_at = raw_bar.get("available_at") or F.iso(trig_close_t)
        ttl = min(trig_close_t + rules["ttl_bars"] * view.tf_s, trig_close_t + 60 * rules["ttl_max_minutes"])
        one = bool(det.get("one_per_structure"))
        sid = _sid(inst, vid, v["strategy_version"], v["config_hash"], tf, side, det.get("structure_key"), None if one else trig_close_t)
        base = self._shell(v, tf, inst, spec, now, "WAIT", "OK", "", side=side, checklist=list(det.get("checklist") or []))
        base["signal_id"] = sid
        base["created_at"] = now
        trig_close_real = view.out(view.c[i])
        p = base["pack"]
        p.update(trigger_bar_open=F.iso(trig_open), trigger_bar_close=F.iso(trig_close_t), available_at=available_at, structure_key=det.get("structure_key"),
                 one_per_structure=one, trigger_close=trig_close_real, max_departure_price=float(cm.get("max_entry_departure_atr", 0.25)) * (a or 0.0),
                 invalidation_pre_fill_view=det.get("invalidation_pre_fill"), source_kind=view.source, data_revision=raw_bar.get("revision"),
                 structure_view=det.get("structure") or {}, mirror=mir, params=v["params"],
                 arrow={"time": available_at, "bar_open": F.iso(trig_open), "side": side, "label": f"{vid} / {tf}",
                        "position": "belowBar" if side == "BUY" else "aboveBar"})
        if not quote:
            base.update(status="WAIT", status_reason="brak notowania – plan wymaga wykonalnej ceny")
            p.update(analytical_state="WAIT", reason_code="NO_QUOTE")
            return base
        E_real = quote["ask"] if side == "BUY" else quote["bid"]
        E = sg * E_real
        if abs(quote["bid"] - trig_close_real) > p["max_departure_price"]:      # bars are Bid: same basis (E itself stays Ask for BUY)
            base.update(status="WAIT", status_reason="cena uciekła od zamknięcia triggera (brak pogoni)")
            p.update(analytical_state="WAIT", reason_code="ENTRY_DEPARTED")
            return base
        if det.get("invalidation_pre_fill") is not None and E <= det["invalidation_pre_fill"]:
            base.update(status="INVALIDATED", status_reason="cena za poziomem unieważnienia")
            p.update(analytical_state="INVALIDATED", reason_code="PRE_FILL_INVALIDATION")
            return base
        cst = SV.costs(ic, mpp, cm)
        c = cst["c_round_trip"]
        hedging = fam == "HEDGING"
        hl, hl_how, b5, ratio = None, None, None, None
        st = det.get("structure") or {}
        if hedging:
            m5 = X.tf("M5", mir)
            b5 = m5.b(m5.n - 1, spec.tick_size, cm)
            hc = v["hedge"] or {}
            ratio = float(hc.get("ratio", hc.get("ratio_max", 0.5)))
            S_try = SV.snap_out(det["sl"], spec.tick_size, False)
            hl, hl_how = P.hedge_loss_bound(vid, st, r=E - S_try, b5=b5 or 0.0, c=c, ratio=ratio, hcfg=hc, fam=rules)
        natural = det.get("natural_targets")
        tspace, tsrc = (None, None) if natural else self._obstacle(X, view, [t for t in v["context_tfs"] if t != tf], mir, E)
        reach = (a * math.sqrt(v["position_max_minutes"] * 60.0 / view.tf_s) * float(cm.get("reach_factor", 1.0))) if a else None
        sol = SV.solve(E=E, S_raw=det["sl"], tick=spec.tick_size, pip=float(pipdef["pip_size"]), rules=rules, c=c, natural=natural,
                       target_space=tspace, reach=reach, hedge_loss=hl, hedging=hedging)
        cl = base["checklist"]
        w1, w2 = rules["shares"]
        econ = {"c_round_trip": c, "cost_status": cst["cost_status"], "cost_basis": cst["basis"], "spread_note": cst["spread_note"],
                "commission_price_rt": cst["commission_price_rt"], "slippage_price": cst["slippage_price"],
                "initial_price_risk": sol.get("r"), "rr_tp1_gross": sol.get("rr_tp1_gross"), "rr_tp2_gross": sol.get("rr_tp2_gross"),
                "rr_plan_net": sol.get("rr_plan_net"), "rr_basket_net_target": sol.get("rr_basket_net_target") if hedging else None,
                "hedge_loss_bound_price": hl, "hedge_loss_bound_method": hl_how, "rr_min": rules["rr_min"],
                "target_distance_price": sol.get("d2"), "target_distance_pips": sol.get("d2_pips"), "target_space_price":
                    None if tspace is None else round(abs(tspace - E), 6), "target_space_source": tsrc, "reach_heuristic_price": reach,
                "account_currency": ccy, "net_validated": False,
                "rr_note": "RR brutto do pojedynczego TP ≠ RR planu netto; dla HG wymagane jest RR koszyka w scenariuszu celu"}
        if sol["status"] == "OK":
            econ["scenarios"] = SV.scenarios(d1=sol["d1"], d2=sol["d2"], r=sol["r"], c=c, hl=hl if hedging else None, w1=w1, w2=w2,
                                             stress_gap=float(cm.get("stress_gap_price", 1.0)), stress_slip=float(cm.get("stress_extra_slippage_price", 0.2)))
        p["economics"] = econ
        p["units"] = {"price_currency": spec.currency_profit, "pip_size": pipdef["pip_size"], "pip_definition": pipdef["pip_definition"],
                      "point": spec.point, "tick_size": spec.tick_size, "digits": spec.digits}
        p["models"] = {"p_tp1_before_sl": None, "p_tp2_before_sl": None, "p_net_positive": None, "expected_net_r": None,
                       "setup_quality_score": None, "model_agreement": None,
                       "reason": "brak skalibrowanego modelu zdarzenia dla tego EventSpec – prawdopodobieństwa = null (nie 0%, nie 80%)",
                       "legacy_tp_model": "sh_tp_model (TP2 = 3 USD, trzy części) NIEZGODNY z tym zdarzeniem – nie ocenia nowych planów"}
        p["event_spec"] = self.event_spec(v, tf, rules, econ, cm)
        if hedging:
            p["hedge"] = {"policy_id": v["management_policy_id"], **P.texts(vid), "ratio": ratio, "max_ratio": rules.get("max_ratio", 0.5),
                          "max_activations": 1, "max_hedge_minutes": (v["hedge"] or {}).get("max_hedge_minutes"),
                          "base_max_minutes": v["position_max_minutes"], "b_m5": b5,
                          "activation_level_if_scalar": view.out(P.activation_level_view(vid, st, b5 or 0.0)) if b5 is not None else None,
                          "status": "NOT_ACTIVE", "activations_used": 0}
        if sol["status"] != "OK":
            SVc = "FAIL"
            cl.append({"id": "plan", "label": "Plan dwóch TP i RR netto", "status": SVc, "detail": sol["reason"]})
            base.update(status="NO_TRADE", status_reason=sol["reason"], entry_ref=E_real, sl=view.out(sol.get("sl")))
            p.update(analytical_state="NO_TRADE", reason_code=sol["reason_code"])
            return base
        tp1, tp2, sl = view.out(sol["tp1"]), view.out(sol["tp2"]), view.out(sol["sl"])
        cl.append({"id": "plan", "label": "Plan dwóch TP i RR netto", "status": "PASS",
                   "detail": f"TP1 {sol['d1_pips']} pips, TP2 {sol['d2_pips']} pips, RR {'koszyka' if hedging else 'planu'} netto "
                             f"{(sol['rr_basket_net_target'] if hedging else sol['rr_plan_net'])}"})
        tps = [{"name": "TP1", "price": tp1, "share": w1, "distance_requested": sol["d1"], "distance_actual": sol["d1"], "distance_pips": sol["d1_pips"]},
               {"name": "TP2", "price": tp2, "share": w2, "distance_requested": sol["d2"], "distance_actual": sol["d2"], "distance_pips": sol["d2_pips"]}]
        passed = sum(1 for x in cl if x["status"] == "PASS")
        base.update(status="READY", status_reason=("wszystkie warunki spełnione" + (" (koszty: scenariusz – prowizja nieznana)"
                                                                                     if cst["cost_status"] != "KNOWN" else "")),
                    entry_ref=E_real, sl=sl, invalidation=sl, tps=tps, shares=[w1, w2], valid_until=ttl, horizon_minutes=v["position_max_minutes"],
                    position_max_minutes=v["position_max_minutes"], be=None, model_mode="OGRANICZONA", mode="PACK",
                    costs={"round_trip_price": round(c + (hl or 0.0), 6), "commission_known": cst["cost_status"] == "KNOWN",
                           "note": "koszt do sizingu = round trip + ograniczona strata hedge (HG)"},
                    net_rr=sol["rr_basket_net_target"] if hedging else sol["rr_plan_net"],
                    entry_zone=[min(E_real, trig_close_real), max(E_real, trig_close_real)])
        base["score"]["value"] = round(100.0 * passed / max(1, len(cl)), 1)
        p.update(analytical_state="READY", reason_code="OK", entry_plan=E_real, initial_sl=sl, tp1_price=tp1, tp2_price=tp2, tp1_share=w1, tp2_share=w2,
                 valid_until=ttl, ready_to_execute=False,
                 readiness_note="READY = analityczna gotowość; zgoda na wykonanie zależy od ryzyka, koordynatora, trybu i walidacji")
        return base

    @staticmethod
    def event_spec(v, tf, rules, econ, cm) -> dict:
        es = {"strategy_id": v["strategy_id"], "strategy_version": v["strategy_version"], "signal_tf": tf, "targets": ["TP1", "TP2"],
              "shares": rules["shares"], "costs": econ["cost_status"], "ttl_bars": rules["ttl_bars"], "ttl_max_minutes": rules["ttl_max_minutes"],
              "timeout_minutes": v["position_max_minutes"], "fill_rule": "następny tick po zamknięciu triggera (BUY Ask / SELL Bid)",
              "be": None, "hedge_policy": v["management_policy_id"] if v["family"] == "HEDGING" else None,
              "risk_reference": "initial_risk_money planu (z ograniczoną ścieżką hedge)", "ambiguous_bar_policy": "STOP_FIRST",
              "config_hash": v["config_hash"]}
        es["event_hash"] = hashlib.sha256(json.dumps(es, sort_keys=True).encode()).hexdigest()[:16]
        return es

    @staticmethod
    def _group_peers(out: list[dict]) -> None:
        """Signals from one logic group are not independent votes: every READY candidate lists its READY peers of the same setup group."""
        ready = [s for s in out if s["status"] == "READY"]
        for s in ready:
            g = s["pack"]["setup_group_id"]
            s["pack"]["group_peers"] = [f"{x['strategy_id']}/{x['pack']['signal_tf']}" for x in ready if x is not s and x["pack"]["setup_group_id"] == g]

    # ------------------------------------------------------------------ execution profile (frozen into the plan)
    @staticmethod
    def profile(su: dict, fam_prof: dict, cfg: dict | None = None) -> dict:
        """Variant profile for the shared risk engine / plan freezing: exactly two targets, no fallback, no BE, variant hedge limits."""
        cfg = cfg or CAT.load()
        v = cfg["variants"][su["strategy_id"]]
        r = v["rules"]
        prof = {"shares": list(r["shares"]), "shares_fallback_two": None, "position_max_minutes": v["position_max_minutes"],
                "horizon_minutes": v["position_max_minutes"], "be_after": None, "be_rule": None, "min_net_rr": r["rr_min"],
                "strategy_id": v["strategy_id"], "strategy_version": v["strategy_version"], "config_hash": v["config_hash"],
                "_instrument": fam_prof.get("_instrument") or {}}
        if v["family"] == "HEDGING":
            prof["hedge"] = {"max_ratio": r.get("max_ratio", 0.5), "ratio": (v["hedge"] or {}).get("ratio", (v["hedge"] or {}).get("ratio_max", 0.5)),
                             "max_activations": 1, "basket_loss_limit_x_risk": r.get("basket_loss_limit_x_risk", 1.0),
                             "netting_alternative": r.get("netting_alternative", "BLOCK"), "max_hedge_minutes": (v["hedge"] or {}).get("max_hedge_minutes"),
                             "policy_id": v["management_policy_id"]}
        return prof

    def public(self) -> dict:
        items = []
        for (vid, tf), su in sorted(self.last.items()):
            p = su.get("pack") or {}
            items.append({"strategy_id": vid, "signal_tf": tf, "family": su.get("strategy"), "status": su.get("status"),
                          "reason_code": p.get("reason_code"), "reason": su.get("status_reason"), "side": su.get("side"),
                          "signal_id": su.get("signal_id") if su.get("status") in ("READY", "EXPIRED", "INVALIDATED") else None,
                          "updated_at": su.get("created_at")})
        return {"contract": PLAN_CONTRACT, "items": items, "timing": self.timing(), "config_hash": self.cfg_hash}
