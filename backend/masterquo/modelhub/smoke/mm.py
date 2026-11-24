"""Smoke checks of the PMW-MM area (master models, backend/masterquo/mm) for `models check --smoke`.

Real project paths only, on SYNTHETIC_TEST data (FakeMT5 of the smoke Ctx) in the temporary data folder:

* trained models (HDC, GPR, Event GRU, STE-FlowNet, Kalman parameter candidate, STFS) - the orchestrator jobs `mm/jobs.py:job_<id>` (the
  functions `python -m masterquo mm train` runs) on an in-memory SYNTHETIC_TEST snapshot with the quick profile cut to 1 epoch, then the
  artifact written by the job is read back (`mm/artifacts.load`) and its stored test metrics are recomputed from the loaded state;
* rules / measurements - the bot's SHADOW service `MMService.live` on a stub runtime (bridge rows of FakeMT5) and the Quant adapter
  `quant.adapters.mm` that turns its cache into PMW-PRED-2 records;
* Event GRU - the Quant adapter `quant.adapters.EventGRU().predict` on an artifact promoted ONLY in the temporary data folder.

Nothing here is a quality result: synthetic artifacts are TECHNICAL_TEST_ONLY by design.
"""
from __future__ import annotations

from . import check, fail, ok, skip

_SNAP_BARS = (("M1", 12000), ("M5", 3000), ("M15", 1200), ("M30", 800))       # orchestrator snapshot (quick profile caps: 24000 / 6000)
_LIVE_BARS = (("M1", 3000), ("M5", 600), ("M15", 300), ("M30", 200), ("H1", 200))   # bridge window of the stub runtime
_CACHE: dict[int, dict] = {}                                                   # per area process: orchestrator ctx, live view


def _cache(ctx) -> dict:
    return _CACHE.setdefault(id(ctx), {})


def _point(ctx) -> tuple[float, float]:
    f = ctx.fake()
    si = f.symbol_info(f.symbol)
    pt = float(getattr(si, "point", 0.01) or 0.01)
    return pt, float(getattr(si, "trade_tick_size", pt) or pt)


def _mm_bars(ctx, tf: str, n: int):
    """mm.data.Bars (UTC open times) of the same synthetic FakeMT5 series as ctx.bars."""
    from ...mm.data import Bars
    f = ctx.fake()
    r = ctx.rates(tf, n)
    return Bars(tf, r["time"] - float(f.offset), r["open"] * 1.0, r["high"] * 1.0, r["low"] * 1.0, r["close"] * 1.0, r["tick_volume"] * 1.0,
                r["spread"] * 1.0)


def _orch(ctx):
    """mm.orchestrator.Ctx on an in-memory SYNTHETIC_TEST snapshot (same object `mm train` builds from a dataset folder)."""
    c = _cache(ctx)
    if "oc" not in c:
        from ...mm import data as D
        from ...mm import orchestrator as O
        pt, tick = _point(ctx)
        bars = {tf: _mm_bars(ctx, tf, n) for tf, n in _SNAP_BARS}
        snap = D.Snapshot("SNAP-SMOKE-SYNTHETIC", "<pamięć: FakeMT5>", ctx.inst, ctx.fake().symbol, "SYNTHETIC_TEST", pt, tick,
                          {"source": "FakeMT5 (models check --smoke)"}, bars, {tf: D.quality(b) for tf, b in bars.items()}, {})
        oc = O.Ctx(ctx.inst, snap, ctx.data_dir / "mm_smoke_run", "quick", 20261025, None)
        oc.out.mkdir(parents=True, exist_ok=True)
        oc.prof = dict(oc.prof, epochs=1, buzoa_evals=40)
        c["oc"] = oc
    return c["oc"]


def _job(ctx, jid: str) -> dict:
    """One orchestrator job (mm/jobs.py job_<jid>) once per process; result as the orchestrator stores it (status SUCCEEDED by default)."""
    oc = _orch(ctx)
    if jid not in oc.results:
        from ...mm import jobs as J
        res = getattr(J, "job_" + jid)(oc)
        res.setdefault("status", "SUCCEEDED")
        oc.results[jid] = res
    return oc.results[jid]


def _job_bad(r: dict) -> str | None:
    return None if r.get("status") == "SUCCEEDED" else f"job {r.get('status')}: {r.get('reason')}"


def _bridge(ctx):
    from types import SimpleNamespace as NS
    rows = {tf: ctx.bars(tf, n) for tf, n in _LIVE_BARS}
    pt, tick = _point(ctx)

    def bars(tf, count=None, include_forming=True, limit=None):
        r = list(rows.get(tf, []))
        return r[-count:] if count else r
    return NS(synthetic=True, symbol_info={"point": pt, "trade_tick_size": tick}, tfs=dict.fromkeys(rows), bars=bars)


def _live(ctx):
    """MMService(rt).live(inst) on a stub runtime + quant.adapters.mm(rt, inst) -> (rt, live view, PMW-PRED-2 records). Once per process."""
    c = _cache(ctx)
    if "live" not in c:
        from types import SimpleNamespace as NS

        from ...mm.service import MMService
        from ...quant import adapters as QA
        cfg = NS(assets=NS(active=ctx.inst), mt5=NS(symbol=ctx.fake().symbol))
        rt = NS(bridge=_bridge(ctx), cfg=NS(get=lambda: cfg))
        rt.mm = MMService(rt)
        v = rt.mm.live(ctx.inst)
        c["live"] = (rt, v, QA.mm(rt, ctx.inst))
    return c["live"]


def _live_ok(ctx, key: str):
    _, v, _ = _live(ctx)
    if v.get("status") != "OK":
        return None, fail(f"MMService.live: {v.get('status')}: {v.get('reason')}")
    return v.get(key), None


