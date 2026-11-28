"""1.46 audit, group D_tools_2 - regression tests for the research / installer tools: replay settlement (stop gaps, time exit cut by
the data end, bar spread from the broker CSV, temporary databases), the Chronos-2 / TiRex-2 / TabICL installer with --cuda on a fresh
environment, the offline test runner on a timeout, the synthetic NLP corpus, and the rebranded .bat / START TUTAJ texts."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env

sys.path.insert(0, str(_env.ROOT / "tools"))

T0 = datetime(2026, 10, 12, 10, tzinfo=UTC)
COST = {"spread": 0.12, "slip": 0.05, "commission": 0.0, "point": 0.01}


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def bars(rows):
    """rows = [(o, h, l, c)] or [(o, h, l, c, spread_points)] -> M5 bars + index from T0."""
    out = []
    for i, r in enumerate(rows):
        b = {"open_utc": iso(T0 + timedelta(minutes=5 * i)), "o": r[0], "h": r[1], "l": r[2], "c": r[3]}
        if len(r) > 4:
            b["spread_points"] = r[4]
        out.append(b)
    return out, {"times": [T0 + timedelta(minutes=5 * i) for i in range(len(rows))]}


def plan(direction, sl, target, **exit_rules):
    return {"direction": direction, "stop_loss": sl, "targets": [{"price": target, "weight": 1.0}], "timeframe": "M15",
            "exit_rules": {"be_after_tp1": False, **exit_rules}}


class TestReplayStopGap(unittest.TestCase):
    """chunk_51#2: a bar that opens beyond the stop (weekend / news gap) fills at the open - the worse price, as PAPER and MT5 do."""

    def test_long_gap_fills_at_the_open(self):
        import replay_strategies as rp
        m5, idx = bars([(2000.0, 2001.0, 1999.5, 2000.5), (1980.0, 1981.0, 1979.0, 1980.0)])
        r = rp.simulate(plan("LONG", 1990.0, 2030.0, time_exit_bars=None), T0, m5, idx, dict(COST))
        self.assertEqual((r["status"], r["exit"]), ("CLOSED", "STOP"))
        entry = 2000.0 + 0.12 + 0.05
        self.assertAlmostEqual(r["r"], ((1980.0 - entry) - 0.05) / (entry - 1990.0), places=3)    # ~ -1.99 R, not -1.01 R
        self.assertTrue(r["stop_gap"])
        self.assertLessEqual(-r["r"], r["mae_r"] + 0.01)

    def test_short_gap_fills_at_the_ask_open(self):
        import replay_strategies as rp
        m5, idx = bars([(2000.0, 2000.5, 1999.0, 1999.5), (2020.0, 2021.0, 2019.0, 2020.0)])
        r = rp.simulate(plan("SHORT", 2010.0, 1970.0, time_exit_bars=None), T0, m5, idx, dict(COST))
        entry = 2000.0 - 0.05
        self.assertEqual(r["status"], "CLOSED")
        self.assertAlmostEqual(r["r"], ((entry - (2020.0 + 0.12)) - 0.05) / (2010.0 - entry), places=3)
        self.assertTrue(r["stop_gap"])

    def test_no_gap_still_fills_at_the_stop(self):
        import replay_strategies as rp
        m5, idx = bars([(2000.0, 2001.0, 1999.5, 2000.5), (1995.0, 1996.0, 1989.0, 1990.5)])
        r = rp.simulate(plan("LONG", 1990.0, 2030.0, time_exit_bars=None), T0, m5, idx, dict(COST))
        entry = 2000.0 + 0.12 + 0.05
        self.assertAlmostEqual(r["r"], ((1990.0 - entry) - 0.05) / (entry - 1990.0), places=3)
        self.assertFalse(r["stop_gap"])
        st = rp.stats([r, dict(r, stop_gap=True)])
        self.assertEqual(st["stop_gap_fills"], 1)


