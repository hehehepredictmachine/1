"""How the bridge attaches to MetaTrader 5 (1.10.1).

`initialize()` without arguments attaches to the terminal the MetaTrader5 package finds first and uses the account that
terminal is logged into. "-6 Terminal: Authorization failed" therefore means: that terminal has no logged-in account
(or the broker rejected it) - or the package picked ANOTHER installed terminal than the one the user logged into.

What this module adds (nothing here sends an order):
  * optional explicit login: mt5.login + mt5.server from the config, password ONLY from the local secret store
    (MT5_PASSWORD - Windows DPAPI; never in config.json, never in logs or API responses);
  * after an authorization / IPC failure with no fixed terminal_path: the installed terminals are discovered (running
    processes and the usual install folders, MetaQuotes "origin.txt") and tried one by one;
  * a rejected password is not retried in a loop (brokers lock accounts after repeated failures) - it is retried only
    after the login / server / password changes;
  * a Polish hint for the known error codes.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

AUTH_FAILED = -6
IPC_CODES = (-10001, -10002, -10003, -10004, -10005)

HINTS = {
    AUTH_FAILED: "Terminal MT5 nie ma zalogowanego rachunku albo broker odrzucił logowanie. Zaloguj rachunek w MT5 (Plik → Zaloguj, "
                 "zaznacz „Zapisz hasło”) albo podaj login, serwer i hasło w Ustawienia → MT5. Przy kilku instalacjach MT5 wskaż "
                 "ścieżkę terminal64.exe.",
    -10003: "Nie znaleziono uruchomionego terminala MT5 x64 – uruchom MT5 (ten sam użytkownik Windows, bez „Uruchom jako administrator”).",
    -10004: "Terminal MT5 nie odpowiada (IPC) – uruchom go ponownie.",
    -10005: "Przekroczony czas połączenia z MT5 (IPC) – terminal jest zajęty lub zablokowany oknem dialogowym.",
}


def error_code(err) -> int | None:
    try:
        return int(err[0])
    except (TypeError, ValueError, IndexError):
        return None


def hint(err) -> str:
    return HINTS.get(error_code(err), "")


def init_kwargs(cfg, password: str | None, *, path: str | None = None) -> dict:
    """Arguments for MetaTrader5.initialize(). Login is used only with BOTH login and server set; the password only from
    the secret store (may be absent: the terminal's saved password is used then)."""
    kw: dict = {}
    p = path or getattr(cfg, "terminal_path", None)
    if p:
        kw["path"] = p
    login, server = getattr(cfg, "login", None), getattr(cfg, "server", None)
    if login and server:
        kw["login"] = int(login)
        kw["server"] = str(server)
        if password:
            kw["password"] = password
    return kw


def credentials_key(cfg, password: str | None) -> str:
    """Identifies the credential set (no secret in clear: only whether a password exists and its length)."""
    return f"{getattr(cfg, 'login', None)}@{getattr(cfg, 'server', None)}#{len(password or '')}"


def running_terminals() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip().lower().endswith("terminal64.exe")]


def discover_terminals(env: dict | None = None, running: list[str] | None = None) -> list[str]:
    """Installed terminal64.exe paths: running ones first, then MetaQuotes data folders (origin.txt) and Program Files.
    Duplicates removed (case-insensitive); only existing files."""
    env = dict(os.environ) if env is None else env
    cands = list(running_terminals() if running is None else running)
    appdata = env.get("APPDATA")
    if appdata:
        for origin in glob.glob(os.path.join(appdata, "MetaQuotes", "Terminal", "*", "origin.txt")):
            for enc in ("utf-16", "utf-8"):
                try:
                    with open(origin, encoding=enc) as f:
                        d = f.read().strip().strip("﻿")
                    if d:
                        cands.append(os.path.join(d, "terminal64.exe"))
                    break
                except (OSError, UnicodeError):
                    continue
    for pf in (env.get("ProgramFiles"), env.get("ProgramW6432"), env.get("ProgramFiles(x86)")):
        if pf:
            cands += sorted(glob.glob(os.path.join(pf, "*", "terminal64.exe")))
    seen, out = set(), []
    for c in cands:
        k = os.path.normcase(os.path.abspath(c))
        if k not in seen and os.path.isfile(c):
            seen.add(k)
            out.append(c)
    return out
