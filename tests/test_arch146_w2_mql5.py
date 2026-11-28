"""1.46 arch, wave 2 - group mql5: native MQL5 sources and their Python counterparts (fixtures, parity, status). MetaEditor / MT5 are not
available here, so the MQL5 side is checked statically (source text) and, where a Python emulation exists, through it; the Python
writers / readers / parity gates are tested directly. Nothing here sends an order - the native programs have no trade API at all."""
from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from _env import ROOT
from masterquo.lab import minirocket_v2 as MR
from masterquo.mm import fixtures as FX
from masterquo.mm import gpr as G
from masterquo.mm import inventory as INV

MQL5 = ROOT / "mql5"
MM = MQL5 / "MasterModels"
MR2 = MQL5 / "MiniRocketV2"
SKTIME = ROOT / "tests" / "fixtures" / "minirocket" / "sktime_fixture.npz"
sys.path.insert(0, str(ROOT / "tools"))


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(src: str) -> str:
    """MQL5 source without // comments (string literals kept)."""
    return re.sub(r"//[^\n]*", "", src)


def _func(src: str, header: str) -> str:
    """Body of the function whose definition starts with `header` (brace matching on the comment-free source)."""
    c = _code(src)
    i = c.index(header)
    j = c.index("{", i)
    depth = 0
    for k in range(j, len(c)):
        depth += {"{": 1, "}": -1}.get(c[k], 0)
        if depth == 0:
            return c[j:k + 1]
    raise AssertionError(f"unbalanced body of {header}")


# ---------------------------------------------------------------------------------------------------------------- I0390
class TestI0390HdcHeaderComment(unittest.TestCase):
    def test_header_does_not_claim_an_artifact_reader(self):
        src = _src(MM / "Include" / "PMW" / "PMW_HDC.mqh")
        self.assertNotIn("loaded from the artifact", src)
        self.assertIn("mm_ref_hdc.csv", src)
        self.assertIn("NO MQL5 reader of the hdc_dir3", src)
        # the claim is true: no MQL5 program reads state.npz / an hdc_dir3 artefact
        for p in MQL5.rglob("*.mq*"):
            self.assertNotIn("state.npz", _code(_src(p)), p.name)


# ---------------------------------------------------------------------------------------------------------------- I0482
class TestI0482MR2IndicatorTimeframe(unittest.TestCase):
    def test_indicator_is_m1_only_and_writes_the_real_period(self):
        src = _src(MR2 / "Indicators" / "PMW_MR2_Indicator.mq5")
        self.assertIn("_Period != PERIOD_M1", _func(src, "int OnInit()"))
        call = next(ln for ln in _code(src).splitlines() if "MR2WriteResult(" in ln)
        self.assertNotIn('"M1"', call)                                         # was a literal "M1" whatever the chart period
        self.assertIn("EnumToString((ENUM_TIMEFRAMES)_Period)", _func(src, "int OnCalculate("))

    def test_importer_rejects_another_timeframe_and_names_the_clock(self):
        with tempfile.TemporaryDirectory() as d:
            sha = "ab" * 32
            now = time.time()
            p = Path(d) / MR.NativeResultImporter.NAME
            imp = MR.NativeResultImporter(d, sha, "XAUUSD-", "M1", 120)
            MR.write_result(p, 5, sha, "XAUUSD-", "M5", int(now) - 60, int(now), "BROKER_WALL_TIME", np.zeros(12))
            r = imp.poll(now)
            self.assertEqual((r["status"], r["reason"]), ("REJECTED", "CONTEXT_MISMATCH"))
            MR.write_result(p, 6, sha, "XAUUSD-", "M1", int(now) - 60, int(now), "BROKER_WALL_TIME", np.zeros(12))
            r = imp.poll(now)
            self.assertEqual(r["status"], "IMPORTED")
            self.assertEqual(r["bar_time_utc"], int(now) - 60)                  # API key kept
            self.assertEqual(r["bar_time_broker"], int(now) - 60)               # explicit alias for broker wall time
            MR.write_result(p, 7, sha, "XAUUSD-", "M1", int(now) - 60, int(now), "UTC", np.zeros(12))
            self.assertNotIn("bar_time_broker", imp.poll(now))


# ---------------------------------------------------------------------------------------------------------------- I0483 / I0484 / I0485
def _sktime_mr():
    with np.load(SKTIME) as z:
        X, biases = z["X"], z["biases"]
    mr = MR.MiniRocketV2().configure(X.shape[1], 10000, 32)
    mr.biases = biases.astype(np.float32)
    mr.fit_idx = np.zeros(len(mr.lay["dilations"]) * 84, np.int32)
    return mr, X