class TestReplayTimeExitDataEnd(unittest.TestCase):
    """chunk_51#3: a plan with a time exit whose data end before that exit is OPEN_AT_DATA_END (like a plan without a time exit),
    not a CLOSED trade with exit TIME."""

    def test_cut_by_the_data_end_is_not_a_result(self):
        import replay_strategies as rp
        m5, idx = bars([(2000.0 + i * 0.1, 2000.5 + i * 0.1, 1999.8 + i * 0.1, 2000.2 + i * 0.1) for i in range(3)])
        r = rp.simulate(plan("LONG", 1990.0, 2030.0, time_exit_bars=36), T0, m5, idx, dict(COST))     # 36 x M15 = 108 M5 bars
        self.assertEqual(r["status"], "OPEN_AT_DATA_END")
        no_time = rp.simulate(plan("LONG", 1990.0, 2030.0, time_exit_bars=None), T0, m5, idx, dict(COST))
        self.assertEqual(no_time["status"], "OPEN_AT_DATA_END")

    def test_time_exit_reached_is_closed(self):
        import replay_strategies as rp
        m5, idx = bars([(2000.0, 2000.5, 1999.8, 2000.2)] * 6)
        r = rp.simulate(plan("LONG", 1990.0, 2030.0, time_exit_bars=2), T0, m5, idx, dict(COST))       # 2 x M15 = 6 M5 bars
        self.assertEqual((r["status"], r["exit"], r["held_m5"]), ("CLOSED", "TIME", 6))


class TestReplayCsvSpread(unittest.TestCase):
    """chunk_51#4: the bar spread of the broker CSV (spread_points x point) is used; --spread only when the bar carries none."""

    def test_entry_pays_the_bar_spread(self):
        import replay_strategies as rp
        m5, idx = bars([(2000.0, 2001.0, 1999.5, 2000.5, 50), (2001.0, 2031.0, 2000.5, 2030.0, 50)])
        r = rp.simulate(plan("LONG", 1990.0, 2030.0, time_exit_bars=None), T0, m5, idx, dict(COST))
        self.assertAlmostEqual(r["risk_price"], 2000.0 + 0.50 + 0.05 - 1990.0, places=4)
        self.assertEqual(r["spread_source"], "CSV_BAR")

    def test_short_exit_at_ask_uses_the_bar_spread(self):
        import replay_strategies as rp
        m5, idx = bars([(2000.0, 2000.5, 1999.0, 1999.5, 10), (2000.0, 2009.6, 1999.0, 2009.0, 80)])
        r = rp.simulate(plan("SHORT", 2010.0, 1970.0, time_exit_bars=None), T0, m5, idx, dict(COST))
        self.assertEqual((r["status"], r["exit"]), ("CLOSED", "STOP"))               # Ask high = 2009.6 + 0.80 >= 2010

    def test_missing_or_zero_spread_falls_back_to_the_cost_argument(self):
        import replay_strategies as rp
        for sp in (None, 0):
            m5, idx = bars([(2000.0, 2001.0, 1999.5, 2000.5, sp), (2001.0, 2031.0, 2000.5, 2030.0, sp)])
            r = rp.simulate(plan("LONG", 1990.0, 2030.0, time_exit_bars=None), T0, m5, idx, dict(COST))
            self.assertAlmostEqual(r["risk_price"], 2000.0 + 0.12 + 0.05 - 1990.0, places=4)
            self.assertEqual(r["spread_source"], "COST_ARG")

    def test_load_csv_keeps_a_missing_spread_missing(self):
        import replay_strategies as rp
        d = Path(tempfile.mkdtemp(prefix="mq_t_csv_"))
        try:
            (d / "M5.csv").write_text("time_utc,open,high,low,close,available_at_utc,spread_points\n"
                                      "2026-10-12T10:00:00Z,1,2,0.5,1.5,2026-10-12T10:05:00Z,\n"
                                      "2026-10-12T10:05:00Z,1,2,0.5,1.5,2026-10-12T10:10:00Z,25\n", encoding="utf-8")
            data, _ = rp.load_csv(d)
            self.assertEqual([b["spread_points"] for b in data["M5"]], [None, 25])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestReplayTempCleanup(unittest.TestCase):
    """chunk_51#18: run() and original_counts() remove their temporary databases."""

    def test_no_temporary_folders_left(self):
        import replay_strategies as rp
        td = _env.TempData()
        tmp_root = tempfile.mkdtemp(prefix="mq_t_root_")
        try:
            data, src = rp.load_synthetic(50, 3)
            with mock.patch.object(tempfile, "tempdir", tmp_root):
                r = rp.run(data, src, "H1", dict(COST), False, 2, walls=None, trade_policy="ALL")
                rp.original_counts(data, step_tf="H1", max_steps=2)
            self.assertEqual(r["steps"], 2)
            self.assertEqual([n for n in os.listdir(tmp_root) if n.startswith(("mq_replay_", "mq_orig_"))], [])
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)
            td.close()


