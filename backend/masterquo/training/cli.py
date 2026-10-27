"""`python -m masterquo training <cmd>` - the single backend of every training launcher and of the panel.

  menu                     simple Polish console wizard (00_TRENING_START.bat)
  run                      plan + execute (TRENUJ_XAUUSD/BTCUSDT/OBA.bat, 22_TRENUJ_WSZYSTKIE_MODELE.bat)
  resume [RUN_ID]          continue a cancelled / interrupted run (finished tasks are not repeated)
  cancel [RUN_ID]          request cancel (the running child is terminated, state kept)
  status [RUN_ID]          JSON state of a run
  report [RUN_ID]          open the HTML report
  rollback                 previous model of one instrument x family (forecast | scalp | ml | lab:<FAMILY>)
  install / diag           environment checks (INSTALUJ_TRENING.bat / DYAGNOSTYKA_TRENINGU.bat)
  symbols                  terminal + candidate broker symbols with contract metadata (own MT5 connection, read only)
  export / ml-offline / lab-offline   internal steps (child processes of `run`)
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

from .. import paths
from . import core

INSTR = ("XAUUSD", "BTC")


# ------------------------------------------------------------------ terminal / symbols (read only)
def detect(synthetic: bool = False) -> dict:
    import mq_instruments as mi
    out: dict = {"terminals": installed_terminals(), "connected": False, "instruments": {}, "warnings": []}
    try:
        if synthetic:
            from ..mt5.fake import BTCUSDT_SYN, SYN_MARKETS, FakeMT5
            mt5 = FakeMT5(markets=dict(SYN_MARKETS, **BTCUSDT_SYN))
        else:
            import MetaTrader5 as mt5
    except ImportError:
        out["error"] = "BRAK_PAKIETU_MetaTrader5 (działa na Windows z zainstalowanym MT5)"
        return out
    from ..config import ConfigStore
    from ..diagnostics import attach
    from ..forecast.export import NoOrders
    mt5 = NoOrders(mt5)
    if not attach(mt5, ConfigStore().get()):
        out["error"] = f"initialize(): {mt5.last_error()} – uruchom i zaloguj MT5"
        return out
    try:
        ti, ai = mt5.terminal_info(), mt5.account_info()
        out["connected"] = True
        out["terminal"] = {"path": getattr(ti, "path", None), "name": getattr(ti, "name", None), "company": getattr(ti, "company", None),
                           "server": getattr(ai, "server", None), "account_currency": getattr(ai, "currency", None)}
        keys = ("name", "description", "path", "visible", "currency_base", "currency_profit", "currency_margin", "trade_calc_mode",
                "trade_contract_size", "point", "trade_tick_size", "trade_tick_value", "digits", "volume_min", "volume_step", "volume_max", "trade_mode")
        syms = [{k: getattr(s, k, None) for k in keys} for s in (mt5.symbols_get() or [])]
        for inst in INSTR:
            out["instruments"][inst] = {"default": mi.profile(inst)["default_broker_symbol"], "candidates": mi.candidates(inst, syms)}
            for c in out["instruments"][inst]["candidates"]:
                full = next(s for s in syms if s["name"] == c["name"])
                c["spec"] = {k: full.get(k) for k in keys if k not in ("name", "visible")}
        for s in syms:
            nm = str(s["name"]).upper()
            if "BTS" in nm and str(s.get("currency_base") or "").upper() not in ("BTC", "XBT"):
                out["warnings"].append(f"{s['name']} istnieje, ale jego waluta bazowa to {s.get('currency_base')} – to NIE jest Bitcoin; wybierz symbol BTC")
    finally:
        mt5.shutdown()
    return out


def installed_terminals() -> list[str]:
    found = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base and Path(base).exists():
                found += [str(p) for p in Path(base).glob("*/terminal64.exe")]
        appdata = os.environ.get("APPDATA")
        if appdata:
            for o in Path(appdata, "MetaQuotes", "Terminal").glob("*/origin.txt"):
                try:
                    found.append(o.read_text(encoding="utf-16", errors="replace").strip() + "\\terminal64.exe")
                except OSError:
                    pass
    return sorted(set(found))


def choose_symbol(inst: str, info: dict, interactive: bool, given: str | None) -> tuple[str | None, str]:
    """Explicit symbol > confirmed mapping > single exact default candidate. Never a silent substitute."""
    if given:
        return given, "PODANY_PRZEZ_UŻYTKOWNIKA"
    from ..config import ConfigStore
    m = ConfigStore().get().assets.mappings.get(inst)
    cands = ((info.get("instruments") or {}).get(inst) or {}).get("candidates") or []
    if m and m.broker_symbol and m.status in ("CONFIRMED", "USER_SPECIFIED", "AUTO_DETECTED") and (not cands or any(c["name"] == m.broker_symbol for c in cands)):
        if not interactive:
            return m.broker_symbol, f"MAPOWANIE_BOTA_{m.status}"
    if interactive:
        print(f"\nInstrument {inst} – kandydaci w terminalu:")
        if not cands:
            print("  (brak – wpisz dokładną nazwę symbolu albo zostaw puste, aby pominąć)")
        for i, c in enumerate(cands, 1):
            sp = c.get("spec") or {}
            print(f"  {i}) {c['name']:<14} {c.get('currency_base')}/{c.get('currency_profit')}  kontrakt {c.get('contract_size')}  tick {sp.get('trade_tick_size')}"
                  f"  calc_mode {sp.get('trade_calc_mode')}  {'OK' if c['metadata_ok'] else 'UWAGA: ' + ','.join(c['problems'])}  {c.get('description') or ''}")
        for w in info.get("warnings") or []:
            print("  [UWAGA] " + w)
        default = (m.broker_symbol if m and m.broker_symbol else None) or (cands[0]["name"] if cands else "")
        ans = input(f"Wybierz numer albo wpisz symbol [{default or 'pomiń'}]: ").strip()
        if not ans:
            return (default or None), "WYBÓR_DOMYŚLNY"
        if ans.isdigit() and 1 <= int(ans) <= len(cands):
            return cands[int(ans) - 1]["name"], "WYBÓR_Z_LISTY"
        return ans, "WPISANY"
    exact = [c for c in cands if c["name"] == (info.get("instruments") or {}).get(inst, {}).get("default") and c["metadata_ok"]]
    if exact:
        return exact[0]["name"], "DOMYŚLNY_SYMBOL_ZWERYFIKOWANY_METADANYMI"
    if m and m.broker_symbol:
        return m.broker_symbol, f"MAPOWANIE_BOTA_{m.status}"
    return None, "BRAK_JEDNOZNACZNEGO_SYMBOLU – wybierz w kreatorze (00_TRENING_START.bat)"


# ------------------------------------------------------------------ run
def cmd_run(a) -> int:
    from . import runner
    if a.profile is None:
        a.profile = "PELNY_TRENING"
        if a.interactive:
            ans = input("Profil: 1) TEST INSTALACJI (szybki, modele nie są aktywowane)  2) PEŁNY TRENING [2]: ").strip()
            a.profile = "TEST_INSTALACJI" if ans == "1" else "PELNY_TRENING"
    if a.months is None and a.interactive:
        ans = input(f"Ile miesięcy historii pobrać? [{core.profiles()[a.profile]['months']}]: ").strip()
        a.months = int(ans) if ans.isdigit() and 1 <= int(ans) <= 36 else None
    insts = [x.strip().upper().replace("BTCUSDT", "BTC") for x in a.instruments.split(",") if x.strip()]
    insts = [i for i in INSTR if i in insts]                      # fixed order: XAUUSD -> BTC
    datasets, ds_synthetic = {}, False
    for inst in insts:                                            # an export made earlier (panel "Eksportuj dane z MT5") instead of a new one
        d = getattr(a, f"dataset_{inst.lower()}", None)
        if not d:
            continue
        from ..forecast.export import dataset_state
        stt = dataset_state(Path(d))
        meta = json.loads((Path(d) / "source_metadata.json").read_text(encoding="utf-8")) if stt["usable"] else None
        if not meta or meta.get("instrument") != inst:
            print(f"[BLAD] {inst}: eksport {d} nie nadaje się do treningu ({stt['state']}{'' if not meta else ', instrument ' + str(meta.get('instrument'))})")
            return 2
        datasets[inst] = str(Path(d).resolve())
        setattr(a, f"symbol_{inst.lower()}", meta["symbol"])
        ds_synthetic = ds_synthetic or meta.get("data_kind") != "REAL_USER_DATA"
    info = detect(a.demo) if not (a.no_detect or (datasets and set(datasets) == set(insts))) else {}
    if info.get("error") and not a.demo:
        print(f"[BLAD] MT5: {info['error']}")
    symbols, sources = {}, {}
    for inst in insts:
        s, src = choose_symbol(inst, info, a.interactive, getattr(a, f"symbol_{inst.lower()}"))
        if s:
            symbols[inst], sources[inst] = s, src
        else:
            print(f"[UWAGA] {inst}: {src}")
    comm = {}
    for inst in insts:
        v = getattr(a, f"commission_{inst.lower()}")
        if v is None and a.interactive:
            raw = input(f"Prowizja {inst} za 1 lot na stronę w walucie konta (Enter = z historii transakcji / nieznana): ").strip().replace(",", ".")
            v = float(raw) if raw else None
        if v is not None:
            comm[inst] = v
    plan, tasks = runner.build_plan(instruments=insts, profile=a.profile, symbols=symbols, commissions=comm, months=a.months,
                                    synthetic=a.demo or ds_synthetic, datasets=datasets,
                                    tasks=a.tasks.split(",") if a.tasks else None, include_approx=not a.no_approx, lab_bars=a.lab_bars,
                                    threads=a.threads, ml_days=a.ml_days, min_events=a.min_events, origin=a.origin)
    plan["symbol_sources"] = sources
    plan["terminal"] = info.get("terminal")
    if not symbols:
        print("[BLAD] Brak symbolu dla żadnego instrumentu – nic do trenowania.")
        return 2
    run = core.Run.create(plan, tasks)
    print(f"Run {run.run_id}: {', '.join(f'{i}={symbols.get(i, "brak")}' for i in insts)}, profil {a.profile}, historia {plan['months']} mies.")
    return runner.execute(run)


def cmd_resume(a) -> int:
    from . import runner
    rid = a.run_id or core.Run.latest()
    if not rid:
        print("[BLAD] Brak runu do wznowienia.")
        return 2
    run = core.Run.load(rid)
    if run.state.get("status") == "FINISHED" and not any(t["execution"] in ("ANULOWANE", "BLAD_TECHNICZNY", "NIE_URUCHOMIONE") for t in run.state["tasks"]):
        print(f"Run {rid} jest zakończony – nic do wznowienia.")
        return 0
    for t in run.state["tasks"]:
        if t["execution"] in ("ANULOWANE", "BLAD_TECHNICZNY", "W_TOKU"):
            t["execution"] = "NIE_URUCHOMIONE"
    run.save()
    return runner.execute(run)


# ------------------------------------------------------------------ internal steps
def cmd_export(a) -> int:
    if a.synthetic:
        from ..mt5.fake import BTCUSDT_SYN, SYN_MARKETS, FakeMT5
        sys.modules["MetaTrader5"] = FakeMT5(markets=dict(SYN_MARKETS, **BTCUSDT_SYN))
    from ..forecast.export import export_candles
    return export_candles(a.months, a.out, a.dst_model, tuple(t.strip().upper() for t in a.tfs.split(",") if t.strip()), "training",
                          a.instrument, a.symbol, date_from=a.date_from, date_to=a.date_to, tick_days=a.ticks_days)


def cmd_ml_offline(a) -> int:
    from ..ml import offline
    res = offline.train(a.instrument, Path(a.dataset), include_approx=a.include_approx, days=a.days, commission=a.commission, threads=a.threads)
    core.write_json_atomic(Path(a.out), res)
    print(json.dumps({k: res.get(k) for k in ("status", "reason", "role", "champion")}, ensure_ascii=False))
    return 0 if res.get("status") in ("DONE", "INSUFFICIENT_DATA") else 1


def load_m5(ds: Path, n: int) -> tuple[list[dict], dict]:
    import csv
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    rows = []
    with (ds / f"{meta.get('file_prefix') or 'XAUUSD'}_M5.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({"open_utc": r["time_open_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                         "tv": int(float(r["tick_volume"] or 0)), "spread": float(r["spread_points"]) if r.get("spread_points") not in (None, "") else None,
                         "closed": True})
    return rows[-n:], meta


def cmd_lab_offline(a) -> int:
    from ..db.database import Database
    from ..lab.protocol import EXPERIMENTS, FAMILIES, LabTrainer, default_protocol
    bars, meta = load_m5(Path(a.dataset), a.bars)
    if meta.get("instrument", "XAUUSD") != a.instrument:
        print(f"[BLAD] INSTRUMENT_MISMATCH {meta.get('instrument')} != {a.instrument}")
        return 2
    fams = [f for f in a.families.split(",") if f in FAMILIES]
    exps = [e for e in a.experiments.split(",") if e in EXPERIMENTS]
    prot = default_protocol(a.instrument, families=fams, experiments=exps, min_events=a.min_events)
    tr = LabTrainer(Database(), paths.data_dir() / "lab")
    src = "MT5" if meta.get("data_kind") == "REAL_USER_DATA" else "SYNTHETIC"
    job = {"job_id": "LJOB-" + core.now().replace(":", "").replace("-", "") + "-OFF", "asset": a.instrument, "status": "RUNNING", "progress": 0,
           "total": 0, "stage": "start", "logs": [], "started_at": core.now(), "protocol_id": prot["protocol_id"], "data_source": src, "cancel": False}
    tr._run(job, bars, float(meta["spec"].get("point") or meta["tick_size"]), src, f"{a.instrument}:{meta.get('account_server')}:{meta['symbol']}",
            prot, "ALL")
    models = []
    for mid in job.get("model_ids") or []:
        man = json.loads((paths.data_dir() / "lab" / "models" / a.instrument / mid / "manifest.json").read_text(encoding="utf-8"))
        models.append({k: man.get(k) for k in ("model_id", "family", "role", "side", "horizon", "verdict", "loader_parity", "fit_scope")})
    core.write_json_atomic(Path(a.out), {"job": {k: v for k, v in job.items() if k != "cancel"}, "models": models, "dataset_id": meta.get("dataset_id")})
    for line in job["logs"][-30:]:
        print(line)
    return 0 if job["status"] == "COMPLETED" else 1


# ------------------------------------------------------------------ rollback / status
def cmd_rollback(a) -> int:
    import subprocess
    inst = a.instrument
    if a.family == "forecast" or a.family == "scalp":
        py = core.candles_python()
        if not py:
            print("[BLAD] brak .venv_candles")
            return 2
        mod = "gold_candles_runtime.registry_cli" if a.family == "forecast" else "gold_candles_runtime.scalp_registry"
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), MASTERQUO_DATA_DIR=str(paths.data_dir()))
        return subprocess.run([py, "-m", mod, "--instrument", inst, "rollback"], cwd=str(paths.ROOT_DIR / "backend"), env=env).returncode
    if a.family == "ml":
        from ..ml.registry import Registry
        from ..ml.router import ml_store
        db, root = ml_store(inst)
        try:
            print(Registry(db, root / "models").rollback())
        except ValueError as exc:
            print(f"[BLAD] {exc}")
            return 2
        return 0
    if a.family.startswith("lab:"):
        from ..lab.protocol import rollback_family
        try:
            ptr = rollback_family(paths.data_dir() / "lab", inst, a.family.split(":", 1)[1])
        except ValueError as exc:
            print(f"[BLAD] {exc}")
            return 2
        print(f"Aktywne modele lab {inst}: {json.dumps(ptr['active'], ensure_ascii=False)}")
        return 0
    print("[BLAD] rodzina: forecast | scalp | ml | lab:<RODZINA>")
    return 2


def cmd_install(a) -> int:
    """Checks (does not overwrite a working environment): interpreters, pinned versions vs requirements/, hashes present, CPU only."""
    import importlib.metadata as md
    import re
    ok = True
    rep = {"python": sys.version.split()[0], "arch": platform.architecture()[0], "platform": platform.platform(), "checks": []}

    def chk(name, good, detail=""):
        nonlocal ok
        ok = ok and good
        rep["checks"].append({"check": name, "ok": bool(good), "detail": detail})
        print(f"[{'OK' if good else 'BLAD'}] {name}" + (f" – {detail}" if detail else ""))
    v = sys.version_info
    chk("Python 3.12/3.13 x64 (.venv)", v[:2] in ((3, 12), (3, 13)) and rep["arch"] == "64bit", f"{rep['python']} {rep['arch']}")
    req = paths.ROOT_DIR / "requirements" / "requirements-win.txt"
    pins = dict(re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s;\\]+)", req.read_text(encoding="utf-8"), re.M)) if req.exists() else {}
    hashes = req.read_text(encoding="utf-8").count("--hash=sha256:") if req.exists() else 0
    chk("requirements-win.txt z hashami SHA256", bool(pins) and hashes >= len(pins), f"{len(pins)} pakietów, {hashes} hashy")
    bad = []
    for name, ver in pins.items():
        if name.lower() == "metatrader5" and os.name != "nt":
            continue
        try:
            got = md.version(name)
            if got != ver:
                bad.append(f"{name} {got}≠{ver}")
        except md.PackageNotFoundError:
            if os.name == "nt":
                bad.append(f"{name} brak")
    chk("wersje .venv zgodne z blokadą", not bad, ", ".join(bad[:8]) or "zgodne")
    cpy = core.candles_python()
    chk(".venv_candles (prognozy/scalp)", bool(cpy), cpy or "brak – INSTALUJ_TRENING.bat utworzy je przez 10_PROGNOZY_INSTALUJ.bat")
    try:
        __import__("xgboost")
        chk("XGBoost na CPU", True, "GPU nie jest wymagane ani używane")
    except ImportError:
        chk("XGBoost", False, "brak pakietu w .venv")
    try:
        __import__("MetaTrader5")
        chk("pakiet MetaTrader5", True)
    except ImportError:
        chk("pakiet MetaTrader5", os.name != "nt", "dostępny tylko na Windows")
    probe = core.training_dir() / "zapis próbny ąę !.tmp"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        chk("zapis w katalogu danych (spacje/Unicode/!)", True, str(core.training_dir()))
    except OSError as exc:
        chk("zapis w katalogu danych", False, str(exc))
    chk("Node.js niepotrzebny", True, "panel jest już zbudowany (frontend/dist)" if (paths.ROOT_DIR / "frontend" / "dist").exists() else "brak frontend/dist")
    core.write_json_atomic(core.training_dir() / "install_check.json", rep)
    return 0 if ok else 1


def cmd_diag(a) -> int:
    rc = cmd_install(a)
    print("\n--- Terminal MT5 i symbole (odczyt, bez zleceń) ---")
    info = detect(a.demo)
    if info.get("error"):
        print("[BLAD] " + info["error"])
    else:
        t = info["terminal"]
        print(f"Terminal: {t.get('name')} ({t.get('company')}), serwer {t.get('server')}, waluta konta {t.get('account_currency')}")
        for inst, d in info["instruments"].items():
            names = ", ".join(f"{c['name']}({c.get('currency_base')}/{c.get('currency_profit')}{'' if c['metadata_ok'] else ' !'})" for c in d["candidates"]) or "brak"
            print(f"{inst}: domyślny {d['default']}; kandydaci: {names}")
        for w in info["warnings"]:
            print("[UWAGA] " + w)
    if info.get("terminals"):
        print("Zainstalowane terminale: " + "; ".join(info["terminals"]))
    from ..train_all import _health
    from ..__main__ import _port
    h = _health(_port())
    print(f"Bot: {'działa – ' + str(h.get('app')) + ' ' + str(h.get('version')) if h else 'nie działa'}; trening nie zmienia trybu wykonania ani nie składa zleceń.")
    rid = core.Run.latest()
    if rid:
        st = core.Run.load(rid).state
        print(f"Ostatni trening: {rid} – {st.get('status')}; {(st.get('summary') or {}).get('line', '')}")
    core.write_json_atomic(core.training_dir() / "diagnostics.json", info)
    return rc


# ------------------------------------------------------------------ menu
MENU = """
==============================================================
  PepeMarketWizard – TRENING MODELI (XAUUSD / BTC)
  Trening nie wysyła zleceń i nie zmienia trybu wykonania.
