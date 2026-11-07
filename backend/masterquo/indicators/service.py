"""IndicatorService (PMW-IND-SERVICE-1) - live indicator snapshot of the active instrument. Analytical only: reads bars / quotes /
market depth through the bridge, never sends or modifies orders.

* Loop (1 s): quote sampled for the spread reference on a fixed clock; market depth polled (if enabled and the symbol has DOM);
  the full snapshot is recomputed once per new CLOSED M1 bar (and on demand).
* Persistence (data/indicators/indicators.sqlite): spread samples, manual AVWAP anchors, anchor versions, the DXY H1 source archive and
  (optionally) book snapshots - replay / dataset export read the same rows. A restored snapshot is never presented as fresh.
* context(view, bars) -> MarketView.context: {"indicators": compact view, "dxy": {status, last_available_at, ...}}. Strategies read it
  as optional context; no strategy gets a new mandatory condition from this service.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from . import avwap as AV
from . import contract as C
from . import dxy as DX
from . import ofi as OF
from . import profile as PF
from . import semivar as SV
from . import spread as SP

VERSION = "PMW-IND-SERVICE-1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS spread_samples (id INTEGER PRIMARY KEY AUTOINCREMENT, instrument TEXT, symbol TEXT, t REAL, spread REAL,
  session TEXT, slot INTEGER, instance TEXT, instance_start REAL);
CREATE INDEX IF NOT EXISTS ix_spread_inst ON spread_samples(instrument, symbol, session, slot, t);
CREATE TABLE IF NOT EXISTS avwap_anchors (anchor_id TEXT PRIMARY KEY, instrument TEXT, symbol TEXT, tf TEXT, source_time TEXT,
  created_at TEXT, label TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS anchor_versions (key TEXT PRIMARY KEY, anchor_id TEXT, version INTEGER, changed_at TEXT);
CREATE TABLE IF NOT EXISTS dxy_bars (symbol TEXT, open_utc TEXT, o REAL, h REAL, l REAL, c REAL, available_at TEXT, basis TEXT,
  PRIMARY KEY(symbol, open_utc));
CREATE TABLE IF NOT EXISTS book_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, t REAL, bids TEXT, asks TEXT);
CREATE INDEX IF NOT EXISTS ix_book_sym ON book_snapshots(symbol, t);
"""


def _default_dir() -> Path:
    from ..paths import data_dir
    return data_dir() / "indicators"


