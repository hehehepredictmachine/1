"""1.46 arch (fala napraw, grupa families) - D5 i D18 z docs/arch146/ETAP2_PROJEKT.md; każdy test nie przechodzi na kodzie sprzed poprawki.

* D5 (W): bramka ASSIST (Store.assist_ok: artefakt APPROVED na danych REAL) działała tylko w set_use. Aktywacja innego artefaktu
  i rollback zostawiały rolę ASSIST na artefakcie bez APPROVED / na danych syntetycznych lub nieznanych (albo bez artefaktu), a taki
  artefakt mógł wstrzymywać setupy SH (READY -> WAIT). Wariant ZAOSTRZAJĄCY: przy roli ASSIST zmiana aktywnego artefaktu na taki, który
  nie przechodzi bramki, jest ODRZUCANA bez zapisu stanu (najpierw rola SHADOW). Nic nie obniża istniejącej roli ASSIST i nic nie zdejmuje
  istniejących wstrzymań (łata 78e261e - obniżanie ASSIST w activate / rollback / predict - świadomie NIE jest stosowana).
* D18 (W): rekord PMW-PRED-2 rodziny brał data_kind z manifestu tylko dla dosłownych 'REAL' / 'SYNTHETIC', a Store danych zapisuje
  REAL_USER_DATA / SYNTHETIC_TEST / MT5_LIVE_BRIDGE - każdy rekord miał data_kind None, więc quant.checks nie odrzucał artefaktu
  wytrenowanego na syntetyce w migawce REAL. Teraz base.kind_class (jedno słownictwo z bramką ASSIST).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import _env

FID, INST = "TS_ARIMA", "XAUUSD"


class _StoreCase(unittest.TestCase):
    def setUp(self):
        from masterquo.modelhub.families import base as B
        tmp = _env.TempData()                                                     # isolated config / data dir
        self.addCleanup(tmp.close)
        self.td = tempfile.mkdtemp(prefix="fam_fix_")
        self.addCleanup(shutil.rmtree, self.td, True)
        self.B, self.store = B, B.Store(Path(self.td))

    def run_(self, rid, status, kind, fid=FID):
        d = self.store.run_dir(fid, INST, rid)
        d.mkdir(parents=True)
        self.B._atomic_json(d / "manifest.json", {"run_id": rid, "validation": {"status": status}, "data_kind": kind, "created_at": 1})

    def state_bytes(self, fid=FID):
        return self.store._state_path(fid, INST).read_bytes()

    def assert_gate(self, fn, *a):
        """The refusal is a ValueError (API _fam -> 409) of the subclass AssistGate, the message starts with ASSIST_GATE."""
        with self.assertRaises(ValueError, msg=a) as cm:
            fn(*a)
        self.assertIn("ASSIST_GATE", str(cm.exception))
        self.assertIsInstance(cm.exception, getattr(self.B, "AssistGate", ()))

    def assist_on(self, rid, fid=FID):
        """An APPROVED / REAL artifact active with the role ASSIST (granted through the gate in set_use)."""
        self.store.set_active(fid, INST, rid, "t")
        self.assertEqual(self.store.set_use(fid, INST, "ASSIST")["use"], "ASSIST")


class TestFamiliesAssistGateOnActivation(_StoreCase):
    """D5: Store.set_active / Store.rollback at the role ASSIST refuse a target that does not pass assist_ok (no state write)."""

    def test_set_active_refuses_target_failing_the_gate_under_assist(self):
        self.run_("GOOD", "APPROVED", "REAL_USER_DATA")
        self.assist_on("GOOD")
        for rid, status, kind in (("REJ", "VALIDATION_FAILED", "REAL_USER_DATA"), ("CAND", None, "REAL_USER_DATA"),
                                  ("SYN", "APPROVED", "SYNTHETIC_TEST"), ("UNK", "APPROVED", "UNKNOWN_SOURCE"), ("NOKIND", "APPROVED", None)):
            self.run_(rid, status, kind)
            before = self.state_bytes()
            self.assert_gate(self.store.set_active, FID, INST, rid, "panel")
            self.assertEqual(self.state_bytes(), before, rid)                     # active, use and history untouched
        st = self.store.state(FID, INST)
        self.assertEqual((st["active"], st["use"]), ("GOOD", "ASSIST"))           # the approved artifact keeps its role (no lowering)
        before = self.state_bytes()
        self.assert_gate(self.store.set_active, FID, INST, None, "panel")         # deactivation under ASSIST too
        self.assertEqual(self.state_bytes(), before)

    def test_set_active_allows_target_passing_the_gate_under_assist(self):
        self.run_("GOOD", "APPROVED", "REAL_USER_DATA")
        self.run_("LIVE", "APPROVED", "MT5_LIVE_BRIDGE")
        self.assist_on("GOOD")
        st = self.store.set_active(FID, INST, "LIVE", "panel")
        self.assertEqual((st["active"], st["use"]), ("LIVE", "ASSIST"))

    def test_shadow_and_off_activation_unchanged(self):
        self.run_("REJ", "VALIDATION_FAILED", "SYNTHETIC_TEST")
        self.run_("REJ2", "VALIDATION_FAILED", "UNKNOWN_SOURCE")
        st = self.store.set_active(FID, INST, "REJ", "panel")
        self.assertEqual((st["active"], st["use"]), ("REJ", "SHADOW"))           # OFF -> SHADOW, as before
        st = self.store.set_active(FID, INST, "REJ2", "panel")
        self.assertEqual((st["active"], st["use"]), ("REJ2", "SHADOW"))
        self.assertEqual(self.store.rollback(FID, INST)["active"], "REJ")

    def test_rollback_to_no_artifact_refused_under_assist(self):
        self.run_("GOOD", "APPROVED", "REAL")
        self.assist_on("GOOD")                                                    # previous active = None
        before = self.state_bytes()
        self.assert_gate(self.store.rollback, FID, INST)
        self.assertEqual(self.state_bytes(), before)

    def test_rollback_to_synthetic_refused_approved_allowed(self):
        self.run_("SYN", "APPROVED", "SYNTHETIC_TEST")
        self.run_("A", "APPROVED", "REAL_USER_DATA")
        self.run_("B", "APPROVED", "REAL_USER_DATA")
        self.store.set_active(FID, INST, "SYN", "t")                              # SHADOW
        self.assist_on("A")                                                       # previous = SYN
        before = self.state_bytes()
        self.assert_gate(self.store.rollback, FID, INST)
        self.assertEqual(self.state_bytes(), before)
        self.store.set_active(FID, INST, "B", "t")                                # previous = A (APPROVED / REAL)
        st = self.store.rollback(FID, INST)
        self.assertEqual((st["active"], st["use"]), ("A", "ASSIST"))

    def test_legacy_assist_state_is_not_lowered(self):
        """A state saved before the fix (ASSIST on a non-approved artifact) is kept as it is - nothing lifts its holds - and reported."""
        self.run_("SYN", "APPROVED", "SYNTHETIC_TEST")
        self.store._save_state(FID, INST, {"active": "SYN", "use": "ASSIST", "history": []})
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        s = FamilyService(ConfigStore(), None, store=self.store)
        st = s.status(FID, INST)
        self.assertEqual(st["use"], "ASSIST")
        self.assertTrue(st["assist_gate_violation"])
        self.assertEqual(self.store.state(FID, INST)["use"], "ASSIST")
        self.run_("GOOD", "APPROVED", "REAL_USER_DATA")
        self.store.set_active(FID, INST, "GOOD", "t")                             # an approved artifact may replace it
        self.assertIsNone(s.status(FID, INST)["assist_gate_violation"])


class TestFamiliesServiceAssistGate(_StoreCase):
    """D5 at the service / CLI level: activate answers ASSIST_GATE (API: 409, path unchanged), rollback raises ValueError (API _fam: 409)."""

    def svc(self):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        return FamilyService(ConfigStore(), None, store=self.store)

    def test_activate_returns_assist_gate_and_keeps_state(self):
        self.run_("GOOD", "APPROVED", "REAL_USER_DATA")
        self.run_("SYN", "APPROVED", "SYNTHETIC_TEST")
        self.assist_on("GOOD")
        s = self.svc()
        before = self.state_bytes()
        with mock.patch.object(s.fams[FID], "load", return_value={}), \
                mock.patch.object(s, "_sample_check", return_value={"ok": True, "checked": False}):
            r = s.activate(FID, INST, "SYN")
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["status"], "ASSIST_GATE")
        self.assertIn("SHADOW", r["reason"])
        self.assertEqual(self.state_bytes(), before)
        with mock.patch.object(s.fams[FID], "load", return_value={}), \
                mock.patch.object(s, "_sample_check", return_value={"ok": True, "checked": False}):
            s.set_use(FID, INST, "SHADOW")
            self.assertTrue(s.activate(FID, INST, "SYN")["ok"])                   # SHADOW first -> the activation goes through
        self.assertEqual(self.store.state(FID, INST)["active"], "SYN")

    def test_rollback_raises_value_error(self):
        self.run_("GOOD", "APPROVED", "REAL_USER_DATA")
        self.assist_on("GOOD")
        s = self.svc()
        self.assert_gate(s.rollback, FID, INST)
        self.assertEqual(self.store.state(FID, INST)["active"], "GOOD")

    def test_cli_rollback_refused_exit_3(self):
        self.run_("GOOD", "APPROVED", "REAL_USER_DATA")
        self.assist_on("GOOD")
        from masterquo.modelhub.families import cli
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PMW_FAMILIES_DIR": self.td}), redirect_stdout(out):
            rc = cli.main(["rollback", "--instrument", INST, "--family", FID])
        self.assertEqual(rc, 3)
        r = json.loads(out.getvalue())
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], "ASSIST_GATE")
        self.assertEqual(self.store.state(FID, INST)["active"], "GOOD")


class TestFamiliesRecordDataKind(_StoreCase):
    """D18: the family record carries base.kind_class(manifest data_kind); Quant drops a SYNTHETIC family from a REAL snapshot."""

    FAM = "KALMAN_LS"

    def predict_for(self, kind):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families import run as RUN
        from masterquo.modelhub.families.service import FamilyService
        from test_families_u4 import data_for, synth
        bars = synth(1500, drift=2e-4, garch=False, phi=0.0, seed=9)
        r = RUN.train(self.FAM, INST, "smoke", {}, data=data_for(bars, kind=kind), store=self.store)
        self.assertEqual(r["state"], "DONE", r)
        s = FamilyService(ConfigStore(), None, store=self.store)
        self.assertTrue(s.activate(self.FAM, INST, r["run_id"])["ok"])
        live = {"bars": synth(1500, drift=2e-4, garch=False, phi=0.0, seed=11)}
        with mock.patch.object(s, "_live", return_value=live):
            p = s.predict(self.FAM, INST)
        self.assertEqual(p["state"], "READY", p)
        return p, float(live["bars"][-1]["t"])

    def test_synthetic_family_excluded_from_real_snapshot(self):
        from masterquo.quant import checks as CK
        p, t = self.predict_for("SYNTHETIC_TEST")
        self.assertEqual(p["data_kind"], "SYNTHETIC")
        r = CK.check(p, now=t + 60, snapshot_kind="REAL")
        self.assertFalse(r["eligible"])
        self.assertEqual(r["reason"], "SYNTHETIC_IN_REAL_SNAPSHOT")
        self.assertTrue(CK.check(p, now=t + 60, snapshot_kind="SYNTHETIC")["eligible"])

    def test_real_user_data_family_is_real(self):
        from masterquo.quant import checks as CK
        p, t = self.predict_for("REAL_USER_DATA")
        self.assertEqual(p["data_kind"], "REAL")
        self.assertTrue(CK.check(p, now=t + 60, snapshot_kind="REAL")["eligible"])

    def test_unknown_source_stays_none(self):
        p, _ = self.predict_for("UNKNOWN_SOURCE")
        self.assertIsNone(p["data_kind"])


if __name__ == "__main__":
    unittest.main()
