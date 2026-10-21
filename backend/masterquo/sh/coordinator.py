"""Conflict coordinator for SCALPING / HEDGING on one symbol (docs/strategie_sh/04_KONFLIKTY.md).

Rules (in this order; anything unresolved becomes WAIT with the reason, never a guess):
1. One owner per position: positions on the symbol owned by another manager (legacy bot, manual, other magic) -> WAIT.
2. An open SH plan on the symbol blocks a new plan of ANY SH strategy unless allow_parallel_same_symbol is true; even then
   SCALPING never opens while a HEDGING basket is open on the symbol (two managers would act on the same exposure), and an
   opposite direction is never opened in parallel (that would be an unmanaged hedge).
3. Two READY setups in OPPOSITE directions in the same cycle -> both WAIT (the market is ambiguous for the bot).
4. Two READY setups in the same direction -> the strategy earlier in `priority` proceeds, the other WAITs.
"""
from __future__ import annotations


def arbitrate(ready: list[dict], *, open_plans: list[dict], foreign_positions: int, cfg: dict, symbol: str) -> list[dict]:
    pri = list(cfg.get("priority") or ["HEDGING", "SCALPING"])
    par = bool(cfg.get("allow_parallel_same_symbol"))
    mine = [p for p in open_plans if p.get("symbol") == symbol and p.get("state") != "CLOSED"]
    out = []
    cands = []
    for s in ready:
        sid, strat, side = s["signal_id"], s["strategy"], s.get("side")
        if foreign_positions:
            out.append({"signal_id": sid, "strategy": strat, "decision": "WAIT",
                        "reason": f"{foreign_positions} pozycji innego menedżera na {symbol} – jeden właściciel pozycji"})
            continue
        if mine:
            hedging_open = any(p["strategy"] == "HEDGING" for p in mine)
            opposite = any(p.get("side") != side for p in mine)
            same_strat = any(p["strategy"] == strat for p in mine)
            if not par or same_strat:
                why = "otwarty plan SH na symbolu (jeden plan na symbol)" if not par else f"otwarty plan {strat} na symbolu"
            elif strat == "SCALPING" and hedging_open:
                why = "otwarty koszyk HEDGING – SCALPING nie zarządza tą samą ekspozycją"
            elif opposite:
                why = "kierunek przeciwny do otwartego planu – byłby niezarządzanym hedge"
            else:
                why = None
            if why:
                out.append({"signal_id": sid, "strategy": strat, "decision": "WAIT", "reason": why})
                continue
        cands.append(s)
    sides = {s.get("side") for s in cands}
    if len(sides) > 1:
        for s in cands:
            out.append({"signal_id": s["signal_id"], "strategy": s["strategy"], "decision": "WAIT",
                        "reason": "SCALPING i HEDGING wskazują przeciwne kierunki w tym samym cyklu – brak jednoznacznej decyzji"})
        return out
    cands.sort(key=lambda s: pri.index(s["strategy"]) if s["strategy"] in pri else 99)
    for i, s in enumerate(cands):
        if i == 0:
            out.append({"signal_id": s["signal_id"], "strategy": s["strategy"], "decision": "PROCEED", "reason": "brak konfliktu"})
        else:
            out.append({"signal_id": s["signal_id"], "strategy": s["strategy"], "decision": "WAIT",
                        "reason": f"priorytet {cands[0]['strategy']} (ten sam kierunek, jeden plan na cykl)"})
    return out
