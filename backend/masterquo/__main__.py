"""Command line entry point (used by the Windows launchers).

  python -m masterquo serve [--demo] [--no-browser]   start (or open the already running monitor)
  python -m masterquo stop                              stop only this project's server
  python -m masterquo doctor                            environment + MT5 + Claude diagnostics
  python -m masterquo clock                             raw MT5 time diagnostics (no trading)
  python -m masterquo set-key                           store the Anthropic API key locally (DPAPI)
  python -m masterquo quant status|inventory|train|list|activate|rollback|mode|bench   PMW Quant Core (quant/cli.py)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import localapi, paths


def _rt_dir() -> Path:
    d = paths.data_dir() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d


# 1.46 arch (I0080): the local-API client helpers live in the leaf masterquo/localapi.py (other modules import them from there, not from
# this entry point); the old names stay as aliases with the former defaults (here: health timeout 1.5 s). I0094: localapi.port() reads
# config.json read-only (config.server_port) - no migration write / .bak before the instance lock.
_port = localapi.port


def _health(port: int, timeout: float = 1.5) -> dict | None:
    return localapi.health(port, timeout)


def _setup_logging() -> None:
    from logging.handlers import RotatingFileHandler
    h = RotatingFileHandler(paths.logs_dir() / "masterquo.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "anthropic", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


from .version import APP_NAME  # noqa: E402


def cmd_serve(args) -> int:
    if args.demo and not os.environ.get("MASTERQUO_DATA_DIR"):
        os.environ["MASTERQUO_DATA_DIR"] = str(paths.ROOT_DIR / "data" / "demo_synthetic")
    port = _port()
    url = f"http://127.0.0.1:{port}/"
    h = _health(port)
    if h and h.get("app") in (APP_NAME, "MasterQUO AI"):          # also an instance of the pre-1.13 name
        print(f"[Apollo23] Aplikacja już działa ({'DANE SYNTETYCZNE' if h.get('synthetic') else 'MT5'}) – otwieram monitor {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    if h is not None or _port_busy(port):
        print(f"[Apollo23] Port {port} jest zajęty przez inny program. Zmień server.port w data\\config.json.", file=sys.stderr)
        return 3
    _setup_logging()
    lock = _single_instance_lock()
    if lock is None:
        print("[Apollo23] Inna instancja Apollo23 już się uruchamia w tym folderze.", file=sys.stderr)
        return 4
    try:                                                   # 1.40.1: a native crash (ctypes, DLL) leaves its stack in engine_console.log
        import faulthandler
        faulthandler.enable(file=sys.stderr, all_threads=True)
    except Exception:  # noqa: BLE001 - no usable stderr (pythonw) = nothing to write to
        pass
    try:
        import uvicorn
        from .api.app import create_app
        from .runtime import Runtime
        rt = Runtime(demo=args.demo)
        app = create_app(rt, port)
    except Exception:  # noqa: BLE001 - the full reason goes to the console log the launcher shows
        import traceback
        print("[Apollo23] BŁĄD STARTU SILNIKA – przyczyna poniżej:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        _crash_report(traceback.format_exc())
        return 5
    tok = _rt_dir() / "shutdown.token"
    tok.write_text(rt.security.shutdown_token, encoding="utf-8")
    try:
        os.chmod(tok, 0o600)
    except OSError:
        pass
    (_rt_dir() / "server.pid").write_text(json.dumps({"pid": os.getpid(), "port": port, "exe": sys.executable}), encoding="utf-8")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="websockets-sansio", lifespan="on", access_log=False,
                            timeout_graceful_shutdown=5)   # open monitor tabs (WebSocket) must not block STOP
    server = uvicorn.Server(config)
    rt.shutdown_hook = lambda: setattr(server, "should_exit", True)
    rt.start()

    def opener():
        for _ in range(120):
            if _health(port, 1.0):
                print(f"[Apollo23] Monitor gotowy: {url}  ({'DANE SYNTETYCZNE' if args.demo else 'tryb wykonania wg ustawień'})")
                if not args.no_browser and rt.cfg.get().server.open_browser:
                    webbrowser.open(url)
                return
            time.sleep(0.5)
    threading.Thread(target=opener, daemon=True).start()
    try:
        server.run()
    finally:
        rt.stop()
        for f in ("shutdown.token", "server.pid"):
            try:
                (_rt_dir() / f).unlink()
            except OSError:
                pass
        print("[Apollo23] Zatrzymano.")
    return 0


def _crash_report(text: str) -> None:
    try:
        d = paths.data_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "engine_crash.txt").write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _port_busy(port: int) -> bool:
    import socket
    s = socket.socket()
    try:
        if os.name != "nt":  # same semantics as uvicorn's listener (TIME_WAIT is not "busy")
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


_LOCK_HANDLE = None


def _try_lock(f) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _single_instance_lock(retries: int = 3, wait: float = 0.1):
    """1.46 arch (I0094): a few short retries - a CLI probe (_instance_lock_busy) holds the lock for microseconds and must never make a
    server starting at that moment exit with 'Inna instancja'. A real second instance still holds it -> None, as before."""
    global _LOCK_HANDLE
    f = open(_rt_dir() / "instance.lock", "a+b")
    for i in range(max(1, retries)):
        if _try_lock(f):
            _LOCK_HANDLE = f
            return f
        if i + 1 < retries:
            time.sleep(wait)
    f.close()
    return None


def _instance_lock_busy() -> bool:
    """1.46 arch (I0094): True when another process holds runtime/instance.lock, i.e. a server is starting or running in this data folder.
    The probe lock is released at once (see _single_instance_lock)."""
    try:
        with open(_rt_dir() / "instance.lock", "a+b") as f:
            if not _try_lock(f):
                return True
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def cmd_stop(args) -> int:
    port = _port()
    tokf = _rt_dir() / "shutdown.token"
    if not _health(port):
        print("[Apollo23] Aplikacja nie działa (brak odpowiedzi na porcie %d)." % port)
        return 0
    if not tokf.exists():
        print("[Apollo23] Brak pliku tokenu zatrzymania – zamknij okno serwera Apollo23 ręcznie.", file=sys.stderr)
        return 2
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/admin/shutdown", data=b"{}", method="POST",
                                 headers={"x-mq-shutdown": tokf.read_text(encoding="utf-8").strip(), "Content-Type": "application/json",
                                          "Host": f"127.0.0.1:{port}"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, OSError) as exc:
        print("[Apollo23] Nie udało się wysłać żądania zatrzymania:", exc, file=sys.stderr)
        return 3
    for _ in range(40):
        if not _health(port, 0.8):
            print("[Apollo23] Zatrzymano serwer Apollo23 (terminal MT5 i inne programy Python nie zostały zamknięte).")
            return 0
        time.sleep(0.5)
    print("[Apollo23] Serwer nie zakończył się w czasie 20 s – zamknij okno 'Apollo23 server'.", file=sys.stderr)
    return 4


def _load_dotenv() -> None:
    """Optional <root>/.env (never packaged). Only secrets_store.DOTENV_VARS are taken (ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    MASTERQUO_DATA_DIR, FRED_API_KEY, TELEGRAM_BOT_TOKEN - 1.46 arch I0118: one list, the same as before); a variable already set in the
    environment wins."""
    from .secrets_store import DOTENV_VARS
    f = paths.ROOT_DIR / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = (x.strip() for x in line.split("=", 1))
        if k in DOTENV_VARS and v and not os.environ.get(k):
            os.environ[k] = v.strip('"')


def cmd_profile(name: str) -> int:
    """Rollback helper. Run with the server stopped (a running server keeps its own copy of the config).

    1.46 arch (I0094): refuses (exit 3) while the bot answers on its port or holds the instance lock - 1.45 wrote config.json anyway, the
    running bot ignored the change and its next settings save overwrote it with its own copy. `show` only reads (never writes the file)."""
    from .config import ConfigStore, peek
    if name == "show":
        a = peek().active
        print(f"Profil: {a.profile}, wybór strategii: {a.strategy_mode}{' ' + a.manual_strategy_id if a.manual_strategy_id else ''}")
        return 0
    h = _health(_port())
    if (h and h.get("app") in (APP_NAME, "MasterQUO AI")) or _instance_lock_busy():
        print("[Apollo23] Program działa – zmiana profilu z wiersza poleceń zostałaby nadpisana przez działający program. "
              "Zatrzymaj program (04_STOP_MASTERQUO.bat) albo zmień profil w Ustawieniach monitora.", file=sys.stderr)
        return 3
    store = ConfigStore()
    store.update({"active": {"profile": name}})
    print(f"[OK] Profil wykrywania: {name}. Tryb wykonywania zleceń i limity bez zmian. Uruchom 03_START_MASTERQUO.bat.")
    return 0


def _studio_port(rest: list[str]) -> int | None:
    """1.46 (I0137): `studio [--port N]` (also --port=N). Was read by hand (int(argv[argv.index('--port') + 1])) - a missing or non-numeric
    value ended in a traceback. N: integer 0-65535 (0 = the Studio default, as serve() treated it before); other arguments are ignored
    as before. ValueError carries the Polish message for the console (exit code 2)."""
    ap = argparse.ArgumentParser(prog="masterquo studio", add_help=False, exit_on_error=False)
    ap.add_argument("--port", default=None)
    try:
        ns, _ignored = ap.parse_known_args(rest)
    except (argparse.ArgumentError, SystemExit):
        raise ValueError("--port wymaga wartości: liczba całkowita 1-65535, np. --port 8780") from None
    if ns.port is None:
        return None
    try:
        p = int(ns.port)
    except ValueError:
        raise ValueError(f"--port musi być liczbą całkowitą 1-65535, podano {ns.port!r}") from None
    if not 0 <= p <= 65535:
        raise ValueError(f"--port poza zakresem 1-65535: {p}")
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["context-indicators"]:           # PMW-UPD-14: VAMD / bounded FD / Pullback+SMC / Buffer Inspector (lab/context_ind/cli.py)
        _load_dotenv()
        from .lab.context_ind.cli import main as ci_main
        return ci_main(argv[1:])
    if argv[:1] == ["flow-context"]:                 # PMW-UPD-11: Markov / Heikin Flow / S/R channels / StopDistance (lab/flow_context/cli.py)
        _load_dotenv()
        from .lab.flow_context.cli import main as fc_main
        return fc_main(argv[1:])
    if argv[:1] == ["structure-intelligence"]:      # PMW-UPD-07: Structure Intelligence (masterquo/lab/structure_cli.py)
        _load_dotenv()
        from .lab.structure_cli import main as si_main
        return si_main(argv[1:])
    if argv[:1] == ["liquidity"]:                    # PMW-UPD-06: session boxes + liquidation heatmap (masterquo/analytics/liquidity_cli.py)
        _load_dotenv()
        from .analytics.liquidity_cli import main as liq_main
        return liq_main(argv[1:])
    if argv[:1] == ["neural-scalp"]:                 # PMW-UPD-04: Neural Scalp System (masterquo/lab/nss_cli.py)
        _load_dotenv()
        from .lab.nss_cli import main as nss_main
        return nss_main(argv[1:])
    if argv[:1] == ["ml-scalp"]:                     # PMW-UPD-03: SCALP_NET_PROFIT_MARKET_V1 (masterquo/ml/scalp_cli.py)
        _load_dotenv()
        from .ml.scalp_cli import main as ml_scalp_main
        return ml_scalp_main(argv[1:])
    if argv[:1] == ["indicator-context"]:            # PMW-UPD-02: IQ / PAL / SAR modules (masterquo/extind/cli.py)
        _load_dotenv()
        from .extind.cli import main as extind_main
        return extind_main(argv[1:])
    if argv[:1] == ["sh"]:                           # PMW-SH-1: SCALPING / HEDGING event model + validation (masterquo/sh/train_cli.py)
        from .sh.train_cli import main as sh_main
        return sh_main(argv[1:])
    if argv[:1] == ["mm"]:                           # PMW-MM: master models (audit inventory, orchestrator, benchmarks; masterquo/mm/cli.py)
        from .mm.cli import main as mm_main
        return mm_main(argv[1:])
    if argv[:1] == ["montecarlo"]:                   # PMW-MC-1: path Monte Carlo validation / calibration (masterquo/montecarlo/cli.py)
        from .montecarlo.cli import main as mc_main
        return mc_main(argv[1:])
    if argv[:1] == ["studio"]:                       # 1.33 Pepe Data & Training Studio - separate app (own port / data dir, no bot Runtime)
        _load_dotenv()                               # 1.46 (I0137): like every other branch (.env MASTERQUO_DATA_DIR; the .bat sets its own first)
        try:
            port = _studio_port(argv[1:])
        except ValueError as e:
            print(f"[PepeTrainingStudio] {e}", file=sys.stderr)
            return 2
        from .licensing.gate import LicenseGate      # 1.44.0: wersja klienta – Studio tylko z ważną licencją (aktywacja w głównej aplikacji)
        lg = LicenseGate()
        st = lg.evaluate(refresh_net=True)
        if lg.locked:
            print(f"[PepeTrainingStudio] Brak ważnej licencji: {st.get('message')} Aktywuj klucz w aplikacji Apollo23.", file=sys.stderr)
            return 6
        from .studio.app import serve
        return serve(port)
    if argv[:1] == ["models"]:                       # 1.46 arch: ONE health check of every model producer (modelhub/check.py)
        from .modelhub.check import main as models_main
        return models_main(argv[1:])
    if argv[:1] == ["families"]:                     # 1.33 model families: list / train / activate / use / rollback (modelhub/families/cli.py)
        from .modelhub.families.cli import main as families_main
        return families_main(argv[1:])
    if argv[:1] == ["trainhub"]:                     # 1.28 Centrum treningu: export -> dataset -> train -> evaluate -> activate (trainhub/cli.py)
        _load_dotenv()
        from .trainhub.cli import main as trainhub_main
        return trainhub_main(argv[1:])
    if argv[:1] == ["quant"]:                        # 1.35 PMW Quant Core (masterquo/quant/cli.py)
        _load_dotenv()
        from .quant.cli import main as quant_main
        return quant_main(argv[1:])
    if argv[:1] == ["training"]:                     # training installer / orchestrator (masterquo/training/cli.py)
        _load_dotenv()
        from .training.cli import main as training_main
        return training_main(argv[1:])
    ap = argparse.ArgumentParser(prog="masterquo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--demo", action="store_true", help="DANE SYNTETYCZNE (symulator terminala, oddzielna baza)")
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("doctor")
    sub.add_parser("clock")
    sub.add_parser("set-key")
    pr = sub.add_parser("profile", help="przełącz profil wykrywania: ACTIVE (S01-S12 + AUTO) albo ORIGINAL (M07 jak w 1.1)")
    pr.add_argument("name", choices=["ACTIVE", "ORIGINAL", "show"])
    e = sub.add_parser("export", help="eksport 8 TF (z M30 i H8) w formacie M06R z czasem UTC")
    e.add_argument("--from-utc", required=True)
    e.add_argument("--to-utc", required=True)
    e.add_argument("--out", default=None, help="folder wyniku (domyślnie <dane>/export_mt5_utc)")
    e.add_argument("--dst-model", choices=["UNIFORM", "NY_CLOSE"], default="UNIFORM",
                   help="UNIFORM = jeden offset (dzisiejszy) dla całego zakresu; NY_CLOSE = offset per świeca (Nowy Jork + 7 h)")
    ec = sub.add_parser("export-candles", help="eksport zamkniętych M5/M30 XAUUSD- do treningu prognoz (CSV + metadane + raport jakości)")
    ec.add_argument("--months", type=int, default=12)
    ec.add_argument("--out")
    ec.add_argument("--dst-model", choices=["AUTO", "UNIFORM", "NY_CLOSE"], default="AUTO")
    ec.add_argument("--from", dest="date_from", help="początek zakresu UTC (zastępuje --months)")
    ec.add_argument("--to", dest="date_to", help="koniec zakresu UTC")
    ec.add_argument("--ticks-days", type=float, default=0.0, help="ticki Bid/Ask z ostatnich N dni (max 31)")
    es = sub.add_parser("export-scalp", help="eksport zamkniętych M1/M5/M15/M30/H1 XAUUSD- do profilu scalp (data/scalp/history)")
    es.add_argument("--months", type=int, default=6)
    es.add_argument("--out")
    es.add_argument("--dst-model", choices=["AUTO", "UNIFORM", "NY_CLOSE"], default="AUTO")
    es.add_argument("--from", dest="date_from", help="początek zakresu UTC (zastępuje --months)")
    es.add_argument("--to", dest="date_to", help="koniec zakresu UTC")
    es.add_argument("--ticks-days", type=float, default=0.0, help="ticki Bid/Ask z ostatnich N dni (max 31)")
    sr = sub.add_parser("scalp-replay", help="replay profilu scalp na wyeksportowanej historii M1 (OHLC, przybliżony – bez ticków)")
    sr.add_argument("--history", help="katalog eksportu (domyślnie najnowszy w data/scalp/history)")
    sr.add_argument("--commission-per-lot-side", type=float, default=None, help="prowizja za 1 lot na stronę w walucie konta; domyślnie scalp.commission_per_lot_side z config.json (paczka: 0.50)")
    sr.add_argument("--slippage-ticks", type=float, default=2.0)
    sr.add_argument("--cost-stress", type=float, default=1.0, help="mnożnik kosztów zmiennych (np. 1.5 = +50%%)")
    sr.add_argument("--margin-mode", choices=["HEDGING", "NETTING"], default="HEDGING")
    sr.add_argument("--variants", action="store_true", help="porównanie wariantów z config/scalp_variants_v1.json (win ratio i expectancy obok siebie)")
    # 1.46 (I0132): help = the real subset (22_*.bat runs `training run` with every task)
    from .train_all import TRAIN_ALL_TASKS
    _ta_txt = ("podzbiór `training run` (XAUUSD, potem BTC): " + ", ".join(t for t, _ in TRAIN_ALL_TASKS) + " (+ eksport, kontrola, aktywacja, "
               "bot). Pozostałe zadania (scalp_B/C, sh_models, sh_pack, monte_carlo, master_models) trenuje `training run` bez --tasks – "
               "tak robi 22_TRENUJ_WSZYSTKIE_MODELE.bat")
    ta = sub.add_parser("train-all", help=_ta_txt, description=_ta_txt)
    ta.add_argument("--months", type=int, default=None, help="historia (miesiące) – jeden eksport dla wszystkich rodzin modeli")
    ta.add_argument("--scalp-months", type=int, default=None, help="(przestarzałe, ignorowane – historia jest wspólna: --months)")
    ta.add_argument("--commission", type=float, default=None, help="prowizja XAUUSD na 1 lot na stronę (BTC: --commission-btc albo z historii transakcji)")
    ta.add_argument("--commission-btc", type=float, default=None)
    ta.add_argument("--instruments", default="XAUUSD,BTC")
    ta.add_argument("--ml-days", type=int, default=None, help="dni historii dla próbek ML (backfill)")
    ta.add_argument("--lab-bars", type=int, default=None, help="liczba świec M5 na aktywo dla modeli lab")
    ta.add_argument("--min-events", type=int, default=None)
    ta.add_argument("--mt5-wait", type=float, default=None, help="(przestarzałe, ignorowane – połączenie MT5 sprawdza `training run`)")
    ta.add_argument("--ml-no-approx", action="store_true", help="nie używaj próbek odtworzonych z historii (APPROX) w treningu ML")
    ta.add_argument("--skip-candles", action="store_true", help="pomiń forecast, scalp_A, indicator_context")
    ta.add_argument("--skip-ml", action="store_true", help="pomiń ml, ml_scalp")
    ta.add_argument("--skip-lab", action="store_true", help="pomiń lab, neural_scalp, structure_intelligence, flow_context, context_indicators")
    ta.add_argument("--quick", action="store_true", help="test ścieżki: mniej rodzin modeli")
    ta.add_argument("--demo", action="store_true", help="tylko test: uruchamia bota na danych syntetycznych, jeśli nie działa")
    iv = sub.add_parser("import-iv", help="import zmienności implikowanej (CSV/JSON, format: docs/STRATEGIA_WALLS_RANGE_PATTERNS_PL.md)")
    iv.add_argument("file")
    from .exports import cli as _exports_cli                       # 1.46: export-<nazwa>, export-list, import-trader-life-game
    _exports_cli.add_parsers(sub)
    a = ap.parse_args(argv)
    _load_dotenv()
    if a.cmd == "serve":
        return cmd_serve(a)
    if a.cmd == "stop":
        return cmd_stop(a)
    from . import diagnostics
    if a.cmd == "doctor":
        return diagnostics.doctor()
    if a.cmd == "clock":
        return diagnostics.clock()
    if a.cmd == "set-key":
        return diagnostics.set_key()
    if a.cmd == "export":
        return diagnostics.export_history(a.from_utc, a.to_utc, a.out or str(paths.data_dir() / "export_mt5_utc"), a.dst_model)
    if a.cmd == "profile":
        return cmd_profile(a.name)
    if a.cmd == "export-candles":
        from .forecast.export import export_candles
        return export_candles(a.months, a.out, a.dst_model, date_from=a.date_from, date_to=a.date_to, tick_days=a.ticks_days)
    if a.cmd == "export-scalp":
        from .forecast.export import SCALP_TFS, export_candles
        return export_candles(a.months, a.out, a.dst_model, SCALP_TFS, "scalp", date_from=a.date_from, date_to=a.date_to, tick_days=a.ticks_days)
    if a.cmd == "scalp-replay":
        from .scalp.cli import replay_cmd
        return replay_cmd(a)
    if a.cmd == "import-iv":
        return cmd_import_iv(a.file)
    if a.cmd == "train-all":
        from .train_all import train_all
        return train_all(a)
    if a.cmd == "export-list":
        return _exports_cli.list_cmd()
    if a.cmd == "import-trader-life-game":
        return _exports_cli.import_tlg_cmd(a)
    if a.cmd.startswith("export-") and a.cmd[len("export-"):] in _exports_cli.R.EXPORTERS:
        return _exports_cli.run_export(a.cmd[len("export-"):], a)
    return 1


def cmd_import_iv(path: str) -> int:
    """Validated IV import into the local database (used from `available_at` on; never edits existing snapshots)."""
    from pathlib import Path as _P

    from .analysis import iv_import
    from .db.database import Database
    p = _P(path)
    if not p.is_file():
        print(f"[BŁĄD] Brak pliku: {p}")
        return 2
    db = Database()                     # 1.46 arch (I0096): Database.__init__ migrates (the second db.migrate() here was redundant)
    rep = iv_import.store(db, iv_import.parse_text(p.read_text(encoding="utf-8"), "json" if p.suffix.lower() == ".json" else "csv"), imported_by="CLI")
    print(f"[IV] wierszy {rep['rows']}: przyjęto {rep['accepted']}, już zapisane {rep['already_stored']}, odrzucono {len(rep['rejected'])}")
    for r in rep["rejected"][:50]:
        print(f"  wiersz {r['row']}: {r['reason']}")
    return 0 if not rep["rejected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
