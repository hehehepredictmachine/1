"""M04N integration (unchanged collector in backend/vendor/m04n), run in-process.

Statuses are reported honestly: a missing calendar is UNAVAILABLE, never "no events".
FF/MM actual/forecast strings are third-party text; nothing is inferred (no surprise, no sentiment).
News content is DATA for the agent, never instructions.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import timedelta

from .. import paths
from ..timeutil import iso, parse_iso, utcnow

log = logging.getLogger("masterquo.news")


def _engine():
    p = str(paths.M04N_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)
    import M04N_ENGINE  # noqa: E402
    return M04N_ENGINE


class NewsService:
    def __init__(self, config_store, secrets, bus, applog):
        self.cfg_store = config_store
        self.secrets = secrets
        self.bus = bus
        self.log = applog
        self.report: dict | None = None
        self.last_error: str | None = None
        self.last_run = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._kick = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="m04n-news", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()

    def refresh_now(self) -> None:
        self._kick.set()

    def _loop(self) -> None:
        store = None
        while not self._stop.is_set():
            cfg = self.cfg_store.get().news
            if cfg.enabled:
                try:
                    eng = _engine()
                    mcfg = json.loads((paths.M04N_DIR / "M04N_CONFIG.json").read_text(encoding="utf-8"))
                    fred = self.secrets.get("FRED_API_KEY")
                    if fred:
                        os.environ["FRED_API_KEY"] = fred
                    if store is None:
                        rt = paths.data_dir() / "m04n"
                        rt.mkdir(parents=True, exist_ok=True)
                        store = eng.Store(rt / "M04N_STATE.sqlite")
                    report, _bridge = eng.collect(mcfg, store)
                    self.report = report
                    self.last_error = None
                    self.last_run = utcnow()
                    self.bus.publish("news", self.summary())
                except Exception as exc:  # network, parse, sqlite - status stays honest
                    self.last_error = f"{type(exc).__name__}: {exc}"[:200]
                    self.last_run = utcnow()
                    log.warning("M04N collect failed: %s", self.last_error)
                    self.bus.publish("news", self.summary())
            self._kick.wait(cfg.poll_seconds if cfg.enabled else 30)
            self._kick.clear()

    def macro(self) -> dict:
        cfg = self.cfg_store.get().news
        if not cfg.enabled:
            return {"status": "DISABLED", "risk_level": "UNKNOWN", "events": []}
        r = self.report
        if not r:
            return {"status": "NOT_LOADED" if not self.last_error else "UNAVAILABLE", "risk_level": "UNKNOWN",
                    "events": [], "error": self.last_error}
        age = (utcnow() - parse_iso(r["as_of"])).total_seconds()
        cal = r.get("calendar") or {}
        st = cal.get("status")
        status = "PARTIAL" if st in ("PARTIAL", "PARTIAL_NO_EVENTS") else "UNAVAILABLE"
        if age > max(2 * cfg.poll_seconds, 900):
            status = "STALE"
        risk = cal.get("risk") or {}
        return {"status": status, "calendar_status": st, "risk_level": risk.get("level", "UNKNOWN"),
                "active_events": risk.get("events", []), "as_of": r["as_of"], "coverage": cal.get("coverage"),
                "note": "Kalendarz częściowy (BLS + Forex Factory/Metals Mine tygodniowo). Brak wpisu ≠ brak wydarzenia."}

    def summary(self) -> dict:
        r = self.report or {}
        now = utcnow()
        cal = (r.get("calendar") or {})
        events = []
        for e in cal.get("events", [])[:150]:
            at = parse_iso(e["scheduled_at"]) if e.get("scheduled_at") else None
            if at and now - timedelta(hours=12) <= at <= now + timedelta(days=3):
                events.append({k: e.get(k) for k in ("event_id", "name", "impact", "scheduled_at", "currency", "actual", "forecast",
                                                    "previous", "provider_sources", "event_time_quality", "available_at")})
        news = [{k: n.get(k) for k in ("event_id", "headline", "source_id", "authority", "published_at", "first_seen_at", "impact",
                                      "categories", "url", "time_quality")} for n in ((r.get("news") or {}).get("recent") or [])[:40]]
        integ = r.get("integrity") or {}
        return {"enabled": self.cfg_store.get().news.enabled, "status": r.get("status") or ("ERROR" if self.last_error else "NOT_LOADED"),
                "as_of": r.get("as_of"), "last_run": iso(self.last_run), "error": self.last_error, "macro": self.macro(),
                "calendar": events, "news": news, "failed_sources": integ.get("failed_or_stale_sources", []),
                "source_health": integ.get("source_health", {}),
                "sentiment": {"status": "NOT_AVAILABLE", "note": "Brak zweryfikowanego źródła sentymentu – nie jest wyliczany ani zgadywany."},
                "risk_advisory": (r.get("interpretation") or {}).get("risk_advisory")}
