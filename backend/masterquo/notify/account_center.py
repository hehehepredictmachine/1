"""Telegram Control Center - MT5 account bridge (Apollo23 TASK 017).

Reuses TelegramNotifier (token only in SecretStore / DPAPI, outbound sendMessage only - no getUpdates, no webhook, no commands) and the
existing MarketBridge deal list (no second MT5 session). Everything is OFF by default and nothing is sent without an explicitly PINNED
account (exact server:login). On the first enable / bind a BASELINE is written: deals that already exist are marked seen - no history
replay. A persistent cursor + outbox with dedup keys guarantee each event is sent at most once. Account ROI = stats.account_roi
(Modified Dietz, whole account incl. manual / external EAs) - separate from PMW strategy stats. No order method exists here.
"""
from __future__ import annotations

import json
import re
import string
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULTS = {"bound_account_key": None, "account_event_enabled": False, "account_event_scope": "ALL_ACCOUNT", "notify_position_open": False,
            "notify_partial_close": False, "notify_position_close": False, "notify_position_reversal": False, "symbol_allowlist": [],
            "symbol_exclude": [], "send_account_daily_report": False, "send_account_weekly_report": False, "report_timezone": "Europe/Warsaw",
            "report_time": "21:00", "account_roi_days": 30}
SCOPES = ("ALL_ACCOUNT", "PMW_ENGINES", "MAGIC_ZERO_UNCLASSIFIED", "EXTERNAL_MAGIC")
# 1.46: PUT /api/v1/telegram/account stored any type / format (report_time "9" -> every report raised, "false" as text was true, a symbol
# list as text matched substrings) - every value is checked now, the stored file on load as well
BOOL_KEYS = ("account_event_enabled", "notify_position_open", "notify_partial_close", "notify_position_close", "notify_position_reversal",
             "send_account_daily_report", "send_account_weekly_report")
LIST_KEYS = ("symbol_allowlist", "symbol_exclude")
REPORT_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# 1.46: display labels of the scope IDs (the IDs - config values / event "source" - stay unchanged)
SOURCE_LABELS = {"PMW_ENGINES": "silniki Apollo23", "MAGIC_ZERO_UNCLASSIFIED": "ręczne / bez magic", "EXTERNAL_MAGIC": "inny EA"}
TEMPLATE_FIELDS = {"open": ("account", "symbol", "side", "volume", "price", "position", "time", "source"),
                   "partial": ("account", "symbol", "side", "volume", "price", "position", "time", "remaining", "source"),
                   "close": ("account", "symbol", "side", "volume", "price", "position", "time", "net_pnl", "source"),
                   "exit": ("account", "symbol", "side", "volume", "price", "position", "time", "source"),
                   "reversal": ("account", "symbol", "side", "volume", "price", "position", "time", "source"),
                   "report": ("account", "period", "roi", "roi_status", "deals", "net", "currency")}
DEFAULT_TEMPLATES = {"open": "🟢 OPEN ${symbol} ${side} ${volume} @ ${price} · poz. ${position} · ${account} (${source})",
                     "partial": "🟡 CZĘŚCIOWE ZAMKNIĘCIE ${symbol} ${volume} @ ${price} · zostało ${remaining} · poz. ${position}",
                     "close": "🔴 CLOSE ${symbol} ${side} ${volume} @ ${price} · wynik netto ${net_pnl} · poz. ${position}",
                     "exit": "🟠 WYJŚCIE ${symbol} ${side} ${volume} @ ${price} · pozostały wolumen nieznany (wejście sprzed historii) · poz. ${position}",
                     "reversal": "🔁 ODWRÓCENIE ${symbol} → ${side} ${volume} @ ${price} · poz. ${position}",
                     "report": "📊 Raport ${period} · ${account}\nROI rachunku: ${roi} (${roi_status}) · transakcje: ${deals} · wynik: ${net} ${currency}"}


class CenterError(ValueError):
    pass


