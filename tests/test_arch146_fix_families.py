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

import shutil
import tempfile
import unittest
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