def _native_quantile(sorted_c: np.ndarray, q: float, f32diff: bool) -> float:
    """Python emulation of CMiniRocketV2::Quantile (PMW_MR2_Core.mqh); f32diff = the 1.46 rule (b - a on the float32 operands)."""
    n = len(sorted_c)
    if n == 1:
        return float(sorted_c[0])
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    fr = pos - lo
    a, b = float(sorted_c[lo]), float(sorted_c[hi])
    dba = float(np.float32(sorted_c[hi]) - np.float32(sorted_c[lo])) if f32diff else b - a
    return b - dba * (1.0 - fr) if fr >= 0.5 else a + dba * fr


def _native_fit(mr: MR.MiniRocketV2, X: np.ndarray, idx: np.ndarray, f32diff: bool) -> np.ndarray:
    """Python emulation of CMiniRocketV2::Fit with frozen indices: ArraySort + Quantile per (dilation, kernel)."""
    b = np.zeros(mr.lay["F"], np.float32)
    f0 = 0
    for di, d in enumerate(mr.lay["dilations"]):
        nf = mr.lay["counts"][di]
        for k in range(84):
            c = np.sort(MR.conv_full(np.asarray(X, np.float32)[idx[di * 84 + k]][None, :], d, k)[0])
            for f in range(nf):
                b[f0 + f] = np.float32(_native_quantile(c, float(mr.lay["quantiles"][f0 + f]), f32diff))
            f0 += nf
    return b


@unittest.skipUnless(SKTIME.exists(), "brak fixture sktime")
class TestI0483MR2NativeLayoutCarried(unittest.TestCase):
    def test_fixture_and_train_file_carry_the_python_layout(self):
        mr, X = _sktime_mr()
        with tempfile.TemporaryDirectory() as d:
            MR.export_fixture(Path(d) / "fx.bin", mr, X)
            a = MR.read_model_bin(Path(d) / "fx.bin")
            self.assertEqual(a["DILS"].tolist(), mr.lay["dilations"])
            self.assertEqual(a["CNTS"].tolist(), mr.lay["counts"])
            self.assertEqual(a["QUAN"].tobytes(), np.asarray(mr.lay["quantiles"], "<f4").tobytes())
            # a non-default L where the MQL5 formula and numpy disagree: (L=25, 840, 32) is [1, 2] in Python
            rng = np.random.default_rng(4)
            Xs = np.cumsum(rng.normal(0, 1, (6, 25)), axis=1).astype(np.float32)
            Y = rng.integers(-1, 3, (6, 2)).astype(np.int32)
            R = rng.normal(0, 1, (6, 2))
            info = MR.export_train(Path(d) / "train.bin", Xs, Y, R, requested=840)
            t = MR.read_model_bin(Path(d) / "train.bin")
            lay = MR.layout(25, 840, 32)
            self.assertEqual(lay["dilations"], [1, 2])
            self.assertEqual((t["DILS"].tolist(), t["CNTS"].tolist(), info["F"]), (lay["dilations"], lay["counts"], lay["F"]))
            self.assertEqual(t["QUAN"].tobytes(), np.asarray(lay["quantiles"], "<f4").tobytes())

    def test_native_scripts_take_the_layout_from_the_file(self):
        fmt = _src(MR2 / "Include" / "PMW" / "PMW_MR2_Format.mqh")
        self.assertIn("bool MR2ReadLayout(", fmt)
        for f in ("PMW_MR2_SelfTest.mq5", "PMW_MR2_Fit.mq5"):
            body = _func(_src(MR2 / "Scripts" / f), "void OnStart()")
            self.assertIn("MR2ReadLayout(", body, f)
            self.assertIn("SetLayout(", body, f)
            self.assertLess(body.index("MR2ReadLayout("), body.index("Configure(L, 10000, 32)"), f)   # Configure only as the fallback

    def test_configure_formula_follows_numpy_logspace(self):
        body = _func(_src(MR2 / "Include" / "PMW" / "PMW_MR2_Core.mqh"), "int               Configure(")
        self.assertIn("double e = i * step;", body)
        self.assertIn("if(tmax > 1 && i == tmax - 1) e = maxExp;", body)       # was unconditional: tmax == 1 gave 2^maxExp

        def mql(L, req, md):                                                   # emulation of the 1.46 rule (C log / pow)
            fpk = req // 84
            tmax = min(fpk, md)
            mx = math.log((L - 1) / 8.0) / math.log(2.0) if L > 9 else 0.0
            step = mx / (tmax - 1) if tmax > 1 else 0.0
            raw = [int(math.pow(2.0, mx if (tmax > 1 and i == tmax - 1) else i * step)) for i in range(tmax)]
            return sorted(set(raw))
        for L in range(9, 300):                                                # a single dilation: numpy logspace(num=1) = [1]
            self.assertEqual(mql(L, 84, 32), MR.layout(L, 84, 32)["dilations"], L)


