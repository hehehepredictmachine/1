"""Smoke of the deterministic rules and measurements (area `rules`): no training and no artifact - every check calls the REAL rule
function on closed FakeMT5 bars (SYNTHETIC_TEST) and checks the type / range / state of its result; where the rule is published to
Quant Core (quant/adapters.py rules() / analysis()) the PMW-PRED-2 records of that adapter are validated with ctx.contract_step.

Shared inputs are computed once per area process and cached on the Ctx (bars per timeframe, the SH context snapshot, the indicator
service fed by a stub bridge that serves the FakeMT5 bars). A smoke result is a technical check of the path, never a quality result.
"""
from __future__ import annotations

import math
import time
from types import SimpleNamespace

from . import check

TICK = 0.01
DXY = "DXY_SYN"                     # extra symbol of FakeMT5 (linear transform of the gold series - synthetic, not a real relation)


# ---------------------------------------------------------------------------------------------------------------- helpers
def _cache(ctx) -> dict:
    c = getattr(ctx, "_rules_cache", None)
    if c is None:
        c = {}
        ctx._rules_cache = c
    return c


def _bars(ctx, tf: str, n: int) -> list[dict]:
    c = _cache(ctx)
    key = ("bars", tf, n)
    if key not in c:
        c[key] = ctx.bars(tf, n)
    return [dict(b) for b in c[key]]                    # a copy - a rule must never see the mutations of another check


def _sym_bars(ctx, symbol: str, tf: str, n: int) -> list[dict]:
    """Closed bars of another FakeMT5 symbol in the bridge row format (same conversion as Ctx.bars)."""
    from datetime import UTC, datetime
    c = _cache(ctx)
    key = ("sym", symbol, tf, n)
    if key not in c:
        f = ctx.fake()
        out = []
        for x in f.copy_rates_from_pos(symbol, getattr(f, "TIMEFRAME_" + tf), 1, n):
            t = int(x["time"]) - f.offset
            out.append({"open_utc": datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z"), "t": t, "o": float(x["open"]),
                        "h": float(x["high"]), "l": float(x["low"]), "c": float(x["close"]), "tv": int(x["tick_volume"]),
                        "spread": int(x["spread"]), "closed": True})
        c[key] = out
    return [dict(b) for b in c[key]]


def _quote(ctx, now: float) -> dict:
    f = ctx.fake()
    tk = f.symbol_info_tick(f.symbol)
    return {"bid": float(tk.bid), "ask": float(tk.ask), "time": now}


def _fin(*xs) -> bool:
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in xs)


def _r(x, n: int = 4):
    """Rounded number for a detail text (a non-number is shown as it is - a detail never raises)."""
    return round(x, n) if _fin(x) else x


def _judge(errs: list[str], detail: str) -> dict:
    return check(not errs, detail, "; ".join(errs))


def _recs(recs: list[dict], cid: str) -> list[dict]:
    return [r for r in recs if r.get("canonical_id") == cid]


def _sh(ctx) -> dict:
    """SH context snapshot exactly as sh/service.py:221 computes it (closed M1/M5/M15/H1 bars, fresh quote, tick 0.01)."""
    c = _cache(ctx)
    if "sh" not in c:
        from ...sh import context as CX
        bars = {tf: _bars(ctx, tf, 400) for tf in ("M1", "M5", "M15", "H1")}
        now = bars["M1"][-1]["t"] + 61
        snap = CX.snapshot(bars, _quote(ctx, now), tick=TICK, now=now, cfg={"max_spread_usd": 0.5}, cache={})
        c["sh"] = {"snap": snap, "bars": bars, "now": now}
    return c["sh"]


def _news(ctx):
    c = _cache(ctx)
    if "news" not in c:
        from ...config import ConfigStore
        from ...news.service import NewsService
        c["news"] = NewsService(ConfigStore(), None, None, None)       # no start(): no network, the report is set by the smoke
    return c["news"]


def _rule_recs(ctx, *, with_sh: bool = True, news=None) -> list[dict]:
    from ...quant import adapters as A
    rt = SimpleNamespace(sh=SimpleNamespace(snapshot=_sh(ctx)["snap"] if with_sh else None), news=news)
    return A.rules(rt, ctx.inst)


def _rule_contract(ctx, cid: str, extra=None) -> dict:
    """PMW-PRED-2 records of quant.adapters.rules for one SH rule: READY with the snapshot, BLOCKED_DATA (not a value) without it."""
    live = _recs(_rule_recs(ctx), cid)
    cold = _recs(_rule_recs(ctx, with_sh=False), cid)
    res = ctx.contract_step(live + cold)
    if res["status"] != "OK":
        return res
    errs = []
    if len(live) != 1 or live[0].get("state") != "READY":
        errs.append(f"z migawką SH oczekiwany 1 rekord READY, jest {[r.get('state') for r in live]}")
    if len(cold) != 1 or cold[0].get("state") != "BLOCKED_DATA" or cold[0].get("result") is not None:
        errs.append(f"bez migawki SH oczekiwany BLOCKED_DATA bez wyniku, jest {[(r.get('state'), r.get('result')) for r in cold]}")
    note = ""
    if not errs and extra is not None:
        e2, note = extra(live[0])
        errs += e2
    return _judge(errs, f"{res['detail']}; quant.adapters.rules: READY z migawką SH, BLOCKED_DATA bez niej{note}")


def _ind(ctx, stale: bool):
    """Real IndicatorService (PMW-IND-1) fed by a stub bridge serving FakeMT5 bars; DXY = FakeMT5 DXY_SYN. stale=True cuts the DXY feed
    100 h before as_of (the source stopped - the relation must be STALE)."""
    c = _cache(ctx)
    key = ("ind", stale)
    if key not in c:
        from ...config import ConfigStore
        from ...indicators.service import IndicatorService
        xau = {tf: _bars(ctx, tf, 600) for tf in ("M1", "M5")}
        xau["H1"] = _bars(ctx, "H1", 400)
        dxy = _sym_bars(ctx, DXY, "H1", 400)
        if stale:
            dxy = dxy[:-100]

        class Bridge:
            def __init__(self):
                self.quote, self.dxy_status, self.session_epoch = None, "OK", 1
                self.symbol_info = {"trade_tick_size": TICK, "digits": 2}

            def bars(self, tf, n=None, include_forming=False):
                rows = dxy if tf == "DXY_H1" else xau.get(tf, [])
                return rows[-n:] if n else rows

        cs = ConfigStore()
        cs.update({"mt5": {"dxy_symbol": DXY}, "indicators": {"book_enabled": False}})
        svc = IndicatorService(cs, Bridge(), data_dir=ctx.data_dir / ("ind_stale" if stale else "ind_fresh"))
        now = time.time()
        svc.refresh(now)
        c[key] = (svc, now)
    return c[key]


def _ind_recs(ctx, stale: bool) -> tuple[list[dict], dict, float]:
    from ...quant import adapters as A
    from ...quant import checks as CK
    svc, now = _ind(ctx, stale)
    recs = A.analysis(SimpleNamespace(indicators=svc), ctx.inst)
    return recs, CK.screen(recs, now=time.time()), now


