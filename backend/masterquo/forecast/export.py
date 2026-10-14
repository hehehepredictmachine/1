"""History export for the candle forecasters: closed M5 and M30 of the exact broker symbol, written in the gold_candles CSV
format, with source_metadata.json and DATA_QUALITY_REPORT.json.

Same time rule as the bot's live feed (mt5/clock.py): MT5 bar times are BROKER SERVER time; they are converted to UTC with
the measured offset (UNIFORM) or the per-bar NY_CLOSE model when it agrees with the measured offset. Training and the
live SHADOW inference therefore see the same timestamps. (The reference gold_candles.mt5_reader treats the epoch as UTC;
the bot does not use that reader.) A frozen cutoff (UTC, aligned to 30 min) is fixed before the first request; the range
is fetched in monthly chunks with a checkpoint per chunk (an interrupted export resumes). Identical rows on chunk borders
are removed and counted; different OHLC for the same time is a REVISION and is reported (the later read is NOT silently
kept - such bars are dropped and listed). Invalid OHLC geometry is dropped and listed, never repaired.
This command opens and closes ITS OWN MT5 connection (standalone process) - it never touches the bot's session.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import paths
from ..timeutil import iso

TFS = {"M5": 300, "M30": 1800}
CHUNK_DAYS = 31


def _measure_offset(mt5, sym: str, server: str | None) -> tuple[float | None, str]:
    from ..db.database import Database
    from ..mt5.clock import ServerClock
    sc = ServerClock()
    t_end = time.monotonic() + 15
    while time.monotonic() < t_end and not sc.verified:
        tk = mt5.symbol_info_tick(sym)
        if tk is not None:
            sc.observe_tick(int(tk.time_msc), datetime.now(timezone.utc))
        time.sleep(0.3)
    if sc.verified:
        return sc.offset, "MEASURED_NOW"
    row = Database().one("SELECT offset_seconds, measured_at FROM clock_offsets WHERE server=?", (server or "",))
    if row:
        return row["offset_seconds"], f"STORED_{row['measured_at']}"
    return None, "UNKNOWN"


def _gaps(times: list[int], step: int) -> dict:
    """Classify gaps between consecutive bars (UTC): weekend, short daily break (<= 2 h), other (listed)."""
    out = {"weekend": 0, "daily_break_le_2h": 0, "other": 0, "other_list": []}
    for a, b in zip(times, times[1:]):
        if b - a == step:
            continue
        da, db = datetime.fromtimestamp(a, timezone.utc), datetime.fromtimestamp(b, timezone.utc)
        if db - da >= timedelta(hours=40) and any((da + timedelta(days=k)).weekday() == 5 for k in range((db - da).days + 1)):
            out["weekend"] += 1
        elif b - a <= 2 * 3600 + step:
            out["daily_break_le_2h"] += 1
        else:
            out["other"] += 1
            if len(out["other_list"]) < 60:
                out["other_list"].append({"after_utc": iso(da), "next_utc": iso(db), "missing_bars": (b - a) // step - 1})
    return out


def export_candles(months: int = 12, out_dir: str | None = None, dst_model: str = "AUTO") -> int:
    from ..config import ConfigStore
    from ..diagnostics import _init_kw, ny_close_offset, server_to_utc
    from ..mt5.fake import is_fake
    from ..mt5 import login as lg
    cfg = ConfigStore().get()
    sym = cfg.mt5.symbol
    if not 1 <= months <= 36:
        print("[BLAD] --months 1..36")
        return 2
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("[BLAD] BLOCKED_NO_MT5: brak pakietu MetaTrader5 (eksport działa na Windows z zainstalowanym i zalogowanym MT5).")
        return 3
    if not mt5.initialize(**_init_kw(cfg)):
        err = mt5.last_error()
        print(f"[BLAD] initialize(): {err} {lg.hint(err)}")
        return 3
    try:
        info = mt5.symbol_info(sym)
        if info is None or not mt5.symbol_select(sym, True):
            print(f"[BLAD] Symbol {sym} niedostępny – program nie podmienia symbolu.")
            return 4
        spec = {k: getattr(info, k, None) for k in ("name", "digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size",
                                                     "currency_base", "currency_profit", "currency_margin", "volume_min", "volume_step")}
        if spec["currency_base"] != "XAU" or spec["currency_profit"] != "USD":
            print(f"[BLAD] {sym} nie jest potwierdzony jako XAU/USD (base={spec['currency_base']}, profit={spec['currency_profit']}).")
            return 4
        tick = float(spec["trade_tick_size"] or 0)
        if tick <= 0 or float(spec["trade_contract_size"] or 0) <= 0:
            print("[BLAD] Nieprawidłowa specyfikacja kontraktu (tick_size / contract_size).")
            return 4
        acc = mt5.account_info()
        offset, basis = _measure_offset(mt5, sym, getattr(acc, "server", None))
        if offset is None:
            print("[BLAD] Nie można zmierzyć offsetu czasu serwera (rynek zamknięty?) i brak zapisanego pomiaru – uruchom przy otwartym rynku.")
            return 5
        now = datetime.now(timezone.utc)
        model = dst_model
        if model == "AUTO":
            model = "NY_CLOSE" if ny_close_offset(now.timestamp()) == int(offset) else "UNIFORM"
        elif model == "NY_CLOSE" and ny_close_offset(now.timestamp()) != int(offset):
            print("[BLAD] Model NY_CLOSE niezgodny z offsetem zmierzonym dziś – użyj --dst-model UNIFORM.")
            return 6
        cutoff = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 30)   # frozen BEFORE the first request
        start = (cutoff - timedelta(days=int(months * 30.44))).replace(hour=0, minute=0)
        out = Path(out_dir) if out_dir else paths.data_dir() / "forecast" / "history" / cutoff.strftime("%Y%m%dT%H%MZ")
        (out / "chunks").mkdir(parents=True, exist_ok=True)
        synthetic = bool(is_fake(mt5))
        dq: dict = {"symbol": sym, "cutoff_utc": iso(cutoff), "requested_from_utc": iso(start), "dst_model": model, "offset_seconds_now": offset,
                    "offset_basis": basis, "timeframes": {}}
        files = {}
        rows_by_tf: dict[str, dict[int, tuple]] = {}
        for tf, step in TFS.items():
            const = getattr(mt5, "TIMEFRAME_" + tf)
            merged: dict[int, tuple] = {}
            dup = 0
            revisions = []
            invalid = []
            requested = 0
            cur = start
            while cur < cutoff:
                nxt = min(cutoff, cur + timedelta(days=CHUNK_DAYS))
                ck = out / "chunks" / f"{tf}_{cur.strftime('%Y%m%d')}_{nxt.strftime('%Y%m%dT%H%M')}.json"
                if ck.exists():
                    part = [tuple(x) for x in json.loads(ck.read_text(encoding="utf-8"))]
                else:
                    margin = 4 * 3600                     # server-time query window must cover any offset of the model
                    r = mt5.copy_rates_range(sym, const, datetime.fromtimestamp(cur.timestamp() + offset - margin, timezone.utc),
                                             datetime.fromtimestamp(nxt.timestamp() + offset + margin, timezone.utc))
                    part = []
                    for x in (r if r is not None else []):
                        u, off, amb = server_to_utc(int(x["time"]), model, int(offset))
                        if cur.timestamp() <= u < nxt.timestamp() and u + step <= cutoff.timestamp():
                            part.append((u, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), int(x["tick_volume"]),
                                         int(x["spread"]), int(x["time"]), int(amb)))
                    ck.write_text(json.dumps(part), encoding="utf-8")
                requested += 1
                for p in part:
                    if p[0] in merged:
                        if merged[p[0]][1:5] == p[1:5]:
                            dup += 1
                        else:
                            revisions.append({"time_utc": iso(datetime.fromtimestamp(p[0], timezone.utc)), "first": merged[p[0]][1:5], "second": p[1:5]})
                    else:
                        merged[p[0]] = p
                cur = nxt
            for rv in revisions:                      # conflicting OHLC: dropped, never "last read wins"
                merged.pop(int(datetime.fromisoformat(rv["time_utc"].replace("Z", "+00:00")).timestamp()), None)
            for t in list(merged):
                _, o, h, lo, c = merged[t][:5]
                if not (o > 0 and h >= max(o, c) and lo <= min(o, c) and h >= lo):
                    invalid.append(iso(datetime.fromtimestamp(t, timezone.utc)))
                    merged.pop(t)
            ts = sorted(merged)
            rows_by_tf[tf] = merged
            path = out / f"XAUUSD_{tf}.csv"
            with path.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["time_open_utc", "open", "high", "low", "close", "tick_volume", "symbol", "spread_points", "time_server_raw", "dst_ambiguous"])
                for t in ts:
                    x = merged[t]
                    w.writerow([iso(datetime.fromtimestamp(t, timezone.utc)), x[1], x[2], x[3], x[4], x[5], sym, x[6], x[7], x[8]])
            days = sorted({datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in ts})
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            dq["timeframes"][tf] = {"rows": len(ts), "first_utc": iso(datetime.fromtimestamp(ts[0], timezone.utc)) if ts else None,
                                    "last_utc": iso(datetime.fromtimestamp(ts[-1], timezone.utc)) if ts else None, "chunks": requested,
                                    "identical_border_duplicates_removed": dup, "conflicting_revisions_dropped": revisions[:100],
                                    "conflicting_revisions_count": len(revisions), "invalid_geometry_dropped": invalid[:100],
                                    "invalid_geometry_count": len(invalid), "trading_days": len(days), "gaps": _gaps(ts, step),
                                    "dst_ambiguous_rows": sum(merged[t][8] for t in ts)}
            print(f"[OK] {tf}: {len(ts)} zamkniętych świec, {len(days)} dni, rewizje {len(revisions)}, błędna geometria {len(invalid)}")
        # M30 completeness against the six M5 bars of the same UTC bucket
        m5, m30 = rows_by_tf["M5"], rows_by_tf["M30"]
        complete = mismatch = incomplete = 0
        for t, x in m30.items():
            parts = [m5.get(t + k * 300) for k in range(6)]
            if any(p is None for p in parts):
                incomplete += 1
                continue
            complete += 1
            if (abs(parts[0][1] - x[1]) > tick or abs(max(p[2] for p in parts) - x[2]) > tick or abs(min(p[3] for p in parts) - x[3]) > tick
                    or abs(parts[-1][4] - x[4]) > tick):
                mismatch += 1
        days5 = dq["timeframes"]["M5"]["trading_days"]
        dq["m30_vs_m5"] = {"m30_with_6_m5": complete, "m30_without_complete_m5": incomplete, "ohlc_mismatch_beyond_1_tick": mismatch}
        dq["requested_vs_received"] = {"requested_months": months, "received_m5_first_utc": dq["timeframes"]["M5"]["first_utc"],
                                       "note": "Terminal może zwrócić krótszą historię (Narzędzia → Opcje → Wykresy → Maks. barów, dostępność u brokera)."}
        dq["warmup"] = {"m5_bars_needed_before_first_feature": 25, "m30_bars_needed": 24, "note": "pierwsze wiersze bez kompletnych cech są odrzucane przy treningu"}
        dq["sufficiency"] = {"trading_days_m5": days5, "estimated_holdout_days_20pct": round(days5 * 0.2, 1),
                             "target_holdout_days": 30, "status": "OK" if days5 * 0.2 >= 30 else "SHORT_FOR_30_HOLDOUT_DAYS"}
        dq["ticks"] = "NOT_EXPORTED – bez historii tickowej nie ma tickowego backtestu SL/TP, poślizgu ani częściowych realizacji"
        meta = {"symbol": sym, "data_kind": "SYNTHETIC_TEST" if synthetic else "REAL_USER_DATA",
                "source": "MT5_COPY_RATES_RANGE_VIA_MASTERQUO" + ("_FAKE_TERMINAL" if synthetic else ""),
                "price_basis": "BROKER_CHART_OHLC (MT5: zwykle Bid) – nie wykonywalne Ask/Bid", "tick_size": tick, "spec": spec,
                "time_basis": "SERVER_TIME_CONVERTED_TO_UTC", "dst_model": model, "offset_seconds_now": offset, "offset_basis": basis,
                "cutoff_utc": iso(cutoff), "range_utc": [dq["timeframes"]["M5"]["first_utc"], dq["timeframes"]["M5"]["last_utc"]],
                "m30_source": "BROKER_M30", "files_sha256": files, "account_server": getattr(acc, "server", None),
                "exported_at_utc": iso(datetime.now(timezone.utc)), "versions": {"python": platform.python_version(),
                                                                                "MetaTrader5": getattr(mt5, "__version__", None)}}
        (out / "source_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "DATA_QUALITY_REPORT.json").write_text(json.dumps(dq, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Zapisano: {out}")
        print(f"Zakres M5: {meta['range_utc'][0]} – {meta['range_utc'][1]}, dni handlowe {days5}, tick_size {tick}, czas: {model}")
        if dq["sufficiency"]["status"] != "OK":
            print(f"[UWAGA] {days5} dni handlowych – holdout 20% ≈ {days5 * 0.2:.0f} dni < 30 (trening badawczy z ograniczeniem albo dłuższa historia).")
        return 0
    finally:
        mt5.shutdown()                                # own connection of this standalone command
