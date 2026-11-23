"""1.46 audit, group B_mq_modelhub_2 - regression tests for modelhub/families/service.py (FamilyService): predictions of an inactive
instrument, the service lock during training preparation, PAIR_COINT / STATARB without a live path.
Synthetic data only, no MT5, no HTTP server, no real training process."""
from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData

T_OPEN = 1_772_445_600  # 2026-03-02 10:00 UTC (open of the last closed bar)


def _rows(n: int, tf_s: int, last_open: int = T_OPEN) -> list[dict]:
    from masterquo.indicators.contract import iso
    out = []
    for i in range(n):
        t = last_open - (n - 1 - i) * tf_s
        out.append({"open_utc": iso(t), "o": 2000.0 + i, "h": 2001.0 + i, "l": 1999.0 + i, "c": 2000.5 + i, "tv": 10, "spread": 20,
                    "closed": True})
    return out


class FakeBridge:
    synthetic = True

    def __init__(self):
        self.calls = []
        self.quote = {"bid": 2000.0, "ask": 2000.2}

    def bars(self, tf, limit=None, include_forming=True):
        self.calls.append(tf)
        return _rows(50, {"M5": 300, "H1": 3600}[tf])


class FakeIndicators:
    def __init__(self):
        self.calls = 0
        self.dir = Path(tempfile.gettempdir())

    def current(self):
        self.calls += 1
        return {"microstructure": None}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = TempData()
        self.addCleanup(self.tmp.close)
        from masterquo.modelhub.families import base as B
        self.td = tempfile.mkdtemp(prefix="fam146b2_")
        self.addCleanup(shutil.rmtree, self.td, True)
        self.B, self.store = B, B.Store(Path(self.td))

    def svc(self, bridge=None, indicators=None):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        return FamilyService(ConfigStore(), bridge, indicators=indicators, store=self.store)

    def activate(self, fid, inst, rid="R1", use="SHADOW"):
        d = self.store.run_dir(fid, inst, rid)
        d.mkdir(parents=True)
        self.B._atomic_json(d / "manifest.json", {"run_id": rid, "validation": {"status": "APPROVED"}, "data_kind": "REAL", "created_at": 1})
        self.store._save_state(fid, inst, {"active": rid, "use": use, "history": []})

    @staticmethod
    def ready(s, fid):
        """The family returns a valid result without a real artifact (the service path is what is tested)."""
        f = s.fams[fid]
        return [mock.patch.object(f, "implementation", return_value=("AVAILABLE", None)),
                mock.patch.object(f, "predict", return_value={"mean": 0.001, "lo": -0.002, "hi": 0.003}),
                mock.patch.object(s, "_artifact", return_value={})]


# ------------------------------------------------------------------------------------------------ chunk_23#5 inactive instrument
class TestInactiveInstrument(_Base):
    def test_inactive_instrument_is_disabled_not_computed_on_active_bars(self):
        """chunk_23#5: predict(fid, 'BTC') with XAUUSD active computed the BTC artifact on XAUUSD bars (bridge.bars has no instrument)."""
        br, ind = FakeBridge(), FakeIndicators()
        s = self.svc(br, ind)
        self.activate("TS_ARIMA", "BTC")
        self.activate("TS_ARIMA", "XAUUSD")
        p = s.predict("TS_ARIMA", "BTC")
        self.assertEqual(p["state"], "DISABLED", p)
        self.assertIsNone(p["result"])
        self.assertIn("aktywnego instrumentu (XAUUSD)", p["unavailable_reason"])
        self.assertEqual(p["instrument"], "BTC")
        self.assertEqual(br.calls, [])                                    # the active symbol's bars were never read for BTC
        m = s.predict("MICROSTRUCTURE", "BTC")                            # measurements of the active book are not BTC either
        self.assertEqual(m["state"], "DISABLED", m)
        self.assertEqual(ind.calls, 0)
        self.assertIsNone(s.predict("TS_SARIMAX", "BTC"))                 # use OFF -> no record, as before
        # the active instrument is computed as before
        ps = self.ready(s, "TS_ARIMA")
        with ps[0], ps[1], ps[2]:
            q = s.predict("TS_ARIMA", "XAUUSD")
        self.assertEqual(q["state"], "READY", q)
        self.assertEqual(br.calls, ["M5"])


# ------------------------------------------------------------------------------------------------ chunk_23#13 lock during preparation
class FakeProc:
    pid = 4242

    def __init__(self, rc=None):
        self.rc = rc

    def poll(self):
        return self.rc


