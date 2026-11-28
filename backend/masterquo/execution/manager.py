"""Position manager & reconciliation loop (1 s cadence).

* resolves UNKNOWN/SENDING order attempts by matching the client tag/magic in terminal positions
  and deals (never by re-sending);
* manages only positions opened by this application (or explicitly adopted by the user) with the exit policy STORED at
  open (execution/policy.py, MQ-EXIT-POLICY-1.0.0): partial exits at every intermediate target with the plan's weights,
  SL to break-even after a CONFIRMED TP1 partial (only if the plan says so), time exit, RR_FROM_FILL target sync;
  partial-exit state comes from the execution: REQUESTED -> CONFIRMED / REJECTED / UNKNOWN (reconciled from the
  terminal's position volume, never re-sent);
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
from ..mt5.worker import PRIO_TRADE, MT5CallTimeout
from . import policy as exit_policy
from ..timeutil import from_epoch, iso, parse_iso, utcnow
from .gateway import RETCODES, align_stops, snap_tick

log = logging.getLogger("masterquo.manager")


class PositionManager:
    # w2 (I0095): optional dependency wired by runtime.py after construction - class default (None = absent), read as self.x
    arc = None

    def __init__(self, cfg_store, bridge, db, bus, applog, modes, paper):
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.db = db
        self.bus = bus
        self.log = applog
        self.modes = modes
        self.paper = paper
        self.reconciled_epoch = -1
        self._be_tries: dict = {}           # position_key -> BE retry state (F-06)
        self._unsettled_seen = None         # w2 (I0712): (account_key, deals_loaded_at) of the last CLOSED_UNSETTLED scan
        self._unsettled_alerted: set = set()
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
        arc = self.arc
        if arc is not None:                     # PMW-ARC-1: settle UNKNOWN/SENT intents from both paths' reconciliation (never re-sent)
            arc.sync()
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
        cfg = self.cfg_store.get()
        pol = exit_policy.from_plan(side="LONG" if a["side"] == "BUY" else "SHORT", stop_loss=float(a["sl"]),
                                    targets=risk.get("targets") or [{"price": a["tp"], "weight": 1.0}], exit_rules=(rec.get("levels") or {}).get("exit_rules"),
                                    timeframe=(rec.get("setup") or {}).get("setup_tf"), tp1_weight_default=cfg.strategy.tp1_weight,
                                    be_default=cfg.strategy.move_sl_to_breakeven_after_tp1, entry=float(price))
        t = pol["targets"]
        self.db.execute("""INSERT OR IGNORE INTO managed_positions(position_key, mode, account_key, position_ticket, attempt_id, decision_id, setup_id,
                           strategy_id, symbol, side, volume_initial, volume_open, entry_price, sl, tp1, tp2, state, opened_at, planned_risk_money, exit_policy_json)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"{a['mode']}:{a['account_key']}:{ticket}", a["mode"], a["account_key"], ticket, a["attempt_id"], a["decision_id"], a["setup_id"],
                         (rec.get("setup") or {}).get("strategy_id"), a["symbol"], a["side"], vol, vol, price, a["sl"],
                         t[0]["price"] if len(t) > 1 else None, a["tp"], "OPEN", iso(utcnow()), risk.get("modeled_loss"), dumps(pol)))

    # ------------------------------------------------------------ exit policy (stored at open)
    def _policy(self, mp: dict) -> dict:
        """The position's own exit policy. Positions opened before 1.10 get it reconstructed ONCE (settings at that moment)
        and frozen - later setting changes never alter an open position."""
        if mp.get("exit_policy_json"):
            return json.loads(mp["exit_policy_json"])
        cfg = self.cfg_store.get()
        pol = exit_policy.legacy(side_order=mp["side"], tp1=mp.get("tp1"), tp2=mp.get("tp2"), sl=mp.get("sl"),
                                 tp1_weight=cfg.strategy.tp1_weight, be=cfg.strategy.move_sl_to_breakeven_after_tp1)
        pol["fill_price"] = mp["entry_price"]
        self.db.execute("UPDATE managed_positions SET exit_policy_json=? WHERE position_key=?", (dumps(pol), mp["position_key"]))
        mp["exit_policy_json"] = dumps(pol)
        return pol

    @staticmethod
    def _note(mp: dict) -> dict:
        try:
            return json.loads(mp.get("exit_note") or "{}") or {}
        except (TypeError, ValueError):
            return {}

    def _save_note(self, mp: dict, note: dict) -> None:
        mp["exit_note"] = dumps(note)
        self.db.execute("UPDATE managed_positions SET exit_note=? WHERE position_key=?", (mp["exit_note"], mp["position_key"]))

    @staticmethod
    def _reached(side: str, q: dict, price: float) -> bool:
        return (q["bid"] >= price) if side == "BUY" else (q["ask"] <= price)

    @staticmethod
    def _time_exit_due(mp: dict, pol: dict) -> bool:
        m = pol.get("time_exit_minutes")
        return m is not None and parse_iso(mp["opened_at"]) + timedelta(minutes=int(m)) <= utcnow()

    def _be_allowed(self, mp: dict) -> bool:
        """BE after TP1 only when TP1 was really reached AND its partial exit is confirmed by the execution (or skipped
        because the volume was too small) - never after a rejected / unknown request."""
        first = next((x for x in self._note(mp).get("partials", []) if x.get("i") == 0), None)
        return bool(first) and first.get("state") in ("CONFIRMED", "SKIPPED_VOLUME")

    # ------------------------------------------------------------ MT5 positions
    def _manage_mt5_positions(self) -> None:
        b = self.bridge
        acct = b.account_key
        rows = self.db.query("SELECT * FROM managed_positions WHERE state='OPEN' AND mode IN ('AUTO_DEMO','AUTO_LIVE') AND account_key=?",
                             (acct,))
        with b._lock:
            if b.account_key != acct:
                return                                      # w2: account switched meanwhile - the lists below are another account's
            positions = {p["ticket"]: p for p in b.positions}
            deals = list(b.deals)
            deals_at = b.deals_loaded_at
        self._settle_unsettled(acct, positions, deals, deals_at)
        if not rows:
            return
        q = b.quote_status()
        for mp in rows:
            p = positions.get(mp["position_ticket"])
            if p is None:
                # w2 (I0711/I0793, hunk f2ed7c2): no settlement before the deal history of THIS account is loaded (after an account
                # switch / at start the lists were empty or another account's and an open position was marked CLOSED_UNSETTLED)
                if deals_at is not None:
                    self._settle_mt5(mp, deals, deals_at)
                continue
            if "missing" in self._note(mp):                 # w2 (I0711): the position is back in the terminal - the wait starts over
                note = self._note(mp)
                note.pop("missing", None)
                self._save_note(mp, note)
            vol_now = float(p.get("volume") or 0)
            self._reconcile_partial(mp, vol_now)
            if abs(vol_now - mp["volume_open"]) > 1e-9:
                self.db.execute("UPDATE managed_positions SET volume_open=? WHERE position_key=?", (vol_now, mp["position_key"]))
                mp["volume_open"] = vol_now
            if mp["adopted"]:
                continue                                    # adopted manual positions: settlement / close on request only
            pol = self._policy(mp)
            self._sync_broker_tp(mp, p, pol)
            if not q:
                continue
            if self._time_exit_due(mp, pol):
                self._time_exit_mt5(mp, p)
                continue
            tg = pol.get("targets") or []
            k = int(mp.get("targets_done") or 0)
            pending = mp.get("tp1_state") in ("REQUESTED", "UNKNOWN")
            if not pending and k < len(tg) - 1 and self._reached(mp["side"], q, tg[k]["price"]):
                self._partial_close(mp, p, pol, k)
            if pol.get("be_after_tp1") and not mp["be_done"] and self._be_allowed(mp):
                self._move_be(mp, p)

    def _reconcile_partial(self, mp: dict, vol_now: float) -> None:
        """REQUESTED / UNKNOWN partial exits are resolved from the terminal's position volume - never by re-sending."""
        st = mp.get("tp1_state")
        if st not in ("REQUESTED", "UNKNOWN"):
            return
        note = self._note(mp)
        cur = next((x for x in reversed(note.get("partials", [])) if x.get("state") in ("REQUESTED", "UNKNOWN")), None)
        if cur is None:
            return
        if vol_now <= cur["volume_before"] - cur["volume"] + 1e-9:
            cur["state"], cur["confirmed_by"] = "CONFIRMED", "TERMINAL_VOLUME"
            self._finish_partial(mp, note, cur, "CONFIRMED")
            self.log.info("EXECUTION", "TP_PARTIAL_RECONCILED", f"Częściowe wyjście potwierdzone stanem pozycji w terminalu (pozycja {mp['position_ticket']}).")
            return
        req_at = parse_iso(cur["at"])
        loaded = self.bridge.deals_loaded_at
        if loaded and loaded > req_at + timedelta(seconds=90) and utcnow() > req_at + timedelta(seconds=90):
            cur["state"] = "NOT_FOUND_CHECK_TERMINAL"
            self._finish_partial(mp, note, cur, "REJECTED")
            self.log.error("EXECUTION", "TP_PARTIAL_NOT_FOUND", "Częściowe wyjście nie zmieniło wolumenu pozycji – sprawdź terminal. Brak ponownego wysłania.")

    def _finish_partial(self, mp: dict, note: dict, cur: dict, state: str) -> None:
        k = int(cur["i"]) + 1
        self._save_note(mp, note)
        self.db.execute("UPDATE managed_positions SET tp1_state=?, targets_done=?, tp1_done=1 WHERE position_key=?", (state, k, mp["position_key"]))
        mp["tp1_state"], mp["targets_done"], mp["tp1_done"] = state, k, 1

    def _partial_close(self, mp: dict, p: dict, pol: dict, k: int) -> None:
        info = self.bridge.symbol_info or {}
        cfg = self.cfg_store.get()
        note = self._note(mp)
        note.setdefault("partials", [])
        vol = exit_policy.partial_volume(pol, k, mp["volume_initial"], mp["volume_open"], float(info.get("volume_step") or 0.01),
                                         float(info.get("volume_min") or 0.01))
        now = iso(utcnow())
        if vol <= 0:
            rec = {"i": k, "state": "SKIPPED_VOLUME", "volume": 0.0, "at": now}
            note["partials"].append(rec)
            self._finish_partial(mp, note, rec, "SKIPPED_VOLUME")
            self.log.info("EXECUTION", "TP_PARTIAL_SKIPPED", f"Cel {k + 1} osiągnięty – wolumen za mały na częściowe zamknięcie; reszta czeka na kolejny cel / SL.")
            return
        sym, ticket, side = mp["symbol"], mp["position_ticket"], mp["side"]
        rec = {"i": k, "state": "REQUESTED", "volume": vol, "volume_before": float(mp["volume_open"]), "at": now}
        note["partials"].append(rec)
        # persisted BEFORE sending as REQUESTED (a crash after sending is reconciled from the terminal, never re-sent)
        self._save_note(mp, note)
        self.db.execute("UPDATE managed_positions SET tp1_state='REQUESTED', tp1_requested_at=?, tp1_volume=? WHERE position_key=?",
                        (now, vol, mp["position_key"]))
        mp["tp1_state"] = "REQUESTED"

        def req(m):
            t = m.symbol_info_tick(sym)
            return {"action": m.TRADE_ACTION_DEAL, "symbol": sym, "volume": vol, "position": ticket,
                    "type": m.ORDER_TYPE_SELL if side == "BUY" else m.ORDER_TYPE_BUY, "price": t.bid if side == "BUY" else t.ask,
                    "deviation": int(cfg.execution.deviation_points), "magic": int(cfg.mt5.magic_number), "comment": f"MQ:TP{k + 1}",
                    "type_time": m.ORDER_TIME_GTC, "type_filling": m.ORDER_FILLING_FOK if int(info.get("filling_mode") or 0) & 1 else m.ORDER_FILLING_IOC}
        try:
            r = self.bridge.raw_call(lambda m: m.order_send(req(m)), PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
        except MT5CallTimeout:
            rec["state"] = "UNKNOWN"
            self._save_note(mp, note)
            self.db.execute("UPDATE managed_positions SET tp1_state='UNKNOWN' WHERE position_key=?", (mp["position_key"],))
            mp["tp1_state"] = "UNKNOWN"
            self.log.error("EXECUTION", "TP_PARTIAL_UNKNOWN", "Brak odpowiedzi przy częściowym zamknięciu – stan UNKNOWN, rekonsyliacja z terminalem (bez ponownego wysłania).")
            return
        except Exception as exc:  # noqa: BLE001 - F-08: refused before sending (Lock / worker) -> handled as a rejection
            from types import SimpleNamespace
            r = SimpleNamespace(retcode=-1, volume=0, comment=type(exc).__name__)
        rc = getattr(r, "retcode", None) if r is not None else None
        if rc in (10009, 10010) and (getattr(r, "volume", None) or 0) > 0:
            rec.update(state="CONFIRMED", volume=float(r.volume), retcode=rc, confirmed_by="ORDER_SEND_RESULT")
            self._finish_partial(mp, note, rec, "CONFIRMED")
            self.log.info("EXECUTION", "TP_PARTIAL", f"Cel {k + 1}: zamknięto częściowo {r.volume} lota pozycji {ticket}.")
        elif rc == 10008 or r is None:
            rec["state"] = "REQUESTED" if rc == 10008 else "UNKNOWN"
            self._save_note(mp, note)
            self.db.execute("UPDATE managed_positions SET tp1_state=? WHERE position_key=?", (rec["state"], mp["position_key"]))
            mp["tp1_state"] = rec["state"]
        else:
            rec.update(state="REJECTED", retcode=rc)
            self._finish_partial(mp, note, rec, "REJECTED")
            self.log.warn("EXECUTION", "TP_PARTIAL_REJECTED", f"Częściowe zamknięcie (cel {k + 1}) odrzucone: {RETCODES.get(rc, rc)} – SL na BE NIE zostanie przesunięty.")

    def _sync_broker_tp(self, mp: dict, p: dict, pol: dict) -> None:
        """RR_FROM_FILL plans (S11): the broker TP sent with the order was computed from the quote at the decision; after the
        fill it is moved ONCE to fill +- rr x risk (the strategy's definition). One attempt, recorded; SL unchanged.

        w2 (I0778): the target is aligned to the tick grid like the entry's TP (align_stops: BUY up, SELL down - the broker refused an
        off-grid price with INVALID_STOPS) and the SL of the request is the CURRENT SL read from the terminal in the same worker call
        (never the 2 s old list: a SL just moved in the terminal is not overwritten); a position with a planned SL that shows no SL in
        the terminal is not touched (sl=0 would remove the stop)."""
        if pol.get("tp_rule") != "RR_FROM_FILL" or not pol.get("targets"):
            return
        note = self._note(mp)
        if note.get("tp_sync"):
            return
        info = self.bridge.symbol_info or {}
        want = align_stops(info, mp["side"], 0.0, float(pol["targets"][-1]["price"]))[1]
        point = float(info.get("point") or 0.01)
        if abs((p.get("tp") or 0.0) - want) < point / 2:
            note["tp_sync"] = "NOT_NEEDED"
            self._save_note(mp, note)
            return
        cfg = self.cfg_store.get()
        ticket = mp["position_ticket"]
        planned_sl = bool(mp.get("sl"))
        note["tp_sync"] = "REQUESTED"
        self._save_note(mp, note)

        def send(m):
            cur = m.positions_get(ticket=ticket)
            pos = cur[0] if cur else None
            if pos is None:
                return "POSITION_NOT_FOUND"
            sl_now = float(getattr(pos, "sl", 0.0) or 0.0)
            if planned_sl and sl_now <= 0:
                return "SL_MISSING_IN_TERMINAL"
            return m.order_send({"action": m.TRADE_ACTION_SLTP, "symbol": mp["symbol"], "position": ticket,
                                 "sl": sl_now, "tp": want, "magic": int(cfg.mt5.magic_number)})
        try:
            r = self.bridge.raw_call(send, PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
            if isinstance(r, str):
                note["tp_sync"] = f"NOT_SENT_{r}"
                self.log.write("WARNING", "EXECUTION", "TP_SYNC_NOT_SENT", f"TP pozycji {ticket} nie zsynchronizowany: {r} (bez zmian w terminalu).")
            else:
                note["tp_sync"] = "DONE" if getattr(r, "retcode", None) in (10008, 10009) else f"REJECTED_{getattr(r, 'retcode', None)}"
        except MT5CallTimeout:
            note["tp_sync"] = "UNKNOWN"
        except Exception as exc:  # noqa: BLE001 - F-08
            note["tp_sync"] = f"REFUSED_{type(exc).__name__}"
        self._save_note(mp, note)
        if note["tp_sync"] == "DONE":            # 1.46: the stored TP follows the broker - not written after REJECTED / UNKNOWN / REFUSED
            self.db.execute("UPDATE managed_positions SET tp2=? WHERE position_key=?", (want, mp["position_key"]))

    TIME_EXIT_MAX_TRIES = 6                     # w2 (I0779): rejected time exits (except MARKET_CLOSED) - like the BE retries
    TIME_EXIT_MARKET_CLOSED_S = 300.0           # MARKET_CLOSED: retried every 5 min while the position exists
    TIME_EXIT_UNKNOWN_WAIT = timedelta(seconds=90)

    def _time_exit_mt5(self, mp: dict, p: dict) -> None:
        """Time exit = a close of THIS ticket (position=ticket, opposite side, the current volume; MT5 refuses a vanished position or a
        larger volume - it can never open or reverse a position).

        w2 (I0779): was one request per position - a REJECTED (market closed at the weekend, requote) or UNKNOWN answer left the
        position open past its plan for good. Now (state in exit_note.time_exit, next attempt time in UTC - survives a restart):
        REJECTED_* retried with back-off min(300, 5 x 2^(n-1)) s, at most TIME_EXIT_MAX_TRIES sends; REJECTED_MARKET_CLOSED every
        300 s while the position exists; UNKNOWN only once more and only when a deal history loaded > 90 s after the request still
        shows the same ticket with the same volume. DONE / POSITION_CLOSED end it. Positions settled before w2 with the old string
        state: only a REJECTED_* one is retried (an old UNKNOWN / REQUESTED is never repeated)."""
        note = self._note(mp)
        te = note.get("time_exit")
        now = self._bridge_now()
        if isinstance(te, str):
            if not te.startswith("REJECTED_") or te == "REJECTED_POSITION_CLOSED":
                return                                      # pre-w2 DONE / UNKNOWN / REQUESTED: never repeated
            te = {"state": "REJECTED", "n": 1, "last": te, "next_at": iso(now)}
        elif not isinstance(te, dict):
            te = {"state": "NEW", "n": 0}
        st = te.get("state")
        if st in ("DONE", "GAVE_UP", "POSITION_CLOSED"):
            return
        if st in ("UNKNOWN", "REQUESTED"):
            loaded = self.bridge.deals_loaded_at
            if not (te.get("at") and loaded and loaded > parse_iso(te["at"]) + self.TIME_EXIT_UNKNOWN_WAIT
                    and abs(float(p.get("volume") or 0) - float(te.get("volume") or -1)) < 1e-9):
                return                                      # not reconciled yet (or the volume changed - something was executed)
            if int(te.get("unknown_retries") or 0) >= 1:
                self._time_exit_gave_up(mp, note, te, "UNKNOWN")
                return
            te["unknown_retries"] = int(te.get("unknown_retries") or 0) + 1
        elif st == "REJECTED":
            if te.get("next_at") and now < parse_iso(te["next_at"]):
                return
            if te.get("last") != "REJECTED_MARKET_CLOSED" and int(te.get("n") or 0) >= self.TIME_EXIT_MAX_TRIES:
                self._time_exit_gave_up(mp, note, te, te.get("last"))
                return
        n = int(te.get("n") or 0) + 1
        te.update(state="REQUESTED", n=n, at=iso(now), volume=float(p.get("volume") or 0), next_at=None)
        note["time_exit"] = te
        self._save_note(mp, note)                           # persisted BEFORE sending (a crash after sending = UNKNOWN rules)
        res = self._close_mt5(mp, p, "MQ:TIME")
        te["last"] = res
        if res == "DONE":
            te["state"] = "DONE"
        elif res == "UNKNOWN":
            te["state"] = "UNKNOWN"
        elif res == "REJECTED_POSITION_CLOSED":
            te["state"] = "POSITION_CLOSED"
        else:
            te["state"] = "REJECTED"
            delay = self.TIME_EXIT_MARKET_CLOSED_S if res == "REJECTED_MARKET_CLOSED" else min(300.0, 5.0 * 2 ** (n - 1))
            te["next_at"] = iso(now + timedelta(seconds=delay))
        note["time_exit"] = te
        self._save_note(mp, note)
        if n == 1:
            self.log.info("EXECUTION", "TIME_EXIT", f"Wyjście czasowe pozycji {mp['position_ticket']}: {res}")
        else:
            self.log.write("WARNING", "EXECUTION", "TIME_EXIT_RETRY", f"Wyjście czasowe pozycji {mp['position_ticket']} - próba {n}: {res}")

    def _time_exit_gave_up(self, mp: dict, note: dict, te: dict, last) -> None:
        te["state"] = "GAVE_UP"
        note["time_exit"] = te
        self._save_note(mp, note)
        self.log.write("WARNING", "EXECUTION", "TIME_EXIT_GAVE_UP",
                       f"Wyjście czasowe pozycji {mp['position_ticket']} nie wykonane po {te.get('n')} próbach ({last}) – zamknij ręcznie w terminalu.")

    def _close_mt5(self, mp: dict, p: dict, comment: str) -> str:
        cfg = self.cfg_store.get()
        info = self.bridge.symbol_info or {}

        def req(m):
            t = m.symbol_info_tick(mp["symbol"])
            return {"action": m.TRADE_ACTION_DEAL, "symbol": mp["symbol"], "volume": float(p["volume"]), "position": p["ticket"],
                    "type": m.ORDER_TYPE_SELL if mp["side"] == "BUY" else m.ORDER_TYPE_BUY, "price": t.bid if mp["side"] == "BUY" else t.ask,
                    "deviation": int(cfg.execution.deviation_points), "magic": int(cfg.mt5.magic_number), "comment": comment,
                    "type_time": m.ORDER_TIME_GTC, "type_filling": m.ORDER_FILLING_FOK if int(info.get("filling_mode") or 0) & 1 else m.ORDER_FILLING_IOC}
        try:
            r = self.bridge.raw_call(lambda m: m.order_send(req(m)), PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
        except MT5CallTimeout:
            return "UNKNOWN"
        except Exception as exc:  # noqa: BLE001 - F-08: Lock / worker refused before sending
            return f"REJECTED_{type(exc).__name__}"
        rc = getattr(r, "retcode", None) if r is not None else None
        return "DONE" if rc in (10008, 10009, 10010) else ("UNKNOWN" if r is None else f"REJECTED_{RETCODES.get(rc, rc)}")

    def _move_be(self, mp: dict, p: dict) -> None:
        info = self.bridge.symbol_info or {}
        point = float(info.get("point") or 0)
        stops = (info.get("trade_stops_level") or 0) * point
        freeze = (info.get("trade_freeze_level") or 0) * point
        q = self.bridge.quote_status()
        if not q:
            return
        be = snap_tick(info, mp["entry_price"], "up" if mp["side"] == "BUY" else "down")   # F-05: on the tick grid, never worse
        cur_sl = p.get("sl") or 0
        better = (be > cur_sl) if mp["side"] == "BUY" else (cur_sl == 0 or be < cur_sl)
        ref = q["bid"] if mp["side"] == "BUY" else q["ask"]
        if not better:
            self.db.execute("UPDATE managed_positions SET be_done=1 WHERE position_key=?", (mp["position_key"],))
            return
        if abs(ref - be) < max(stops, freeze):
            return  # too close to the market (stops/freeze level) - retry next tick
        # F-06: bounded retries with back-off (was: a new SLTP request every second after a rejection)
        st = self._be_tries.setdefault(mp["position_key"], {"n": 0, "next": 0.0, "warned": False})
        if time.monotonic() < st["next"]:
            return
        if st["n"] >= 6:
            if not st["warned"]:
                st["warned"] = True
                self.log.warn("EXECUTION", "SL_TO_BE_GAVE_UP", f"BE dla pozycji {mp['position_ticket']} odrzucony {st['n']}× – ustaw ręcznie w terminalu.")
            return
        st["n"] += 1
        st["next"] = time.monotonic() + min(300.0, 5.0 * 2 ** (st["n"] - 1))
        cfg = self.cfg_store.get()
        ticket, tp = mp["position_ticket"], p.get("tp") or 0.0
        try:
            r = self.bridge.raw_call(lambda m: m.order_send({"action": m.TRADE_ACTION_SLTP, "symbol": mp["symbol"], "position": ticket,
                                                              "sl": float(be), "tp": float(tp), "magic": int(cfg.mt5.magic_number)}),
                                     PRIO_TRADE, timeout=cfg.execution.order_timeout_seconds)
            if getattr(r, "retcode", None) in (10008, 10009):
                self.db.execute("UPDATE managed_positions SET be_done=1, sl=? WHERE position_key=?", (be, mp["position_key"]))
                self.log.info("EXECUTION", "SL_TO_BE", f"SL przesunięty na cenę wejścia ({be}) dla pozycji {ticket} (BE cenowe – prowizja i swap nadal obciążają wynik).")
        except MT5CallTimeout:
            self.log.error("EXECUTION", "SL_TO_BE_UNKNOWN", "Brak odpowiedzi przy przesunięciu SL na BE – sprawdź terminal.")
        except Exception as exc:  # noqa: BLE001 - Lock flipped / worker down: nothing sent, retried with back-off
            self.log.warn("EXECUTION", "SL_TO_BE_REFUSED", f"Przesunięcie SL na BE nie wysłane: {type(exc).__name__}")

    # ------------------------------------------------------------ settlement (w2: I0711 / I0712 / I0726 / I0793)
    SETTLE_LIMIT = timedelta(minutes=10)        # incomplete history / no deal at all: decided only this long after the position vanished
    OFFSET_WAIT = timedelta(minutes=5)          # unknown server offset: closed_at = observed disappearance after this long
    UNSETTLED_RELOAD = timedelta(seconds=60)    # CLOSED_UNSETTLED needs a deal reload at least this long after the disappearance

    def _bridge_now(self):
        fn = getattr(self.bridge, "now", None)
        return fn() if callable(fn) else utcnow()

    def _settle_mt5(self, mp: dict, deals: list[dict], deals_at=None, *, unsettled: bool = False) -> None:
        """Settle a position that is no longer in the terminal - only from a deal history loaded AFTER it vanished.

        w2: (I0711) the moment it vanished (`missing.first_missing_at`, bridge clock = the clock of deals_loaded_at) is stored in
        exit_note and a deal reload is requested (neutral: only the history poll timer); settlement needs deals_loaded_at > that
        moment and the closing volume >= the opening volume (IN deals of the position, else volume_initial). Past SETTLE_LIMIT and
        >= 2 reloads the available closing deals are settled anyway (HISTORY_INCOMPLETE). (I0712) CLOSED_UNSETTLED only when there
        is no closing deal at all SETTLE_LIMIT after the disappearance and a reload >= 60 s after it (was: 10 min after opened_at).
        (I0726) an unknown server offset is never taken as 0: the settlement waits up to OFFSET_WAIT, then closed_at = the observed
        disappearance (CLOSED_AT_OBSERVED). Nothing is sent to MT5; while waiting the row stays OPEN and is not managed."""
        now = self._bridge_now()
        note = self._note(mp)
        miss = note.get("missing") or {}
        if not miss.get("first_missing_at"):
            if unsettled:                               # rows marked CLOSED_UNSETTLED before w2: the marking time is the observation
                miss = {"first_missing_at": mp.get("closed_at") or iso(now), "reloads": 2, "last_deals_at": None}
            else:
                note["missing"] = {"first_missing_at": iso(now), "reloads": 0, "last_deals_at": iso(deals_at) if deals_at else None}
                self._save_note(mp, note)
                req = getattr(self.bridge, "request_deals_reload", None)
                if callable(req):
                    req()
                self.log.write("INFO", "EXECUTION", "POSITION_GONE_WAITING_FOR_HISTORY",
                               f"Pozycja {mp['position_ticket']} zniknęła z terminala – rozliczenie po wczytaniu historii transakcji.")
                return
        first = parse_iso(miss["first_missing_at"])
        if deals_at is None or deals_at <= first:
            return                                      # the deal list may predate the closing deal
        if not unsettled and miss.get("last_deals_at") != iso(deals_at):
            miss["reloads"] = int(miss.get("reloads") or 0) + 1
            miss["last_deals_at"] = iso(deals_at)
            note["missing"] = miss
            self._save_note(mp, note)
        late = now - first >= self.SETTLE_LIMIT
        mine = [d for d in deals if d.get("position_id") == mp["position_ticket"]]
        outs = [d for d in mine if d.get("entry") in (1, 2, 3)]
        if not outs:
            if not unsettled and late and deals_at > first + self.UNSETTLED_RELOAD:
                self.db.execute("UPDATE managed_positions SET state='CLOSED_UNSETTLED', closed_at=? WHERE position_key=?", (iso(utcnow()), mp["position_key"]))
                self.log.warn("EXECUTION", "CLOSED_UNSETTLED", f"Pozycja {mp['position_ticket']} zniknęła, brak transakcji w historii – sprawdź historię w terminalu.")
            return
        flags = []
        vol_in = sum(float(d.get("volume") or 0) for d in mine if d.get("entry") == 0) or float(mp.get("volume_initial") or 0)
        vol = sum(float(d.get("volume") or 0) for d in outs)
        if vol < vol_in - 1e-9:
            if not (late and (unsettled or int(miss.get("reloads") or 0) >= 2)):
                return                                  # e.g. only the TP1 partial is in the list - the final close is not loaded yet
            flags.append("HISTORY_INCOMPLETE")
        off = self.bridge.clock.offset
        if off is None:
            if now - first < self.OFFSET_WAIT:
                if not miss.get("offset_wait_logged"):
                    miss["offset_wait_logged"] = True
                    note["missing"] = miss
                    self._save_note(mp, note)
                    self.log.write("WARNING", "EXECUTION", "SETTLE_WAITS_FOR_SERVER_OFFSET",
                                   f"Pozycja {mp['position_ticket']}: rozliczenie czeka na pomiar przesunięcia czasu serwera.")
                return
            closed = first
            flags.append("CLOSED_AT_OBSERVED")
        else:
            closed = from_epoch(max(d["time"] for d in outs) - off)
        trade_id = f"{mp['mode']}-{mp['account_key']}-{mp['position_ticket']}"
        if unsettled and self.db.one("SELECT 1 AS x FROM trades WHERE trade_id=?", (trade_id,)):
            return                                      # w2 (I0712): an existing trades row is never overwritten (skipped)
        gross = sum(float(d.get("profit") or 0) for d in mine)
        comm = sum(float(d.get("commission") or 0) for d in mine)
        swap = sum(float(d.get("swap") or 0) for d in mine)
        fee = sum(float(d.get("fee") or 0) for d in mine)
        avg = sum(float(d["volume"]) * float(d["price"]) for d in outs) / vol if vol else None
        net = gross + comm + swap + fee
        cur = (self.bridge.account_status() or {}).get("currency")
        risk = mp.get("planned_risk_money")
        pol = json.loads(mp.get("exit_policy_json") or "null") or {}
        self.db.execute("""INSERT OR REPLACE INTO trades(trade_id, mode, source, account_key, position_ticket, decision_id, setup_id, strategy_id, symbol, side,
                           volume, entry_price, exit_price_avg, opened_at, closed_at, gross_pnl, commission, swap, fee, net_pnl, currency, planned_risk_money,
                           r_multiple, deals_json, status, exit_policy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (trade_id, mp["mode"], "BOT" if not mp["adopted"] else "ADOPTED",
                         mp["account_key"], mp["position_ticket"], mp["decision_id"], mp["setup_id"], mp["strategy_id"], mp["symbol"], mp["side"],
                         vol, mp["entry_price"], avg, mp["opened_at"], iso(closed), round(gross, 2), round(comm, 2), round(swap, 2), round(fee, 2),
                         round(net, 2), cur, risk, round(net / risk, 3) if risk else None, dumps(mine), "CLOSED", pol.get("version")))
        if flags:                                       # trades.deals_json keeps its list format; the flags live in the position note
            miss["settle_flags"] = flags
            note["missing"] = miss
            self._save_note(mp, note)
        self.db.execute("UPDATE managed_positions SET state='CLOSED', volume_open=0, closed_at=? WHERE position_key=?", (iso(closed), mp["position_key"]))
        self.log.info("EXECUTION", "SETTLED", f"Pozycja {mp['position_ticket']} rozliczona: netto {round(net, 2)} {cur or ''}"
                      + (f" ({', '.join(flags)})" if flags else ""))
        self.bus.publish("trade_settled", {"position": mp["position_ticket"], "net": round(net, 2)})

    def _settle_unsettled(self, acct: str | None, positions: dict, deals: list[dict], deals_at) -> None:
        """w2 (I0712): CLOSED_UNSETTLED rows of this account are settled when their closing deals appear in a NEW deal history (same
        rules as _settle_mt5). Never restored to OPEN, never managed, nothing sent; a ticket back in the terminal is only reported."""
        if deals_at is None or acct is None or self._unsettled_seen == (acct, deals_at):
            return
        self._unsettled_seen = (acct, deals_at)
        rows = self.db.query("SELECT * FROM managed_positions WHERE state='CLOSED_UNSETTLED' AND mode IN ('AUTO_DEMO','AUTO_LIVE') AND account_key=?",
                             (acct,))
        for mp in rows:
            if mp["position_ticket"] in positions:
                if mp["position_key"] not in self._unsettled_alerted:
                    self._unsettled_alerted.add(mp["position_key"])
                    self.log.write("WARNING", "EXECUTION", "CLOSED_UNSETTLED_TICKET_IN_TERMINAL",
                                   f"Pozycja {mp['position_ticket']} oznaczona jako zamknięta bez rozliczenia jest znów widoczna w terminalu – "
                                   "nie jest zarządzana przez bota, sprawdź ją ręcznie.")
                continue
            self._settle_mt5(mp, deals, deals_at, unsettled=True)

    # ------------------------------------------------------------ PAPER
    def _manage_paper(self) -> None:
        rows = self.db.query("SELECT * FROM managed_positions WHERE state='OPEN' AND mode='PAPER'")
        if not rows:
            return
        q = self.bridge.quote_status()
        if not q or q.get("age_seconds") is None or q["age_seconds"] > self.cfg_store.get().mt5.max_quote_age_seconds:
            return
        info = self.bridge.symbol_info or {}
        for mp in rows:
            pol = self._policy(mp)
            buy = mp["side"] == "BUY"
            px = q["bid"] if buy else q["ask"]
            if mp["sl"] and ((buy and px <= mp["sl"]) or (not buy and px >= mp["sl"])):
                fill = min(px, mp["sl"]) if buy else max(px, mp["sl"])
                self.paper.close_part(mp, mp["volume_open"], fill, "SL" if not mp["be_done"] else "BE")
                self._paper_done(mp)
                continue
            if self._time_exit_due(mp, pol):
                self.paper.close_part(mp, mp["volume_open"], px, "TIME")
                self._paper_done(mp)
                continue
            tg = pol.get("targets") or []
            k = int(mp.get("targets_done") or 0)
            note = self._note(mp)
            note.setdefault("partials", [])
            while k < len(tg) and self._reached(mp["side"], q, tg[k]["price"]) and mp["volume_open"] > 1e-9:
                if k == len(tg) - 1:
                    self.paper.close_part(mp, mp["volume_open"], px, f"TP{k + 1}" if len(tg) > 1 else "TP")
                    self._paper_done(mp)
                    k += 1
                    break
                vol = exit_policy.partial_volume(pol, k, mp["volume_initial"], mp["volume_open"], float(info.get("volume_step") or 0.01),
                                                 float(info.get("volume_min") or 0.01))
                if vol > 0:
                    self.paper.close_part(mp, vol, px, f"TP{k + 1}")
                    note["partials"].append({"i": k, "state": "CONFIRMED", "volume": vol, "at": iso(utcnow()), "confirmed_by": "PAPER_FILL"})
                else:
                    note["partials"].append({"i": k, "state": "SKIPPED_VOLUME", "volume": 0.0, "at": iso(utcnow())})
                k += 1
                self._save_note(mp, note)
                self.db.execute("UPDATE managed_positions SET targets_done=?, tp1_done=1, tp1_state=? WHERE position_key=?",
                                (k, note["partials"][-1]["state"], mp["position_key"]))
                mp["targets_done"] = k
                if k == 1 and pol.get("be_after_tp1") and not mp["be_done"]:
                    self.db.execute("UPDATE managed_positions SET sl=?, be_done=1 WHERE position_key=?", (mp["entry_price"], mp["position_key"]))
                    mp["sl"], mp["be_done"] = mp["entry_price"], 1
                    self.log.info("PAPER", "SL_TO_BE", f"PAPER: SL na cenę wejścia {mp['entry_price']} (prowizja nadal obciąża wynik)")

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
            if pa.get("equity") is None:
                return                          # 1.46: incomplete PAPER valuation (no quote / P&L unknown) is not stored as equity
            self.db.execute("INSERT INTO equity_snapshots(ts, mode, account_key, balance, equity, margin, free_margin, currency) VALUES (?,?,?,?,?,?,?,?)",
                            (now, "PAPER", None, pa["balance"], pa["equity"], None, None, pa["currency"]))

    # ------------------------------------------------------------ user operations
    def close_positions(self, scope: str, ticket: int | None = None) -> dict:
        """Explicit, confirmed close of positions managed by this app (separate from 'stop new entries')."""
        b = self.bridge
        cfg = self.cfg_store.get()
        rows = self.db.query("SELECT * FROM managed_positions WHERE state='OPEN'" + (" AND position_ticket=?" if ticket else ""), (ticket,) if ticket else ())
        done, errors = [], []
        paper_rows = []
        for mp in rows:
            if mp["mode"] == "PAPER":
                paper_rows.append(mp)           # 1.46: closed below under the manager lock (account positions never wait for it)
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
            except Exception as exc:  # noqa: BLE001 - F-08
                errors.append({"ticket": p["ticket"], "error": type(exc).__name__})
        if paper_rows:
            self._close_paper(paper_rows, cfg, done, errors)
        self.log.warn("EXECUTION", "CLOSE_REQUEST", f"Zamknięcie pozycji ({scope}): wykonane {len(done)}, błędy {len(errors)}")
        return {"closed": done, "errors": errors}

    def _close_paper(self, rows: list[dict], cfg, done: list, errors: list) -> None:
        """1.46: PAPER closes run under the manager lock, serialized with the tick (a PAPER position was closed - and booked - twice);
        the row and the quote are read under the lock. PAPER only: MT5 closes of account positions stay unlocked, as in 1.45."""
        with self._lock:
            q = self.bridge.quote_status()
            for row in rows:
                mp = self.db.one("SELECT * FROM managed_positions WHERE position_key=? AND state='OPEN'", (row["position_key"],))
                if mp is None:
                    continue                    # closed by the tick meanwhile
                # 1.46: no quote / a stale quote is reported (was: skipped silently - "0 done, 0 errors" with the position still open)
                if not q or q.get("age_seconds") is None or q["age_seconds"] > cfg.mt5.max_quote_age_seconds:
                    errors.append({"ticket": mp["position_ticket"], "error": "NO_QUOTE" if not q else "QUOTE_STALE"})
                    continue
                self.paper.close_part(mp, mp["volume_open"], q["bid"] if mp["side"] == "BUY" else q["ask"], "MANUAL_CLOSE")
                done.append(mp["position_ticket"])

    def adopt(self, ticket: int) -> dict:
        b = self.bridge
        p = next((x for x in b.positions if x["ticket"] == ticket), None)
        if not p:
            return {"ok": False, "error": "POSITION_NOT_FOUND"}
        try:                                                    # one owner per position: SCALPING/HEDGING positions are never adopted
            from ..sh import config as _shc
            sh_owned = self.db.one("SELECT 1 FROM sh_owners WHERE account_key=? AND position_ticket=?", (b.account_key, int(ticket)))
            if sh_owned or int(p.get("magic") or 0) == int(_shc.load()["magic_number"]):
                return {"ok": False, "error": "POSITION_OWNED_BY_SH_STRATEGY"}
        except Exception:  # noqa: BLE001 - the ownership check must never break adoption of manual positions
            pass
        # w2 (I0781): a position this app already manages is never adopted (a second OPEN row: two close requests for one ticket,
        # trades overwritten with source ADOPTED); a re-adoption of an adopted one stays idempotent. Read only - no row is changed.
        ex = self.db.one("SELECT position_key, adopted FROM managed_positions WHERE account_key=? AND position_ticket=? AND state='OPEN'",
                         (b.account_key, int(ticket)))
        if ex:
            return {"ok": True} if ex["adopted"] else {"ok": False, "error": "POSITION_ALREADY_MANAGED"}
        if int(p.get("magic") or 0) == int(self.cfg_store.get().mt5.magic_number):
            pend = self.db.query("SELECT client_tag FROM order_attempts WHERE state IN ('SENDING','UNKNOWN') AND account_key=?", (b.account_key,))
            if any(a.get("client_tag") and str(p.get("comment") or "").startswith(a["client_tag"]) for a in pend):
                return {"ok": False, "error": "POSITION_PENDING_RECONCILIATION"}    # the bot's own order, not reconciled yet
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


__all__ = ["PositionManager"]          # 1.46: unused re-export of engine.lifecycle.TERMINAL removed
