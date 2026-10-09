"""Live setup tracker for S01-S10 (table strategy_setups).

* identity: setup_id = hash(symbol, account, strategy, direction, TF, structure) - refreshes update
  the same row (version + history) instead of creating new signals; first detection time and price
  are kept.
* soft changes are smoothed: a stage DOWNGRADE needs `downgrade_confirm_updates` consecutive updates
  on NEW data; an upgrade (incl. CONFIRMED) is applied immediately - a real trigger is never delayed.
* hard events act immediately: invalidation (closed setup-TF bar beyond the level, or quote touch
  for TOUCH rules), expiry (time/bars), MISSED_ENTRY after the confirmed window, data STALE (flag,
  no new setups while stale), strategy disabled.
* a setup no longer reported by its strategy for `cancel_after_misses` new-data updates is CANCELLED
  (kept in history - publications are never deleted).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..db.database import dumps
from ..timeutil import iso, parse_iso
from .base import STAGES, TF_SECONDS

TERMINAL = ("INVALIDATED", "EXPIRED", "MISSED_ENTRY", "CANCELLED", "ENTERED")
RANK = {s: i for i, s in enumerate(STAGES)}
UTC = timezone.utc


class SetupTracker:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------ queries
    def _row(self, sid: str) -> dict | None:
        r = self.db.one("SELECT * FROM strategy_setups WHERE setup_id=?", (sid,))
        if not r:
            return None
        r["record"] = json.loads(r.pop("record_json"))
        r["history"] = json.loads(r.pop("history_json"))
        return r

    def get(self, sid: str) -> dict | None:
        return self._row(sid)

    def active(self, symbol: str, account_key: str | None) -> list[dict]:
        rows = self.db.query("SELECT setup_id FROM strategy_setups WHERE status='ACTIVE' AND symbol=? AND IFNULL(account_key,'')=IFNULL(?, '')",
                             (symbol, account_key))
        return [self._row(r["setup_id"]) for r in rows]

    def recent(self, limit: int = 50, include_terminal: bool = True) -> list[dict]:
        where = "" if include_terminal else "WHERE status='ACTIVE'"
        rows = self.db.query(f"SELECT setup_id FROM strategy_setups {where} ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [self._row(r["setup_id"]) for r in rows]

    # ------------------------------------------------------------ writes
    def _save(self, r: dict) -> None:
        rec = r["record"]
        self.db.execute("""INSERT INTO strategy_setups(setup_id, account_key, symbol, strategy_id, strategy_version, config_hash, direction, timeframe,
                           structure_key, event_id, stage, status, version, score, first_seen_at, first_price, updated_at, stage_changed_at, data_updates,
                           expires_at, terminal_reason, terminal_at, stale, synthetic, record_json, history_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(setup_id) DO UPDATE SET stage=excluded.stage, status=excluded.status, version=excluded.version, score=excluded.score,
                           updated_at=excluded.updated_at, stage_changed_at=excluded.stage_changed_at, data_updates=excluded.data_updates,
                           expires_at=excluded.expires_at, terminal_reason=excluded.terminal_reason, terminal_at=excluded.terminal_at, stale=excluded.stale,
                           record_json=excluded.record_json, history_json=excluded.history_json""",
                        (r["setup_id"], r["account_key"], r["symbol"], rec["strategy_id"], rec["strategy_version"], rec["config_hash"], rec["direction"],
                         rec["timeframe"], rec["structure_key"], rec["event_id"], r["stage"], r["status"], r["version"], rec["setup_score"],
                         r["first_seen_at"], r["first_price"], r["updated_at"], r["stage_changed_at"], r["data_updates"], r["expires_at"],
                         r.get("terminal_reason"), r.get("terminal_at"), int(r.get("stale") or 0), int(bool(rec.get("synthetic"))),
                         dumps(rec), dumps(r["history"][-60:])))

    def terminate(self, sid: str, status: str, reason: str, now: str) -> dict | None:
        r = self._row(sid)
        if not r or r["status"] in TERMINAL:
            return r
        r.update(status=status, terminal_reason=reason, terminal_at=now, updated_at=now)
        r["history"].append({"at": now, "event": status, "reason": reason})
        self._save(r)
        return r

    # ------------------------------------------------------------ main update
    def update(self, candidates: list[dict], *, view, symbol: str, account_key: str | None, data_ok: bool, new_data: bool,
               now: datetime, cfg, scanned: set[str]) -> list[tuple[str, dict]]:
        """Apply one scan. Returns events [(kind, row)] - NEW_<STAGE>, STAGE_<STAGE>, PLAN_REVISED and terminal kinds."""
        now_s = iso(now)
        events: list[tuple[str, dict]] = []
        active = {r["setup_id"]: r for r in self.active(symbol, account_key)}
        # data stale: flag rows, create nothing, no stage changes (previous setups shown as STALE)
        if not data_ok:
            for r in active.values():
                if not r["stale"]:
                    r["stale"] = 1
                    r["updated_at"] = now_s
                    r["history"].append({"at": now_s, "event": "STALE"})
                    self._save(r)
                    events.append(("STALE", r))
            return events
        seen = set()
        for c in candidates:
            sid = c["setup_id"]
            seen.add(sid)
            r = active.get(sid)
            if r is None:
                old = self._row(sid)
                if old is not None:
                    # a structure that only faded (soft cancel) may come back as a new version;
                    # invalidated/expired/entered structures are never republished
                    if old["status"] == "CANCELLED" and old.get("terminal_reason") in ("CONDITIONS_NO_LONGER_MET", "RESTART_REVALIDATION"):
                        old.update(status="ACTIVE", terminal_reason=None, terminal_at=None, version=old["version"] + 1, updated_at=now_s,
                                   stage=c["stage"], stage_changed_at=now_s, stale=0,
                                   expires_at=iso(now + timedelta(seconds=TF_SECONDS[c["timeframe"]] * max(1, c["expires_bars"]))))
                        old["record"] = {**c, "pending_downgrade": 0, "misses": 0}
                        old["history"].append({"at": now_s, "event": "REACTIVATED", "stage": c["stage"], "score": c["setup_score"]})
                        self._save(old)
                        events.append(("NEW_" + c["stage"], old))
                    continue
                tf_s = TF_SECONDS[c["timeframe"]]
                exp = now + timedelta(seconds=tf_s * max(1, c["expires_bars"]))
                if c["stage"] == "CONFIRMED":
                    exp = now + timedelta(seconds=tf_s * cfg.confirmed_window_bars)
                r = {"setup_id": sid, "account_key": account_key, "symbol": symbol, "stage": c["stage"], "status": "ACTIVE", "version": 1,
                     "first_seen_at": now_s, "first_price": view.mid, "updated_at": now_s, "stage_changed_at": now_s, "data_updates": 1,
                     "expires_at": iso(exp), "stale": 0, "record": {**c, "pending_downgrade": 0, "misses": 0},
                     "history": [{"at": now_s, "event": "NEW", "stage": c["stage"], "score": c["setup_score"], "price": view.mid}]}
                self._save(r)
                events.append(("NEW_" + c["stage"], r))
                continue
            rec = r["record"]
            changed = False
            if r["stale"]:
                r["stale"] = 0
                r["history"].append({"at": now_s, "event": "FRESH_DATA"})
                changed = True
            # plan revision (structural levels moved) -> new version, never silently
            if self._plan_moved(rec, c):
                r["version"] += 1
                r["history"].append({"at": now_s, "event": "PLAN_REVISED", "version": r["version"],
                                     "stop_loss": c["stop_loss"], "invalidation": c["invalidation_level"]})
                events.append(("PLAN_REVISED", r))
                changed = True
            cur, new = RANK[r["stage"]], RANK[c["stage"]]
            pend = rec.get("pending_downgrade", 0)
            if new > cur:
                r["stage"], r["stage_changed_at"], pend = c["stage"], now_s, 0
                r["history"].append({"at": now_s, "event": "STAGE", "stage": c["stage"], "score": c["setup_score"]})
                if c["stage"] == "CONFIRMED":
                    r["expires_at"] = iso(now + timedelta(seconds=TF_SECONDS[c["timeframe"]] * cfg.confirmed_window_bars))
                events.append(("STAGE_" + c["stage"], r))
                changed = True
            elif new < cur and r["stage"] != "CONFIRMED":
                if new_data:
                    pend += 1
                if pend >= cfg.downgrade_confirm_updates:
                    r["stage"], r["stage_changed_at"], pend = c["stage"], now_s, 0
                    r["history"].append({"at": now_s, "event": "STAGE_DOWN", "stage": c["stage"], "score": c["setup_score"]})
                    changed = True
            else:
                pend = 0
            keep = {k: rec.get(k) for k in ("pending_downgrade", "misses")}
            r["record"] = {**c, **keep, "pending_downgrade": pend, "misses": 0, "stage": r["stage"]}
            if new_data:
                r["data_updates"] += 1
            r["updated_at"] = now_s
            if changed or new_data:
                self._save(r)
        # rows not reported this scan
        for sid, r in active.items():
            if sid in seen:
                continue
            rec = r["record"]
            if rec["strategy_id"] not in scanned:
                events.append(("CANCELLED", self.terminate(sid, "CANCELLED", "STRATEGY_SCAN_DISABLED_OR_NO_DATA", now_s)))
                continue
            if new_data and r["stage"] != "CONFIRMED":
                rec["misses"] = rec.get("misses", 0) + 1
                if rec["misses"] >= cfg.cancel_after_misses:
                    events.append(("CANCELLED", self.terminate(sid, "CANCELLED", "CONDITIONS_NO_LONGER_MET", now_s)))
                    continue
                r["updated_at"] = now_s
                self._save(r)
        # hard checks on every active row (immediate, independent of hysteresis)
        for r in self.active(symbol, account_key):
            k = self._hard_check(r, view, now)
            if k:
                st, why = k
                events.append((st, self.terminate(r["setup_id"], st, why, now_s)))
        return events

    @staticmethod
    def _plan_moved(old: dict, new: dict) -> bool:
        def moved(a, b):
            return a is not None and b is not None and abs(a - b) > max(abs(a), 1.0) * 0.0015
        return moved(old.get("stop_loss"), new.get("stop_loss")) or moved(old.get("invalidation_level"), new.get("invalidation_level"))

    @staticmethod
    def _hard_check(r: dict, view, now: datetime) -> tuple[str, str] | None:
        rec = r["record"]
        lvl = rec.get("invalidation_level")
        d = rec["direction"]
        v = view.tfs.get(rec["timeframe"])
        if lvl is not None and v is not None and v.t:
            since = parse_iso(r["first_seen_at"])
            tf_s = TF_SECONDS[rec["timeframe"]]
            for k in range(len(v.t) - 1, max(-1, len(v.t) - 40), -1):
                close_time = parse_iso(v.t[k]) + timedelta(seconds=tf_s)
                if close_time <= since:
                    break
                if (d == "LONG" and v.c[k] < lvl) or (d == "SHORT" and v.c[k] > lvl):
                    return "INVALIDATED", f"CLOSE_BEYOND_{round(lvl, 3)}"
            if rec.get("invalidation_rule") == "TOUCH" and view.bid is not None:
                if (d == "LONG" and view.bid < lvl) or (d == "SHORT" and view.ask > lvl):
                    return "INVALIDATED", f"TOUCH_{round(lvl, 3)}"
        if r.get("expires_at") and parse_iso(r["expires_at"]) <= now:
            return ("MISSED_ENTRY", "CONFIRMED_WINDOW_ELAPSED") if r["stage"] == "CONFIRMED" else ("EXPIRED", "TTL_ELAPSED")
        return None

    def mark_entered(self, sid: str, reason: str, now: str) -> dict | None:
        return self.terminate(sid, "ENTERED", reason, now)

    def cancel_all(self, symbol: str, account_key: str | None, reason: str, now: str) -> int:
        n = 0
        for r in self.active(symbol, account_key):
            self.terminate(r["setup_id"], "CANCELLED", reason, now)
            n += 1
        return n


def public(r: dict | None) -> dict | None:
    """Row -> compact dict for API/monitor (record fields flattened)."""
    if not r:
        return None
    rec = r["record"]
    return {**{k: rec.get(k) for k in ("strategy_id", "strategy_name", "strategy_version", "config_hash", "event_id", "direction", "timeframe",
                                       "horizon", "family", "regime", "phase", "setup_score", "score", "strategy_fit_score", "entry_plan",
                                       "invalidation_level", "invalidation_rule", "stop_loss", "targets", "exit_rules", "reason_codes",
                                       "missing_confirmations", "countertrend", "facts", "validation_status", "source_time", "forming_bar_used",
                                       "synthetic", "anchor_time")},
            "setup_id": r["setup_id"], "stage": r["stage"], "status": r["status"], "version": r["version"], "first_seen_at": r["first_seen_at"],
            "first_price": r["first_price"], "updated_at": r["updated_at"], "stage_changed_at": r["stage_changed_at"], "expires_at": r["expires_at"],
            "terminal_reason": r.get("terminal_reason"), "terminal_at": r.get("terminal_at"), "stale": bool(r.get("stale")),
            "data_updates": r["data_updates"], "history": r["history"][-12:]}