def invalid_value(key: str, v) -> str | None:
    """1.46: error text for a wrong type / format of a config value, None when it is valid (unknown keys are not judged here)."""
    if key in BOOL_KEYS:
        return None if isinstance(v, bool) else f"{key}: true | false"
    if key in LIST_KEYS:
        return None if isinstance(v, list) and all(isinstance(x, str) for x in v) else f"{key}: lista symboli (tekst), np. [\"XAUUSD\"]"
    if key == "bound_account_key":
        return None if v is None or (isinstance(v, str) and v) else "bound_account_key: server:login albo null"
    if key == "account_event_scope":
        return None if v in SCOPES else f"account_event_scope: {SCOPES}"
    if key == "report_time":
        return None if isinstance(v, str) and REPORT_TIME.fullmatch(v) else "report_time: HH:MM (00:00-23:59)"
    if key == "report_timezone":
        if not isinstance(v, str):
            return "report_timezone: strefa IANA"
        try:
            ZoneInfo(v)
        except Exception:  # noqa: BLE001
            return "report_timezone: strefa IANA"
    if key == "account_roi_days":
        return None if not isinstance(v, bool) and v in (1, 7, 30, 90) else "account_roi_days: 1 | 7 | 30 | 90"
    return None


def validate_template(kind: str, text: str) -> str:
    if kind not in TEMPLATE_FIELDS:
        raise CenterError(f"UNKNOWN_TEMPLATE: {kind}")
    if not (1 <= len(text) <= 1000):
        raise CenterError("TEMPLATE_LENGTH: 1-1000")
    names = {m.group("named") or m.group("braced") for m in string.Template.pattern.finditer(text) if m.group("named") or m.group("braced")}
    bad = sorted(n for n in names if n not in TEMPLATE_FIELDS[kind])
    if bad or any(m.group("invalid") is not None for m in string.Template.pattern.finditer(text)):
        raise CenterError(f"TEMPLATE_FIELDS: dozwolone {TEMPLATE_FIELDS[kind]}, błędne {bad}")
    return text


