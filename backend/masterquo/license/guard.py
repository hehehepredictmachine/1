"""LicenseGuard - the single gate of protected modules (deny by default).

Protected while the guard is not OK: new analysis cycles (engine), market scanner, bot signals, ML training/prediction,
AI agent requests, NEW orders (gateway) and the monitor API/WebSocket (except health, license status and STOP).
NOT blocked: PositionManager protection of already open positions (their SL/TP stay on the broker's server; nothing is
closed and no SL/TP is removed because of a license expiry).
"""
from __future__ import annotations

import logging
import threading

from .client import FATAL, MESSAGES, LicenseClient, LicenseError

log = logging.getLogger("masterquo.license")


class LicenseDenied(Exception):
    def __init__(self, feature: str, state: str):
        super().__init__(f"LICENSE_REQUIRED:{feature}:{state}")
        self.feature, self.state = feature, state


class LicenseGuard:
    """Owns the LicenseClient of this run and the renewal thread. `ok()` is cheap (called by every protected loop)."""

    def __init__(self, client: LicenseClient | None, *, on_change=None, telemetry_fn=None):
        self.client = client
        self.state = "ACTIVE" if client is not None and client.lease_ok() else "NO_LICENSE"
        self.reason: str | None = None if self.state == "ACTIVE" else "NO_LICENSE"
        self.on_change = on_change
        self.telemetry_fn = telemetry_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------ checks
    def ok(self) -> bool:
        return self.state == "ACTIVE" and self.client is not None and self.client.lease_ok()

    def require(self, feature: str) -> None:
        if not self.ok():
            raise LicenseDenied(feature, self.public_state())

    def public_state(self) -> str:
        if self.state == "ACTIVE" and not (self.client and self.client.lease_ok()):
            return "LEASE_LAPSED"
        return self.state

    def status(self) -> dict:
        st = self.public_state()
        out = {"state": st, "ok": st == "ACTIVE", "reason": self.reason, "message": MESSAGES.get(self.reason or "", None),
               "last_error": self.last_error}
        if self.client is not None:
            out.update(self.client.status())
        if st != "ACTIVE":
            out["hint"] = ("Nowe sygnały, analiza i nowe zlecenia są zablokowane. Otwarte pozycje pozostają z SL/TP. "
                           "Uruchom ponownie masterquo_start i wklej ważną licencję.")
        return out

    # ------------------------------------------------------------ renewal
    def start(self) -> None:
        if self.client is None or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="license-lease", daemon=True)
        self._thread.start()

    def _set(self, state: str, reason: str | None) -> None:
        changed = (state, reason) != (self.state, self.reason)
        self.state, self.reason = state, reason
        if changed:
            log.warning("license state %s (%s)", state, reason)
            if self.on_change:
                try:
                    self.on_change(self.status())
                except Exception:
                    log.exception("license on_change")

    def _loop(self) -> None:
        while not self._stop.wait(self.client.renew_every):
            if self.state in ("DENIED", "STOPPED"):
                return
            try:
                tel = None
                if self.telemetry_fn and self.client.telemetry_opt_in:
                    try:
                        tel = self.telemetry_fn()
                    except Exception:
                        tel = None
                self.client.renew(tel)
                self.last_error = None
                self._set("ACTIVE", None)
            except LicenseError as e:
                self.last_error = e.code
                if e.code in FATAL:
                    self._set("DENIED", e.code)              # final for this run: a new paste at the next start is required
                    return
                if not self.client.lease_ok():
                    self._set("LEASE_LAPSED", e.code)        # network/server problem: blocked until a renewal succeeds
            except Exception as e:                           # never let the thread die silently
                self.last_error = type(e).__name__
                if not self.client.lease_ok():
                    self._set("LEASE_LAPSED", "SERVER_UNREACHABLE")

    def stop(self) -> None:
        self._stop.set()
        if self.client is not None:
            self.client.end()
        self.state = "STOPPED"


def prompt_key(stdin=None, stdout=None) -> str:
    """Asks for the key on the console (hidden input on a terminal; one line from stdin otherwise, e.g. a pipe in tests).
    The value is returned to the caller only - never stored, logged or echoed."""
    import getpass
    import sys
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stdout.write("\n================ MasterQUO - licencja ================\n"
                 "Serwer glowny wystartuje dopiero po przyjeciu licencji.\n"
                 "Wklej klucz (prawy przycisk myszy lub Ctrl+V) - znaki nie sa wyswietlane.\n\n")
    stdout.flush()
    if stdin.isatty():
        return getpass.getpass("Wklej licencję MasterQUO (MQL72-…) i naciśnij Enter: ")
    stdout.write("Wklej licencję MasterQUO (MQL72-…) i naciśnij Enter: \n")
    stdout.flush()
    return (stdin.readline() or "").strip()


def licensed(component) -> bool:
    """True only when the component was given a guard (attribute `license`) and that guard is OK. A component without
    a guard is NOT licensed (deny by default): the runtime always injects the guard of this run."""
    g = getattr(component, "license", None)
    return g is not None and g.ok()
