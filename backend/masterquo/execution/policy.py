"""One exit policy for every path (MQ-EXIT-POLICY-1.0.0): live MT5, PAPER, ML labels and replay.

The policy is built ONCE from the setup plan (targets with their weights, exit_rules) when a position is opened (or a sample
is created) and stored with it. Settings changed later (tp1 weight, BE switch, strategy choice, recalculated walls) never
alter an open position - they only affect future plans.

  targets          all targets of the plan, nearest first, weights normalised to 1.0 (the last one closes the rest)
  be_after_tp1     from the setup's exit_rules; if the plan does not say, the configured default AT OPEN is frozen
  time_exit        exit_rules.time_exit_bars x setup TF -> minutes; None = the plan has NO time exit (S11) - never an
                   invented default
  tp_rule          STRUCTURAL (prices from the plan) or RR_FROM_FILL (final target = fill +- rr x (fill - SL))
  trailing         recorded as declared by the strategy; trailing rules that need strategy state (e.g. KAMA_STATE_FLIP)
                   are NOT executed by any path (live, PAPER, labels and replay agree) - flagged trailing_executed=False
Moving SL to the entry price after TP1 does not mean a zero net result: commission and swap are still paid.
"""
from __future__ import annotations

VERSION = "MQ-EXIT-POLICY-1.0.0"
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "H8": 480, "D1": 1440}


def from_plan(*, side: str, stop_loss: float, targets: list[dict], exit_rules: dict | None, timeframe: str | None,
              tp1_weight_default: float = 0.5, be_default: bool = True, entry: float | None = None, source: str = "SETUP_PLAN") -> dict:
    """side LONG/SHORT. Targets keep the plan's weights (renormalised); two targets without weights get the configured split."""
    ex = dict(exit_rules or {})
    s = 1 if side == "LONG" else -1
    tg = [{"price": float(t["price"]), "weight": float(t["weight"]) if t.get("weight") is not None else None}
          for t in (targets or []) if t.get("price") is not None]
    tg.sort(key=lambda t: s * t["price"])
    if tg and any(t["weight"] is None for t in tg):
        if len(tg) == 2:
            tg[0]["weight"], tg[1]["weight"] = tp1_weight_default, 1 - tp1_weight_default
        else:
            for t in tg:
                t["weight"] = 1.0 / len(tg)
    tot = sum(t["weight"] for t in tg) or 1.0
    for t in tg:
        t["weight"] = round(t["weight"] / tot, 6)
    teb = ex.get("time_exit_bars") if "time_exit_bars" in ex else None
    tf_min = TF_MINUTES.get(timeframe or "", None)
    time_exit = int(teb) * tf_min if (teb is not None and tf_min) else None
    be = ex.get("be_after_tp1")
    trailing = ex.get("trailing")
    pol = {"version": VERSION, "source": source, "side": side, "stop_loss": float(stop_loss), "targets": tg,
           "be_after_tp1": bool(be_default if be is None else be), "be_source": "SETUP" if be is not None else "CONFIG_AT_OPEN",
           "time_exit_minutes": time_exit, "time_exit_source": ("SETUP" if teb is not None else ("SETUP_NO_TIME_EXIT" if "time_exit_bars" in ex else "NONE_IN_PLAN")),
           "tp_rule": ex.get("tp_rule") or "STRUCTURAL", "rr": ex.get("rr"), "trailing": trailing,
           "trailing_executed": False if trailing else None, "timeframe": timeframe,
           "session_end_utc": ex.get("session_end_utc")}
    if entry is not None:
        pol = rebase_on_fill(pol, entry)
    return pol


def rebase_on_fill(pol: dict, fill: float) -> dict:
    """RR_FROM_FILL: the final target is recomputed from the REAL fill price (the strategy defines TP as rr x risk from the
    entry). Structural plans are unchanged. The fill is recorded in both cases."""
    out = dict(pol, fill_price=float(fill))
    if pol.get("tp_rule") == "RR_FROM_FILL" and pol.get("rr"):
        s = 1 if pol["side"] == "LONG" else -1
        risk = s * (fill - pol["stop_loss"])
        if risk > 0:
            out["targets"] = [{"price": round(fill + s * float(pol["rr"]) * risk, 6), "weight": 1.0}]
            out["tp_rebased_on_fill"] = True
        else:
            out["tp_rebased_on_fill"] = False
            out["note"] = "FILL_BEYOND_STOP"
    return out


def partial_volume(pol: dict, index: int, volume_initial: float, volume_open: float, step: float, vmin: float) -> float:
    """Volume to close at target `index` (0-based, not the last one): weight x initial volume, floored to the broker step.
    0 = skip the partial (too small, or it would close everything - the rest waits for the next target / SL)."""
    from ..risk.engine import floor_to_step
    w = pol["targets"][index]["weight"]
    v = floor_to_step(volume_initial * w, step, vmin)
    if v <= 0 or v >= volume_open - 1e-9:
        return 0.0
    return v


def legacy(*, side_order: str, tp1: float | None, tp2: float | None, sl: float | None, tp1_weight: float, be: bool) -> dict:
    """Positions opened by 1.9.0 (no stored policy): the policy is reconstructed ONCE from the stored levels and the settings
    at the first management tick of 1.10, then frozen (later setting changes no longer apply)."""
    side = "LONG" if side_order == "BUY" else "SHORT"
    tg = []
    if tp1 is not None:
        tg.append({"price": tp1, "weight": tp1_weight})
    if tp2 is not None:
        tg.append({"price": tp2, "weight": (1 - tp1_weight) if tp1 is not None else 1.0})
    return from_plan(side=side, stop_loss=sl or 0.0, targets=tg, exit_rules={"be_after_tp1": be}, timeframe=None,
                     tp1_weight_default=tp1_weight, be_default=be, source="MIGRATED_FROM_1_9_SETTINGS_AT_FIRST_TICK")
