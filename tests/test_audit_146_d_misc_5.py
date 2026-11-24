"""1.46 audit, group D_misc_5 - regression tests (1.41 upgrade auto_install vs Bootstrap, upgrade state texts, Database.execute,
export redaction of the owner's private key)."""
from __future__ import annotations

import json
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData, wait_for

_REAL_SLEEP = time.sleep
_FAST_TIME = types.SimpleNamespace(sleep=lambda s: _REAL_SLEEP(0.002), time=time.time, monotonic=time.monotonic)


class _Log:
    def __init__(self):
        self.rows = []

    def info(self, *a):
        self.rows.append(a)


class _Tsfm:
    """TSFM service stub: install jobs in .jobs (the shape of TsfmService.jobs), every start recorded with the jobs RUNNING at that moment."""

    def __init__(self, jobs=None):
        self.jobs = dict(jobs or {})
        self.starts = []
        self.settings = types.SimpleNamespace(get=lambda: types.SimpleNamespace(models={"tirex2": None}))

    def _running(self):
        return sorted(n for n, j in self.jobs.items() if isinstance(j, dict) and j.get("state") == "RUNNING")

    def start_install(self, mid):
        self.starts.append((f"install_{mid}", self._running()))
        self.jobs[f"install_{mid}"] = {"state": "RUNNING"}
        return {"ok": True, "job": f"install_{mid}"}

    def _run_job_proc(self, name, argv, env=None, on_done=None):
        self.starts.append((name, self._running()))
        self.jobs[name] = {"state": "RUNNING"}
        return {"ok": True, "job": name}

    def job(self, name):
        j = self.jobs.get(name)
        return dict(j) if j else None


class TestAutoInstallNeverParallelToBootstrap(unittest.TestCase):
    """chunk_38#7: upgrade.migrate.auto_install started TiRex-2 ~90 s after the start while Bootstrap.run_heavy (started 60 s after the
    start) installed chronos2 - two heavy installs at once; TabICL followed without waiting for any other install."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.upgrade import migrate as M
        self.M = M
        for p in (mock.patch("masterquo.tsfm.settings.find_python", return_value=None),
                  mock.patch("masterquo.quant.tabicl.find_python", return_value=None),
                  mock.patch.object(M, "time", _FAST_TIME),
                  mock.patch.object(M, "_POLL_S", 0.002, create=True)):
            p.start()
            self.addCleanup(p.stop)

    def _rt(self, tsfm, bootstrap=None):
        rt = types.SimpleNamespace(tsfm=tsfm, kronos=None, log=_Log(), _stop=threading.Event(), bootstrap=bootstrap)
        self.addCleanup(rt._stop.set)                    # a leftover auto_install thread ends with the test
        return rt

    def test_full_profile_bootstrap_owns_the_queue(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        bt = threading.Thread(target=gate.wait, daemon=True)
        bt.start()
        bs = types.SimpleNamespace(_thread=bt, _stop=threading.Event(), state={"profile": "FULL", "components": {}})
        tsfm = _Tsfm({"install_chronos2": {"state": "RUNNING"}})           # Bootstrap.run_heavy installs chronos2
        r = self.M.auto_install(self._rt(tsfm, bs))
        _REAL_SLEEP(0.3)
        self.assertEqual(tsfm.starts, [])                                   # no second heavy install next to Bootstrap's
        self.assertEqual(r.get("delegated"), "bootstrap")
        self.assertNotIn("last_try", self.M.state().get("auto_install") or {})   # nothing tried -> no 24 h lock-out

    def test_each_step_waits_until_no_heavy_install_runs(self):
        tsfm = _Tsfm({"install_chronos2": {"state": "RUNNING"}})           # e.g. started in the panel
        rt = self._rt(tsfm)                                                  # no Bootstrap (PMW_BOOTSTRAP=0 / CORE)
        r = self.M.auto_install(rt)
        self.assertTrue(r["ok"], r)
        _REAL_SLEEP(0.3)
        self.assertEqual(tsfm.starts, [])                                   # chronos2 still installing
        tsfm.jobs["install_chronos2"]["state"] = "DONE"
        self.assertTrue(wait_for(lambda: len(tsfm.starts) >= 1, 5))
        self.assertEqual(tsfm.starts[0], ("install_tirex2", []))
        _REAL_SLEEP(0.3)
        self.assertEqual(len(tsfm.starts), 1)                               # TabICL waits for the TiRex-2 job
        tsfm.jobs["install_tirex2"]["state"] = "FAILED"
        self.assertTrue(wait_for(lambda: len(tsfm.starts) >= 2, 5))
        self.assertEqual(tsfm.starts[1], ("install_tabicl", []))

    def test_core_profile_bootstrap_does_not_take_over(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        bt = threading.Thread(target=gate.wait, daemon=True)
        bt.start()
        bs = types.SimpleNamespace(_thread=bt, _stop=threading.Event(), state={"profile": "CORE", "components": {}})
        tsfm = _Tsfm()
        r = self.M.auto_install(self._rt(tsfm, bs))
        self.assertNotIn("delegated", r)
        self.assertTrue(wait_for(lambda: len(tsfm.starts) >= 1, 5))
        self.assertEqual(tsfm.starts[0], ("install_tirex2", []))


class TestUpgradeStateTexts(unittest.TestCase):
    """chunk_38#15: every fresh install recorded the 1.41 catalog ("9 x 10 profiles") and "CRYPTO / OTC (manual)" - OTC is retired."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_fresh_install_state_has_no_live_otc_or_old_catalog(self):
        from masterquo.upgrade import migrate as M
        with mock.patch.object(M.INV, "write_reports", return_value={}):
            st41 = M.before()
        st42 = M.apply_142(types.SimpleNamespace(tsfm=None, kronos=None, baskets=None, log=_Log()))
        blob = json.dumps([st41["activation_scope"], st41["not_changed"], st42["not_changed"]], ensure_ascii=False)
        self.assertNotIn("9 x 10", blob)
        self.assertNotIn("OTC (manual)", blob)
        self.assertIn("60 strategies / 6 baskets / 2 profiles", blob)
        self.assertIn("OTC retired", blob)
        for k in ("account execution mode", "STOP"):                         # the guarantees themselves are unchanged
            self.assertIn(k, st41["not_changed"])
            self.assertIn(k, st42["not_changed"])

    def test_rollback_config_restores_the_pre_141_snapshot(self):
        """chunk_38#14 (kept, not removed): rollback_config() is the reverse path of the 1.41 configuration migration."""
        from masterquo import paths
        from masterquo.upgrade import migrate as M
        cfg = paths.data_dir() / "tsfm" / "settings.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('{"v": "pre"}', encoding="utf-8")
        with mock.patch.object(M.INV, "write_reports", return_value={}):
            M.before()
        cfg.write_text('{"v": "post"}', encoding="utf-8")
        r = M.rollback_config()
        self.assertTrue(r["ok"], r)
        self.assertIn("tsfm/settings.json", r["restored"])
        self.assertEqual(cfg.read_text(encoding="utf-8"), '{"v": "pre"}')


