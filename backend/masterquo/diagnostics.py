"""Console diagnostics for Windows users (02_DIAGNOSTYKA.bat, 06_DIAGNOZA_CZASU_MT5.bat).

Read-only: no order functions are called. Reports are written to data/logs/ without secrets.
"""
from __future__ import annotations

import getpass
import importlib
import json
import platform
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from .timeutil import TIMEFRAMES, iso

OK, WARN, FAIL = "OK  ", "UWAGA", "BŁĄD"


def _line(status: str, text: str) -> None:
    print(f"[{status}] {text}")


def _save(name: str, data: dict) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p = paths.logs_dir() / f"{name}_{stamp}.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return str(p)


def doctor() -> int:
    from .config import ConfigStore
    from .secrets_store import SecretStore
    rep: dict = {"generated_at": iso(datetime.now(timezone.utc)), "checks": []}
    bad = 0

    def chk(name, status, detail):
        nonlocal bad
        rep["checks"].append({"check": name, "status": status.strip(), "detail": detail})
        _line(status, f"{name}: {detail}")
        if status == FAIL:
            bad += 1
    bits = struct.calcsize("P") * 8
    chk("Python", OK if sys.version_info[:2] in ((3, 12), (3, 13)) and bits == 64 else (WARN if bits == 64 else FAIL),
        f"{sys.version.split()[0]} {bits}-bit ({sys.executable})")
    chk("System", OK if sys.platform == "win32" else WARN, platform.platform())
    for mod in ("fastapi", "uvicorn", "pydantic", "anthropic", "numpy", "websockets", "scipy", "sklearn", "xgboost", "joblib", "cryptography", "jwt"):
        try:
            m = importlib.import_module(mod)
            chk(f"Pakiet {mod}", OK, getattr(m, "__version__", "?"))
        except Exception as exc:
            chk(f"Pakiet {mod}", FAIL, f"{type(exc).__name__}: {exc}")
    # ML smoke test: both model families really fit and predict on this machine (tiny synthetic arrays, CPU, 1 thread)
    try:
        import numpy as np
        from sklearn.tree import DecisionTreeClassifier
        import xgboost as xgb
        rng = np.random.default_rng(0)
        X = rng.normal(size=(80, 3))
        X[::7, 1] = np.nan
        y = (X[:, 0] > 0).astype(int)
        DecisionTreeClassifier(max_depth=2, random_state=0).fit(X, y).predict_proba(X)
        xgb.XGBClassifier(n_estimators=5, max_depth=2, n_jobs=1, tree_method="hist").fit(X, y).predict_proba(X)
        chk("ML: Decision Tree + XGBoost (test działania)", OK, "trening i predykcja na danych testowych OK (to nie jest model handlowy)")
    except Exception as exc:
        chk("ML: Decision Tree + XGBoost (test działania)", FAIL, f"{type(exc).__name__}: {exc}")
    cfg = ConfigStore().get()
    chk("Symbol brokera (config)", OK, cfg.mt5.symbol)
    # central account / license server (HTTPS, certificate validated)
    if not cfg.central.url:
        chk("Serwer kont i licencji", WARN, "adres nie ustawiony – wpisz go w monitorze na ekranie logowania")
    else:
        try:
            from .licensing.central_client import CentralClient
            h = CentralClient(cfg.central.url, allow_insecure_localhost=cfg.central.allow_insecure_localhost)._req("GET", "/api/v1/health")
            chk("Serwer kont i licencji", OK if not h.get("clock_anomaly") else WARN,
                f"{cfg.central.url} odpowiada (czas serwera {h.get('server_time')}){' – ANOMALIA ZEGARA' if h.get('clock_anomaly') else ''}")
        except Exception as exc:
            chk("Serwer kont i licencji", FAIL, f"{cfg.central.url}: {getattr(exc, 'code', type(exc).__name__)}")
    dist = paths.FRONTEND_DIST / "index.html"
    chk("Frontend (frontend/dist)", OK if dist.exists() else FAIL, str(dist))
    # MT5
    try:
        import MetaTrader5 as mt5
        chk("Pakiet MetaTrader5", OK, getattr(mt5, "__version__", "?"))
        ok = mt5.initialize(path=cfg.mt5.terminal_path) if cfg.mt5.terminal_path else mt5.initialize()
        if not ok:
            chk("Połączenie z terminalem MT5", FAIL, f"initialize() = False, last_error={mt5.last_error()} – uruchom i zaloguj MT5 (lub ustaw mt5.terminal_path)")
        else:
            t = mt5.terminal_info()
            a = mt5.account_info()
            chk("Terminal MT5", OK if t and t.connected else WARN, f"{getattr(t, 'name', '?')} build {getattr(t, 'build', '?')} path={getattr(t, 'path', '?')} connected={getattr(t, 'connected', '?')}")
            if a is None:
                chk("Rachunek", FAIL, "Brak zalogowanego rachunku w terminalu")
            else:
                mode = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(a.trade_mode, a.trade_mode)
                chk("Rachunek", OK, f"login {a.login} serwer {a.server} waluta {a.currency} typ {mode}")
            info = mt5.symbol_info(cfg.mt5.symbol)
            if info is None:
                cands = sorted({s.name for s in (mt5.symbols_get(group="*XAU*,*GOLD*") or ())})[:20]
                chk(f"Symbol {cfg.mt5.symbol}", FAIL, f"nie istnieje u brokera. Kandydaci: {', '.join(cands) or 'brak'} (program NIE zamienia symbolu samodzielnie)")
            else:
                mt5.symbol_select(cfg.mt5.symbol, True)
                chk(f"Symbol {cfg.mt5.symbol}", OK, f"digits {info.digits} point {info.point} min lot {info.volume_min} step {info.volume_step} trade_mode {info.trade_mode}")
                for tf in TIMEFRAMES:
                    r = mt5.copy_rates_from_pos(cfg.mt5.symbol, getattr(mt5, "TIMEFRAME_" + tf), 0, 600)
                    n = 0 if r is None else len(r)
                    chk(f"Historia {tf}", OK if n >= 300 else WARN, f"{n} świec dostępnych w terminalu")
            mt5.shutdown()
    except ImportError as exc:
        chk("Pakiet MetaTrader5", FAIL if sys.platform == "win32" else WARN, f"{exc} (działa tylko na Windows)")
    # Claude
    sec = SecretStore()
    src = sec.source("ANTHROPIC_API_KEY")
    model = cfg.agent.model or __import__("os").environ.get("ANTHROPIC_MODEL")
    chk("Klucz Anthropic", OK if src != "MISSING" else WARN, f"źródło: {src} (wartość nie jest wyświetlana)")
    chk("Model Claude (ANTHROPIC_MODEL)", OK if model else WARN, model or "nie ustawiono – wybierz w monitorze (Ustawienia → Agent)")
    if src != "MISSING" and model:
        try:
            import anthropic
            c = anthropic.Anthropic(api_key=sec.get("ANTHROPIC_API_KEY"), timeout=20, max_retries=0)
            m = c.models.retrieve(model)
            chk("Test API Claude", OK, f"model dostępny: {m.id}")
        except Exception as exc:
            chk("Test API Claude", FAIL, f"{type(exc).__name__}: {str(exc)[:160]}")
    path = _save("diagnostyka", rep)
    print(f"\nRaport zapisano: {path}")
    print("WYNIK:", "BRAK BŁĘDÓW KRYTYCZNYCH" if not bad else f"{bad} BŁĘDÓW – patrz wyżej")
    return 0 if not bad else 1


