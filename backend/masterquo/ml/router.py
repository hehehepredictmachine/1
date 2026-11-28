"""Legacy ML (Decision Tree / XGBoost on S01-S12 setups) per instrument.

Each instrument has its own sample/model database and model directory - XAUUSD keeps the historical ones (masterquo.sqlite,
data/ml), every other instrument uses data/instruments/<INST>/ml/ml.sqlite. Only the service of the ACTIVE instrument runs
(collector, labeller, scheduler): the bridge delivers the bars of one symbol, so a second service would label its samples with
another market's prices. Switching the asset stops the old service (a running training job becomes INTERRUPTED and can be
resumed) and starts the one of the new instrument. Everything else is delegated unchanged (API, engine, tests).
"""
from __future__ import annotations

import threading
import time

from .service import MLService

JOIN_TIMEOUT_S = 10.0          # 1.46 arch (I0096): how long switch() waits for the old service's threads before closing its database


def ml_store(inst: str, main_db=None):
    """(database, root) of an instrument's legacy ML space."""
    import mq_instruments
    from ..db.database import Database
    if inst == mq_instruments.DEFAULT:
        return (main_db or Database()), mq_instruments.root("ml", inst)
    root = mq_instruments.root("ml", inst)
    return Database(root / "ml.sqlite"), root


class MLRouter:
    def __init__(self, cfg_store, db, bridge, bus, applog):
        object.__setattr__(self, "_a", (cfg_store, db, bridge, bus, applog))
        object.__setattr__(self, "_lock", threading.Lock())
        object.__setattr__(self, "_stop", threading.Event())
        object.__setattr__(self, "_started", False)
        object.__setattr__(self, "cur", self._make(cfg_store.get().assets.active))

    def _make(self, inst: str) -> MLService:
        cfg_store, db, bridge, bus, applog = self._a
        try:
            import mq_instruments
            mq_instruments.profile(inst)
        except ValueError:
            inst = "XAUUSD"
        d, root = ml_store(inst, db)
        return MLService(cfg_store, d, bridge, bus, applog, root=root, instrument=inst)

    def start(self) -> None:
        object.__setattr__(self, "_started", True)
        self.cur.start()
        threading.Thread(target=self._watch, name="ml-router", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.cur.stop()

    def _watch(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self.switch(self._a[0].get().assets.active)
            except Exception:                       # noqa: BLE001 - routing never stops the bot
                pass

    def switch(self, inst: str) -> bool:
        with self._lock:
            if inst == self.cur.inst:
                return False
            old = self.cur
            old.stop()
            self._close_old_db(old)
            new = self._make(inst)
            object.__setattr__(self, "cur", new)
            if self._started:
                new.start()
            self._a[4].info("ML", "INSTRUMENT", f"Legacy ML: przełączono na bazę instrumentu {new.inst} ({new.root})")
            return True

    def _close_old_db(self, old) -> None:
        """1.46 arch (I0096): the old instrument's database was never closed on a switch. Closed only AFTER old.stop() and after its
        worker threads ended (joined, bounded wait) and NEVER when it is the main database (XAUUSD uses masterquo.sqlite). Database.close()
        closes the connection of the calling thread only - connections of other threads (an in-flight gate / API call on the old
        service) are untouched, so no running reader can hit a closed connection (the engine's ML gate falls back on errors)."""
        db = getattr(old, "db", None)
        if db is None or db is self._a[1]:
            return
        end = time.monotonic() + JOIN_TIMEOUT_S
        for t in list(getattr(old, "_threads", None) or []):
            t.join(max(0.0, end - time.monotonic()))
            if t.is_alive():
                return                                 # still working - leave the database to the garbage collector, as before
        try:
            db.close()
        except Exception as exc:                       # noqa: BLE001 - closing never stops the switch
            self._a[4].warn("ML", "DB_CLOSE_FAILED", f"Legacy ML: nie zamknięto bazy instrumentu {getattr(old, 'inst', '?')}: {exc}"[:300])

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "cur"), name)

    def __setattr__(self, name, value):
        setattr(self.cur, name, value)
