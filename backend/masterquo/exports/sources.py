"""Data sources of the exporters (Apollo23 1.46). Every function READS an existing store (SQLite / JSON files of the module that owns the
data, the in-memory ledgers of the running app, the market bridges of TASK 003) and returns `Collected` rows - nothing here keeps a second
copy of the data and nothing changes the source.

SourceContext tells a source what is reachable:
* CLI without a running app: data folder only (SQLite / JSON stores, provider bridges built on demand);
* inside the app (API): additionally the runtime objects - MT5 bars, in-memory ledgers (order flow, ASGE trials, SFB snapshots, SHADOW journal).
A source that needs a runtime object and does not get it returns status UNAVAILABLE with a reason (never an invented / zero value).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .core import Collected, Dataset, mask_account, utc_iso

SAFE_ID = re.compile(r"[^a-z0-9_\-]+")


@dataclass
class SourceContext:
    data_dir: Path
    rt: object | None = None              # Runtime of the running app (None in the CLI)
    wf32: dict = field(default_factory=dict)   # in-memory objects published by api/wf32_routes.register (ledger, trials, journal, ...)
    hl: object | None = None              # Hyperliquid public client override (tests / CLI)

    # ---- helpers shared by sources
    @property
    def bridge(self):
        return getattr(self.rt, "bridge", None) if self.rt is not None else None

    def mt5_closed_bars(self, tf: str, count: int) -> list[dict] | None:
        b = self.bridge
        if b is None or tf not in getattr(b, "tfs", {}):
            return None
        return b.bars(tf, count, include_forming=False)

    def hyperliquid(self):
        if self.hl is not None:
            return self.hl
        fn = self.wf32.get("hl")
        if fn is not None:
            return fn()
        from ..baskets.hyperliquid import Hyperliquid
        return Hyperliquid()

    def universe(self):
        fn = self.wf32.get("universe")
        if fn is not None and self.hl is None:
            return fn()
        from ..markets import universe as MU
        return MU.Universe(self.hyperliquid())

    def market_bridge(self, market: str):
        from ..markets import universe as MU
        br = {"CRYPTO": MU.CryptoMarketBridge, "INDICES": MU.IndicesMarketBridge, "FOMO_STOCK_PERPS": MU.FomoStockPerpsBridge}.get(market)
        if br is None:
            raise ValueError(f"UNKNOWN_MARKET: {market} (CRYPTO, INDICES, FOMO_STOCK_PERPS)")
        return br(self.hyperliquid(), self.universe())


class ReadOnlyDB:
    """Read-only SQLite access (URI mode=ro): an export never migrates, locks for writing or creates the database."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=15, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def query(self, sql: str, args=()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def tables(self) -> list[str]:
        return [r["name"] for r in self.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    def columns(self, table: str) -> list[str]:
        if table not in self.tables():
            raise ValueError(f"UNKNOWN_TABLE: {table}")
        return [r["name"] for r in self.query(f'PRAGMA table_info("{table}")')]

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _unavailable(reason: str, provenance: dict) -> Collected:
    return Collected([], {**provenance, "unavailable_reason": reason}, status="UNAVAILABLE", notes=[reason])


def _slug(s: str) -> str:
    return SAFE_ID.sub("_", str(s).lower()).strip("_")[:40] or "x"


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ================================================================================================ TASK 001 / 002 / 004 - order flow
def orderflow(ctx: SourceContext, market: str = "CRYPTO", instrument: str = "", row: float = 0.0, tf_seconds: int = 60,
              refresh: bool = True) -> Collected:
    """Trade ledger + footprint + trade-based Volume Profile + DOM snapshot / heatmap column of one instrument (one ledger: the app's)."""
    from ..orderflow import analytics as OA
    prov = {"source": "orderflow.trades.TradeLedger (pamięć działającej aplikacji, jeden ledger)", "engine": None, "market": market,
            "instrument": instrument, "vp_version": OA.VP_VERSION, "fp_version": OA.FP_VERSION}
    ledger = ctx.wf32.get("ledger")
    if ledger is None:
        return _unavailable("APP_NOT_RUNNING: ledger transakcji istnieje tylko w pamięci działającej aplikacji (użyj API albo uruchom aplikację)", prov)
    from ..orderflow.trades import ENGINE_VERSION, SIDE_SEMANTICS
    prov["engine"] = ENGINE_VERSION
    if not instrument:
        return _unavailable("INSTRUMENT_REQUIRED", prov)
    br = ctx.market_bridge(market)
    notes, book = [], None
    try:
        if refresh:                                     # same path as the workspace view: append the latest public trades to THE ledger
            ledger.extend(br.trades(instrument))
        book = br.book(instrument)
    except Exception as exc:  # noqa: BLE001 - provider / network: export what the ledger already holds
        notes.append(f"PROVIDER_UNAVAILABLE: {type(exc).__name__}: {exc}"[:240])
    ins_id = book["instrument_id"] if book else br._ins(instrument).instrument_id
    ev = ledger.events(ins_id)
    if row <= 0:
        px = book["bids"][0][0] if book and book["bids"] else (ev[-1].price if ev else None)
        row = OA.auto_row(px) if px else 0.0
    trades = [{"ts_utc": utc_iso(e.ts), "ts_epoch": e.ts, "provider": e.provider, "instrument_id": e.instrument_id, "trade_id": e.trade_id,
               "price": e.price, "size": e.size, "aggressor": e.aggressor, "raw_side": e.raw_side, "revision": e.revision} for e in ev]
    fp_rows, vp_rows, vp = [], [], None
    if ev and row > 0:
        fp = OA.footprint(ev, int(tf_seconds), row)
        for b in fp["bars"]:
            for r in b["rows"]:
                fp_rows.append({"bar_open_utc": utc_iso(b["t"]), "price": r["price"], "A": r["A"], "B": r["B"], "U": r["U"], "V": r["V"],
                                "delta": r["delta"], "trades": r["trades"], "imbalance": r["imbalance"], "bar_poc": b["poc"],
                                "bar_volume": b["volume"], "bar_delta": b["delta"]})
        vp = OA.volume_profile(ev, row)
        vp_rows = [{**r} for r in vp.get("rows", [])]
    dom_rows, heat_rows = [], []
    if book:
        snap_t = utc_iso(book["t"]) if book.get("t") else None
        ob = OA.OrderBook()
        ob.snapshot(book["bids"], book["asks"])
        d = ob.dom()
        for side, levels in (("BID", d["bids"]), ("ASK", d["asks"])):
            for i, (p, s) in enumerate(levels):
                dom_rows.append({"snapshot_utc": snap_t, "side": side, "level": i + 1, "price": p, "size": s, "book_state": d["state"]})
        if row > 0:
            hm = OA.heatmap([{"t": book["t"], "bids": book["bids"], "asks": book["asks"]}], row)
            for col in hm["columns"]:
                for p, s in col["cells"].items():
                    heat_rows.append({"snapshot_utc": utc_iso(col["t"]) if col["t"] else None, "price_row": p, "resting_size": s})
    prov.update(instrument_id=ins_id, row_size=row or None, tf_seconds=int(tf_seconds), side_semantics=SIDE_SEMANTICS.get("HYPERLIQUID"),
                volume_profile={k: vp.get(k) for k in ("status", "poc", "vah", "val", "total_volume", "value_area_pct", "directional", "delta",
                                                       "unknown_volume")} if vp else {"status": "NO_DATA"},
                dom_quality=(book or {}).get("quality"), mode="READ_ONLY")
    ds = [Dataset("trades", trades, "PROVIDER", time_columns={"ts_utc": "UTC", "ts_epoch": "UTC_EPOCH_SECONDS"},
                  description="jeden ledger transakcji (TradeLedger): strona agresora tylko zweryfikowana, inaczej UNKNOWN"),
          Dataset("footprint", fp_rows, "DERIVED", time_columns={"bar_open_utc": "UTC"}, description="footprint: A+B+U=V, delta tylko przy zweryfikowanej stronie"),
          Dataset("volume_profile", vp_rows, "DERIVED", description="Volume Profile z transakcji (POC/VA w manifest.provenance.volume_profile)"),
          Dataset("dom_snapshot", dom_rows, "PROVIDER", time_columns={"snapshot_utc": "UTC"}, description="DOM: płynność oczekująca (snapshot top-N)"),
          Dataset("heatmap", heat_rows, "DERIVED", time_columns={"snapshot_utc": "UTC"}, description="kolumna heatmapy z tego snapshotu (DEGRADED top-N)")]
    return Collected(ds, prov, status="PARTIAL" if notes else "OK", notes=notes)


# ================================================================================================ TASK 003 - market candles + FOMO 101
def market_candles(ctx: SourceContext, market: str = "CRYPTO", instruments: list[str] | None = None, timeframes: list[str] | None = None,
                   n: int = 500) -> Collected:
    from ..markets import universe as MU
    tfs = list(timeframes or MU.TIMEFRAMES)
    bad = [t for t in tfs if t not in MU.TIMEFRAMES]
    if bad:
        raise ValueError(f"UNSUPPORTED_TF: {bad} ({', '.join(MU.TIMEFRAMES)})")
    if not instruments:
        raise ValueError("INSTRUMENT_REQUIRED: podaj co najmniej jeden instrument (symbol lub instrument_id)")
    n = max(10, min(int(n), 5000))
    br = ctx.market_bridge(market)
    prov = {"source": f"markets.universe.{type(br).__name__}.candles (Hyperliquid, istniejący most TASK 003)", "market": market,
            **{k: v for k, v in MU.MARKETS[market].items()}, "timeframes": tfs, "bars_per_tf": n, "partial_bar_policy": "tylko zamknięte świece",
            "resample": MU.RESAMPLE_FROM, "instruments": {}}
    ds, notes = [], []
    for ins in instruments:
        for tf in tfs:
            try:
                c = br.candles(ins, tf, n)
            except Exception as exc:  # noqa: BLE001 - provider / unknown instrument: reported per series, never filled
                notes.append(f"{ins}/{tf}: {type(exc).__name__}: {exc}"[:240])
                continue
            meta = c["instrument"]
            prov["instruments"][meta["instrument_id"]] = {k: meta.get(k) for k in ("native_symbol", "display", "asset_id", "metadata_version", "status",
                                                                                   "execution", "product_type")}
            rows = [{"open_utc": utc_iso(b["t"]), "open_epoch": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b.get("v"),
                     "trades": b.get("trades"), "resampled_from": b.get("resampled_from"), "instrument_id": meta["instrument_id"],
                     "metadata_version": meta.get("metadata_version"), "timeframe": tf} for b in c["bars"]]
            ds.append(Dataset(f"candles_{_slug(meta['display'] or meta['native_symbol'])}_{tf}", rows, "PROVIDER",
                              time_columns={"open_utc": "UTC", "open_epoch": "UTC_EPOCH_SECONDS"}, description=f"{meta['instrument_id']} {tf} ({c['basis']})"))
    if not ds:
        return Collected([], prov, status="UNAVAILABLE", notes=notes or ["NO_SERIES"])
    return Collected(ds, prov, status="PARTIAL" if notes else "OK", notes=notes)


def fomo_universe(ctx: SourceContext) -> Collected:
    from ..markets import universe as MU
    from .core import sha256_file
    seed = MU.load_seed()
    u = ctx.universe()
    ins = u.instruments()
    res = MU.resolve_seed(seed, ins)
    prov = {"source": "markets.universe.resolve_seed (seed CSV + aktualne metadane venue xyz)", "seed_file": MU.SEED_FILE.name,
            "seed_sha256": sha256_file(MU.SEED_FILE), "seed_date": MU.SEED_DATE, "seed_check": MU.validate_seed(seed),
            "metadata_versions": u.raw_versions or None, "universe_error": u.error, "execution": "DISABLED (RESEARCH_ONLY)"}
    rows = [{"rank": r.get("rank"), "symbol": r.get("symbol"), "group": r.get("group"), "category": r.get("category"),
             "snapshot_date": r.get("snapshot_date"), "instrument_type": r.get("instrument_type"), "status": r.get("status"),
             "instrument_id": r.get("instrument_id"), "native_symbol": r.get("native_symbol"), "asset_id": r.get("asset_id"),
             "metadata_version": r.get("metadata_version"), "market": r.get("market"), "reason": r.get("reason")} for r in res]
    versions = [{"venue": k, "metadata_version": v} for k, v in (u.raw_versions or {}).items() if k != "dexs"]
    notes = [f"UNIVERSE_ERROR: {u.error}"] if u.error else []
    return Collected([Dataset("fomo_101_resolution", rows, "REFERENCE", description="seed FOMO 101 -> instrument xyz (status ACTIVE/NOT_FOUND/DELISTED/NOT_VERIFIED)"),
                      Dataset("metadata_versions", versions, "REFERENCE", description="wersje metadanych venue użyte do rozpoznania")],
                     prov, status="PARTIAL" if notes else "OK", notes=notes)


# ================================================================================================ TASK 014 - strategy ROI
ROI_ENVS = (("PAPER", "roi_paper", "VIRTUAL"), ("AUTO_DEMO", "roi_auto_demo", "DEMO"), ("AUTO_LIVE", "roi_auto_live", "REAL"))


def strategy_roi(ctx: SourceContext) -> Collected:
    from ..evaluation import strategy_roi as SR
    dbp = ctx.data_dir / "masterquo.sqlite"
    prov = {"source": "evaluation.strategy_roi.outcomes_from_db + report (tabela trades, tylko odczyt)", "database": dbp.name,
            "separation": "PAPER (wirtualne), AUTO_DEMO (konto demo), AUTO_LIVE (realne) – osobne pliki, nigdy łączone",
            "account_ids": "zamaskowane (server:***123)"}
    if not dbp.exists():
        return Collected([Dataset(name, [], kind) for _, name, kind in ROI_ENVS], {**prov, "database_present": False}, status="EMPTY",
                         notes=["NO_DATABASE: brak masterquo.sqlite w folderze danych"])
    ds, excluded = [], {}
    with ReadOnlyDB(dbp) as db:
        for mode, name, kind in ROI_ENVS:
            rep = SR.report(SR.outcomes_from_db(db, mode, None))
            rows = []
            for section, items in (("ACTIVE", rep["items"]), ("RETIRED_SCOPE", rep["retired_scope"])):
                for it in items:
                    sc = dict(it["scope"])
                    sc["account"] = mask_account(sc.get("account")) if sc.get("account") else sc.get("account")
                    rows.append({"section": section, **{f"scope_{k}": (v or None) for k, v in sc.items()},
                                 **{k: v for k, v in it.items() if k not in ("scope", "label")}})
            excluded[mode] = rep["excluded"]
            ds.append(Dataset(name, rows, kind, description=f"ROI strategii – środowisko {mode} ({kind})"))
    prov.update(excluded=excluded, policy=SR.report([])["policy"])
    return Collected(ds, prov)


# ================================================================================================ TASK 018 - SFB snapshots
def sfb_snapshots(ctx: SourceContext) -> Collected:
    prov = {"source": "baskets.sfb.StrategyFilterBucket.snapshots (pamięć działającej aplikacji, ostatnie 200)", "apply_to_execution": False}
    b = getattr(ctx.rt, "baskets", None) if ctx.rt is not None else None
    sfb = getattr(b, "sfb", None) if b is not None else None
    cfg = _read_json(ctx.data_dir / "baskets" / "sfb.json")
    if sfb is None:
        return _unavailable("APP_NOT_RUNNING: snapshoty SFB istnieją tylko w pamięci działającej aplikacji", {**prov, "config_file": cfg})
    snaps, items = [], []
    for s in list(sfb.snapshots):
        snaps.append({"snapshot_id": s.get("snapshot_id"), "at_utc": utc_iso(s.get("at")), "bucket_key": s.get("bucket_key"), "mode": s.get("mode"),
                      "bucket_status": s.get("bucket_status"), "would_keep": s.get("would_keep"), "apply_to_execution": s.get("apply_to_execution"),
                      "scope": s.get("scope"), "config": s.get("config")})
        for sid, it in (s.get("items") or {}).items():
            ev = it.get("evidence") or {}
            items.append({"snapshot_id": s.get("snapshot_id"), "at_utc": utc_iso(s.get("at")), "strategy_id": sid,
                          "compatibility_status": it.get("compatibility_status"), "eligibility_status": it.get("eligibility_status"),
                          "reason_codes": it.get("reason_codes"), **{f"evidence_{k}": v for k, v in ev.items()}})
    prov.update(mode=sfb.cfg.get("mode"), config=sfb.cfg)
    return Collected([Dataset("sfb_snapshots", snaps, "DERIVED", time_columns={"at_utc": "UTC"}),
                      Dataset("sfb_items", items, "DERIVED", time_columns={"at_utc": "UTC"})], prov)


# ================================================================================================ TASK 024 - ASGE trial ledger
def asge_trials(ctx: SourceContext) -> Collected:
    from ..apollo import asge as ASG
    trials = ctx.wf32.get("trials")
    prov = {"source": "apollo.asge.TrialLedger (<dane>/apollo/asge_trials.jsonl, append-only)", "version": ASG.VERSION,
            "execution_allowed": ASG.EXECUTION_ALLOWED}
    if trials is None:                                   # CLI: the durable ledger file (1.46), read only
        f = ctx.data_dir / "apollo" / "asge_trials.jsonl"
        if not f.exists():
            return Collected([Dataset("asge_trials", [], "DERIVED")], {**prov, "file_present": False}, status="EMPTY",
                             notes=["NO_TRIALS: generator nie był uruchamiany"])
        trials = ASG.TrialLedger(f)
    rows = [{"trial_id": r.get("trial_id"), "created_at_utc": utc_iso(r.get("created_at")), "ir_hash": r.get("ir_hash"), "parent": r.get("parent"),
             "data_hash": r.get("data_hash"), "status": r.get("status"), "reasons": r.get("reasons"), "dev_trades": r.get("dev_trades"),
             "dev_mean_net_r": r.get("dev_mean_net_r"), "positive_folds": r.get("positive_folds"), "holdout_mean_net_r": r.get("holdout_mean_net_r"),
             # 1.46: the constant, never the value stored in the row (a restored / edited ledger file could say true); `integrity` shows it
             "execution_allowed": ASG.EXECUTION_ALLOWED, "integrity": r.get("integrity"), "hurdle_net_r": r.get("hurdle_net_r"),
             "holdout_reused_from": r.get("holdout_reused_from"), "data_hash_basis": r.get("data_hash_basis"), "version": r.get("version"),
             "ir": r.get("ir")} for r in list(trials.rows)]
    prov["persistence"] = getattr(trials, "path", None) and str(Path(trials.path).name)
    return Collected([Dataset("asge_trials", rows, "DERIVED", time_columns={"created_at_utc": "UTC"},
                              description="każda próba generatora (także odrzucone) z rodowodem parent/child; execution_allowed = false")], prov)


# ================================================================================================ TASK 012 / 015 / 010 / 011 / 016 / 005 - SHADOW models
def _mt5_series(ctx: SourceContext, tf: str, count: int) -> tuple[list[dict] | None, str | None]:
    bars = ctx.mt5_closed_bars(tf, count)
    if bars is None:
        return None, "APP_NOT_RUNNING_OR_TF_NOT_LOADED: świece MT5 są w pamięci działającej aplikacji"
    return bars, None


def change_points(ctx: SourceContext, timeframe: str = "H1", lookback: int = 500, min_segment: int = 10, sensitivity: bool = False) -> Collected:
    from ..lab.change_points import pelt as CPT
    prov = {"source": "lab.change_points.pelt.detect (zamknięte świece MT5)", "objective": CPT.OBJECTIVE_VERSION, "timeframe": timeframe,
            "lookback_returns": lookback, "min_segment": min_segment, "mode": "RESEARCH / READ_ONLY"}
    bars, why = _mt5_series(ctx, timeframe, max(lookback * 2, 800))
    if bars is None:
        return _unavailable(why, prov)
    if len(bars) < 2 * min_segment + 1:
        return Collected([Dataset("segments", [], "DERIVED"), Dataset("change_points", [], "DERIVED")], {**prov, "bars": len(bars)},
                         status="EMPTY", notes=["INSUFFICIENT_DATA"])
    closes = [float(b["c"]) for b in bars]
    res = CPT.detect(closes, lookback_returns=max(20, min(lookback, 5000)), m=max(2, min(min_segment, 200)), sensitivity=sensitivity)
    n_ret = res.get("n") or 0
    # return index k = log(c[k+1]/c[k]) of the LAST n_ret returns -> bar index of its END close = len(bars) - n_ret + k
    base = len(bars) - n_ret

    def bar_t(i):
        return (bars[i].get("open_utc") if 0 <= i < len(bars) else None), (bars[i].get("t_raw") if 0 <= i < len(bars) else None)
    segs = []
    for s in res.get("segments") or []:
        a_utc, a_raw = bar_t(base + s["start"])
        e_utc, e_raw = bar_t(base + s["end"] - 1) if s.get("end") else (None, None)
        segs.append({**{k: v for k, v in s.items()}, "start_bar_open_utc": a_utc, "start_bar_open_server": a_raw, "end_bar_open_utc": e_utc,
                     "end_bar_open_server": e_raw})
    cps = []
    for c in res.get("change_points") or []:
        u, raw = bar_t(base + c)
        cps.append({"return_index": c, "bar_open_utc": u, "bar_open_server": raw})
    for s in res.get("sensitivity") or []:
        for c in cps:
            if c["return_index"] == s["index"]:
                c.update(support_count=s["support_count"], eligible_runs=s["eligible_runs"], robustness_label=s["robustness_label"])
    prov.update(status=res.get("status"), beta=res.get("beta"), n_returns=n_ret, bars=len(bars),
                time_basis={"*_utc": "UTC (open_utc z mostu MT5; null gdy offset serwera niezweryfikowany)",
                            "*_server": "BROKER_SERVER_TIME epoch (t_raw z MT5)"})
    tc = {"start_bar_open_utc": "UTC", "end_bar_open_utc": "UTC", "start_bar_open_server": "BROKER_SERVER_TIME", "end_bar_open_server": "BROKER_SERVER_TIME"}
    return Collected([Dataset("segments", segs, "DERIVED", time_columns=tc),
                      Dataset("change_points", cps, "DERIVED", time_columns={"bar_open_utc": "UTC", "bar_open_server": "BROKER_SERVER_TIME"})], prov)


def long_horizon(ctx: SourceContext, timeframe: str = "H1", horizons: list[str] | None = None) -> Collected:
    from ..forecast import long_horizon as LH
    hz = list(horizons or LH.HORIZONS_S)
    bad = [h for h in hz if h not in LH.HORIZONS_S]
    if bad:
        raise ValueError(f"horizon: {list(LH.HORIZONS_S)}")
    prov = {"source": "forecast.long_horizon.forecast (zamknięte świece MT5, UTC)", "engine": LH.ENGINE, "timeframe": timeframe,
            "horizons": hz, "mode": "SHADOW / DISPLAY_ONLY", "execution": "HARD_OFF"}
    bars, why = _mt5_series(ctx, timeframe, 5000)
    if bars is None:
        return _unavailable(why, prov)
    pts = [(b["open_utc"], float(b["c"])) for b in bars if b.get("open_utc")]
    if not pts:
        return Collected([Dataset("forecasts", [], "DERIVED")], {**prov, "bars": len(bars)}, status="UNAVAILABLE",
                         notes=["TIME_OFFSET_UNVERIFIED: brak open_utc (offset serwera MT5 nieustalony) – prognoza nie jest liczona na zgadywanym czasie"])
    import time as _time

    from ..timeutil import TF_SECONDS, parse_iso
    ts = [parse_iso(t).timestamp() for t, _ in pts]
    px = [c for _, c in pts]
    rows = []
    now = _time.time()
    for h in hz:
        # 1.46: bar OPEN times -> close times (as_of / target_utc were one TF early) and the wall clock for the data age (STALE unreachable)
        f = LH.forecast(ts, px, h, now=now, bar_seconds=TF_SECONDS.get(timeframe, 0))
        q = f.get("log_return_quantiles") or {}
        pq = f.get("price_quantiles") or {}
        rows.append({"horizon": h, "as_of_utc": utc_iso(f.get("as_of")), "target_utc": utc_iso(f["as_of"] + f["horizon_seconds"]) if f.get("as_of") else None,
                     "status": f.get("status"), "reason": f.get("reason"), "data_age_seconds": f.get("data_age_seconds"),
                     "calibration": f.get("calibration"), "samples": f.get("samples"),
                     "calib_coverage_q05_q95": f.get("calib_coverage_q05_q95"), "p_down": f.get("p_down"), "p_flat": f.get("p_flat"), "p_up": f.get("p_up"),
                     "median_log_return": f.get("median_log_return"), "volatility_h": f.get("volatility_h"), "vol_scale": f.get("vol_scale"),
                     **{f"logret_{k}": v for k, v in q.items()}, **{f"price_{k}": v for k, v in pq.items()}, "engine": f.get("engine")})
    prov.update(bars_used=len(pts), last_bar_open_utc=pts[-1][0])
    return Collected([Dataset("forecasts", rows, "DERIVED", time_columns={"as_of_utc": "UTC", "target_utc": "UTC"},
                              description="rozkład zmian 24–72 h (kwantyle) – nie pewna cena")], prov)


def association_rules(ctx: SourceContext, timeframe: str = "H1", horizon: int = 24) -> Collected:
    from datetime import datetime as _dt

    from ..ml import association_rules as AR
    prov = {"source": "ml.association_rules (event_bits + train + assess, zamknięte świece MT5)", "schema": AR.SCHEMA, "timeframe": timeframe,
            "horizon_bars": horizon, "mode": "OBSERVE"}
    bars, why = _mt5_series(ctx, timeframe, 5000)
    if bars is None:
        return _unavailable(why, prov)
    rows = [b for b in bars if b.get("open_utc")]
    if not rows:
        return Collected([Dataset("rules", [], "DERIVED"), Dataset("assessment", [], "DERIVED")], prov, status="UNAVAILABLE",
                         notes=["TIME_OFFSET_UNVERIFIED: zdarzenia sesyjne wymagają czasu UTC"])
    rows = [{**b, "hour": _dt.fromisoformat(b["open_utc"].replace("Z", "+00:00")).hour} for b in rows]
    masks = AR.event_bits(rows)
    h = max(1, min(int(horizon), 200))
    m = AR.train(masks, AR.labels([float(b["c"]) for b in rows], h, 0.0), scope={"timeframe": timeframe, "horizon": h})
    rules = [{**{k: v for k, v in r.items()}} for r in m.get("rules", [])]
    cur = masks[-1] if masks else None
    assess = []
    for d in ("LONG", "SHORT"):
        a = AR.assess(m, cur, d)
        assess.append({"as_of_bar_open_utc": rows[-1]["open_utc"], "direction": d, "action": a.get("action"), "reason": a.get("reason"),
                       "candidate_direction_supported": a.get("candidate_direction_supported"), "matched_rules": a.get("matched_rules"),
                       "current_mask": cur, "current_events": [AR.CATALOG[k] for k in range(len(AR.CATALOG)) if cur is not None and cur >> k & 1]})
    prov.update(status=m.get("status"), n_labeled=m.get("n_labeled"), base_up=m.get("base_up"), base_down=m.get("base_down"), bars=len(rows))
    return Collected([Dataset("rules", rules, "DERIVED", description="reguły asocjacyjne (filtr OBSERVE)"),
                      Dataset("assessment", assess, "DERIVED", time_columns={"as_of_bar_open_utc": "UTC"})], prov)


def shadow_journal(ctx: SourceContext, kind: str) -> Collected:
    """Results of PT evaluations / DT rankings produced through the API since the app start (journal published by wf32_routes)."""
    j = ctx.wf32.get("shadow_journal")
    label = {"pt": "evaluation.pt_skill.evaluate (POST /api/v1/models/pt/evaluate)",
             "dt": "ml.dt_ranker.rank (POST /api/v1/models/dt-ranker/rank, tryb SHADOW)"}[kind]
    prov = {"source": label, "journal": "pamięć działającej aplikacji (ostatnie wyniki od startu)", "mode": "SHADOW / OBSERVE"}
    if j is None:
        return _unavailable("APP_NOT_RUNNING: wyniki są w dzienniku działającej aplikacji", prov)
    rows = []
    for e in [x for x in list(j) if x.get("kind") == kind]:
        r = e.get("result") or {}
        if kind == "pt":
            rows.append({"at_utc": utc_iso(e.get("at")), "inputs_sha256": e.get("inputs_sha256"), "n_pairs": e.get("n"), "profile": e.get("profile"),
                         **{k: (v if not isinstance(v, (dict, list)) else v) for k, v in r.items()}})
        else:
            rows.append({"at_utc": utc_iso(e.get("at")), "inputs_sha256": e.get("inputs_sha256"), "candidates": e.get("n"), "decision": r.get("decision"),
                         "selected_candidate_id": r.get("selected_candidate_id"), "reason_codes": r.get("reason_codes"), "mode": r.get("mode"),
                         "apply_to_selection": r.get("apply_to_selection"), "ranked_candidates": r.get("ranked_candidates")})
    name = "pt_results" if kind == "pt" else "dt_rankings"
    return Collected([Dataset(name, rows, "DERIVED", time_columns={"at_utc": "UTC"})], prov)


# ================================================================================================ TASK 017 - Telegram account center
def telegram_center(ctx: SourceContext) -> Collected:
    d = ctx.data_dir / "telegram_account"
    cfg = _read_json(d / "telegram_account.json") or {}
    st = _read_json(d / "telegram_account_state.json") or {}
    tpl = _read_json(d / "account_templates.json") or {}
    acct = cfg.get("bound_account_key")
    prov = {"source": "notify.account_center.AccountCenter (pliki <dane>/telegram_account/*.json, tylko odczyt)",
            "token": "NIE EKSPORTOWANY (SecretStore)", "account_ids": "zamaskowane (server:***123)", "files_present": d.is_dir()}

    def m(s):
        if not isinstance(s, str):
            return s
        return s.replace(acct, mask_account(acct)) if acct else s
    from ..notify.account_center import DEFAULTS
    conf = [{"key": k, "value": (mask_account(v) if k == "bound_account_key" else v), "default": DEFAULTS.get(k), "stored": k in cfg}
            for k, v in {**DEFAULTS, **cfg}.items()] if (cfg or st) else []
    outbox = [{"dedup_key": m(x.get("key")), "text": m(x.get("text")), "state": "PENDING"} for x in st.get("outbox") or []]
    sent = [{"dedup_key": m(k), "state": "SENT"} for k in st.get("sent_keys") or []]
    # 1.46: an entry volume never seen (position opened before the baseline) is null, not 0
    pos = [{"position_id": pid, "side": p.get("side"), "volume_in": p.get("vin") if p.get("vin_known", bool(p.get("vin"))) else None,
            "volume_out": p.get("vout"), "net": p.get("net")}
           for pid, p in (st.get("positions") or {}).items()]
    seen = [{"deal_ticket": t} for t in st.get("cursor") or []]
    meta = [{"baseline_at_utc": utc_iso(st.get("baseline_at")), "paused": st.get("paused"), "outbox_pending": len(outbox), "sent_keys": len(sent),
             "cursor_size": len(seen), "custom_templates": sorted(tpl)}] if (cfg or st) else []
    ds = [Dataset("config", conf, "CONFIG"), Dataset("outbox_pending", outbox, "REAL", description="kolejka wiadomości o zdarzeniach rachunku (bez tokenu)"),
          Dataset("sent_events", sent, "REAL", description="klucze deduplikacji wysłanych zdarzeń / raportów"),
          Dataset("positions_state", pos, "REAL", description="stan pozycji używany do rozpoznania open / partial / close"),
          Dataset("seen_deals", seen, "REAL", description="kursor: deale już obsłużone (linia bazowa)"),
          Dataset("center_state", meta, "STATE", time_columns={"baseline_at_utc": "UTC"})]
    status = "OK" if (cfg or st) else "EMPTY"
    return Collected(ds, prov, status=status, notes=[] if (cfg or st) else ["NO_CENTER_FILES: centrum Telegram nigdy nie było konfigurowane"])


# ================================================================================================ TASK 013 - bootstrap state
def bootstrap_state(ctx: SourceContext) -> Collected:
    from ..bootstrap import COMPONENTS, topo_order
    st = _read_json(ctx.data_dir / "bootstrap_state.json")
    prov = {"source": "bootstrap.Bootstrap (plik <dane>/bootstrap_state.json, tylko odczyt)", "file_present": st is not None,
            "profile": (st or {}).get("profile"), "policy": {"heavy_parallel": False, "training": "MANUAL_ONLY", "execution_changes": False}}
    comps = {c[0]: c for c in COMPONENTS}
    rows = []
    for cid in (topo_order() if st is not None else []):
        c = comps[cid]
        s = ((st or {}).get("components") or {}).get(cid) or {}
        rows.append({"order": len(rows) + 1, "id": cid, "kind": c[1], "deps": list(c[2]), "required_for_core": c[3], "heavy": c[4],
                     "state": s.get("state") or "PENDING", "detail": s.get("detail"), "at_utc": utc_iso(s.get("at"))})
    return Collected([Dataset("components", rows, "STATE", time_columns={"at_utc": "UTC"})], prov, status="OK" if st is not None else "EMPTY",
                     notes=[] if st is not None else ["NO_STATE_FILE: bootstrap nie był uruchamiany (tryb demo / PMW_BOOTSTRAP=0 albo nowa instalacja)"])


# ================================================================================================ TASK 019 - TraderLifeGame backup
TLG_KINDS = {"meta": "STATE", "profile": "GAME", "events": "GAME", "xp_ledger": "GAME", "gold_ledger": "GAME", "skills": "GAME", "quest_claims": "GAME",
             "academy": "GAME", "quiz": "GAME", "journal": "USER_NOTE", "notes": "USER_NOTE", "sim_sessions": "SIMULATED", "sim_trades": "SIMULATED",
             "inventory": "GAME", "coach_memory": "USER_NOTE"}
TLG_EPOCH_COLS = ("ts", "created_at", "updated_at", "unlocked_at", "completed_at", "acquired_at", "finished_at")


def trader_life_game(ctx: SourceContext) -> Collected:
    dbp = ctx.data_dir / "trader_life_game" / "game.sqlite"
    prov = {"source": "trader_life_game.GameService (SQLite <dane>/trader_life_game/game.sqlite, tylko odczyt)", "database": "game.sqlite",
            "purpose": "kopia zapasowa użytkownika (import: python -m masterquo import-trader-life-game)",
            "separation": "dane gry, notatki użytkownika i symulator (wirtualne) w osobnych plikach; dziennik = adnotacje nad dealami MT5"}
    if not dbp.exists():
        return Collected([Dataset(t, [], k) for t, k in TLG_KINDS.items()], {**prov, "database_present": False}, status="EMPTY",
                         notes=["NO_GAME_DATABASE: gra nie była uruchamiana"])
    ds = []
    with ReadOnlyDB(dbp) as db:
        present = set(db.tables())
        sv = next((r["v"] for r in db.query("SELECT v FROM meta WHERE k='schema_version'")), None) if "meta" in present else None
        prov["game_schema_version"] = sv
        for t, kind in TLG_KINDS.items():
            if t not in present:
                ds.append(Dataset(t, [], kind))
                continue
            cols = db.columns(t)
            rows = []
            for r in db.query(f'SELECT * FROM "{t}" ORDER BY rowid'):
                for c in TLG_EPOCH_COLS:
                    if c in r:
                        r[f"{c}_utc"] = utc_iso(r[c])
                rows.append(r)
            tc = {c: "UTC_EPOCH_SECONDS" for c in TLG_EPOCH_COLS if c in cols}
            tc.update({f"{c}_utc": "UTC" for c in TLG_EPOCH_COLS if c in cols})
            ds.append(Dataset(t, rows, kind, columns=cols + [f"{c}_utc" for c in TLG_EPOCH_COLS if c in cols], time_columns=tc))
    return Collected(ds, prov)


# ================================================================================================ persistent stores without a bulk export (X6 inventory)
# store -> (file relative to <data>, tables NEVER exported). Excluded: personal data and audit of settings (account logins, AI questions / memory,
# Telegram dedup keys, settings change log) - "no personal data beyond need". Secrets are never in these stores (SecretStore is a separate file).
STORES = {
    "main": ("masterquo.sqlite", {"accounts_seen", "account_prefs", "agent_runs", "agent_memory", "notifications_sent", "settings_audit"}),
    "svp": ("svp/svp.sqlite", set()),
    "indicators": ("indicators/indicators.sqlite", set()),          # book_snapshots = DOM snapshots MT5, spread_samples, AVWAP anchors, DXY bars
    "baskets": ("baskets/ledger.sqlite", set()),
    "zones": ("zones/zones.sqlite", set()),
    "market-zones": ("zones/market_zones.sqlite", set()),
    "evaluation": ("evaluation/ledger.sqlite", set()),
    "mm": ("mm/ledger.sqlite", set()),
    "quant": ("quant/ledger.sqlite", set()),
    "trainhub": ("trainhub/jobs.sqlite", set()),
    "news": ("m04n/M04N_STATE.sqlite", set()),
}
MODE_KINDS = {"PAPER": "VIRTUAL", "AUTO_DEMO": "DEMO", "AUTO_LIVE": "REAL"}
TABLE_KINDS = {"paper_account": "VIRTUAL", "schema_migrations": "STATE", "book_snapshots": "PROVIDER", "spread_samples": "PROVIDER",
               "dxy_bars": "PROVIDER", "articles": "PROVIDER", "calendar": "PROVIDER", "observations": "PROVIDER"}
ACCOUNT_COLUMNS = ("account_key", "account")


def _time_labels(db: ReadOnlyDB, table: str, cols: list[str]) -> dict:
    """A column is labelled UTC only when its stored values are ISO-8601 strings with an explicit UTC designator (checked on data)."""
    out = {}
    for c in cols:
        if not (c.endswith("_at") or c.endswith("_utc") or c in ("ts", "at", "t", "as_of", "bar_t", "anchor_time")):
            continue
        r = db.query(f'SELECT "{c}" AS v FROM "{table}" WHERE "{c}" IS NOT NULL LIMIT 1')
        v = r[0]["v"] if r else None
        if isinstance(v, str) and (v.endswith("Z") or v.endswith("+00:00")) and utc_iso(v):
            out[c] = "UTC"
    return out


def store_tables(ctx: SourceContext, store: str = "main", tables: list[str] | None = None) -> Collected:
    if store not in STORES:
        raise ValueError(f"store: {', '.join(STORES)}")
    rel, excluded = STORES[store]
    dbp = ctx.data_dir / rel
    prov = {"source": f"SQLite <dane>/{rel} (tylko odczyt, URI mode=ro)", "store": store, "excluded_tables": sorted(excluded),
            "excluded_reason": "dane osobowe / audyt ustawień – poza zakresem eksportu", "account_ids": "zamaskowane (server:***123)",
            "split": "tabele z kolumną mode / exec_mode: osobny plik na tryb (PAPER = VIRTUAL, AUTO_DEMO = DEMO, AUTO_LIVE = REAL, inne = DERIVED); "
                     "kolumna synthetic = 1 -> osobny plik SYNTHETIC",
            "time_policy": "kolumny czasu oznaczone UTC tylko gdy wartości mają jawne Z / +00:00; liczbowe znaczniki czasu bez konwersji (strefa wg modułu)"}
    if not dbp.exists():
        return Collected([], {**prov, "database_present": False}, status="EMPTY", notes=[f"NO_DATABASE: brak <dane>/{rel}"])
    db = ReadOnlyDB(dbp)
    try:
        allowed = [t for t in db.tables() if t not in excluded]
        sel = list(tables) if tables else allowed
        bad = [t for t in sel if t not in allowed]
        if bad:
            raise ValueError(f"tables: {bad} (dozwolone w '{store}': {', '.join(allowed)})")
        datasets, used = [], set()

        def rows_of(table, cols, where, args):
            def gen():
                cur = db.conn.execute(f'SELECT * FROM "{table}"{where} ORDER BY rowid', args)
                for r in cur:
                    d = dict(r)
                    for c in ACCOUNT_COLUMNS:
                        if c in d and isinstance(d[c], str):
                            d[c] = mask_account(d[c])
                    yield d
            return gen()

        for t in sel:
            cols = db.columns(t)
            tl = _time_labels(db, t, cols)
            split_col = "mode" if "mode" in cols else ("exec_mode" if "exec_mode" in cols else None)
            if split_col:
                vals = [r["v"] for r in db.query(f'SELECT DISTINCT "{split_col}" AS v FROM "{t}" ORDER BY v')]
                for v in vals:
                    name = f"{_slug(t)}__{_slug(v) if v is not None else 'no_mode'}"
                    if name in used:
                        continue
                    used.add(name)
                    where, args = (f' WHERE "{split_col}" = ?', (v,)) if v is not None else (f' WHERE "{split_col}" IS NULL', ())
                    datasets.append(Dataset(name, rows_of(t, cols, where, args), MODE_KINDS.get(str(v), "DERIVED"), columns=cols, time_columns=tl,
                                            description=f"{t} ({split_col} = {v})"))
                if not vals:
                    datasets.append(Dataset(_slug(t), [], TABLE_KINDS.get(t, "DERIVED"), columns=cols, time_columns=tl, description=t))
            elif "synthetic" in cols:
                datasets.append(Dataset(_slug(t), rows_of(t, cols, ' WHERE COALESCE("synthetic", 0) = 0', ()), TABLE_KINDS.get(t, "DERIVED"),
                                        columns=cols, time_columns=tl, description=f"{t} (dane rzeczywiste rynku)"))
                datasets.append(Dataset(f"{_slug(t)}__synthetic", rows_of(t, cols, ' WHERE "synthetic" = 1', ()), "SYNTHETIC", columns=cols,
                                        time_columns=tl, description=f"{t} (DANE SYNTETYCZNE)"))
            else:
                datasets.append(Dataset(_slug(t), rows_of(t, cols, "", ()), TABLE_KINDS.get(t, "DERIVED"), columns=cols, time_columns=tl, description=t))
        prov["tables"] = sel
    except BaseException:
        db.close()
        raise
    return Collected(datasets, prov, cleanup=[db.close])