# ---------------------------------------------------------------------------------------------------------------- SH rules
def _data_quality(ctx) -> dict:
    from ...quant import snapshot as QS
    from ...sh import context as CX
    ctx.step = "predict"
    m1, m5 = _bars(ctx, "M1", 300), _bars(ctx, "M5", 300)
    now = m1[-1]["t"] + 61
    good = CX.data_quality({"M1": m1, "M5": m5}, _quote(ctx, now), now,
                           {"max_bar_age_s": {"M1": 180, "M5": 600}, "max_quote_age_s": 10.0, "max_spread_usd": 0.5})
    bad = CX.data_quality({"M1": m1}, None, now + 999, {"max_bar_age_s": {}, "max_quote_age_s": 10.0})
    qc = QS.qc(QS.normalise(m5, "M5"), "M5")
    errs = []
    if good["status"] != "OK" or good["issues"] or not _fin(good["spread"], good["quote_age_s"]):
        errs.append(f"świeże zamknięte świece + świeże notowanie: {good['status']} {good['issues']} (sh/context.py:35)")
    if bad["status"] != "BLOCK" or "brak notowania Bid/Ask" not in bad["issues"] or not any("nieaktualne" in i for i in bad["issues"]):
        errs.append(f"stare świece bez notowania nie dały BLOCK z powodami: {bad}")
    if qc.get("status") != "OK" or qc.get("gap_count"):
        errs.append(f"quant/snapshot.py qc M5: {qc.get('status')} {qc.get('issues')}")
    steps = {"predict": _judge(errs, f"SH data_quality: świeże OK (wiek M1 {good['bar_age_s'].get('M1')} s, spread {_r(good['spread'], 2)}); "
                                     f"stare + brak notowania → BLOCK ({'; '.join(bad['issues'])}); quant qc M5 {qc['status']} bez luk")}
    ctx.step = "contract"

    def extra(rec):
        st = (rec.get("result") or {}).get("status")
        return ([] if st == _sh(ctx)["snap"]["data"]["status"] else [f"wynik rekordu {st} ≠ migawka SH"]), f"; status w rekordzie {st}"
    steps["contract"] = _rule_contract(ctx, "rule:data_quality", extra)
    return steps


def _risk_engine(ctx) -> dict:
    from ...risk import portfolio as PF
    from ...sh import config as C
    from ...sh import risk as RK
    from ...sh.units import SymbolSpec
    ctx.step = "predict"
    cfg = C.load()
    prof = C.profile(cfg, "XAUUSD", "SCALPING")
    spec = SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 100, 2, "USD", source="TEST")
    now = time.time()
    q = _quote(ctx, now)
    su = {"strategy": "SCALPING", "side": "BUY", "status": "READY", "valid_until": now + 300, "entry_ref": q["ask"], "sl": q["ask"] - 3.0,
          "signal_id": "SH-SMOKE-1", "costs": {"round_trip_price": 0.2}}
    st = {"open_plans": [], "daily_realized_money": 0, "last_close_at": {}, "recent_signals": [], "foreign_positions": 0}
    acc = {"equity": 10000, "margin": 0, "margin_mode": "HEDGING", "margin_per_lot": 500}
    r = RK.evaluate(setup=su, spec=spec, prof=prof, cfg=cfg, inst="XAUUSD", account=acc, state=st, exec_mode="PAPER", now=now,
                    quote={"age_s": 0.5, "spread": q["ask"] - q["bid"]})
    b = RK.evaluate(setup=su, spec=spec, prof=prof, cfg=cfg, inst="XAUUSD", account={"equity": 10000}, state=dict(st, daily_realized_money=-10**6),
                    exec_mode="PAPER", now=now, quote={"age_s": 99, "spread": 9})
    lim = SimpleNamespace(daily_loss_limit_pct=2.0, max_open_positions=3)
    p_bad = PF.check({"realized_today": -1000.0, "open_positions": 3}, equity=10000, legacy_limits=lim, sh_limits={})
    p_ok = PF.check({"realized_today": 0.0, "open_positions": 0}, equity=10000, legacy_limits=lim, sh_limits={})
    errs = []
    legs = r.get("legs") or []
    if r["status"] != "PASS" or not _fin(r["volume"]) or r["volume"] <= 0 or abs(sum(legs) - r["volume"]) > 1e-9:
        errs.append(f"poprawny setup: {r['status']} {r.get('reasons')} wolumen {r['volume']} nogi {legs} (sh/risk.py:16)")
    if any(abs(x / spec.volume_step - round(x / spec.volume_step)) > 1e-6 for x in legs):
        errs.append(f"nogi poza krokiem wolumenu {spec.volume_step}: {legs}")
    want = ("quote_fresh", "spread", "daily_loss")
    if b["status"] != "BLOCK" or not all(any(x.startswith(w) for x in b.get("reasons") or []) for w in want):
        errs.append(f"stare notowanie / szeroki spread / limit dzienny nie dały BLOCK z {want}: {b['status']} {b.get('reasons')}")
    if set(p_bad) != {"PORTFOLIO_DAILY_LOSS_LIMIT", "PORTFOLIO_MAX_OPEN_POSITIONS"} or p_ok:
        errs.append(f"risk/portfolio.py:61 check: przekroczone {p_bad}, w normie {p_ok}")
    return {"predict": _judge(errs, f"sh/risk evaluate: PASS wolumen {r['volume']} nogi {legs}; BLOCK {len(b.get('reasons') or [])} powody "
                                    f"({', '.join(x.split(':')[0] for x in b.get('reasons') or [])}); portfolio.check {p_bad} / w normie []")}


