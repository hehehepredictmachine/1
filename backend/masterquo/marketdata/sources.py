"""Where candles come from. Every source exposes `call(fn)` = run fn(mt5_module) on a terminal connection, plus the server clock
offset. The export logic is the same for all of them.

* BridgeSource - the running bot's bridge (its MT5 worker thread, low priority): the bot and the terminal on the same Windows machine.
* DirectSource - a standalone process with its own MetaTrader5 connection (Windows, terminal logged in) or the terminal simulator
  in tests. Order functions are not reachable (forecast.export.NoOrders wrapper).
* MT5 on ANOTHER machine: there is no network access to a remote terminal in this program. Run the export on the machine with MT5
  (bot panel or 32_CENTRUM_TRENINGU.bat there), copy the folder data/marketdata/<INSTRUMENT> (or the exported dataset zip) and import
  it here with `python -m masterquo trainhub import-data <folder|zip>` - checksums of the manifest are verified before the merge.
"""
from __future__ import annotations

import time


class SourceError(RuntimeError):
    pass


class BridgeSource:
    kind = "BRIDGE"

    def __init__(self, bridge):
        self.bridge = bridge

    def call(self, fn):
        from ..mt5.worker import PRIO_HISTORY
        if getattr(self.bridge, "state", "CONNECTED") != "CONNECTED":
            raise SourceError(f"terminal MT5 niepołączony ({getattr(self.bridge, 'state', '?')})")
        return self.bridge.raw_call(fn, PRIO_HISTORY, timeout=120)

    def offset(self, symbol: str) -> tuple[float | None, str]:
        off = getattr(self.bridge.clock, "offset", None)
        return (float(off), "BRIDGE_CLOCK_MEASURED") if off is not None else (None, "UNKNOWN")

    def synthetic(self) -> bool | None:
        """True = terminal simulator, False = a real MetaTrader5 terminal, None = could not tell (then the data is never labelled real)."""
        from ..mt5.fake import is_fake
        try:
            return bool(self.call(lambda m: is_fake(m)))
        except Exception:  # noqa: BLE001
            flag = getattr(self.bridge, "synthetic", None)
            flag = flag() if callable(flag) else flag
            return bool(flag) if flag is not None else None

    def describe(self) -> dict:
        return {"kind": self.kind, "note": "bridge bota (ten sam terminal i połączenie co bot; zapytania o niskim priorytecie)"}


class DirectSource:
    kind = "MT5_DIRECT"

    def __init__(self, mt5, *, offset: float | None = None, offset_basis: str | None = None, server: str | None = None):
        from ..forecast.export import NoOrders
        self.mt5 = NoOrders(mt5)
        self._offset, self._basis, self.server = offset, offset_basis, server

    def call(self, fn):
        return fn(self.mt5)

    def offset(self, symbol: str) -> tuple[float | None, str]:
        if self._offset is not None:
            return float(self._offset), self._basis or "GIVEN"
        from ..forecast.export import _measure_offset
        off, basis = _measure_offset(self.mt5, symbol, self.server)
        self._offset, self._basis = off, basis
        return off, basis

    def synthetic(self) -> bool:
        from ..mt5.fake import is_fake
        return bool(is_fake(self.mt5))

    def describe(self) -> dict:
        return {"kind": self.kind, "note": "osobne połączenie z MT5 (proces eksportu)"}


def open_direct(cfg) -> DirectSource:
    """Standalone connection to the logged-in terminal (Windows). Raises SourceError with an actionable message."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise SourceError("BRAK_MT5: pakiet MetaTrader5 niedostępny – eksport bezpośredni działa na Windows z zainstalowanym i zalogowanym "
                          "terminalem (albo uruchom eksport z panelu bota, który ma połączenie z MT5)") from None
    from ..diagnostics import attach
    if not attach(mt5, cfg):
        raise SourceError(f"initialize(): {mt5.last_error()} – uruchom i zaloguj terminal MT5")
    acc = mt5.account_info()
    return DirectSource(mt5, server=getattr(acc, "server", None))


def retry(fn, attempts: int = 3, base_delay: float = 0.5, sleep=time.sleep):
    """fn() with exponential backoff; the last exception is re-raised."""
    last = None
    for k in range(attempts):
        try:
            r = fn()
            if r is not None:
                return r
            last = SourceError("terminal zwrócił None (brak danych albo błąd zapytania)")
        except Exception as exc:  # noqa: BLE001
            last = exc
        if k < attempts - 1:
            sleep(base_delay * (2 ** k))
    raise last if isinstance(last, Exception) else SourceError("nieznany błąd")
