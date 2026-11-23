"""Telegram Control Center - MT5 account bridge (Apollo23 TASK 017).

Reuses TelegramNotifier (token only in SecretStore / DPAPI, outbound sendMessage only - no getUpdates, no webhook, no commands) and the
existing MarketBridge deal list (no second MT5 session). Everything is OFF by default and nothing is sent without an explicitly PINNED
account (exact server:login). On the first enable / bind a BASELINE is written: deals that already exist are marked seen - no history
replay. A persistent cursor + outbox with dedup keys guarantee each event is sent at most once. Account ROI = stats.account_roi
(Modified Dietz, whole account incl. manual / external EAs) - separate from PMW strategy stats. No order method exists here.
"""
from __future__ import annotations

import json
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
TEMPLATE_FIELDS = {"open": ("account", "symbol", "side", "volume", "price", "position", "time", "source"),
                   "partial": ("account", "symbol", "side", "volume", "price", "position", "time", "remaining", "source"),
                   "close": ("account", "symbol", "side", "volume", "price", "position", "time", "net_pnl", "source"),
                   "reversal": ("account", "symbol", "side", "volume", "price", "position", "time", "source"),
                   "report": ("account", "period", "roi", "roi_status", "deals", "net", "currency")}
DEFAULT_TEMPLATES = {"open": "🟢 OPEN ${symbol} ${side} ${volume} @ ${price} · poz. ${position} · ${account} (${source})",
                     "partial": "🟡 CZĘŚCIOWE ZAMKNIĘCIE ${symbol} ${volume} @ ${price} · zostało ${remaining} · poz. ${position}",
                     "close": "🔴 CLOSE ${symbol} ${side} ${volume} @ ${price} · wynik netto ${net_pnl} · poz. ${position}",
                     "reversal": "🔁 ODWRÓCENIE ${symbol} → ${side} ${volume} @ ${price} · poz. ${position}",
                     "report": "📊 Raport ${period} · ${account}\nROI rachunku: ${roi} (${roi_status}) · transakcje: ${deals} · wynik: ${net} ${currency}"}


