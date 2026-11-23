"""Multi-market plane (Apollo23 TASK 003 + FOMO Stock Perps addendum): instrument master, FOMO 101 seed universe, capability registry,
three market bridges on one shared contract, ten timeframes (incl. deterministic M10) and per-market strategy basket TEMPLATES.

Status policy from the later tasks (TASK 020-024 override TASK 003's activation wording):
  FOREX_MT5           active (existing path)                      CRYPTO (Hyperliquid core perps)  data + MANUAL_ONLY tickets
  INDICES             RESEARCH_ONLY (read-only data, no orders)   FOMO_STOCK_PERPS (xyz HIP-3)     RESEARCH_ONLY (read-only data, no orders)
Identity = (provider, venue/dex, native_symbol, asset_id, metadata_version); a ticker is only a display alias. The FOMO CSV is a seed /
reference snapshot - runtime venue metadata is the authority (ACTIVE / NOT_FOUND / DELISTED / NOT_VERIFIED). Stock perps are synthetic
derivatives, not shares. Charts never select an execution venue. No order method exists in this module.
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

SEED_FILE = Path(__file__).parent / "data" / "fomo_stock_perps_101_2026-11-04.csv"
SEED_DATE = "2026-11-04"
TIMEFRAMES = ("1d", "8h", "4h", "1h", "30m", "15m", "10m", "5m", "3m", "1m")
TF_SECONDS = {"1d": 86400, "8h": 28800, "4h": 14400, "1h": 3600, "30m": 1800, "15m": 900, "10m": 600, "5m": 300, "3m": 180, "1m": 60}
HL_NATIVE_TF = {"1d", "8h", "4h", "1h", "30m", "15m", "5m", "3m", "1m"}          # Hyperliquid candleSnapshot intervals; 10m = resampled from 5m
RESAMPLE_FROM = {"10m": "5m"}
CAP_STATES = ("SUPPORTED", "UNSUPPORTED", "NOT_VERIFIED", "RESTRICTED", "DEGRADED")
INDEX_SYMBOLS = {"XYZ100", "SP500", "JP225", "KR200", "NIFTY", "IBOV", "VIX", "DXY", "VOL"}       # xyz synthetic index perps (by name)
NON_EQUITY_XYZ = {"GOLD", "SILVER", "CL", "COPPER", "NATGAS", "URANIUM", "ALUMINIUM", "PLATINUM", "PALLADIUM", "BRENTOIL", "CORN", "WHEAT", "TTF",
                  "HO", "JPY", "EUR", "GBP", "KRW", "H100"}
MARKETS = {
    "CRYPTO": {"provider": "HYPERLIQUID", "venue": "core", "product": "PERPETUAL", "status": "ACTIVE_DATA", "execution": "MANUAL_ONLY"},
    "INDICES": {"provider": "HYPERLIQUID", "venue": "xyz", "product": "SYNTHETIC_INDEX_PERP", "status": "RESEARCH_ONLY", "execution": "DISABLED",
                "not_merged_with": ["CME dated futures (brak providera)", "IG/broker CFD (brak zweryfikowanego providera)"]},
    "FOMO_STOCK_PERPS": {"provider": "HYPERLIQUID", "venue": "xyz", "product": "STOCK_PERPETUAL", "status": "RESEARCH_ONLY", "execution": "DISABLED",
                         "distribution": "FOMO (aplikacja) -> Trade[XYZ] na Hyperliquid HIP-3"},
}
STOCK_PERP_WARNINGS = ["Syntetyczny kontrakt perpetual – nie są to akcje (brak własności, dywidend i prawa głosu).",
                       "Ryzyka: funding, likwidacja, różnica oracle/mark, wycena poza godzinami rynku bazowego, ADL/delewarowanie, niska płynność, "
                       "ryzyko venue i deployera HIP-3."]


class UniverseError(ValueError):
    pass


def load_seed(path: Path = SEED_FILE) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [{"rank": int(r["rank_in_source_order"]), "symbol": r["symbol"].strip(), "group": r["alphabetical_group"], "category": r["fomo_category"],
             "snapshot_date": r["source_snapshot_date"], "instrument_type": r["instrument_type"]} for r in rows]


def validate_seed(rows: list[dict]) -> dict:
    syms = [r["symbol"] for r in rows]
    return {"count": len(rows), "unique": len(set(syms)), "nvda_present": "NVDA" in syms, "snapshot_dates": sorted({r["snapshot_date"] for r in rows}),
            "ok": len(rows) == 101 and len(set(syms)) == 101 and "NVDA" in syms and {r["snapshot_date"] for r in rows} == {SEED_DATE}}


@dataclass(frozen=True)
class Instrument:
    instrument_id: str            # immutable: provider|venue|native_symbol|asset_id
    provider: str
    venue: str
    native_symbol: str
    asset_id: int | None
    metadata_version: str
    display: str
    market: str
    product_type: str
    sz_decimals: int | None
    max_leverage: float | None
    status: str                   # ACTIVE | DELISTED | NOT_FOUND | NOT_VERIFIED
    execution: str                # MANUAL_ONLY | DISABLED

    def to_dict(self):
        return asdict(self)


def metadata_version(meta: dict) -> str:
    return hashlib.sha256(json.dumps(meta, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def hip3_asset_id(dex_index: int, index_in_meta: int) -> int:
    """Builder-deployed perp asset id = 100000 + perp_dex_index * 10000 + index_in_meta (Hyperliquid asset-id convention for HIP-3)."""
    return 100_000 + dex_index * 10_000 + index_in_meta


def classify_xyz(name: str) -> tuple[str, str]:
    base = name.split(":", 1)[-1]
    if base in INDEX_SYMBOLS:
        return "INDICES", "SYNTHETIC_INDEX_PERP"
    if base in NON_EQUITY_XYZ:
        return "OTHER_XYZ", "SYNTHETIC_COMMODITY_OR_FX_PERP"
    return "FOMO_STOCK_PERPS", "STOCK_PERPETUAL"


def build_instruments(core_meta: dict | None, xyz_meta: dict | None, dex_names: list) -> list[Instrument]:
    out: list[Instrument] = []
    if core_meta:
        mv = metadata_version(core_meta)
        for i, u in enumerate(core_meta.get("universe") or []):
            out.append(Instrument(f"HYPERLIQUID|core|{u['name']}|{i}", "HYPERLIQUID", "core", u["name"], i, mv, u["name"], "CRYPTO", "PERPETUAL",
                                  u.get("szDecimals"), u.get("maxLeverage"), "DELISTED" if u.get("isDelisted") else "ACTIVE", "MANUAL_ONLY"))
    if xyz_meta:
        mv = metadata_version(xyz_meta)
        try:
            dex_idx = list(dex_names).index("xyz")
        except ValueError:
            dex_idx = None
        for i, u in enumerate(xyz_meta.get("universe") or []):
            mkt, prod = classify_xyz(u["name"])
            aid = hip3_asset_id(dex_idx, i) if dex_idx is not None else None
            out.append(Instrument(f"HYPERLIQUID|xyz|{u['name']}|{aid}", "HYPERLIQUID", "xyz", u["name"], aid, mv, u["name"].split(":", 1)[-1], mkt, prod,
                                  u.get("szDecimals"), u.get("maxLeverage"), "DELISTED" if u.get("isDelisted") else "ACTIVE", "DISABLED"))
    return out


def resolve_seed(seed: list[dict], instruments: list[Instrument]) -> list[dict]:
    """Seed symbol -> exact xyz stock perp instrument; reports NOT_FOUND / DELISTED / NOT_VERIFIED, never fabricates a listing."""
    if not any(i.venue == "xyz" for i in instruments):
        return [{**r, "status": "NOT_VERIFIED", "instrument_id": None, "reason": "brak metadanych venue xyz"} for r in seed]
    by = {i.display: i for i in instruments if i.venue == "xyz"}
    out = []
    for r in seed:
        ins = by.get(r["symbol"])
        if ins is None:
            out.append({**r, "status": "NOT_FOUND", "instrument_id": None, "reason": f"brak xyz:{r['symbol']} w aktualnych metadanych"})
        else:
            out.append({**r, "status": "DELISTED" if ins.status == "DELISTED" else "ACTIVE", "instrument_id": ins.instrument_id,
                        "native_symbol": ins.native_symbol, "asset_id": ins.asset_id, "metadata_version": ins.metadata_version,
                        "market": ins.market})
    return out


def capabilities(ins: Instrument) -> dict:
    from ..orderflow.trades import capability as aggr_cap
    research = MARKETS.get(ins.market, {}).get("status") == "RESEARCH_ONLY"
    return {"ohlcv": "SUPPORTED", "trades": "SUPPORTED", "trades_aggressor": aggr_cap(ins.provider),
            "orderbook": "DEGRADED", "historical_depth": "UNSUPPORTED", "mark": "SUPPORTED", "oracle": "SUPPORTED", "funding": "SUPPORTED",
            "open_interest": "SUPPORTED", "replay": "NOT_VERIFIED", "orders": "UNSUPPORTED", "testnet_demo": "NOT_VERIFIED",
            "account_eligible": "NOT_VERIFIED", "region_eligible": "NOT_VERIFIED",
            "notes": {"orderbook": "l2Book snapshot odpytywany (top-N) – nie pełna historia L2", "orders": "brak ścieżki zleceń w Apollo23 dla tego rynku",
                      "research_only": research}}


def resample(bars: list[dict], from_s: int, to_s: int) -> list[dict]:
    """Deterministic UTC-aligned resample of CLOSED bars; a target bar is emitted only when every source slot is present (complete)."""
    if to_s % from_s:
        raise UniverseError("INCOMPATIBLE_TF")
    k = to_s // from_s
    groups: dict[int, list[dict]] = {}
    for b in bars:
        groups.setdefault(int(b["t"]) // to_s * to_s, []).append(b)
    out = []
    for t0 in sorted(groups):
        g = sorted(groups[t0], key=lambda b: b["t"])
        slots = {int(b["t"]) for b in g}
        complete = len(g) == k and slots == {t0 + j * from_s for j in range(k)}
        if not complete:
            continue
        out.append({"t": t0, "o": g[0]["o"], "h": max(b["h"] for b in g), "l": min(b["l"] for b in g), "c": g[-1]["c"],
                    "v": sum(b.get("v", 0.0) for b in g), "trades": sum(b.get("trades", 0) for b in g), "resampled_from": f"{from_s}s", "complete": True})
    return out


class MarketBridge:
    """Common versioned contract for CryptoMarketBridge / IndicesMarketBridge / FomoStockPerpsBridge (shared Hyperliquid public client)."""
    MARKET = ""
    CONTRACT = "PMW-MARKET-BRIDGE-1"

    def __init__(self, hl, universe: "Universe"):
        self.hl, self.universe = hl, universe

    def instruments(self) -> list[dict]:
        return [i.to_dict() | {"capabilities": capabilities(i)} for i in self.universe.instruments() if i.market == self.MARKET]

    def _ins(self, instrument_id: str) -> Instrument:
        ins = next((i for i in self.universe.instruments() if i.instrument_id == instrument_id or i.native_symbol == instrument_id
                    or (i.display == instrument_id and i.market == self.MARKET)), None)
        if ins is None or ins.market != self.MARKET:
            raise UniverseError(f"UNKNOWN_INSTRUMENT: {instrument_id}")
        return ins

    def candles(self, instrument_id: str, tf: str, n: int = 300) -> dict:
        if tf not in TIMEFRAMES:
            raise UniverseError(f"UNSUPPORTED_TF: {tf} ({', '.join(TIMEFRAMES)})")
        ins = self._ins(instrument_id)
        src_tf = RESAMPLE_FROM.get(tf, tf)
        k = TF_SECONDS[tf] // TF_SECONDS[src_tf]
        now_ms = int(time.time() * 1000)
        start = now_ms - (n * k + 2 * k) * TF_SECONDS[src_tf] * 1000
        raw = self.hl.post({"type": "candleSnapshot", "req": {"coin": ins.native_symbol, "interval": src_tf, "startTime": start, "endTime": now_ms}}) or []
        bars = [{"t": int(c["t"]) // 1000, "o": float(c["o"]), "h": float(c["h"]), "l": float(c["l"]), "c": float(c["c"]), "v": float(c["v"]),
                 "trades": int(c.get("n") or 0)} for c in raw if int(c["T"]) < now_ms]
        if tf in RESAMPLE_FROM:
            bars = resample(bars, TF_SECONDS[src_tf], TF_SECONDS[tf])
        return {"instrument": ins.to_dict(), "timeframe": tf, "bars": bars[-n:], "basis": "TRADE_PRICE (Hyperliquid candles)",
                "partial_bar_policy": "tylko zamknięte świece", "resampled": tf in RESAMPLE_FROM, "time_basis": "UTC"}

    def context(self, instrument_id: str) -> dict:
        ins = self._ins(instrument_id)
        d = self.hl.post({"type": "metaAndAssetCtxs"} | ({"dex": ins.venue} if ins.venue != "core" else {})) or [{}, []]
        uni = (d[0] or {}).get("universe") or []
        ctx = next((c for u, c in zip(uni, d[1] or []) if u.get("name") == ins.native_symbol), None)
        if ctx is None:
            return {"instrument_id": ins.instrument_id, "status": "UNAVAILABLE"}
        f = lambda k: float(ctx[k]) if ctx.get(k) not in (None, "") else None  # noqa: E731
        return {"instrument_id": ins.instrument_id, "status": "OK", "mark": f("markPx"), "oracle": f("oraclePx"), "mid": f("midPx"),
                "funding": f("funding"), "open_interest": f("openInterest"), "day_volume_notional": f("dayNtlVlm"), "prev_day_px": f("prevDayPx"),
                "warnings": STOCK_PERP_WARNINGS if ins.market == "FOMO_STOCK_PERPS" else []}

    def book(self, instrument_id: str) -> dict:
        ins = self._ins(instrument_id)
        b = self.hl.post({"type": "l2Book", "coin": ins.native_symbol}) or {}
        lv = b.get("levels") or [[], []]
        return {"instrument_id": ins.instrument_id, "t": float(b.get("time") or 0) / 1000.0, "bids": [[float(x["px"]), float(x["sz"])] for x in lv[0]],
                "asks": [[float(x["px"]), float(x["sz"])] for x in lv[1]], "quality": "DEGRADED (snapshot top-N)"}

    def trades(self, instrument_id: str):
        from ..orderflow.trades import from_hyperliquid
        ins = self._ins(instrument_id)
        return from_hyperliquid(ins.instrument_id, self.hl.post({"type": "recentTrades", "coin": ins.native_symbol}) or [])

    def health(self) -> dict:
        return {"market": self.MARKET, "contract": self.CONTRACT, "hl_errors": getattr(self.hl, "errors", None),
                "last_error": getattr(self.hl, "last_error", None), **MARKETS[self.MARKET]}


class CryptoMarketBridge(MarketBridge):
    MARKET = "CRYPTO"


class IndicesMarketBridge(MarketBridge):
    MARKET = "INDICES"


class FomoStockPerpsBridge(MarketBridge):
    MARKET = "FOMO_STOCK_PERPS"


class Universe:
    """Cached instrument master built from live venue metadata (perpDexs, meta core, meta dex=xyz)."""

    def __init__(self, hl, ttl: float = 3600.0):
        self.hl, self.ttl = hl, ttl
        self._ins: list[Instrument] = []
        self._at = 0.0
        self.error: str | None = None
        self.raw_versions: dict = {}

    def refresh(self) -> list[Instrument]:
        dexs = [d.get("name") if d else None for d in (self.hl.post({"type": "perpDexs"}) or [])]
        core = self.hl.post({"type": "meta"})
        xyz = self.hl.post({"type": "meta", "dex": "xyz"}) if "xyz" in dexs else None
        self._ins = build_instruments(core, xyz, dexs)
        self._at = time.time()
        self.raw_versions = {"core": metadata_version(core) if core else None, "xyz": metadata_version(xyz) if xyz else None, "dexs": dexs}
        return self._ins

    def instruments(self) -> list[Instrument]:
        if not self._ins or time.time() - self._at > self.ttl:
            try:
                self.refresh()
                self.error = None
            except Exception as exc:  # noqa: BLE001 - keep the last good catalogue, report the error
                self.error = f"{type(exc).__name__}: {exc}"[:200]
        return self._ins


def basket_templates(markets=("CRYPTO", "INDICES", "FOMO_STOCK_PERPS")) -> dict:
    """Per market x TF strategy basket TEMPLATES (instantiated per instrument on demand). Status PROPOSED: they are NOT in the active 60-strategy
    catalogue, produce no signals and need data sufficiency + OOS validation + SFB migration before any activation."""
    fam = {"CRYPTO": ["TREND_PULLBACK", "BREAKOUT", "MEAN_REVERSION", "FUNDING_CONTEXT", "OI_EXPANSION"],
           "INDICES": ["SESSION_OPEN_RANGE", "TREND_PULLBACK", "MEAN_REVERSION", "GAP_CONTEXT"],
           "FOMO_STOCK_PERPS": ["EARNINGS_SESSION_CONTEXT", "TREND_PULLBACK", "OUT_OF_HOURS_BASIS", "MEAN_REVERSION"]}
    return {m: {"families": fam[m], "timeframes": list(TIMEFRAMES), "instance_key": f"{m}/<native_symbol>/<TF>", "status": "PROPOSED",
                "market_status": MARKETS[m]["status"], "execution": MARKETS[m]["execution"],
                "contract_fields": ["required_data", "regime", "entry", "exit", "filters", "invalidation", "stop", "sizing", "fees_funding_slippage",
                                    "confidence", "risk", "cooldown", "evaluation_metrics", "oos_status"]} for m in markets}
