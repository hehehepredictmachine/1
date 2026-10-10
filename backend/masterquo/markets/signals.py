"""Bot signals - CONFIRMED setups of the MasterQUO strategies S01-S10, on every market.

Sources (both run the same strategy code, thresholds, parameters and per-strategy switches as the bot):
  MAIN     - the bot's own engine on the main symbol (ActiveEngine events NEW_CONFIRMED / STAGE_CONFIRMED);
  SCANNER  - the market scanner runs S01-S10 on each other scanned symbol (M5/M15/H1/H4/D1 bars from the terminal).

A signal = direction, entry at the confirmation price (Ask for BUY, Bid for SELL - the strategies' plan is
MARKET_ON_CONFIRMATION), the strategy's stop loss and targets. Deterministic checks: stop/targets on the right side,
price not further from the trigger than the plan's max_distance_atr, weighted R:R of the strategy's targets (gross, the
same weights the bot's risk engine uses) >= the bot's own `risk.rr_block_below`, spread <= 50% of the risk. One signal per setup and per market event (several strategies describing the same move -> one signal).
Signals are tracked on M15 Bid bars (WIN / LOSS / TIMEOUT); a same-bar SL+TP touch counts as a loss.
Only the main symbol can be traded, and only through the unchanged execution path (modes, risk engine, gateway);
signals of other markets are information for the user.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import timedelta

from ..db.database import dumps
from ..strategies import adapter, registry
from ..timeutil import iso, parse_iso, utcnow

log = logging.getLogger("masterquo.signals")
OPEN_STATES = ("OPEN",)
SIGNAL_EVENTS = ("NEW_CONFIRMED", "STAGE_CONFIRMED")
STRATEGY_TFS = {"M5": 400, "M15": 400, "H1": 400, "H4": 300, "D1": 420}


# ---------------------------------------------------------------------------------------------- validation
def validate(rec: dict, bid: float | None, ask: float | None, atr_setup: float | None, min_rr: float) -> dict:
    """min_rr = the bot's risk.rr_block_below; R:R = sum(weight x reward) / risk over the strategy's targets (gross)."""
    """Checks of a CONFIRMED setup turned into a market signal. Returns {ok, reasons, entry, risk, rr}."""
    reasons = []
    if bid is None or ask is None:
        return {"ok": False, "reasons": ["NO_QUOTE"], "rr": []}
    long = rec["direction"] == "LONG"
    entry = ask if long else bid
    sl = rec.get("stop_loss")
    tps = [t["price"] for t in (rec.get("targets") or []) if t.get("price") is not None]
    if sl is None:
        return {"ok": False, "reasons": ["NO_STOP_LOSS"], "rr": [], "entry": entry}
    if not tps:
        reasons.append("NO_VALID_TARGET")
    risk = (entry - sl) if long else (sl - entry)
    if risk <= 0:
        reasons.append("PRICE_ALREADY_BEYOND_STOP")
    if any((t <= entry) if long else (t >= entry) for t in tps):
        reasons.append("PRICE_ALREADY_BEYOND_TARGET")
    ep = rec.get("entry_plan") or {}
    lvl = ep.get("trigger_level") or ep.get("reference_price")
    md = ep.get("max_distance_atr")
    if lvl is not None and md and atr_setup and ((entry - lvl) if long else (lvl - entry)) > md * atr_setup:
        reasons.append("PRICE_RAN_AWAY_FROM_TRIGGER")
    rr = [round(abs(t - entry) / risk, 2) for t in tps] if risk > 0 else []
    ws = [float(t.get("weight") or 0) for t in (rec.get("targets") or []) if t.get("price") is not None]
    rr_w = round(sum(w * x for w, x in zip(ws, rr)) / sum(ws), 2) if rr and sum(ws) > 0 else (rr[0] if rr else None)
    if min_rr and rr_w is not None and rr_w < min_rr and not reasons:
        reasons.append(f"RR_BELOW_BOT_LIMIT_{min_rr:g}")
    if risk > 0 and (ask - bid) > 0.5 * risk:
        reasons.append("SPREAD_TOO_LARGE_VS_RISK")
    return {"ok": not reasons, "reasons": reasons, "rr": rr, "rr_weighted": rr_w, "entry": entry, "risk": risk if risk > 0 else None}


# ---------------------------------------------------------------------------------------------- tracking
def evaluate(sig: dict, bars: list[dict], now_iso: str, max_hold_hours: int) -> dict | None:
    """Advance an OPEN signal on closed M15 Bid bars opening at/after the signal. Returns field updates or None.
    SL and TP in one bar = loss (order unknown). The last target closes as WIN, earlier targets are recorded in tp_hit.
    After max_hold_hours the signal is closed at the last close (TIMEOUT)."""
    if sig["status"] not in OPEN_STATES:
        return None
    long = sig["action"] == "BUY"
    entry, sl = sig["entry_price"], sig["stop_loss"]
    tps = json.loads(sig["take_profits_json"] or "[]")
    risk = abs(entry - sl)
    t0 = parse_iso(sig["created_at"])
    tp_hit = sig.get("tp_hit") or 0
    upd: dict = {}
    for b in sorted((b for b in bars if b.get("closed") and b.get("open_utc")), key=lambda b: b["open_utc"]):
        if parse_iso(b["open_utc"]) < t0:
            continue
        if (b["l"] <= sl) if long else (b["h"] >= sl):
            return {**upd, "status": "LOSS", "closed_at": b["open_utc"], "exit_price": sl, "outcome_r": -1.0, "tp_hit": tp_hit}
        hits = [i for i, t in enumerate(tps) if ((b["h"] >= t) if long else (b["l"] <= t))]
        if hits:
            k = max(hits)
            if k == len(tps) - 1:
                return {**upd, "status": "WIN", "closed_at": b["open_utc"], "exit_price": tps[k],
                        "outcome_r": round(abs(tps[k] - entry) / risk, 2) if risk else None, "tp_hit": k + 1}
            if k + 1 > tp_hit:
                tp_hit = k + 1
                upd["tp_hit"] = tp_hit
    if parse_iso(now_iso) - t0 >= timedelta(hours=max_hold_hours):
        last = next((b for b in reversed(bars) if b.get("closed")), None)
        if last:
            px = last["c"]
            r = ((px - entry) if long else (entry - px)) / risk if risk else None
            return {**upd, "status": "TIMEOUT", "closed_at": last["open_utc"], "exit_price": px, "outcome_r": None if r is None else round(r, 2)}
    return upd or None


def stats(rows: list[dict]) -> dict:
    done = [r for r in rows if r["status"] in ("WIN", "LOSS", "TIMEOUT")]
    wins = [r for r in done if r["status"] == "WIN" or (r["status"] == "TIMEOUT" and (r["outcome_r"] or 0) > 0)]
    losses = [r for r in done if r["status"] == "LOSS" or (r["status"] == "TIMEOUT" and (r["outcome_r"] or 0) < 0)]
    rs = [r["outcome_r"] for r in done if r["outcome_r"] is not None]
    return {"signals": len(rows), "rejected": sum(1 for r in rows if r["status"] == "REJECTED"),
            "open": sum(1 for r in rows if r["status"] in OPEN_STATES), "closed": len(done), "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(100 * len(wins) / (len(wins) + len(losses)), 1) if (wins or losses) else None,
            "avg_r": round(sum(rs) / len(rs), 2) if rs else None, "total_r": round(sum(rs), 2) if rs else None,
            "note": "Wynik liczony na świecach M15 (Bid), bez spreadu i prowizji; SL i TP w tej samej świecy = strata."}


# ---------------------------------------------------------------------------------------------- service
class BotSignalService:
    def __init__(self, cfg_store, bridge, db, bus, applog, telegram=None):
        self.cfg_store, self.bridge, self.db, self.bus, self.log, self.telegram = cfg_store, bridge, db, bus, applog, telegram
        self._lock = threading.RLock()

    @property
    def cfg(self):
        return self.cfg_store.get().signals

    # ------------------------------------------------------------ main symbol (bot engine)
    def on_main_events(self, events: list, view) -> None:
        if not self.cfg.enabled or view is None:
            return
        for kind, r in events:
            if kind in SIGNAL_EVENTS and r and r.get("record") and r.get("stage") == "CONFIRMED":
                rec = {**r["record"], "setup_id": r["setup_id"]}
                self.record(rec, view, source="MAIN")

    # ------------------------------------------------------------ other markets (scanner)
    def scan_symbol(self, symbol: str, bars: dict[str, list[dict]], quote: dict | None, meta: dict | None) -> dict:
        """Run S01-S10 on one scanned market; record CONFIRMED setups as signals. Returns a compact summary."""
        cfg = self.cfg_store.get()
        ac = cfg.active
        if not (self.cfg.enabled and self.cfg.scan_other_markets):
            return {"status": "DISABLED"}
        age = (quote or {}).get("age_seconds")
        status = "OK" if quote and age is not None and age <= max(cfg.mt5.max_quote_age_seconds, 30.0) else "STALE"
        view = adapter.build_view(symbol=symbol, bars_by_tf={tf: bars.get(tf) or [] for tf in STRATEGY_TFS}, bid=(quote or {}).get("bid"),
                                  ask=(quote or {}).get("ask"), point=(meta or {}).get("point"), as_of=iso(utcnow()),
                                  synthetic=self.bridge.synthetic, regime_params=ac.regime, data_status=status)
        if status != "OK":
            return {"status": "STALE_QUOTE", "regime": view.regime.get("state"), "setups": []}
        res = registry.scan(view, enabled={sid: t.scan for sid, t in ac.strategies.items()}, overrides=ac.params,
                            thresholds=ac.thresholds.model_dump(), account_key=self.bridge.account_key)
        for c in res["candidates"]:
            if c["stage"] == "CONFIRMED":
                self.record(c, view, source="SCANNER")
        order = {"CONFIRMED": 0, "EARLY": 1, "WATCH": 2}
        setups = sorted(({k: c.get(k) for k in ("strategy_id", "strategy_name", "direction", "timeframe", "stage", "setup_score", "setup_id")}
                         for c in res["candidates"]), key=lambda x: (order.get(x["stage"], 3), -(x["setup_score"] or 0)))
        return {"status": "OK", "regime": res.get("regime"), "setups": setups[:8],
                "strategies_ok": sum(1 for p in res["per_strategy"].values() if p["status"] == "OK")}

    # ------------------------------------------------------------ record
    def record(self, rec: dict, view, source: str) -> dict | None:
        symbol = view.symbol
        with self._lock:
            if self.db.one("SELECT 1 FROM ai_signals WHERE source='BOT' AND setup_id=?", (rec["setup_id"],)):
                return None                                  # one signal per setup
            ev = rec.get("event_id")
            if ev and self.db.one("SELECT 1 FROM ai_signals WHERE source='BOT' AND event_id=? AND status='OPEN'", (ev,)):
                return None                                  # several strategies, one market event -> one signal
            tfv = view.tfs.get(rec["timeframe"])
            atr = None
            if tfv is not None and len(tfv):
                atr = tfv.atr()[tfv.last]
            v = validate(rec, view.bid, view.ask, atr, self.cfg_store.get().risk.rr_block_below)
            now = utcnow()
            nowi = iso(now)
            sid = "BOT-" + uuid.uuid4().hex[:14]
            tps = [t["price"] for t in rec.get("targets") or []]
            st = "OPEN" if v["ok"] else "REJECTED"
            action = "BUY" if rec["direction"] == "LONG" else "SELL"
            entry = v.get("entry")
            detail = {k: rec.get(k) for k in ("strategy_version", "family", "regime", "horizon", "phase", "entry_plan", "invalidation_level",
                                              "invalidation_rule", "reason_codes", "missing_confirmations", "countertrend", "facts", "score",
                                              "exit_rules", "validation_status", "anchor_time", "source_time")}
            detail["validation"] = v
            self.db.execute("""INSERT INTO ai_signals(signal_id, created_at, updated_at, symbol, trigger, status, action, entry_type, entry_price,
                               stop_loss, take_profits_json, rr1, horizon, price_at_signal, validation_json, record_json, filled_at, fill_price,
                               account_key, synthetic, source, setup_id, event_id, strategy_id, strategy_name, timeframe, setup_score)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (sid, nowi, nowi, symbol, source, st, action, "MARKET", entry, rec.get("stop_loss"), json.dumps(tps),
                             v.get("rr_weighted"), rec.get("horizon"), view.bid, dumps(v), dumps(detail),
                             nowi if st == "OPEN" else None, entry if st == "OPEN" else None, self.bridge.account_key,
                             int(bool(view.synthetic)), "BOT", rec["setup_id"], ev, rec["strategy_id"], rec.get("strategy_name"),
                             rec["timeframe"], rec.get("setup_score")))
        out = self.get(sid)
        txt = (f"Sygnał bota {symbol}: {action} {rec['strategy_id']} {rec['timeframe']} wejście {entry} SL {rec.get('stop_loss')} TP {tps}"
               + (f" – odrzucony ({', '.join(v['reasons'])})" if st == "REJECTED" else ""))
        self.log.info("SIGNAL", st, txt, {"signal_id": sid, "setup_id": rec["setup_id"]})
        self.bus.publish("bot_signal", out)
        if st == "OPEN" and self.telegram is not None and self.cfg.telegram:
            try:
                self.telegram.notify(f"signal:{rec['setup_id']}", f"MasterQUO {'[DANE SYNTETYCZNE] ' if view.synthetic else ''}{txt}")
            except Exception:
                log.exception("telegram notify failed")
        return out

    # ------------------------------------------------------------ tracking
    def track(self) -> int:
        rows = self.db.query("SELECT * FROM ai_signals WHERE source='BOT' AND status='OPEN'")
        if not rows or self.bridge.state != "CONNECTED":
            return 0
        changed = 0
        by_symbol: dict[str, list[dict]] = {}
        for r in rows:
            by_symbol.setdefault(r["symbol"], []).append(dict(r))
        now = iso(utcnow())
        for sym, sigs in by_symbol.items():
            try:
                bars = self.bridge.symbol_bars(sym, "M15", 400)
            except Exception:
                continue
            for s in sigs:
                upd = evaluate(s, bars, now, self.cfg.max_hold_hours)
                if not upd:
                    continue
                upd["updated_at"] = now
                self.db.execute(f"UPDATE ai_signals SET {', '.join(f'{k}=?' for k in upd)} WHERE signal_id=?", (*upd.values(), s["signal_id"]))
                changed += 1
                out = self.get(s["signal_id"])
                if out["status"] != "OPEN":
                    self.log.info("SIGNAL", out["status"], f"Sygnał bota {sym} {out['action']} {out['strategy_id']} rozliczony: {out['status']}"
                                  + (f" ({out['outcome_r']:+.2f} R)" if out.get("outcome_r") is not None else ""))
                self.bus.publish("bot_signal", out)
        return changed

    # ------------------------------------------------------------ read API
    @staticmethod
    def _public(r) -> dict:
        d = dict(r)
        d["take_profits"] = json.loads(d.pop("take_profits_json") or "[]")
        d["validation"] = json.loads(d.pop("validation_json") or "null")
        d["detail"] = json.loads(d.pop("record_json") or "null") or {}
        d["synthetic"] = bool(d.get("synthetic"))
        for k in ("run_id", "model_id", "prompt_version", "confidence", "est_cost_usd", "valid_until"):
            d.pop(k, None)
        return d

    def get(self, signal_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM ai_signals WHERE signal_id=? AND source='BOT'", (signal_id,))
        return self._public(r) if r else None

    def list(self, symbol: str | None = None, limit: int = 50, include_rejected: bool = True) -> dict:
        syn = int(bool(self.bridge.synthetic))
        where, args = "source='BOT' AND synthetic=?", [syn]
        if symbol:
            where += " AND symbol=?"
            args.append(symbol)
        if not include_rejected:
            where += " AND status<>'REJECTED'"
        rows = self.db.query(f"SELECT * FROM ai_signals WHERE {where} ORDER BY created_at DESC LIMIT ?", (*args, limit))
        allr = self.db.query(f"SELECT status, action, outcome_r FROM ai_signals WHERE {where}", tuple(args))
        return {"items": [self._public(r) for r in rows], "stats": stats([dict(r) for r in allr])}

    def status(self) -> dict:
        c = self.cfg
        return {"enabled": c.enabled, "scan_other_markets": c.scan_other_markets, "rr_limit": self.cfg_store.get().risk.rr_block_below,
                "max_hold_hours": c.max_hold_hours}