def _news_rule(ctx) -> dict:
    from ...engine import decision as D
    from ...timeutil import iso, utcnow
    ctx.step = "predict"
    n = _news(ctx)
    n.report = None
    m0 = n.macro()
    n.report = {"as_of": iso(utcnow()), "status": "PARTIAL",
                "calendar": {"status": "PARTIAL", "risk": {"level": "HIGH", "events": [{"name": "NFP (syntetyczny)"}]}}}
    m = n.macro()
    cs = n.cfg_store.get()
    dq = {"analysis_allowed": True, "entries_allowed": True, "reason_codes": [], "market_state": "OPEN", "data_quality": "GOOD"}
    d = D.build(snapshot_id="S-SMOKE", as_of=iso(utcnow()), symbol="XAUUSD-", account_key=None, session_epoch=1, dq=dq,
                legacy={"m02": {"structural_direction": "BULLISH"}}, setup=None, levels=None, risk=None, agent_gate={"status": "NOT_REQUIRED"},
                mode_gate={"allowed": False, "mode": "SIGNALS", "reason_codes": []}, macro=m, strategy_cfg=cs.strategy, risk_cfg=cs.risk,
                dxy_status="OK", synthetic=True)
    node = next((x for x in d["decision_tree"] if x["node"] == "MARKET"), None)
    errs = []
    if m0["status"] != "NOT_LOADED" or m0["risk_level"] != "UNKNOWN":
        errs.append(f"bez raportu: {m0['status']} / {m0['risk_level']} (news/service.py:100)")
    if m["status"] != "PARTIAL" or m["risk_level"] != "HIGH":
        errs.append(f"raport z wydarzeniem HIGH: {m['status']} / {m['risk_level']}")
    if not node or node["status"] != "FAIL" or "MACRO_EVENT_WINDOW" not in (node.get("reason_codes") or []):
        errs.append(f"węzeł MARKET drzewa decyzji nie zablokował okna wydarzenia HIGH: {node}")
    steps = {"predict": _judge(errs, f"news.macro: bez raportu NOT_LOADED/UNKNOWN; z syntetycznym NFP PARTIAL/HIGH; engine.decision MARKET "
                                     f"{node and node['status']} {node and node.get('reason_codes')}")}
    ctx.step = "contract"
    live = _recs(_rule_recs(ctx, news=n), "rule:news")
    n.report = None
    unloaded = _recs(_rule_recs(ctx, news=n), "rule:news")
    cold = _recs(_rule_recs(ctx, with_sh=False, news=n), "rule:news")
    res = ctx.contract_step(live + unloaded)
    if res["status"] != "OK":
        steps["contract"] = res
        return steps
    errs = []
    keys = set(n.summary())
    if live and live[0].get("state") == "READY" and not {"blackout", "next_event_in_s"} & set(live[0].get("result") or {}):
        miss = sorted({"blackout", "next_event_in_s"} - keys)
        errs.append(f"NEWS_BLACKOUT READY bez blackoutu: wynik {live[0].get('result')}; quant/adapters.py:101 czyta {miss} - brak w "
                    "NewsService.summary() (news/service.py:132-137)")
    if unloaded and unloaded[0].get("state") == "READY":
        errs.append(f"kalendarz NOT_LOADED jako READY {unloaded[0].get('result')} (adapters.py:100-102 state='READY' stałe; adapters.py:6)")
    if not cold:
        errs.append("bez migawki SH rekord rule:news znika (adapters.py:76-80 return przed :96)")
    steps["contract"] = _judge(errs, f"{res['detail']}; rule:news niesie blackout, NOT_LOADED nie jest READY, rekord obecny bez migawki SH")
    return steps


def _regime_v2(ctx) -> dict:
    from ...lab import market_v2 as MV
    from ...sh import context as CX
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 400)
    r = CX._regime(m5, TICK, {})
    cache: dict = {}
    CX._regime(m5[:-20], TICK, cache)
    inc = CX._regime(m5, TICK, cache)                                  # live path: cached machine fed the 20 newer bars one by one
    rep = MV.regime_series(m5, "M5", TICK, tf_s=300)["current"]["state"]
    allowed = ("TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION")
    errs = []
    if r.get("status") != "OK" or r.get("state") not in allowed:
        errs.append(f"stan reżimu {r} poza {allowed} (sh/context.py:132)")
    if r.get("strength") is not None and not (_fin(r["strength"]) and 0 <= r["strength"] <= 100):
        errs.append(f"siła {r.get('strength')} poza 0..100")
    if inc.get("state") != r.get("state") or rep != r.get("state"):
        errs.append(f"rozjazd na żywo/odtworzenie: świeży {r.get('state')}, przyrostowy {inc.get('state')}, market_v2.regime_series {rep}")
    steps = {"predict": _judge(errs, f"MQ_REGIME_MULTI_V2 M5: {r.get('state')} (siła {r.get('strength')}, zmienność {r.get('volatility')}); "
                                     "przyrostowy = świeży = regime_series")}
    ctx.step = "contract"

    def extra(rec):
        from ...quant import features as F
        st = (rec.get("result") or {}).get("state")
        fx = F.context_features({"market_regime": {"state": st}})
        oh = {k: v for k, v in fx.items() if k.startswith("ctx:regime=")}
        note = f"; stan w rekordzie {st}"
        if oh and not any(oh.values()):
            note += (f"; UWAGA (cecha MetaModel, nie FAIL - zmiana wejść modelu): stan {st} nie pasuje do REGIMES quant/features.py:22 "
                     f"→ ctx:regime=* same zera (features.py:74-77)")
        return ([] if st == _sh(ctx)["snap"]["regime"].get("state") else [f"stan rekordu {st} ≠ migawka SH"]), note
    steps["contract"] = _rule_contract(ctx, "rule:regime_v2", extra)
    return steps


def _structure_v2(ctx) -> dict:
    from ...analysis import structure_v2 as S
    from ...sh import context as CX
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 400)
    r = S.analyse([b["open_utc"] for b in m5], [b["h"] for b in m5], [b["l"] for b in m5], [b["c"] for b in m5], tick=TICK)
    per = {tf: CX._structure(_bars(ctx, tf, 400), TICK) for tf in ("M5", "M15", "H1")}
    errs = []
    lay = r.get("layers") or {}
    if not all(isinstance((lay.get(k) or {}).get("trend"), str) and lay[k]["trend"] for k in ("internal", "major")):
        errs.append(f"warstwy internal/major bez trendu: { {k: (v or {}).get('trend') for k, v in lay.items()} } (analysis/structure_v2.py:147)")
    ev = r.get("events") or []
    if any(not (0 <= e.get("bar_index", -1) < len(m5)) for e in ev) or [e["bar_index"] for e in ev] != sorted(e["bar_index"] for e in ev):
        errs.append("zdarzenia BOS/CHOCH poza zakresem świec lub nieuporządkowane")
    for tf, s in per.items():
        if s.get("status") != "OK" or not all(_fin(x) for x in (s.get("highs") or []) + (s.get("lows") or [])):
            errs.append(f"{tf}: {s.get('status')} {s.get('reason')}")
    steps = {"predict": _judge(errs, f"structure_v2 M5 internal {lay.get('internal', {}).get('trend')} / major {lay.get('major', {}).get('trend')}, "
                                     f"{len(ev)} zdarzeń; SH _structure: " + ", ".join(f"{tf} {s.get('internal')}" for tf, s in per.items()))}
    ctx.step = "contract"

    def extra(rec):
        res = rec.get("result") or {}
        return ([] if set(res) == {"M5", "M15", "H1"} else [f"wynik rekordu ma TF {sorted(res)}"]), f"; TF w rekordzie {sorted(res)}"
    steps["contract"] = _rule_contract(ctx, "rule:structure_v2", extra)
    return steps