def _rec(recs: list[dict], cid: str) -> dict | None:
    return next((r for r in recs if r.get("canonical_id") == cid), None)


def _contract(ctx, cid: str, note: str = "") -> dict:
    _, _, recs = _live(ctx)
    rec = _rec(recs, cid)
    if rec is None:
        return fail(f"quant.adapters.mm nie opublikował rekordu {cid}")
    if rec.get("state") != "READY":
        return fail(f"rekord {cid} w stanie {rec.get('state')}: {rec.get('unavailable_reason')}")
    st = ctx.contract_step([rec])
    if note and st["status"] == "OK":
        st = ok(f"{st['detail']} ({rec.get('task_type')} {rec.get('task')}, data_kind {rec.get('data_kind')}); {note}")
    return st


def _num(x) -> bool:
    import math
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _fmt(x, spec: str = ".3g") -> str:
    """Number for a detail text; anything else (None, str) as is - a failing value must never crash the detail formatting."""
    return format(x, spec) if _num(x) else str(x)


def _diff(a, b) -> float:
    """Max abs difference of two numbers / arrays; NaN at the same place counts as equal; shape mismatch -> inf."""
    import numpy as np
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.shape != b.shape:
        return float("inf")
    same_nan = np.isnan(a) & np.isnan(b)
    d = np.where(same_nan, 0.0, np.abs(a - b))
    return float(np.nanmax(np.where(np.isnan(d), np.inf, d))) if d.size else 0.0


def _metric_diff(stored: dict, fresh: dict) -> tuple[float, list[str]]:
    keys = [k for k in stored if _num(stored.get(k)) and _num(fresh.get(k))]
    return (max((abs(float(stored[k]) - float(fresh[k])) for k in keys), default=float("inf")), keys)


# ---------------------------------------------------------------------------------------------------------------- rules (MMService)
def _kalman_obs(ctx) -> dict:
    """D8 observation: the Quant path passes the RAW Kalman state (quant/adapters.py:191) and quant/features._dir_of reads *_CANDIDATE as a
    direction, the MM board takes the last ACCEPTED crossover (mm/service._kalman_direction). Measured on the live window; never a FAIL."""
    c = _cache(ctx)
    if "kobs" not in c:
        from ...mm import kalman as K
        from ...mm.service import _kalman_direction, _to_bars
        from ...quant.features import _dir_of
        rt, _, _ = _live(ctx)
        b5 = _to_bars(rt.bridge.bars("M5", include_forming=False), "M5")
        kc, rows = K.run(b5.t, b5.c, K.CrossConfig())
        sg = {"BULLISH": 1, "BEARISH": -1}

        def acc_dir(r):
            a = int(r.get("accepted") or 0)
            return 1 if a > 0 else -1 if a < 0 else 0
        cand = [r for r in rows if str(r.get("state", "")).endswith("_CANDIDATE")]
        c["kobs"] = {"state": kc.state, "accepted": kc.accepted, "board": sg.get(_kalman_direction(kc.state, kc.accepted) or "", 0),
                     "quant": _dir_of(kc.state), "n": len(rows), "cand": len(cand), "diff": sum(1 for r in cand if _dir_of(r["state"]) != acc_dir(r)),
                     "bull": _dir_of("BULLISH_CANDIDATE"), "bear": _dir_of("BEARISH_CANDIDATE")}
    return c["kobs"]


def _kalman_cross(ctx) -> dict:
    from ...mm import kalman as K
    ctx.step = "predict"
    k, bad = _live_ok(ctx, "kalman")
    if bad:
        return {"predict": bad}
    o = _kalman_obs(ctx)
    k_ref = K.steady_state_gain(1.0, 0.2)
    states = ("NEUTRAL", "INSUFFICIENT_HISTORY", "BULLISH_CONFIRMED", "BEARISH_CONFIRMED", "BULLISH_CANDIDATE", "BEARISH_CANDIDATE")
    good = k.get("state") in states and k.get("state") == o["state"] and _num(k.get("K_fast")) and abs(k["K_fast"] - k_ref) < 1e-3
    obs = (f"OBSERWACJA D8 (nie FAIL): Quant bierze surowy stan (quant/adapters.py:191), quant/features.py:34-40 _dir_of('BULLISH_CANDIDATE')="
           f"{o['bull']}, ('BEARISH_CANDIDATE')={o['bear']}; tablica MM – ostatnie zaakceptowane przecięcie. W oknie {o['n']} M5: {o['cand']} świec "
           f"*_CANDIDATE, w {o['diff']} cecha st:mm:kalman_cross:aligned ≠ kierunek tablicy")
    steps = {"predict": check(good, f"MMService.live: stan {k.get('state')}, accepted {o['accepted']}, K_fast {_fmt(k.get('K_fast'), '.3f')} "
                                    f"(ustalone {k_ref:.3f}), "
                                    f"zdarzeń {k.get('events_in_window')}. {obs}",
                              f"stan Kalmana niespójny: live {k.get('state')} vs K.run {o['state']}, K_fast {k.get('K_fast')} vs {k_ref:.3f}")}
    ctx.step = "contract"
    from ...quant.features import prediction_features
    rec = _rec(_live(ctx)[2], "mm:kalman_cross")
    feat = prediction_features([rec], "LONG").get("st:mm:kalman_cross:aligned") if rec else None
    steps["contract"] = _contract(ctx, "mm:kalman_cross", f"obserwacja D8: result.state={(rec or {}).get('result', {}).get('state')} -> cecha aligned(LONG)="
                                                          f"{feat}, kierunek tablicy {o['board']} (naprawa zmienia wejścia MetaModelu – decyzja D8)")
    return steps