@unittest.skipUnless(SKTIME.exists(), "brak fixture sktime")
class TestI0484MR2FixtureCarriesFitBiases(unittest.TestCase):
    def test_fixture_carries_frozen_fit_windows_and_python_biases(self):
        mr, X = _sktime_mr()
        frozen = mr.biases.copy()
        with tempfile.TemporaryDirectory() as d:
            info = MR.export_fixture(Path(d) / "fx.bin", mr, X)
            a = MR.read_model_bin(Path(d) / "fx.bin")
        self.assertEqual(mr.biases.tobytes(), frozen.tobytes())                  # the caller's frozen sktime biases untouched
        idx = MR.fit_window_indices(len(X), len(mr.lay["dilations"]), MR.FIXTURE_FIT_SEED)
        self.assertEqual(a["FIDX"].tolist(), idx.tolist())
        ref = MR.MiniRocketV2()
        ref.lay = dict(mr.lay)
        ref.fit(X, indices=idx)
        self.assertEqual(a["BFIT"].tobytes(), ref.biases.astype("<f4").tobytes())
        self.assertEqual(info["fit_bias_sha256"], ref.bias_hash())
        # emulated native Fit: the 1.46 quantile rule reproduces BFIT exactly, the old double-difference rule does not
        new = _native_fit(mr, X, idx, f32diff=True)
        old = _native_fit(mr, X, idx, f32diff=False)
        self.assertTrue(np.array_equal(new, a["BFIT"]))
        self.assertGreaterEqual(int((old != a["BFIT"]).sum()), 1)

    def test_quantile_guard_against_numpy(self):
        rng = np.random.default_rng(11)
        for _ in range(200):
            c = np.sort((rng.normal(0, 1, 128) * 10.0 ** rng.integers(-4, 4)).astype(np.float32))
            for q in rng.random(8).astype(np.float32):
                ref = float(np.quantile(c, np.array([float(q)], dtype=np.float64))[0])     # the call shape of MiniRocketV2.fit
                self.assertEqual(_native_quantile(c, float(q), True), ref)

    def test_native_sources(self):
        q = _func(_src(MR2 / "Include" / "PMW" / "PMW_MR2_Core.mqh"), "static double     Quantile(")
        self.assertIn("float d32 = sorted[hi] - sorted[lo];", q)
        self.assertIn("dba = (double)d32", q)
        st = _src(MR2 / "Scripts" / "PMW_MR2_SelfTest.mq5")
        for s in ("NATIVE_FIT_BIAS_PARITY", '"FIDX"', '"BFIT"', ".Fit(X, n, 0, frozen)"):
            self.assertIn(s, st)


class TestI0485MR2ExportTrainBounds(unittest.TestCase):
    def test_export_train_refuses_l_above_uchar_range(self):
        rng = np.random.default_rng(1)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(MR.MRError, "L_TOO_LONG_FOR_NATIVE_FIT"):
                MR.export_train(Path(d) / "t.bin", rng.normal(0, 1, (5, 300)), np.zeros((5, 3), np.int32), np.zeros((5, 3)))
            self.assertFalse((Path(d) / "t.bin").exists())
            with self.assertRaisesRegex(MR.MRError, "HEADS_OUT_OF_RANGE"):
                MR.export_train(Path(d) / "t.bin", rng.normal(0, 1, (5, 64)), np.zeros((5, 17), np.int32), np.zeros((5, 17)))
            r = MR.export_train(Path(d) / "t.bin", rng.normal(0, 1, (5, 255)), np.zeros((5, 3), np.int32), np.zeros((5, 3)))
            self.assertEqual(r["rows"], 5)

    def test_native_fit_checks_meta_before_allocation(self):
        body = _func(_src(MR2 / "Scripts" / "PMW_MR2_Fit.mq5"), "void OnStart()")
        self.assertIn("L > 255", body)
        self.assertIn("META_OUT_OF_RANGE", body)
        self.assertLess(body.index("L > 255"), body.index("ArrayResize(X, n * L)"))
        self.assertIn("(uchar)hh[f]", body)                                     # the reason of the bound is still there


# ---------------------------------------------------------------------------------------------------------------- I0488 / I0501
def _native_from_references(ref: Path) -> dict:
    """PMW_MM_NATIVE.txt as a perfect native run would write it (built from the reference CSVs). Merge with group mm: every section of
    that group (gpr_tune, hdc words, hdc_acc, breakout_modes, tsvp, stack) is a gate too, so the perfect native is the format contract
    fixtures.expected_native (which carries the align section of I0501); the align entries are checked against the reference here."""
    nat = FX.expected_native(ref)
    al = FX._align_ref(ref / "mm_ref_align.csv")
    assert [x["k"] for x in nat["align"]] == list(al) and all(len(x["mean"]) == len(al[x["k"]]["mean"]) for x in nat["align"])
    return nat


