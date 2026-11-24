"""1.46 arch, fala 2 – grupa mm: master models (backend/masterquo/mm), parytet natywny MQL5 (mm/fixtures.py + PMW_MM_SelfTest.mq5),
inwentarz statusów, SHADOW GPR na żywo i ledger. Każdy test nie przechodzi na kodzie sprzed poprawki (klucze pozycji w nazwach klas).

* I0351: artefakt HDC wczytywany jedną funkcją (hdc.from_state) z kontrolą bazy (codebooki odtworzone z ziarna == zapisane).
* I0355: UNIT_TESTED tylko dla modułu z zadeklarowaną klasą testów (mapa UNIT_TESTS, klasa istnieje w pliku testów).
* I0357: GPR na żywo – tor procedury walidowanej (strojenie co retune_every świec jak walk_forward) obok dotychczasowej prognozy, której
  wartości (cecha Quant) zostają bez zmian (stare MetaModele dostają dokładnie dzisiejsze wejścia).
* I0358: wiersze ledgera spoza okna mostka nie są skanowane przy każdym przeliczeniu (min_source_ts).
* I0490 / I0497 / I0505 / I0506 / I0508 / I0511: bramki parytetu natywnego – LML, siatka GPR, 4 tryby wybicia, akumulatory HDC, niezależne
  porównanie słów HDC w Pythonie, stos stanów (CPU/OpenCL), rdzeń TSVP.
* I0499 / I0505 / I0508: status natywny modułu z zakresu (native_scope), nie stałe IMPLEMENTED dla każdego pliku mql5/.
* I0545: wskaźnik SHADOW przesuwa tylko artefakt VALIDATED_SHADOW z kompletem zaliczonych bramek na REAL_USER_DATA.
"""
from __future__ import annotations

import ast
import json
import math
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env
import numpy as np
from _env import TempData
from masterquo.mm import artifacts as AR
from masterquo.mm import fixtures as FX
from masterquo.mm import hdc as H
from masterquo.mm import inventory as INV
from masterquo.mm.ledger import Ledger

ROOT = _env.ROOT
MQL5_DIR = ROOT / "mql5"
SELFTEST = ROOT / "mql5" / "MasterModels" / "Scripts" / "PMW_MM_SelfTest.mq5"


def _rows(p: Path) -> list[list[str]]:
    return [ln.split(",") for ln in p.read_text(encoding="ascii").splitlines()[1:] if ln]


def _kv(p: Path) -> dict:
    out = {}
    for ln in p.read_text(encoding="ascii").splitlines():
        if ln:
            k, _, v = ln.partition(",")
            out[k] = v
    return out