==============================================================
  1) Instalacja / naprawa środowiska
  2) Trenuj XAUUSD
  3) Trenuj BTC (BTCUSDT-)
  4) Trenuj oba (najpierw XAUUSD, potem BTC)
  5) Diagnostyka (terminal, symbole, środowisko)
  6) Wyniki ostatniego treningu (raport)
  7) Wznów przerwany trening
  8) Rollback modelu (instrument / rodzina)
  0) Wyjście
"""


def cmd_menu(a) -> int:
    while True:
        print(MENU)
        c = input("Wybór: ").strip()
        if c == "0" or c == "":
            return 0
        if c == "1":
            cmd_install(a)
        elif c in ("2", "3", "4"):
            ns = parser().parse_args(["run", "--instruments", {"2": "XAUUSD", "3": "BTC", "4": "XAUUSD,BTC"}[c], "--interactive", "--origin", "menu"]
                                     + (["--demo"] if a.demo else []))
            rc = cmd_run(ns)
            print(f"Kod zakończenia: {rc} (0 = wszystkie zadania wykonane; szczegóły jakości w raporcie)")
        elif c == "5":
            cmd_diag(a)
        elif c == "6":
            cmd_report(argparse.Namespace(run_id=None))
        elif c == "7":
            cmd_resume(argparse.Namespace(run_id=None))
        elif c == "8":
            inst = input("Instrument (XAUUSD/BTC): ").strip().upper() or "XAUUSD"
            fam = input("Rodzina (forecast / scalp / ml / lab:SEW_SNN ...): ").strip()
            cmd_rollback(argparse.Namespace(instrument="BTC" if inst.startswith("BTC") else "XAUUSD", family=fam))
        input("\nEnter = powrót do menu")


def cmd_report(a) -> int:
    from . import report
    rid = a.run_id or core.Run.latest()
    if not rid:
        print("Brak treningów.")
        return 2
    report.write(core.Run.load(rid), open_browser=True)
    return 0


def cmd_status(a) -> int:
    rid = a.run_id or core.Run.latest()
    print(json.dumps(core.Run.load(rid).state if rid else {"status": "NO_RUNS"}, indent=1, ensure_ascii=False))
    return 0


def cmd_cancel(a) -> int:
    rid = a.run_id or core.Run.latest()
    if not rid:
        return 2
    (core.runs_dir() / rid / "CANCEL").write_text(core.now(), encoding="utf-8")
    print(f"Anulowanie zgłoszone dla {rid}.")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="masterquo training", description="Trening modeli XAUUSD/BTC (offline/SHADOW, bez zleceń)")
    sub = ap.add_subparsers(dest="tcmd", required=True)
    for n in ("menu", "install", "diag"):
        s = sub.add_parser(n)
        s.add_argument("--demo", action="store_true", help="test: syntetyczny terminal")
    r = sub.add_parser("run")
    r.add_argument("--instruments", default="XAUUSD,BTC")
    r.add_argument("--profile", choices=tuple(core.profiles()), default=None, help="domyślnie PELNY_TRENING (w trybie --interactive pytanie)")
    r.add_argument("--months", type=int)
    r.add_argument("--symbol-xauusd", dest="symbol_xauusd")
    r.add_argument("--symbol-btc", dest="symbol_btc")
    r.add_argument("--commission-xauusd", dest="commission_xauusd", type=float)
    r.add_argument("--commission-btc", dest="commission_btc", type=float)
    r.add_argument("--tasks", help="podzbiór: forecast,scalp_A,ml,lab (eksport, kontrola, aktywacja i bot zawsze)")
    r.add_argument("--no-approx", action="store_true", help="ML bez próbek APPROX (tylko dla tego zadania)")
    r.add_argument("--lab-bars", type=int)
    r.add_argument("--ml-days", type=int)
    r.add_argument("--min-events", type=int)
    r.add_argument("--threads", type=int)
    r.add_argument("--interactive", action="store_true")
    r.add_argument("--no-detect", action="store_true")
    r.add_argument("--demo", action="store_true", help="TEST: syntetyczny terminal; modele techniczne, nigdy aktywowane")
    r.add_argument("--dataset-xauusd", dest="dataset_xauusd", help="użyj gotowego eksportu (folder) zamiast nowego eksportu XAUUSD")
    r.add_argument("--dataset-btc", dest="dataset_btc", help="użyj gotowego eksportu (folder) zamiast nowego eksportu BTC")
    r.add_argument("--origin", default="cli")
    for n in ("resume", "cancel", "status", "report"):
        s = sub.add_parser(n)
        s.add_argument("run_id", nargs="?")
    rb = sub.add_parser("rollback")
    rb.add_argument("--instrument", choices=INSTR, required=True)
    rb.add_argument("--family", required=True, help="forecast | scalp | ml | lab:<RODZINA>")
    sy = sub.add_parser("symbols")
    sy.add_argument("--demo", action="store_true")
    ex = sub.add_parser("export")
    ex.add_argument("--instrument", choices=INSTR, required=True)
    ex.add_argument("--symbol", required=True)
    ex.add_argument("--months", type=int, default=12)
    ex.add_argument("--out", required=True)
    ex.add_argument("--tfs", default="M1,M5,M15,M30,H1,H4,D1")
    ex.add_argument("--dst-model", choices=["AUTO", "UNIFORM", "NY_CLOSE"], default="AUTO")
    ex.add_argument("--from", dest="date_from", help="początek zakresu UTC (np. 2026-01-01) – zastępuje --months")
    ex.add_argument("--to", dest="date_to", help="koniec zakresu UTC (domyślnie ostatnia zamknięta świeca)")
    ex.add_argument("--ticks-days", type=float, default=0.0, help="dodaj ticki Bid/Ask z ostatnich N dni zakresu (0 = bez ticków, max 31)")
    ex.add_argument("--synthetic", action="store_true")
    mo = sub.add_parser("ml-offline")
    mo.add_argument("--instrument", choices=INSTR, required=True)
    mo.add_argument("--dataset", required=True)
    mo.add_argument("--days", type=int, default=180)
    mo.add_argument("--threads", type=int, default=2)
    mo.add_argument("--include-approx", action="store_true")
    mo.add_argument("--commission", type=float)
    mo.add_argument("--out", required=True)
    lo = sub.add_parser("lab-offline")
    lo.add_argument("--instrument", choices=INSTR, required=True)
    lo.add_argument("--dataset", required=True)
    lo.add_argument("--bars", type=int, default=60000)
    lo.add_argument("--families", default="DUMMY,LOGREG")
    lo.add_argument("--experiments", default="")
    lo.add_argument("--min-events", type=int, default=600)
    lo.add_argument("--out", required=True)
    return ap


def main(argv: list[str]) -> int:
    a = parser().parse_args(argv)
    fn = {"menu": cmd_menu, "run": cmd_run, "resume": cmd_resume, "cancel": cmd_cancel, "status": cmd_status, "report": cmd_report,
          "rollback": cmd_rollback, "install": cmd_install, "diag": cmd_diag, "export": cmd_export, "ml-offline": cmd_ml_offline,
          "lab-offline": cmd_lab_offline, "symbols": lambda x: print(json.dumps(detect(x.demo), indent=1, ensure_ascii=False, default=str)) or 0}[a.tcmd]
    return fn(a)
