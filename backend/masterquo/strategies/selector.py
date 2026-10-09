"""StrategyAutoSelector (MQ-AUTO-SELECT-1.0.0) - picks the main strategy/setup for NEW opportunities.

rank_score (0-100+, deterministic, documented):
    rank = 0.35 x strategy_fit_score + 0.65 x setup_score + stage_bonus - countertrend_penalty
    strategy_fit_score = regime_fit[regime] x 100 (registry table; how well the method's hypothesis
                         matches the CURRENT regime) ; setup_score = ACTIVE 0-100 score of the setup
    stage_bonus WATCH 0 / EARLY 4 / CONFIRMED 8 ; countertrend_penalty 5
Both inputs are on the same 0-100 scale; neither is a probability of profit. Past results do NOT
enter the rank (no verified out-of-sample history exists yet - documented rule, not an omission).

* signals sharing an event_id (same breakout/level/move) are grouped; only the best one is ranked,
  the others are listed as `grouped_with` (no double counting, no duplicate orders)
* LONG vs SHORT in the same horizon with rank difference < conflict_margin -> CONFLICT, no selection
* hysteresis: a challenger replaces the current selection only if it leads by >= min_switch_margin
  on `switch_confirm_updates` consecutive updates with NEW data and the current selection is older
  than min_selection_hold_seconds. Invalid/expired/stale/disabled selections are dropped immediately.
* MANUAL: only the chosen strategy is considered; a regime mismatch is reported, never hidden.
Changing the selection never touches open positions (they keep their strategy and rules).
"""
from __future__ import annotations

from datetime import datetime

from ..db.database import dumps
from ..timeutil import iso, parse_iso
from .registry import STRATEGIES

VERSION = "MQ-AUTO-SELECT-1.0.0"
STAGE_BONUS = {"WATCH": 0.0, "EARLY": 4.0, "CONFIRMED": 8.0}


def rank_score(c: dict) -> float:
    return round(0.35 * (c.get("strategy_fit_score") or 0) + 0.65 * (c.get("setup_score") or 0) + STAGE_BONUS.get(c["stage"], 0)
                 - (5.0 if c.get("countertrend") else 0.0), 2)


