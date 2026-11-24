"""Smoke checks of the Quant area (`models check --smoke --area quant`): evaluation engine, Quant MetaModel, TabICLv2.

Every function goes through the bot's own objects on SYNTHETIC_TEST data (FakeMT5 bars through ctx): EvaluationService (the SHADOW
ledger of every setup), QuantService (the Quant Core thread: cycle -> assess -> ledger -> train_from_ledger -> metamodel artifacts) and
TabICLService (the confidence estimator). A result is a technical check of the path, never a quality claim.
"""
from __future__ import annotations

import math
import time

from . import check, fail, ok, unverified

INST = "XAUUSD"


# ---------------------------------------------------------------------------------------------------------------- shared helpers
class _Bridge:
    """MarketBridge surface used by QuantService / EvaluationService, filled with closed FakeMT5 bars (synthetic terminal of the bot)."""

    synthetic = True

    def __init__(self, ctx):
        from types import SimpleNamespace
        f = ctx.fake()
        self._fake = f
        self.series = {tf: ctx.bars(tf, n) for tf, n in (("M1", 600), ("M5", 300), ("M15", 200), ("H1", 200))}
        self.tfs = {k: None for k in self.series}
        self.cfg = SimpleNamespace(symbol=f.symbol)
        self.buffer_symbol = f.symbol
        si = f.symbol_info(f.symbol)
        self.symbol_info = dict(si._asdict()) if hasattr(si, "_asdict") else {"point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0}

    def bars(self, tf, limit=None, include_forming=True):
        rows = list(self.series.get(tf, []))
        return rows[-limit:] if limit else rows

    def quote_status(self):
        t = self._fake.symbol_info_tick(self._fake.symbol)
        return {"bid": float(t.bid), "ask": float(t.ask), "age_seconds": 0.5} if t else None


def _rt(ctx):
    from types import SimpleNamespace
    return SimpleNamespace(bridge=_Bridge(ctx), sh=SimpleNamespace(instrument=lambda: INST, snapshot=None))


def _sh_setup(bridge, back: int = 120, sid: str = "SMOKE-SH-1") -> dict:
    """SCALPING setup (status READY) priced on a closed FakeMT5 M1 bar `back` bars before the newest one (its 30 min horizon lies
    inside the buffer, so the outcome can mature from the same bars)."""
    b = bridge.series["M1"][-back]
    ref = round(float(b["c"]), 2)
    tps = [("TP1", 1.0, 0.5), ("TP2", 2.0, 0.3), ("TP3", 3.0, 0.2)]
    return {"signal_id": sid, "strategy": "SCALPING", "instrument": INST, "symbol": bridge.buffer_symbol, "side": "BUY", "status": "READY",
            "entry_ref": ref, "sl": round(ref - 2.0, 2), "tps": [{"name": n, "price": round(ref + d, 2), "share": s} for n, d, s in tps],
            "costs": {"round_trip_price": 0.3, "spread": 0.2, "commission_known": True}, "horizon_minutes": 30, "created_at": float(b["t"]) + 60.0,
            "score": {"value": 80}, "net_rr": 1.2, "mode": "CONTINUATION", "model_mode": "OGRANICZONA"}


def _ledger_rows(ledger, spec, n: int, kind: str, seed: int, prefix: str) -> int:
    """Labelled ledger rows of ONE task (the row format QuantService.assess(log_row=True) + mature() write). Synthetic: one informative
    column (ctx:heuristic_score), the rest noise; decision times strictly in the past."""
    import numpy as np
    rng = np.random.default_rng(seed)
    t0 = time.time() - 86400.0 * 30
    sd = spec.to_dict()
    for i in range(n):
        x = float(rng.normal())
        y = int(rng.random() < 1.0 / (1.0 + math.exp(-1.5 * x)))
        dts = t0 + i * 600.0
        feats = {"plan:gain_r": 0.85, "plan:tp1_r": 0.5, "ctx:heuristic_score": x, "ctx:hour_sin": float(rng.normal()), "ctx:cost_r": 0.15}
        rid = f"{prefix}{i}"
        ledger.add_row({"row_id": rid, "instrument": INST, "engine": "SH_SCALPING", "strategy": "SCALPING", "direction": "LONG", "decision_ts": dts,
                        "task_hash": spec.task_hash(), "event_id": spec.event_id, "spec": sd, "features": feats, "data_kind": kind,
                        "matures_at": dts + spec.horizon_s})
        ledger.label(rid, "LABELLED", {"y_event": y, "net_r": (0.85 if y else -1.15)}, dts + 1800.0)
    return n


# ---------------------------------------------------------------------------------------------------------------- analysis:evaluation
def _evaluation(ctx) -> dict:
    """EvaluationService (runtime SHADOW ledger): SH setup -> SetupCandidate -> engine.assess -> ledger row -> listener -> outcome from M1."""
    from ...config import ConfigStore
    from ...db.database import Database
    from ...evaluation import contract as K
    from ...evaluation.service import EvaluationService
    ctx.step = "predict"
    br = _Bridge(ctx)
    svc = EvaluationService(ConfigStore(), br, Database(), data_dir=ctx.data_dir / "smoke_evaluation", clock=time.time)
    seen: list = []
    svc.listeners.append(lambda c, ad: seen.append((c.key(), ad.get("decision"))))
    su = _sh_setup(br)
    now = su["created_at"]
    svc.on_sh_cycle({"SCALPING": su, "HEDGING": {"status": "WAIT", "strategy": "HEDGING"}}, inst=INST, symbol=su["symbol"],
                    snap={"regime": {"state": "TREND"}}, now=now)
    svc.on_sh_cycle({"SCALPING": su}, inst=INST, symbol=su["symbol"], snap=None, now=now + 1)          # same version: duplicate, no new row
    items = svc.assessments("SH_SCALPING")
    if not items:
        return {"predict": fail(f"brak oceny w ledgerze (liczniki {svc.counters}, ostatni błąd {svc.last_error})")}
    it = items[0]
    out = it.get("outcome") or {}
    good = (svc.counters["logged"] == 1 and svc.counters["duplicates"] == 1 and len(seen) == 1 and it["decision"] in ("ACCEPT", "REDUCE", "DEFER", "REJECT")
            and out.get("status") in ("MATURED", "NO_BARS"))
    steps = {"predict": check(good, f"SH_SCALPING -> decyzja SHADOW {it['decision']} ({it['probability_status']}), p*={it['break_even_probability']}, "
                                    f"gain_r={it['gain_r']}, loss_r={it['loss_r']}, cost_r={it['cost_r']}; wynik z M1 FakeMT5: {out.get('status')} "
                                    f"first_event={out.get('first_event')} event_hit={out.get('event_hit')}; słuchacz Quant wywołany {len(seen)}×, "
                                    f"duplikat odrzucony",
                              f"liczniki {svc.counters}, słuchacz {len(seen)}×, decyzja {it.get('decision')}, wynik {out.get('status')} ({svc.last_error})")}
    ctx.step = "contract"
    errs = []
    try:
        K.from_sh_setup(su, regime={"state": "TREND"}).validate()
    except K.ContractError as exc:
        errs.append(f"SetupCandidate: {exc}")
    bad = dict(su, sl=su["entry_ref"] + 1.0, signal_id="SMOKE-SH-BAD")             # stop on the wrong side: contract violation, not a row
    svc.on_sh_cycle({"SCALPING": bad}, inst=INST, symbol=su["symbol"], snap=None, now=now + 2)
    if svc.counters["invalid"] != 1:
        errs.append(f"błędny plan nie został odrzucony kontraktem (invalid={svc.counters['invalid']})")
    p_star = it.get("break_even_probability")
    if p_star is None or not 0.0 < p_star < 1.0:
        errs.append(f"break_even_probability poza (0,1): {p_star}")
    if it["probability"] is not None or it["probability_status"] != "NO_MODEL":
        errs.append(f"prawdopodobieństwo bez modelu: {it['probability']} / {it['probability_status']} (oczekiwane None / NO_MODEL)")
    rep = svc.report()
    if rep.get("mode") != "SHADOW" or svc.status().get("mode") != "SHADOW":
        errs.append("tryb inny niż SHADOW")
    steps["contract"] = check(not errs, f"PMW-EVAL-CONTRACT-1: kandydat poprawny, zły plan odrzucony (CONTRACT:{(svc.last_error or '')[9:40]}), brak P bez "
                                        f"modelu, raport SHADOW ({rep.get('matured')} dojrzałych)", "; ".join(errs))
    svc.ledger.c.close()
    return steps


# ---------------------------------------------------------------------------------------------------------------- quant:metamodel
def _metamodel(ctx) -> dict:
    """QuantService: cycle -> ledger (SYNTHETIC) -> train (train_from_ledger -> metamodel.train/save) -> activation gate; technical
    VALIDATED_SHADOW artifact -> load roundtrip -> EvaluationService listener -> QuantService.assess READY -> coordinator_entry."""
    from ...config import ConfigStore
    from ...db.database import Database
    from ...evaluation import contract as K
    from ...evaluation.service import EvaluationService
    from ...quant import events as EV
    from ...quant import metamodel as M
    from ...quant.ledger import QuantLedger
    from ...quant.service import QuantService, train_from_ledger
    ctx.step = "train"
    rt = _rt(ctx)
    q = QuantService(rt, data_dir=ctx.data_dir / "smoke_quant_meta")
    steps: dict = {}
    try:
        pub = q.cycle()
        su = _sh_setup(rt.bridge, sid="SMOKE-QM-1")
        c = K.from_sh_setup(su).validate()
        cd = dict(c.to_dict(), candidate_key=c.key())
        spec = EV.spec_from_candidate(cd)
        th = spec.task_hash()
        # 1) the bot's own data world: SYNTHETIC rows -> real trainer -> artifact that the activation gate must refuse
        _ledger_rows(q.ledger, spec, 900, "SYNTHETIC", 1, "syn")
        t0 = time.monotonic()
        job = q.train(INST, th, background=False)
        res = (job.get("results") or [{}])[0]
        gate_msg = None
        try:
            M.activate(INST, th, res.get("version") or "missing")
        except M.MetaError as exc:
            gate_msg = str(exc)
        a0 = q.assess(cd)
        syn_ok = (job["state"] == "DONE" and res.get("status") == "VALIDATION_FAILED" and "data_real" in (res.get("failed_gates") or [])
                  and bool(res.get("version")) and (gate_msg or "").startswith("NOT_VALIDATED") and a0.get("status") == "NOT_TRAINED")
        if not syn_ok:
            return {"train": fail(f"ścieżka SYNTHETIC: job {job.get('state')} {job.get('error')}, wynik {res}, aktywacja {gate_msg}, assess {a0.get('status')} "
                                  "(oczekiwane VALIDATION_FAILED[data_real] + odmowa aktywacji + NOT_TRAINED)")}
        # 2) technical artifact: the same synthetic rows marked REAL ONLY in a separate ledger of this temporary folder, so the trainer can
        #    produce a VALIDATED_SHADOW candidate and the READY inference path can be exercised (never a claim about real data)
        led2 = QuantLedger(ctx.data_dir / "smoke_quant_meta_tech" / "ledger.sqlite")
        _ledger_rows(led2, spec, 900, "REAL", 1, "tech")
        r2 = train_from_ledger(led2, INST, th, log=lambda m: None)[0]
        dt = time.monotonic() - t0
        tt = r2.get("test") or {}
        steps["train"] = check(r2.get("status") == "VALIDATED_SHADOW" and bool(r2.get("version")),
                               f"QuantService.train (train_from_ledger -> metamodel.train) na 900 wierszach SYNTHETIC: VALIDATION_FAILED "
                               f"{res.get('failed_gates')}, aktywacja odrzucona zgodnie z bramką ({gate_msg}), assess NOT_TRAINED; techniczny przebieg "
                               f"na tych samych wierszach oznaczonych REAL (tylko folder tymczasowy): {r2.get('status')} {r2.get('version')} "
                               f"(test: log loss {tt.get('log_loss', float('nan')):.3f} vs prior {tt.get('prior_log_loss', float('nan')):.3f}); {dt:.1f} s",
                               f"techniczny trening: {r2}")
        if steps["train"]["status"] != "OK":
            return steps
        ctx.step = "artifact"
        ver = r2["version"]
        model, man = M.load(INST, th, ver)                       # sha256 + schema + reproduction sample are checked by load()
        rep = (man.get("report") or {}).get("reproduction") or []
        diff = max((abs(M.predict(model, s["features"])["p_event"] - s["out"]["p_event"]) for s in rep), default=float("nan"))
        M.activate(INST, th, ver)
        act = M.pointer(INST).get("active", {}).get(th)
        steps["artifact"] = check(bool(rep) and diff <= 1e-12 and act == ver and q.validated_active(INST).get(th) == ver,
                                  f"model.json + manifest.json (sha256 OK, schemat {model['feature_schema'][:28]}…), odczyt -> predykcja próbki "
                                  f"reprodukcji ({len(rep)}): max różnica {diff:.1e}; ACTIVE.json -> {ver}",
                                  f"roundtrip: próbek {len(rep)}, różnica {diff}, aktywny {act} != {ver}")
        ctx.step = "predict"
        ev = EvaluationService(ConfigStore(), rt.bridge, Database(), data_dir=ctx.data_dir / "smoke_quant_meta_eval")
        ev.listeners.append(q.on_candidate)                       # runtime.py: evaluation.listeners.append(quant.on_candidate)
        ev.on_sh_cycle({"SCALPING": su}, inst=INST, symbol=su["symbol"], snap=None, now=su["created_at"])
        a = (q.recent or [{}])[0]
        prob = a.get("probability") or {}
        p = prob.get("p")
        ev_ = (a.get("ev") or {}).get("e_net_r")
        ptxt = f"{p:.4f}" if isinstance(p, float) else str(p)
        row = q.ledger.c.execute("SELECT data_kind FROM rows WHERE row_id=?", (str(a.get("row_id")),)).fetchone()
        good = (a.get("status") == "READY" and isinstance(p, float) and 0.0 <= p <= 1.0 and (a.get("model") or {}).get("version") == ver
                and row is not None and row[0] == "SYNTHETIC")
        steps["predict"] = check(good, f"EvaluationService -> QuantService.on_candidate -> assess: {a.get('status')} p={ptxt} "
                                       f"({prob.get('status')}, pokrycie cech {prob.get('coverage')}), E[net R]={ev_ if ev_ is None else round(ev_, 4)}, "
                                       f"would_hold={a.get('would_hold')!r}, influence {a.get('influence')}; "
                                       f"wiersz ledgera data_kind={row[0] if row else None}",
                                 f"assess: {a.get('status')} {a.get('reason')} p={p} (wersja {(a.get('model') or {}).get('version')}, oczekiwana {ver}); "
                                 f"wiersz ledgera {tuple(row) if row else None}; pętla: {q.loop.get('last_error')}")
        ctx.step = "contract"
        e = q.coordinator_entry("ACTIVE", cand=cd)
        errs = []
        if a.get("execution_allowed") is not False or a.get("mode") != "SHADOW" or a.get("influence") != "NONE":
            errs.append(f"SHADOW: execution_allowed={a.get('execution_allowed')}, mode={a.get('mode')}, influence={a.get('influence')}")
        if ev_ is not None and not math.isfinite(ev_):
            errs.append(f"E[net R] nieskończone: {ev_}")
        if (e or {}).get("family") != "quant:metamodel" or e.get("state") != "READY" or abs((e.get("result") or {}).get("p", -1) - (p or 0)) > 1e-12:
            errs.append(f"coordinator_entry: {e}")
        if (a.get("confidence") or {}).get("estimator_kind") != "tabicl_v2":
            errs.append(f"confidence.estimator_kind {(a.get('confidence') or {}).get('estimator_kind')}")
        steps["contract"] = check(not errs, f"ocena: status/p∈[0,1]/E[net R] skończone, execution_allowed False, SHADOW bez wpływu; coordinator_entry "
                                            f"(ASSIST) quant:metamodel READY z tym samym p; generacja {pub.get('generation')} "
                                            f"(complete={pub.get('complete')}). "
                                            f"Uwaga: probability.status 'CALIBRATED_VALIDATED' także przy kalibratorze {model['calibrator'].get('kind')}",
                                  "; ".join(errs))
        ev.ledger.c.close()
    finally:
        q.stop()
    return steps


# ---------------------------------------------------------------------------------------------------------------- quant:tabicl_v2
def _tabicl(ctx) -> dict:
    """TabICLService: env + weights (.venv_tabicl, checkpoint) -> real in-context predict; without them the bot's NOT_INSTALLED path."""
    from ...evaluation import contract as K
    from ...quant import events as EV
    from ...quant import tabicl as T
    from ...quant.service import QuantService
    ctx.step = "env"
    py = ctx.env_python(".venv_tabicl")
    inst = T.installed(max_age_s=0.0)
    steps: dict = {}
    if py is None:
        steps["env"] = unverified("brak .venv_tabicl (tabicl 2.2.0 + torch 2.14.1, instalator 41_AI_TABICL_TIREX_INSTALUJ.bat / MQ_TABICL_PYTHON); wagi "
                                  f"z huggingface.co niedostępne tutaj (403); verify: {'; '.join(inst.get('problems') or [])[:180]}")
    elif not inst.get("weights"):
        steps["env"] = unverified(f".venv_tabicl: {py}, ale brak wag TabICLv2: {'; '.join(inst.get('problems') or [])[:250]}")
    else:
        steps["env"] = ok(f".venv_tabicl: {py}; wagi zweryfikowane (sha256)")
    rt = _rt(ctx)
    q = QuantService(rt, data_dir=ctx.data_dir / "smoke_quant_tabicl")
    try:
        ctx.step = "contract"
        q.cycle()
        su = _sh_setup(rt.bridge, sid="SMOKE-TB-1")
        cd = K.from_sh_setup(su).validate().to_dict()
        spec = EV.spec_from_candidate(cd)
        if steps["env"]["status"] == "OK":
            # weights + environment present: the real in-context path (context from labelled ledger rows of this event, worker process)
            ctx.step = "predict"
            _ledger_rows(q.ledger, spec, 64, "SYNTHETIC", 7, "tb")
            a = q.assess(dict(cd, decision_ts=time.time()))
            job = q.tabicl.jobs.get_nowait()
            q.tabicl._score(job)
            r = q.tabicl.lookup(job["plan_hash"]) or {}
            pr = r.get("p_event_raw")
            steps["predict"] = check(r.get("state") == "READY" and isinstance(pr, float) and 0.0 <= pr <= 1.0,
                                     f"TabICLService._score (worker .venv_tabicl, kontekst {(r.get('context') or {}).get('n')} wierszy SYNTHETIC): READY "
                                     f"p_event_raw={pr}, UNCALIBRATED, {r.get('latency_ms')} ms",
                                     f"TabICL: {r.get('state')} {r.get('reason')} (assess {a.get('tabicl', {}).get('state')})")
            return steps
        # no environment / weights: the bot's own path without TabICL (never a value)
        a = q.assess(cd)
        tb, conf = a.get("tabicl") or {}, a.get("confidence") or {}
        job = q.tabicl.jobs.get_nowait()
        q.tabicl._score(job)
        r = q.tabicl.lookup(job["plan_hash"]) or {}
        st = q.tabicl.status()
        good = (tb.get("state") == "QUEUED" and conf.get("estimator_kind") == "tabicl_v2" and conf.get("confidence_score") is None
                and conf.get("influence") == "NONE" and r.get("state") == "NOT_INSTALLED" and r.get("p_event_raw") is None
                and not st["worker"]["running"] and r.get("plan_hash") == spec.plan_hash())
        steps["contract"] = check(good, f"ścieżka bez wag: assess -> TabICL {tb.get('state')} (confidence_score None, influence NONE), _score -> "
                                        f"{r.get('state')} ('{(r.get('reason') or '')[:60]}…'), worker nieuruchomiony, brak wartości ≠ 50 %",
                                  f"assess tabicl {tb.get('state')}, confidence {conf}, _score {r.get('state')} {r.get('reason')}, worker {st['worker']}")
        steps["predict"] = unverified("predict_proba TabICLv2 niesprawdzone: brak .venv_tabicl i checkpointu (huggingface.co 403) – sprawdzona tylko "
                                      "ścieżka NOT_INSTALLED (krok kontrakt)")
    finally:
        q.stop()
    return steps


SMOKES = {"analysis:evaluation": _evaluation, "quant:metamodel": _metamodel, "quant:tabicl_v2": _tabicl}