def _breakout_zones(ctx) -> dict:
    ctx.step = "predict"
    b, bad = _live_ok(ctx, "breakout")
    if bad:
        return {"predict": bad}
    p = (b or {}).get("panel") or {}
    steps = {"predict": check(p.get("direction") in ("BULLISH", "BEARISH", "NONE"),
                              f"MMService.live: panel {p.get('direction')}, strefy kwalifikowane {len(b.get('zones') or [])}, "
                              f"ostatnie zdarzenia {len(b.get('last_events') or [])}, wolumen {b.get('volume_source')}",
                              f"panel wybicia bez kierunku: {p}")}
    ctx.step = "contract"
    steps["contract"] = _contract(ctx, "mm:breakout_zones")
    return steps


def _multi_indicator(ctx) -> dict:
    ctx.step = "predict"
    m, bad = _live_ok(ctx, "multi_indicator")
    if bad:
        return {"predict": bad}
    good = m.get("status") == "OK" and m.get("decision") in ("LONG", "SHORT", "NONE", None)
    steps = {"predict": check(good, f"MMService.live: decyzja {m.get('decision')}, status {m.get('status')}, powody LONG "
                                    f"{len(m.get('long_reasons') or [])} / SHORT {len(m.get('short_reasons') or [])}",
                              f"decyzja reguł: status {m.get('status')}, decyzja {m.get('decision')}")}
    ctx.step = "contract"
    steps["contract"] = _contract(ctx, "mm:multi_indicator")
    return steps


def _smc_fvg(ctx) -> dict:
    ctx.step = "predict"
    s, bad = _live_ok(ctx, "smc_fvg")
    if bad:
        return {"predict": bad}
    steps = {"predict": check(isinstance(s.get("trend"), str) and s.get("depth_min") is not None,
                              f"MMService.live: trend {s.get('trend')}, aktywne setupy {len(s.get('live_setups') or [])}, ostatnie zdarzenia "
                              f"{[e.get('kind') for e in (s.get('last_events') or [])]}, depth_min {s.get('depth_min')}", f"brak stanu SMC: {s}")}
    ctx.step = "contract"
    steps["contract"] = _contract(ctx, "mm:smc_fvg")
    return steps


def _align_mean(ctx) -> dict:
    ctx.step = "predict"
    a, bad = _live_ok(ctx, "align_mean")
    if bad:
        return {"predict": bad}
    ch = (a or {}).get("charts") or []
    okc = [x for x in ch if x.get("status") == "OK" and _num(x.get("dist_atr"))]
    steps = {"predict": check(len(okc) == len(_LIVE_BARS), f"MMService.live: {len(okc)}/{len(ch)} TF OK, dist_atr " +
                              ", ".join(f"{x['tf']} {_fmt(x['dist_atr'], '.2f')}" for x in okc) + f"; konfiguracja {a.get('config_key')}",
                              f"Align Mean: TF OK {len(okc)}/{len(ch)}: {[(x.get('tf'), x.get('status')) for x in ch]}")}
    ctx.step = "contract"
    steps["contract"] = _contract(ctx, "mm:align_mean")
    return steps


def _robust_vol(ctx) -> dict:
    ctx.step = "predict"
    r, bad = _live_ok(ctx, "robust_vol")
    if bad:
        return {"predict": bad}
    steps = {"predict": check(r.get("status") == "OK" and r.get("n") == 48,
                              f"MMService.live (RV.window_stat ostatnich 48 M5): dyspersja posortowana {_fmt(r.get('sorted_dispersion'))}, czasowa "
                              f"{_fmt(r.get('time_aware_dispersion'))}, path {_fmt(r.get('path'))}", f"robust_vol: {r}")}
    ctx.step = "contract"
    vals = [r.get(k) for k in ("sorted_dispersion", "time_aware_dispersion")]
    path_ok = (r.get("path_status") == "OK" and _num(r.get("path"))) or (r.get("path_status") == "DEGENERATE_RETURNS" and r.get("path") is None)
    good = all(_num(x) and x >= 0 for x in vals) and path_ok and isinstance(r.get("units"), dict)
    steps["contract"] = check(good, "własny słownik: dyspersje skończone i >= 0, path (statystyka ze znakiem) zgodna z path_status, jednostki opisane (brak "
                                    "rekordu Quant – wynik tylko w API /api/v1/mm/live i agencie)", f"robust_vol: wartości poza zakresem: {r}")
    return steps


def _fusion_board(ctx) -> dict:
    ctx.step = "predict"
    bd, bad = _live_ok(ctx, "board")
    if bad:
        return {"predict": bad}
    o = _kalman_obs(ctx)
    rd = {r.get("source"): r for r in bd.get("readings") or []}
    kdir = (rd.get("kalman") or {}).get("direction")
    exp_k = {1: "UP", -1: "DOWN"}.get(o["board"])
    dirs = [r.get("direction") for r in rd.values() if r.get("direction") in ("UP", "DOWN")]
    good = set(rd) <= {"kalman", "breakout_zones", "multi_indicator", "gpr"} and "kalman" in rd and kdir == exp_k \
        and bd["directional"]["UP"] == dirs.count("UP") and bd["directional"]["DOWN"] == dirs.count("DOWN")
    steps = {"predict": check(good, f"MMService.live: odczyty {sorted(rd)}, odrzucone {len(bd.get('rejected') or [])}, kierunki {bd.get('directional')}; "
                                    f"Kalman na tablicy {kdir} = ostatnie zaakceptowane przecięcie (poprawka 1.46)",
                              f"tablica: odczyty {sorted(rd)}, Kalman {kdir} (oczekiwane {exp_k}), kierunki {bd.get('directional')}")}
    ctx.step = "contract"
    keys = {"version", "symbol", "readings", "rejected", "directional", "independence", "rule", "execution_allowed"}
    steps["contract"] = check(keys <= set(bd) and bd.get("execution_allowed") is False and bd.get("symbol") == ctx.inst,
                              "własny słownik tablicy: wszystkie klucze, execution_allowed False, bez głosowania", f"tablica: brak kluczy {keys - set(bd)}")
    return steps