class StrategyAutoSelector:
    def __init__(self, db):
        self.db = db
        self.selected: dict | None = None        # {"setup_id", "strategy_id", "at", "rank"}
        self.challenger: dict | None = None      # {"setup_id", "count"}
        self.last_change: dict | None = None
        self.state: dict = {"system_state": "STARTING", "selected": None, "ranking": [], "reason_codes": ["NO_SCAN_YET"]}
        row = db.one("SELECT * FROM strategy_selection_log ORDER BY id DESC LIMIT 1")
        if row:
            # history is restored; the previous recommendation is NOT treated as valid after restart
            self.last_change = {k: row[k] for k in ("at", "previous_strategy", "selected_strategy", "reason")}

    def _log(self, *, now: str, mode: str, account_key, prev: dict | None, new: dict | None, snapshot_id, reason: str, ranking: list) -> None:
        self.db.execute("""INSERT INTO strategy_selection_log(at, account_key, strategy_mode, previous_strategy, previous_setup, selected_strategy,
                           selected_setup, snapshot_id, reason, ranking_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (now, account_key, mode, (prev or {}).get("strategy_id"), (prev or {}).get("setup_id"), (new or {}).get("strategy_id"),
                         (new or {}).get("setup_id"), snapshot_id, reason, dumps(ranking[:5])))
        self.last_change = {"at": now, "previous_strategy": (prev or {}).get("strategy_id"), "selected_strategy": (new or {}).get("strategy_id"),
                            "reason": reason}

    def reset(self, reason: str) -> None:
        self.selected = None
        self.challenger = None
        self.state = {"system_state": "SCANNING", "selected": None, "ranking": [], "reason_codes": [reason]}

    def select(self, rows: list[dict], *, cfg, regime: dict, data_ok: bool, new_data: bool, now: datetime, snapshot_id: str | None,
               account_key: str | None, per_strategy: dict, ml_bonus=None) -> dict:
        """`ml_bonus(row) -> float` (ml_mode ASSIST only): re-orders candidates by the calibrated model probability;
        the setup score itself is not changed (no double counting)."""
        now_s = iso(now)
        mode = cfg.strategy_mode
        manual = cfg.manual_strategy_id if mode == "MANUAL" else None
        toggles = cfg.strategies
        live = [r for r in rows if r["status"] == "ACTIVE" and not r["stale"]
                and (toggles.get(r["record"]["strategy_id"]) is None or toggles[r["record"]["strategy_id"]].scan)]
        if manual:
            live = [r for r in live if r["record"]["strategy_id"] == manual]
        ranked = []
        for r in live:
            c = r["record"]
            ranked.append({"setup_id": r["setup_id"], "strategy_id": c["strategy_id"], "strategy_name": c.get("strategy_name"),
                           "strategy_version": c.get("strategy_version"), "direction": c["direction"], "timeframe": c["timeframe"],
                           "horizon": c.get("horizon"), "stage": r["stage"], "setup_score": c.get("setup_score"),
                           "strategy_fit_score": c.get("strategy_fit_score"), "countertrend": c.get("countertrend"), "event_id": c.get("event_id"),
                           "rank_score": 0.0, "score_points": (c.get("score") or {}).get("points"), "grouped_with": []})
            ranked[-1]["rank_score"] = rank_score({**c, "stage": r["stage"]})
            if ml_bonus is not None:
                try:
                    b = float(ml_bonus(r) or 0.0)
                except Exception:
                    b = 0.0
                ranked[-1]["ml_rank_adjust"] = b
                ranked[-1]["rank_score"] = round(ranked[-1]["rank_score"] + b, 2)
        ranked.sort(key=lambda x: (-x["rank_score"], x["strategy_id"], x["setup_id"]))
        # group by event_id
        by_event: dict[str, dict] = {}
        grouped = []
        for x in ranked:
            ev = x["event_id"]
            if ev in by_event:
                by_event[ev]["grouped_with"].append(x["strategy_id"] + ":" + x["timeframe"])
                continue
            by_event[ev] = x
            grouped.append(x)
        reasons: list[str] = []
        if not data_ok:
            prev = self.selected
            self.reset("DATA_STALE_OR_UNAVAILABLE")
            if prev:
                self._log(now=now_s, mode=mode, account_key=account_key, prev=prev, new=None, snapshot_id=snapshot_id,
                          reason="DATA_STALE_OR_UNAVAILABLE", ranking=grouped)
            self.state.update(system_state="STALE", ranking=grouped)
            return self._publish(regime, mode, manual, grouped, per_strategy, now_s, snapshot_id, ["DATA_STALE_OR_UNAVAILABLE"])
        best = grouped[0] if grouped else None
        # same-horizon LONG/SHORT conflict
        if best and len(grouped) > 1:
            opp = next((x for x in grouped[1:] if x["direction"] != best["direction"] and x["horizon"] == best["horizon"]), None)
            if opp and best["rank_score"] - opp["rank_score"] < cfg.conflict_margin:
                reasons.append(f"CONFLICT_{best['direction']}_{opp['direction']}_{best['horizon']}_DIFF_{best['rank_score'] - opp['rank_score']:.1f}")
                best = None
        cur = self.selected
        cur_row = next((x for x in grouped if cur and x["setup_id"] == cur["setup_id"]), None)
        new_sel, why = cur, None
        if cur and cur_row is None:
            new_sel = best
            why = "PREVIOUS_SETUP_NO_LONGER_VALID"
            self.challenger = None
        elif cur is None:
            if best:
                new_sel, why = best, "FIRST_SELECTION" if not self.last_change else "NEW_CANDIDATE"
        elif best and best["setup_id"] != cur["setup_id"]:
            lead = best["rank_score"] - cur_row["rank_score"]
            if lead >= cfg.min_switch_margin:
                ch = self.challenger if self.challenger and self.challenger["setup_id"] == best["setup_id"] else {"setup_id": best["setup_id"], "count": 0}
                if new_data:
                    ch["count"] += 1
                self.challenger = ch
                held = (now - parse_iso(cur["at"])).total_seconds()
                if ch["count"] >= cfg.switch_confirm_updates and held >= cfg.min_selection_hold_seconds:
                    new_sel, why = best, f"CHALLENGER_LEADS_BY_{lead:.1f}_FOR_{ch['count']}_UPDATES"
                    self.challenger = None
                else:
                    reasons.append(f"SWITCH_PENDING_{ch['count']}/{cfg.switch_confirm_updates}_HOLD_{int(held)}s")
            else:
                self.challenger = None
        if why is not None and (new_sel or {}).get("setup_id") != (cur or {}).get("setup_id"):
            self._log(now=now_s, mode=mode, account_key=account_key, prev=cur, new=new_sel, snapshot_id=snapshot_id, reason=why, ranking=grouped)
            self.selected = None if new_sel is None else {"setup_id": new_sel["setup_id"], "strategy_id": new_sel["strategy_id"], "at": now_s}
        if self.selected:
            sel = next((x for x in grouped if x["setup_id"] == self.selected["setup_id"]), None)
            if sel is None:
                self.selected = None
        if not self.selected:
            reasons.append("NO_VALID_CANDIDATE" if not grouped else "NO_SELECTION")
        return self._publish(regime, mode, manual, grouped, per_strategy, now_s, snapshot_id, reasons)

    def _publish(self, regime, mode, manual, grouped, per_strategy, now_s, snapshot_id, reasons) -> dict:
        sel = next((x for x in grouped if self.selected and x["setup_id"] == self.selected["setup_id"]), None)
        if sel is None and self.state.get("system_state") == "STALE":
            st = "STALE"
        elif sel is None:
            st = "SCANNING"
        else:
            st = {"WATCH": "WATCHING", "EARLY": "DEVELOPING", "CONFIRMED": "CONFIRMED"}[sel["stage"]]
        alt = None
        if sel and len(grouped) > 1:
            other = next((x for x in grouped if x["setup_id"] != sel["setup_id"]), None)
            if other:
                alt = {**{k: other[k] for k in ("strategy_id", "setup_id", "direction", "stage", "rank_score")},
                       "needs": f"przewaga ≥ {self._margin} pkt rankingu przez kolejne aktualizacje (brakuje {sel['rank_score'] - other['rank_score'] + self._margin:.1f})"}
        manual_fit = None
        if manual and manual in STRATEGIES:
            f = STRATEGIES[manual].regime_fit.get(regime.get("state"), 0.3)
            manual_fit = {"strategy_id": manual, "fit": round(f * 100, 1), "mismatch": f < 0.5}
        self.state = {"engine": VERSION, "strategy_mode": mode, "manual_strategy_id": manual, "manual_fit": manual_fit, "system_state": st,
                      "regime": regime, "selected": sel, "selected_at": (self.selected or {}).get("at"), "candidate_ranking": grouped[:10],
                      "alternative": alt, "reason_codes": reasons, "last_evaluated_at": now_s, "snapshot_id": snapshot_id,
                      "last_change": self.last_change, "per_strategy": per_strategy}
        return self.state

    _margin = 8.0

    def configure(self, cfg) -> None:
        self._margin = cfg.min_switch_margin
