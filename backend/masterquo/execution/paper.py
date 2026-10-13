"""PAPER simulation - a local ledger in this application's database, not an MT5 demo account.

Fills: entry at current Ask (BUY) / Bid (SELL); exits at Bid (BUY) / Ask (SELL) when the level is
crossed; if price gapped beyond a stop the fill uses the worse current price. Commission from the
resolved cost model (per lot per side). P/L via the broker profit calculator when available.

Settlement (1.10): one `trades` row per position.
  OPEN_PARTIAL  partial exits done, the rest still open - NEVER counted in statistics;
  CLOSED        the whole position is closed and every part has a calculated P/L;
  UNSETTLED     a part could not be calculated (profit calculator unavailable) - never booked as 0, excluded from statistics.
  An unknown commission (no history, no configured value) is NOT assumed to be zero silently: the part is flagged
  commission_unknown and statistics report how many trades carry that flag.
PAPER is not evidence of real fill quality: no extra slippage, swap, fees, latency or rejections are modelled; quotes are
sampled about once per second.
"""
from __future__ import annotations

import json
import uuid

from ..db.database import dumps
from ..risk.costs import resolve_commission
from ..timeutil import iso, utcnow
from . import policy as exit_policy


class PaperBroker:
    def __init__(self, cfg_store, bridge, db, bus, applog):
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.db = db
        self.bus = bus
        self.log = applog

    def account(self) -> dict:
        row = self.db.one("SELECT * FROM paper_account WHERE id=1")
        if not row:
            bal = self.cfg_store.get().execution.paper_starting_balance
            cur = (self.bridge.account_status() or {}).get("currency") or "USD"
            self.db.execute("INSERT OR IGNORE INTO paper_account(id, currency, starting_balance, balance, started_at) VALUES (1,?,?,?,?)",
                            (cur, bal, bal, iso(utcnow())))
            row = self.db.one("SELECT * FROM paper_account WHERE id=1")
        floating, unknown = 0.0, 0
        q = self.bridge.quote_status()
        for p in self.db.query("SELECT * FROM managed_positions WHERE mode='PAPER' AND state='OPEN'"):
            if q:
                px = q["bid"] if p["side"] == "BUY" else q["ask"]
                v = self._profit(p["side"], p["volume_open"], p["entry_price"], px)
                if v is None:
                    unknown += 1
                else:
                    floating += v
        return {"mode": "PAPER", "currency": row["currency"], "balance": round(row["balance"], 2), "equity": round(row["balance"] + floating, 2),
                "floating": round(floating, 2), "floating_unknown_positions": unknown, "starting_balance": row["starting_balance"],
                "started_at": row["started_at"]}

    def _profit(self, side, vol, o, c):
        try:
            return self.bridge.calc_profit(side, vol, o, c)
        except Exception:
            return None

    def _commission(self, vol: float) -> float | None:
        """Commission in account currency for `vol` lots, one side. None = unknown (never assumed 0)."""
        cfg = self.cfg_store.get()
        with self.bridge._lock:
            deals = list(self.bridge.deals)
        c = resolve_commission(cfg.costs, deals, cfg.mt5.symbol).get("per_lot_per_side")
        return None if c is None else round(c * vol, 2)

    def open(self, *, attempt_id: str, decision: dict, side: str, lots: float, sl: float, targets: list[dict], exit_policy: dict | None = None) -> dict:
        q = self.bridge.quote_status()
        if not q:
            self.db.execute("UPDATE order_attempts SET state='REJECTED', retcode_text='PAPER_NO_QUOTE', updated_at=? WHERE attempt_id=?", (iso(utcnow()), attempt_id))
            return {"status": "REJECTED", "reason": "PAPER_NO_QUOTE"}
        price = q["ask"] if side == "BUY" else q["bid"]
        if exit_policy is None:
            cfg = self.cfg_store.get()
            exit_policy = _policy_mod_from(decision, side, sl, targets, cfg)
        pol = _rebase(exit_policy, price)
        ticket = int(uuid.uuid4().int % 10**12)
        self.account()
        comm = self._commission(lots)
        if comm is not None:
            self.db.execute("UPDATE paper_account SET balance = balance - ? WHERE id=1", (comm,))
        now = iso(utcnow())
        self.db.execute("""UPDATE order_attempts SET state='FILLED', retcode_text='PAPER_FILL', position_ticket=?, fill_price=?, filled_volume=?,
                           updated_at=?, result_json=? WHERE attempt_id=?""", (ticket, price, lots, now, dumps({"paper": True, "commission": comm}), attempt_id))
        t = pol["targets"]
        self.db.execute("""INSERT INTO managed_positions(position_key, mode, account_key, position_ticket, attempt_id, decision_id, setup_id, strategy_id,
                           symbol, side, volume_initial, volume_open, entry_price, sl, tp1, tp2, state, opened_at, planned_risk_money, exit_policy_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"PAPER:{ticket}", "PAPER", self.bridge.account_key, ticket, attempt_id, decision["decision_id"], decision["setup"]["setup_id"],
                         decision["setup"]["strategy_id"], decision["symbol"], side, lots, lots, price, sl,
                         t[0]["price"] if len(t) > 1 else None, t[-1]["price"] if t else None, "OPEN", now, (decision.get("risk") or {}).get("modeled_loss"),
                         dumps(pol)))
        self.log.info("PAPER", "FILLED", f"PAPER: {side} {lots} @ {price} (symulacja lokalna)")
        return {"status": "FILLED", "ticket": ticket, "price": price, "volume": lots, "paper": True, "commission": comm}

    def close_part(self, pos: dict, volume: float, price: float, reason: str) -> float | None:
        """Close `volume` of a PAPER position at `price`; returns net P/L of the part (None = could not be calculated)."""
        gross = self._profit(pos["side"], volume, pos["entry_price"], price)
        comm = self._commission(volume)
        net = None if gross is None else round(gross - (comm or 0.0), 2)
        if net is not None:
            self.db.execute("UPDATE paper_account SET balance = balance + ? WHERE id=1", (net,))
        left = round(pos["volume_open"] - volume, 8)
        closed = left <= 1e-9
        self.db.execute("UPDATE managed_positions SET volume_open=?, state=?, closed_at=? WHERE position_key=?",
                        (max(0.0, left), "CLOSED" if closed else "OPEN", iso(utcnow()) if closed else None, pos["position_key"]))
        pos["volume_open"] = max(0.0, left)
        self._accumulate(pos, volume, price, gross, comm, reason, closed)
        self.log.info("PAPER", reason, f"PAPER: zamknięto {volume} @ {price} ({reason}), wynik netto "
                      + (f"{net}" if net is not None else "NIEROZLICZONY (brak kalkulacji P/L)"))
        return net

    def _accumulate(self, pos: dict, volume: float, price: float, gross: float | None, comm: float | None, reason: str, closed: bool) -> None:
        tid = f"PAPER-{pos['position_ticket']}"
        row = self.db.one("SELECT * FROM trades WHERE trade_id=?", (tid,))
        now = iso(utcnow())
        part = {"volume": volume, "price": price, "reason": reason, "at": now, "gross": gross, "commission": comm,
                "settled": gross is not None, "commission_unknown": comm is None}
        pol = json.loads(pos.get("exit_policy_json") or "null") or {}
        if row is None:
            entry_comm = self._commission(pos["volume_initial"])    # entry side commission charged at open
            deals = [{"entry_commission": entry_comm, "settled": True, "commission_unknown": entry_comm is None}, part]
        else:
            deals = json.loads(row["deals_json"] or "[]") + [part]
        parts = [d for d in deals if "volume" in d]
        unsettled = not all(d.get("settled") for d in deals)
        vol = sum(d["volume"] for d in parts)
        avg = sum(d["volume"] * d["price"] for d in parts) / vol if vol else None
        g = sum(d["gross"] for d in parts if d.get("gross") is not None)
        c = -sum(abs(d["commission"]) for d in parts if d.get("commission") is not None) - abs(deals[0].get("entry_commission") or 0.0)
        net = g + c
        status = "UNSETTLED" if (closed and unsettled) else ("CLOSED" if closed else "OPEN_PARTIAL")
        risk = pos.get("planned_risk_money")
        r_mult = round(net / risk, 3) if (risk and status == "CLOSED") else None
        if row is None:
            self.db.execute("""INSERT INTO trades(trade_id, mode, source, account_key, position_ticket, decision_id, setup_id, strategy_id, symbol, side,
                               volume, entry_price, exit_price_avg, opened_at, closed_at, gross_pnl, commission, swap, fee, net_pnl, currency,
                               planned_risk_money, r_multiple, deals_json, status, exit_policy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (tid, "PAPER", "BOT", pos["account_key"], pos["position_ticket"], pos["decision_id"], pos["setup_id"], pos["strategy_id"],
                             pos["symbol"], pos["side"], vol, pos["entry_price"], avg, pos["opened_at"], now, round(g, 2), round(c, 2), 0.0, 0.0,
                             round(net, 2), self.account()["currency"], risk, r_mult, dumps(deals), status, pol.get("version")))
        else:
            self.db.execute("""UPDATE trades SET volume=?, exit_price_avg=?, closed_at=?, gross_pnl=?, commission=?, net_pnl=?, deals_json=?, status=?,
                               r_multiple=? WHERE trade_id=?""",
                            (vol, avg, now, round(g, 2), round(c, 2), round(net, 2), dumps(deals), status, r_mult, tid))


def _policy_mod_from(decision: dict, side: str, sl: float, targets: list[dict], cfg) -> dict:
    lv = decision.get("levels") or {}
    return exit_policy.from_plan(side="LONG" if side == "BUY" else "SHORT", stop_loss=sl, targets=targets, exit_rules=lv.get("exit_rules"),
                                 timeframe=(decision.get("setup") or {}).get("setup_tf"), tp1_weight_default=cfg.strategy.tp1_weight,
                                 be_default=cfg.strategy.move_sl_to_breakeven_after_tp1)


def _rebase(pol: dict, fill: float) -> dict:
    return exit_policy.rebase_on_fill(pol, fill)