class TestDatabaseExecuteCount(unittest.TestCase):
    """chunk_08#10: execute() returned the connection's stale lastrowid for UPDATE / DELETE / an ignored INSERT OR IGNORE."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.db.database import Database
        self.db = Database(Path(self.td.dir) / "t.sqlite")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT UNIQUE)")

    def test_insert_returns_rowid_other_statements_the_changed_rows(self):
        db = self.db
        self.assertEqual([db.execute("INSERT INTO t(v) VALUES(?)", (v,)) for v in "abc"], [1, 2, 3])
        self.assertEqual(db.execute("  insert or replace into t(id, v) values(7, 'z')"), 7)
        self.assertEqual(db.execute("UPDATE t SET v=v||'x' WHERE id=99"), 0)        # matched nothing (was 7)
        self.assertEqual(db.execute("UPDATE t SET v=v||'x' WHERE id<=2"), 2)        # 2 rows (was 7)
        self.assertEqual(db.execute("DELETE FROM t WHERE id=99"), 0)
        self.assertEqual(db.execute("INSERT OR IGNORE INTO t(v) VALUES('c')"), 0)   # ignored (was the stale 7)
        self.assertEqual(db.execute("DELETE FROM t WHERE id IN (1, 2, 3)"), 3)


class TestExportRedactsOwnerKey(unittest.TestCase):
    """focus_X7#13: SECRET_PATTERNS had a non-existent 'PMW1-PRIV-' marker; the real owner key text was neither redacted nor detected."""

    def _key_text(self):
        from masterquo.licensing.owner import KEY_HEADER
        seed = "3c" * 32                                    # dummy seed (not a real key), built at run time
        return KEY_HEADER + "\n" + "seed: " + seed + "\npublic: " + "00" * 32 + "\n", seed

    def test_owner_private_key_is_redacted_and_detected(self):
        from masterquo.exports.core import REDACTED, Redactor
        text, seed = self._key_text()
        red = Redactor([])
        out = red.value({"message": "backup: " + text})
        self.assertNotIn(seed, json.dumps(out))
        self.assertIn(REDACTED, out["message"])
        self.assertEqual(red.count, 1)
        self.assertTrue(red.leaks(text))
        self.assertTrue(red.leaks(json.dumps({"m": text})))                          # JSONL: the newline is escaped
        self.assertTrue(red.leaks(text.replace("\n", "\r\n")))                      # CSV cell / Windows file

    def test_no_false_positive_on_hashes(self):
        from masterquo.exports.core import Redactor
        red = Redactor([])
        blob = json.dumps({"seed_sha256": "ab" * 32, "sha256": "cd" * 32, "seed": 42})
        self.assertFalse(red.leaks(blob))
        self.assertEqual(red.text(blob), blob)


if __name__ == "__main__":
    unittest.main()