class IndicatorService:
    def __init__(self, cfg_store, bridge, *, zones=None, bus=None, log=None, data_dir: Path | None = None, clock=time.time):
        self.cfg_store, self.bridge, self.zones, self.bus, self.log, self.clock = cfg_store, bridge, zones, bus, log, clock
        d = Path(data_dir or _default_dir())
        d.mkdir(parents=True, exist_ok=True)
        self.dir = d
        self.db = sqlite3.connect(str(d / "indicators.sqlite"), check_same_thread=False, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.snap: dict | None = None
        self.last_m1: str | None = None
        self._last_sample = 0.0
        self._last_book = 0.0
        self.intensity = SP.Intensity()
        self.book = OF.BookAdapter(bridge, recorder=self._record_book)
        self.ofi = OF.OFIAccumulator()
        self.state = {"version": VERSION, "runs": 0, "last_error": None, "last_ms": None, "mode": "ANALYTICAL_ONLY", "spread_samples": 0}

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="indicators", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.book.close()
        except Exception:  # noqa: BLE001
            pass

    def _cfg(self):
        return self.cfg_store.get().indicators

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - analytical loop never stops the bot
                self.state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]

    def tick(self, now: float | None = None) -> None:
        cfg = self._cfg()
        if not cfg.enabled:
            return
        now = now if now is not None else self.clock()
        q = getattr(self.bridge, "quote", None)
        self.intensity.observe(q, now)
        if q and now - self._last_sample >= cfg.spread_sample_s:
            self._last_sample = now
            self.sample_spread(q, now)
        if cfg.book_enabled and now - self._last_book >= cfg.book_period_s:
            self._last_book = now
            self.poll_book()
        rows = self.bridge.bars("M1", include_forming=False)
        t = rows[-1].get("open_utc") if rows else None
        if t and t != self.last_m1:
            self.last_m1 = t
            self.refresh(now)

    # ------------------------------------------------------------------ inputs
    def _inst(self) -> tuple[str, str, float, dict]:
        app = self.cfg_store.get()
        info = getattr(self.bridge, "symbol_info", None) or {}
        tick = float(info.get("trade_tick_size") or info.get("point") or 0.01)
        return app.assets.active, app.mt5.symbol, tick, {"tick": tick, "digits": info.get("digits")}

    def _profile_id(self) -> str:
        app = self.cfg_store.get()
        return app.zones.session_profile.get(app.assets.active) or "LAB_XAU_REFERENCE_V1"

    def sample_spread(self, q: dict, now: float) -> None:
        inst, sym, _, _ = self._inst()
        if q.get("bid") is None or q.get("ask") is None or (q.get("symbol") and q["symbol"] != sym):
            return
        ss = SP.session_slot(self._profile_id(), now, self._cfg().spread_slot_minutes)
        with self._lock:
            self.db.execute("INSERT INTO spread_samples(instrument, symbol, t, spread, session, slot, instance, instance_start) VALUES (?,?,?,?,?,?,?,?)",
                            (inst, sym, now, float(q["ask"]) - float(q["bid"]), ss["session"], ss["slot"], ss["instance"], ss["instance_start"]))
        self.state["spread_samples"] += 1

    def _spread_samples(self, inst: str, sym: str, session: str, slot: int) -> list[dict]:
        rows = self.db.execute("SELECT t, spread, session, slot, instance, instance_start FROM spread_samples WHERE instrument=? AND symbol=? "
                               "AND session=? AND slot=? ORDER BY t DESC LIMIT 20000", (inst, sym, session, slot)).fetchall()
        return [dict(r) for r in rows]

    def _record_book(self, sym: str, book: dict) -> None:
        if not self._cfg().book_record:
            return
        with self._lock:
            self.db.execute("INSERT INTO book_snapshots(symbol, t, bids, asks) VALUES (?,?,?,?)",
                            (sym, book["t"], json.dumps(book["bids"][:20]), json.dumps(book["asks"][:20])))

    def poll_book(self) -> None:
        _, sym, _, _ = self._inst()
        self.book.ensure(sym)
        b = self.book.poll()
        cfg = self._cfg()
        self.ofi.period_s, self.ofi.max_gap_s = cfg.book_period_s, cfg.book_max_gap_s
        self.ofi.add(b, key=(sym, self.book.epoch))

    def _archive_dxy(self, sym: str, bars: list[dict]) -> None:
        with self._lock:
            self.db.executemany("INSERT OR REPLACE INTO dxy_bars(symbol, open_utc, o, h, l, c, available_at, basis) VALUES (?,?,?,?,?,?,?,?)",
                                [(sym, b["open_utc"], b["o"], b["h"], b["l"], b["c"], b.get("available_at"), b.get("basis"))
                                 for b in bars if b.get("closed") and b.get("open_utc")])

    # ------------------------------------------------------------------ anchors
    def add_manual_anchor(self, tf: str, source_time: str, label: str | None = None) -> dict:
        inst, sym, _, _ = self._inst()
        created = C.iso(self.clock())
        a = AV.manual_anchor(source_time, created, label)
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO avwap_anchors(anchor_id, instrument, symbol, tf, source_time, created_at, label, active) "
                            "VALUES (?,?,?,?,?,?,?,1)", (a["anchor_id"], inst, sym, tf, a["source_time"], created, label))
        return a

    def remove_manual_anchor(self, anchor_id: str) -> bool:
        with self._lock:
            n = self.db.execute("UPDATE avwap_anchors SET active=0 WHERE anchor_id=?", (anchor_id,)).rowcount
        return n > 0

    def manual_anchors(self, tf: str | None = None) -> list[dict]:
        inst, sym, _, _ = self._inst()
        q = "SELECT * FROM avwap_anchors WHERE active=1 AND instrument=? AND symbol=?" + (" AND tf=?" if tf else "") + " ORDER BY created_at"
        return [dict(r) for r in self.db.execute(q, (inst, sym, tf) if tf else (inst, sym)).fetchall()]

    def _version(self, key: str, anchor_id: str | None) -> int:
        if anchor_id is None:
            return 0
        with self._lock:
            r = self.db.execute("SELECT anchor_id, version FROM anchor_versions WHERE key=?", (key,)).fetchone()
            if r and r["anchor_id"] == anchor_id:
                return int(r["version"])
            v = (int(r["version"]) + 1) if r else 1
            self.db.execute("INSERT OR REPLACE INTO anchor_versions(key, anchor_id, version, changed_at) VALUES (?,?,?,?)",
                            (key, anchor_id, v, C.iso(self.clock())))
            return v

    # ------------------------------------------------------------------ compute
    def compute(self, as_of: float, *, with_lines: bool = False, persist_versions: bool = True) -> dict:
        """Pure snapshot of every indicator as known at as_of (bars cut at as_of inside each engine)."""
        cfg = self._cfg()
        inst, sym, tick, meta = self._inst()
        pid = self._profile_id()
        out = {"version": VERSION, "contract": C.VERSION, "instrument": inst, "broker_symbol": sym, "as_of": C.iso(as_of), "avwap": {}}
        m1 = [b for b in self.bridge.bars("M1", include_forming=False) if b.get("open_utc")]
        atr_m1 = AV.atr([b for b in m1 if C.ts(b["open_utc"]) + 60 <= as_of + 1e-6])
        for tf in cfg.avwap_tfs:
            bars = self.bridge.bars(tf, include_forming=False)[-cfg.avwap_history_bars:]
            from ..timeutil import TF_SECONDS
            anchors = {"SESSION": AV.session_anchor(pid, as_of, cfg.avwap_session),
                       "EVENT": AV.event_anchor(bars, TF_SECONDS[tf], as_of, tick=tick, kinds=tuple(cfg.avwap_event_kinds))}
            res = {}
            for mode, a in anchors.items():
                ver = self._version(f"{inst}|{sym}|{tf}|{mode}", a and a["anchor_id"]) if persist_versions else 1
                res[mode] = AV.compute(bars, tf, a, as_of=as_of, instrument=inst, broker_symbol=sym, price_mode=cfg.avwap_price,
                                       slope_bars=cfg.avwap_slope_bars, retest_tol_atr=cfg.avwap_retest_tol_atr, instrument_meta=meta,
                                       with_line=with_lines, anchor_version=ver)
            man = []
            for r in self.manual_anchors(tf):
                a = {"mode": "MANUAL", "kind": r["label"] or "MANUAL", "source_time": r["source_time"], "confirmed_at": r["created_at"],
                     "anchor_id": r["anchor_id"]}
                man.append(AV.compute(bars, tf, a, as_of=as_of, instrument=inst, broker_symbol=sym, price_mode=cfg.avwap_price,
                                      slope_bars=cfg.avwap_slope_bars, retest_tol_atr=cfg.avwap_retest_tol_atr, instrument_meta=meta,
                                      with_line=with_lines))
            res["MANUAL"] = man
            out["avwap"][tf] = res
        out["semivar"] = SV.compute(m1, "M1", as_of=as_of, instrument=inst, broker_symbol=sym, windows=tuple(cfg.semivar_windows),
                                    gap_factor=cfg.semivar_gap_factor, gap_mode=cfg.semivar_gap_mode)
        q = getattr(self.bridge, "quote", None)
        ss = SP.session_slot(pid, as_of, cfg.spread_slot_minutes)
        out["spread"] = SP.compute(q, self._spread_samples(inst, sym, ss["session"], ss["slot"]), now=as_of, instrument=inst, broker_symbol=sym,
                                   profile_id=pid, tick=tick, atr_v=atr_m1, slot_minutes=cfg.spread_slot_minutes, min_sessions=cfg.spread_min_sessions,
                                   max_sessions=cfg.spread_max_sessions, intensity=self.intensity.view(), sample_every_s=cfg.spread_sample_s)
        app = self.cfg_store.get()
        dsym = app.mt5.dxy_symbol
        dbars = self.bridge.bars("DXY_H1", include_forming=False)[-cfg.dxy_history_bars:] if dsym else []
        if dsym and dbars:
            self._archive_dxy(dsym, dbars)
        h1 = self.bridge.bars("H1", include_forming=False)[-cfg.dxy_history_bars:]
        out["dxy"] = DX.compute(h1, dbars, as_of=as_of, instrument=inst, broker_symbol=sym, dxy_symbol=dsym,
                                dxy_status=getattr(self.bridge, "dxy_status", None), windows=tuple(cfg.dxy_windows), min_obs=cfg.dxy_min_obs,
                                max_age_s=cfg.dxy_max_age_s)
        zm = self.zones.current() if self.zones is not None else None
        price = float(m1[-1]["c"]) if m1 else None
        m5 = [b for b in self.bridge.bars("M5", include_forming=False) if b.get("open_utc")]
        out["profile"] = PF.compute(zm, price, AV.atr(m5), instrument=inst, broker_symbol=sym)
        if cfg.book_enabled:
            out["microstructure"] = OF.compute(self.book.last, self.ofi, instrument=inst, broker_symbol=sym, status=self.book.status,
                                               reason=self.book.reason, levels=cfg.book_levels, now=as_of, max_age_s=max(5.0, 5 * cfg.book_period_s))
        else:
            out["microstructure"] = C.result("MICROSTRUCTURE", OF.VERSION, instrument=inst, broker_symbol=sym, source="MT5_MARKET_BOOK(broker)",
                                             timeframe=None, status="DISABLED", reason="book_enabled=false")
        out["snapshot_id"] = "INDS-" + hashlib.sha256(json.dumps({k: (v.get("snapshot_id") if isinstance(v, dict) else None)
                                                                   for k, v in out.items()}, sort_keys=True, default=str).encode()).hexdigest()[:16]
        return out

    def refresh(self, now: float | None = None) -> dict:
        t0 = time.perf_counter()
        s = self.compute(now if now is not None else self.clock())
        with self._lock:
            self.snap = s
        self.state.update(runs=self.state["runs"] + 1, last_ms=round((time.perf_counter() - t0) * 1000, 1), last_error=None, as_of=s["as_of"])
        if self.bus is not None:
            try:
                self.bus.publish("indicators", self.compact(s))
            except Exception:  # noqa: BLE001
                pass
        return s

    def current(self) -> dict | None:
        with self._lock:
            return self.snap

    def current_or_refresh(self) -> dict | None:
        if self.snap is not None:
            return self.snap
        try:
            return self.refresh()
        except Exception as exc:  # noqa: BLE001
            self.state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            return None

    # ------------------------------------------------------------------ outputs
    @staticmethod
    def compact(s: dict | None) -> dict:
        """Small view for MarketView.context, agent snapshot and the WS event: status + main values per indicator."""
        if not s:
            return {"status": "NO_SNAPSHOT"}

        def sv(r, keys):
            return {"status": r.get("status"), "reason": r.get("reason"), **{k: (r.get("values") or {}).get(k) for k in keys}} if r else None
        av = {}
        for tf, modes in (s.get("avwap") or {}).items():
            for mode in ("SESSION", "EVENT"):
                r = modes.get(mode)
                if r:
                    av[f"{tf}_{mode}"] = dict(sv(r, ("avwap", "sigma", "distance_atr", "distance_sigma", "slope_atr", "side", "last_event")),
                                              anchor=(r.get("anchor") or {}).get("kind"), anchor_version=(r.get("anchor") or {}).get("version"))
        return {"version": s.get("version"), "as_of": s.get("as_of"), "snapshot_id": s.get("snapshot_id"), "avwap": av,
                "semivar": sv(s.get("semivar"), ("downside_share_20", "downside_share_60", "rv_20", "rv_60")),
                "spread": sv(s.get("spread"), ("spread_price", "spread_ticks", "spread_atr", "percentile", "quote_age_s", "unusual")),
                "dxy": sv(s.get("dxy"), ("corr_24", "corr_72", "corr_240", "beta_72", "resid_z_72", "joint_obs", "age_s", "sign")),
                "profile": sv(s.get("profile"), ("dev_dist_poc_atr", "dev_va_position", "prev_va_position", "relative_volume",
                                                 "interval_relative_volume", "poc_migration_bins", "dev_shape")),
                "microstructure": sv(s.get("microstructure"), ("best_imbalance", "depth_imbalance", "ofi_window", "microprice_dev"))}

    def context(self, view, bars: dict) -> dict:
        s = self.current()
        return {"indicators": self.compact(s), "dxy": DX.feature_context((s or {}).get("dxy"))}

    def status(self) -> dict:
        s = self.current()
        return {**self.state, "book": {"status": self.book.status, "reason": self.book.reason, "symbol": self.book.symbol,
                                       "ofi": self.ofi.view()},
                "summary": {k: (v.get("status") if isinstance(v, dict) else None) for k, v in (s or {}).items()
                            if k in ("semivar", "spread", "dxy", "profile", "microstructure")},
                "note": "wskaźniki analityczne – same nie blokują strategii; pasma σ nie są przedziałami prawdopodobieństwa"}

    def chart(self, tf: str) -> dict:
        """Lines for the chart (backend values, the panel only draws)."""
        s = self.compute(self.clock(), with_lines=True, persist_versions=False)
        return {"tf": tf, "as_of": s["as_of"], "avwap": (s["avwap"] or {}).get(tf) or {}, "dxy": s["dxy"]}

    def manifest(self) -> dict:
        """Source archive manifest (spread samples, DXY bars, book snapshots) for dataset export / replay."""
        def one(q):
            r = self.db.execute(q).fetchone()
            return dict(r) if r else {}
        return {"version": VERSION, "contract": C.VERSION, "db": str(self.dir / "indicators.sqlite"),
                "spread_samples": one("SELECT COUNT(*) n, MIN(t) t0, MAX(t) t1, COUNT(DISTINCT instance) instances FROM spread_samples"),
                "dxy_bars": one("SELECT COUNT(*) n, MIN(open_utc) t0, MAX(open_utc) t1 FROM dxy_bars"),
                "book_snapshots": one("SELECT COUNT(*) n, MIN(t) t0, MAX(t) t1 FROM book_snapshots"),
                "algorithms": {"avwap": AV.VERSION, "spread": SP.VERSION, "semivar": SV.VERSION, "dxy": DX.VERSION, "profile": PF.VERSION,
                               "ofi": OF.VERSION}}

    def prune(self, keep_days: int | None = None) -> None:
        cut = self.clock() - 86400 * (keep_days or self._cfg().book_keep_days)
        with self._lock:
            self.db.execute("DELETE FROM book_snapshots WHERE t < ?", (cut,))