class _NtOs:
    """os seen by tsfm_setup as on Windows (only the module's own `os` name is replaced - pathlib keeps the real one)."""
    name = "nt"

    def __getattr__(self, k):
        return getattr(os, k)


class TestTsfmCudaInstallOrder(unittest.TestCase):
    """chunk_51#1: --cuda on a FRESH .venv_*: the hashed requirements without torch need torch already installed (chronos-forecasting,
    accelerate depend on it; pip in --require-hashes mode refuses an unpinned dependency), so torch from the PyTorch index goes first."""

    def test_fresh_environment_with_cuda_installs(self):
        import kronos_setup as KS
        import tsfm_setup as TS
        root = Path(tempfile.mkdtemp(prefix="mq_t_tsfm_"))
        try:
            (root / "requirements").mkdir()
            shutil.copy(_env.ROOT / "requirements" / "requirements-chronos2-win.txt", root / "requirements")
            (root / ".venv_chronos2" / "Scripts").mkdir(parents=True)
            (root / ".venv_chronos2" / "Scripts" / "python.exe").write_bytes(b"")
            installed, calls = {"torch": False}, []

            def fake_pip(cmd, out, step, env=None):      # pip semantics: hash mode refuses an unpinned dependency that is not installed
                calls.append(list(cmd))
                if "--require-hashes" in cmd:
                    req = Path(cmd[cmd.index("-r") + 1]).read_text(encoding="utf-8")
                    if not any(ln.startswith("torch==") for ln in req.splitlines()) and not installed["torch"]:
                        return 1, "ERROR: In --require-hashes mode, all requirements must have their versions pinned with ==. These do not: torch>=2.2"
                    return 0, ""
                if TS.TORCH["chronos2"] in cmd and "--index-url" in cmd:
                    installed["torch"] = True
                return 0, ""

            a = types.SimpleNamespace(cuda="cu126", weights_root=str(root / "w"), from_dir=None)
            with mock.patch.object(TS, "os", _NtOs()), mock.patch.object(TS, "hardware", return_value={}), \
                    mock.patch.object(TS.shutil, "disk_usage", return_value=types.SimpleNamespace(free=10 ** 13)), \
                    mock.patch.object(KS, "venv_repair", return_value={"state": "OK"}), mock.patch.object(KS, "run", fake_pip), \
                    mock.patch.object(KS, "emit", lambda line: None), \
                    mock.patch.object(TS.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)):
                KS.CHILD["result"] = None
                res = TS.install_one("chronos2", a, root, "python", TS.Out(None))
            self.assertTrue(res["ok"], res)
            i_torch = next(i for i, c in enumerate(calls) if "--index-url" in c)
            i_hash = next(i for i, c in enumerate(calls) if "--require-hashes" in c)
            self.assertLess(i_torch, i_hash)
            self.assertIn("--no-deps", calls[i_torch])
            self.assertIn("https://download.pytorch.org/whl/cu126", calls[i_torch])
            hashed = Path(calls[i_hash][calls[i_hash].index("-r") + 1]).read_text(encoding="utf-8")
            self.assertNotIn("torch==", hashed)
            self.assertIn("chronos-forecasting==", hashed)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestRunTestsTimeout(unittest.TestCase):
    """chunk_51#16: a timeout of the candles / legacy suites is reported (TIMEOUT, not ok) - the JSON report is still written."""

    def test_candles_timeout_is_reported(self):
        import run_tests as RT
        exc = subprocess.TimeoutExpired(["py"], 3600, output=b"", stderr=b"test_a ... ok\n")
        with mock.patch.object(RT, "candle_python", return_value="/x/python"), mock.patch.object(RT.subprocess, "run", side_effect=exc):
            r = RT.run_candles()
        self.assertEqual((r["status"], r["ok"]), ("TIMEOUT", False))
        self.assertIn("test_a", r["tail"])
        self.assertIsNone(r["ran"])

    def test_legacy_timeout_is_reported(self):
        import run_tests as RT
        with mock.patch.object(RT.shutil, "copytree"), \
                mock.patch.object(RT.subprocess, "run", side_effect=subprocess.TimeoutExpired(["py"], 1800, output="partial", stderr=None)):
            out = RT.run_legacy()
        self.assertEqual(len(out), len(RT.LEGACY))
        self.assertTrue(all(x["status"] == "TIMEOUT" and x["returncode"] is None for x in out))
        self.assertFalse(all(x["returncode"] == 0 for x in out))                  # main() then reports SA BLEDY