def _atr_vol(ctx) -> dict:
    import itertools

    from ...sh import context as CX
    ctx.step = "predict"
    sh = _sh(ctx)
    m5 = sh["bars"]["M5"]
    tr = [max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"])) for a, b in itertools.pairwise(m5)]
    w = sum(tr[:14]) / 14
    for x in tr[14:]:
        w = (w * 13 + x) / 14                                         # independent Wilder(14)
    v = sh["snap"]["vol"]
    errs = []
    if v.get("status") != "OK" or not _fin(v.get("atr_m1"), v.get("atr_m5")) or v["atr_m1"] <= 0 or v["atr_m5"] <= 0:
        errs.append(f"vol {v} (sh/context.py:217-218)")
    elif abs(v["atr_m5"] - w) > 1e-9 * max(1.0, w):
        errs.append(f"ATR M5 {v['atr_m5']} ≠ niezależny Wilder(14) {w} (sh/context.py:22)")
    if CX._atr(m5[:10]) is not None:
        errs.append("ATR z 10 świec (< 15) nie jest None")
    steps = {"predict": _judge(errs, f"ATR Wilder14: M1 {_r(v.get('atr_m1'))}, M5 {_r(v.get('atr_m5'))} (= niezależne przeliczenie); "
                                     "<15 świec → None")}
    ctx.step = "contract"

    def extra(rec):
        from ...evaluation import contract as K
        from ...quant import features as F
        res = rec.get("result") or {}
        now = sh["now"]
        q = sh["snap"]["price"] or {}
        su = {"strategy": "SCALPING", "side": "BUY", "status": "READY", "created_at": now, "entry_ref": q.get("ask"), "sl": q.get("ask", 0) - 3,
              "tps": [{"name": "TP1", "price": q.get("ask", 0) + 2, "share": 1.0}], "horizon_minutes": 30, "costs": {}}
        has = "ctx:risk_atr" in F.build(K.from_sh_setup(su, regime=sh["snap"]["regime"]).to_dict(), [])
        note = f"; atr_m5 w rekordzie {res.get('atr_m5')}"
        if not has:
            note += ("; UWAGA (cecha MetaModel, nie FAIL - zmiana wejść modelu): kandydat SH (evaluation.contract.from_sh_setup) nie niesie "
                     "atr_m5 → ctx:risk_atr brak (quant/features.py:61-63)")
        return ([] if res.get("atr_m5") == v.get("atr_m5") else [f"atr_m5 rekordu {res.get('atr_m5')} ≠ migawka"]), note
    steps["contract"] = _rule_contract(ctx, "rule:atr_vol", extra)
    return steps


def _smc_pullback(ctx) -> dict:
    from ...lab.context_ind import smc as SM
    from ...sh import context as CX
    ctx.step = "predict"
    m1, m5 = _bars(ctx, "M1", 300), _bars(ctx, "M5", 400)
    s = SM.run(m5, 300, tick=TICK)
    last_close = m5[-1]["t"] + 300
    pb = s.pb.ledger
    c5, c1 = CX._ctx_m5(m5, TICK), CX._ctx_m1(m1, TICK)
    errs = []
    if s.trend not in ("UP", "DOWN", "NONE"):
        errs.append(f"trend SMC {s.trend} (lab/context_ind/smc.py:289)")
    if not pb:
        errs.append("pusta księga pullbacków na 400 świecach M5")
    # a swing is known at the close of its confirming bar (never before the bar it comes from, never after the last closed bar)
    bad = [x for x in pb if x["side"] not in ("H", "L") or x["confirming_bar"] < x["origin_bar"] or not _fin(x["price"])
           or abs(x["available_at"] - (m5[x["confirming_bar"]]["t"] + 300)) > 1e-6 or x["available_at"] > last_close + 1e-6]
    if bad:
        errs.append(f"{len(bad)} swingów z look-ahead / złą stroną, np. {bad[0]}")
    for k in ("smc_trend_m5", "pb_last_low_m5", "pb_last_high_m5", "vamd_m5", "fd_zone_m5"):
        if k not in c5:
            errs.append(f"brak {k} w SH _ctx_m5")
    if "smc_trend_m1" not in c1:
        errs.append("brak smc_trend_m1 w SH _ctx_m1")
    return {"predict": _judge(errs, f"SMC M5 trend {s.trend}, {len(pb)} swingów pullback (znane na zamknięciu świecy potwierdzenia); "
                                    f"SH ctx_m5 {c5.get('status')}, trend M1 {c1.get('smc_trend_m1')}")}


def _vamd(ctx) -> dict:
    from ...lab.context_ind import vamd as VM
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 300)
    s = VM.series(m5)
    rd = [x for x in s if x.get("status") == "READY"]
    errs = []
    if len(s) != len(m5):
        errs.append(f"{len(s)} wyników dla {len(m5)} świec (lab/context_ind/vamd.py:101)")
    if not rd:
        errs.append("brak wyników READY na 300 świecach M5")
    elif not all(_fin(x["y"], x["atr"]) and x["atr"] > 0 and x["sign"] in (-1, 0, 1) for x in rd):
        errs.append("READY z nieskończoną wartością / ATR ≤ 0 / znakiem poza -1,0,1")
    return {"predict": _judge(errs, f"VAMD M5: {len(rd)}/{len(s)} READY, ostatnie y {_r(rd[-1]['y'], 3)} znak {rd[-1]['sign']}" if rd else "")}


def _fractal(ctx) -> dict:
    from ...lab.context_ind import fractal as FD
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 200)
    z = [x for x in FD.series(m5) if x.get("zone")]
    k = FD.katz([b["c"] for b in m5[-30:]])
    errs = []
    if not z:
        errs.append("brak stref FD na 200 świecach M5 (lab/context_ind/fractal.py:82)")
    elif not all(_fin(x["fd_smooth"]) and 1.0 - 1e-9 <= x["fd_smooth"] <= 2.0 + 1e-9 for x in z if x.get("fd_smooth") is not None):
        errs.append("wymiar fraktalny poza [1, 2]")
    fd = k.get("fd_bounded") if isinstance(k, dict) else None
    if not isinstance(k, dict) or k.get("status") != "READY" or not (_fin(fd) and 1.0 - 1e-9 <= fd <= 2.0 + 1e-9):
        errs.append(f"katz() na 30 zamknięciach: {k} (lab/context_ind/fractal.py:25)")
    return {"predict": _judge(errs, f"Katz FD M5: {len(z)} punktów ze strefą, ostatnia {z[-1]['zone']} fd {_r(z[-1]['fd_smooth'], 3)}; katz(30) {_r(fd, 3)}"
                                    if z else "")}


def _candles_patterns(ctx) -> dict:
    from ...analysis import candles as CN
    from ...analysis import chart_patterns as CH
    from ...analysis import sci2
    ctx.step = "predict"
    m1 = _bars(ctx, "M1", 120)
    rd = sci2.read([x["open_utc"] for x in m1], [x["o"] for x in m1], [x["h"] for x in m1], [x["l"] for x in m1], [x["c"] for x in m1], "M1", tick=TICK)
    v = _view(ctx)
    c = CN.scan(v.tfs["M5"], "M5", lookback=20)
    h = CH.scan(v.tfs["M15"], "M15")
    errs = []
    if not isinstance(rd.get("role"), str) or not rd["role"]:
        errs.append(f"sci2.read bez roli świecy: {rd.get('role')} (analysis/sci2.py:39)")
    pats = c.get("patterns")
    if not isinstance(pats, list) or any(not isinstance(p, dict) for p in pats):
        errs.append(f"candles.scan: {type(pats).__name__}")
    if h.get("status") != "OK" or not isinstance(h.get("patterns"), list):
        errs.append(f"chart_patterns.scan M15: {h.get('status')}")
    return {"predict": _judge(errs, f"sci2 M1 rola {rd.get('role')}; świece M5 {len(pats or [])} wzorców; formacje M15 {h.get('status')} "
                                    f"{len(h.get('patterns') or [])}")}