def _drift(ctx) -> dict:
    import numpy as np

    from ...mm import drift as DR
    ctx.step = "predict"
    g, bad = _live_ok(ctx, "gpr")
    if bad:
        return {"predict": bad}
    live_dr = ((g or {}).get("live_calibration") or {}).get("drift") or {}
    rng = np.random.default_rng(1)
    ref = rng.normal(0, 1, 2000)
    shifted = DR.evaluate(feature_ref={"x": (DR.reference_bins(ref), ref)}, feature_cur={"x": rng.normal(2, 1, 500)}, ref_abs_err=1.0, cur_abs_err=1.0,
                          ref_coverage=0.68, cur_coverage=0.40, artifact_created_at=None)
    same = DR.evaluate(feature_ref={"x": (DR.reference_bins(ref), ref)}, feature_cur={"x": rng.normal(0, 1, 500)}, ref_abs_err=1.0, cur_abs_err=1.0,
                       ref_coverage=0.68, cur_coverage=0.68, artifact_created_at=None)
    good = live_dr.get("action") in ("NONE", "SCHEDULE_CANDIDATE") and shifted["action"] == "SCHEDULE_CANDIDATE" and same["action"] == "NONE"
    steps = {"predict": check(good, f"na żywo (MMService._gpr): akcja {live_dr.get('action')}, {live_dr.get('measured_on')}"
                                    f"{'; ' + live_dr['note'] if live_dr.get('note') else ''}; DR.evaluate: przesunięty rozkład -> {shifted['action']} "
                                    f"{shifted['reasons']}, ten sam -> {same['action']}",
                              f"dryf: na żywo {live_dr.get('action')}, przesunięty {shifted['action']}, ten sam {same['action']}")}
    ctx.step = "contract"
    keys = {"version", "policy", "psi", "reasons", "action", "note"}
    steps["contract"] = check(keys <= set(live_dr) and keys <= set(shifted),
                              "własny słownik: klucze komplet, akcja tylko NONE/SCHEDULE_CANDIDATE (nigdy promocja)",
                              f"dryf: brak kluczy {keys - set(live_dr)}")
    return steps


# ---------------------------------------------------------------------------------------------------------------- GPR (job + live)
def _gpr_logret(ctx) -> dict:
    import math

    from ...mm import artifacts as AR
    from ...mm import gpr as G
    ctx.step = "train"
    r = _job(ctx, "gpr")
    if _job_bad(r):
        return {"train": fail(_job_bad(r))}
    cal = r.get("test_calibration_once") or {}
    steps = {"train": check(r.get("training_executed") and r.get("artifact_status") == "TECHNICAL_TEST_ONLY" and cal.get("n_scored", 0) > 0,
                            f"mm/jobs.py job_gpr (walk-forward, profil quick, M5 {len(_orch(ctx).bars('M5'))}): TEST n_scored {cal.get('n_scored')}, "
                            f"pokrycie 1σ {_fmt(cal.get('coverage_1sd'))}, bramki {r.get('gates')}; artefakt TECHNICAL_TEST_ONLY (syntetyka – bramka)",
                            f"job_gpr: status artefaktu {r.get('artifact_status')}, n_scored {cal.get('n_scored')}")}
    ctx.step = "artifact"
    st, man = AR.load(ctx.inst, "gpr_logret", r["artifact_id"])
    c = _orch(ctx).bars("M5").c
    x, base = math.log(c[-1] / c[-2]), float(c[-1])
    pj = G.GPModel.from_state(G.GPRConfig(), st).predict(x, base)
    m = G.GPModel(G.GPRConfig())
    m.refit(c, len(c) - 1, True)
    p0 = m.predict(x, base)
    aid2 = AR.save(ctx.inst, "gpr_logret", m.state(), {"status": "TECHNICAL_TEST_ONLY", "model_type": "GPR_MATERN32", "feature_schema": "GPR_LAG1_LOGRET",
                                                       "note": "smoke roundtrip (folder tymczasowy)"})
    st2, _ = AR.load(ctx.inst, "gpr_logret", aid2)
    p1 = G.GPModel.from_state(G.GPRConfig(), st2).predict(x, base)
    d = max(_diff(p0["mean_logret"], p1["mean_logret"]), _diff(p0["sd"], p1["sd"]))
    steps["artifact"] = check(man.get("status") == "TECHNICAL_TEST_ONLY" and pj.get("status") in ("OK", "DEGRADED") and d <= 1e-12,
                              f"artefakt jobu {r['artifact_id']} wczytany (sha256), GPModel.from_state -> {pj.get('status')}; roundtrip zapis/odczyt "
                              f"GPModel: różnica mean/sd {d:.1e}", f"GPR: manifest {man.get('status')}, predykcja z artefaktu {pj.get('status')}, różnica {d}")
    ctx.step = "predict"
    g, bad = _live_ok(ctx, "gpr")
    if bad:
        steps["predict"] = bad
        return steps
    good = g.get("status") in ("OK", "DEGRADED") and _num(g.get("mean_logret")) and _num(g.get("sd")) and g["sd"] > 0
    steps["predict"] = check(good, f"MMService.live: {g.get('status')} mean_logret {_fmt(g.get('mean_logret'), '.3e')} sd {_fmt(g.get('sd'), '.3e')} "
                                   f"h={g.get('horizon_bars')} "
                                   "(na żywo GP dopasowywany co świecę M5 – artefakt nieużywany, mm/service.py:190-199)", f"GPR na żywo: {g.get('status')}")
    ctx.step = "contract"
    steps["contract"] = _contract(ctx, "mm:gpr_logret")
    return steps