class TestI0501MMAlignParity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_t_align_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fixture_exports_align_reference(self):
        FX.export(self.tmp)
        p = self.tmp / "mm_ref_align.csv"
        self.assertTrue(p.exists())
        lines = p.read_text(encoding="ascii").splitlines()
        self.assertEqual(sum(ln.startswith("C,") for ln in lines), len(FX.ALIGN_FIXTURE_CONFIGS))
        self.assertEqual(sum(ln.startswith("M,") for ln in lines), 1500 * len(FX.ALIGN_FIXTURE_CONFIGS))
        ref = FX._align_ref(p)
        for k, cfg in enumerate(FX.ALIGN_FIXTURE_CONFIGS):                    # every configuration has READY values
            self.assertGreater(sum(x != "nan" for x in ref[k]["mean"]), 1000, cfg.key())
        self.assertEqual({c.mode for c in FX.ALIGN_FIXTURE_CONFIGS}, {"ROLLING_MEAN", "FIXED_ANCHORED_MEAN", "SESSION_MEAN"})
        self.assertEqual({c.lookback for c in FX.ALIGN_FIXTURE_CONFIGS}, {"BARS", "ELAPSED_TIME", "SESSION"})
        self.assertEqual({c.source for c in FX.ALIGN_FIXTURE_CONFIGS}, {"CLOSE", "TYPICAL", "MEDIAN", "WEIGHTED_CLOSE"})

    def test_parity_gate_align(self):
        FX.export(self.tmp)
        nat = _native_from_references(self.tmp)
        p = self.tmp / "PMW_MM_NATIVE.txt"
        p.write_text(json.dumps(nat), encoding="utf-8")
        ok = FX.parity(p, self.tmp)
        self.assertTrue(ok["gates"]["align"], ok.get("align"))
        self.assertEqual(ok["status"], "NATIVE_PARITY_PASS")
        nat.pop("align")                                                       # an old self-test without the section
        p.write_text(json.dumps(nat), encoding="utf-8")
        r = FX.parity(p, self.tmp)
        self.assertIs(r["gates"]["align"], False)
        self.assertEqual(r["status"], "NATIVE_PARITY_FAIL")
        nat = _native_from_references(self.tmp)
        nat["align"][3]["mean"][700] += 1e-6                                   # one mean off by more than the tolerance
        p.write_text(json.dumps(nat), encoding="utf-8")
        self.assertIs(FX.parity(p, self.tmp)["gates"]["align"], False)

    def test_native_sources_share_the_core(self):
        core = _src(MM / "Include" / "PMW" / "PMW_AlignMeanCore.mqh")
        for fn in ("double PmwAmPx(", "long PmwAmSid(", "void PmwAmCompute(", "double PmwAmAtr("):
            self.assertIn(fn, core)
        ind = _src(MM / "Indicators" / "PMW_AlignMean.mq5")
        self.assertIn("#include <PMW\\PMW_AlignMeanCore.mqh>", ind)
        self.assertNotIn("double Px(", ind)                                    # no second copy of the calculation
        st = _src(MM / "Scripts" / "PMW_MM_SelfTest.mq5")
        self.assertIn("#include <PMW\\PMW_AlignMeanCore.mqh>", st)
        self.assertIn('ReadLines("mm_ref_align.csv"', st)
        self.assertIn("PmwAmCompute(t, h, l, c, n,", st)
        self.assertIn('\\"align\\":[', st)


class TestI0503AlignMeanIncremental(unittest.TestCase):
    def test_same_forming_bar_skips_the_full_recompute(self):
        body = _func(_src(MM / "Indicators" / "PMW_AlignMean.mq5"), "int OnCalculate(")
        self.assertIn("prev_calculated == rates_total", body)
        self.assertLess(body.index("prev_calculated == rates_total"), body.index("PmwAmCompute("))
        self.assertIn("if(!same_bar)", body)
        self.assertLess(body.index("if(!same_bar)"), body.index("PmwAmAtr("))     # ATR once per closed bar, not per tick
        self.assertIn("ObjectSetString(0, g_lab, OBJPROP_TEXT, txt)", body)     # the label (P&L) still refreshes every tick


MM_PROGRAMS = (("Scripts", ("PMW_MM_SelfTest", "MathFidelity_SelfTest")),
               ("Indicators", ("PMW_AlignMean", "PMW_BreakoutZones", "PMW_GPR_Forecast", "PMW_KalmanCross", "PMW_TickSessionVP", "FidelityMonitor")),
               ("Experts", ("PMW_GPR_ShadowEA", "PMW_KalmanShadowEA", "MathFidelityBenchmark_EA")))