def _view(ctx):
    c = _cache(ctx)
    if "view" not in c:
        from ...strategies import adapter
        bars = {tf: _bars(ctx, tf, 400) for tf in ("M1", "M5", "M15", "H1")}
        c["view"] = adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=None, ask=None, point=TICK, as_of=bars["M1"][-1]["open_utc"],
                                       synthetic=True)
    return c["view"]


def _liquidity(ctx) -> dict:
    from ...analytics import liquidity_context as LC
    from ...analytics import session_engine as SE
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 600)
    bx = SE.build(m5, 300, "SCALP_OPENING_V1", "XAUUSD", m5[-1]["t"] + 300, days=2)
    r = LC.evaluate(boxes=bx, heatmap=None, price=m5[-1]["c"], atr_m5=1.5)
    n0 = LC.evaluate(boxes=[], heatmap=None, price=None, atr_m5=None)
    codes = [x.get("code") for x in r.get("reason_codes") or []]
    errs = []
    if r.get("mode") != "OBSERVE" or not codes or not all(isinstance(x, str) for x in codes):
        errs.append(f"liquidity_context.evaluate: tryb {r.get('mode')}, kody {codes} (analytics/liquidity_context.py:41)")
    if n0.get("mode") != "OBSERVE":
        errs.append(f"bez pudełek sesji: tryb {n0.get('mode')}")
    return {"predict": _judge(errs, f"kontekst płynności (OBSERVE, bez wpływu na wejścia): {len(bx)} pudełek sesji, kody {sorted(set(codes))[:5]}")}


def _flow_sr(ctx) -> dict:
    from ...lab.flow_context import heikin
    from ...lab.flow_context import sr_channels as SR
    from ...lab.flow_context import stop_distance as SD
    ctx.step = "predict"
    m1, m15 = _bars(ctx, "M1", 300), _bars(ctx, "M15", 400)
    h = heikin.heikin_series(m15)
    c = SR.channels_at(m15, len(m15) - 1)
    px = m15[-1]["c"]
    nr = SR.nearest(c, px)
    sd = SD.series(m1)[-1]
    errs = []
    if len(h.get("rows") or []) != len(m15):
        errs.append(f"heikin_series: {len(h.get('rows') or [])} wierszy dla {len(m15)} świec (lab/flow_context/heikin.py:88)")
    chs = c.get("channels") or []
    if any(not (_fin(x["lo"], x["hi"]) and x["lo"] <= x["hi"]) for x in chs):
        errs.append("kanał S/R z lo > hi")
    if (nr.get("support") and not nr["support"]["hi"] < px) or (nr.get("resistance") and not nr["resistance"]["lo"] > px):
        errs.append(f"nearest(): wsparcie/opór po złej stronie ceny {px}: {nr}")
    if sd.get("status") != "OK" or not _fin(sd.get("suggested_price_distance")) or sd["suggested_price_distance"] <= 0:
        errs.append(f"stop_distance M1: {sd}")
    return {"predict": _judge(errs, f"Heikin M15 {len(h['rows'])} wierszy; {len(chs)} kanałów S/R; dystans stopu M1 "
                                    f"{_r(sd.get('suggested_price_distance'), 3)}")}


def _decomposition(ctx) -> dict:
    from ...analytics import signal as SG
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 600)
    x = SG.fft_analysis(m5, "M5")
    e = SG.emd_analysis(m5, "M5")
    dom = ((x.get("values") or {}).get("dominant") or [])
    errs = []
    if x.get("status") != "ready" or not dom:
        errs.append(f"fft_analysis: {x.get('status')} {x.get('reason')} (analytics/signal.py:95)")
    elif not all(_fin(d["period_bars"], d["power_share"]) and d["period_bars"] >= 2 and 0 <= d["power_share"] <= 1 for d in dom):
        errs.append(f"dominanty FFT poza zakresem: {dom[:2]}")
    if e.get("status") not in ("ready", "unavailable", "insufficient_data"):
        errs.append(f"emd_analysis: {e.get('status')} {e.get('reason')} (analytics/signal.py:193)")
    return {"predict": _judge(errs, f"FFT {x.get('status')}: okres dominujący {dom[0]['period_bars'] if dom else None} świec, udział "
                                    f"{dom[0]['power_share'] if dom else None}; EMD {e.get('status')} {e.get('reason') or ''}")}


# ---------------------------------------------------------------------------------------------------------------- analysis:*
def _zones(ctx) -> dict:
    from ...config import ConfigStore
    from ...quant import adapters as A
    from ...zones import features as ZF
    from ...zones.service import ZoneService
    ctx.step = "predict"
    b = {"M5": _bars(ctx, "M5", 600), "M15": _bars(ctx, "M15", 400), "H1": _bars(ctx, "H1", 300), "D1": _bars(ctx, "D1", 40)}

    class Bridge:
        def __init__(self):
            self.symbol_info = {"trade_tick_size": TICK, "digits": 2}

        def symbol_bars(self, symbol, tf, n):
            return b[tf][-n:]

        def bars(self, tf, n=None, include_forming=False):
            return b.get(tf, [])

    svc = ZoneService(ConfigStore(), Bridge(), data_dir=ctx.data_dir / "zones")
    zm = svc.refresh(b["M5"][-1]["t"] + 300)
    px = b["M5"][-1]["c"]
    ft = ZF.compute(zm, direction="LONG", entry=px, stop=px - 3, cost_price=0.2)
    errs = []
    if (zm.get("data") or {}).get("state") != "OK" or not zm.get("zones"):
        errs.append(f"mapa stref: {(zm.get('data') or {}).get('state')} {len(zm.get('zones') or [])} stref (zones/engine.py:19)")
    bad = [z for z in zm.get("zones") or [] if not (_fin(z.get("lower_price"), z.get("upper_price")) and z["lower_price"] <= z["upper_price"])]
    if bad:
        errs.append(f"{len(bad)} stref z lower > upper / bez cen")
    if not isinstance(ft, dict) or not ft:
        errs.append(f"zones.features.compute: {ft}")
    steps = {"predict": _judge(errs, f"ZoneService.refresh: {zm['data']['state']}, {len(zm['zones'])} stref; najbliższe wsparcie "
                                     f"{(zm['summary'].get('nearest_support') or {}).get('zone_type')}; {len(ft)} cech planu LONG")}
    ctx.step = "contract"
    recs = A.analysis(SimpleNamespace(zones=svc), ctx.inst)
    z = _recs(recs, "analysis:zones")
    res = ctx.contract_step(z)
    if res["status"] == "OK":
        res = check(len(z) == 1 and z[0]["state"] == "READY", f"{res['detail']}; analysis:zones READY ({len(z[0].get('result') or {})} pól podsumowania)",
                    f"analysis:zones: {[(r['state'], r.get('unavailable_reason')) for r in z]}")
    steps["contract"] = res
    return steps


