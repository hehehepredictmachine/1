"""MasterQUO M01→M02→M02I read-only continuous bridge v1.0 CANDIDATE.

Local Windows + MetaTrader5 only. This is NOT a full M01 production validator,
NOT an order executor, and NOT an empirical strategy signal generator.
Original M01/M02/M02I sources are copied unmodified under vendor/.

Per startup/new closed candle:
 - fetch 261 MT5 bars per TF (last bar forming is excluded)
 - run M02 on SAME snapshot as M02I
 - write atomic monitor JSON with execution BLOCKED.
Between closes: update verified-as-received bid/ask and health, do NOT
refit/recompute closed-bar indicators for each tick.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

BASE = Path(__file__).resolve().parent
for sub in ("M01", "M02", "M02I"):
    sys.path.insert(0, str(BASE / "vendor" / sub))

from M01_CONTINUOUS_MT5_OBSERVER_REFERENCE import Observer, TF_NAMES  # noqa
from M02_REFERENCE_ENGINE import analyze as analyze_m02, RegimeMemory  # noqa
from M02I_INDICATOR_ENGINE import analyze as analyze_m02i  # noqa
from M02I_MT5_READONLY_PREVIEW import preview_snapshot  # noqa

VERSION = "1.0.0-CANDIDATE"
DEFAULT_M02 = BASE / "vendor" / "M02" / "M02_PROFILE.example.json"
DEFAULT_M02I = BASE / "vendor" / "M02I" / "M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json"
STATUS_VALID = {"PASS", "PASS_WITH_LIMITATIONS"}


def stamp(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc).isoformat()


def parse_time(s: str) -> datetime:
    value = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def atomic_json(path: str | Path, data: dict) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8") + b"\n"
    fd, temp_name = tempfile.mkstemp(prefix=".masterquo_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(raw)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def validate_configuration(settings: dict) -> None:
    if settings.get("data_source_policy") != "MT5_PRIMARY_TV_SUPPLEMENTAL_NO_SCREENSHOTS":
        raise ValueError("INVALID_SOURCE_POLICY")
    if settings.get("account_profile") != "ZERO_SPREAD_DECLARED_UNVERIFIED":
        raise ValueError("ACCOUNT_PROFILE_MUST_REMAIN_UNVERIFIED")
    if settings.get("enable_orders") is not False or settings.get("screenshots_enabled") is not False:
        raise ValueError("READ_ONLY_REQUIRED")
    for k in ("quote_poll_seconds", "bar_poll_seconds", "heartbeat_seconds", "max_quote_age_seconds", "full_refresh_seconds"):
        v = settings.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0:
            raise ValueError("INVALID_" + k.upper())
    n = settings.get("history_closed_bars")
    if not isinstance(n, int) or isinstance(n, bool) or n < 230 or n > 2000:
        raise ValueError("HISTORY_BAR_COUNT_230_TO_2000")


class IntegratedReadOnlyMonitor:
    def __init__(self, mt5: Any, symbol: str, settings: dict,
                 m02_profile: dict, m02i_profile: dict,
                 monitor_file: str | Path,
                 clock: Callable[[], datetime] | None = None,
                 session_id: str | None = None, dxy_symbol: str | None = None):
        validate_configuration(settings)
        if not isinstance(symbol, str) or not symbol.strip() or any(ord(c) < 32 for c in symbol):
            raise ValueError("INVALID_BROKER_SYMBOL")
        if dxy_symbol is not None and (not dxy_symbol.strip() or any(ord(c) < 32 for c in dxy_symbol)):
            raise ValueError("INVALID_DXY_SYMBOL")
        self.mt5 = mt5
        self.symbol = symbol
        self.dxy_symbol = dxy_symbol
        self.settings = copy.deepcopy(settings)
        self.m02_profile = copy.deepcopy(m02_profile)
        self.m02i_profile = copy.deepcopy(m02i_profile)
        self.monitor_file = Path(monitor_file)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.session_id = session_id or uuid4().hex
        self.sequence = 0
        self.regime_memory = RegimeMemory(m02_profile["regime_confirmation_bars"])
        self.quote: dict | None = None
        self.market: dict | None = None
        self.indicators: dict | None = None
        self.snapshot: dict | None = None
        self.events: list[dict] = []
        self.new_closed_bars = False
        self.connected = False
        self.last_error: str | None = "NOT_CONNECTED"
        subscriptions = {symbol: list(TF_NAMES)}
        if dxy_symbol and dxy_symbol != symbol:
            subscriptions[dxy_symbol] = ["H1"]
        self.observer = Observer(mt5, symbol, subscriptions,
                                 settings["quote_poll_seconds"],
                                 settings["bar_poll_seconds"],
                                 self.on_event,
                                 heartbeat_s=settings["heartbeat_seconds"])
        self.last_published: dict | None = None

    def on_event(self, event: dict) -> None:
        typ = event.get("event_type")
        minimal = {"event_type": typ, "received_at": event.get("received_at"),
                   "timeframe": event.get("timeframe"), "reason": event.get("reason")}
        self.events.append(minimal)
        self.events = self.events[-40:]
        if typ == "quote_updated" and event.get("symbol") == self.symbol:
            self.quote = {"bid": event["bid"], "ask": event["ask"],
                          "spread_abs": event["spread_abs"],
                          "source_timestamp": event["source_timestamp"],
                          "source": "MT5_BROKER", "symbol": self.symbol}
        elif typ == "candle_closed":
            self.new_closed_bars = True
        elif typ in ("data_degraded", "data_gap"):
            if event.get("reason") in ("QUOTE_UNAVAILABLE", "INVALID_BID_ASK"):
                self.quote = None  # never retain formerly-good broker quote as current
            self.last_error = str(event.get("reason") or typ)

    def now(self) -> datetime:
        return self.clock().astimezone(timezone.utc)

    def start(self, terminal_path: str | None = None) -> bool:
        # A reconnect cannot prove we observed all bars during disconnection.
        self.observer.last_open.clear()
        self.observer.last_bar_data.clear()
        self.quote = None
        self.regime_memory = RegimeMemory(self.m02_profile["regime_confirmation_bars"])
        if not self.observer.connect(terminal_path):
            self.connected = False
            self.last_error = "M01_CONNECT_FAILED"
            self.publish()
            return False
        self.connected = True
        self.last_error = None
        try:
            self.observer.check_quote()
            self.observer.check_bars()
            self.refresh()
        except Exception as ex:
            self.last_error = "STARTUP_READ_FAILED:" + type(ex).__name__
            self.connected = False
            self.observer.close()
            self.publish()
            return False
        return True

    def refresh(self) -> dict:
        if not self.connected:
            raise RuntimeError("MT5_DISCONNECTED")
        now = self.now()
        snap = preview_snapshot(self.mt5, self.symbol,
                                self.settings["history_closed_bars"], now,
                                self.dxy_symbol)
        self.sequence += 1
        snap["analysis_id"] = "BRIDGE-" + self.session_id
        snap["snapshot_id"] = f"M01-M02-M02I:{self.session_id}:{self.sequence}"
        snap["_preview_only"] = True
        snap["data_gates"] = [
            {"gate_id": "M01_FULL_PRODUCTION_AUDIT", "status": "PENDING",
             "required_for": ["ANALYSIS", "DIRECTION"],
             "reason_codes": ["M01_REFERENCE_OBSERVER_NOT_FULL_VALIDATOR"]},
            {"gate_id": "M01_EXECUTION_DATA", "status": "PENDING",
             "required_for": ["EXECUTION"],
             "reason_codes": ["NO_PRODUCTION_EXECUTION_VALIDATION"]},
        ]
        snap["bridge_data_status"] = "UNVERIFIED_DIAGNOSTIC"
        # Same immutable point-in-time snapshot for both engines.
        m02 = analyze_m02(snap, self.m02_profile, runtime_health={
            "status": "UNKNOWN", "execution_data_gate": "UNKNOWN"
        }, memory=self.regime_memory)
        m02i = analyze_m02i({"data_snapshot": snap, "market_state": m02}, self.m02i_profile)
        if m02["snapshot_id"] != m02i["snapshot_id"] or m02["as_of"] != m02i["as_of"]:
            raise RuntimeError("M02_M02I_SNAPSHOT_MISMATCH")
        if m02["status"] in STATUS_VALID or m02i["status"] in STATUS_VALID:
            raise RuntimeError("UNEXPECTED_AUDIT_PROMOTION")
        self.snapshot = snap
        self.market = m02
        self.indicators = m02i
        self.new_closed_bars = False
        self.last_error = None if not snap.get("preview_reasons") else "SNAPSHOT_HAS_LIMITATIONS"
        return self.publish()

    def quote_health(self) -> tuple[str, list[str], float | None]:
        if not self.connected:
            return "DISCONNECTED", ["MT5_DISCONNECTED"], None
        if not self.quote:
            return "PENDING", ["BROKER_QUOTE_UNAVAILABLE"], None
        try:
            t = parse_time(self.quote["source_timestamp"])
            age = (self.now() - t).total_seconds()
            bid, ask = self.quote["bid"], self.quote["ask"]
            if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
                return "FAIL", ["INVALID_BID_ASK"], age
            if age < -self.settings["max_quote_age_seconds"]:
                return "FAIL", ["FUTURE_BROKER_TICK"], age
            if age > self.settings["max_quote_age_seconds"]:
                return "STALE", ["STALE_BROKER_QUOTE"], age
            return "RECEIVED", [], age
        except (ValueError, KeyError, TypeError):
            return "FAIL", ["INVALID_QUOTE_TIMESTAMP"], None

    def make_report(self) -> dict:
        quality, warnings, age = self.quote_health()
        market_status = self.market.get("status") if self.market else "NOT_RUN"
        indicator_status = self.indicators.get("status") if self.indicators else "NOT_RUN"
        reasons = list(dict.fromkeys((warnings +
                     (self.snapshot.get("preview_reasons", []) if self.snapshot else []) +
                     ([self.last_error] if self.last_error else []) +
                     ["M01_PRODUCTION_AUDIT_PENDING", "NO_AUTO_TRADING"])))
        return {
            "schema_version": "2.0.0", "prompt_version": "4.1.0",
            "module_id": "M01_M02_M02I_BRIDGE", "bridge_version": VERSION,
            "updated_at": stamp(self.now()), "connection_status": "CONNECTED" if self.connected else "DISCONNECTED",
            "data_mode": "MT5_LIVE_READONLY_DIAGNOSTIC", "symbol": self.symbol,
            "timeframes": list(TF_NAMES), "optional_dxy_symbol": self.dxy_symbol,
            "quote": dict(self.quote, age_seconds=round(age, 4) if age is not None else None,
                          health_status=quality) if self.quote and self.connected else None,
            "quote_status": quality, "account_profile": "ZERO_SPREAD_DECLARED_UNVERIFIED",
            "real_broker_costs_verified": False,
            "snapshot_id": self.snapshot.get("snapshot_id") if self.snapshot else None,
            "analysis_id": self.snapshot.get("analysis_id") if self.snapshot else None,
            "snapshot_as_of": self.snapshot.get("as_of") if self.snapshot else None,
            "market_state": self.market, "indicator_intelligence": self.indicators,
            "m02_status": market_status, "m02i_status": indicator_status,
            "research_observation_only": True, "live_signal_available": False,
            "execution_permission": "BLOCKED", "execution_eligible": False,
            "live_execution_allowed": False, "submitted_order_id": None,
            "visual_capture_enabled": False, "screen_capture_count": 0,
            "reason_codes": reasons, "last_events": self.events[-12:],
        }

    def publish(self) -> dict:
        report = self.make_report()
        atomic_json(self.monitor_file, report)
        self.last_published = report
        return report

    def poll(self, check_bars: bool = True) -> dict:
        if not self.connected:
            return self.publish()
        try:
            terminal = self.mt5.terminal_info()
            if terminal is None or not getattr(terminal, "connected", False):
                self.disconnect("TERMINAL_CONNECTION_LOST")
                return self.last_published
            self.observer.check_quote()
            if check_bars:
                self.observer.check_bars()
            if self.new_closed_bars:
                return self.refresh()
            return self.publish()
        except Exception as ex:
            self.disconnect("MT5_POLL_FAILED:" + type(ex).__name__)
            return self.last_published

    def disconnect(self, reason: str = "STOPPED") -> None:
        self.connected = False
        self.last_error = reason
        try:
            self.observer.close()
        except Exception:
            pass
        self.publish()


def run_windows(args: argparse.Namespace) -> int:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("Brak pakietu MetaTrader5. Windows: py -m pip install MetaTrader5", file=sys.stderr)
        return 2
    settings = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    if args.quote_poll_seconds is not None:
        settings["quote_poll_seconds"] = args.quote_poll_seconds
    if args.bar_poll_seconds is not None:
        settings["bar_poll_seconds"] = args.bar_poll_seconds
    if args.bars is not None:
        settings["history_closed_bars"] = args.bars
    monitor = IntegratedReadOnlyMonitor(mt5, args.symbol, settings,
        json.loads(Path(args.m02_profile).read_text(encoding="utf-8")),
        json.loads(Path(args.m02i_profile).read_text(encoding="utf-8")),
        args.monitor_file, dxy_symbol=args.dxy_symbol)
    started = time.monotonic()
    next_quote = next_bars = next_attempt = next_full_refresh = 0.0
    attempts = 0
    try:
        while args.duration_seconds is None or time.monotonic() - started < args.duration_seconds:
            now_mono = time.monotonic()
            if not monitor.connected:
                if now_mono >= next_attempt:
                    if monitor.start(args.terminal_path):
                        attempts = 0
                        next_quote = next_bars = now_mono
                        next_full_refresh = now_mono + settings["full_refresh_seconds"]
                        print("MT5 podłączony (podgląd diagnostyczny; handel zablokowany).", flush=True)
                    else:
                        attempts += 1
                        next_attempt = now_mono + min(30.0, 2.0 ** min(5, attempts))
                        print("MT5 niedostępny, bezpieczne ponowienie po przerwie.", flush=True)
            else:
                due_quote = now_mono >= next_quote
                due_full = now_mono >= next_full_refresh
                due_bars = now_mono >= next_bars
                if due_quote or due_bars or due_full:
                    if due_full:
                        try:
                            monitor.refresh()
                        except Exception as exc:
                            monitor.disconnect("PERIODIC_HISTORY_REFRESH_FAILED:" + type(exc).__name__)
                        next_full_refresh = now_mono + settings["full_refresh_seconds"]
                    if monitor.connected and (due_quote or due_bars):
                        monitor.poll(check_bars=due_bars)
                    if due_quote:
                        next_quote = now_mono + settings["quote_poll_seconds"]
                    if due_bars:
                        next_bars = now_mono + settings["bar_poll_seconds"]
                    if not monitor.connected:
                        attempts += 1
                        next_attempt = now_mono + min(30.0, 2.0 ** min(5, attempts))
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.disconnect("STOPPED_BY_USER")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MasterQUO M01/M02/M02I continuous MT5 read-only indicator monitor")
    ap.add_argument("--symbol", default="XAUUSD", help="Dokładna nazwa symbolu u brokera")
    ap.add_argument("--dxy-symbol", default=None, help="Opcjonalny indeks DXY u brokera")
    ap.add_argument("--terminal-path", default=None, help="Opcjonalna ścieżka do terminal64.exe")
    ap.add_argument("--settings", default=str(BASE / "BRIDGE_SETTINGS.example.json"))
    ap.add_argument("--m02-profile", default=str(DEFAULT_M02))
    ap.add_argument("--m02i-profile", default=str(DEFAULT_M02I))
    ap.add_argument("--monitor-file", default=str(BASE / "runtime" / "monitor_indicators.json"))
    ap.add_argument("--quote-poll-seconds", type=float, default=None)
    ap.add_argument("--bar-poll-seconds", type=float, default=None)
    ap.add_argument("--bars", type=int, default=None)
    ap.add_argument("--duration-seconds", type=float, default=None, help="Diagnostyczny, opcjonalny limit uruchomienia")
    return run_windows(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
