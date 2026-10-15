"""Hedge controller - bounded risk overlay of an EXISTING base position (SHADOW only in this release).

Not a second scalp signal; no martingale, no grid, no adding to the base, no hedge-on-hedge, no growing the hedge.
Actions: HOLD, REDUCE, CLOSE, HEDGE_PARTIAL.
  * NETTING account (ACCOUNT_MARGIN_MODE = RETAIL_NETTING / EXCHANGE): an opposite order reduces / reverses the single
    position - there are no two legs; HEDGE_PARTIAL is replaced by the equivalent partial close (REDUCE).
  * HEDGING: at most ONE opposite hedge per cycle, volume <= max_fraction x CURRENT base, floored to the lot step;
    if the minimum lot would exceed the limit the hedge is not allowed (never rounded up).
  * HEDGE_PARTIAL is considered only when: base setup still valid, closed M1 show transient adverse risk, a calibrated
    and validated policy model shows net benefit vs REDUCE/CLOSE/HOLD (none exists -> SHADOW/REDUCE), and the combined
    cycle risk fits the SAME budget (no extra loss budget for the hedge).
  * Hedge TTL: 3 closed M1 from fill and never past the base exit; exit earlier on 2 consecutive closes in the base
    direction with the zone edge reclaimed, or basket close. After the hedge is removed no second one in that cycle.
  * Orphan leg: if one leg's SL fills, exposure is recomputed immediately and the remaining leg keeps its own server SL.
  * Order timeout: reconcile orders / deals / positions with the broker first - never resend blindly.
"""
from __future__ import annotations

import math

from .strategy import V

NETTING_MODES = {0, 1, "RETAIL_NETTING", "EXCHANGE", "NETTING"}       # MT5: 0 = RETAIL_NETTING, 1 = EXCHANGE, 2 = RETAIL_HEDGING


def margin_mode_name(mode) -> str:
    if mode is None:
        return "UNKNOWN"
    return "NETTING" if mode in NETTING_MODES else "HEDGING" if mode in (2, "RETAIL_HEDGING", "HEDGING") else "UNKNOWN"


def hedge_volume(base_lots: float, prof: dict, vmin: float, vstep: float) -> dict:
    cap = base_lots * V(prof, "hedge", "max_fraction_of_base")
    lots = math.floor(cap / vstep + 1e-9) * vstep
    if lots < vmin:
        return {"ok": False, "lots": 0.0, "cap": cap, "reason": f"minimalny lot {vmin} > limit {cap:.4f} (50% base) – hedge niedozwolony"}
    return {"ok": True, "lots": round(lots, 8), "cap": cap}