# ---------------------------------------------------------------------------------------------------------------- I0351
class TestI0351HdcFromState(unittest.TestCase):
    def _artifact(self):
        sp = H.Space(256, seed=4242)
        names = ["f1", "f2", "f3", "f4", "f5"]
        X = np.random.default_rng(7).normal(size=(300, 5))
        X[5, 2] = np.nan                                                    # NaN feature left out of the bundle
        y = np.random.default_rng(8).integers(0, 3, 300)
        enc = H.Encoder(sp, names, levels=16).fit(X[:200])
        clf = H.Classifier(sp, 3)
        for i in range(200):
            clf.update(enc.record(X[i]), int(y[i]))
        state = {"roles": enc.roles, "levels": enc.levels, "tie": sp.tie, "acc": clf.acc, "lo": enc.lo, "hi": enc.hi,
                 "meta": np.array([sp.D, sp.seed, enc.L, 3])}                   # exactly the layout of mm/jobs.py job_hdc
        return names, X, enc, clf, state

    def test_artifact_roundtrip_from_state(self):
        names, X, enc, clf, state = self._artifact()
        td = TempData()
        self.addCleanup(td.close)
        aid = AR.save("XAUUSD", "hdc_dir3", state, {"status": "CANDIDATE", "features": names})
        st, man = AR.load("XAUUSD", "hdc_dir3", aid)                          # through the npz store (dtypes as written)
        sp2, enc2, clf2 = H.from_state(st, man["features"])
        self.assertEqual((sp2.D, enc2.L, clf2.C), (256, 16, 3))
        for i in range(200, 250):
            c1, m1, s1 = clf.predict(enc.record(X[i]))
            c2, m2, s2 = clf2.predict(enc2.record(X[i]))
            self.assertEqual((c1, m1), (c2, m2))
            self.assertTrue(np.array_equal(s1, s2))

    def test_basis_mismatch_is_refused(self):
        names, _, _, _, state = self._artifact()
        bad = dict(state, roles=state["roles"][[1, 0, 2, 3, 4]])              # two roles swapped
        with self.assertRaisesRegex(ValueError, "HDC_ARTIFACT_BASIS_MISMATCH"):
            H.from_state(bad, names)
        with self.assertRaisesRegex(ValueError, "HDC_ARTIFACT_BASIS_MISMATCH"):
            H.from_state(state, names[:4])                                   # other feature list -> other role set
        with self.assertRaises(ValueError):
            H.from_state(dict(state, acc=state["acc"][:2]), names)            # accumulator shape != (C, D)

    def test_smoke_uses_from_state(self):
        src = (ROOT / "backend" / "masterquo" / "modelhub" / "smoke" / "mm.py").read_text(encoding="utf-8")
        body = src[src.index("def _hdc_dir3"):src.index("def _event_engine_dir3")]
        self.assertIn("H.from_state(", body)
        self.assertNotIn("H.Encoder(", body)                                   # no hand-made copy of the reconstruction


# ---------------------------------------------------------------------------------------------------------------- I0355
class TestI0355InventoryUnitTestEvidence(unittest.TestCase):
    def test_every_mapped_test_class_exists(self):
        self.assertTrue(INV.UNIT_TESTS)
        for mid, refs in INV.UNIT_TESTS.items():
            self.assertIn(mid, INV.by_id(), mid)
            for ref in refs:
                path, _, cls = ref.partition("::")
                tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
                self.assertIn(cls, {n.name for n in tree.body if isinstance(n, ast.ClassDef)}, ref)

    def test_unit_tested_only_with_mapped_test(self):
        fake = {"n": 99, "id": "zzz", "name": "x", "version": "X-1", "category": "RULE_STRATEGY", "files": ["backend/masterquo/mm/zzz.py"]}
        with mock.patch.object(INV, "MODULES", INV.MODULES + [fake]):
            rows = {r["id"]: r for r in INV.merge_run(None)}
        self.assertNotIn("UNIT_TESTED", rows["zzz"]["status_chain"])
        self.assertIsNone(rows["zzz"].get("unit_tests"))
        self.assertIn("UNIT_TESTED", rows["gpr"]["status_chain"])
        self.assertEqual(rows["gpr"]["unit_tests"], INV.UNIT_TESTS["gpr"])
        live = [m["id"] for m in INV.MODULES if not m.get("blocked")]
        self.assertEqual(sorted(live), sorted(INV.UNIT_TESTS))               # today: every implemented module keeps its UNIT_TESTED


# ---------------------------------------------------------------------------------------------------------------- I0357 / I0358 (service)
def _svc():
    from masterquo.mm.service import MMService
    return MMService(SimpleNamespace())