# ---------------------------------------------------------------------------------------------------------------- HDC
def _hdc_dir3(ctx) -> dict:
    import numpy as np

    from ...mm import artifacts as AR
    from ...mm import features as FE
    from ...mm import hdc as H
    from ...mm import jobs as J
    from ...mm import splits
    from ...mm.event_engine import metrics as cls_metrics
    ctx.step = "train"
    r = _job(ctx, "hdc")
    if _job_bad(r):
        return {"train": fail(_job_bad(r))}
    steps = {"train": check(r.get("training_executed") and r.get("artifact_status") == "TECHNICAL_TEST_ONLY" and r.get("online_equals_rebuild_bit_exact"),
                            f"mm/jobs.py job_hdc (D={_orch(ctx).prof['hdc_D']}): n {r.get('n')}, wybór {r.get('picked')}, online==rebuild bit-exact, "
                            "artefakt TECHNICAL_TEST_ONLY (syntetyka – bramka)", f"job_hdc: {r.get('artifact_status')}, online==rebuild "
                            f"{r.get('online_equals_rebuild_bit_exact')}")}
    ctx.step = "artifact"
    st, man = AR.load(ctx.inst, "hdc_dir3", r["artifact_id"])
    D_, seed, L, C = (int(x) for x in st["meta"])
    sp = H.Space(D_, seed=seed)
    enc = H.Encoder(sp, man["features"], levels=L)
    same_basis = bool(np.array_equal(sp.tie, st["tie"]) and np.array_equal(enc.roles, st["roles"]) and np.array_equal(enc.levels, st["levels"]))
    enc.lo, enc.hi = np.asarray(st["lo"], float), np.asarray(st["hi"], float)
    clf = H.Classifier(sp, C)
    clf.acc = np.asarray(st["acc"]).astype(np.int32)
    ds = FE.dataset(_orch(ctx).bars("M5"), J.HDC_FEATURES, 300, 12)
    ts = splits.chrono_split(ds["t_obs"], ds["t_end"], (0.6, 0.2, 0.2), embargo_s=12 * 300)["test"]
    pred = np.array([clf.predict(enc.record(ds["X"][i]))[0] for i in ts])
    fresh = cls_metrics(np.clip(np.eye(3)[pred], 1e-6, 1), ds["y"][ts])
    d, keys = _metric_diff((man.get("metrics") or {}).get("test_once") or {}, fresh)
    steps["artifact"] = check(same_basis and d <= 1e-9,
                              f"artefakt {r['artifact_id']} wczytany; ręczna rekonstrukcja Space/Encoder/Classifier (hdc.py nie ma from_state): bazy "
                              f"identyczne, metryki TEST z odczytu vs manifest ({len(keys)} pól) różnica {d:.1e}",
                              f"HDC roundtrip: bazy identyczne {same_basis}, różnica metryk TEST {d} (pola {keys})")
    ctx.step = "predict"
    _, v, _ = _live(ctx)
    steps["predict"] = skip("brak ścieżki predykcji na żywo (stan faktyczny): hdc.py bez from_state/loadera, quant/inventory.py:87 adapter=None, "
                            f"MMService tylko wypisuje wskaźnik: '{(v.get('trained_models') or {}).get('hdc_dir3')}' (mm/service.py:186-187); rejestr "
                            "deklaruje callers 'mm.service' (mm/inventory.py:26) i SHADOW_ONLY przy wskaźniku (sh/models.py:182-183) – rozjazd statusów")
    return steps