def clock() -> int:
    """Raw MT5 time evidence: tick and bar epochs as received, PC UTC, measured offset."""
    from .config import ConfigStore
    from .data.pcclock import PCClockCheck
    from .mt5.clock import ServerClock
    cfg = ConfigStore().get()
    out: dict = {"generated_at": iso(datetime.now(timezone.utc)), "symbol": cfg.mt5.symbol, "trading_calls": "NONE"}
    pc = PCClockCheck(cfg.clock.reference_url, cfg.clock.max_pc_clock_skew_seconds).check()
    out["pc_clock_vs_reference"] = pc
    _line(OK if pc.get("status") == "OK" else WARN, f"Zegar PC vs {pc.get('source')}: {pc.get('status')} skew={pc.get('skew_seconds')} s")
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        _line(FAIL, f"Brak pakietu MetaTrader5: {exc}")
        print(_save("diagnoza_czasu", out))
        return 2
    ok = mt5.initialize(path=cfg.mt5.terminal_path) if cfg.mt5.terminal_path else mt5.initialize()
    if not ok:
        _line(FAIL, f"initialize() nieudane: {mt5.last_error()}")
        print(_save("diagnoza_czasu", out))
        return 3
    try:
        a = mt5.account_info()
        out["server"] = getattr(a, "server", None)
        if not mt5.symbol_select(cfg.mt5.symbol, True):
            _line(FAIL, f"Symbol {cfg.mt5.symbol} niedostępny")
            return 4
        sc = ServerClock(cfg.clock.offset_granularity_seconds, cfg.clock.offset_tolerance_seconds, cfg.clock.min_samples)
        samples = []
        print("Zbieram ticki przez ok. 20 s ...")
        t_end = time.monotonic() + 20
        while time.monotonic() < t_end:
            tk = mt5.symbol_info_tick(cfg.mt5.symbol)
            now = datetime.now(timezone.utc)
            if tk is not None:
                ev = sc.observe_tick(int(tk.time_msc), now)
                samples.append({"tick_time_raw": int(tk.time), "tick_time_msc_raw": int(tk.time_msc), "pc_utc": iso(now),
                                "raw_minus_utc_seconds": round(tk.time_msc / 1000 - now.timestamp(), 3)})
            time.sleep(0.5)
        ev = sc.evidence.as_dict()
        out["tick_samples"] = samples[-15:]
        out["offset_evidence"] = ev
        uniq = len({s["tick_time_msc_raw"] for s in samples})
        _line(OK if ev["status"] == "VERIFIED" else WARN,
              f"Offset czasu serwera: {ev['offset_hours']} h, status {ev['status']}, nowych ticków {uniq}"
              + (" (rynek zamknięty? – brak świeżych ticków)" if uniq < 3 else ""))
        off = ev["offset_seconds"]
        out["timeframes"] = {}
        for tf in TIMEFRAMES:
            r = mt5.copy_rates_from_pos(cfg.mt5.symbol, getattr(mt5, "TIMEFRAME_" + tf), 0, 4)
            if r is None or len(r) == 0:
                out["timeframes"][tf] = {"status": "NO_HISTORY"}
                _line(WARN, f"{tf}: brak historii")
                continue
            opens = sorted(int(x["time"]) for x in r)
            nowts = datetime.now(timezone.utc).timestamp()
            rec = {"open_times_raw": opens, "open_times_raw_iso": [iso(datetime.fromtimestamp(x, timezone.utc)) for x in opens],
                   "newest_raw_minus_pc_utc_seconds": round(opens[-1] - nowts, 1)}
            if off is not None:
                rec["open_times_utc"] = [iso(datetime.fromtimestamp(x - off, timezone.utc)) for x in opens]
                rec["future_bars_after_offset"] = sum(1 for x in opens if x - off > nowts + 60)
            out["timeframes"][tf] = rec
            _line(OK if rec.get("future_bars_after_offset", 0) == 0 else FAIL,
                  f"{tf}: ostatnie otwarcie raw {rec['open_times_raw_iso'][-1]}" + (f" → UTC {rec['open_times_utc'][-1]}" if off is not None else ""))
        out["interpretation"] = ("Surowe czasy MT5 to czas serwera brokera zapisany jako epoch. Program mierzy przesunięcie z ticków, "
                                 "nie przyjmuje go arbitralnie. Jeśli status != VERIFIED przy otwartym rynku, sprawdź zegar Windows (synchronizacja czasu).")
    finally:
        mt5.shutdown()
        print("Raport:", _save("diagnoza_czasu", out))
    return 0


