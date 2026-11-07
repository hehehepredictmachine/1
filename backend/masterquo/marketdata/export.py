"""MT5 -> candle store export (PMW-MD-EXPORT-1): historical (from..to) and incremental (from the last stored bar), M1/M5/M15/M30
(H1/H4/D1 optional), chunked (<= 7200 bars per request), each chunk retried with backoff, checkpointed - an interrupted export resumes
at the first chunk that is not done. UTC everywhere: broker server time is converted with the measured offset and the server's DST
convention (NY_CLOSE vs UNIFORM, detected from the history - forecast.export.dst_model_probe), frozen for the whole run.

* Only CLOSED candles: the cutoff is the open time of the candle forming at the start of the run.
* Rows are merged into the store by (instrument, timeframe, time) - repeated exports never duplicate.
* Invalid OHLC is rejected and listed; gaps are classified (quality.py) and never filled.
* Costs: the bar spread column (as recorded by the terminal) is stored; commission only from the account's own deal history of this
  symbol (else UNKNOWN); slippage = the user's stress assumption. Historical bid/ask and historical commissions are NOT reconstructed
  from today's values - the manifest says what is measured and what is an assumption.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import quality as Q
from .sources import SourceError, retry
from .store import SCHEMA_VERSION, TF_SECONDS, Store, atomic_json, iso, read_json

EXPORT_TFS = ("M1", "M3", "M5", "M15", "M30")
CHUNK_BARS = 7200
MARGIN_S = 4 * 3600
LOCK_STALE_S = 600


class ExportBusy(RuntimeError):
    pass


class ExportCancelled(RuntimeError):
    pass


def _now() -> float:
    return time.time()


def time_model(source, symbol: str, now: float, previous: dict | None) -> dict:
    """Offset + DST convention of the broker server, decided once per run."""
    from ..diagnostics import ny_close_offset
    from ..forecast.export import dst_model_probe
    off, basis = source.offset(symbol)
    if off is None:
        raise SourceError("nie można ustalić offsetu czasu serwera MT5 (brak notowań?) – uruchom eksport przy otwartym rynku")
    probe = {}
    try:
        probe = source.call(lambda m: dst_model_probe(m, symbol, datetime.fromtimestamp(now, timezone.utc)))
    except Exception as exc:  # noqa: BLE001
        probe = {"verdict": "UNVERIFIED", "reason": f"{type(exc).__name__}: {exc}"[:160]}
    today_ny = ny_close_offset(now) == int(off)
    model = "NY_CLOSE" if today_ny and probe.get("verdict") in ("NY_CLOSE", "UNVERIFIED") else "UNIFORM"
    if today_ny and probe.get("verdict") == "UNVERIFIED" and previous and previous.get("model") in ("NY_CLOSE", "UNIFORM"):
        model = previous["model"]                                    # keep the convention of the data already stored
    out = {"model": model, "offset_seconds": int(off), "offset_basis": basis, "probe": probe.get("verdict"), "decided_at": iso(now)}
    if previous and previous.get("model") and previous.get("model") != model:
        out["warning"] = f"konwencja czasu serwera zmieniła się ({previous['model']} -> {model}) – sprawdź raport jakości przy granicy eksportów"
    return out


def _windows(start: int, end: int, step: int) -> list[tuple[int, int]]:
    span = CHUNK_BARS * step
    out, cur = [], start
    while cur < end:
        nxt = min(end, cur + span)
        out.append((cur, nxt))
        cur = nxt
    return out


def _fetch(source, symbol: str, tf: str, a: int, b: int, cutoff: int, tm: dict, sleep) -> list[tuple]:
    from ..diagnostics import server_to_utc
    step = TF_SECONDS[tf]
    off = tm["offset_seconds"]

    def q(m):
        const = getattr(m, "TIMEFRAME_" + tf)
        return m.copy_rates_range(symbol, const, datetime.fromtimestamp(a + off - MARGIN_S, timezone.utc),
                                  datetime.fromtimestamp(b + off + MARGIN_S, timezone.utc))
    r = retry(lambda: source.call(q), attempts=3, base_delay=0.5, sleep=sleep)
    names = getattr(getattr(r, "dtype", None), "names", None) or ()
    out = []
    for x in r:
        raw = int(x["time"])
        u, _, amb = server_to_utc(raw, tm["model"], off)
        if a <= u < b and u < cutoff and u % step == 0:                  # closed candles of this window only
            out.append((u, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), int(x["tick_volume"]),
                        int(x["spread"]) if "spread" in names else 0, int(x["real_volume"]) if "real_volume" in names else 0, raw, int(amb)))
    return out


def run(source, store: Store, instrument: str, symbol: str, *, timeframes=EXPORT_TFS, mode: str = "incremental",
        start: str | float | None = None, end: str | float | None = None, lookback_days: float = 90.0, cfg=None,
        progress=None, cancel=None, sleep=time.sleep, now: float | None = None) -> dict:
    """mode: 'incremental' (from the last stored bar of each TF; no data yet -> `start` or `lookback_days`) or 'historical' (start..end).
    progress(dict) is called after every chunk; cancel() -> True stops after the current chunk (resumable)."""
    import os as _os
    if _os.environ.get("MQ_STUDIO_DATA_DIR"):        # inside a Studio job: the Studio queue already holds the shared export lock
        return _run(source, store, instrument, symbol, timeframes=timeframes, mode=mode, start=start, end=end, lookback_days=lookback_days,
                    cfg=cfg, progress=progress, cancel=cancel, sleep=sleep, now=now)
    from ..paths import data_dir
    from ..studio.lock import Lock
    lk = Lock(data_dir() / "locks" / "pmw_export.lock", app="PepeMarketWizard-export")
    ok, owner = lk.acquire(f"export:{instrument}")
    if not ok:
        raise ExportBusy(f"trwa inny eksport ({(owner or {}).get('app')}: {(owner or {}).get('job')}) – np. Pepe Data & Training Studio; spróbuj później")
    try:
        return _run(source, store, instrument, symbol, timeframes=timeframes, mode=mode, start=start, end=end, lookback_days=lookback_days,
                    cfg=cfg, progress=lambda d: (lk.heartbeat(), progress(d) if progress else None), cancel=cancel, sleep=sleep, now=now)
    finally:
        lk.release()


def _run(source, store: Store, instrument: str, symbol: str, *, timeframes=EXPORT_TFS, mode: str = "incremental",
         start: str | float | None = None, end: str | float | None = None, lookback_days: float = 90.0, cfg=None,
         progress=None, cancel=None, sleep=time.sleep, now: float | None = None) -> dict:
    tfs = [t for t in timeframes if t in TF_SECONDS]
    if not tfs:
        raise ValueError("brak interwałów do eksportu")
    t_start = _ts(start)
    t_end = _ts(end)
    if mode == "historical" and t_start is None:
        raise ValueError("eksport historyczny wymaga daty początkowej (--from)")
    if t_start is not None and t_end is not None and t_end <= t_start:
        raise ValueError("data końcowa musi być późniejsza niż początkowa")
    inst_dir = store.inst_dir(instrument)
    inst_dir.mkdir(parents=True, exist_ok=True)
    st_path = inst_dir / "export_state.json"
    req = {"instrument": instrument, "symbol": symbol, "timeframes": tfs, "mode": mode, "start": start, "end": end, "lookback_days": lookback_days}
    prev = read_json(st_path, {}) or {}
    n0 = now if now is not None else _now()
    if prev.get("status") == "RUNNING" and prev.get("pid") != os.getpid() and n0 - float(prev.get("heartbeat") or 0) < LOCK_STALE_S:
        raise ExportBusy(f"eksport {instrument} już trwa (pid {prev.get('pid')}) – poczekaj albo zatrzymaj go w Centrum treningu")
    resume = prev.get("request") == req and prev.get("status") in ("FAILED", "CANCELLED", "RUNNING") and prev.get("frozen")
    man = store.manifest(instrument)
    if resume:
        frozen = prev["frozen"]
        done = {k: set(map(tuple, v)) for k, v in (prev.get("done") or {}).items()}
    else:
        tm = time_model(source, symbol, n0, man.get("time_model"))
        ranges = {}
        for tf in tfs:
            step = TF_SECONDS[tf]
            cutoff = int(n0 // step * step)                           # open of the candle forming now: excluded
            if t_end is not None:
                cutoff = min(cutoff, int(t_end // step * step))
            last = store.last_time(instrument, tf)
            if mode == "incremental" and last is not None:
                a = last + step
            else:
                a = int((t_start if t_start is not None else n0 - lookback_days * 86400) // step * step)
            ranges[tf] = [a, cutoff]
        frozen = {"time_model": tm, "ranges": ranges, "now": n0}
        done = {}
    run_id = prev.get("run_id") if resume else "EXP-" + datetime.fromtimestamp(n0, timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    state = {"request": req, "frozen": frozen, "done": {k: sorted(v) for k, v in done.items()}, "status": "RUNNING", "pid": os.getpid(),
             "run_id": run_id, "started_at": prev.get("started_at") if resume else iso(n0), "heartbeat": _now(), "resumed": bool(resume)}
    atomic_json(st_path, state)
    tm = frozen["time_model"]
    summary = {"run_id": run_id, "instrument": instrument, "symbol": symbol, "mode": mode, "resumed": bool(resume), "source": source.describe(),
               "time_model": tm, "timeframes": {}, "status": "RUNNING"}
    total_chunks = sum(len(_windows(*frozen["ranges"][tf], TF_SECONDS[tf])) for tf in tfs)
    k_chunk = 0
    try:
        for tf in tfs:
            step = TF_SECONDS[tf]
            a, cutoff = frozen["ranges"][tf]
            wins = _windows(a, cutoff, step)
            acc = {"requested_from_utc": iso(a), "requested_to_utc": iso(cutoff), "chunks": len(wins), "chunks_skipped_done": 0, "received": 0,
                   "added": 0, "duplicates": 0, "conflicts": 0, "invalid": 0, "conflict_list": [], "invalid_list": []}
            for (wa, wb) in wins:
                k_chunk += 1
                if cancel and cancel():
                    raise ExportCancelled("przerwane przez użytkownika")
                if (wa, wb) in done.get(tf, set()):
                    acc["chunks_skipped_done"] += 1
                    continue
                rows = _fetch(source, symbol, tf, wa, wb, cutoff, tm, sleep)
                ok, bad = Q.check_rows(rows)
                m = store.merge(instrument, tf, ok)
                acc["received"] += len(rows)
                acc["added"] += m["added"]
                acc["duplicates"] += m["duplicates"]
                acc["conflicts"] += m["conflicts"]
                acc["invalid"] += len(bad)
                acc["conflict_list"] = (acc["conflict_list"] + m["conflict_list"])[:100]
                acc["invalid_list"] = (acc["invalid_list"] + bad)[:100]
                done.setdefault(tf, set()).add((wa, wb))
                state.update(done={k: sorted(v) for k, v in done.items()}, heartbeat=_now())
                atomic_json(st_path, state)
                if progress:
                    progress({"stage": "export", "tf": tf, "chunk": k_chunk, "chunks": total_chunks, "rows_added": acc["added"],
                              "window_utc": [iso(wa), iso(wb)]})
            summary["timeframes"][tf] = acc
        summary["status"] = "COMPLETE"
    except ExportCancelled as exc:
        summary.update(status="CANCELLED", reason=str(exc))
    except Exception as exc:  # noqa: BLE001 - recorded for resume; re-raised after the state is saved
        summary.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}"[:400])
    state.update(status=summary["status"], heartbeat=_now(), finished_at=iso(_now()), reason=summary.get("reason"))
    atomic_json(st_path, state)
    _finish(source, store, instrument, symbol, tfs, frozen, summary, cfg)
    return summary


def _finish(source, store: Store, inst: str, symbol: str, tfs, frozen: dict, summary: dict, cfg) -> None:
    quality = {}
    for tf in TF_SECONDS:
        cols = store.read(inst, tf)
        if cols["time"]:
            rq = frozen["ranges"].get(tf)
            quality[tf] = Q.report(cols, tf, (rq[0], rq[1]) if rq else None)
    atomic_json(store.inst_dir(inst) / "quality_report.json", {"schema_version": SCHEMA_VERSION, "instrument": inst, "generated_at": iso(_now()),
                                                               "timeframes": quality, "gap_classes": Q.__doc__})
    commission = {"source": "UNKNOWN", "reason": "nie odczytano"}
    try:
        from ..forecast.export import _commission
        commission = source.call(lambda m: _commission(m, symbol))
    except Exception as exc:  # noqa: BLE001
        commission = {"source": "UNKNOWN", "reason": f"{type(exc).__name__}"}
    point = contract = None
    spec = {}
    try:
        info = source.call(lambda m: m.symbol_info(symbol))
        point = float(getattr(info, "point", 0) or 0) or None
        contract = float(getattr(info, "trade_contract_size", 0) or 0) or None
        spec = {k: getattr(info, k, None) for k in ("digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size", "currency_base",
                                                    "currency_profit", "currency_margin", "volume_min", "volume_step")}
    except Exception:  # noqa: BLE001
        point = None
    costs_cfg = getattr(cfg, "costs", None) if cfg is not None else None
    man = store.manifest(inst)
    entry = {k: v for k, v in summary.items() if k != "source"} | {"finished_at": iso(_now())}
    entry["timeframes"] = {tf: {k: v for k, v in acc.items() if k not in ("conflict_list", "invalid_list")}
                           for tf, acc in (summary.get("timeframes") or {}).items()}
    hist = (man.get("exports") or [])[-49:] + [entry]
    lists = {tf: {"conflicts": acc.get("conflict_list"), "invalid": acc.get("invalid_list")} for tf, acc in (summary.get("timeframes") or {}).items()
             if acc.get("conflict_list") or acc.get("invalid_list")}
    store.write_manifest(inst, {
        "instrument": inst, "symbol": symbol, "source": source.describe(), "data_kind": _kind(source),
        "time_model": frozen["time_model"], "time_basis": "UTC (czas serwera MT5 przeliczony offsetem i konwencją DST)",
        "timeframes": {tf: {k: q.get(k) for k in ("rows", "first_utc", "last_utc", "trading_days", "status", "coverage_of_continuous_range")}
                       | {"gaps": {k: q["gaps"].get(k) for k in ("WEEKEND", "SESSION_BREAK", "NO_TICKS_SHORT", "MISSING", "missing_bars")}
                          if q.get("gaps") else None} for tf, q in quality.items()},
        "symbol_spec": spec,
        "costs": {"spread": {"status": "MEASURED_PER_BAR", "column": "spread", "unit": "punkty", "point": point, "contract_size": contract,
                             "note": "spread zapisany przez terminal dla świecy – nie jest historycznym bid/ask (nie rekonstruujemy go)"},
                  "commission": commission | {"note": "prowizja tylko z historii transakcji tego symbolu na rachunku; konto 'Zero' nie oznacza zerowych kosztów"},
                  "commission_user": {"value": getattr(costs_cfg, "commission_per_lot_per_side", None), "status": "ASSUMPTION_USER_CONFIG"},
                  "slippage": {"value_points": getattr(costs_cfg, "slippage_stress_points", None), "status": "ASSUMPTION_STRESS",
                               "note": "założenie użytkownika – nie pomiar"},
                  "bid_ask_history": "NOT_AVAILABLE – świece wykresu brokera (MT5: zwykle Bid); Ask historyczny nie jest rekonstruowany"},
        "params": {"chunk_bars": CHUNK_BARS, "retry": "3 próby, backoff 0,5/1/2 s", "closed_candles_only": True, "dedup_key": "(instrument, timeframe, time)"},
        "exports": hist, "last_export": {k: summary.get(k) for k in ("run_id", "status", "mode", "resumed", "reason")},
        "last_export_rejected_rows": lists})


def _kind(source) -> str:
    try:
        syn = source.synthetic()
    except Exception:  # noqa: BLE001
        syn = None
    return "SYNTHETIC_TEST" if syn else ("REAL_USER_DATA" if syn is False else "UNKNOWN_SOURCE")


def _ts(x) -> float | None:
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        return float(x)
    d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def import_folder(store: Store, instrument: str, src) -> dict:
    """Merge a copied candle folder (data/marketdata/<INSTRUMENT> from the machine with MT5, or the dataset zip) into this store after
    verifying the checksums of its manifest. Nothing is merged when a checksum does not match."""
    import shutil
    import tempfile
    import zipfile
    from pathlib import Path
    src = Path(src)
    tmp = None
    if src.is_file() and src.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="pmw_import_"))
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():
                if n.startswith("/") or ".." in Path(n).parts:
                    raise ValueError(f"niebezpieczna ścieżka w archiwum: {n}")
            z.extractall(tmp)
        cands = [p.parent for p in tmp.rglob("manifest.json")]
        if not cands:
            raise ValueError("w archiwum nie ma manifest.json")
        src = cands[0]
    try:
        other = Store(src.parent)
        name = src.name
        man = other.manifest(name)
        if man.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"niezgodna wersja schematu danych: {man.get('schema_version')} (oczekiwana {SCHEMA_VERSION})")
        if man.get("instrument") not in (None, instrument):
            raise ValueError(f"folder zawiera {man.get('instrument')}, a wybrano {instrument}")
        ver = other.verify(name)
        if not ver["ok"]:
            raise ValueError(f"sumy kontrolne niezgodne – import przerwany: {ver}")
        out = {}
        for tf in TF_SECONDS:
            cols = other.read(name, tf)
            if not cols["time"]:
                continue
            rows = list(zip(*(cols[c] for c in ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume", "server_time",
                                                 "dst_ambiguous"))))
            ok, bad = Q.check_rows(rows)
            m = store.merge(instrument, tf, ok)
            out[tf] = {"rows": len(rows), "added": m["added"], "duplicates": m["duplicates"], "conflicts": m["conflicts"], "invalid": len(bad)}
        cur = store.manifest(instrument)
        store.write_manifest(instrument, {"instrument": instrument, "symbol": cur.get("symbol") or man.get("symbol"),
                                          "data_kind": cur.get("data_kind") or man.get("data_kind"),
                                          "time_model": cur.get("time_model") or man.get("time_model"),
                                          "imports": (cur.get("imports") or [])[-19:] + [{"from": str(src), "source": man.get("source"), "at": iso(_now()),
                                                                                         "result": out}]})
        return {"status": "OK", "timeframes": out, "verified_files": ver["files"]}
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
