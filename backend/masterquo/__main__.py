"""Command line entry point (used by the Windows launchers).

  python -m masterquo serve [--demo] [--no-browser]   start (or open the already running monitor)
  python -m masterquo stop                              stop only this project's server
  python -m masterquo doctor                            environment + MT5 + Claude diagnostics
  python -m masterquo clock                             raw MT5 time diagnostics (no trading)
  python -m masterquo set-key                           store the Anthropic API key locally (DPAPI)
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

from . import paths


def _rt_dir() -> Path:
    d = paths.data_dir() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _port() -> int:
    try:
        from .config import ConfigStore
        return ConfigStore().get().server.port
    except Exception:
        return 8765


def _health(port: int, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/health", headers={"Host": f"127.0.0.1:{port}"}), timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


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


def cmd_serve(args) -> int:
    if args.demo and not os.environ.get("MASTERQUO_DATA_DIR"):
        os.environ["MASTERQUO_DATA_DIR"] = str(paths.ROOT_DIR / "data" / "demo_synthetic")
    port = _port()
    url = f"http://127.0.0.1:{port}/"
    h = _health(port)
    if h and h.get("app") == "MasterQUO AI":
        print(f"[MasterQUO] Aplikacja już działa ({'DANE SYNTETYCZNE' if h.get('synthetic') else 'MT5'}) – otwieram monitor {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    if h is not None or _port_busy(port):
        print(f"[MasterQUO] Port {port} jest zajęty przez inny program. Zmień server.port w data\\config.json.", file=sys.stderr)
        return 3
    _setup_logging()
    lock = _single_instance_lock()
    if lock is None:
        print("[MasterQUO] Inna instancja MasterQUO już się uruchamia w tym folderze.", file=sys.stderr)
        return 4
    import uvicorn
    from .api.app import create_app
    from .runtime import Runtime
    rt = Runtime(demo=args.demo)
    app = create_app(rt, port)
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
                print(f"[MasterQUO] Monitor gotowy: {url}  ({'DANE SYNTETYCZNE' if args.demo else 'tryb wykonania wg ustawień'})")
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
        print("[MasterQUO] Zatrzymano.")
    return 0


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


def _single_instance_lock():
    global _LOCK_HANDLE
    f = open(_rt_dir() / "instance.lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    _LOCK_HANDLE = f
    return f


def cmd_stop(args) -> int:
    port = _port()
    tokf = _rt_dir() / "shutdown.token"
    if not _health(port):
        print("[MasterQUO] Aplikacja nie działa (brak odpowiedzi na porcie %d)." % port)
        return 0
    if not tokf.exists():
        print("[MasterQUO] Brak pliku tokenu zatrzymania – zamknij okno serwera MasterQUO ręcznie.", file=sys.stderr)
        return 2
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/admin/shutdown", data=b"{}", method="POST",
                                 headers={"x-mq-shutdown": tokf.read_text(encoding="utf-8").strip(), "Content-Type": "application/json",
                                          "Host": f"127.0.0.1:{port}"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, OSError) as exc:
        print("[MasterQUO] Nie udało się wysłać żądania zatrzymania:", exc, file=sys.stderr)
        return 3
    for _ in range(40):
        if not _health(port, 0.8):
            print("[MasterQUO] Zatrzymano serwer MasterQUO (terminal MT5 i inne programy Python nie zostały zamknięte).")
            return 0
        time.sleep(0.5)
    print("[MasterQUO] Serwer nie zakończył się w czasie 20 s – zamknij okno 'MasterQUO server'.", file=sys.stderr)
    return 4


def _load_dotenv() -> None:
    """Optional <root>/.env with ANTHROPIC_API_KEY / ANTHROPIC_MODEL / MASTERQUO_DATA_DIR (never packaged)."""
    f = paths.ROOT_DIR / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = (x.strip() for x in line.split("=", 1))
        if k in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "MASTERQUO_DATA_DIR", "FRED_API_KEY", "TELEGRAM_BOT_TOKEN") and v and not os.environ.get(k):
            os.environ[k] = v.strip('"')


def cmd_profile(name: str) -> int:
    """Rollback helper. Run with the server stopped (a running server keeps its own copy of the config)."""
    from .config import ConfigStore
    store = ConfigStore()
    if name == "show":
        a = store.get().active
        print(f"Profil: {a.profile}, wybór strategii: {a.strategy_mode}{' ' + a.manual_strategy_id if a.manual_strategy_id else ''}")
        return 0
    store.update({"active": {"profile": name}})
    print(f"[OK] Profil wykrywania: {name}. Tryb wykonywania zleceń i limity bez zmian. Uruchom 03_START_MASTERQUO.bat.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="masterquo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--demo", action="store_true", help="DANE SYNTETYCZNE (symulator terminala, oddzielna baza)")
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("doctor")
    sub.add_parser("clock")
    sub.add_parser("set-key")
    pr = sub.add_parser("profile", help="przełącz profil wykrywania: ACTIVE (S01-S10 + AUTO) albo ORIGINAL (M07 jak w 1.1)")
    pr.add_argument("name", choices=["ACTIVE", "ORIGINAL", "show"])
    e = sub.add_parser("export", help="eksport 6 TF w formacie M06R z czasem UTC")
    e.add_argument("--from-utc", required=True)
    e.add_argument("--to-utc", required=True)
    e.add_argument("--out", default=str(paths.ROOT_DIR / "data" / "export_mt5_six_tf"))
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
        # product function: requires a fresh online lease (same LicenseGuard as the app); doctor/clock/stop stay available
        from .config import ConfigStore
        from .licensing.service import LicenseService
        from .secrets_store import SecretStore
        lic = LicenseService(ConfigStore(), SecretStore(), paths.data_dir())
        if not lic.heartbeat_now() or not lic.guard.allows("analysis"):
            print(f"Eksport wymaga ważnej licencji (online): {lic.guard.reason}")
            return 3
        return diagnostics.export_history(a.from_utc, a.to_utc, a.out)
    if a.cmd == "profile":
        return cmd_profile(a.name)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