# ---------------------------------------------------------------------------------------------------------------- Event GRU (+ STFS)
def _event_engine_dir3(ctx) -> dict:
    import numpy as np

    from ...mm import artifacts as AR
    from ...mm import event_engine as EE
    from ...mm import events as EV
    from ...mm import jobs as J
    from ...mm import splits
    from ...quant import adapters as QA
    ctx.step = "train"
    r = _job(ctx, "event_engine")
    if _job_bad(r):
        return {"train": fail(_job_bad(r))}
    onl = r.get("online_offline_max_prob_diff")
    good = r.get("training_executed") and r.get("artifact_status") == "TECHNICAL_TEST_ONLY" and onl is not None and onl < 1e-6
    steps = {"train": check(good, f"mm/jobs.py job_event_engine (1 epoka, {r.get('event_source')}): jednostki {r.get('units')}, wybór {r.get('picked')}, "
                                  f"replay Runtime online vs offline max |ΔP| {_fmt(onl, '.1e')} ({r.get('online_units_compared')} jedn.), backend "
                                  f"{r.get('backend_used')}; artefakt TECHNICAL_TEST_ONLY (syntetyka – bramka)",
                            f"job_event_engine: status artefaktu {r.get('artifact_status')}, online vs offline {onl}")}
    ctx.step = "artifact"
    aid = r["artifact_id"]
    st, man = AR.load(ctx.inst, "event_engine_dir3", aid)
    m = EE.EventModel.from_state(st)
    sc = EV.Scaler()
    sc.med, sc.iqr = np.asarray(st["scaler_med"], float), np.asarray(st["scaler_iqr"], float)
    acc, fe, _, _ = J._events(_orch(ctx))
    u = EV.units(acc, fe, 16)
    tg = EV.unit_targets(u, 2)
    idx = np.where(tg["ok"])[0]
    ts = idx[splits.chrono_split(u["t_end"][idx], tg["t_label"][idx], (0.6, 0.2, 0.2), 0.0)["test"]]
    y = EV.classify(np.nan_to_num(tg["r"]), float(st["band"][0]))
    X = sc.transform(u["X"])
    fresh = EE.metrics(EE.predict(m, X[ts], u["segment"][ts]), y[ts])
    d, keys = _metric_diff((man.get("metrics") or {}).get("test_once") or {}, fresh)
    try:
        AR.promote_shadow(ctx.inst, "event_engine_dir3", aid, "smoke")
        gate = f"BŁĄD bramki: artefakt {man.get('status')} przesunął wskaźnik SHADOW (mm/artifacts.py promote_shadow)"
    except AR.ArtifactError as exc:
        gate = None if "NOT_VALIDATED" in str(exc) else f"nieoczekiwany błąd promocji: {exc}"
    steps["artifact"] = check(d <= 1e-9 and gate is None,
                              f"artefakt {aid} wczytany, EventModel.from_state + skaler: metryki TEST vs manifest ({len(keys)} pól) różnica {d:.1e}; "
                              "promote_shadow artefaktu TECHNICAL_TEST_ONLY odrzucone (NOT_VALIDATED) – odmowa zgodnie z bramką",
                              gate or f"Event GRU roundtrip: różnica metryk TEST {d} (pola {keys})")
    ctx.step = "predict"
    rt, _, _ = _live(ctx)
    p0 = QA.EventGRU().predict(rt, ctx.inst)
    if p0.get("state") != "NOT_TRAINED":
        steps["predict"] = fail(f"bez wskaźnika SHADOW oczekiwano NOT_TRAINED, jest {p0.get('state')}: {p0.get('unavailable_reason')}")
        return steps
    # technical artifact = the job's state re-saved with VALIDATED_SHADOW ONLY in the temporary data folder (no validation claimed)
    aid2 = AR.save(ctx.inst, "event_engine_dir3", st, {"status": "VALIDATED_SHADOW", "model_type": man.get("model_type"),
                                                       "feature_schema": man.get("feature_schema"),
                                                       "event_source": man.get("event_source"), "target": man.get("target"),
                                                       "note": "SMOKE: artefakt techniczny w folderze tymczasowym models check – NIE walidacja"})
    AR.promote_shadow(ctx.inst, "event_engine_dir3", aid2, "models check --smoke (folder tymczasowy)")
    p = QA.EventGRU().predict(rt, ctx.inst)
    res = p.get("result") or {}
    tot = sum(float(x) for x in res.values()) if res else float("nan")
    good = p.get("state") == "READY" and set(res) == {"DOWN", "FLAT", "UP"} and abs(tot - 1) < 1e-6 and p.get("model_version") == aid2
    steps["predict"] = check(good, f"quant.adapters.EventGRU: bez wskaźnika NOT_TRAINED (poprawnie); po promocji artefaktu technicznego (tylko folder "
                                   f"tymczasowy) {p.get('state')} " + ", ".join(f"{k} {_fmt(v, '.3f')}" for k, v in res.items()) +
                                   f", źródło {p.get('source')}, data_time {p.get('data_time')}",
                             f"EventGRU: {p.get('state')} {p.get('unavailable_reason')}, wynik {res}")
    ctx.step = "contract"
    steps["contract"] = ctx.contract_step([p]) if p.get("state") == "READY" else fail(f"brak rekordu READY: {p.get('state')}")
    return steps


def _stfs(ctx) -> dict:
    ctx.step = "train"
    ee = _job(ctx, "event_engine")
    if _job_bad(ee):
        return {"train": fail("zależność event_engine: " + _job_bad(ee))}
    r = _job(ctx, "stfs")
    if _job_bad(r):
        return {"train": fail(_job_bad(r))}
    cmp_ = r.get("comparison_val") or {}
    good = {"full", "full_stfs"} <= set(cmp_) and r.get("param_count_equal") is True and all(_num(cmp_[k].get("val_log_loss")) for k in ("full", "full_stfs"))
    return {"train": check(good, "job_event_engine (wariant full_stfs) + mm/jobs.py job_stfs: val log-loss full "
                                 f"{_fmt(cmp_.get('full', {}).get('val_log_loss'), '.4f')} "
                                 f"vs full_stfs {_fmt(cmp_.get('full_stfs', {}).get('val_log_loss'), '.4f')}, równa liczba parametrów, wybrany wariant "
                                 f"{ee.get('picked')}; STFS nie ma wyjścia inferencyjnego (mm/inventory.py:48) – predykcja przez mm:event_engine_dir3",
                           f"STFS: porównanie {sorted(cmp_)}, równa liczba parametrów {r.get('param_count_equal')}")}


