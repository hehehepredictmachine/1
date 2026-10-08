"""PAPER simulation - a local ledger in this application's database, not an MT5 demo account.

Fills: entry at current Ask (BUY) / Bid (SELL); exits at Bid (BUY) / Ask (SELL) when the level is
crossed; if price gapped beyond a level the fill uses the worse current price. Commission from the
resolved cost model (per lot per side). P/L via the broker profit calculator when available.
"""
from __future__ import annotations

import uuid

from ..db.database import dumps
from ..risk.costs import resolve_commission
from ..timeutil import iso, utcnow


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
        floating = 0.0
        q = self.bridge.quote_status()
        for p in self.db.query("SELECT * FROM managed_positions WHERE mode='PAPER' AND state='OPEN'"):
            if q:
                px = q["bid"] if p["side"] == "BUY" else q["ask"]
                v = self._profit(p["side"], p["volume_open"], p["entry_price"], px)
                floating += v or 0.0
        return {"mode": "PAPER", "currency": row["currency"], "balance": round(row["balance"], 2), "equity": round(row["balance"] + floating, 2),
                "floating": round(floating, 2), "starting_balance": row["starting_balance"], "started_at": row["started_at"]}

    def _profit(self, side, vol, o, c):
        try:
            return self.bridge.calc_profit(side, vol, o, c)
        except Exception:
            return None

    def _commission(self, vol: float) -> float:
        cfg = self.cfg_store.get()
        with self.bridge._lock:
            deals = list(self.bridge.deals)
        c = resolve_commission(cfg.costs, deals, cfg.mt5.symbol).get("per_lot_per_side") or 0.0
        return round(c * vol, 2)

    def open(self, *, attempt_id: str, decision: dict, side: str, lots: float, sl: float, targets: list[dict]) -> dict:
        q = self.bridge.quote_status()
        if not q:
            self.db.execute("UPDATE order_attempts SET state='REJECTED', retcode_text='PAPER_NO_QUOTE', updated_at=? WHERE attempt_id=?", (iso(utcnow()), attempt_id))
            return {"status": "REJECTED", "reason": "PAPER_NO_QUOTE"}
        price = q["ask"] if side == "BUY" else q["bid"]
        ticket = int(uuid.uuid4().int % 10**12)
        self.account()
        comm = self._commission(lots)
        self.db.execute("UPDATE paper_account SET balance = balance - ? WHERE id=1", (comm,))
        now = iso(utcnow())
        self.db.execute("""UPDATE order_attempts SET state='FILLED', retcode_text='PAPER_FILL', position_ticket=?, fill_price=?, filled_volume=?,
                           updated_at=?, result_json=? WHERE attempt_id=?""", (ticket, price, lots, now, dumps({"paper": True, "commission": comm}), attempt_id))
        self.db.execute("""INSERT INTO managed_positions(position_key, mode, account_key, position_ticket, attempt_id, decision_id, setup_id, strategy_id,
                           symbol, side, volume_initial, volume_open, entry_price, sl, tp1, tp2, state, opened_at, planned_risk_money)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"PAPER:{ticket}", "PAPER", self.bridge.account_key, ticket, attempt_id, decision["decision_id"], decision["setup"]["setup_id"],
                         decision["setup"]["strategy_id"], decision["symbol"], side, lots, lots, price, sl,
                         targets[0]["price"] if len(targets) > 1 else None, targets[-1]["price"], "OPEN", now, (decision.get("risk") or {}).get("modeled_loss")))
        self.log.info("PAPER", "FILLED", f"PAPER: {side} {lots} @ {price} (symulacja lokalna)")
        return {"status": "FILLED", "ticket": ticket, "price": price, "volume": lots, "paper": True, "commission": comm}

    def close_part(self, pos: dict, volume: float, price: float, reason: str) -> float:
        """Close `volume` of a PAPER position at `price`; returns net P/L of the part."""
        gross = self._profit(pos["side"], volume, pos["entry_price"], price) or 0.0
        comm = self._commission(volume)
        net = round(gross - comm, 2)
        self.db.execute("UPDATE paper_account SET balance = balance + ? WHERE id=1", (net,))
        left = round(pos["volume_open"] - volume, 8)
        self.db.execute("UPDATE managed_positions SET volume_open=?, state=? , closed_at=? WHERE position_key=?",
                        (left, "OPEN" if left > 1e-9 else "CLOSED", iso(utcnow()) if left <= 1e-9 else None, pos["position_key"]))
        self._accumulate(pos, volume, price, gross, comm, reason)
        self.log.info("PAPER", reason, f"PAPER: zamknięto {volume} @ {price} ({reason}), wynik netto {net}")
        return net

    def _accumulate(self, pos: dict, volume: float, price: float, gross: float, comm: float, reason: str) -> None:
        tid = f"PAPER-{pos['position_ticket']}"
        row = self.db.one("SELECT * FROM trades WHERE trade_id=?", (tid,))
        now = iso(utcnow())
        entry_comm = self._commission(pos["volume_initial"])  # entry side commission charged at open
        if row is None:
            deals = [{"volume": volume, "price": price, "reason": reason, "at": now}]
            self.db.execute("""INSERT INTO trades(trade_id, mode, source, account_key, position_ticket, decision_id, setup_id, strategy_id, symbol, side,
                               volume, entry_price, exit_price_avg, opened_at, closed_at, gross_pnl, commission, swap, fee, net_pnl, currency,
                               planned_risk_money, r_multiple, deals_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (tid, "PAPER", "BOT", pos["account_key"], pos["position_ticket"], pos["decision_id"], pos["setup_id"], pos["strategy_id"],
                             pos["symbol"], pos["side"], volume, pos["entry_price"], price, pos["opened_at"], now, round(gross, 2),
                             -round(comm + entry_comm, 2), 0.0, 0.0, round(gross - comm - entry_comm, 2), self.account()["currency"],
                             pos.get("planned_risk_money"), None, dumps(deals)))
        else:
            import json
            deals = json.loads(row["deals_json"] or "[]") + [{"volume": volume, "price": price, "reason": reason, "at": now}]
            vol = row["volume"] + volume
            avg = sum(x["volume"] * x["price"] for x in deals) / vol
            g = row["gross_pnl"] + gross
            c = row["commission"] - comm
            self.db.execute("UPDATE trades SET volume=?, exit_price_avg=?, closed_at=?, gross_pnl=?, commission=?, net_pnl=?, deals_json=? WHERE trade_id=?",
                            (vol, avg, now, round(g, 2), round(c, 2), round(g + c, 2), dumps(deals), tid))
        risk = pos.get("planned_risk_money")
        if risk:
            self.db.execute("UPDATE trades SET r_multiple = ROUND(net_pnl / ?, 3) WHERE trade_id=?", (risk, tid))
