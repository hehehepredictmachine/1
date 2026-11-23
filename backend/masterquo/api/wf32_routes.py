"""Apollo23 workflow v3.2 routes (TASK 001-025). Every new module is read-only / OFF / SHADOW by default; none of these routes can send,
modify or close an order or change risk / STOP / execution mode."""
from __future__ import annotations

import threading

from fastapi import Body, HTTPException

from .. import paths


def register(app, rt) -> None:
    _lock = threading.Lock()
    _svc: dict = {}

    def lazy(name, factory):
        with _lock:
            if name not in _svc:
                _svc[name] = factory()
            return _svc[name]

    # ------------------------------------------------------------------ TASK 019: TraderLifeGame
    from ..trader_life_game import GameError, GameService, ReadOnlyAccountView

    def tlg():
        return lazy("tlg", lambda: GameService(paths.data_dir() / "trader_life_game", ReadOnlyAccountView.from_bridge(getattr(rt, "bridge", None))))

    def g(fn, *a, **k):
        try:
            return fn(*a, **k)
        except GameError as exc:
            raise HTTPException(exc.status, f"{exc.code}: {exc.detail}" if exc.detail else exc.code) from None

    @app.get("/api/v1/tlg/meta")
    def tlg_meta():
        return {**tlg().classes(), "navigation_id": "TRADER_LIFEGAME", "market_profile": None, "execution": "ISOLATED"}

    @app.get("/api/v1/tlg/state")
    def tlg_state():
        s = tlg()
        if s._profile(required=False) is None:
            return {"profile": None, "needs_character": True}
        return g(s.state)

    @app.post("/api/v1/tlg/profile")
    def tlg_profile_create(body: dict = Body(...)):
        return g(tlg().create_profile, body)

    @app.put("/api/v1/tlg/profile")
    def tlg_profile_update(body: dict = Body(...)):
        return g(tlg().update_profile, body)

    @app.get("/api/v1/tlg/xp")
    def tlg_xp(limit: int = 100):
        return {"items": g(tlg().xp_history, limit)}

    @app.get("/api/v1/tlg/journal")
    def tlg_journal():
        return g(tlg().journal)

    @app.put("/api/v1/tlg/journal/{ref}")
    def tlg_annotate(ref: str, body: dict = Body(...)):
        return g(tlg().annotate, ref, body)

    @app.get("/api/v1/tlg/notes")
    def tlg_notes(kind: str | None = None):
        return {"items": g(tlg().notes, kind)}

    @app.post("/api/v1/tlg/notes/{kind}")
    def tlg_note(kind: str, body: dict = Body(...)):
        return g(tlg().add_note, kind.upper(), body)

    @app.get("/api/v1/tlg/academy")
    def tlg_academy():
        return g(tlg().academy)

    @app.post("/api/v1/tlg/academy/lesson/{lesson_id}")
    def tlg_lesson(lesson_id: str):
        return g(tlg().complete_lesson, lesson_id)

    @app.post("/api/v1/tlg/academy/quiz/{level}")
    def tlg_quiz(level: int, body: dict = Body(...)):
        return g(tlg().submit_quiz, level, body.get("answers"))

    @app.get("/api/v1/tlg/academy/risk")
    def tlg_risk():
        return g(tlg().risk_exercise)

    @app.post("/api/v1/tlg/academy/risk")
    def tlg_risk_submit(body: dict = Body(...)):
        return g(tlg().submit_risk_exercise, str(body.get("exercise_id") or ""), body.get("answer"))

    @app.get("/api/v1/tlg/quests")
    def tlg_quests():
        return {"items": g(tlg().quests)}

    @app.post("/api/v1/tlg/quests/{quest_id}/claim")
    def tlg_claim(quest_id: str):
        return g(tlg().claim, quest_id)

    @app.get("/api/v1/tlg/skills")
    def tlg_skills():
        return g(tlg().skills)

    @app.post("/api/v1/tlg/skills/{skill_id}")
    def tlg_unlock(skill_id: str):
        return g(tlg().unlock_skill, skill_id)

    @app.get("/api/v1/tlg/calendar")
    def tlg_calendar(month: str):
        return g(tlg().calendar, month)

    @app.get("/api/v1/tlg/coach")
    def tlg_coach():
        return g(tlg().coach)

    @app.post("/api/v1/tlg/coach/memory")
    def tlg_mem_add(body: dict = Body(...)):
        return g(tlg().coach_memory_add, body.get("text"))

    @app.delete("/api/v1/tlg/coach/memory")
    def tlg_mem_del(memory_id: int | None = None):
        return g(tlg().coach_memory_delete, memory_id)

    @app.get("/api/v1/tlg/sim")
    def tlg_sims():
        return {"items": g(tlg().sim_sessions)}

    @app.post("/api/v1/tlg/sim")
    def tlg_sim_start(body: dict = Body(...)):
        sym = str(body.get("symbol") or getattr(getattr(rt.cfg.get(), "mt5", None), "symbol", "XAUUSD"))
        return g(tlg().sim_start, sym, str(body.get("tf") or "H1"), int(body.get("count") or 400))

    @app.get("/api/v1/tlg/sim/{sid}")
    def tlg_sim_view(sid: int):
        return g(tlg().sim_view, sid)

    @app.post("/api/v1/tlg/sim/{sid}/step")
    def tlg_sim_step(sid: int, body: dict = Body(default={})):
        return g(tlg().sim_step, sid, int(body.get("n") or 1))

    @app.post("/api/v1/tlg/sim/{sid}/open")
    def tlg_sim_open(sid: int, body: dict = Body(...)):
        return g(tlg().sim_open, sid, str(body.get("side") or ""), body.get("size"), body.get("sl"), body.get("tp"))

    @app.post("/api/v1/tlg/sim/{sid}/close/{trade_id}")
    def tlg_sim_close(sid: int, trade_id: int):
        return g(tlg().sim_close, sid, trade_id)

    @app.post("/api/v1/tlg/sim/{sid}/finish")
    def tlg_sim_finish(sid: int):
        return g(tlg().sim_finish, sid)

    @app.get("/api/v1/tlg/lifestyle")
    def tlg_life():
        return g(tlg().lifestyle)

    @app.post("/api/v1/tlg/lifestyle/{item_id}/buy")
    def tlg_buy(item_id: str):
        return g(tlg().buy, item_id)

    @app.post("/api/v1/tlg/lifestyle/{item_id}/equip")
    def tlg_equip(item_id: str):
        return g(tlg().equip, item_id)

    @app.get("/api/v1/tlg/leaderboard")
    def tlg_board():
        return g(tlg().leaderboard)

    # ------------------------------------------------------------------ TASK 007: Modular Indicator & Smoothing Engine
    from ..indicators import smoothing as SM
    _ind = SM.IndicatorEngine()

    def _bars(tf: str, count: int) -> list[dict]:
        b = getattr(rt, "bridge", None)
        if b is None:
            return []
        try:
            return b.bars(tf, count, include_forming=False)
        except Exception:  # noqa: BLE001
            return []

    @app.get("/api/v1/indicators/catalog")
    def ind_catalog():
        return SM.catalog()

    @app.post("/api/v1/indicators/calculate")
    def ind_calculate(body: dict = Body(...)):
        try:
            tf = str(body.get("timeframe") or "H1")
            sym = getattr(getattr(rt.cfg.get(), "mt5", None), "symbol", "") if getattr(rt, "cfg", None) else ""
            spec = SM.IndicatorSpec.make(body.get("method"), body.get("period"), body.get("applied_price") or "CLOSE",
                                         body.get("policy") or "PMW_LEGACY_V1", sym, tf, "MT5")
            bars = body.get("bars") if isinstance(body.get("bars"), list) else _bars(tf, max(10, min(int(body.get("count") or 500), 20000)))
            rev = sum(int(b.get("revision") or 0) for b in bars) if bars else None
            return _ind.calculate(spec, bars, revision=rev)
        except SM.SpecError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/v1/indicators/diagnostics")
    def ind_diag():
        return {"engine": SM.ENGINE_VERSION, "states": len(_ind._st), "keys": sorted(_ind._st)[:50], "mode": "CHART_ONLY / SHADOW (opt-in)"}

    # ------------------------------------------------------------------ TASK 008 / 009: session context clock + server-hour boxes (read-only)
    from datetime import datetime as _dt, timezone as _tz
    from ..analytics import session_context as SC

    def _ctx_inputs(tf: str):
        b = getattr(rt, "bridge", None)
        if b is None:
            return None, None, [], [], {}, ""
        q = b.quote_status()
        ev = b.clock.evidence.as_dict() if getattr(b, "clock", None) else {}
        bars = b.bars(tf, 2000, include_forming=True) if tf in getattr(b, "tfs", {}) else []
        d1 = b.bars("D1", 40, include_forming=True) if "D1" in getattr(b, "tfs", {}) else []
        return q, ev, bars, d1, dict(b.symbol_info or {}), getattr(b.cfg, "symbol", "")

    @app.get("/api/v1/session-context")
    def session_ctx(timeframe: str = "M5", mode: str = "AUTO_DST"):
        if mode not in ("AUTO_DST", "FIXED_GMT"):
            raise HTTPException(400, "mode: AUTO_DST | FIXED_GMT")
        q, ev, bars, d1, _, sym = _ctx_inputs(timeframe)
        last = next((b for b in reversed(bars) if b.get("open_utc")), None)
        lo = _dt.fromisoformat(last["open_utc"].replace("Z", "+00:00")) if last else None
        return SC.snapshot(instrument=sym, timeframe=timeframe, as_of=_dt.now(_tz.utc), mode=mode, quote=q, clock_evidence=ev,
                           last_bar_open_utc=lo, d1_bars=d1)

    @app.get("/api/v1/session-context/boxes")
    def session_boxes(timeframe: str = "M5", days: int = 5):
        q, ev, bars, _, meta, sym = _ctx_inputs(timeframe)
        return {"instrument": sym, "timeframe": timeframe, "boxes": SC.range_boxes(bars, history_days=max(1, min(days, 30)),
                tf_seconds=SC.TF_SECONDS.get(timeframe, 300)), "definition": SC.SERVER_BOXES, "hud": SC.hud(q, meta, bars, ev),
                "mode": "OBSERVABILITY_ONLY", "time_basis": "BROKER_SERVER_TIME (godziny serwera, nie strefy IANA)"}

    # ------------------------------------------------------------------ TASK 001-004: multi-market plane + order flow (read-only)
    from ..markets import universe as MU
    from ..orderflow import analytics as OA
    from ..orderflow.trades import SIDE_SEMANTICS, TradeLedger

    def _hl():
        b = getattr(rt, "baskets", None)
        if b is not None and getattr(b, "hl", None) is not None:
            return b.hl
        from ..baskets.hyperliquid import Hyperliquid
        return lazy("hl", Hyperliquid)

    def universe():
        return lazy("universe", lambda: MU.Universe(_hl()))

    _BR = {"CRYPTO": MU.CryptoMarketBridge, "INDICES": MU.IndicesMarketBridge, "FOMO_STOCK_PERPS": MU.FomoStockPerpsBridge}
    _ledger = TradeLedger()

    def bridge(market: str):
        if market not in _BR:
            raise HTTPException(404, f"UNKNOWN_MARKET: {market} ({', '.join(_BR)})")
        return _BR[market](_hl(), universe())

    def mu(fn, *a):
        try:
            return fn(*a)
        except MU.UniverseError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception as exc:  # noqa: BLE001 - provider / network
            raise HTTPException(503, f"PROVIDER_UNAVAILABLE: {type(exc).__name__}: {exc}"[:300]) from None

    @app.get("/api/v1/markets/v2")
    def markets_v2():
        return {"markets": MU.MARKETS, "timeframes": MU.TIMEFRAMES, "resample": MU.RESAMPLE_FROM, "templates": MU.basket_templates(),
                "side_semantics": SIDE_SEMANTICS, "seed": MU.validate_seed(MU.load_seed())}

    @app.get("/api/v1/markets/v2/fomo-universe")
    def fomo_universe():
        u = universe()
        ins = u.instruments()
        res = MU.resolve_seed(MU.load_seed(), ins)
        counts = {}
        for r in res:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"seed": MU.validate_seed(MU.load_seed()), "seed_date": MU.SEED_DATE, "resolution": res, "counts": counts, "metadata": u.raw_versions,
                "error": u.error, "warnings": MU.STOCK_PERP_WARNINGS, "execution": "DISABLED (RESEARCH_ONLY)"}

    @app.get("/api/v1/markets/v2/{market}/instruments")
    def market_instruments(market: str):
        return {"market": market, "items": mu(bridge(market).instruments), "health": bridge(market).health(), "error": universe().error}

    @app.get("/api/v1/markets/v2/{market}/candles")
    def market_candles(market: str, instrument: str, timeframe: str = "1h", n: int = 300):
        return mu(bridge(market).candles, instrument, timeframe, max(10, min(n, 2000)))

    @app.get("/api/v1/markets/v2/{market}/context")
    def market_context(market: str, instrument: str):
        return mu(bridge(market).context, instrument)

    @app.get("/api/v1/orderflow/{market}/workspace")
    def orderflow_workspace(market: str, instrument: str, row: float = 0.0, tf_seconds: int = 60):
        """Bookmap-style workspace data: DOM + depth column + trade bubbles + trade-based VP + footprint (one ledger)."""
        br = bridge(market)
        book = mu(br.book, instrument)
        evs = mu(br.trades, instrument)
        stats = _ledger.extend(evs)
        ins_id = evs[0].instrument_id if evs else book["instrument_id"]
        ev = _ledger.events(ins_id)
        if row <= 0:
            px = (book["bids"][0][0] if book["bids"] else (ev[-1].price if ev else 1.0))
            row = float(f"{px * 0.0005:.2g}") or 0.01
        ob = OA.OrderBook()
        ob.snapshot(book["bids"], book["asks"])
        return {"instrument_id": ins_id, "dom": ob.dom(), "heatmap": OA.heatmap([{"t": book["t"], "bids": book["bids"], "asks": book["asks"]}], row),
                "bubbles": OA.bubbles(ev), "volume_profile": OA.volume_profile(ev, row) if ev else {"status": "NO_DATA"},
                "footprint": OA.footprint(ev, tf_seconds, row) if ev else {"status": "NO_DATA"}, "cvd": OA.cvd(ev), "ledger": stats,
                "side_semantics": SIDE_SEMANTICS.get("HYPERLIQUID"), "mode": "READ_ONLY"}

    # ------------------------------------------------------------------ TASK 005 / 006 / 010 / 011 / 016: model layers (OFF / OBSERVE / SHADOW)
    from ..evaluation import pt_skill as PT
    from ..ml import association_rules as AR
    from ..ml import dt_ranker as DT
    from ..mm.bat_encoder import BATEncoder

    _ranker: dict = {"bundle": None, "manifest": None}

    @app.post("/api/v1/models/pt/evaluate")
    def pt_evaluate(body: dict = Body(...)):
        f, y = body.get("forecasts") or [], body.get("outcomes") or []
        if not isinstance(f, list) or not isinstance(y, list) or len(f) != len(y) or len(f) > 200_000:
            raise HTTPException(400, "forecasts / outcomes: listy tej samej długości")
        prof = body.get("profile") or "ARTICLE_25105_V1"
        if prof not in PT.PROFILES:
            raise HTTPException(400, f"profile: {PT.PROFILES}")
        return PT.evaluate(f, y, prof)

    @app.get("/api/v1/models/association/snapshot")
    def ar_snapshot(timeframe: str = "H1", horizon: int = 24):
        bars = _bars(timeframe, 5000)
        if not bars:
            return {"status": "NOT_CONFIGURED", "reason": "brak zamkniętych świec", "mode": "OBSERVE"}
        from datetime import datetime as _d
        rows = [{**b, "hour": _d.fromisoformat(b["open_utc"].replace("Z", "+00:00")).hour if b.get("open_utc") else -1} for b in bars]
        masks = AR.event_bits(rows)
        m = AR.train(masks, AR.labels([float(b["c"]) for b in rows], max(1, min(horizon, 200)), 0.0), scope={"timeframe": timeframe, "horizon": horizon})
        cur = masks[-1] if masks else None
        return {"status": m["status"], "mode": "OBSERVE", "n_labeled": m.get("n_labeled"), "rules": len(m.get("rules", [])), "current_mask": cur,
                "current_events": [AR.CATALOG[k] for k in range(len(AR.CATALOG)) if cur is not None and cur >> k & 1],
                "assess_long": AR.assess(m, cur, "LONG"), "assess_short": AR.assess(m, cur, "SHORT"), "schema": AR.SCHEMA}

    @app.get("/api/v1/models/dt-ranker/status")
    def dtr_status():
        return {"schema": DT.SCHEMA, "feature_schema": DT.FEATURE_SCHEMA, "mode": DT.DEFAULT_POLICY["mode"], "ready": _ranker["bundle"] is not None,
                "manifest": _ranker["manifest"], "note": "osobna rodzina; legacy DECISION_TREE / XGBOOST / selektor bez zmian"}

    @app.post("/api/v1/models/dt-ranker/rank")
    def dtr_rank(body: dict = Body(...)):
        try:
            cands = [DT.candidate_from_dict(c) for c in (body.get("candidates") or [])]
        except DT.CandidateError as exc:
            raise HTTPException(400, str(exc)) from None
        return DT.rank(_ranker["bundle"], cands, {"mode": "SHADOW"})

    @app.get("/api/v1/models/bat/shadow")
    def bat_shadow(timeframe: str = "H1"):
        bars = [{**b, "v": b.get("tv", 0)} for b in _bars(timeframe, 600)]
        return {**lazy("bat", BATEncoder).run(bars), "timeframe": timeframe} if bars else {"status": "NOT_CONFIGURED", "reason": "brak świec"}

    # ------------------------------------------------------------------ TASK 012 / 014 / 015: long horizon, strategy ROI, change points (read-only)
    from ..evaluation import strategy_roi as SR
    from ..forecast import long_horizon as LH
    from ..lab.change_points import pelt as CPT

    @app.get("/api/v1/strategy-roi")
    def strategy_roi(mode: str = "PAPER"):
        if mode not in ("PAPER", "AUTO_DEMO", "AUTO_LIVE"):
            raise HTTPException(400, "INVALID_MODE")
        b = getattr(rt, "bridge", None)
        return SR.report(SR.outcomes_from_db(rt.db, mode, getattr(b, "account_key", None)))

    @app.get("/api/v1/forecast/long-horizon")
    def long_horizon(horizon: str = "24h", timeframe: str = "H1"):
        if horizon not in LH.HORIZONS_S:
            raise HTTPException(400, f"horizon: {list(LH.HORIZONS_S)}")
        bars = [b for b in _bars(timeframe, 5000) if b.get("t_raw")]
        if not bars:
            return {"status": "UNAVAILABLE", "reason": "brak świec"}
        clk = getattr(getattr(rt, "bridge", None), "clock", None)
        off = getattr(clk, "offset", None) or 0
        return LH.forecast([b["t_raw"] - off for b in bars], [float(b["c"]) for b in bars], horizon)

    @app.get("/api/v1/change-points")
    def change_points(timeframe: str = "H1", lookback: int = 500, min_segment: int = 10, sensitivity: bool = False):
        bars = _bars(timeframe, max(lookback * 2, 800))
        if len(bars) < 2 * min_segment + 1:
            return {"status": "INSUFFICIENT_DATA", "bars": len(bars)}
        res = CPT.detect([float(b["c"]) for b in bars], lookback_returns=max(20, min(lookback, 5000)), m=max(2, min(min_segment, 200)),
                         sensitivity=sensitivity)
        times = [b.get("open_utc") for b in bars][-(len(res.get("segments", [])) and res["n"]) - 1:] if res.get("status") == "OK" else []
        if times:
            for s in res["segments"]:
                s["start_utc"], s["end_utc"] = times[s["start"] + 1] if s["start"] + 1 < len(times) else None, times[min(s["end"], len(times) - 1)]
        return {**res, "timeframe": timeframe, "computed_on": "closed bars only"}

    # ------------------------------------------------------------------ TASK 013: bootstrap status / profile
    @app.get("/api/v1/bootstrap")
    def bootstrap_status():
        b = getattr(rt, "bootstrap", None)
        if b is None:
            from ..bootstrap import Bootstrap
            b = lazy("bootstrap_view", lambda: Bootstrap(rt))
        return b.status()

    @app.put("/api/v1/bootstrap")
    def bootstrap_profile(body: dict = Body(...)):
        b = getattr(rt, "bootstrap", None)
        if b is None:
            raise HTTPException(409, "BOOTSTRAP_DISABLED (tryb demo / PMW_BOOTSTRAP=0)")
        try:
            return b.set_profile(str(body.get("profile") or ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/v1/desktop/display")
    def desktop_display(body: dict = Body(...)):
        from .. import desktop as DK
        bad = [k for k in body if k not in DK.DISPLAY_KEYS]
        if bad or not all(isinstance(body.get(k, True), bool) for k in DK.DISPLAY_KEYS):
            raise HTTPException(400, f"klucze: {DK.DISPLAY_KEYS} (bool)")
        cur = DK.load_prefs()
        return DK.save_display(*(body.get(k, cur[k]) for k in DK.DISPLAY_KEYS))

    # ------------------------------------------------------------------ TASK 017: Telegram account center (outbound only, OFF by default)
    from ..notify.account_center import AccountCenter, CenterError

    def _acct_roi(days: int) -> dict:
        b = rt.bridge
        with b._lock:
            deals = list(b.deals)
        from .. import stats as _ST
        r = _ST.account_roi(rt.db, b.account_key, deals, b.clock.offset, days=days) or {}
        return {"roi_pct": r.get("roi_pct"), "status": r.get("status") or ("OK" if r.get("roi_pct") is not None else "NO_DATA"),
                "deals": r.get("deals"), "net": r.get("net"), "currency": r.get("currency")}

    def acct():
        def make():
            b = getattr(rt, "bridge", None)
            tg = getattr(rt, "telegram", None)
            magic = getattr(getattr(rt.cfg.get(), "mt5", None), "magic_number", None) if getattr(rt, "cfg", None) else None
            return AccountCenter(paths.data_dir() / "telegram_account", deliver=(tg.account_event if tg else None),
                                 deals_fn=(lambda: [dict(d) for d in (b.deals or [])]) if b else None,
                                 account_fn=(lambda: b.account_status()) if b else None, pmw_magics=[magic] if magic else [],
                                 roi_fn=_acct_roi if b else None)
        return lazy("acct", make)

    def _acct_loop():
        import time as _t
        while True:
            _t.sleep(10)
            try:
                c = acct()
                c.poll()
                c.queue_reports()
                c.flush()
            except Exception:  # noqa: BLE001 - never breaks the engine
                pass
    if getattr(rt, "bridge", None) is not None and not getattr(rt, "_acct_thread", None):
        rt._acct_thread = threading.Thread(target=_acct_loop, name="telegram-account", daemon=True)
        rt._acct_thread.start()

    def ac(fn, *a):
        try:
            return fn(*a)
        except CenterError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/v1/telegram/account")
    def tg_account():
        return acct().status()

    @app.post("/api/v1/telegram/account/bind")
    def tg_bind(body: dict = Body(...)):
        return ac(acct().bind, str(body.get("account_key") or ""))

    @app.post("/api/v1/telegram/account/unbind")
    def tg_unbind():
        return acct().unbind()

    @app.put("/api/v1/telegram/account")
    def tg_update(body: dict = Body(...)):
        return ac(acct().update, body)

    @app.put("/api/v1/telegram/account/templates/{kind}")
    def tg_template(kind: str, body: dict = Body(...)):
        return ac(acct().set_template, kind, body.get("template"))

    # ------------------------------------------------------------------ TASK 018: Strategy Filter Bucket
    @app.get("/api/v1/strategy-filter/status")
    def sfb_status():
        b = getattr(rt, "baskets", None)
        if b is None:
            raise HTTPException(503, "koszyki niedostępne")
        return b.sfb.status()

    @app.put("/api/v1/strategy-filter/config")
    def sfb_config(body: dict = Body(...)):
        from ..baskets.sfb import ConfigError
        b = getattr(rt, "baskets", None)
        if b is None:
            raise HTTPException(503, "koszyki niedostępne")
        try:
            return b.set_sfb(body)
        except ConfigError as exc:
            raise HTTPException(400, str(exc)) from None

    # ------------------------------------------------------------------ TASK 021-025 (OFF / SHADOW / read-only)
    from ..apollo import asge as ASG
    from ..apollo import relationships as REL
    from ..apollo import risk_loot as RLC
    from ..apollo import smma_cci as SCC
    from ..apollo import traps as MTD

    def _hl_closes(market: str, instrument: str, tf: str, n: int):
        c = mu(bridge(market).candles, instrument, tf, n)
        return [(b["t"], b["c"]) for b in c["bars"]]

    @app.get("/api/v1/relationships/candidates")
    def rel_candidates():
        return {"items": REL.candidates(), "version": REL.VERSION}

    @app.get("/api/v1/relationships/pair")
    def rel_pair(a: str, b: str, market: str = "CRYPTO", timeframe: str = "1h", n: int = 500):
        return REL.analyse(_hl_closes(market, a, timeframe, n), _hl_closes(market, b, timeframe, n))

    @app.get("/api/v1/market-trap")
    def market_trap(timeframe: str = "M5"):
        bars = [{**b, "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"])} for b in _bars(timeframe, 300)]
        q = getattr(rt, "bridge", None).quote_status() if getattr(rt, "bridge", None) else None
        return MTD.detect(bars, spread_points=(q or {}).get("spread_points"), spread_baseline=None)

    @app.get("/api/v1/smma-cci")
    def smma_cci(timeframe: str = "M5"):
        if timeframe not in ("M5", "M15"):
            raise HTTPException(400, "timeframe: M5 | M15")
        return SCC.evaluate([{**b, "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"])} for b in _bars(timeframe, 400)])

    _trials = ASG.TrialLedger()

    @app.post("/api/v1/asge/run")
    def asge_run(body: dict = Body(...)):
        bars = [{"o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"])} for b in _bars(str(body.get("timeframe") or "H1"), 5000)]
        if len(bars) < 600:
            return {"status": "INSUFFICIENT_DATA", "bars": len(bars)}
        try:
            return ASG.run(bars, body.get("seeds") or [], int(body.get("children") or 10), ledger=_trials)
        except ASG.IRError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/v1/asge/ledger")
    def asge_ledger():
        return {"items": _trials.rows[-500:], "execution_allowed": ASG.EXECUTION_ALLOWED}

    @app.get("/api/v1/tlg/loot/catalog")
    def loot_catalog():
        return {"items": RLC.catalog(), "policy_version": RLC.POLICY_VERSION, "weights": RLC.WEIGHTS}

    @app.post("/api/v1/tlg/loot/evaluate")
    def loot_evaluate(body: dict = Body(...)):
        return RLC.evaluate(body)

    @app.post("/api/v1/tlg/loot/grant")
    def loot_grant(body: dict = Body(...)):
        if body.get("source_mode") != "SIMULATOR":
            raise HTTPException(409, "GRANT_SOURCE_NOT_ENABLED: w tej wersji nagrody tylko z symulatora (MT5 / dziennik: tylko ocena)")
        return g(RLC.grant, tlg(), body)