class AccountCenter:
    def __init__(self, data_dir: Path, deliver=None, deals_fn=None, account_fn=None, pmw_magics=(), roi_fn=None, clock=time.time):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.deliver = deliver or (lambda key, text: False)      # (dedup_key, text) -> bool (TelegramNotifier outbound)
        self.deals_fn = deals_fn or (lambda: [])
        self.account_fn = account_fn or (lambda: None)
        self.pmw_magics = set(pmw_magics)
        self.roi_fn = roi_fn
        self.clock = clock
        self._lock = threading.RLock()
        raw = self._read("telegram_account.json")
        self.cfg = {**DEFAULTS, **(raw if isinstance(raw, dict) else {})}
        # 1.46: a wrong stored value (written by the unvalidated 1.45 API) is replaced by its safe default (all OFF) and reported in
        # status()["config_invalid"] instead of breaking every report / enabling events through the text "false"
        self.cfg_invalid = sorted(k for k in DEFAULTS if invalid_value(k, self.cfg[k]))
        for k in self.cfg_invalid:
            self.cfg[k] = list(DEFAULTS[k]) if isinstance(DEFAULTS[k], list) else DEFAULTS[k]
        self.state = {"cursor": [], "positions": {}, "outbox": [], "sent_keys": [], "baseline_at": None, "paused": None,
                      **self._read("telegram_account_state.json")}
        pos = self.state.get("positions")
        for p in (pos.values() if isinstance(pos, dict) else ()):   # 1.46: 1.45 stored vin 0.0 for a position whose entry was never seen
            if isinstance(p, dict):
                p.setdefault("vin_known", bool(p.get("vin")))
        self.templates = {**DEFAULT_TEMPLATES, **self._read("account_templates.json")}

    # ------------------------------------------------------------ persistence
    def _read(self, name):
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, name, obj):
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.dir / name)

    def _save(self):
        self.state["sent_keys"] = self.state["sent_keys"][-5000:]
        self.state["cursor"] = self.state["cursor"][-20000:]
        self._write("telegram_account_state.json", self.state)

    # ------------------------------------------------------------ config
    def account_key(self) -> str | None:
        a = self.account_fn() or {}
        return f"{a.get('server')}:{a.get('login')}" if a.get("server") and a.get("login") else None

    def bind(self, account_key: str) -> dict:
        """Explicit pin of the CURRENT account only; writes a baseline (existing deals = seen, no replay)."""
        cur = self.account_key()
        if not cur or account_key != cur:
            raise CenterError("ACCOUNT_MISMATCH: można przypiąć tylko aktualnie połączony rachunek (server:login)")
        with self._lock:
            deals = self._loaded_deals()
            self.cfg["bound_account_key"] = account_key
            self._write("telegram_account.json", self.cfg)
            self._baseline(deals)
        return self.status()

    def unbind(self) -> dict:
        with self._lock:
            self.cfg["bound_account_key"] = None
            self.cfg["account_event_enabled"] = False
            self._write("telegram_account.json", self.cfg)
        return self.status()

    def update(self, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise CenterError("BODY: obiekt JSON")
        bad = [k for k in patch if k not in DEFAULTS or k == "bound_account_key"]
        if bad:
            raise CenterError(f"KEYS_NOT_ALLOWED: {bad}")
        errors = [e for e in (invalid_value(k, v) for k, v in patch.items()) if e]     # 1.46: type + format of every value
        if errors:
            raise CenterError("; ".join(errors))
        with self._lock:
            # 1.46: the patch is applied to a copy - a refused patch (ACCOUNT_NOT_BOUND / DEALS_NOT_LOADED) left its other keys changed
            new = {**self.cfg, **patch}
            if new["account_event_enabled"] and not new["bound_account_key"]:
                raise CenterError("ACCOUNT_NOT_BOUND: najpierw przypnij rachunek")
            deals = self._loaded_deals() if new["account_event_enabled"] and not self.cfg["account_event_enabled"] else None
            self.cfg.update(new)
            self.cfg_invalid = [k for k in self.cfg_invalid if k not in patch]
            self._write("telegram_account.json", self.cfg)
            if deals is not None:
                self._baseline(deals)
        return self.status()

    def set_template(self, kind: str, text: str | None) -> dict:
        with self._lock:
            if text is None:
                self.templates[kind] = DEFAULT_TEMPLATES[kind]
            else:
                self.templates[kind] = validate_template(kind, text)
            self._write("account_templates.json", {k: v for k, v in self.templates.items() if v != DEFAULT_TEMPLATES.get(k)})
        return {"templates": self.templates}

    def _loaded_deals(self) -> list[dict]:
        """1.46: deals_fn() returns None while the deal history of the CURRENT account is not loaded (before the first history poll,
        or still the previous account's list after a switch). An empty list taken as the baseline replayed the whole history later."""
        deals = self.deals_fn()
        if deals is None:
            raise CenterError("DEALS_NOT_LOADED: historia transakcji tego rachunku nie jest jeszcze wczytana z MT5 - spróbuj za chwilę")
        return list(deals)

    def _baseline(self, deals: list[dict]):
        self.state["cursor"] = sorted({str(d.get("ticket")) for d in deals})
        # 1.46: positions still open at the baseline are rebuilt from the deals already in the history window (entry volume known);
        # a reset to {} took their entry volume as 0 - the first partial close was a CLOSE with a negative remaining volume
        pos: dict = {}
        for d in sorted(deals, key=lambda x: (x.get("time") or 0, x.get("ticket") or 0)):
            if d.get("type") in (0, 1):
                self._apply(pos, d)
        self.state["positions"] = {pid: p for pid, p in pos.items() if not p["vin_known"] or p["vin"] - p["vout"] > 1e-9}
        self.state["baseline_at"] = self.clock()
        self._save()

    # ------------------------------------------------------------ events
    def _source(self, magic) -> str:
        m = int(magic or 0)
        return "PMW_ENGINES" if m in self.pmw_magics else ("MAGIC_ZERO_UNCLASSIFIED" if m == 0 else "EXTERNAL_MAGIC")

    def _in_scope(self, d: dict) -> bool:
        sc = self.cfg["account_event_scope"]
        src = self._source(d.get("magic"))
        if sc != "ALL_ACCOUNT" and src != sc:
            return False
        sym = d.get("symbol")
        if self.cfg["symbol_allowlist"] and sym not in self.cfg["symbol_allowlist"]:
            return False
        return sym not in self.cfg["symbol_exclude"]

    def _apply(self, positions: dict, d: dict) -> tuple[str, dict, str | None]:
        """One trade deal applied to the volume state of its position -> (position id, state, event kind or None).
        1.46: vin_known False = entry volume unknown (position opened before the deals seen here): its exits are "exit" events with
        remaining / net None - never a CLOSE computed from an entry volume taken as 0. A reversal (INOUT) closes the remaining volume
        and opens the rest in the opposite direction (the volume before the reversal made the final close a PARTIAL). vin / net stay
        numbers in the file (additive "vin_known" key - a state file written here still loads in 1.45)."""
        t = str(d.get("ticket"))
        pid = str(d.get("position_id") or t)
        vol = float(d.get("volume") or 0)
        entry = d.get("entry")
        side = "BUY" if d.get("type") == 0 else "SELL"
        p = positions.get(pid)
        first = p is None
        if first:
            p = positions[pid] = {"vin": 0.0, "vout": 0.0, "net": 0.0, "side": None, "vin_known": entry == 0}
        p["net"] += float(d.get("profit") or 0) + float(d.get("commission") or 0) + float(d.get("swap") or 0) + float(d.get("fee") or 0)
        if entry == 0:
            kind = "open" if first else None
            p["vin"] += vol
            p["side"] = p["side"] or side
        elif entry == 2:
            kind = "reversal"
            rest = vol - (p["vin"] - p["vout"])
            p["vin_known"] = p["vin_known"] and rest > 1e-9
            p["vin"], p["vout"] = (rest if p["vin_known"] else 0.0), 0.0
            p["side"] = side
        else:
            p["vout"] += vol
            p["side"] = p["side"] or ("SELL" if side == "BUY" else "BUY")     # an OUT deal is opposite to its position (MT5)
            kind = "exit" if not p["vin_known"] else ("close" if p["vout"] >= p["vin"] - 1e-9 else "partial")
        return pid, p, kind

    def _pause(self, reason: str) -> list:
        if self.state.get("paused") != reason:          # 1.46: written once, not every 10 s
            self.state["paused"] = reason
            self._save()
        return []

    def poll(self) -> list[dict]:
        """Turns NEW deals of the bound account into events; queues messages in the outbox; never sends pending orders (deals only)."""
        with self._lock:
            if not self.cfg["account_event_enabled"] or not self.cfg["bound_account_key"]:
                return []
            if self.account_key() != self.cfg["bound_account_key"]:
                return self._pause("ACCOUNT_MISMATCH")
            deals = self.deals_fn()
            if deals is None:                               # 1.46: history of this account not loaded yet -> wait, never "no deals"
                return self._pause("DEALS_NOT_LOADED")
            dirty = self.state["paused"] is not None
            self.state["paused"] = None
            seen = set(self.state["cursor"])
            n_seen = len(seen)
            events = []
            for d in sorted(deals, key=lambda x: (x.get("time") or 0, x.get("ticket") or 0)):
                t = str(d.get("ticket"))
                if t in seen or d.get("type") not in (0, 1):
                    seen.add(t)
                    continue
                seen.add(t)
                pid, p, kind = self._apply(self.state["positions"], d)
                if kind is None or not self._in_scope(d):
                    continue
                flag = {"open": "notify_position_open", "partial": "notify_partial_close", "close": "notify_position_close",
                        "reversal": "notify_position_reversal"}.get(kind)
                enabled = self.cfg[flag] if flag else (self.cfg["notify_partial_close"] or self.cfg["notify_position_close"])   # exit
                ev = {"kind": kind, "key": f"acct:{self.cfg['bound_account_key']}:{pid}:{t}:{kind}", "position": pid, "ticket": t,
                      "symbol": d.get("symbol"), "side": p["side"], "volume": float(d.get("volume") or 0), "price": d.get("price"),
                      "time": d.get("time"), "remaining": round(p["vin"] - p["vout"], 8) if p["vin_known"] else None,
                      "net_pnl": round(p["net"], 2) if kind == "close" else None,
                      "source": self._source(d.get("magic")), "enabled": bool(enabled)}
                events.append(ev)
                if ev["enabled"]:
                    self.state["outbox"].append({"key": ev["key"], "text": self.render(kind, ev)})
            if len(seen) != n_seen or dirty:                # 1.46: state written only when something changed (was: every 10 s)
                self.state["cursor"] = sorted(seen)
                self._save()
            return events

    def render(self, kind: str, ev: dict) -> str:
        vals = {k: ("—" if ev.get(k) is None else ev.get(k)) for k in TEMPLATE_FIELDS[kind]}
        vals["account"] = self.cfg["bound_account_key"]
        if "source" in vals:
            vals["source"] = SOURCE_LABELS.get(vals["source"], vals["source"])     # 1.46: display label, not the raw scope ID
        return string.Template(self.templates[kind]).safe_substitute(vals)

    def flush(self) -> int:
        with self._lock:
            if not self.state["outbox"]:
                return 0                                   # 1.46: nothing queued -> no state write every 10 s
            sent = 0
            keep = []
            done = set(self.state["sent_keys"])
            for m in self.state["outbox"]:
                if m["key"] in done:
                    continue
                if self.deliver(m["key"], m["text"]):
                    done.add(m["key"])
                    self.state["sent_keys"].append(m["key"])
                    sent += 1
                else:
                    keep.append(m)
            self.state["outbox"] = keep[-500:]
            self._save()
            return sent

    def report_due(self, now: float | None = None) -> list[str]:
        now = self.clock() if now is None else now
        tz = ZoneInfo(self.cfg["report_timezone"])
        loc = datetime.fromtimestamp(now, tz)
        hh, mm = (int(x) for x in self.cfg["report_time"].split(":"))
        if (loc.hour, loc.minute) < (hh, mm) or not self.cfg["bound_account_key"]:
            return []
        out = []
        if self.cfg["send_account_daily_report"]:
            out.append(f"report:daily:{self.cfg['bound_account_key']}:{loc.date().isoformat()}")
        if self.cfg["send_account_weekly_report"] and loc.isoweekday() == 7:
            y, w, _ = loc.isocalendar()
            out.append(f"report:weekly:{self.cfg['bound_account_key']}:{y}-W{w:02d}")
        return [k for k in out if k not in set(self.state["sent_keys"])]

    def queue_reports(self, now: float | None = None) -> int:
        keys = self.report_due(now)
        if not keys:
            return 0                                       # 1.46: no due report -> no state write
        queued = {m["key"] for m in self.state["outbox"]}
        keys = [k for k in keys if k not in queued]         # 1.46: a report already waiting in the outbox is not queued again every 10 s
        for k in keys:
            roi = self.roi_fn(self.cfg["account_roi_days"]) if self.roi_fn else {"status": "NO_DATA"}
            ev = {"period": k.split(":")[1], "roi": roi.get("roi_pct") if roi.get("roi_pct") is not None else "—", "roi_status": roi.get("status", "NO_DATA"),
                  "deals": roi.get("deals", "—"), "net": roi.get("net", "—"), "currency": roi.get("currency") or ""}
            self.state["outbox"].append({"key": k, "text": self.render("report", ev)})
        self._save()
        return len(keys)

    def status(self) -> dict:
        tok = None
        return {"config": self.cfg, "current_account": self.account_key(), "paused": self.state.get("paused"),
                "baseline_at": self.state.get("baseline_at"), "outbox": len(self.state["outbox"]), "cursor_size": len(self.state["cursor"]),
                "templates": self.templates, "token": tok, "channel": "OUTBOUND_ONLY (sendMessage)", "config_invalid": list(self.cfg_invalid),
                "roi_note": "ROI rachunku = cały rachunek (Modified Dietz), osobno od statystyk strategii Apollo23"}   # 1.46: brand