# ---------------------------------------------------------------------------------------------------------------- STE-FlowNet
def _ste_flownet_ret(ctx) -> dict:
    import numpy as np

    from ...mm import artifacts as AR
    from ...mm import jobs as J
    from ...mm import splits
    from ...mm import ste_flownet as SF
    ctx.step = "train"
    r = _job(ctx, "ste_flownet")
    if _job_bad(r):
        return {"train": fail(_job_bad(r))}
    steps = {"train": check(r.get("training_executed") and r.get("artifact_status") == "TECHNICAL_TEST_ONLY",
                            f"mm/jobs.py job_ste_flownet (1 epoka, 5 wariantów, {r.get('event_source')}): próbki {r.get('samples')}, wybór {r.get('picked')}, "
                            f"bramki {r.get('gates')}; artefakt TECHNICAL_TEST_ONLY (syntetyka – bramka)", f"job_ste_flownet: {r.get('artifact_status')}")}
    ctx.step = "artifact"
    st, man = AR.load(ctx.inst, "ste_flownet_ret", r["artifact_id"])
    m = SF.STEModel.from_state(st)
    pick = man.get("pick")
    acc, fe, _, _ = J._events(_orch(ctx))
    smp = {w: SF.build_samples(acc, fe, 8, 16, 32, weighting=w) for w in (True, False)}       # the job builds both (mm/jobs.py:533,540)
    y = smp[True]["y"]
    okk = np.where(np.isfinite(y))[0]
    sp = splits.chrono_split(smp[True]["t_obs"][okk], smp[True]["t_label"][okk], (0.6, 0.2, 0.2), 0.0)
    tr, ts = okk[sp["train"]], okk[sp["test"]]
    mu, sd = np.asarray(st["x_mu"], float), np.asarray(st["x_sd"], float)
    weighted = man.get("sample_weighting", True) is not False                # 1.46 arch: stored with the picked variant (mm/jobs.py)
    Xp = smp[weighted]["X"]
    fresh = SF.reg_metrics(m.predict(((Xp - mu) / sd)[ts]), y[ts])
    d, keys = _metric_diff((man.get("metrics") or {}).get("test_once") or {}, fresh)
    # the stored normalisation must be the train statistics of the samples the PICKED variant was trained on
    Xw = smp[weighted]["X"][tr].reshape(-1, smp[weighted]["X"].shape[2])
    dn = max(_diff(mu, Xw.mean(0)), _diff(sd, Xw.std(0) + 1e-12))
    good = d <= 1e-9 and dn <= 1e-12 and (weighted == (pick != "no_temporal_weighting"))
    steps["artifact"] = check(good, f"artefakt {r['artifact_id']} wczytany, STEModel.from_state + x_mu/x_sd wariantu {pick} (ważenie {weighted}): "
                                    f"metryki TEST vs manifest ({len(keys)} pól) różnica {d:.1e}",
                              f"artefakt nie odtwarza wybranego wariantu {pick}: różnica metryk TEST {_fmt(d, '.1e')}, max |Δμ/Δσ| normalizacji {dn:.2e}, "
                              f"sample_weighting={man.get('sample_weighting')} (mm/jobs.py job_ste_flownet)")
    ctx.step = "predict"
    steps["predict"] = skip("brak ścieżki predykcji na żywo (stan faktyczny): quant/inventory.py:91 adapter=None ('tylko artefakt badawczy'), brak loadera "
                            "w kodzie aplikacji, mm/service.py:186-187 tylko wypisuje wskaźnik; sh/models.py:182-183 zgłosi SHADOW_ONLY 'obserwacja' przy "
                            "wskaźniku – rozjazd statusów rejestru; predykcja offline sprawdzona w kroku artefakt")
    return steps


# ---------------------------------------------------------------------------------------------------------------- Kalman parameters (BUZOA)
def _kalman_params(ctx) -> dict:
    from ...mm import artifacts as AR
    ctx.step = "train"
    r = _job(ctx, "kalman_calibration")
    if _job_bad(r):
        return {"train": fail(_job_bad(r))}
    good = r.get("training_executed") and r.get("artifact_status") == "TECHNICAL_TEST_ONLY" and r.get("applied_to_production") is False \
        and r.get("trials_total", 0) > 0 and r.get("picked") in ("buzoa", "random", "default")
    steps = {"train": check(good, f"mm/jobs.py job_kalman_calibration (BUZOA + random, {r.get('trials_total')} ocen): wybór {r.get('picked')} "
                                  f"{[round(x, 3) for x in r.get('picked_x') or []]}, TEST raz {_fmt(r.get('test_once'))}, koszt {r.get('cost_status')}; "
                                  "applied_to_production False", f"kalibracja Kalmana: {r.get('artifact_status')}, picked {r.get('picked')}")}
    ctx.step = "artifact"
    st, man = AR.load(ctx.inst, "kalman_params", r["artifact_id"])
    d = max(_diff(st["params"], r["picked_x"]), _diff((man.get("metrics") or {}).get("test_once", float("nan")), r.get("test_once", float("nan"))))
    steps["artifact"] = check(d == 0.0 and man.get("status") == "TECHNICAL_TEST_ONLY",
                              f"artefakt {r['artifact_id']} wczytany: parametry i wynik TEST identyczne (różnica {d:.1e}); brak konsumenta – serwis używa "
                              "K.CrossConfig() (mm/service.py:152), zgodnie z projektem", f"kalman_params roundtrip: różnica {d}, status {man.get('status')}")
    return steps


# ---------------------------------------------------------------------------------------------------------------- tools
def _tsvp(ctx) -> dict:
    ctx.step = "predict"
    r = _job(ctx, "tsvp")
    if _job_bad(r):
        return {"predict": fail(_job_bad(r))}
    s = r.get("proxy") or {}
    steps = {"predict": check(r.get("incremental_equals_rebuild") is True and s.get("buckets", 0) > 0,
                              f"mm/jobs.py job_tsvp ({r.get('source')}, {r.get('ticks')} ticków): inkrementalnie == rebuild, kubełki {s.get('buckets')}, "
                              f"POC {s.get('poc_price')}, {s.get('label')}; tryb wolumenu rzeczywistego: {r.get('actual_volume_mode')}",
                              f"TSVP: inkrementalnie==rebuild {r.get('incremental_equals_rebuild')}, kubełki {s.get('buckets')}")}
    ctx.step = "contract"
    keys = {"version", "source", "bucket_size", "buckets", "total", "poc_key", "poc_price", "status", "counted", "ignored", "session_ms"}
    good = keys <= set(s) and _num(s.get("poc_price")) and s.get("total", 0) > 0 and s.get("counted", 0) > 0
    steps["contract"] = check(good, f"własny słownik profilu: klucze komplet, POC skończony, policzone {s.get('counted')}, pominięte {s.get('ignored')}",
                              f"profil TSVP: brak kluczy {keys - set(s)} lub POC {s.get('poc_price')}")
    return steps