def _market_zones(ctx) -> dict:
    from ...zones import market as MZ
    from ...zones.series import Series
    ctx.step = "predict"
    bars = {"M5": _bars(ctx, "M5", 600), "M15": _bars(ctx, "M15", 400)}           # market zones exist for M1..M30 (zones/market.py:67)
    as_of = bars["M15"][-1]["t"] + 900
    ser = {tf: Series.from_bars(b, tf, as_of) for tf, b in bars.items()}
    r = MZ.compute(ser, instrument="XAUUSD", symbol="XAUUSD-", tick=TICK, as_of=as_of, spreads={tf: MZ.spread_price(b, TICK) for tf, b in bars.items()})
    errs = []
    n = 0
    for tf, x in r["timeframes"].items():
        if x.get("state") != "OK":
            errs.append(f"{tf}: {x.get('state')} (zones/market.py:436)")
            continue
        zs = x.get("zones") or []
        n += len(zs)
        ids = {z["id"] for z in zs}
        if not set(x.get("visible") or []) <= ids:
            errs.append(f"{tf}: widoczne id spoza listy stref")
        for z in zs:
            sc = (z.get("quality") or {}).get("score")
            if not (_fin(z["lower"], z["upper"]) and z["lower"] <= z["upper"]) or not (_fin(sc) and 0 <= sc <= 100) or z.get("probability") is not None:
                errs.append(f"{tf}: strefa {z.get('id')} lower/upper/jakość/prawdopodobieństwo poza kontraktem")
                break
    return {"predict": _judge(errs, f"strefy rynkowe M5+M15: {n} stref, typy {sorted({z['type'] for x in r['timeframes'].values() for z in x['zones']})[:5]}; "
                                    "jakość 0..100, prawdopodobieństwo None")}


def _indicators(ctx) -> dict:
    from ...quant import features as F
    ctx.step = "predict"
    svc, _ = _ind(ctx, False)
    s = svc.current()
    cp = svc.compact(s)
    errs = []
    for k in ("avwap", "semivar", "spread", "dxy", "profile", "microstructure"):
        if k not in s:
            errs.append(f"migawka PMW-IND-1 bez {k} (indicators/service.py:215)")
    if cp.get("snapshot_status") != "READY":
        errs.append(f"świeża migawka oznaczona {cp.get('snapshot_status')}")
    av = (s.get("avwap") or {}).get("M1", {}).get("SESSION") or {}
    if av.get("status") == "READY" and not _fin((av.get("values") or {}).get("avwap")):
        errs.append("AVWAP M1 SESSION READY bez wartości")
    sts = {k: (cp.get(k) or {}).get("status") for k in ("semivar", "spread", "dxy", "profile", "microstructure")}
    steps = {"predict": _judge(errs, f"IndicatorService.refresh na świecach FakeMT5: migawka {cp.get('snapshot_status')}, statusy {sts}, "
                                     f"AVWAP M1 SESSION {av.get('status')}")}
    ctx.step = "contract"
    recs, scr, _ = _ind_recs(ctx, False)
    r = _recs(recs, "analysis:indicators")
    res = ctx.contract_step(r)
    if res["status"] == "OK":
        feats = [k for k in F.prediction_features(scr["eligible"], "LONG") if "analysis:indicators" in k]
        el = [p["canonical_id"] for p in scr["eligible"]]
        res = check(len(r) == 1 and r[0]["state"] == "READY" and "analysis:indicators" in el,
                    f"{res['detail']}; analysis:indicators READY i dopuszczony w quant.checks.screen; cech MetaModel z rekordu: {len(feats)} "
                    "(rola CONTEXT_FEATURE bez cech - quant/features.py:86-111)",
                    f"analysis:indicators: {[(x['state'], x.get('unavailable_reason')) for x in r]}, dopuszczone {el}")
    steps["contract"] = res
    return steps


def _svp(ctx) -> dict:
    from ...svp import engine as SVP
    from ...svp import zones as SZ
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 600)
    p = SVP.compute(m5, "M5", m5[-288]["t"], m5[-1]["t"] + 300, as_of=m5[-1]["t"] + 300, tick=TICK, bin_ticks=10, instrument="XAUUSD", mode="RANGE")
    z = SZ.algorithmic(p)
    lo, hi = min(b["l"] for b in m5[-288:]), max(b["h"] for b in m5[-288:])
    errs = []
    if p.get("status") != "READY" or not _fin(p.get("poc"), p.get("val"), p.get("vah")):
        errs.append(f"svp.compute: {p.get('status')} {p.get('reason')} (svp/engine.py:83)")
    elif not (p["val"] <= p["poc"] <= p["vah"] and lo - 1 <= p["val"] and p["vah"] <= hi + 1):
        errs.append(f"VAL {p['val']} ≤ POC {p['poc']} ≤ VAH {p['vah']} w zakresie [{lo:.2f}, {hi:.2f}] - niespełnione")
    if not isinstance(z, list):
        errs.append(f"svp.zones.algorithmic: {type(z).__name__}")
    return {"predict": _judge(errs, f"SVP M5 (288 świec): POC {p.get('poc')}, VA [{p.get('val')}, {p.get('vah')}], źródło {p.get('volume_source')}; "
                                    f"{len(z) if isinstance(z, list) else '?'} stref algorytmicznych")}