def set_key() -> int:
    from .secrets_store import SecretStore
    print("Wklej klucz Anthropic API (nie będzie wyświetlany). Pusta wartość = usuń zapisany klucz.")
    v = getpass.getpass("ANTHROPIC_API_KEY: ").strip()
    SecretStore().set("ANTHROPIC_API_KEY", v or None)
    print("Zapisano lokalnie (Windows DPAPI)." if v else "Usunięto zapisany klucz.")
    return 0


def export_history(from_utc: str, to_utc: str, out_dir: str) -> int:
    """Six-timeframe export in the M06R CSV format with *UTC* times (raw - measured offset).

    The broker offset is measured now from fresh ticks (or taken from the last verified value
    stored for this server). It is applied uniformly: historical DST changes of the broker are not
    reconstructed - this limitation is written into the manifest.
    """
    import csv
    import hashlib
    from datetime import timedelta
    from .config import ConfigStore
    from .db.database import Database
    from .mt5.clock import ServerClock
    from .timeutil import TF_SECONDS, parse_iso
    cfg = ConfigStore().get()
    sym = cfg.mt5.symbol
    start, end = parse_iso(from_utc), parse_iso(to_utc)
    if not start or not end or end <= start or (end - start).days > 500:
        print("[BLAD] Zakres: --from-utc < --to-utc, maks. 500 dni, format 2026-01-01T00:00:00Z")
        return 2
    import MetaTrader5 as mt5
    ok = mt5.initialize(path=cfg.mt5.terminal_path) if cfg.mt5.terminal_path else mt5.initialize()
    if not ok:
        print("[BLAD] initialize():", mt5.last_error())
        return 3
    try:
        if not mt5.symbol_select(sym, True):
            print(f"[BLAD] Symbol {sym} niedostępny")
            return 4
        sc = ServerClock()
        t_end = time.monotonic() + 15
        while time.monotonic() < t_end and not sc.verified:
            tk = mt5.symbol_info_tick(sym)
            if tk is not None:
                sc.observe_tick(int(tk.time_msc), datetime.now(timezone.utc))
            time.sleep(0.3)
        offset, basis = sc.offset, "MEASURED_NOW"
        if not sc.verified:
            a = mt5.account_info()
            row = Database().one("SELECT offset_seconds, measured_at FROM clock_offsets WHERE server=?", (getattr(a, "server", ""),))
            if not row:
                print("[BLAD] Nie można zmierzyć offsetu czasu serwera (rynek zamknięty?) i brak zapisanego pomiaru. Uruchom przy otwartym rynku.")
                return 5
            offset, basis = row["offset_seconds"], f"STORED_{row['measured_at']}"
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        files = {}
        now = datetime.now(timezone.utc)
        for tf in ("D1", "H4", "H1", "M15", "M5", "M1"):
            rows = []
            cur = start
            while cur < end:
                nxt = min(end, cur + timedelta(days=7 if tf in ("M1", "M5") else 120))
                r = mt5.copy_rates_range(sym, getattr(mt5, "TIMEFRAME_" + tf), datetime.fromtimestamp(cur.timestamp() + offset, timezone.utc),
                                         datetime.fromtimestamp(nxt.timestamp() + offset, timezone.utc))
                if r is not None:
                    rows += [x for x in r]
                cur = nxt
            uniq = {}
            for x in rows:
                uniq[int(x["time"])] = x
            ts = sorted(uniq)
            path = out / f"{tf}.csv"
            n = 0
            with path.open("w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["symbol", "time_utc", "open", "high", "low", "close", "tick_volume", "real_volume", "spread_points", "bar_state", "available_at_utc"])
                for i, t in enumerate(ts):
                    op = datetime.fromtimestamp(t - offset, timezone.utc)
                    if op < start or op >= end or op + timedelta(seconds=TF_SECONDS[tf]) > now:
                        continue
                    nxt_open = datetime.fromtimestamp(ts[i + 1] - offset, timezone.utc) if i + 1 < len(ts) else None
                    if nxt_open is None or nxt_open > now:
                        continue  # not confirmed by an observed next bar
                    x = uniq[t]
                    w.writerow([sym, iso(op), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), int(x["tick_volume"]),
                                int(x["real_volume"]), int(x["spread"]), "CLOSED", iso(max(nxt_open, op + timedelta(seconds=TF_SECONDS[tf])))])
                    n += 1
            files[tf] = {"bars": n, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            print(f"[OK] {tf}: {n} zamkniętych świec")
        manifest = {"module_id": "MQAI_MT5_EXPORT_UTC", "symbol": sym, "from_utc": iso(start), "to_utc": iso(end), "created_at": iso(now),
                    "server_offset_seconds": offset, "offset_basis": basis, "files": files, "execution_permission": "BLOCKED",
                    "limitations": ["Offset czasu serwera zastosowany jednolicie; historyczne zmiany DST brokera nie są rekonstruowane",
                                    "available_at = otwarcie następnej świecy (oszacowanie historyczne, nie obserwacja live)",
                                    "Świece BID z wykresu, nie historyczne ticki Bid/Ask"]}
        (out / "MT5_EXPORT_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Manifest:", out / "MT5_EXPORT_MANIFEST.json")
    finally:
        mt5.shutdown()
    return 0
