"""Position manager & reconciliation loop (1 s cadence).

* resolves UNKNOWN/SENDING order attempts by matching the client tag/magic in terminal positions
  and deals (never by re-sending);
* manages only positions opened by this application (or explicitly adopted by the user):
  TP1 partial close and SL to break-even after TP1 (strategy rule MQAI-LEVELS-1.0.0);
* settles closed positions from MT5 deal history into `trades` (partial fills grouped by position);
* simulates PAPER exits on live quotes;
* stores equity snapshots every 60 s (ACCOUNT and PAPER) for real equity curves;
* after (re)connection performs a full reconciliation before the gateway may send orders.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import timedelta

from ..db.database import dumps
from ..engine.lifecycle import TERMINAL
from ..mt5.worker import PRIO_TRADE, MT5CallTimeout
from ..risk.engine import floor_to_step
from ..timeutil import from_epoch, iso, parse_iso, utcnow
from .gateway import RETCODES

log = logging.getLogger("masterquo.manager")


class PositionManager:
    def __init__(self, cfg_store, bridge, db, bus, applog, modes, paper):
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.db = db
        self.bus = bus
        self.log = applog
        self.modes = modes
        self.paper = paper
        self.reconciled_epoch = -1
        self._stop = threading.Event()
        self._last_equity = 0.0
        self.last_error: str | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="position-manager", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._lock:
                    self.tick()
                self.last_error = None
            except Exception as exc:
                log.exception("manager tick failed")
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            self._stop.wait(1.0)

    # ------------------------------------------------------------ main tick
    def tick(self) -> None:
        b = self.bridge
        connected = b.state == "CONNECTED"
        if connected:
            self._resolve_unknown()
            self._manage_mt5_positions()
            if self.reconciled_epoch != b.session_epoch and b.deals_loaded_at is not None:
                self.reconciled_epoch = b.session_epoch
                self.log.info("EXECUTION", "RECONCILED", "Stan pozycji uzgodniony z terminalem po połączeniu.")
        self._manage_paper()
        if time.monotonic() - self._last_equity >= 60:
            self._last_equity = time.monotonic()
            self._equity_snapshot()

    # ------------------------------------------------------------ unknown attempts
    def _resolve_unknown(self) -> None:
        rows = self.db.query("SELECT * FROM order_attempts WHERE state IN ('SENDING','UNKNOWN') AND mode IN ('AUTO_DEMO','AUTO_LIVE') AND account_key=?",
                             (self.bridge.account_key,))
        if not rows:
            return
        with self.bridge._lock:
            positions = list(self.bridge.positions)
            deals = list(self.bridge.deals)
            deals_at = self.bridge.deals_loaded_at
        magic = self.cfg_store.get().mt5.magic_number
        for a in rows:
            pos = next((p for p in positions if p.get("magic") == magic and str(p.get("comment") or "").startswith(a["client_tag"])), None)
            deal = next((d for d in deals if d.get("magic") == magic and str(d.get("comment") or "").startswith(a["client_tag"]) and d.get("entry") == 0), None)
            if pos or deal:
                ticket = pos["ticket"] if pos else deal["position_id"]
                vol = pos["volume"] if pos else deal["volume"]
                price = pos["price_open"] if pos else deal["price"]
                self.db.execute("UPDATE order_attempts SET state='FILLED', position_ticket=?, fill_price=?, filled_volume=?, retcode_text=?, updated_at=? WHERE attempt_id=?",
                                (ticket, price, vol, "RECONCILED_FROM_TERMINAL", iso(utcnow()), a["attempt_id"]))
                self._register_from_attempt(a, ticket, vol, price)
                self.log.warn("EXECUTION", "UNKNOWN_RESOLVED_FILLED", f"Zlecenie UNKNOWN odnalezione w terminalu (ticket {ticket}).")
            elif deals_at and deals_at > parse_iso(a["updated_at"]) + timedelta(seconds=90):
                self.db.execute("UPDATE order_attempts SET state='NOT_FOUND_CHECK_TERMINAL', updated_at=? WHERE attempt_id=?",
                                (iso(utcnow()), a["attempt_id"]))
                self.log.error("EXECUTION", "UNKNOWN_NOT_FOUND", "Zlecenie UNKNOWN nie występuje w pozycjach ani historii – sprawdź terminal. Brak ponownego wysłania.")

    def _register_from_attempt(self, a: dict, ticket: int, vol: float, price: float) -> None:
        dec = self.db.one("SELECT record_json FROM decisions WHERE decision_id=?", (a["decision_id"],))
        rec = json.loads(dec["record_json"]) if dec else {}
        risk = rec.get("risk") or {}
        t = risk.get("targets") or []
        self.db.execute("""INSERT OR IGNORE INTO managed_positions(position_key, mode, account_key, position_ticket, attempt_id, decision_id, setup_id,
                           strategy_id, symbol, side, volume_initial, volume_open, entry_price, sl, tp1, tp2, state, opened_at, planned_risk_money)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"{a['mode']}:{a['account_key']}:{ticket}", a["mode"], a["account_key"], ticket, a["attempt_id"], a["decision_id"], a["setup_id"],
                         (rec.get("setup") or {}).get("strategy_id"), a["symbol"], a["side"], vol, vol, price, a["sl"],
                         t[0]["price"] if len(t) > 1 else None, a["tp"], "OPEN", iso(utcnow()), risk.get("modeled_loss")))

    # ------------------------------------------------------------ MT5 positions
    def _manage_mt5_positions(self) -> None:
        b = self.bridge
        rows = self.db.query("SELECT * FROM managed_positions WHERE state='OPEN' AND mode IN ('AUTO_DEMO','AUTO_LIVE') AND account_key=?",
                             (b.account_key,))
        if not rows:
            return
        with b._lock:
            positions = {p["ticket"]: p for p in b.positions}
            deals = list(b.deals)
        q = b.quote_status()
        cfg = self.cfg_store.get()
        for mp in rows:
            p = positions.get(mp["position_ticket"])
            if p is None:
                self._settle_mt5(mp, deals)
                continue
            if abs((p.get("volume") or 0) - mp["volume_open"]) > 1e-9:
                self.db.execute("UPDATE managed_positions SET volume_open=? WHERE position_key=?", (p["volume"], mp["position_key"]))
                mp["volume_open"] = p["volume"]
            if not q or mp["tp1"] is None or mp["tp1_done"]:
                if mp["tp1_done"] and not mp["be_done"] and cfg.strategy.move_sl_to_breakeven_after_tp1:
                    self._move_be(mp, p)
                continue
            hit = (q["bid"] >= mp["tp1"]) if mp["side"] == "BUY" else (q["ask"] <= mp["tp1"])
            if hit and (mp["adopted"] == 0):
                self._partial_close(mp, p)

    def _partial_close(self, mp: dict, p: dict) -> None:
        info = self.bridge.symbol_info or {}
        cfg = self.cfg_store.get()
        vol = floor_to_step(mp["volume_initial"] * cfg.strategy.tp1_weight, float(info.get("volume_step") or 0.01), float(info.get("volume_min") or 0.01))
        if vol <= 0 or vol >= mp["volume_open"] - 1e-9:
            self.db.execute("UPDATE managed_positions SET tp1_done=1 WHERE position_key=?", (mp["position_key"],))
            self.log.info("EXECUTION", "TP1_PARTIAL_SKIPPED", "TP1 osiągnięty – wolumen za mały na częściowe zamknięcie; pozycja zostaje do TP2/SL.")
            return
        sym, ticket, side = mp["symbol"], mp["position_ticket"], mp["side"]

        def req(m):
            t = m.symbol_info_tick(sym)
            return {"action": m.TRADE_ACTION_DEAL, "symbol": sym, "volume": vol, "position": ticket,
                    "type": m.ORDER_TYPE_SELL if side == "BUY" else m.ORDER_TYPE_BUY, "price": t.bid if side == "BUY" else t.ask,
                    "deviation": int(cfg.execution.deviation_points), "magic": int(cfg.mt5.magic_number), "comment": "MQ:TP1",
                    "type_time": m.ORDER_TIME_GTC, "type_filling": m.ORDER_FILLING_FOK if int(info.get("filling_mode") or 0) & 1 else m.ORDER_FILLING_IOC}
        # mark first: a crash after sending must not lead to a second partial close
        self.db.execute("UPDATE managed_positions SET tp1_done=1 WHERE position_key=?", (mp["position_key"],))
        try:
            r = self.bridge.raw_call(lambda m: m.order_send(req(m)), PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
            rc = getattr(r, "retcode", None)
            if rc in (10008, 10009, 10010):
                self.log.info("EXECUTION", "TP1_PARTIAL", f"TP1: zamknięto częściowo {vol} lota pozycji {ticket}.")
            else:
                self.log.warn("EXECUTION", "TP1_PARTIAL_REJECTED", f"TP1 częściowe zamknięcie odrzucone: {RETCODES.get(rc, rc)}")
        except MT5CallTimeout:
            self.log.error("EXECUTION", "TP1_PARTIAL_UNKNOWN", "Brak odpowiedzi przy częściowym zamknięciu TP1 – sprawdź terminal.")

    def _move_be(self, mp: dict, p: dict) -> None:
        info = self.bridge.symbol_info or {}
        point = float(info.get("point") or 0)
        stops = (info.get("trade_stops_level") or 0) * point
        freeze = (info.get("trade_freeze_level") or 0) * point
        q = self.bridge.quote_status()
        if not q:
            return
        be = mp["entry_price"]
        cur_sl = p.get("sl") or 0
        better = (be > cur_sl) if mp["side"] == "BUY" else (cur_sl == 0 or be < cur_sl)
        ref = q["bid"] if mp["side"] == "BUY" else q["ask"]
        if not better:
            self.db.execute("UPDATE managed_positions SET be_done=1 WHERE position_key=?", (mp["position_key"],))
            return
        if abs(ref - be) < max(stops, freeze):
            return  # too close to the market (stops/freeze level) - retry next tick
        cfg = self.cfg_store.get()
        ticket, tp = mp["position_ticket"], p.get("tp") or 0.0
        try:
            r = self.bridge.raw_call(lambda m: m.order_send({"action": m.TRADE_ACTION_SLTP, "symbol": mp["symbol"], "position": ticket,
                                                              "sl": float(be), "tp": float(tp), "magic": int(cfg.mt5.magic_number)}),
                                     PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
            if getattr(r, "retcode", None) in (10008, 10009):
                self.db.execute("UPDATE managed_positions SET be_done=1, sl=? WHERE position_key=?", (be, mp["position_key"]))
                self.log.info("EXECUTION", "SL_TO_BE", f"SL przesunięty na BE ({be}) dla pozycji {ticket}.")
        except MT5CallTimeout:
            self.log.error("EXECUTION", "SL_TO_BE_UNKNOWN", "Brak odpowiedzi przy przesunięciu SL na BE – sprawdź terminal.")

    def _settle_mt5(self, mp: dict, deals: list[dict]) -> None:
        mine = [d for d in deals if d.get("position_id") == mp["position_ticket"]]
        outs = [d for d in mine if d.get("entry") in (1, 2, 3)]
        if not outs:
            if parse_iso(mp["opened_at"]) < utcnow() - timedelta(minutes=10):
                self.db.execute("UPDATE managed_positions SET state='CLOSED_UNSETTLED', closed_at=? WHERE position_key=?", (iso(utcnow()), mp["position_key"]))
                self.log.warn("EXECUTION", "CLOSED_UNSETTLED", f"Pozycja {mp['position_ticket']} zniknęła, brak transakcji w historii – sprawdź historię w terminalu.")
            return
        off = self.bridge.clock.offset or 0
        gross = sum(float(d.get("profit") or 0) for d in mine)
        comm = sum(float(d.get("commission") or 0) for d in mine)
        swap = sum(float(d.get("swap") or 0) for d in mine)
        fee = sum(float(d.get("fee") or 0) for d in mine)
        vol = sum(float(d.get("volume") or 0) for d in outs)
        avg = sum(float(d["volume"]) * float(d["price"]) for d in outs) / vol if vol else None
        closed = from_epoch(max(d["time"] for d in outs) - off)
        net = gross + comm + swap + fee
        cur = (self.bridge.account_status() or {}).get("currency")
        risk = mp.get("planned_risk_money")
        self.db.execute("""INSERT OR REPLACE INTO trades(trade_id, mode, source, account_key, position_ticket, decision_id, setup_id, strategy_id, symbol, side,
                           volume, entry_price, exit_price_avg, opened_at, closed_at, gross_pnl, commission, swap, fee, net_pnl, currency, planned_risk_money,
                           r_multiple, deals_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"{mp['mode']}-{mp['account_key']}-{mp['position_ticket']}", mp["mode"], "BOT" if not mp["adopted"] else "ADOPTED",
                         mp["account_key"], mp["position_ticket"], mp["decision_id"], mp["setup_id"], mp["strategy_id"], mp["symbol"], mp["side"],
                         vol, mp["entry_price"], avg, mp["opened_at"], iso(closed), round(gross, 2), round(comm, 2), round(swap, 2), round(fee, 2),
                         round(net, 2), cur, risk, round(net / risk, 3) if risk else None, dumps(mine)))
        self.db.execute("UPDATE managed_positions SET state='CLOSED', volume_open=0, closed_at=? WHERE position_key=?", (iso(closed), mp["position_key"]))
        self.log.info("EXECUTION", "SETTLED", f"Pozycja {mp['position_ticket']} rozliczona: netto {round(net, 2)} {cur or ''}")
        self.bus.publish("trade_settled", {"position": mp["position_ticket"], "net": round(net, 2)})

    # ------------------------------------------------------------ PAPER
    def _manage_paper(self) -> None:
        rows = self.db.query("SELECT * FROM managed_positions WHERE state='OPEN' AND mode='PAPER'")
        if not rows:
            return
        q = self.bridge.quote_status()
        if not q or q.get("age_seconds") is None or q["age_seconds"] > self.cfg_store.get().mt5.max_quote_age_seconds:
            return
        cfg = self.cfg_store.get()
        info = self.bridge.symbol_info or {}
        for mp in rows:
            buy = mp["side"] == "BUY"
            px = q["bid"] if buy else q["ask"]
            if mp["sl"] and ((buy and px <= mp["sl"]) or (not buy and px >= mp["sl"])):
                fill = min(px, mp["sl"]) if buy else max(px, mp["sl"])
                self.paper.close_part(mp, mp["volume_open"], fill, "SL" if not mp["be_done"] else "BE")
                self._paper_done(mp)
                continue
            if mp["tp2"] and ((buy and px >= mp["tp2"]) or (not buy and px <= mp["tp2"])):
                self.paper.close_part(mp, mp["volume_open"], px, "TP2" if mp["tp1"] else "TP")
                self._paper_done(mp)
                continue
            if mp["tp1"] and not mp["tp1_done"] and ((buy and px >= mp["tp1"]) or (not buy and px <= mp["tp1"])):
                vol = floor_to_step(mp["volume_initial"] * cfg.strategy.tp1_weight, float(info.get("volume_step") or 0.01), float(info.get("volume_min") or 0.01))
                self.db.execute("UPDATE managed_positions SET tp1_done=1 WHERE position_key=?", (mp["position_key"],))
                if 0 < vol < mp["volume_open"] - 1e-9:
                    self.paper.close_part(mp, vol, px, "TP1")
                if cfg.strategy.move_sl_to_breakeven_after_tp1:
                    self.db.execute("UPDATE managed_positions SET sl=?, be_done=1 WHERE position_key=?", (mp["entry_price"], mp["position_key"]))
                    self.log.info("PAPER", "SL_TO_BE", f"PAPER: SL na BE {mp['entry_price']}")

    def _paper_done(self, mp: dict) -> None:
        self.bus.publish("trade_settled", {"position": mp["position_ticket"], "mode": "PAPER"})

    # ------------------------------------------------------------ equity
    def _equity_snapshot(self) -> None:
        now = iso(utcnow())
        a = self.bridge.account_status()
        if a and self.bridge.state == "CONNECTED":
            self.db.execute("INSERT INTO equity_snapshots(ts, mode, account_key, balance, equity, margin, free_margin, currency) VALUES (?,?,?,?,?,?,?,?)",
                            (now, "ACCOUNT", self.bridge.account_key, a.get("balance"), a.get("equity"), a.get("margin"), a.get("free_margin"), a.get("currency")))
        if self.db.one("SELECT 1 AS x FROM paper_account WHERE id=1"):
            pa = self.paper.account()
            self.db.execute("INSERT INTO equity_snapshots(ts, mode, account_key, balance, equity, margin, free_margin, currency) VALUES (?,?,?,?,?,?,?,?)",
                            (now, "PAPER", None, pa["balance"], pa["equity"], None, None, pa["currency"]))

    # ------------------------------------------------------------ user operations
    def close_positions(self, scope: str, ticket: int | None = None) -> dict:
        """Explicit, confirmed close of positions managed by this app (separate from 'stop new entries')."""
        b = self.bridge
        cfg = self.cfg_store.get()
        rows = self.db.query("SELECT * FROM managed_positions WHERE state='OPEN'" + (" AND position_ticket=?" if ticket else ""), (ticket,) if ticket else ())
        done, errors = [], []
        q = b.quote_status()
        for mp in rows:
            if mp["mode"] == "PAPER":
                if q:
                    self.paper.close_part(mp, mp["volume_open"], q["bid"] if mp["side"] == "BUY" else q["ask"], "MANUAL_CLOSE")
                    done.append(mp["position_ticket"])
                continue
            if mp["account_key"] != b.account_key:
                errors.append({"ticket": mp["position_ticket"], "error": "OTHER_ACCOUNT"})
                continue
            p = next((x for x in b.positions if x["ticket"] == mp["position_ticket"]), None)
            if not p:
                continue
            try:
                def req(m, p=p, mp=mp):
                    t = m.symbol_info_tick(mp["symbol"])
                    return {"action": m.TRADE_ACTION_DEAL, "symbol": mp["symbol"], "volume": float(p["volume"]), "position": p["ticket"],
                            "type": m.ORDER_TYPE_SELL if mp["side"] == "BUY" else m.ORDER_TYPE_BUY, "price": t.bid if mp["side"] == "BUY" else t.ask,
                            "deviation": int(cfg.execution.deviation_points), "magic": int(cfg.mt5.magic_number), "comment": "MQ:CLOSE",
                            "type_time": m.ORDER_TIME_GTC, "type_filling": m.ORDER_FILLING_FOK if int((b.symbol_info or {}).get("filling_mode") or 0) & 1 else m.ORDER_FILLING_IOC}
                r = b.raw_call(lambda m: m.order_send(req(m)), PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
                rc = getattr(r, "retcode", None)
                (done if rc in (10008, 10009, 10010) else errors).append({"ticket": p["ticket"], "retcode": RETCODES.get(rc, rc)})
            except MT5CallTimeout:
                errors.append({"ticket": p["ticket"], "error": "TIMEOUT_CHECK_TERMINAL"})
        self.log.warn("EXECUTION", "CLOSE_REQUEST", f"Zamknięcie pozycji ({scope}): wykonane {len(done)}, błędy {len(errors)}")
        return {"closed": done, "errors": errors}

    def adopt(self, ticket: int) -> dict:
        b = self.bridge
        p = next((x for x in b.positions if x["ticket"] == ticket), None)
        if not p:
            return {"ok": False, "error": "POSITION_NOT_FOUND"}
        key = f"ADOPTED:{b.account_key}:{ticket}"
        mode = self.modes.gate(b.account_key)["mode"]
        if mode not in ("AUTO_DEMO", "AUTO_LIVE"):
            return {"ok": False, "error": "ADOPTION_REQUIRES_EXECUTION_MODE"}
        self.db.execute("""INSERT OR IGNORE INTO managed_positions(position_key, mode, account_key, position_ticket, symbol, side, volume_initial, volume_open,
                           entry_price, sl, tp2, state, adopted, opened_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (key, mode, b.account_key, ticket, p["symbol"], p["side"], p["volume"], p["volume"], p["price_open"], p.get("sl"), p.get("tp"),
                         "OPEN", 1, iso(utcnow())))
        self.log.warn("EXECUTION", "ADOPTED", f"Pozycja ręczna {ticket} przejęta przez użytkownika (tylko rozliczanie/zamknięcie na żądanie).")
        return {"ok": True}


__all__ = ["PositionManager", "TERMINAL"]
