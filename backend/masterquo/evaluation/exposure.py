"""Read-only portfolio view across both execution paths (AR-02). It never opens, closes, blocks or changes a position.

Sources: `managed_positions` in state OPEN (S01-S12 path: PAPER and AUTO_*) and `sh_plans` that are not closed (SCALPING / HEDGING,
including the hedge leg of a HEDGING basket). The SHADOW service makes no terminal calls: positions opened by hand or by another
EA are not part of this view (in AUTO_DEMO the SH coordinator counts them separately).

Status per symbol:
  FLAT           no open exposure
  SINGLE_ENGINE  exposure from one engine only
  STACKING       both engines hold the same direction (risk adds up; each engine sizes as if it were alone)
  CONFLICT       opposite directions from different engines - on a netting account the second order reduces or closes the
                 first; on a hedging account it is an unplanned hedge
"""
from __future__ import annotations

from ..sh.store import SHStore

SIDE = {"BUY": "LONG", "SELL": "SHORT", "LONG": "LONG", "SHORT": "SHORT"}


def positions(db, symbol: str | None = None) -> list[dict]:
    out = []
    q = "SELECT position_key, mode, setup_id, strategy_id, symbol, side, volume_open, entry_price, sl, opened_at FROM managed_positions WHERE state='OPEN'"
    args: list = []
    if symbol:
        q += " AND symbol=?"
        args.append(symbol)
    for r in db.query(q, args):
        out.append({"engine": "ACTIVE_S01_S12", "id": r["position_key"], "mode": r["mode"], "strategy": r["strategy_id"], "symbol": r["symbol"],
                    "side": SIDE.get(r["side"], r["side"]), "volume": float(r["volume_open"] or 0.0), "entry": r["entry_price"], "sl": r["sl"],
                    "opened_at": r["opened_at"], "leg": "PRIMARY"})
    for p in SHStore(db).open_plans(symbol):
        o = p.get("fsm_obj")
        prim = getattr(o, "primary", o)
        vol = getattr(prim, "remaining", None)
        if vol is None:
            vol = ((p.get("plan") or {}).get("risk") or {}).get("volume", 0.0)
        side = SIDE.get(p["side"], p["side"])
        base = {"engine": "SH_" + p["strategy"], "id": p["plan_id"], "mode": p["exec_mode"], "strategy": p["strategy"], "symbol": p["symbol"],
                "opened_at": p["created_at"], "state": p["state"]}
        out.append({**base, "side": side, "volume": float(vol or 0.0), "entry": getattr(prim, "entry", None), "sl": getattr(prim, "sl", None),
                    "leg": "PRIMARY"})
        h = getattr(o, "hedge", None)
        if h is not None and getattr(h, "status", None) == "OPEN" and getattr(h, "volume", 0.0):
            out.append({**base, "side": "SHORT" if side == "LONG" else "LONG", "volume": float(h.volume), "entry": getattr(h, "entry", None),
                        "sl": None, "leg": "HEDGE"})
    return out


def summarize(items: list[dict]) -> dict:
    by: dict[str, dict] = {}
    for it in items:
        s = by.setdefault(it["symbol"], {"items": [], "long_volume": 0.0, "short_volume": 0.0, "engines": set()})
        s["items"].append(it)
        s["engines"].add(it["engine"])
        s["long_volume" if it["side"] == "LONG" else "short_volume"] += it["volume"]
    out = {}
    for sym, s in by.items():
        prim = [i for i in s["items"] if i["leg"] == "PRIMARY"]
        dirs = {(i["engine"], i["side"]) for i in prim}
        engines_by_side = {side: {e for e, d in dirs if d == side} for side in ("LONG", "SHORT")}
        cross = any(e1 != e2 for e1 in engines_by_side["LONG"] for e2 in engines_by_side["SHORT"])
        same = any(len(v) > 1 for v in engines_by_side.values())
        status = "CONFLICT" if cross else "STACKING" if same else "SINGLE_ENGINE"
        out[sym] = {"status": status, "engines": sorted(s["engines"]), "long_volume": round(s["long_volume"], 4),
                    "short_volume": round(s["short_volume"], 4), "net_volume": round(s["long_volume"] - s["short_volume"], 4),
                    "items": s["items"]}
    return out


def portfolio(db, symbol: str | None = None) -> dict:
    items = positions(db, symbol)
    per = summarize(items)
    worst = "CONFLICT" if any(v["status"] == "CONFLICT" for v in per.values()) else \
        "STACKING" if any(v["status"] == "STACKING" for v in per.values()) else ("SINGLE_ENGINE" if per else "FLAT")
    return {"status": worst, "symbols": per, "open_items": len(items), "mode": "READ_ONLY",
            "sources": ["managed_positions (S01-S12)", "sh_plans (SCALPING/HEDGING)"],
            "not_included": "pozycje ręczne i innych EA w terminalu (serwis SHADOW nie odpytuje terminala)"}


def for_candidate(items: list[dict], symbol: str, direction: str) -> dict:
    """Where a NEW idea would land in the current portfolio (own primary legs of every engine count)."""
    mine = [i for i in items if i["symbol"] == symbol and i["leg"] == "PRIMARY"]
    opp = [i for i in mine if i["side"] != direction]
    same = [i for i in mine if i["side"] == direction]
    status = "CONFLICT" if opp else "STACKING" if same else "OK"
    return {"status": status, "opposite": [{k: i[k] for k in ("engine", "id", "volume")} for i in opp],
            "same_direction": [{k: i[k] for k in ("engine", "id", "volume")} for i in same]}