class HedgeController:
    """Pure decision logic; the caller supplies state. Execution is never performed here (SHADOW)."""

    def __init__(self, prof: dict):
        self.p = prof

    def decide(self, *, margin_mode, base: dict, setup_valid: bool, adverse_signal: dict | None, policy_model: dict | None,
               hedges_used: int, budget_ok: bool, vmin: float, vstep: float) -> dict:
        mm = margin_mode_name(margin_mode)
        out = {"margin_mode": mm, "policy": self.p["hedge"]["policy"], "execution": False, "reasons": []}
        if not setup_valid:
            return dict(out, action="CLOSE", reasons=["setup bazowy zanegowany – planowe wyjście, bez odwlekania straty hedge'em"])
        if not adverse_signal:
            return dict(out, action="HOLD", reasons=["brak sygnału przejściowego ryzyka na zamkniętych M1"])
        if mm == "NETTING":
            return dict(out, action="REDUCE", reasons=["rachunek NETTING – przeciwne zlecenie redukuje pozycję; częściowe zamknięcie zamiast hedge"])
        if mm == "UNKNOWN":
            return dict(out, action="REDUCE", reasons=["tryb marży nieznany – hedge zablokowany"])
        if hedges_used >= V(self.p, "hedge", "max_hedges_per_cycle"):
            return dict(out, action="REDUCE", reasons=["limit 1 hedge na cykl wykorzystany – brak hedge na hedge"])
        if not budget_ok:
            return dict(out, action="REDUCE", reasons=["brak rezerwy w budżecie cyklu – hedge nie dostaje dodatkowego budżetu"])
        hv = hedge_volume(base["lots"], self.p, vmin, vstep)
        if not hv["ok"]:
            return dict(out, action="REDUCE", reasons=[hv["reason"]])
        if not policy_model or policy_model.get("status") != "VALIDATED" or (policy_model.get("hedge_minus_reduce_r") or 0) <= policy_model.get("threshold_r", 0):
            return dict(out, action="REDUCE", hypothetical_hedge_lots=hv["lots"],
                        reasons=["brak zwalidowanej polityki pokazującej korzyść HEDGE_PARTIAL względem REDUCE po kosztach – SHADOW/REDUCE"])
        return dict(out, action="HEDGE_PARTIAL", lots=hv["lots"], reasons=["polityka zwalidowana – tylko SHADOW (HEDGE_EXECUTION=false)"])

    def hedge_exit(self, *, bars_since_fill: int, consecutive_base_dir_closes: int, edge_reclaimed: bool, base_open: bool) -> str | None:
        if not base_open:
            return "BASKET_CLOSE"
        if bars_since_fill >= V(self.p, "hedge", "ttl_m1"):
            return "TTL"
        if consecutive_base_dir_closes >= V(self.p, "hedge", "exit_confirm_m1") and edge_reclaimed:
            return "BASE_DIRECTION_CONFIRMED"
        return None

    @staticmethod
    def on_leg_stopped(legs: list[dict], stopped_ticket: int) -> dict:
        """One leg hit its server SL: recompute exposure; the remaining leg keeps its own SL (orphan handling)."""
        rest = [l for l in legs if l["ticket"] != stopped_ticket]
        net = sum(l["lots"] * (1 if l["side"] == "BUY" else -1) for l in rest)
        gross = sum(l["lots"] for l in rest)
        action = "NONE"
        for l in rest:
            if l.get("role") == "HEDGE":
                action = "CLOSE_ORPHAN_HEDGE"                      # base gone: a lone hedge is a new directional bet -> close it
            elif l.get("sl") is None:
                action = "SET_PROTECTION_OR_CLOSE"
        return {"remaining": rest, "net_lots": net, "gross_lots": gross, "action": action}

    @staticmethod
    def on_timeout(journal_key: str, broker_orders: list[dict], broker_positions: list[dict]) -> dict:
        """After an order timeout: look for our idempotency key at the broker; never resend before reconciliation."""
        found = [x for x in broker_orders + broker_positions if x.get("comment") == journal_key or x.get("key") == journal_key]
        return {"action": "ADOPT_EXISTING" if found else "RECONCILE_AGAIN_THEN_DECIDE", "found": found, "resend": False}


def basket(legs: list[dict], marks: dict, costs: dict) -> dict:
    """Combined cycle P&L (realized + mark-to-close of open legs - commissions), gross and net lots."""
    realized = sum(l.get("realized", 0.0) for l in legs)
    mtm = 0.0
    for l in legs:
        if l.get("open", True):
            s = 1 if l["side"] == "BUY" else -1
            mtm += s * (marks[l["side"]] - l["price"]) * l["lots"] * costs.get("contract_size", 100.0)
    fees = sum(l.get("commission", 0.0) + l.get("swap", 0.0) for l in legs)
    return {"realized": realized, "mark_to_close": mtm, "fees": fees, "net": realized + mtm - fees,
            "gross_lots": sum(l["lots"] for l in legs if l.get("open", True)),
            "net_lots": sum(l["lots"] * (1 if l["side"] == "BUY" else -1) for l in legs if l.get("open", True))}
