"""Exporter registry (Apollo23 1.46): one table drives the CLI (`python -m masterquo export-<name>`), the API (`GET /api/v1/exports/<name>`)
and the tests. Parameters are typed and bounded here - the API never passes a path, the CLI may only choose the output folder (--out)."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import sources as S
from .core import Collected, ExportError, write_export

MARKETS = ("CRYPTO", "INDICES", "FOMO_STOCK_PERPS")
SHADOW_TF = ("M5", "M15", "M30", "H1", "H4", "D1")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str                      # str | int | float | bool | list
    default: object = None
    choices: tuple | None = None
    lo: float | None = None
    hi: float | None = None
    help: str = ""
    max_items: int = 60

    def parse(self, raw):
        if raw is None or raw == "":
            return self.default
        try:
            if self.kind == "int":
                v = int(raw)
            elif self.kind == "float":
                v = float(raw)
            elif self.kind == "bool":
                v = raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "yes", "tak", "on")
            elif self.kind == "list":
                items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
                v = [str(x).strip() for x in items if str(x).strip()]
                if len(v) > self.max_items:
                    raise ExportError(f"BAD_PARAM: {self.name} (maks. {self.max_items} pozycji)")
            else:
                v = str(raw).strip()
        except (TypeError, ValueError):
            raise ExportError(f"BAD_PARAM: {self.name} ({self.kind})") from None
        if self.kind in ("int", "float"):
            if v != v or (self.lo is not None and v < self.lo) or (self.hi is not None and v > self.hi):
                raise ExportError(f"BAD_PARAM: {self.name} poza zakresem [{self.lo}, {self.hi}]")
        if self.choices is not None:
            vals = v if isinstance(v, list) else [v]
            bad = [x for x in vals if x not in self.choices]
            if bad:
                raise ExportError(f"BAD_PARAM: {self.name}={bad} (dozwolone: {', '.join(map(str, self.choices))})")
        if self.kind == "str" and len(v) > 80:
            raise ExportError(f"BAD_PARAM: {self.name} (maks. 80 znaków)")
        return v


@dataclass(frozen=True)
class Exporter:
    name: str
    title: str
    collect: object                # fn(ctx, **params) -> Collected
    params: tuple = field(default_factory=tuple)
    needs_app: bool = False        # source lives in the memory of the running app -> the CLI asks the running app (API)
    task: str = ""

    def parse_params(self, raw: dict) -> dict:
        known = {p.name for p in self.params}
        extra = sorted(k for k in raw if k not in known and k not in ("format",))
        if extra:
            raise ExportError(f"UNKNOWN_PARAM: {extra}")
        return {p.name: p.parse(raw.get(p.name)) for p in self.params}


def _lh_horizons():
    from ..forecast.long_horizon import HORIZONS_S
    return tuple(HORIZONS_S)


def _market_tfs():
    from ..markets.universe import TIMEFRAMES
    return tuple(TIMEFRAMES)


EXPORTERS: dict[str, Exporter] = {e.name: e for e in (
    Exporter("orderflow", "Ledger transakcji, footprint, Volume Profile, DOM i heatmapa (order flow)", S.orderflow, (
        Param("market", "str", "CRYPTO", MARKETS), Param("instrument", "str", "", help="symbol lub instrument_id (wymagany)"),
        Param("row", "float", 0.0, lo=0.0, hi=1e9, help="wysokość wiersza ceny; 0 = automatycznie jak w widoku workspace"),
        Param("tf_seconds", "int", 60, lo=1, hi=86400), Param("refresh", "bool", True, help="dopisz najnowsze transakcje do ledgera przed eksportem")),
        needs_app=True, task="TASK 001/002/004"),
    Exporter("market-candles", "Świece CRYPTO / INDICES / FOMO_STOCK_PERPS (10 interwałów)", S.market_candles, (
        Param("market", "str", "CRYPTO", MARKETS), Param("instruments", "list", None, help="symbole lub instrument_id, po przecinku (wymagane)", max_items=120),
        Param("timeframes", "list", None, help="domyślnie wszystkie 10: 1d,8h,4h,1h,30m,15m,10m,5m,3m,1m"),
        Param("n", "int", 500, lo=10, hi=5000)), task="TASK 003"),
    Exporter("fomo-universe", "Rozpoznanie FOMO 101 z wersją metadanych venue", S.fomo_universe, (), task="TASK 003"),
    Exporter("strategy-roi", "ROI strategii (TASK 014) – PAPER / AUTO_DEMO / AUTO_LIVE osobno", S.strategy_roi, (), task="TASK 014"),
    Exporter("sfb-snapshots", "Snapshoty Strategy Filter Bucket", S.sfb_snapshots, (), needs_app=True, task="TASK 018"),
    Exporter("asge-trials", "Ledger prób generatora strategii (ASGE)", S.asge_trials, (), task="TASK 024"),
    Exporter("change-points", "Wyniki PELT (punkty zmiany)", S.change_points, (
        Param("timeframe", "str", "H1", SHADOW_TF), Param("lookback", "int", 500, lo=20, hi=5000), Param("min_segment", "int", 10, lo=2, hi=200),
        Param("sensitivity", "bool", False)), needs_app=True, task="TASK 015"),
    Exporter("long-horizon", "Prognozy 24–72 h (rozkład, SHADOW)", S.long_horizon, (
        Param("timeframe", "str", "H1", SHADOW_TF), Param("horizons", "list", None, help="24h,36h,48h,72h")), needs_app=True, task="TASK 012"),
    Exporter("association-rules", "Reguły asocjacyjne (OBSERVE)", S.association_rules, (
        Param("timeframe", "str", "H1", SHADOW_TF), Param("horizon", "int", 24, lo=1, hi=200)), needs_app=True, task="TASK 011"),
    Exporter("pt-skill", "Wyniki testu Pesarana–Timmermanna (dziennik od startu aplikacji)", lambda ctx: S.shadow_journal(ctx, "pt"), (),
             needs_app=True, task="TASK 010"),
    Exporter("dt-ranker", "Rankingi DT (SHADOW, dziennik od startu aplikacji)", lambda ctx: S.shadow_journal(ctx, "dt"), (), needs_app=True,
             task="TASK 005"),
    Exporter("telegram-center", "Zdarzenia i outbox centrum Telegram rachunku (bez tokenu)", S.telegram_center, (), task="TASK 017"),
    Exporter("trader-life-game", "TraderLifeGame – kopia zapasowa (profil, XP, Gold, questy, dziennik, symulator, inwentarz)", S.trader_life_game, (),
             task="TASK 019"),
    Exporter("bootstrap", "Stan bootstrapu (komponenty, stany)", S.bootstrap_state, (), task="TASK 013"),
    Exporter("store-tables", "Tabele trwałych magazynów SQLite bez eksportu zbiorczego (biała lista; tryby i dane syntetyczne osobno)",
             S.store_tables, (Param("store", "str", "main", tuple(S.STORES)), Param("tables", "list", None, help="domyślnie wszystkie dozwolone",
                                                                                     max_items=100)), task="inwentarz X6"),
)}


def run(name: str, ctx: S.SourceContext, raw_params: dict | None = None, *, formats=("csv", "jsonl"), out_root=None) -> dict:
    """Validate params, collect from the source, write the export folder; returns the manifest (with `path`)."""
    ex = EXPORTERS.get(name)
    if ex is None:
        raise ExportError(f"UNKNOWN_EXPORTER: {name}")
    params = ex.parse_params(dict(raw_params or {}))
    if name == "market-candles":
        tfs = params.get("timeframes")
        if tfs:
            bad = [t for t in tfs if t not in _market_tfs()]
            if bad:
                raise ExportError(f"BAD_PARAM: timeframes={bad} (dozwolone: {', '.join(_market_tfs())})")
    if name == "long-horizon" and params.get("horizons"):
        bad = [h for h in params["horizons"] if h not in _lh_horizons()]
        if bad:
            raise ExportError(f"BAD_PARAM: horizons={bad} (dozwolone: {', '.join(_lh_horizons())})")
    try:
        col: Collected = ex.collect(ctx, **params)
    except ValueError as exc:
        raise ExportError(str(exc)) from None
    col.provenance.setdefault("task", ex.task)
    return write_export(name, col, out_root=out_root, formats=formats, params=params, data_dir=ctx.data_dir)
