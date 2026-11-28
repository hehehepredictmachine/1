"""Services of the workflow v3.2 modules owned by the Runtime, not by the HTTP layer (1.46 arch I0088 / I0092).

Before 1.46 api/wf32_routes.register created these objects itself (a private lazy registry next to the Runtime), started the
'telegram-account' thread already while the routes were registered (before rt.start() and regardless of the licence lock) and
published the objects only through app.state.wf32 - the exporters returned APP_NOT_RUNNING without the HTTP app.

Now one ``Wf32Services`` per Runtime (rt.wf32_services, its dict rt.wf32 is the same object as app.state.wf32):

* lazy (no network call at construction): TraderLifeGame (tlg), Hyperliquid / Universe (hl, universe; the baskets' client is preferred),
  BAT encoder, the Telegram AccountCenter (acct);
* eager, in memory / one file: TradeLedger (+ its lock), the ASGE TrialLedger (append-only JSONL), the PT / DT shadow journal;
* the account loop (poll / queue_reports / flush every 10 s) is started by Runtime.start (after the licence unlock, real MT5 only, once)
  and ends with rt._stop.

None of these objects sends, modifies or closes an order: the AccountCenter only reads the account and its deals and sends Telegram
reports; the ledgers are analytical; Bootstrap is not here (rt.bootstrap, created in Runtime.__init__)."""
from __future__ import annotations

import collections
import logging
import threading
import time

from . import paths

log = logging.getLogger("masterquo.telegram_account")