class TestSubmitPreparationWithoutLock(_Base):
    def _blocking_prep(self, s):
        entered, release = threading.Event(), threading.Event()

        def prep(fid, inst):
            entered.set()
            release.wait(10)
        return entered, release, prep

    def test_lock_free_while_bars_prepared_and_one_job_per_family(self):
        """chunk_23#13: submit() held the service RLock while it read the archive / fetched up to 20 000 MT5 bars / wrote the bars JSON -
        predict() (SH cycle, decision coordinator) waited for the whole preparation."""
        s = self.svc()
        s.procs["KALMAN_LS__XAUUSD"] = FakeProc(rc=0)                     # a finished earlier run of the same family
        entered, release, prep = self._blocking_prep(s)
        popen, res = [], {}
        with mock.patch.object(s, "_live_bars_file", side_effect=prep), \
                mock.patch("subprocess.Popen", side_effect=lambda *a, **k: popen.append(a) or FakeProc()):
            th = threading.Thread(target=lambda: res.update(r=s.submit("KALMAN_LS", "XAUUSD")))
            th.start()
            self.assertTrue(entered.wait(10))
            try:
                got = s._lock.acquire(timeout=1.0)
                if got:
                    s._lock.release()
                self.assertTrue(got, "the service lock was held during the bars preparation")
                self.assertEqual(s.job("KALMAN_LS", "XAUUSD")["state"], "QUEUED")       # the finished earlier proc is not this job
                self.assertEqual(s.submit("KALMAN_LS", "XAUUSD")["status"], "ALREADY_RUNNING")
                self.assertGreaterEqual(s._running(), 1)                                 # counted against MAX_PARALLEL
            finally:
                release.set()
                th.join(10)
        self.assertEqual(res["r"]["status"], "STARTED", res)
        self.assertEqual(len(popen), 1)

    def test_cancel_during_preparation_starts_nothing(self):
        s = self.svc()
        entered, release, prep = self._blocking_prep(s)
        popen, res = [], {}
        with mock.patch.object(s, "_live_bars_file", side_effect=prep), \
                mock.patch("subprocess.Popen", side_effect=lambda *a, **k: popen.append(a) or FakeProc()):
            th = threading.Thread(target=lambda: res.update(r=s.submit("KALMAN_LS", "XAUUSD")))
            th.start()
            self.assertTrue(entered.wait(10))
            s.cancel("KALMAN_LS", "XAUUSD")
            release.set()
            th.join(10)
        self.assertEqual(popen, [])
        self.assertFalse(res["r"]["ok"])
        self.assertEqual(s.job("KALMAN_LS", "XAUUSD")["state"], "CANCELLED")

    def test_failed_preparation_is_failed_not_queued_forever(self):
        s = self.svc()
        with mock.patch.object(s, "_live_bars_file", side_effect=OSError("dysk pełny")), mock.patch("subprocess.Popen") as po:
            with self.assertRaises(OSError):
                s.submit("KALMAN_LS", "XAUUSD")
            po.assert_not_called()
        j = s.job("KALMAN_LS", "XAUUSD")
        self.assertEqual(j["state"], "FAILED", j)
        self.assertIn("dysk pełny", j["reason"])
        with mock.patch.object(s, "_live_bars_file", return_value=None), mock.patch("subprocess.Popen", return_value=FakeProc()):
            self.assertEqual(s.submit("KALMAN_LS", "XAUUSD")["status"], "STARTED")       # the reservation was released


# ------------------------------------------------------------------------------------------------ chunk_23#21 pair / basket live path
class TestPairFamiliesWithoutLivePath(_Base):
    def test_pair_and_basket_are_disabled_with_the_reason(self):
        """chunk_23#21: _live never provides pair_bars / basket_bars - an active PAIR_COINT / STATARB looked like a temporary data gap."""
        s = self.svc(FakeBridge())
        for fid in ("PAIR_COINT", "STATARB"):
            self.activate(fid, "XAUUSD")
            p = s.predict(fid, "XAUUSD")
            self.assertEqual(p["state"], "DISABLED", p)
            self.assertIn("na żywo", p["unavailable_reason"])
            self.assertIsNone(p["result"])
        self.store._save_state("PAIR_COINT", "XAUUSD", {"active": "R1", "use": "OFF", "history": []})
        self.assertIsNone(s.predict("PAIR_COINT", "XAUUSD"))              # OFF -> no record, as before


if __name__ == "__main__":
    unittest.main()