def _dxy(ctx) -> dict:
    from ...indicators import dxy as DX
    from ...quant import features as F
    ctx.step = "predict"
    h1, dx = _bars(ctx, "H1", 400), _sym_bars(ctx, DXY, "H1", 400)
    now = h1[-1]["t"] + 3600 + 30
    kw = {"as_of": now, "instrument": "XAUUSD", "broker_symbol": "XAUUSD-", "dxy_symbol": DXY}
    r = DX.compute(h1, dx, **kw)
    s = DX.compute(h1, dx[:-100], **kw)
    d = DX.compute(h1, dx, as_of=now, instrument="XAUUSD", broker_symbol="XAUUSD-", dxy_symbol=None)
    fc, fs = DX.feature_context(r), DX.feature_context(s)
    errs = []
    if r.get("status") != "READY" or not _fin(fc.get("corr_72"), fc.get("beta_72")) or not -1 - 1e-9 <= fc["corr_72"] <= 1 + 1e-9:
        errs.append(f"świeży DXY: {r.get('status')} {r.get('reason')} corr_72 {fc.get('corr_72')} (indicators/dxy.py:97)")
    if s.get("status") != "STALE" or fs.get("status") != "STALE":
        errs.append(f"DXY zatrzymany 100 h przed as_of: relacja {s.get('status')}, kontekst ML {fs.get('status')} (oczekiwane STALE)")
    if d.get("status") != "DISABLED":
        errs.append(f"bez symbolu DXY: {d.get('status')}")
    steps = {"predict": _judge(errs, f"relacja XAU-DXY H1: świeża {r.get('status')} corr_72 {_r(fc.get('corr_72'))} beta_72 {_r(fc.get('beta_72'), 3)} "
                                     f"(DXY_SYN syntetyczny); zatrzymany feed → {s.get('status')} ({s.get('reason')}), kontekst ML {fs.get('status')}; "
                                     "brak symbolu → DISABLED" if not errs else "")}
    ctx.step = "contract"
    recs_f, scr_f, _ = _ind_recs(ctx, False)
    recs_s, scr_s, _ = _ind_recs(ctx, True)
    rf, rs = _recs(recs_f, "analysis:dxy_correlation"), _recs(recs_s, "analysis:dxy_correlation")
    res = ctx.contract_step(rf + rs)
    if res["status"] != "OK":
        steps["contract"] = res
        return steps
    ff = {k[8:]: round(v, 3) for k, v in F.prediction_features(scr_f["eligible"], "LONG").items() if k.startswith("ctx:dxy_")}
    fst = {k[8:]: round(v, 3) for k, v in F.prediction_features(scr_s["eligible"], "LONG").items() if k.startswith("ctx:dxy_")}
    inner = (rs[0].get("result") or {}).get("status") if rs else None
    errs = []
    if len(rf) != 1 or rf[0]["state"] != "READY" or not ff:
        errs.append(f"świeży DXY: rekord {[x['state'] for x in rf]}, cechy {ff} (quant/adapters.py:123-127)")
    if len(rs) != 1 or inner != "STALE":
        errs.append(f"nieaktualny DXY: rekord {[x['state'] for x in rs]}, status wewnętrzny {inner}")
    elig = "analysis:dxy_correlation" in [p["canonical_id"] for p in scr_s["eligible"]]
    # D9 (owner decision): a STALE relation still feeding MetaModel features is reported, not failed - the fix changes model inputs
    note = (f"OBSERWACJA D9 (nie FAIL - poprawka zmienia wejścia MetaModel): DXY {inner} → rekord {rs[0]['state'] if rs else None}, screen "
            f"eligible={elig}, cechy ctx:dxy_ {fst} (quant/adapters.py:123-126 READY gdy compact['dxy'] niepusty; quant/features.py:108-111 "
            "bez statusu)") if fst else "nieaktualna relacja DXY nie daje cech ctx:dxy_* (D9 rozwiązane)"
    steps["contract"] = _judge(errs, f"{note}; świeży READY → cechy ctx:dxy_ {sorted(ff)}; {res['detail']}")
    return steps


def _walls(ctx) -> dict:
    from datetime import UTC, datetime

    from ...analysis import walls as W
    from ...config import AppConfig
    ctx.step = "predict"
    d = _bars(ctx, "D1", 40)
    d[-1]["closed"] = False
    s = W.build(symbol="XAUUSD-", d1_bars=d, cfg=AppConfig().walls, iv_obs=None, manual=None, now=datetime.now(UTC))
    ws = s.get("walls") or []
    up = sorted((w["k"], w["level"]) for w in ws if w["side"] == "UPPER")
    lo = sorted((w["k"], w["level"]) for w in ws if w["side"] == "LOWER")
    errs = []
    if s.get("status") != "OK" or not up or not lo:
        errs.append(f"walls.build: {s.get('status')} {s.get('reason')} ściany {len(ws)} (analysis/walls.py:91)")
    elif not (min(x[1] for x in up) > max(x[1] for x in lo) and [x[1] for x in up] == sorted(x[1] for x in up)
              and [x[1] for x in lo] == sorted((x[1] for x in lo), reverse=True)):
        errs.append(f"ściany nieuporządkowane: górne {up}, dolne {lo}")
    return {"predict": _judge(errs, f"ściany zmienności D1 ({s.get('source_type')}): górne {[round(x[1], 2) for x in up][:3]}, dolne "
                                    f"{[round(x[1], 2) for x in lo][:3]} - rosnące z k")}


def _strategies_regime(ctx) -> dict:
    ctx.step = "predict"
    from ...strategies import regime as SR
    v = _view(ctx)
    rg = v.regime or {}
    per = {tf: (r or {}).get("state") for tf, r in (rg.get("per_tf") or {}).items()}
    errs = []
    if rg.get("state") not in SR.STATES:
        errs.append(f"stan MQ-REGIME {rg.get('state')} poza STATES (strategies/regime.py:33,82)")
    if set(per) != {"M1", "M5", "M15", "H1"} or not all(s in SR.STATES for s in per.values()):
        errs.append(f"stany per TF: {per}")
    return {"predict": _judge(errs, f"MarketRegimeEngine: {rg.get('state')}, per TF {per}, konflikty {rg.get('conflicts')}")}


def _signals(ctx) -> dict:
    from ...analysis import levels as LV
    from ...analysis import mitp
    from ...analysis import neutralization as NZ
    from ...analysis import range_m5 as RG
    ctx.step = "predict"
    v = _view(ctx)
    m5 = _bars(ctx, "M5", 400)
    r = RG.detect(v.tfs["M5"])
    lz = LV.zones_for_tf(v.tfs["H1"], "H1")
    h, lo, c = [b["h"] for b in m5], [b["l"] for b in m5], [b["c"] for b in m5]
    mt = mitp.series(h, lo, c)
    nz = NZ.factors(h, lo, c)
    errs = []
    if r.get("status") not in ("OK", "NO_RANGE"):                       # BRAK_DANYCH = 400 bars M5 judged too short
        errs.append(f"range_m5.detect: {r.get('status')} (analysis/range_m5.py:59)")
    if lz.get("status") != "OK":
        errs.append(f"levels.zones_for_tf H1: {lz.get('status')} (analysis/levels.py:74)")
    if not isinstance(mt, dict) or not mt or any(len(x) != len(c) for x in mt.values() if isinstance(x, list)):
        errs.append(f"mitp.series: {sorted(mt)[:5] if isinstance(mt, dict) else mt}")
    if not isinstance(nz, dict) or not nz:
        errs.append(f"neutralization.factors: {nz}")
    return {"predict": _judge(errs, f"range_m5 {r.get('status')}; poziomy H1 {lz.get('status')}; mitp {len(mt)} serii; neutralizacja {sorted(nz)}")}


def _session_engine(ctx) -> dict:
    from ...analytics import session_engine as SE
    from ...quant.checks import ts as _ts
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 600)
    as_of = m5[-1]["t"] + 300
    bx = SE.build(m5, 300, "SCALP_OPENING_V1", "XAUUSD", as_of, days=2)
    fin = [b for b in bx if b["state"] == "FINAL"]
    errs = []
    if not bx or any(b["session"] not in ("ASIA", "LONDON", "NEW_YORK") for b in bx):
        errs.append(f"sesje: {[b['session'] for b in bx]} (analytics/session_engine.py:93)")
    if not fin:
        errs.append(f"brak zamkniętej sesji w 2 dniach: {[b['state'] for b in bx]}")
    bad = [b for b in fin if not (_fin(b.get("final_high"), b.get("final_low")) and b["final_high"] >= b["final_low"])]
    if bad:
        errs.append(f"{len(bad)} sesji FINAL bez poprawnego high/low, np. {bad[0]['session']} {bad[0].get('final_high')} {bad[0].get('final_low')}")
    late = [b for b in bx if b.get("known_at") and _ts(b["known_at"]) > as_of + 1e-6]
    if late:
        errs.append(f"{len(late)} pudełek znanych po as_of (look-ahead)")
    return {"predict": _judge(errs, f"{len(bx)} pudełek sesji, FINAL {len(fin)}, stany {sorted({b['state'] for b in bx})}; known_at ≤ as_of")}


