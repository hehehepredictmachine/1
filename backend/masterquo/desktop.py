"""Desktop application settings (PepeMarketWizardDesktop.exe).

The Windows shell supervises this engine and starts it with PMW_DESKTOP=1 and PMW_DESKTOP_EXE=<path of the shell>. The panel
changes the shell's behaviour only through this module, i.e. through the protected local API (session + CSRF + Origin + Host):

* <data>/desktop_prefs.json - what closing the window does (ask / background / exit) and whether an autostart start goes to the
  tray. The shell reads the file when the window is closed and at start.
* autostart - value "PepeMarketWizard" under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run with "<exe>" --autostart.
  Only the current user, no administrator rights, OFF until the user switches it on (never enabled silently).
* engine restart - <data>/runtime/restart.request + a normal shutdown; the shell sees the request and starts the engine again
  at once (without the crash backoff).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Protocol

from . import paths

CLOSE_ACTIONS = ("ask", "background", "exit")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "PepeMarketWizard"
DEFAULT_PREFS = {"close_action": "ask", "autostart": False, "start_minimized": False}


class DesktopError(ValueError):
    pass


class Registry(Protocol):
    def get(self) -> str | None: ...
    def set(self, command: str) -> None: ...
    def delete(self) -> None: ...


class WinRunKey:
    """HKCU Run value of this app (current user only)."""

    def get(self) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                return str(winreg.QueryValueEx(k, RUN_VALUE)[0])
        except FileNotFoundError:
            return None

    def set(self, command: str) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, command)

    def delete(self) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, RUN_VALUE)
        except FileNotFoundError:
            pass


def _registry() -> Registry | None:
    return WinRunKey() if sys.platform == "win32" else None


def desktop_exe() -> str | None:
    """Path of the supervising desktop shell, None when the engine runs without it (BAT launcher, tests)."""
    if os.environ.get("PMW_DESKTOP") != "1":
        return None
    return os.environ.get("PMW_DESKTOP_EXE") or None


def autostart_command(exe: str) -> str:
    return f'"{exe}" --autostart'


def _prefs_path():
    return paths.data_dir() / "desktop_prefs.json"


def load_prefs() -> dict:
    p = dict(DEFAULT_PREFS)
    try:
        raw = json.loads(_prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return p
    if raw.get("close_action") in CLOSE_ACTIONS:
        p["close_action"] = raw["close_action"]
    p["autostart"] = bool(raw.get("autostart"))
    p["start_minimized"] = bool(raw.get("start_minimized"))
    return p


def _write_prefs(p: dict) -> None:
    path = _prefs_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(p, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def info(reg: Registry | None = None) -> dict:
    reg = reg if reg is not None else _registry()
    exe = desktop_exe()
    registered = None
    if reg is not None:
        try:
            registered = reg.get()
        except OSError:
            registered = None
    prefs = load_prefs()
    return {
        "desktop": exe is not None,
        "exe": exe,
        "prefs": prefs,
        "autostart_supported": exe is not None and reg is not None,
        "autostart_registered": registered is not None,
        # the entry points to another copy of the app (moved / second folder) - shown so the user can fix it by saving again
        "autostart_other_exe": registered is not None and exe is not None and registered != autostart_command(exe),
        "restart_supported": exe is not None,
        "data_dir": str(paths.data_dir()),
        "logs_dir": str(paths.logs_dir()),
    }


def save_prefs(close_action: str, autostart: bool, start_minimized: bool, reg: Registry | None = None) -> dict:
    if close_action not in CLOSE_ACTIONS:
        raise DesktopError(f"close_action musi być jednym z {CLOSE_ACTIONS}")
    reg = reg if reg is not None else _registry()
    exe = desktop_exe()
    if autostart and (exe is None or reg is None):
        raise DesktopError("AUTOSTART_NEEDS_DESKTOP_APP: autostart działa tylko w aplikacji Windows (PepeMarketWizardDesktop.exe)")
    if reg is not None and exe is not None:
        if autostart:
            reg.set(autostart_command(exe))
        elif reg.get() is not None:
            reg.delete()
    _write_prefs({"close_action": close_action, "autostart": bool(autostart), "start_minimized": bool(start_minimized)})
    return info(reg)


def request_restart() -> None:
    """Marks the coming shutdown as a restart for the shell. Only meaningful when the shell supervises the engine."""
    if desktop_exe() is None:
        raise DesktopError("RESTART_NEEDS_DESKTOP_APP: ponowne uruchomienie silnika obsługuje aplikacja Windows")
    d = paths.data_dir() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    (d / "restart.request").write_text("1", encoding="utf-8")