class Wf32Services:
    def __init__(self, rt):
        from .apollo import asge as ASG
        from .orderflow.trades import TradeLedger
        self.rt = rt
        self._lock = threading.RLock()            # 1.46: re-entrant - the "universe" factory calls lazy("hl")
        self._svc: dict = {}
        self.ledger = TradeLedger(max_per_instrument=200_000)     # 1.46: bounded (the oldest events of an instrument are dropped first)
        self.ledger_lock = threading.Lock()                         # 1.46: one ledger, many request threads
        self.trials = ASG.TrialLedger(paths.data_dir() / "apollo" / "asge_trials.jsonl")      # 1.46: durable append-only ledger
        self.journal: collections.deque = collections.deque(maxlen=500)   # results of PT / DT calls since start (export: pt-skill, dt-ranker)
        self.acct_thread: threading.Thread | None = None
        # 1.46: the exporters (api/export_routes.py, exports/sources.py) read THESE objects - one ledger / journal, never a copy
        self.public = {"ledger": self.ledger, "trials": self.trials, "shadow_journal": self.journal, "hl": self.hl, "universe": self.universe,
                       "tlg": self.tlg, "acct": self.acct, "acct_roi": self.acct_roi}

    # ------------------------------------------------------------------ lazy registry
    def lazy(self, name, factory):
        with self._lock:
            if name not in self._svc:
                self._svc[name] = factory()
            return self._svc[name]

    def tlg(self):
        from .trader_life_game import GameService, ReadOnlyAccountView
        return self.lazy("tlg", lambda: GameService(paths.data_dir() / "trader_life_game",
                                                    ReadOnlyAccountView.from_bridge(getattr(self.rt, "bridge", None))))

    def hl(self):
        b = getattr(self.rt, "baskets", None)
        if b is not None and getattr(b, "hl", None) is not None:
            return b.hl
        from .baskets.hyperliquid import Hyperliquid
        return self.lazy("hl", Hyperliquid)

    def universe(self):
        from .markets import universe as MU
        return self.lazy("universe", lambda: MU.Universe(self.hl()))

    def bat(self):
        from .mm.bat_encoder import BATEncoder
        return self.lazy("bat", BATEncoder)

    # ------------------------------------------------------------------ TASK 017: Telegram account center (outbound only, OFF by default)
    def acct_roi(self, days: int) -> dict:
        rt = self.rt
        b = rt.bridge
        from . import stats as _ST
        # 1.46: deposits older than the deal history (deals_history_days) counted as profit -> deals + coverage from one atomic snapshot;
        # 1.46 arch (I0081): the same ROI function as GET /api/v1/stats
        snap = _ST.bridge_deals_snapshot(b)
        deals = snap[0]
        off = b.clock.offset
        r = _ST.account_roi_for_bridge(rt.db, b, days=days, snapshot=snap) or {}
        # 1.46: account_roi has no deals / net / currency keys - the report always showed "—". Net = equity change minus external flows
        # (same Modified-Dietz window), deals = trade deals in that window; unknown stays None ("—").
        net = deals_n = None
        if r.get("status") == "OK" and None not in (r.get("start_equity"), r.get("end_equity"), r.get("net_flows")):
            net = round(r["end_equity"] - r["start_equity"] - r["net_flows"], 2)
            from .timeutil import parse_iso as _pi
            t0, t1 = _pi(r["period_from"]).timestamp(), _pi(r["period_to"]).timestamp()
            deals_n = sum(1 for d in deals if d.get("type") in (0, 1) and off is not None and t0 < float(d.get("time") or 0) - off <= t1)
        cur = (b.account_status() or {}).get("currency") if hasattr(b, "account_status") else None
        return {"roi_pct": r.get("roi_pct"), "status": r.get("status") or ("OK" if r.get("roi_pct") is not None else "NO_DATA"),
                "deals": deals_n, "net": net, "currency": cur}

    @staticmethod
    def acct_deals_fn(b):
        """1.46: bridge.deals is [] until the first history poll and still holds the PREVIOUS account's deals after an account switch
        (connect() / _poll_account() do not clear it, a deal carries no account) - the Telegram baseline written from it replayed the
        whole history, and the other account's deals were reported as the pinned account's events. The list is tagged with the account
        it was loaded for (bridge "deals" notification, sent by _poll_deals in the bridge thread); None = NOT LOADED for this account."""
        tracked = hasattr(b, "add_listener")
        owner = {"key": None}
        if tracked:
            b.add_listener(lambda kind, data: owner.update(key=b.account_key) if kind == "deals" else None)

        def deals():
            # 1.46 arch (I0089): the same read under the bridge's lock, through the bridge (callers never take b._lock themselves)
            from .mt5.bridge import loaded_deals_copy
            return loaded_deals_copy(b, owner["key"], check_account=tracked)
        return deals

    def acct(self):
        from .notify.account_center import AccountCenter
        rt = self.rt

        def make():
            b = getattr(rt, "bridge", None)
            tg = getattr(rt, "telegram", None)
            magic = getattr(getattr(rt.cfg.get(), "mt5", None), "magic_number", None) if getattr(rt, "cfg", None) else None
            magics = [magic] if magic else []
            try:                                                   # 1.46: SH engine deals (own magic) are PMW_ENGINES too, not EXTERNAL_MAGIC
                from .sh import config as _SHC
                if _SHC.load().get("magic_number"):
                    magics.append(int(_SHC.load()["magic_number"]))
            except Exception:  # noqa: BLE001, S110 - no SH config: only the main magic (moved unchanged from api/wf32_routes.py)
                pass
            return AccountCenter(paths.data_dir() / "telegram_account", deliver=(tg.account_event if tg else None),
                                 deals_fn=self.acct_deals_fn(b) if b else None,
                                 account_fn=(lambda: b.account_status()) if b else None, pmw_magics=magics,
                                 roi_fn=self.acct_roi if b else None)
        return self.lazy("acct", make)

    def account_loop(self, stop: threading.Event | None = None) -> None:
        """poll / queue_reports / flush every 10 s until `stop` (rt._stop) is set. 1.46: ends with Runtime.stop() (was `while True`);
        each step on its own (a failing report no longer blocks the delivery of queued events), errors logged at most once per 10 min."""
        stop = stop if isinstance(stop, threading.Event) else getattr(self.rt, "_stop", None)
        last: dict = {}
        while not (stop.wait(10) if isinstance(stop, threading.Event) else (time.sleep(10) or False)):
            for step in ("poll", "queue_reports", "flush"):
                try:
                    getattr(self.acct(), step)()
                except Exception as exc:  # noqa: BLE001 - never breaks the engine
                    if time.time() - last.get(step, 0) > 600:
                        last[step] = time.time()
                        log.warning("telegram account %s: %s: %s", step, type(exc).__name__, str(exc)[:300])

    def start_account_loop(self, stop: threading.Event) -> bool:
        """Start the 'telegram-account' thread ONCE (guard: self.acct_thread / rt._acct_thread) and only when the runtime has a bridge.
        Called by Runtime.start after the licence unlock and never for the synthetic demo (no reports from a synthetic account)."""
        rt = self.rt
        if getattr(rt, "bridge", None) is None or self.acct_thread is not None or getattr(rt, "_acct_thread", None):
            return False
        t = threading.Thread(target=self.account_loop, args=(stop,), name="telegram-account", daemon=True)
        self.acct_thread = t
        rt._acct_thread = t
        t.start()
        return True