def _volzones(ctx) -> dict:
    from ...config import AppConfig
    from ...engine import volzones
    ctx.step = "predict"
    d = _bars(ctx, "D1", 40)
    d[-1]["closed"] = False
    r = volzones.compute(d, AppConfig().volatility)
    errs = []
    if r.get("status") != "OK" or not _fin(r.get("expected_high"), r.get("expected_low"), r.get("hv_annual_pct")):
        errs.append(f"volzones.compute: {r.get('status')} {r.get('reason')} (engine/volzones.py:94)")
    elif not (r["expected_high"] > r["expected_low"] and r["hv_annual_pct"] > 0):
        errs.append(f"oczekiwany zakres [{r['expected_low']}, {r['expected_high']}], HV {r['hv_annual_pct']}")
    return {"predict": _judge(errs, f"strefy zmienności ({r.get('source_type')}): zakres dnia [{r.get('expected_low')}, {r.get('expected_high')}], "
                                    f"HV roczna {r.get('hv_annual_pct')} %")}


def _market_trap(ctx) -> dict:
    from ...apollo import traps
    ctx.step = "predict"
    m5 = _bars(ctx, "M5", 300)
    a = traps.detect(m5)
    b = traps.detect(m5, spread_points=40, spread_baseline=12)
    errs = []
    for name, x in (("OHLC", a), ("OHLC+spread", b)):
        sc = x.get("market_trap_score")
        if not (_fin(sc) and 0 <= sc <= 100) or not 0 <= x.get("confidence", -1) <= 1 or x.get("recommendation") not in ("NONE", "WAIT"):
            errs.append(f"{name}: wynik {sc}, pokrycie {x.get('confidence')}, rekomendacja {x.get('recommendation')} (apollo/traps.py:50)")
    if a.get("confidence", 1) >= 0.3 or b.get("confidence", 0) < 0.3 or (b.get("components") or {}).get("EXECUTION_STRESS", {}).get("score") is None:
        errs.append(f"pokrycie: same OHLC {a.get('confidence')} (oczekiwane < 0,3), ze spreadem {b.get('confidence')} (≥ 0,3)")
    return {"predict": _judge(errs, f"market trap: OHLC wynik {a.get('market_trap_score')} pokrycie {a.get('confidence')} → {a.get('recommendation')}; "
                                    f"ze skokiem spreadu {b.get('market_trap_score')} pokrycie {b.get('confidence')} → {b.get('recommendation')}")}


def _sfb(ctx) -> dict:
    from collections import Counter

    from ...baskets import catalog as CAT
    from ...baskets import sfb
    ctx.step = "predict"
    prof = "FOREX_MT5"
    strats = [s for s in CAT.CATALOG if s["profile_id"] == prof]
    scope = {"profile": prof, "venue": CAT.PROFILES[prof]["venue"], "environment": "LIVE_DATA", "product": CAT.PROFILES[prof]["products"][0],
             "instrument": "EURUSD"}
    out = {m: sfb.StrategyFilterBucket({"mode": m}).filter(strats, scope) for m in ("OFF", "SHADOW", "ASSIST")}
    sn = out["ASSIST"][1] or {}
    comp = [s for s in strats if (sn.get("items") or {}).get(s["strategy_id"], {}).get("compatibility_status") == "COMPATIBLE"
            and s["kind"] != "HEDGING"]
    errs = []
    if out["OFF"][0] != strats or out["OFF"][1] is not None:
        errs.append("OFF zmienia listę lub tworzy migawkę (baskets/sfb.py:215)")
    if out["SHADOW"][0] != strats or not out["SHADOW"][1]:
        errs.append("SHADOW zmienia listę lub nie tworzy migawki")
    keep = set(sn.get("would_keep") or []) | set(sn.get("hedging_passthrough") or [])
    if {s["strategy_id"] for s in out["ASSIST"][0]} != keep or sn.get("evidence_source") != "NOT_CONNECTED" or sn.get("would_keep"):
        errs.append(f"ASSIST bez źródła wyników: zostawione {len(out['ASSIST'][0])}, would_keep {sn.get('would_keep')}, źródło {sn.get('evidence_source')}")
    el = None
    if comp:                                                         # synthetic TASK 014 outcomes with the exact lineage -> ELIGIBLE reachable
        s0 = comp[0]
        now = time.time()
        rows = [{"strategy_id": s0["strategy_id"], "version": s0["version"], "config_hash": s0["config_hash"], "net_R": 0.4 + 0.2 * math.sin(i),
                 "closed_ts": now - 3600 - i * 6 * 3600, "event_group_id": f"E{i}", "regime": ("TREND", "RANGE")[i % 2], "cost_complete": True,
                 "source": "SYNTHETIC_TEST"} for i in range(160)]
        bk = sfb.StrategyFilterBucket({"mode": "ASSIST"}, outcomes_fn=lambda sc: rows)
        kept, sn2 = bk.filter(strats, scope)
        el = sn2["items"][s0["strategy_id"]]
        if el["eligibility_status"] != "ELIGIBLE" or s0["strategy_id"] not in {s["strategy_id"] for s in kept} or sn2.get("bucket_status") != "ACTIVE":
            errs.append(f"syntetyczne wyniki z pełną linią: {el['eligibility_status']} {el.get('reason_codes')} (baskets/sfb.py:117)")
    else:
        errs.append("brak zgodnej strategii niehedgingowej w profilu FOREX_MT5")
    cnt = Counter(v["eligibility_status"] for v in (sn.get("items") or {}).values())
    return {"predict": _judge(errs, f"SFB {len(strats)} strategii: OFF/SHADOW bez zmian, ASSIST bez źródła → {len(out['ASSIST'][0])} "
                                    f"(hedging passthrough), statusy {dict(cnt)}; z syntetycznymi wynikami (160 zdarzeń) → "
                                    f"{el and el['eligibility_status']}")}


SMOKES = {
    "rule:data_quality": _data_quality,
    "rule:risk_engine": _risk_engine,
    "rule:news": _news_rule,
    "rule:regime_v2": _regime_v2,
    "rule:structure_v2": _structure_v2,
    "rule:smc_pullback": _smc_pullback,
    "rule:vamd": _vamd,
    "rule:fractal": _fractal,
    "rule:atr_vol": _atr_vol,
    "rule:candles_patterns": _candles_patterns,
    "rule:liquidity": _liquidity,
    "rule:flow_sr": _flow_sr,
    "rule:decomposition": _decomposition,
    "analysis:zones": _zones,
    "analysis:market_zones": _market_zones,
    "analysis:indicators": _indicators,
    "analysis:svp": _svp,
    "analysis:dxy_correlation": _dxy,
    "analysis:walls": _walls,
    "strategies:regime": _strategies_regime,
    "analysis:signals": _signals,
    "analytics:session_engine": _session_engine,
    "engine:volzones": _volzones,
    "apollo:market_trap": _market_trap,
    "baskets:sfb": _sfb,
}
