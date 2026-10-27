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
import io
import json
import os
import platform
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..timeutil import iso

TFS = {"M5": 300, "M30": 1800}
ALL_TFS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
TRAINING_TFS = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
SCALP_TFS = ("M1", "M5", "M15", "M30", "H1")
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


class NoOrders:
    """The export (and every training process) reads history only: order functions of the MT5 module raise."""
    BLOCKED = ("order_send", "order_check", "order_calc_margin_send")

    def __init__(self, m):
        self._m = m                                   # is_fake() unwraps this attribute

    def __getattr__(self, name):
        if name in self.BLOCKED:
            raise RuntimeError(f"TRAINING_NO_ORDERS:{name}")
        return getattr(self._m, name)


def _commission(mt5, sym: str, days: int = 180) -> dict:
    """Commission per 1 lot per side from the account's own deal history of THIS symbol (read only). No deals -> UNKNOWN:
    the training then needs a value given by the user; nothing assumes a default for every instrument."""
    try:
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(days=days), now) or []
    except Exception as exc:                          # noqa: BLE001 - history is optional
        return {"source": "UNKNOWN", "reason": f"history_deals_get: {type(exc).__name__}"}
    per = sorted(abs(float(d.commission)) / float(d.volume) for d in deals
                 if getattr(d, "symbol", None) == sym and float(getattr(d, "volume", 0) or 0) > 0 and float(getattr(d, "commission", 0) or 0) != 0)
    if not per:
        return {"source": "UNKNOWN", "reason": f"brak transakcji {sym} z prowizją w ostatnich {days} dniach", "n_deals": 0}
    return {"source": "DEALS_HISTORY", "commission_per_lot_side": round(per[len(per) // 2], 4), "n_deals": len(per),
            "unit": "waluta rachunku za 1 lot na stronę (mediana)", "window_days": days}


# ===================================================================================== dataset files (1.25)
STATUS_FILE = "EXPORT_STATUS.json"
META_FILE = "source_metadata.json"
CSV_HEADER = ["time_open_utc", "open", "high", "low", "close", "tick_volume", "symbol", "spread_points", "time_server_raw", "dst_ambiguous",
              "real_volume"]
TICK_CHUNK_S = 3600
TICK_MAX_DAYS = 31


class ExportError(Exception):
    """A failure with a return code and a message that says what to do (printed instead of a traceback)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def atomic_write_text(p: Path, text: str) -> None:
    """Write next to the target, then replace it: an interrupted write never leaves a half file under the final name."""
    tmp = p.with_name(f"{p.name}.tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def _write_json(p: Path, obj) -> None:
    atomic_write_text(p, json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def read_status(ds: Path) -> dict | None:
    try:
        return json.loads((Path(ds) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dataset_state(ds: Path) -> dict:
    """COMPLETE | LEGACY_COMPLETE (export older than 1.25: metadata, no status file) | IN_PROGRESS | INTERRUPTED (process gone) |
    FAILED | CANCELLED | MISSING. Only COMPLETE / LEGACY_COMPLETE may be used for training."""
    ds = Path(ds)
    st = read_status(ds)
    has_meta = (ds / META_FILE).exists()
    if st is None:
        return {"state": "LEGACY_COMPLETE" if has_meta else "MISSING", "usable": has_meta}
    s = st.get("status")
    if s == "IN_PROGRESS":
        from ..training.core import _pid_alive
        if not _pid_alive(int(st.get("pid") or 0)):
            s = "INTERRUPTED"
    return {"state": s, "usable": s == "COMPLETE" and has_meta, "reason": st.get("reason"), "progress": st.get("progress"),
            "updated_at": st.get("updated_at")}


class _Status:
    def __init__(self, out: Path, base: dict):
        self.out, self.doc = out, dict(base)

    def set(self, **kw) -> None:
        self.doc.update(kw, updated_at=iso(datetime.now(timezone.utc)))
        _write_json(self.out / STATUS_FILE, self.doc)

    def progress(self, phase: str, item: str, done: int, total: int, **extra) -> None:
        self.set(progress={"phase": phase, "item": item, "done": done, "total": total, **extra})
        print(f"[POSTEP] eksport {item} {done}/{total}", flush=True)


def _read_chunk(ck: Path) -> list[tuple] | None:
    """A checkpoint of one request; None when missing or damaged (an interrupted write) - then it is fetched again."""
    if not ck.exists():
        return None
    try:
        return [tuple(x) for x in json.loads(ck.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        print(f"[UWAGA] uszkodzona partia {ck.name} (przerwany zapis) – pobieram ją ponownie")
        return None


def _offset_at(model: str, offset: int, utc_ts: float) -> int:
    from ..diagnostics import ny_close_offset
    return int(offset) if model == "UNIFORM" else ny_close_offset(utc_ts)


def export_ticks(mt5, sym: str, out: Path, t_from: datetime, t_to: datetime, model: str, offset: int, status: _Status | None = None) -> dict:
    """Bid/Ask ticks of [t_from, t_to) UTC in hourly requests (copy_ticks_range, COPY_TICKS_ALL), one compressed file per hour.
    Half-open UTC windows make chunk borders exact: nothing is de-duplicated, so several ticks with the same time_msc stay, in the
    order the terminal returned them (field `ord`). Times: server time of the terminal converted to UTC with the same model as the bars."""
    import numpy as np
    from ..diagnostics import server_to_utc
    d = out / "ticks"
    d.mkdir(parents=True, exist_ok=True)
    flag_all = getattr(mt5, "COPY_TICKS_ALL", -1)
    hours = []
    h = t_from.replace(minute=0, second=0, microsecond=0)
    while h < t_to:
        hours.append(h)
        h += timedelta(seconds=TICK_CHUNK_S)
    files, total, same_time, non_mono, empty_hours, first_ms, last_ms = {}, 0, 0, 0, 0, None, None
    for i, h in enumerate(hours):
        a_ms, b_ms = int(max(h, t_from).timestamp() * 1000), int(min(h + timedelta(seconds=TICK_CHUNK_S), t_to).timestamp() * 1000)
        f = d / f"ticks_{h.strftime('%Y%m%dT%H')}.npz"
        arr = None
        if f.exists():
            try:
                with np.load(f, allow_pickle=False) as z:
                    arr = {k: z[k] for k in z.files}
            except Exception:  # noqa: BLE001 - truncated npz (BadZipFile, EOFError, ValueError ...) = interrupted write
                print(f"[UWAGA] uszkodzony plik ticków {f.name} – pobieram ponownie")
                arr = None
        if arr is None:
            off = _offset_at(model, offset, a_ms / 1000)
            r = mt5.copy_ticks_range(sym, datetime.fromtimestamp(a_ms / 1000 + off - 120, timezone.utc),
                                     datetime.fromtimestamp(b_ms / 1000 + off + 120, timezone.utc), flag_all)
            rows = []
            for k, x in enumerate(r if r is not None else []):
                srv = int(x["time_msc"])
                u, o, _amb = server_to_utc(srv // 1000, model, int(offset))
                um = srv - o * 1000
                if a_ms <= um < b_ms:
                    rows.append((um, srv, float(x["bid"]), float(x["ask"]), float(x["last"]), int(x["volume"]),
                                 float(x["volume_real"]) if "volume_real" in x.dtype.names else 0.0, int(x["flags"]), k))
            arr = {"time_msc_utc": np.array([x[0] for x in rows], np.int64), "time_msc_server": np.array([x[1] for x in rows], np.int64),
                   "bid": np.array([x[2] for x in rows], float), "ask": np.array([x[3] for x in rows], float),
                   "last": np.array([x[4] for x in rows], float), "volume": np.array([x[5] for x in rows], np.int64),
                   "volume_real": np.array([x[6] for x in rows], float), "flags": np.array([x[7] for x in rows], np.int64),
                   "ord": np.arange(len(rows), dtype=np.int64)}
            tmp = f.with_name(f.name + f".tmp{os.getpid()}.npz")
            np.savez_compressed(tmp, **arr)
            os.replace(tmp, f)
        t = arr["time_msc_utc"]
        n = int(len(t))
        total += n
        if n == 0:
            empty_hours += 1
        else:
            dt = np.diff(t)
            same_time += int((dt == 0).sum())
            non_mono += int((dt < 0).sum())
            first_ms = int(t[0]) if first_ms is None else first_ms
            last_ms = int(t[-1])
        files[f.name] = {"ticks": n, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
        if status is not None and (i % 6 == 5 or i == len(hours) - 1):
            status.progress("ticks", "ticki", i + 1, len(hours), ticks=total)
    man = {"symbol": sym, "requested_utc": [iso(t_from), iso(t_to)],
           "received_utc": [iso(datetime.fromtimestamp(first_ms / 1000, timezone.utc)) if first_ms else None,
                            iso(datetime.fromtimestamp(last_ms / 1000, timezone.utc)) if last_ms else None],
           "ticks": total, "hours": len(hours), "empty_hours": empty_hours, "same_time_msc_neighbours": same_time,
           "non_monotonic_steps": non_mono, "files": files, "chunk": "1 h UTC, półotwarte [od, do) – bez usuwania ticków o tym samym czasie",
           "fields": {"time_msc_utc": "czas UTC [ms]", "time_msc_server": "czas serwera z terminala [ms]", "bid": "Bid", "ask": "Ask",
                      "last": "Last (dla CFD/FX zwykle 0)", "volume": "wolumen ticku (dla CFD zwykle 0)", "volume_real": "wolumen rzeczywisty, jeśli broker podaje",
                      "flags": "flagi MT5 TICK_FLAG_* (2 BID, 4 ASK, 8 LAST, 16 VOLUME, ...)", "ord": "kolejność w odpowiedzi terminala"},
           "note": "Ticki to notowania brokera, nie książka zleceń i nie wolumen giełdowy."}
    if first_ms and first_ms > t_from.timestamp() * 1000 + 6 * 3600 * 1000:
        man["warning"] = ("TERMINAL_RETURNED_SHORTER_TICK_HISTORY – terminal zwrócił ticki od "
                          f"{man['received_utc'][0]} (żądano od {iso(t_from)}); historia ticków u brokera może być krótsza")
    _write_json(d / "TICKS_MANIFEST.json", man)
    return {k: man[k] for k in ("requested_utc", "received_utc", "ticks", "empty_hours", "same_time_msc_neighbours", "non_monotonic_steps")} | (
        {"warning": man["warning"]} if "warning" in man else {})


class _DstModelMismatch(Exception):
    """NY_CLOSE gave two bars the same UTC time next to a US DST switch: the server clock did not jump -> fixed offset (UNIFORM)."""


def us_dst_switches(t0: float, t1: float) -> list[float]:
    """UTC instants of the America/New_York offset changes in [t0, t1] (2:00 local, Sunday - FX/gold markets are closed)."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    out, prev = [], None
    t = int(t0 // 3600 * 3600)
    while t <= t1:
        off = datetime.fromtimestamp(t, timezone.utc).astimezone(ny).utcoffset()
        if prev is not None and off != prev:
            out.append(float(t))
        prev = off
        t += 3600
    return out


def dst_model_probe(mt5, sym: str, now: datetime) -> dict:
    """Evidence for the broker's time convention from H1 history of the last ~13 months: the server time of the weekly market open in
    US winter vs US summer. The open is tied to New York time, so a server that follows New York (NY_CLOSE, "NY close = 00:00") shows
    the SAME server time in both seasons; a fixed-offset server shows it one hour apart (UNIFORM). Too few weeks -> UNVERIFIED."""
    from ..diagnostics import ny_close_offset
    try:
        r = mt5.copy_rates_range(sym, getattr(mt5, "TIMEFRAME_H1"), now - timedelta(days=400), now + timedelta(hours=6))
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "UNVERIFIED", "reason": f"copy_rates_range H1: {type(exc).__name__}"}
    times = [int(x["time"]) for x in (r if r is not None else [])]
    opens = {"US_SUMMER": [], "US_WINTER": []}
    for a, b in zip(times, times[1:]):
        if b - a > 36 * 3600:                                         # first bar after a weekend
            season = "US_SUMMER" if ny_close_offset(b - 3 * 3600) == 10800 else "US_WINTER"
            dw = datetime.fromtimestamp(b, timezone.utc)                # server wall clock (epoch of server time)
            opens[season].append(dw.weekday() * 86400 + dw.hour * 3600 + dw.minute * 60)
    mode = {k: (max(set(v), key=v.count) if v else None) for k, v in opens.items()}
    n = {k: len(v) for k, v in opens.items()}
    if min(n.values()) < 3:
        return {"verdict": "UNVERIFIED", "weekly_opens": n, "reason": "za mało weekendów w obu sezonach (historia H1 terminala)"}
    diff = (mode["US_WINTER"] - mode["US_SUMMER"]) % (7 * 86400)
    if diff == 0:
        return {"verdict": "NY_CLOSE", "weekly_opens": n, "server_open_seconds_of_week": mode}
    if diff == 3600:
        return {"verdict": "UNIFORM", "weekly_opens": n, "server_open_seconds_of_week": mode,
                "reason": "otwarcie tygodnia przesuwa się o 1 h między sezonami – serwer ma stały offset"}
    return {"verdict": "UNVERIFIED", "weekly_opens": n, "server_open_seconds_of_week": mode, "reason": f"niejednoznaczna różnica {diff} s"}


def _parse_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def export_candles(months: int = 12, out_dir: str | None = None, dst_model: str = "AUTO", timeframes: tuple[str, ...] = ("M5", "M30"),
                   kind: str = "forecast", instrument: str | None = None, symbol: str | None = None, *, date_from: str | None = None,
                   date_to: str | None = None, tick_days: float = 0.0) -> int:
    """kind="forecast": M5/M30 for gold_candles; kind="scalp": M1/M5/M15/M30/H1 for the scalp profile (data/scalp/history);
    kind="training": every TF of one instrument into data/training/datasets/<INST>/<dataset_id> (the training installer).
    instrument: XAUUSD (default, historical paths/file names) or BTC; symbol: the EXACT broker symbol (never normalised).
    date_from / date_to (UTC ISO) replace `months`; tick_days > 0 adds Bid/Ask ticks of the LAST tick_days of the range (separate
    size choice, at most 31 days). Progress, result and failures are in EXPORT_STATUS.json; source_metadata.json is written last, so
    an interrupted export is never read as complete. A repeated export into the same folder continues the same frozen range."""
    try:
        return _export(months, out_dir, dst_model, timeframes, kind, instrument, symbol, date_from, date_to, tick_days)
    except ExportError as exc:
        print(f"[BLAD] {exc}")
        return exc.code


def _fail_status(st: _Status | None, code: int, msg: str) -> ExportError:
    if st is not None:
        try:
            st.set(status="FAILED", reason=msg, return_code=code)
        except OSError:
            pass
    return ExportError(code, msg)


def _export(months, out_dir, dst_model, timeframes, kind, instrument, symbol, date_from, date_to, tick_days) -> int:
    import mq_instruments as mi
    from ..config import ConfigStore
    from ..diagnostics import attach, ny_close_offset, server_to_utc
    from ..mt5.fake import is_fake
    from ..mt5 import login as lg
    cfg = ConfigStore().get()
    inst = mi.current(instrument)
    m = cfg.assets.mappings.get(inst)
    sym = symbol or (m.broker_symbol if m and m.broker_symbol else None) or (cfg.mt5.symbol if inst == "XAUUSD" else None)
    if not sym:
        raise ExportError(4, f"Brak symbolu brokera dla {inst} – wybierz go w kreatorze (np. {mi.profile(inst)['default_broker_symbol']}).")
    prefix = mi.file_prefix(inst)
    d_from, d_to = _parse_utc(date_from), _parse_utc(date_to)
    if d_from is None and not 1 <= months <= 36:
        raise ExportError(2, "--months 1..36 (albo zakres --from/--to)")
    if d_from is not None and d_to is not None and d_to <= d_from:
        raise ExportError(2, "--to musi być późniejsze niż --from")
    if not 0 <= float(tick_days or 0) <= TICK_MAX_DAYS:
        raise ExportError(2, f"--ticks-days 0..{TICK_MAX_DAYS} (ticki zajmują dużo miejsca – wybierz krótki zakres)")
    unknown = [t for t in timeframes if t not in ALL_TFS]
    if unknown:
        raise ExportError(2, f"nieznane interwały {unknown} – dozwolone {list(ALL_TFS)}")
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise ExportError(3, "BLOCKED_NO_MT5: brak pakietu MetaTrader5 (eksport działa na Windows z zainstalowanym i zalogowanym MT5).") from None
    mt5 = NoOrders(mt5)
    if not attach(mt5, cfg):
        err = mt5.last_error()
        raise ExportError(3, f"initialize(): {err} {lg.hint(err)} – uruchom i zaloguj terminal MT5 (ścieżkę terminal64.exe ustawisz w "
                             "Konfiguracji MT5, gdy masz kilka instalacji).")
    st = None
    try:
        info = mt5.symbol_info(sym)
        if info is None or not mt5.symbol_select(sym, True):
            raise ExportError(4, f"Symbol {sym} niedostępny w terminalu – włącz go w Market Watch (Ctrl+U) albo wybierz dokładną nazwę; "
                                 "program nie podmienia symbolu.")
        spec = {k: getattr(info, k, None) for k in ("name", "digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size",
                                                     "currency_base", "currency_profit", "currency_margin", "volume_min", "volume_step")}
        for k in ("trade_calc_mode", "volume_max", "swap_long", "swap_short", "trade_stops_level", "description", "path"):
            spec[k] = getattr(info, k, None)
        ok_meta, problems = mi.check_metadata(inst, spec)
        if not ok_meta:
            raise ExportError(4, f"{sym} nie pasuje do profilu {inst} ({', '.join(problems)}; base={spec['currency_base']}, "
                                 f"profit={spec['currency_profit']}).")
        tick = float(spec["trade_tick_size"] or 0)
        if tick <= 0 or float(spec["trade_contract_size"] or 0) <= 0:
            raise ExportError(4, "Nieprawidłowa specyfikacja kontraktu (tick_size / contract_size).")
        acc = mt5.account_info()
        now = datetime.now(timezone.utc)
        # ---------------- output folder + frozen request (a repeated export into the same folder continues the same range)
        req_key = {"instrument": inst, "symbol": sym, "timeframes": list(timeframes), "kind": kind, "date_from": date_from, "date_to": date_to,
                   "months": None if d_from else months, "tick_days": float(tick_days or 0), "dst_model_requested": dst_model}
        out = Path(out_dir) if out_dir else None
        prev = read_status(out) if out is not None else None
        resume = bool(prev and prev.get("request") == req_key and prev.get("status") != "COMPLETE" and prev.get("frozen"))
        if resume:
            fr = prev["frozen"]
            model, offset, basis = fr["dst_model"], fr["offset_seconds"], fr["offset_basis"] + "_RESUMED"
            start, cutoff = _parse_utc(fr["from_utc"]), _parse_utc(fr["cutoff_utc"])
            print(f"[..] Wznawiam eksport {fr['from_utc']} – {fr['cutoff_utc']} (partie już pobrane nie są pobierane ponownie)")
        else:
            offset, basis = _measure_offset(mt5, sym, getattr(acc, "server", None))
            if offset is None:
                raise ExportError(5, "Nie można zmierzyć offsetu czasu serwera (rynek zamknięty?) i brak zapisanego pomiaru – uruchom przy "
                                     "otwartym rynku.")
            model = dst_model
            if model == "AUTO":
                today = "NY_CLOSE" if ny_close_offset(now.timestamp()) == int(offset) else "UNIFORM"
                probe = dst_model_probe(mt5, sym, now)
                if today == "NY_CLOSE" and probe["verdict"] == "UNIFORM":
                    model, basis = "UNIFORM", f"{basis}+PROBE_FIXED_OFFSET"             # today's offset equals NY+7 only by season
                else:
                    model = today
                    basis = f"{basis}+PROBE_{probe['verdict']}"
                print(f"[..] Konwencja czasu serwera: {model} (offset dziś {int(offset) // 3600} h; dowód z historii: {probe['verdict']})")
            elif model == "NY_CLOSE" and ny_close_offset(now.timestamp()) != int(offset):
                raise ExportError(6, "Model NY_CLOSE niezgodny z offsetem zmierzonym dziś – użyj --dst-model UNIFORM.")
            last_closed = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 30)   # frozen BEFORE the first request
            cutoff = min(d_to, last_closed) if d_to else last_closed
            start = d_from if d_from else (cutoff - timedelta(days=int(months * 30.44))).replace(hour=0, minute=0)
            if start >= cutoff:
                raise ExportError(2, f"zakres {iso(start)} – {iso(cutoff)} jest pusty (koniec w przyszłości jest przycinany do ostatniej zamkniętej świecy)")
        dataset_id = (f"{inst}_{cutoff.strftime('%Y%m%dT%H%MZ')}_{months}m" if not d_from
                      else f"{inst}_{start.strftime('%Y%m%dT%H%MZ')}_{cutoff.strftime('%Y%m%dT%H%MZ')}")
        if out is None:
            out = (mi.data_dir() / "training" / "datasets" / inst / dataset_id if kind == "training"
                   else mi.root(kind, inst) / "history" / cutoff.strftime("%Y%m%dT%H%MZ"))
        try:
            (out / "chunks").mkdir(parents=True, exist_ok=True)
            if (out / META_FILE).exists():                # metadata of an older export in this folder: it must not describe new files
                (out / META_FILE).unlink()
            st = _Status(out, {"status": "IN_PROGRESS", "pid": os.getpid(), "started_at": iso(now), "request": req_key, "dataset_id": dataset_id,
                               "frozen": {"from_utc": iso(start), "cutoff_utc": iso(cutoff), "dst_model": model, "offset_seconds": offset,
                                          "offset_basis": basis}})
            st.set()
        except PermissionError:
            raise ExportError(7, f"Brak uprawnień do zapisu w {out} – wybierz folder w swoim profilu użytkownika (np. Dokumenty) albo zmień "
                                 "uprawnienia folderu.") from None
        except OSError as exc:
            raise ExportError(8, f"Nie można utworzyć folderu {out}: {exc.strerror or exc} (miejsce na dysku, długość ścieżki, uprawnienia).") from None
        synthetic = bool(is_fake(mt5))
        try:
            try:
                _bars_and_reports(mt5, sym, inst, prefix, out, st, timeframes, start, cutoff, model, offset, basis, tick, spec, acc, synthetic,
                                  dataset_id, months, d_from, d_to, tick_days, server_to_utc, auto=dst_model == "AUTO")
            except _DstModelMismatch as mm:
                print(f"[UWAGA] {mm} – serwer nie przestawia zegara z Nowym Jorkiem; eksport od nowa w modelu UNIFORM")
                import shutil
                shutil.rmtree(out / "chunks", ignore_errors=True)        # checkpoints hold UTC times of the rejected model
                shutil.rmtree(out / "ticks", ignore_errors=True)
                (out / "chunks").mkdir(parents=True, exist_ok=True)
                model, basis = "UNIFORM", f"{basis}+AUTO_SWITCH_NY_CLOSE_COLLISIONS"
                st.set(frozen=dict(st.doc["frozen"], dst_model=model, offset_basis=basis))
                _bars_and_reports(mt5, sym, inst, prefix, out, st, timeframes, start, cutoff, model, offset, basis, tick, spec, acc, synthetic,
                                  dataset_id, months, d_from, d_to, tick_days, server_to_utc, auto=False)
        except PermissionError as exc:
            raise _fail_status(st, 7, f"Brak uprawnień do zapisu ({exc.filename}) – zamknij programy, które trzymają plik, albo wybierz inny folder.") from None
        except OSError as exc:
            import errno
            if exc.errno == errno.ENOSPC:
                raise _fail_status(st, 8, f"Brak miejsca na dysku podczas zapisu do {out} – zwolnij miejsce i uruchom eksport ponownie "
                                          "(pobrane partie zostaną użyte).") from None
            raise _fail_status(st, 8, f"Błąd zapisu {exc.filename or out}: {exc.strerror or exc}") from None
        except ExportError as exc:
            raise _fail_status(st, exc.code, str(exc)) from None
        except KeyboardInterrupt:
            if st is not None:
                st.set(status="CANCELLED", reason="przerwane przez użytkownika – ponowienie wznowi eksport od pobranych partii")
            raise
        except Exception as exc:  # noqa: BLE001 - unexpected: recorded, re-raised with the traceback
            if st is not None:
                st.set(status="FAILED", reason=f"{type(exc).__name__}: {exc}"[:500], return_code=1)
            raise
        return 0
    finally:
        mt5.shutdown()                                # own connection of this standalone command


def _bars_and_reports(mt5, sym, inst, prefix, out, st, timeframes, start, cutoff, model, offset, basis, tick, spec, acc, synthetic, dataset_id,
                      months, d_from, d_to, tick_days, server_to_utc, auto: bool = False) -> None:
    import mq_instruments as mi
    dq: dict = {"symbol": sym, "cutoff_utc": iso(cutoff), "requested_from_utc": iso(start), "dst_model": model, "offset_seconds_now": offset,
                "offset_basis": basis, "timeframes": {}}
    files = {}
    rows_by_tf: dict[str, dict[int, tuple]] = {}
    for tf, step in ((k, ALL_TFS[k]) for k in timeframes):
        const = getattr(mt5, "TIMEFRAME_" + tf)
        merged: dict[int, tuple] = {}
        dup = 0
        revisions = []
        invalid = []
        requested = 0
        windows = []
        cur = start
        while cur < cutoff:
            nxt = min(cutoff, cur + timedelta(days=CHUNK_DAYS))
            windows.append((cur, nxt))
            cur = nxt
        for wi, (cur, nxt) in enumerate(windows):
            ck = out / "chunks" / f"{tf}_{cur.strftime('%Y%m%d')}_{nxt.strftime('%Y%m%dT%H%M')}.json"
            part = _read_chunk(ck)
            if part is None:
                margin = 4 * 3600                     # server-time query window must cover any offset of the model
                r = mt5.copy_rates_range(sym, const, datetime.fromtimestamp(cur.timestamp() + offset - margin, timezone.utc),
                                         datetime.fromtimestamp(nxt.timestamp() + offset + margin, timezone.utc))
                part = []
                has_rv = r is not None and "real_volume" in (r.dtype.names or ())
                for x in (r if r is not None else []):
                    u, off, amb = server_to_utc(int(x["time"]), model, int(offset))
                    if cur.timestamp() <= u < nxt.timestamp() and u + step <= cutoff.timestamp():
                        part.append((u, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), int(x["tick_volume"]),
                                     int(x["spread"]), int(x["time"]), int(amb), int(x["real_volume"]) if has_rv else None))
                atomic_write_text(ck, json.dumps(part))
            requested += 1
            for p in part:
                if len(p) == 9:                       # checkpoint written before 1.25 (no real_volume)
                    p = (*p, None)
                if p[0] in merged:
                    if merged[p[0]][1:5] == p[1:5]:
                        dup += 1
                    else:
                        revisions.append({"time_utc": iso(datetime.fromtimestamp(p[0], timezone.utc)), "first": merged[p[0]][1:5], "second": p[1:5]})
                else:
                    merged[p[0]] = p
            st.progress("bars", tf, wi + 1, len(windows), rows=len(merged))
        if auto and model == "NY_CLOSE" and revisions:
            sw = us_dst_switches(start.timestamp() - 86400, cutoff.timestamp() + 86400)
            near = [rv for rv in revisions if any(abs(datetime.fromisoformat(rv["time_utc"].replace("Z", "+00:00")).timestamp() - s) <= 2 * 3600
                                                  for s in sw)]
            if near and len(near) == len(revisions):
                raise _DstModelMismatch(f"{tf}: {len(near)} świec NY_CLOSE trafia w ten sam czas UTC przy zmianie czasu w USA")
        for rv in revisions:                          # conflicting OHLC: dropped, never "last read wins"
            merged.pop(int(datetime.fromisoformat(rv["time_utc"].replace("Z", "+00:00")).timestamp()), None)
        for t in list(merged):
            _, o, h, lo, c = merged[t][:5]
            if not (o > 0 and h >= max(o, c) and lo <= min(o, c) and h >= lo):
                invalid.append(iso(datetime.fromtimestamp(t, timezone.utc)))
                merged.pop(t)
        ts = sorted(merged)
        rows_by_tf[tf] = merged
        path = out / f"{prefix}_{tf}.csv"
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(CSV_HEADER)
        for t in ts:
            x = merged[t]
            w.writerow([iso(datetime.fromtimestamp(t, timezone.utc)), x[1], x[2], x[3], x[4], x[5], sym, x[6], x[7], x[8],
                        "" if x[9] is None else x[9]])
        atomic_write_text(path, buf.getvalue())
        days = sorted({datetime.fromtimestamp(t, timezone.utc).date().isoformat() for t in ts})
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        first = ts[0] if ts else None
        short_days = round((first - start.timestamp()) / 86400, 1) if first else None
        rv_known = sum(1 for t in ts if merged[t][9])
        dq["timeframes"][tf] = {"rows": len(ts), "first_utc": iso(datetime.fromtimestamp(ts[0], timezone.utc)) if ts else None,
                                "last_utc": iso(datetime.fromtimestamp(ts[-1], timezone.utc)) if ts else None, "chunks": requested,
                                "identical_border_duplicates_removed": dup, "conflicting_revisions_dropped": revisions[:100],
                                "conflicting_revisions_count": len(revisions), "invalid_geometry_dropped": invalid[:100],
                                "invalid_geometry_count": len(invalid), "trading_days": len(days), "gaps": _gaps(ts, step),
                                "dst_ambiguous_rows": sum(merged[t][8] for t in ts), "real_volume_nonzero_rows": rv_known,
                                "history_shorter_than_requested_days": short_days if short_days and short_days > 3 else 0}
        if not ts:
            print(f"[UWAGA] {tf}: terminal nie zwrócił żadnej zamkniętej świecy w zakresie {iso(start)} – {iso(cutoff)}")
        elif short_days and short_days > 3:
            print(f"[UWAGA] {tf}: historia od {dq['timeframes'][tf]['first_utc']} – krótsza o {short_days} dni niż żądano "
                  "(MT5: Narzędzia → Opcje → Wykresy → Maks. słupków na wykresie; dostępność historii u brokera)")
        print(f"[OK] {tf}: {len(ts)} zamkniętych świec, {len(days)} dni, rewizje {len(revisions)}, błędna geometria {len(invalid)}")
    # M30 completeness against the six M5 bars of the same UTC bucket
    m5, m30 = rows_by_tf.get("M5", {}), rows_by_tf.get("M30", {})
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
    base_tf = "M5" if "M5" in dq["timeframes"] else timeframes[0]
    days5 = dq["timeframes"][base_tf]["trading_days"]
    dq["m30_vs_m5"] = {"m30_with_6_m5": complete, "m30_without_complete_m5": incomplete, "ohlc_mismatch_beyond_1_tick": mismatch}
    dq["requested_vs_received"] = {"requested_months": None if d_from else months, "requested_from_utc": iso(start), "requested_to_utc": iso(cutoff),
                                   "received_first_utc": {tf: v["first_utc"] for tf, v in dq["timeframes"].items()},
                                   "received_rows": {tf: v["rows"] for tf, v in dq["timeframes"].items()},
                                   "note": "Terminal może zwrócić krótszą historię (Narzędzia → Opcje → Wykresy → Maks. barów, dostępność u brokera)."}
    dq["warmup"] = {"m5_bars_needed_before_first_feature": 25, "m30_bars_needed": 24, "note": "pierwsze wiersze bez kompletnych cech są odrzucane przy treningu"}
    dq["sufficiency"] = {"trading_days_m5": days5, "estimated_holdout_days_20pct": round(days5 * 0.2, 1),
                         "target_holdout_days": 30, "status": "OK" if days5 * 0.2 >= 30 else "SHORT_FOR_30_HOLDOUT_DAYS"}
    dq["columns"] = {"tick_volume": "liczba zmian ceny (ticków) w świecy – NIE jest wolumenem giełdowym",
                     "real_volume": "wolumen rzeczywisty, jeśli broker go podaje (dla CFD zwykle 0 / puste)",
                     "spread_points": "spread w punktach zapisany przez terminal dla świecy (x spec.point = cena)",
                     "price_basis": "OHLC wykresu brokera (MT5: zwykle Bid)"}
    if tick_days and float(tick_days) > 0:
        t_from = max(start, cutoff - timedelta(days=float(tick_days)))
        print(f"[..] Ticki Bid/Ask {iso(t_from)} – {iso(cutoff)} (partie 1 h)")
        dq["ticks"] = export_ticks(mt5, sym, out, t_from, cutoff, model, offset, st)
        print(f"[OK] Ticki: {dq['ticks']['ticks']} (ten sam czas ms: {dq['ticks']['same_time_msc_neighbours']} – zachowane)")
    else:
        dq["ticks"] = "NOT_EXPORTED – bez historii tickowej kolejność TP/SL w jednej świecy jest niejednoznaczna (oznaczana), brak poślizgu z ticków"
    costs = _commission(mt5, sym)
    meta = {"symbol": sym, "instrument": inst, "canonical_asset": mi.profile(inst)["canonical_asset"], "file_prefix": prefix,
            "dataset_id": dataset_id, "requested_months": None if d_from else months, "requested_range_utc": [iso(start), iso(cutoff)], "costs": costs,
            "quote_currency": spec["currency_profit"], "account_currency": getattr(acc, "currency", None), "data_kind": "SYNTHETIC_TEST" if synthetic else "REAL_USER_DATA",
            "source": "MT5_COPY_RATES_RANGE_VIA_MASTERQUO" + ("_FAKE_TERMINAL" if synthetic else ""),
            "price_basis": "BROKER_CHART_OHLC (MT5: zwykle Bid) – nie wykonywalne Ask/Bid", "tick_size": tick, "spec": spec,
            "time_basis": "SERVER_TIME_CONVERTED_TO_UTC", "dst_model": model, "offset_seconds_now": offset, "offset_basis": basis,
            "cutoff_utc": iso(cutoff), "range_utc": [dq["timeframes"][base_tf]["first_utc"], dq["timeframes"][base_tf]["last_utc"]],
            "m30_source": "BROKER_M30", "higher_tf_join_rule": "wyższy TF dołączany dopiero od available_at = open + długość świecy (świeca zamknięta)",
            "timeframes": list(timeframes), "spread_unit": "points (x spec.point = price)", "files_sha256": files, "account_server": getattr(acc, "server", None),
            "csv_columns": CSV_HEADER, "ticks": "ticks/TICKS_MANIFEST.json" if isinstance(dq["ticks"], dict) else None,
            "exported_at_utc": iso(datetime.now(timezone.utc)), "versions": {"python": platform.python_version(),
                                                                            "MetaTrader5": getattr(mt5, "__version__", None)}}
    _write_json(out / "DATA_QUALITY_REPORT.json", dq)
    _write_json(out / META_FILE, meta)
    st.set(status="COMPLETE", reason=None, return_code=0, files_sha256=files, range_utc=meta["range_utc"], data_kind=meta["data_kind"],
           finished_at=iso(datetime.now(timezone.utc)), progress={"phase": "done", "item": "gotowe", "done": 1, "total": 1})
    from ..training import requirements as RQ
    readiness = RQ.check_dataset(out)                 # model -> required data -> file -> status, for THIS export
    _write_json(out / "MODEL_DATA_READINESS.json", readiness)
    print(f"Zapisano: {out}")
    print(f"Prowizja: {costs.get('commission_per_lot_side', 'NIEZNANA')} ({costs['source']})")
    print(f"Zakres {base_tf}: {meta['range_utc'][0]} – {meta['range_utc'][1]}, dni handlowe {days5}, tick_size {tick}, czas: {model}")
    for row in readiness["models"]:
        print(f"  {row['status']:<18} {row['kind']:<24} {row['reason']}")
    if dq["sufficiency"]["status"] != "OK":
        print(f"[UWAGA] {days5} dni handlowych – holdout 20% ≈ {days5 * 0.2:.0f} dni < 30 (trening badawczy z ograniczeniem albo dłuższa historia).")