class TestI0357GprLiveRetune(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        self.b = FX._fixture_bars()

    def test_live_retunes_every_24_bars_like_walk_forward(self):
        from masterquo.mm import gpr as G
        svc = _svc()
        calls = []
        orig = G.GPModel.refit

        def rec(model, c, T, tune, window_id=""):
            calls.append((id(model), bool(tune)))
            return orig(model, c, T, tune, window_id)
        outs = []
        with mock.patch.object(G.GPModel, "refit", rec):
            for n in (600, 601, 601, 623, 624):                                # the same bar twice (cache expiry) does not count
                calls.clear()
                outs.append(svc._gpr("XAUUSD", self.b.slice(0, n), "OK"))
                wf_ids = {i for i, _ in calls} & {id(svc._gpr_wf["XAUUSD"]["model"])}
                self.assertEqual(len(wf_ids), 1)
                outs[-1]["_wf_flags"] = [t for i, t in calls if i in wf_ids]
        self.assertEqual([o["_wf_flags"] for o in outs], [[True], [False], [False], [False], [True]])
        wf = [o["walk_forward"] for o in outs]
        self.assertEqual([w["retuned"] for w in wf], [True, False, False, False, True])
        self.assertEqual([w["bars_since_tune"] for w in wf], [0, 1, 1, 23, 0])
        self.assertEqual(wf[0]["retune_every"], 24)
        self.assertEqual(wf[1]["hp"], wf[0]["hp"])                             # between retunes: fixed hyper-parameters
        led = svc._ledger("XAUUSD")
        rows = led.rows("gpr_logret:LIVE_RETUNE24")
        self.assertEqual(len(rows), 4)                                         # one forecast per bar (bar 601 logged once)
        self.assertEqual({r["feature_schema"] for r in rows}, {"GPR_LAG1_LOGRET;retune=24"})

    def test_quant_facing_forecast_unchanged(self):
        """The top-level mean/sd (Quant column fc:mm:gpr_logret) is still the per-bar full grid fit: old MetaModels get the same inputs."""
        from masterquo.mm import gpr as G
        svc = _svc()
        for n in (600, 601, 640):
            b = self.b.slice(0, n)
            g = svc._gpr("XAUUSD", b, "OK")
            m = G.GPModel(G.GPRConfig())
            m.refit(np.asarray(b.c, float), n - 1, True)
            p = m.predict(math.log(b.c[n - 1] / b.c[n - 2]), b.c[n - 1])
            self.assertEqual((g["mean_logret"], g["sd"]), (p["mean_logret"], p["sd"]))
        self.assertEqual(len(svc._ledger("XAUUSD").rows("gpr_logret:LIVE")), 3)


class TestI0358LedgerOutOfWindow(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_rows_older_than_window_are_not_rescanned(self):
        led = Ledger(Path(self.td.dir) / "l.sqlite")
        kw = {"model_id": "m", "artifact_id": None, "feature_schema": "f", "symbol": "XAUUSD", "timeframe": "M5", "horizon": "3bars", "kind": "K",
              "payload": {}, "quality": "OK"}
        led.log(pred_id="old", source_ts=1000, available_at=1300, matures_at=2000, **kw)
        led.log(pred_id="new", source_ts=5000, available_at=5300, matures_at=6000, **kw)
        calls = []
        res = lambda r: calls.append(r["pred_id"])
        self.assertEqual(led.mature(1e9, res, "m", min_source_ts=4000), 0)
        self.assertEqual(calls, ["new"])
        self.assertEqual(len(led.pending("m")), 2)                             # nothing deleted or marked: still unscored
        calls.clear()
        led.mature(1e9, res, "m")
        self.assertEqual(sorted(calls), ["new", "old"])                       # without the bound: old behaviour

    def test_service_passes_window_start(self):
        svc = _svc()
        b = FX._fixture_bars().slice(300, 600)
        seen = []
        orig = Ledger.mature

        def spy(led, observed_until, resolver, model_id=None, min_source_ts=None):
            seen.append((model_id, min_source_ts))
            return orig(led, observed_until, resolver, model_id, min_source_ts=min_source_ts)
        with mock.patch.object(Ledger, "mature", spy):
            svc._gpr("XAUUSD", b, "OK")
        self.assertIn(("gpr_logret:LIVE", float(b.t[0])), seen)
        self.assertIn(("gpr_logret:LIVE_RETUNE24", float(b.t[0])), seen)


# ---------------------------------------------------------------------------------------------------------------- native parity (fixtures)
class _Ref(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        cls.ref = Path(cls.td.dir) / "fx"
        cls.export = FX.export(cls.ref)

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def _parity(self, nat: dict) -> dict:
        p = Path(self.td.dir) / "PMW_MM_NATIVE.txt"
        p.write_text(json.dumps(nat))
        return FX.parity(p, self.ref)

    def _legacy_native(self) -> dict:
        """The JSON the pre-fix PMW_MM_SelfTest.mq5 wrote (kalman, gpr, hdc booleans, breakout NONE) - built from the references."""
        f = lambda x: None if x == "nan" else float(x)
        k, g, b = (_rows(self.ref / n) for n in ("mm_ref_kalman.csv", "mm_ref_gpr.csv", "mm_ref_breakout.csv"))
        return {"kalman": [[int(r[0])] + [f(x) for x in r[1:7]] + [r[7]] for r in k], "gpr": [[int(r[0])] + [f(x) for x in r[1:]] for r in g],
                "hdc": {"parsed": True, "hamming": True, "bind": True, "permute": True, "bundle3": True, "bundle2_tie": True, "all_pass": True},
                "breakout": [[int(r[0]), r[1], float(r[2]), float(r[3])] for r in b]}


class TestNativeReferenceContract(_Ref):
    def test_expected_native_passes_and_legacy_native_fails(self):
        res = self._parity(FX.expected_native(self.ref))
        self.assertEqual(res["status"], "NATIVE_PARITY_PASS", res["gates"])
        res = self._parity(self._legacy_native())
        self.assertEqual(res["status"], "NATIVE_PARITY_FAIL")
        self.assertTrue(res["gates"]["kalman"] and res["gates"]["gpr"] and res["gates"]["breakout"])
        for gname in ("gpr_tune", "hdc", "hdc_acc", "breakout_SESSION_VWAP", "breakout_SMA", "breakout_SMMA", "breakout_NONE", "tsvp", "stack"):
            self.assertIs(res["gates"][gname], False, gname)                 # a missing section is a FAIL, never a pass

    def test_selftest_writes_every_section_parity_reads(self):
        src = SELFTEST.read_text(encoding="utf-8")
        for key in ("gpr_tune", "hdc_acc", "breakout_modes", "tsvp", "stack", "hamming_ab", "bind_ab", "perm_a_77", "bundle_abc", "bundle_ab_tie"):
            self.assertIn(f'\\"{key}\\"', src, key)
        for fname in ("mm_ref_hdc_acc.csv", "mm_fixture_ticks.csv", "mm_ref_tsvp.csv", "mm_ref_stack.csv"):
            self.assertIn(fname, src)
            self.assertTrue((self.ref / fname).exists(), fname)

    def test_missing_reference_file_is_reported(self):
        import shutil
        d = Path(self.td.dir) / "fx_old"
        shutil.copytree(self.ref, d)
        (d / "mm_ref_tsvp.csv").unlink()
        p = Path(self.td.dir) / "nat2.txt"
        p.write_text(json.dumps(FX.expected_native(self.ref)))
        res = FX.parity(p, d)
        self.assertEqual(res["status"], "REFERENCE_INCOMPLETE")
        self.assertIn("mm_ref_tsvp.csv", res["missing"])


class TestI0490GprParityGate(_Ref):
    def test_lml_enters_the_gate(self):
        nat = self._legacy_native()
        self.assertTrue(self._parity(nat)["gates"]["gpr"])
        nat["gpr"][1][7] += 1.0                                                # mean / var identical, LML off by 1
        res = self._parity(nat)
        self.assertIs(res["gates"]["gpr"], False)
        self.assertGreater(res["gpr_max_rel_lml_diff"], 1e-3)

    def test_grid_search_reference_and_gate(self):
        from masterquo.mm import gpr as G
        rows = _rows(self.ref / "mm_ref_gpr_tune.csv")
        self.assertEqual([int(r[0]) for r in rows], [300, 700, 900, 1200, 1499])
        c = np.array([float(r[4]) for r in _rows(self.ref / "mm_fixture_bars.csv")])          # what the MQL5 script reads
        cfg = G.GPRConfig(window=60, horizon=3, auto_tune=True)
        self.assertEqual((cfg.grid_ell, cfg.grid_signal, cfg.grid_noise), (G.GPRConfig().grid_ell, G.GPRConfig().grid_signal, G.GPRConfig().grid_noise))
        for r in rows:
            m = G.GPModel(cfg)
            res = m.refit(c, int(r[0]), True)
            self.assertEqual([float(r[1]), float(r[2]), float(r[3])], [res["hp"]["ell"], res["hp"]["signal_var"], res["hp"]["noise_var"]])
        self.assertIn({"ell": 1, "signal_var": 0.01, "noise_var": 1.0}, [{"ell": float(r[1]), "signal_var": float(r[2]), "noise_var": float(r[3])}
                                                                           for r in rows])          # not every probe at the grid edge
        nat = FX.expected_native(self.ref)
        nat["gpr_tune"][2][1] = 2.0                                            # another ell chosen natively
        self.assertIs(self._parity(nat)["gates"]["gpr_tune"], False)
        nat = FX.expected_native(self.ref)
        nat["gpr_tune"][0][4] += 1e-6
        self.assertIs(self._parity(nat)["gates"]["gpr_tune"], False)
        nat = FX.expected_native(self.ref)
        del nat["gpr_tune"]
        self.assertIs(self._parity(nat)["gates"]["gpr_tune"], False)


class TestI0497BreakoutModesParity(_Ref):
    def test_four_mode_references(self):
        from masterquo.mm import breakout_zones as BZ
        for m in BZ.FILTERS:
            self.assertGreater(len(_rows(self.ref / f"mm_ref_breakout_{m}.csv")), 10, m)
        self.assertEqual((self.ref / "mm_ref_breakout.csv").read_text(), (self.ref / "mm_ref_breakout_NONE.csv").read_text())   # old file kept
        self.assertNotEqual(_rows(self.ref / "mm_ref_breakout_SESSION_VWAP.csv"), _rows(self.ref / "mm_ref_breakout_NONE.csv"))

    def test_gate_per_mode(self):
        nat = self._legacy_native()
        self.assertIs(self._parity(nat)["gates"]["breakout_SESSION_VWAP"], False)
        nat = FX.expected_native(self.ref)
        nat["breakout_modes"]["SMMA"] = nat["breakout_modes"]["SMMA"][:-1]
        g = self._parity(nat)["gates"]
        self.assertEqual((g["breakout_SMMA"], g["breakout_SMA"], g["breakout_SESSION_VWAP"], g["breakout_NONE"]), (False, True, True, True))


class TestI0505HdcAccumulatorParity(_Ref):
    def test_reference_matches_python_classifier(self):
        kv = _kv(self.ref / "mm_ref_hdc_acc.csv")
        D, C = int(kv["D"]), int(kv["C"])
        sp = H.Space(D, seed=7)
        hexv = lambda s: np.array([int(w, 16) for w in s.split(" ")], dtype=np.uint64)
        self.assertTrue(np.array_equal(hexv(kv["tie"]), sp.tie))
        clf = H.Classifier(sp, C)
        for u in range(int(kv["n_updates"])):
            clf.update(hexv(kv[f"u{u}_v"]), int(kv[f"u{u}_y"]))
        clf.finalize()
        tie_bits = 0
        for k in range(C):
            self.assertEqual(kv[f"proto{k}"], " ".join(f"{int(w):016x}" for w in clf.protos[k]))
            tie_bits += int(np.sum(clf.acc[k] == 0))
        self.assertGreater(tie_bits, 0)                                        # the tie vector is exercised
        preds = set()
        for q in range(int(kv["n_queries"])):
            c, m, s = clf.predict(hexv(kv[f"q{q}"]))
            preds.add(c)
            self.assertEqual(int(kv[f"q{q}_pred"]), c)
            self.assertEqual(float(kv[f"q{q}_margin"]), m)
            self.assertEqual([float(x) for x in kv[f"q{q}_sims"].split(" ")], list(s))
        self.assertGreater(len(preds), 1)

    def test_gate(self):
        nat = FX.expected_native(self.ref)
        self.assertTrue(self._parity(nat)["gates"]["hdc_acc"])
        p = nat["hdc_acc"]["protos"][1]
        nat["hdc_acc"]["protos"][1] = ("0" if p[0] != "0" else "1") + p[1:]
        self.assertIs(self._parity(nat)["gates"]["hdc_acc"], False)
        nat = FX.expected_native(self.ref)
        nat["hdc_acc"]["queries"][0][0] = (nat["hdc_acc"]["queries"][0][0] + 1) % 3
        self.assertIs(self._parity(nat)["gates"]["hdc_acc"], False)


class TestI0506HdcParityIndependent(_Ref):
    def test_python_compares_the_words(self):
        nat = FX.expected_native(self.ref)
        self.assertTrue(self._parity(nat)["gates"]["hdc"])
        w = nat["hdc"]["bind_ab"]
        nat["hdc"]["bind_ab"] = w[:-1] + ("0" if w[-1] != "0" else "1")          # one hex digit off, self-check still claims PASS
        self.assertTrue(nat["hdc"]["all_pass"])
        res = self._parity(nat)
        self.assertIs(res["gates"]["hdc"], False)
        self.assertIs(res["hdc_checks"]["bind_ab"], False)
        nat = FX.expected_native(self.ref)
        nat["hdc"]["hamming_ab"] += 1
        self.assertIs(self._parity(nat)["gates"]["hdc"], False)
        self.assertIs(self._parity(self._legacy_native())["gates"]["hdc"], False)   # booleans only: not evidence any more


class TestI0508StateStackHarness(_Ref):
    def test_header_is_included_by_a_program(self):
        inc = [p.name for p in MQL5_DIR.rglob("*.mq5") if re.search(r"#include\s*<PMW\\PMW_StateStack\.mqh>", p.read_text(encoding="utf-8"))]
        self.assertIn("PMW_MM_SelfTest.mq5", inc)

    def test_reference_from_python_state_stack(self):
        from masterquo.mm import event_engine as EE
        kv = _kv(self.ref / "mm_ref_stack.csv")
        S, D, n = int(kv["S"]), int(kv["D"]), int(kv["n_push"])
        fl = lambda s: np.array([np.float32(float(x)) for x in s.split(" ")], dtype=np.float32)
        st = EE.StateStack(S, D, backend="cpu")
        q = fl(kv["q"])
        checks = [int(x) for x in kv["checks"].split(" ")]
        self.assertTrue(any(c < S for c in checks) and any(c > S for c in checks))   # invalid slots and the shift are both exercised
        for i in range(1, n + 1):
            st.push(fl(kv[f"p{i - 1}"]))
            if i in checks:
                self.assertEqual([float(x) for x in kv[f"c{i}_raw"].split(" ")], list(st.corr(q, False)))
                self.assertEqual([float(x) for x in kv[f"c{i}_l2"].split(" ")], list(st.corr(q, True)))
                self.assertEqual([int(x) for x in kv[f"c{i}_valid"].split(" ")], list(st.snapshot()[1]))

    def test_gates_cpu_and_opencl(self):
        nat = FX.expected_native(self.ref)
        res = self._parity(nat)
        self.assertTrue(res["gates"]["stack"])
        self.assertNotIn("stack_opencl", res["gates"])                        # no GPU device in the terminal -> reported, not gated
        self.assertIn("NOT_AVAILABLE", res["stack_opencl"])
        nat["stack"]["cpu"]["checks"][1][1][0] += 1e-2
        self.assertIs(self._parity(nat)["gates"]["stack"], False)
        nat = FX.expected_native(self.ref)
        nat["stack"]["opencl"] = json.loads(json.dumps(nat["stack"]["cpu"]))
        nat["stack"]["opencl"]["backend"] = "OPENCL"
        nat["stack"]["opencl"]["checks"][0][2][0] += 1e-2
        res = self._parity(nat)
        self.assertIs(res["gates"]["stack_opencl"], False)

    def test_inventory_scope(self):
        rows = {r["id"]: r for r in INV.merge_run(None)}
        self.assertIn("HEADER_ONLY", rows["event_engine"]["native"])


class TestI0511TsvpParity(_Ref):
    def _ticks(self) -> dict[int, tuple[int, list[dict]]]:
        reads: dict[int, tuple[int, list[dict]]] = {}
        names = ("read", "read_until", "time_msc", "bid", "ask", "last", "volume", "volume_real", "flags")
        for r in _rows(self.ref / "mm_fixture_ticks.csv"):
            d = dict(zip(names, r))
            t = {"time_msc": int(d["time_msc"]), "bid": float(d["bid"]), "ask": float(d["ask"]), "last": float(d["last"]), "volume": int(d["volume"]),
                 "volume_real": float(d["volume_real"]), "flags": int(d["flags"])}
            reads.setdefault(int(d["read"]), (int(d["read_until"]), []))[1].append(t)
        return reads

    def test_reference_from_fixture_ticks(self):
        from masterquo.mm import tsvp as TV
        kv = _kv(self.ref / "mm_ref_tsvp.csv")
        reads = self._ticks()
        self.assertGreaterEqual(len(reads), 4)
        for name in kv["configs"].split(" "):
            cfg = TV.TSVPConfig(source={0: "TICK_ACTIVITY_PROXY", 1: "ACTUAL_TRADE_VOLUME"}[int(kv[f"{name}_source"])],
                                bucket_mode={0: "MANUAL", 1: "ATR"}[int(kv[f"{name}_bucket_mode"])], bucket_ticks=int(kv[f"{name}_bucket_ticks"]),
                                atr_mult=float(kv[f"{name}_atr_mult"]), tick=float(kv["tick"]),
                                proxy_event="ANY_QUOTE" if int(kv[f"{name}_any_quote"]) else "BID_CHANGE")
            p = TV.Profile(cfg, int(kv["start_ms"]), int(kv["end_ms"]), float(kv[f"{name}_atr"]) if cfg.bucket_mode == "ATR" else None)
            got = []
            for i in sorted(reads):
                until, ticks = reads[i]
                r = p.ingest(ticks, None if until < 0 else until)
                got.append([r["added"], r["state"], len(p.render_pass(10 ** 9)["draw"]), r["status"]])
            exp = json.loads(kv[f"{name}_expected"])
            self.assertEqual(got, exp["reads"], name)
            self.assertEqual([[k, v, c] for k, v, c in p.map.items()], exp["buckets"], name)
            self.assertEqual((p.poc, p.counted, p.map.rehashes), (exp["poc"], exp["counted"], exp["rehashes"]), name)
        proxy = json.loads(kv["proxy_expected"])
        self.assertGreater(proxy["rehashes"], 0)                               # the open-addressing growth is exercised
        self.assertGreater(proxy["ignored"][3], 0)                             # overlapping reads: duplicates reconciled
        self.assertGreater(proxy["ignored"][0], 0)                             # ticks outside the closed session interval
        self.assertEqual(proxy["reads"][-1][0], 0)                             # a full re-read adds nothing
        self.assertIn("FULL_REDRAW_REQUIRED", [r[1] for r in proxy["reads"][1:]])
        self.assertIn("PARTIAL_UPDATE_PENDING", [r[1] for r in proxy["reads"][1:]] + [r[1] for r in json.loads(kv["actual_expected"])["reads"][1:]])

    def test_gate(self):
        nat = FX.expected_native(self.ref)
        self.assertTrue(self._parity(nat)["gates"]["tsvp"])
        nat["tsvp"]["actual"]["buckets"][0][2] += 1
        self.assertIs(self._parity(nat)["gates"]["tsvp"], False)
        nat = FX.expected_native(self.ref)
        nat["tsvp"]["proxy"]["reads"][1][1] = "CLEAN"
        self.assertIs(self._parity(nat)["gates"]["tsvp"], False)
        self.assertIs(self._parity(self._legacy_native())["gates"]["tsvp"], False)


# ---------------------------------------------------------------------------------------------------------------- I0499 / I0505 / I0508 inventory
class TestI0499I0505InventoryNativeScope(unittest.TestCase):
    def test_native_from_scope(self):
        rows = {r["id"]: r for r in INV.merge_run(None)}
        self.assertIn("robust_vol: PYTHON_ONLY", rows["breakout_zones"]["native"])
        self.assertIn("PRIMITIVES_ONLY", rows["hdc"]["native"])
        self.assertIn("HEADER_ONLY", rows["event_engine"]["native"])
        flat = "IMPLEMENTED (MQL5 nieskompilowany: brak MetaEditor/terminala w tym środowisku)"
        for r in rows.values():
            self.assertNotEqual(r.get("native"), flat, r["id"])
        for m in INV.MODULES:                                                  # every module with an mql5/ file declares its native scope
            if any(f.startswith("mql5/") for f in m.get("files", [])):
                self.assertTrue(m.get("native_scope"), m["id"])
            else:
                self.assertIsNone(rows[m["id"]].get("native"), m["id"])


# ---------------------------------------------------------------------------------------------------------------- I0545
class TestI0545MmPromoteGuard(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def _save(self, **man) -> str:
        return AR.save("XAUUSD", "unit_model", {"w": np.arange(3.0)}, {"status": "VALIDATED_SHADOW", **man})

    def test_status_string_alone_is_not_enough(self):
        for man in ({}, {"gates": None, "data_kind": "REAL_USER_DATA"}, {"gates": {}, "data_kind": "REAL_USER_DATA"},
                    {"gates": {"a": True, "b": False}, "data_kind": "REAL_USER_DATA"}, {"gates": {"a": "True"}, "data_kind": "REAL_USER_DATA"},
                    {"gates": {"a": True}, "data_kind": "SYNTHETIC_TEST"}, {"gates": {"a": True}, "data_kind": "SYNTHETIC"},
                    {"gates": {"a": True}}):
            aid = self._save(**man)
            with self.assertRaisesRegex(AR.ArtifactError, "NOT_VALIDATED_GATES", msg=str(man)):
                AR.promote_shadow("XAUUSD", "unit_model", aid, "test")
        self.assertEqual(AR.read_pointer("XAUUSD")["active"], {})

    def test_job_style_artifact_promotes(self):
        aid = self._save(gates={"a": True, "b": True}, data_kind="REAL_USER_DATA")
        self.assertEqual(AR.promote_shadow("XAUUSD", "unit_model", aid, "test")["active"]["unit_model"], aid)

    def test_jobs_save_still_promotes_a_passed_real_model(self):
        from masterquo.mm import jobs as J
        ctx = SimpleNamespace(synthetic=False, inst="XAUUSD", snap=SimpleNamespace(snapshot_id="S1", data_kind="REAL_USER_DATA"), seed=1,
                              profile="quick")
        aid, st = J._save(ctx, "gpr_logret", {"w": np.zeros(2)}, {"gates": {"min_scored": True, "cov1_band": True}}, True)
        self.assertEqual((st, AR.read_pointer("XAUUSD")["active"].get("gpr_logret")), ("VALIDATED_SHADOW", aid))


if __name__ == "__main__":
    unittest.main()