def _buzoa(ctx) -> dict:
    import numpy as np

    from ...mm import buzoa as BZ
    ctx.step = "predict"
    lb, ub = np.full(5, -5.12), np.full(5, 5.12)
    r = BZ.buzoa(BZ.rastrigin, lb, ub, BZ.BuzoaConfig(max_evals=500, seed=1))
    bx = np.asarray(r.get("best_x"), float)
    start = float(BZ.rastrigin(np.random.default_rng(1).uniform(lb, ub)))
    good = _num(r.get("best_f")) and r.get("evaluations", 10 ** 9) <= 500 and bx.shape == lb.shape and bool(np.all((bx >= lb) & (bx <= ub)))
    steps = {"predict": check(good and r["best_f"] < start, f"BZ.buzoa(rastrigin 5D, 500 ocen): best_f {_fmt(r.get('best_f'), '.3f')} "
                                                           f"(losowy punkt {start:.1f}), "
                                                           f"ocen {r.get('evaluations')}, best_x w granicach",
                              f"BUZOA: best_f {r.get('best_f')}, ocen {r.get('evaluations')}, best_x {bx}")}
    ctx.step = "contract"
    j = _job(ctx, "buzoa")
    b = j.get("benchmark") or {}
    res = b.get("results") or {}
    steps["contract"] = check(not _job_bad(j) and bool(res) and b.get("budget_evals") == _orch(ctx).prof["bench_budget"],
                              f"mm/jobs.py job_buzoa: benchmark {len(res)} zestawów (wymiary {b.get('dims')}, ziarna {b.get('seeds')}, budżet "
                              f"{b.get('budget_evals')}) – równy budżet algorytmów", f"benchmark BUZOA: {_job_bad(j) or b}")
    return steps


def _mathbench(ctx) -> dict:
    import hashlib
    from pathlib import Path
    ctx.step = "train"
    r = _job(ctx, "mathbench")
    if _job_bad(r):
        return {"train": fail(_job_bad(r))}
    man, chk = r.get("manifest") or {}, r.get("python_checks") or {}
    steps = {"train": check(bool(man.get("training")), f"mm/jobs.py job_mathbench: MLP 8-16-8-1 wytrenowany (wagi referencyjne, dane syntetyczne), "
                                                       f"wektory {man.get('n_vectors')}", "mathbench: brak informacji o treningu w manifeście")}
    ctx.step = "artifact"
    out = Path(r["files_dir"])
    sha_ok = all(hashlib.sha256((out / f).read_bytes()).hexdigest() == h for f, h in (man.get("files_sha256") or {}).items())
    steps["artifact"] = check(sha_ok and chk.get("reload_max_abs_diff") == 0.0 and chk.get("rows_read") == man.get("n_vectors"),
                              f"wagi CSV + wektory testowe + model.onnx: sha256 zgodne, odczyt wag -> max |Δ| {chk.get('reload_max_abs_diff')}; "
                              f"walidacja ONNX: {chk.get('onnx_checker')}", f"mathbench: sha256 {sha_ok}, reload {chk.get('reload_max_abs_diff')}")
    ctx.step = "predict"
    e32 = chk.get("float32_expected_max_abs_err")
    steps["predict"] = check(_num(e32) and e32 < 1e-4, f"forward float32 vs float64: max |Δ| {_fmt(e32, '.1e')}; onnxruntime: {chk.get('onnxruntime_python')} "
                                                       "(MQL5 EA – ręcznie w terminalu)", f"mathbench float32: {e32}")
    return steps


def _bat_encoder(ctx) -> dict:
    import numpy as np

    from ...mm.bat_encoder import BATEncoder
    ctx.step = "predict"
    bars = [{**b, "v": b.get("tv", 0)} for b in ctx.bars("H1", 600)]        # the same row mapping as GET /api/v1/models/bat/shadow
    enc = BATEncoder()
    r = enc.run(bars)
    a = r.get("actor") or {}
    steps = {"predict": check(r.get("status") == "SHADOW_UNTRAINED",
                              "BATEncoder.run (H1 600, jak api/wf32_routes.py:400-403): status SHADOW_UNTRAINED – wagi niewytrenowane, oznaczone zgodnie "
                              "z bramką; actor " + ", ".join(f"{k} {_fmt(v, '.3f')}" for k, v in a.items()) + f", critic {_fmt(r.get('critic_value'))}",
                              f"BAT: status {r.get('status')} (oczekiwano SHADOW_UNTRAINED)")}
    ctx.step = "contract"
    k = len(bars) - 50
    causal = r.get("status") == "SHADOW_UNTRAINED" and enc.run(bars, asof_index=k).get("actor") == BATEncoder().run(bars[:k + 1]).get("actor")
    vals = [float(x) for x in a.values()]
    good = set(a) == {"LONG", "FLAT", "SHORT"} and all(0 <= x <= 1 for x in vals) and abs(sum(vals) - 1) < 1e-9 and _num(r.get("critic_value")) \
        and str(r.get("execution", "")).startswith("NONE") and bool(np.all(np.isfinite(r.get("context") or [np.nan]))) and causal
    steps["contract"] = check(good, "własny słownik: actor LONG/FLAT/SHORT w [0,1] sumuje się do 1, critic skończony, execution NONE, asof_index nie czyta "
                                    "przyszłych świec (identyczny wynik z obciętą historią)",
                              f"BAT: actor {a}, critic {r.get('critic_value')}, przyczynowość {causal}")
    return steps


SMOKES = {
    "mm:align_mean": _align_mean,
    "mm:kalman_cross": _kalman_cross,
    "mm:breakout_zones": _breakout_zones,
    "mm:multi_indicator": _multi_indicator,
    "mm:smc_fvg": _smc_fvg,
    "mm:gpr_logret": _gpr_logret,
    "mm:hdc_dir3": _hdc_dir3,
    "mm:event_engine_dir3": _event_engine_dir3,
    "mm:ste_flownet_ret": _ste_flownet_ret,
    "mm:buzoa": _buzoa,
    "mm:stfs": _stfs,
    "mm:tsvp": _tsvp,
    "mm:mathbench": _mathbench,
    "mm:fusion_board": _fusion_board,
    "mm:kalman_params": _kalman_params,
    "mm:robust_vol": _robust_vol,
    "mm:drift": _drift,
    "mm:bat_encoder": _bat_encoder,
}