class TestI0488MMNativeStatus(unittest.TestCase):
    def setUp(self):
        import mr2_native_status as ns
        self.ns = ns
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_t_mmnative_"))
        self.mql = self.tmp / "MQL5"
        for d in ("Scripts/PMW", "Indicators/PMW", "Experts/PMW", "Include/PMW", "Files/PMW", "Files/PMW_MM"):
            (self.mql / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _compile(self, skip=()):
        now = time.time() - 100
        for sub, names in MM_PROGRAMS:
            for n in names:
                (self.mql / sub / "PMW" / f"{n}.mq5").write_text("src", encoding="utf-8")
                if n not in skip:
                    e = self.mql / sub / "PMW" / f"{n}.ex5"
                    e.write_bytes(b"ex5")
                    os.utime(e, (now, now))
        with redirect_stdout(io.StringIO()):
            self.ns.main(str(self.tmp), "0", "log", mm=True)
        return json.loads((self.mql / "Files" / "PMW" / "mm_native_status.json").read_text(encoding="utf-8"))

    def test_status_file_and_inventory(self):
        files = str(self.mql / "Files")
        rows = {r["id"]: r for r in INV.merge_run(None, files_dir=files)}
        # merge with group mm (I0499): `native` = declared scope + this evidence, `native_evidence` = the evidence alone
        self.assertTrue(rows["kalman"]["native_evidence"].startswith("NOT_COMPILED"))    # no status file yet
        self.assertTrue(rows["kalman"]["native"].endswith(" – " + rows["kalman"]["native_evidence"]), rows["kalman"]["native"])
        self.assertIn("MQL5 PMW_Kalman.mqh", rows["kalman"]["native"])
        self.assertIsNone(rows["buzoa"]["native"])                             # no MQL5 port at all
        st = self._compile()
        self.assertEqual(st["compile_errors"], 0)
        self.assertIn("PMW_KalmanShadowEA.ex5", st["ex5_files"])
        self.assertEqual(st["selftest_result"], "NATIVE_NOT_EXECUTED")
        rows = {r["id"]: r for r in INV.merge_run(None, files_dir=files)}
        self.assertIn("COMPILED (PMW_KalmanCross.ex5, PMW_KalmanShadowEA.ex5)", rows["kalman"]["native"])
        self.assertIn("NATIVE_NOT_EXECUTED", rows["kalman"]["native"])
        self.assertIn("COMPILED (nagłówek w PMW_MM_SelfTest.ex5)", rows["hdc"]["native"])
        self.assertIn("PRIMITIVES_ONLY", rows["hdc"]["native"])
        # merge with group mm (I0508): PMW_MM_SelfTest includes PMW_StateStack.mqh now - the header is compiled through it
        self.assertTrue(rows["event_engine"]["native_evidence"].startswith("COMPILED (nagłówek w PMW_MM_SelfTest.ex5)"))
        self.assertIn("HEADER_ONLY", rows["event_engine"]["native"])
        self.assertIn("COMPILED", rows["mathbench"]["native"])
        # a fresh self-test output (written after the compilation) is compared with the references exported next to it
        FX.export(self.mql / "Files" / "PMW_MM")
        nat = _native_from_references(self.mql / "Files" / "PMW_MM")
        nat["align"][0]["mean"][100] += 1.0
        (self.mql / "Files" / "PMW_MM" / "PMW_MM_NATIVE.txt").write_text(json.dumps(nat), encoding="utf-8")
        rows = {r["id"]: r for r in INV.merge_run(None, files_dir=files)}
        self.assertTrue(rows["kalman"]["native"].endswith("NATIVE_PARITY_PASS"), rows["kalman"]["native"])
        self.assertTrue(rows["gpr"]["native"].endswith("NATIVE_PARITY_PASS"), rows["gpr"]["native"])
        self.assertTrue(rows["align_mean"]["native"].endswith("NATIVE_PARITY_FAIL"), rows["align_mean"]["native"])
        # an output older than the newest EX5 belongs to a previous build
        old = time.time() - 10_000
        os.utime(self.mql / "Files" / "PMW_MM" / "PMW_MM_NATIVE.txt", (old, old))
        rows = {r["id"]: r for r in INV.merge_run(None, files_dir=files)}
        self.assertTrue(rows["kalman"]["native"].endswith("NATIVE_NOT_EXECUTED"), rows["kalman"]["native"])

    def test_missing_ex5_and_compile_errors(self):
        self._compile(skip=("PMW_KalmanShadowEA",))
        rows = {r["id"]: r for r in INV.merge_run(None, files_dir=str(self.mql / "Files"))}
        self.assertEqual(rows["kalman"]["native_evidence"], "NOT_COMPILED (brak EX5: PMW_KalmanShadowEA)")
        self.assertTrue(rows["kalman"]["native"].endswith(" – NOT_COMPILED (brak EX5: PMW_KalmanShadowEA)"))
        with redirect_stdout(io.StringIO()):
            self.ns.main(str(self.tmp), "2", "log", mm=True)
        rows = {r["id"]: r for r in INV.merge_run(None, files_dir=str(self.mql / "Files"))}
        self.assertTrue(rows["gpr"]["native_evidence"].startswith("COMPILE_FAIL"))
        self.assertIn(" – COMPILE_FAIL", rows["gpr"]["native"])

    def test_bat_is_ascii_crlf_and_only_installs_and_compiles(self):
        bat = ROOT / "44_MASTERMODELS_NATIVE.bat"
        raw = bat.read_bytes()
        raw.decode("ascii")
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        txt = raw.decode("ascii")
        for s in ("mql5\\MasterModels\\Include\\PMW\\*.mqh", "mql5\\MathFidelity\\Include\\PMW_MathFidelity\\*.mqh", "/compile:",
                  "mr2_native_status.py\" \"%DATA%\" !ERR! \"%LOG%\" --mm", "mm export-fixtures --out \"%DATA%\\MQL5\\Files\\PMW_MM\""):
            self.assertIn(s, txt)
        for bad in ("terminal64", "AutoTrading", "start_mode", "live_autobind", "OrderSend"):
            self.assertNotIn(bad.lower(), "\n".join(ln for ln in txt.lower().splitlines() if not ln.startswith("rem ")), bad)


# ---------------------------------------------------------------------------------------------------------------- merge mql5 x mm
class TestMergeNativeContractMqlMm(unittest.TestCase):
    """Merge of the groups mql5 (I0488 evidence, I0501 align) and mm (I0490/I0497/I0499/I0505/I0506/I0508/I0511): one native contract -
    the self-test writes every section parity() gates, the inventory maps every gate to its module and never shows a PASS without it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mq_t_merge_"))
        FX.export(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _parity(self, nat: dict) -> dict:
        p = self.tmp / "PMW_MM_NATIVE.txt"
        p.write_text(json.dumps(nat), encoding="utf-8")
        return FX.parity(p, self.tmp)

    def test_export_writes_every_reference_of_both_groups(self):
        names = {p.name for p in self.tmp.iterdir()}
        self.assertLessEqual(set(FX.REF_FILES), names)
        for f in ("mm_ref_hdc_acc.csv", "mm_ref_breakout_SESSION_VWAP.csv", "mm_fixture_ticks.csv", "mm_ref_tsvp.csv", "mm_ref_stack.csv",
                  "mm_ref_align.csv"):
            self.assertIn(f, FX.REF_FILES)

    def test_selftest_reads_and_writes_every_section(self):
        src = _src(MM / "Scripts" / "PMW_MM_SelfTest.mq5")
        nat = FX.expected_native(self.tmp)
        for key in set(nat) - {"version", "bars", "terminal"}:
            self.assertIn(f'\\"{key}\\":', src, key)
        for f in ("mm_fixture_bars.csv", "mm_ref_hdc.csv", "mm_ref_hdc_acc.csv", "mm_fixture_ticks.csv", "mm_ref_tsvp.csv", "mm_ref_stack.csv",
                  "mm_ref_align.csv"):
            self.assertIn(f'ReadLines("{f}"', src, f)
        heads = set(re.findall(r"#include\s*<PMW\\(PMW_\w+\.mqh)>", _code(src)))
        self.assertEqual(heads, INV.SELFTEST_HEADERS)                         # "COMPILED (nagłówek w PMW_MM_SelfTest.ex5)" only for these
        # the align rows the script parses: C rows with 11 fields (StringSplit(...) < 11 -> skipped), the header row is not a C row
        rows = (self.tmp / "mm_ref_align.csv").read_text(encoding="ascii").splitlines()
        c_rows = [r for r in rows if r.startswith("C,")]
        self.assertEqual(len(c_rows), len(FX.ALIGN_FIXTURE_CONFIGS))
        self.assertTrue(all(len(r.split(",")) == 11 for r in c_rows))
        self.assertFalse(rows[0].startswith("C,"))

    def test_every_gate_belongs_to_a_module(self):
        res = self._parity(FX.expected_native(self.tmp))
        self.assertEqual(res["status"], "NATIVE_PARITY_PASS", res["gates"])
        expected = {"kalman", "gpr", "gpr_tune", "hdc", "hdc_acc", "breakout", "tsvp", "stack", "align"} | {f"breakout_{m}" for m in
                                                                                                          ("SESSION_VWAP", "SMA", "SMMA", "NONE")}
        self.assertEqual(set(res["gates"]), expected)                           # stack_opencl only with an OpenCL device
        mapped = {g for v in INV.PARITY_GATE.values() for g in v}
        self.assertLessEqual(set(res["gates"]) | {"stack_opencl"}, mapped)
        for nat_key in ("align", "tsvp", "stack", "hdc_acc", "breakout_modes", "gpr_tune"):   # a missing section of either group fails
            nat = FX.expected_native(self.tmp)
            nat.pop(nat_key)
            self.assertEqual(self._parity(nat)["status"], "NATIVE_PARITY_FAIL", nat_key)

    def _row(self, mid: str, gates: dict) -> str:
        m = INV.by_id()[mid]
        ex5 = ["PMW_MM_SelfTest.ex5"] + [Path(f).stem + ".ex5" for f in m["files"] if f.endswith(".mq5")]
        ev = {"status": {"compile_errors": 0, "ex5_files": ex5}, "parity": {"status": "NATIVE_PARITY_FAIL", "gates": gates}}
        return INV.native_status(m, ev)

    def test_module_verdict_needs_every_gate_of_the_module(self):
        ok = {g: True for v in INV.PARITY_GATE.values() for g in v if g not in INV.PARITY_OPTIONAL}
        for mid in INV.PARITY_GATE:
            self.assertTrue(self._row(mid, ok).endswith("NATIVE_PARITY_PASS"), mid)
        self.assertTrue(self._row("breakout_zones", {**ok, "breakout_SMMA": False}).endswith("NATIVE_PARITY_FAIL"))
        self.assertTrue(self._row("hdc", {**ok, "hdc_acc": False}).endswith("NATIVE_PARITY_FAIL"))
        self.assertTrue(self._row("gpr", {k: v for k, v in ok.items() if k != "gpr_tune"}).endswith("NATIVE_PARITY_FAIL"))   # never compared
        self.assertTrue(self._row("event_engine", {**ok, "stack_opencl": False}).endswith("NATIVE_PARITY_FAIL"))
        self.assertTrue(self._row("event_engine", {**ok, "stack_opencl": True}).endswith("NATIVE_PARITY_PASS"))
        self.assertTrue(self._row("kalman", {**ok, "align": False}).endswith("NATIVE_PARITY_PASS"))   # another module's gate
        # the row: declared scope (I0499) + this evidence (I0488), never the old flat IMPLEMENTED
        rows = {r["id"]: r for r in INV.merge_run(None, files_dir="")}
        for r in rows.values():
            if r.get("native") is not None:
                self.assertNotIn("IMPLEMENTED", r["native"], r["id"])
                self.assertIn("NOT_COMPILED", r["native_evidence"], r["id"])
                self.assertTrue(r["native"].endswith(" – " + r["native_evidence"]), r["id"])


# ---------------------------------------------------------------------------------------------------------------- I0491
class TestI0491GprNativeDefaults(unittest.TestCase):
    def test_native_start_hyperparameters_equal_gprconfig(self):
        cfg = G.GPRConfig()
        ind = _src(MM / "Indicators" / "PMW_GPR_Forecast.mq5")
        val = {k: float(re.search(rf"input double {k}\s*=\s*([0-9.eE+-]+);", ind).group(1)) for k in ("InpEll", "InpSignalVar", "InpNoiseVar")}
        self.assertEqual((val["InpEll"], val["InpSignalVar"], val["InpNoiseVar"]), (cfg.ell, cfg.signal_var, cfg.noise_var))
        ea = _src(MM / "Experts" / "PMW_GPR_ShadowEA.mq5")
        line = next(ln for ln in ea.splitlines() if "double e0 = g_gp.fit.valid" in ln)
        fb = [float(x) for x in re.findall(r"g_gp\.fit\.(?:ell|sv|nv) : ([0-9.eE+-]+)", line)]
        self.assertEqual(fb, [cfg.ell, cfg.signal_var, cfg.noise_var])
        for s in (ind, ea):                                                    # the different re-tune cadence is documented
            self.assertIn("InpRetuneEvery", s.split("#property")[0])

    def test_fixture_keeps_its_explicit_noise(self):
        # the native parity uses explicit hyper-parameters (0.5), so the default change does not move the reference
        self.assertIn("gp.Refit(x, y, false, 4.0, 0.1, 0.5)", _src(MM / "Scripts" / "PMW_MM_SelfTest.mq5"))


# ---------------------------------------------------------------------------------------------------------------- I0493
class TestI0493KalmanShadowEaCsv(unittest.TestCase):
    def test_csv_opened_before_the_history_check_and_no_epoch_copy(self):
        src = _src(MM / "Experts" / "PMW_KalmanShadowEA.mq5")
        init = _func(src, "int OnInit()")
        self.assertLess(init.index("OpenCsv();"), init.index("RebuildState()"))
        self.assertIn("FileOpen(InpCsvName", _func(src, "void OpenCsv()"))
        tick = _func(src, "void OnTick()")
        self.assertNotIn("(datetime)0", tick)
        self.assertLess(tick.index("if(g_last == 0)"), tick.index("CopyRates("))
        self.assertIn("RebuildState();", tick)
        self.assertIn("CopyRates(_Symbol, _Period, 1, InpBars, r)", _func(src, "bool RebuildState()"))
        # OpenCsv skips an open handle, and an EA keeps its globals across a chart change: the handle is reset on deinit
        self.assertIn("g_fh = INVALID_HANDLE;", _func(src, "void OnDeinit("))
        self.assertLess(init.index("g_last = 0;"), init.index("RebuildState()"))


# ---------------------------------------------------------------------------------------------------------------- I0509
class TestI0509StateStackInitClFailure(unittest.TestCase):
    def test_failed_program_build_resets_the_handles(self):
        body = _func(_src(MM / "Include" / "PMW" / "PMW_StateStack.mqh"), "bool   InitCL()")
        line = next(ln for ln in body.splitlines() if "prg == INVALID_HANDLE" in ln)
        self.assertIn("Free();", line)
        self.assertNotIn("CLContextFree(ctx)", line)                            # was: freed, but ctx kept -> freed again in ~Free()


# ---------------------------------------------------------------------------------------------------------------- I0521
class TestI0521Mql5Utf8Encoding(unittest.TestCase):
    def test_no_utf8_conversion_bounded_by_string_length(self):
        bad = []
        for p in MQL5.rglob("*.mq*"):
            for i, ln in enumerate(_code(_src(p)).splitlines(), 1):
                if "StringToCharArray(" in ln and "CP_UTF8" in ln:
                    if "StringLen(" in ln:
                        bad.append(f"{p.name}:{i}")
                    elif "WHOLE_ARRAY" in ln and "MR2_Format" not in p.name:
                        self.assertRegex(ln, r"\[(\w+) - 1\] == 0\) ArrayResize\(\w+, \1 - 1\)", f"{p.name}:{i} terminating 0 kept")
        self.assertEqual(bad, [])


# ---------------------------------------------------------------------------------------------------------------- all touched sources
class TestTouchedSourcesStayNonTrading(unittest.TestCase):
    FILES = ("MasterModels/Include/PMW/PMW_HDC.mqh", "MasterModels/Include/PMW/PMW_AlignMeanCore.mqh", "MasterModels/Include/PMW/PMW_StateStack.mqh",
             "MasterModels/Indicators/PMW_AlignMean.mq5", "MasterModels/Indicators/PMW_GPR_Forecast.mq5", "MasterModels/Experts/PMW_GPR_ShadowEA.mq5",
             "MasterModels/Experts/PMW_KalmanShadowEA.mq5", "MasterModels/Scripts/PMW_MM_SelfTest.mq5", "MiniRocketV2/Include/PMW/PMW_MR2_Core.mqh",
             "MiniRocketV2/Include/PMW/PMW_MR2_Format.mqh", "MiniRocketV2/Indicators/PMW_MR2_Indicator.mq5", "MiniRocketV2/Scripts/PMW_MR2_SelfTest.mq5",
             "MiniRocketV2/Scripts/PMW_MR2_Fit.mq5", "FlowContext/Scripts/MQ_FlowCollector.mq5", "ContextIndicators/Include/PMW/PMW_ContextCore.mqh",
             "ContextIndicators/Scripts/PWM_ContextSelfTest.mq5", "PMW_ExtIndicatorExporter.mq5")
    TRADE = re.compile(r"\b(OrderSend|OrderSendAsync|OrderModify|OrderDelete|PositionOpen|PositionClose|PositionModify|CTrade|CPositionInfo)\b"
                       r"|Trade\\Trade\.mqh")

    def test_no_trade_api_balanced_and_ascii(self):
        for f in self.FILES:
            raw = (MQL5 / f).read_bytes()
            raw.decode("ascii")                                                # MetaEditor-safe encoding of every touched file
            code = re.sub(r'"(\\.|[^"\\])*"', '""', _code(raw.decode("ascii")))
            self.assertIsNone(self.TRADE.search(code), f)
            self.assertEqual(code.count("{"), code.count("}"), f)
            self.assertEqual(code.count("("), code.count(")"), f)
            self.assertEqual(code.count("["), code.count("]"), f)


if __name__ == "__main__":
    unittest.main()