class CenterError(ValueError):
    pass


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
        self.cfg = {**DEFAULTS, **self._read("telegram_account.json")}
        self.state = {"cursor": [], "positions": {}, "outbox": [], "sent_keys": [], "baseline_at": None, "paused": None,
                      **self._read("telegram_account_state.json")}
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
            self.cfg["bound_account_key"] = account_key
            self._write("telegram_account.json", self.cfg)
            self._baseline()
        return self.status()

    def unbind(self) -> dict:
        with self._lock:
            self.cfg["bound_account_key"] = None
            self.cfg["account_event_enabled"] = False
            self._write("telegram_account.json", self.cfg)
        return self.status()

    def update(self, patch: dict) -> dict:
        bad = [k for k in patch if k not in DEFAULTS or k == "bound_account_key"]
        if bad:
            raise CenterError(f"KEYS_NOT_ALLOWED: {bad}")
        if "account_event_scope" in patch and patch["account_event_scope"] not in SCOPES:
            raise CenterError(f"account_event_scope: {SCOPES}")
        if "report_timezone" in patch:
            try:
                ZoneInfo(str(patch["report_timezone"]))
            except Exception:  # noqa: BLE001
                raise CenterError("report_timezone: strefa IANA") from None
        if "account_roi_days" in patch and patch["account_roi_days"] not in (1, 7, 30, 90):
            raise CenterError("account_roi_days: 1 | 7 | 30 | 90")
        with self._lock:
            was = self.cfg["account_event_enabled"]
            self.cfg.update(patch)
            if self.cfg["account_event_enabled"] and not self.cfg["bound_account_key"]:
                self.cfg["account_event_enabled"] = False
                raise CenterError("ACCOUNT_NOT_BOUND: najpierw przypnij rachunek")
            self._write("telegram_account.json", self.cfg)
            if self.cfg["account_event_enabled"] and not was:
                self._baseline()
        return self.status()

    def set_template(self, kind: str, text: str | None) -> dict:
        with self._lock:
            if text is None:
                self.templates[kind] = DEFAULT_TEMPLATES[kind]
            else:
                self.templates[kind] = validate_template(kind, text)
            self._write("account_templates.json", {k: v for k, v in self.templates.items() if v != DEFAULT_TEMPLATES.get(k)})
        return {"templates": self.templates}

    def _baseline(self):
        self.state["cursor"] = sorted({str(d.get("ticket")) for d in self.deals_fn()})
        self.state["positions"] = {}
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

    def poll(self) -> list[dict]:
        """Turns NEW deals of the bound account into events; queues messages in the outbox; never sends pending orders (deals only)."""
        with self._lock:
            if not self.cfg["account_event_enabled"] or not self.cfg["bound_account_key"]:
                return []
            if self.account_key() != self.cfg["bound_account_key"]:
                self.state["paused"] = "ACCOUNT_MISMATCH"
                self._save()
                return []
            self.state["paused"] = None
            seen = set(self.state["cursor"])
            events = []
            for d in sorted(self.deals_fn(), key=lambda x: (x.get("time") or 0, x.get("ticket") or 0)):
                t = str(d.get("ticket"))
                if t in seen or d.get("type") not in (0, 1):
                    seen.add(t)
                    continue
                seen.add(t)
                pid = str(d.get("position_id") or t)
                p = self.state["positions"].setdefault(pid, {"vin": 0.0, "vout": 0.0, "net": 0.0, "side": None})
                vol = float(d.get("volume") or 0)
                p["net"] += float(d.get("profit") or 0) + float(d.get("commission") or 0) + float(d.get("swap") or 0) + float(d.get("fee") or 0)
                entry = d.get("entry")
                side = "BUY" if d.get("type") == 0 else "SELL"
                if entry == 0:
                    kind = "open" if p["vin"] == 0 else None
                    p["vin"] += vol
                    p["side"] = p["side"] or side
                elif entry == 2:
                    kind = "reversal"
                    p["side"] = side
                else:
                    p["vout"] += vol
                    kind = "close" if p["vout"] >= p["vin"] - 1e-9 else "partial"
                if kind is None or not self._in_scope(d):
                    continue
                flag = {"open": "notify_position_open", "partial": "notify_partial_close", "close": "notify_position_close",
                        "reversal": "notify_position_reversal"}[kind]
                ev = {"kind": kind, "key": f"acct:{self.cfg['bound_account_key']}:{pid}:{t}:{kind}", "position": pid, "ticket": t,
                      "symbol": d.get("symbol"), "side": p["side"] if kind != "reversal" else side, "volume": vol, "price": d.get("price"),
                      "time": d.get("time"), "remaining": round(p["vin"] - p["vout"], 8), "net_pnl": round(p["net"], 2) if kind == "close" else None,
                      "source": self._source(d.get("magic")), "enabled": bool(self.cfg[flag])}
                events.append(ev)
                if ev["enabled"]:
                    self.state["outbox"].append({"key": ev["key"], "text": self.render(kind, ev)})
            self.state["cursor"] = sorted(seen)
            self._save()
            return events

    def render(self, kind: str, ev: dict) -> str:
        vals = {k: ("—" if ev.get(k) is None else ev.get(k)) for k in TEMPLATE_FIELDS[kind]}
        vals["account"] = self.cfg["bound_account_key"]
        return string.Template(self.templates[kind]).safe_substitute(vals)

    def flush(self) -> int:
        with self._lock:
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
                "templates": self.templates, "token": tok, "channel": "OUTBOUND_ONLY (sendMessage)",
                "roi_note": "ROI rachunku = cały rachunek (Modified Dietz), osobno od statystyk strategii PMW"}