class TestSyntheticNlpCorpus(unittest.TestCase):
    """chunk_51#15: every class of the synthetic headline corpus uses all three of its phrases (the phrase index was always = class)."""

    def test_three_phrases_per_class(self):
        import validate_families_synthetic as V
        from masterquo.modelhub.families import nlp as NL
        seen = {}

        def imp(p, data_kind=None):           # 1.46 arch I0469/I0470: import_file takes the corpus provenance
            seen["rows"] = [json.loads(ln) for ln in Path(p).read_text(encoding="utf-8").splitlines()]
            seen["data_kind"] = data_kind

        tmp = Path(tempfile.mkdtemp(prefix="mq_t_nlp_"))
        try:
            with mock.patch.object(NL, "import_file", imp), mock.patch.object(NL, "load_corpus", lambda: seen["rows"]):
                rows = V.corpus(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        phrases = {"POSITIVE": ("gold rallies", "bullion surges", "strong demand lifts"),
                   "NEUTRAL": ("market waits", "traders eye data", "session opens quietly"),
                   "NEGATIVE": ("gold plunges", "prices slump", "sell-off deepens")}
        self.assertEqual(len(rows), 600)
        for lab, ph in phrases.items():
            used = {p for r in rows if r["label"] == lab for p in ph if r["text"].startswith(p)}
            self.assertEqual(used, set(ph), lab)
            self.assertEqual(sum(1 for r in rows if r["label"] == lab), 200)


class TestRebrandTexts(unittest.TestCase):
    """focus_X5#4 / #5 / #9: user-visible texts of the .bat files and START TUTAJ."""

    def _bat(self, name):
        raw = (_env.ROOT / name).read_bytes()
        raw.decode("ascii")                                                      # .bat files stay ASCII + CRLF
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        return raw.decode("ascii")

    def test_export_bat_points_to_the_desktop_app(self):
        import re
        t = self._bat("11_EKSPORT_HISTORII_XAUUSD.bat")
        line = next(ln for ln in t.split("\r\n") if ln.startswith('if not exist "%PY%" ('))
        self.assertIn("PepeMarketWizardDesktop.exe", line)                       # the app that creates <home>\pyenv (pmwpy.cmd)
        self.assertNotIn("PepeMarketWizard.exe", line)
        body = line[len('if not exist "%PY%" ('):-1]
        self.assertTrue(line.endswith(")"))
        self.assertIsNone(re.search(r"(?<!\^)[()]", body), body)               # an unescaped ) would end the IF block early

    def test_profile_bat_prefix(self):
        t = self._bat("08_PROFIL_ORIGINAL.bat")
        self.assertIn("echo [Apollo23] Powrot do profilu ORIGINAL", t)
        self.assertNotIn("[MasterQUO]", t)
        self.assertIn("04_STOP_MASTERQUO.bat", t)                               # file names are identifiers

    def test_start_tutaj_describes_1_45(self):
        t = (_env.ROOT / "START_TUTAJ_PL.md").read_text(encoding="utf-8")
        first = t.splitlines()[0]
        self.assertIn("Apollo23", first)
        self.assertIn("PepeMarketWizard", first)
        i45, i42 = t.find("## Nowe w 1.45"), t.find("## Nowe w 1.42")
        self.assertTrue(0 <= i45 < i42)
        sec = t[i45:i42]
        for s in ("TraderLifeGame", "OTC", "masterquo", "PMW_"):
            self.assertIn(s, sec)
        self.assertIn("1.45", t[i42:t.find("## Nowe w 1.40")])                 # the 1.42 FOREX / CRYPTO / OTC menu is marked as replaced


if __name__ == "__main__":
    unittest.main()
