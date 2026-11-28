"""Etap 4 (Apollo23 1.46, docs/arch146/ETAP2_PROJEKT.md §3-§6): cechy i ledgery - features/schemas.py + ledgers/ (widok).

* features/schemas.py PMW-FEAT-SCHEMAS-1: rejestr 25 schematów cech (id, wersja, właściciel = moduł buildera, lista cech, fingerprint =
  hash WYJŚCIA buildera na zamrożonym fixture PMW-FEAT-FIXTURE-1). Buildery zostają u właścicieli bez zmian. Zmiana buildera bez nowej
  wersji (nowego id) = test czerwony.
Wszystko tylko odczyt / liczenie na danych SYNTETYCZNYCH - bez MT5, bez zleceń, bez zapisu do data/.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import _env

REQUIRED_IDS = {"PMW-QUANT-FEAT-1", "PMW-QUANT-FEAT-3", "PMW-QUANT-FEAT-4", "MQ-FEAT-1.3.0", "SCALP_INDICATOR_CONTEXT_V2",
                "SCALP-SETUP-FEAT-1.0.0", "PMW-TH-FEAT-1", "PMW-MM-EVENT-1", "FS-1.0.0", "SMF-1.0.0", "NSS-FEAT-1.0.0", "PMW-ZONES-SEM-1",
                "PMW-ZONES-SEM-2"}
FIXTURE_DIGEST = "899c42bba3ff4a7d"        # PMW-FEAT-FIXTURE-1 (the generator is frozen with FIXTURE_VERSION)


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = _env.TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()


class TestFeatureSchemaRegistry(_Data):
    """ETAP2 §4 'Cechy': 25 schematów wersjonowanych samymi nazwami (ETAP1 rejestry_cech#4) - rejestr z odciskiem formuły."""

    def test_registry_covers_the_schemas_of_the_code(self):
        from masterquo.features import schemas as FS
        ids = [s.id for s in FS.SCHEMAS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 25)
        self.assertLessEqual(REQUIRED_IDS, set(ids))
        self.assertEqual(set(FS.FINGERPRINTS), set(ids))                  # every schema has a frozen fingerprint, nothing else
        self.assertEqual({s.family for s in FS.SCHEMAS},
                         {"quant", "ml", "zones", "extind", "scalp", "gold_candles", "trainhub", "mm", "lab", "sh", "research"})

    def test_owner_declares_the_label_and_owns_the_builder(self):
        import importlib

        from masterquo.features import schemas as FS
        for s in FS.SCHEMAS:
            self.assertEqual(FS.owner_id(s.id), FS.label(s.id), s.id)
            mod, fn = s.owner.split(" ")[0].split(":")
            self.assertTrue(callable(getattr(importlib.import_module(mod), fn)), s.owner)
            self.assertTrue(s.version and s.version in s.id or s.version in ("1",), s.id)
        self.assertEqual(FS.label("PMW-MM-EVENT-1"), __import__("masterquo.mm.events", fromlist=["x"]).FEATURE_SCHEMA)
        from masterquo.mm import features as MMF
        from masterquo.mm import jobs as MJ
        self.assertEqual(FS.label("PMW-MM-FEATURES-1/HDC"), MMF.schema_id(MJ.HDC_FEATURES))

    def test_names_are_the_owner_lists_and_match_the_dictionary(self):
        from masterquo.features import catalog as FC
        from masterquo.features import schemas as FS
        live = FC.registry_names()
        for s in FS.SCHEMAS:
            nm = FS.names(s.id)
            self.assertTrue(nm, s.id)
            self.assertEqual(len(nm), len(set(nm)), s.id)
            if s.catalog and s.id != "PMW-MM-FEATURES-1/HDC":
                self.assertEqual(nm, live[s.catalog], s.id)               # the same names as PMW-FEAT-DICT-1 knows
        self.assertLessEqual(set(FS.names("PMW-MM-FEATURES-1/HDC")), set(live["mm"]))
        from masterquo.ml import features as MF
        from masterquo.scalp import strategy as ST
        self.assertEqual(FS.names("MQ-FEAT-1.3.0"), MF.FEATURE_NAMES)
        self.assertEqual(FS.names("SCALP-SETUP-FEAT-1.0.0"), list(ST.SETUP_FEATURES))
        self.assertEqual(FS.names("SCALP-NET-FEAT-1.0.0")[:len(ST.SETUP_FEATURES)], list(ST.SETUP_FEATURES))
        for v in ("PMW-QUANT-FEAT-1", "PMW-QUANT-FEAT-4"):
            self.assertEqual(FS.get(v).names_kind, "FIXTURE")
        self.assertTrue(any(n.startswith("ctx:regime_sh=") for n in FS.names("PMW-QUANT-FEAT-4")))
        self.assertFalse(any(n.startswith("ctx:regime=") for n in FS.names("PMW-QUANT-FEAT-4")))
        self.assertTrue(any(n.startswith("ctx:regime=") for n in FS.names("PMW-QUANT-FEAT-1")))

    def test_fingerprints_are_frozen_stable_and_create_nothing(self):
        from masterquo.features import schemas as FS
        rows = FS.check()
        bad = [r for r in rows if not r["ok"]]
        self.assertEqual(bad, [], "fingerprint / label differ from the frozen ones - a builder changed without a new schema version")
        self.assertEqual({r["id"]: FS.fingerprint(r["id"]) for r in rows}, FS.FINGERPRINTS)   # recomputed: the same
        self.assertEqual(list(self.data.rglob("*")), [])                  # builders on the fixture write nothing to data/
        self.assertEqual(FS.FINGERPRINTS["PMW-QUANT-FEAT-1"], FS.FINGERPRINTS["PMW-QUANT-FEAT-2"])   # one builder (build2)
        self.assertNotEqual(FS.FINGERPRINTS["PMW-QUANT-FEAT-1"], FS.FINGERPRINTS["PMW-QUANT-FEAT-3"])
        self.assertNotEqual(FS.FINGERPRINTS["PMW-ZONES-SEM-1"], FS.FINGERPRINTS["PMW-ZONES-SEM-2"])
        self.assertEqual(len(set(FS.FINGERPRINTS.values())), len(FS.FINGERPRINTS) - 1)

    def test_fingerprint_is_the_hash_of_the_owner_builder_output(self):
        """The registry wraps the owner's function (same call, same numbers): the digest of a direct call = the registry fingerprint."""
        from masterquo.features import schemas as FS
        from masterquo.lab import features as LF
        from masterquo.quant import features as QF
        from masterquo.trainhub import features as TF
        cands, preds = FS._quant_inputs()

        def fp(out):
            return FS.digest({"fixture": FS.FIXTURE_VERSION, "output": out})
        self.assertEqual(fp([QF.build4(c, preds) for c in cands]), FS.FINGERPRINTS["PMW-QUANT-FEAT-4"])
        self.assertEqual(fp([QF.build3(c, preds) for c in cands]), FS.FINGERPRINTS["PMW-QUANT-FEAT-3"])
        self.assertEqual(fp([QF.build2(c, preds) for c in cands]), FS.FINGERPRINTS["PMW-QUANT-FEAT-1"])
        self.assertEqual(fp(LF.feature_matrix(FS._b("M5", 700), "M5")), FS.FINGERPRINTS["FS-1.0.0"])
        cols = {tf: FS._cols(tf, 1500) for tf in ("M1", "M5", "M15", "M30")}
        th = {}
        for base in ("M1", "M5", "M15"):
            t, X, nm = TF.build(cols, base, 0.01)
            th[base] = {"t": t[-200:], "X": X[-200:], "names": nm}
        self.assertEqual(fp(th), FS.FINGERPRINTS["PMW-TH-FEAT-1"])

    def test_builder_change_without_version_bump_is_red(self):
        """A formula change under the same id is detected - and only for the schemas whose builder it touches."""
        from masterquo.features import schemas as FS
        from masterquo.quant import features as QF

        def red(*ids):
            return {r["id"] for r in FS.check(list(ids)) if not r["ok"]}
        # FEAT-3 / FEAT-4 fix (D8) reverted under the same ids: FEAT-3 / -4 red, the frozen FEAT-1 / -2 (build2) untouched
        with mock.patch.object(QF, "_filter_dir_v3", QF._dir_of):
            self.assertEqual(red("PMW-QUANT-FEAT-1", "PMW-QUANT-FEAT-2", "PMW-QUANT-FEAT-3", "PMW-QUANT-FEAT-4"),
                             {"PMW-QUANT-FEAT-3", "PMW-QUANT-FEAT-4"})
        # another RSI seed in trainhub (ETAP1: 2.96e-3 at bar 14, 1.18e-5 at bar 100)
        from masterquo.strategies import indicators as SI
        from masterquo.trainhub import features as TF

        def rsi_other_seed(c):
            import numpy as np
            return np.array([np.nan if v is None else v / 100.0 - 0.5 for v in SI.rsi(list(c), 14)])
        with mock.patch.object(TF, "_rsi", rsi_other_seed):
            self.assertEqual(red("PMW-TH-FEAT-1", "FS-1.0.0"), {"PMW-TH-FEAT-1"})
        # SMA ATR instead of Wilder in lab FS-1.0.0 (3.75 % median difference, ETAP1 rejestry_cech#7)
        from masterquo.lab import common as LC
        from masterquo.lab import features as LF

        def sma_atr(h, lo, c, n=14):
            import numpy as np
            prev = np.r_[c[0], c[:-1]]
            tr = np.maximum(np.maximum(h - lo, np.abs(h - prev)), np.abs(lo - prev))
            return LC.sma(tr, n)
        with mock.patch.object(LF, "atr", sma_atr):
            self.assertEqual(red("FS-1.0.0", "SMF-1.0.0"), {"FS-1.0.0"})
        # SEM-1 session coding in SEM-2 (I0865): only SEM-2 changes
        from masterquo.zones import features as ZF
        orig = ZF._session_code
        with mock.patch.object(ZF, "_session_code", lambda ctx, legacy: orig(ctx, True)):
            self.assertEqual(red("PMW-ZONES-SEM-1", "PMW-ZONES-SEM-2"), {"PMW-ZONES-SEM-2"})
        # a missing setup context as NaN instead of 0.0 in setup_features: SETUP red
        from masterquo.scalp import strategy as ST
        orig_sf = ST.setup_features
        with mock.patch.object(ST, "setup_features", lambda *a: {k: (float("nan") if v == 0.0 else v) for k, v in orig_sf(*a).items()}):
            self.assertIn("SCALP-SETUP-FEAT-1.0.0", red("SCALP-SETUP-FEAT-1.0.0"))
        # a version bump in the owner without a registry entry is red as well (the registry must get the new id)
        from masterquo.ml import features as MF
        with mock.patch.object(MF, "FEATURE_SCHEMA_VERSION", "MQ-FEAT-1.4.0"):
            row = FS.check(["MQ-FEAT-1.3.0"])[0]
            self.assertEqual((row["ok"], row["owner_id"]), (False, "MQ-FEAT-1.4.0"))
        self.assertEqual([r["id"] for r in FS.check() if not r["ok"]], [])          # patches gone: green again

    def test_fixture_is_frozen_and_valid(self):
        from masterquo.features import schemas as FS
        fx = FS.fixture()
        self.assertEqual({tf: len(v) for tf, v in fx.items()}, {"M1": 8640, "M5": 1728, "M15": 576, "M30": 288, "H1": 144, "H4": 140, "D1": 90})
        for tf, bars in fx.items():
            s = FS.TF_MIN[tf] * 60
            self.assertLessEqual(bars[-1]["t"] + s, FS.T_END, tf)           # every bar closed at T_END
            self.assertEqual([b["t"] for b in bars], sorted({b["t"] for b in bars}), tf)
            for b in bars:
                self.assertTrue(b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"], (tf, b))
                self.assertEqual(round(b["c"], 2), b["c"])
        self.assertEqual(fx["M1"][0]["open_utc"], "2026-03-02T00:00:00Z")
        self.assertEqual(FS.digest(fx), FIXTURE_DIGEST)
        g = FS._Rng(0)                                                    # splitmix64 reference stream (seed 0): 0xe220a8397b1dcdaf, ...
        self.assertEqual([int(g.u() * 2 ** 53) for _ in range(2)], [0xe220a8397b1dcdaf >> 11, 0x6e789e6aa1b965f4 >> 11])

    def test_canonical_form(self):
        import numpy as np
        from masterquo.features import schemas as FS
        self.assertEqual(FS.canonical([float("nan"), float("inf"), -float("inf"), 1e-13, 0.123456789123, 2650.123456789, True, None]),
                         ["NaN", "Inf", "-Inf", 0.0, 0.1234568, 2650.123, True, None])
        self.assertEqual(FS.canonical(np.array([[1.0, np.nan]])), {"__ndarray__": [1, 2], "v": [[1.0, "NaN"]]})
        self.assertEqual(FS.digest({"a": 1.0, "b": [1, 2]}), FS.digest({"b": [1, 2], "a": 1.0 + 1e-15}))
        self.assertNotEqual(FS.digest({"a": 1.0}), FS.digest({"a": 1.0 + 1e-6}))

    def test_tag_and_manifest_check(self):
        from masterquo.features import schemas as FS
        t = FS.tag("PMW-MM-EVENT-1")
        self.assertEqual(t["feature_schema_id"], FS.label("PMW-MM-EVENT-1"))
        self.assertEqual(FS.check_manifest("SMF-1.0.0", {})["status"], "LEGACY")             # artifacts of today: accepted as today
        self.assertEqual(FS.check_manifest("SMF-1.0.0", {"feature_fingerprint": FS.FINGERPRINTS["SMF-1.0.0"]})["status"], "OK")
        self.assertEqual(FS.check_manifest("SMF-1.0.0", {"feature_fingerprint": "0" * 16})["status"], "MISMATCH")
        self.assertEqual(FS.check_manifest("NOPE", {})["status"], "UNKNOWN_SCHEMA")
        reg = FS.registry()
        self.assertEqual([r["id"] for r in reg], [s.id for s in FS.SCHEMAS])
        self.assertTrue(all(r["fingerprint"] for r in reg))


if __name__ == "__main__":
    unittest.main()
