"""TEST DOUBLES for the Kronos integration tests (bot side, no torch): a fake bridge with deterministic candles and a stub worker process.

Nothing here is used by the application. The stub worker speaks the same JSON-lines protocol as kronos_runtime.worker but its "forecast"
is a fixed arithmetic rule (last close + 0.1 per step) - it only exercises the bot's plumbing (queue, timeouts, contract, ledger,
settlement, panel). It is never a Kronos forecast and never shown as one outside the tests.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OFF = 7200                                                       # server time = UTC + 2 h (typical broker)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_bars(tf_sec: int, end_utc: float, days: float, *, session: str = "24x7", price: float = 2000.0, tv: int = 50, rv: int = 0,
              forming: bool = True) -> list[dict]:
    """Closed bars (oldest first) ending with the bar that closed at/before end_utc; session '24x7' (BTC-like) or 'XAU' (daily break
    23:00-00:00 server time, closed Saturday + Sunday server time)."""
    out = []
    last_open = int(end_utc // tf_sec * tf_sec) - tf_sec
    t = last_open - int(days * 86400)
    i = 0
    while t <= last_open + (tf_sec if forming else 0):
        raw = t + OFF
        wd = (raw // 86400 + 3) % 7
        hod = (raw % 86400) / 3600
        if session == "XAU" and (wd in (5, 6) or hod >= 23):
            t += tf_sec
            continue
        c = price + 3 * ((i % 40) - 20) / 20 + i * 0.001
        o = c - 0.2
        out.append({"t_raw": raw, "open_utc": iso(t), "o": o, "h": max(o, c) + 0.3, "l": min(o, c) - 0.3, "c": c, "tv": tv, "rv": rv,
                    "closed": t <= last_open})
        i += 1
        t += tf_sec
    return out


class FakeMapping:
    def __init__(self, sym, status="CONFIRMED"):
        self.broker_symbol, self.status = sym, status


class FakeCfg:
    def __init__(self, mappings: dict, main="XAUUSD-"):
        class A:
            pass
        self.assets = A()
        self.assets.mappings = mappings
        self.mt5 = A()
        self.mt5.symbol = main


class FakeCfgStore:
    def __init__(self, cfg):
        self.cfg = cfg

    def get(self):
        return self.cfg


class FakeBridge:
    def __init__(self, bars_by: dict, *, connected=True, synthetic=False, trade_mode="DEMO"):
        self.bars_by = bars_by                                   # (symbol, tf) -> list
        self.connected, self._synthetic, self.trade_mode = connected, synthetic, trade_mode
        self.calls: list = []

    @property
    def synthetic(self):
        return self._synthetic

    def connection_status(self):
        return {"state": "CONNECTED" if self.connected else "RECONNECTING"}

    def account_status(self):
        return {"trade_mode": self.trade_mode}

    def bars(self, tf, limit=None, include_forming=True):
        return []                                                # force symbol_bars (counted) in tests

    def symbol_bars(self, sym, tf, n):
        self.calls.append((sym, tf, n))
        b = self.bars_by.get((sym, tf))
        if b is None:
            raise RuntimeError(f"COPY_RATES_FAILED:{tf}")
        return [dict(x) for x in b[-n:]]

    def symbol_meta(self, sym):
        return {"point": 0.01, "digits": 2}


class Log:
    def __init__(self):
        self.lines = []

    def info(self, *a):
        self.lines.append(("INFO",) + a)

    def warning(self, *a):
        self.lines.append(("WARN",) + a)


class Bus:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


def stub_python(tmp: Path, mode: str = "ok") -> str:
    """An executable that ignores '-m kronos_runtime.worker' and runs the stub worker with this interpreter (POSIX only)."""
    p = Path(tmp) / f"stub_python_{mode}"
    p.write_text(f"#!/bin/sh\nSTUB_MODE={mode} exec {sys.executable} {HERE / 'kronos_stub_worker.py'}\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def fixture_weights(dest: Path) -> Path:
    """A manifest + dummy files in the pinned layout, marked fixture (accepted only with MQ_KRONOS_ALLOW_FIXTURE=1)."""
    sys.path.insert(0, str(HERE.parent / "backend"))
    from kronos_runtime import lock
    from kronos_runtime import manifest as M
    comps = []
    for c in lock.COMPONENTS:
        d = Path(dest) / lock.component_dir_name(c)
        d.mkdir(parents=True, exist_ok=True)
        files = []
        for name in lock.REQUIRED_FILES:
            (d / name).write_bytes(b"{}" if name.endswith(".json") else b"\0" * 64)
            files.append({"name": name, "size": (d / name).stat().st_size, "sha256": M.sha256_file(d / name), "source_check": "fixture"})
        comps.append({"kind": c["kind"], "repo": c["repo"], "revision": c["revision"], "dir": d.name, "files": files})
    M.write(dest, {"schema": lock.MANIFEST_SCHEMA, "installed_at": "2026-01-01T00:00:00Z", "fixture": True, "components": comps})
    return Path(dest)


if __name__ == "__main__":
    print(json.dumps({"ok": True}))
    os._exit(0)
