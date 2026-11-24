"""1.46 audit, group D_tools_1 - regression tests for the research / build tools: EMA pullback backtest (missing spread = NOT_VERIFIED,
instrument units), playbook generator (S11/S12 in the registry), MQL5 native status (stale self-test), RAM benchmark (one reader per
worker, short history, dead model process), migration check (server killed when it does not start) and the texts of the PDF guides
(client package, Apollo23 display name, no OTC / removed intro). No HTTP server, no MT5, no orders, no reportlab needed."""
from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env

ROOT = _env.ROOT
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))


def _src(name: str) -> str:
    return (TOOLS / name).read_text(encoding="utf-8")


# ============================================================================================== backtest_ema_pullback (chunk_50#1, #2)
def _write_bars(path: Path, n: int = 2200, *, spread=None, symbol: str = "XAUUSD-", decimals: int = 2, seed: int = 3) -> None:
    """Closed M30 bars on the price grid of `decimals`; spread = None -> no spread_points column, else the column with this value
    ('' = empty cell)."""
    rnd = random.Random(seed)
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    c = 2000.0
    cols = ["symbol", "time_utc", "open", "high", "low", "close", "bar_state"] + (["spread_points"] if spread is not None else [])
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for i in range(n):
            o = c
            c = round(o + rnd.gauss(0.05 * ((i // 300) % 2 * 2 - 1), 1.5), decimals)
            h = round(max(o, c) + abs(rnd.gauss(0, 0.6)), decimals)
            lo = round(min(o, c) - abs(rnd.gauss(0, 0.6)), decimals)
            row = [symbol, (t0 + timedelta(minutes=30 * i)).isoformat().replace("+00:00", "Z"), o, h, lo, c, "CLOSED"]
            w.writerow(row + ([spread] if spread is not None else []))


class _BacktestRun(unittest.TestCase):
    def setUp(self):
        import backtest_ema_pullback as bt_tool
        self.m = bt_tool
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_t_ema_"))
        (self.tmp / "csv").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_tool(self, *extra):
        out = io.StringIO()
        with mock.patch.object(self.m, "ROOT", self.tmp), redirect_stdout(out):
            rc = self.m.main(["--csv", str(self.tmp / "csv"), "--report", str(self.tmp / "r.md"), *extra])
        res = sorted((self.tmp / "data" / "results" / "ema_pullback").glob("*/results.json"))
        return rc, (json.loads(res[-1].read_text(encoding="utf-8")) if res else None), out.getvalue()


class TestBacktestSpreadNotZero(_BacktestRun):
    """chunk_50#1: a missing spread is None (not 0) and the run reports the share of bars without / with zero spread as NOT_VERIFIED."""

    def test_load_csv_keeps_a_missing_spread_missing(self):
        p = self.tmp / "M30.csv"
        p.write_text("time_utc,open,high,low,close,bar_state,spread_points\n"
                     "2025-01-01T00:00:00Z,1,2,0.5,1.5,CLOSED,\n"
                     "2025-01-01T00:30:00Z,1,2,0.5,1.5,CLOSED,0\n"
                     "2025-01-01T01:00:00Z,1,2,0.5,1.5,CLOSED,25\n", encoding="utf-8")
        self.assertEqual([b["spread"] for b in self.m.load_csv(p)], [None, 0.0, 25.0])
        q = self.tmp / "M30b.csv"
        q.write_text("time_utc,open,high,low,close\n2025-01-01T00:00:00Z,1,2,0.5,1.5\n", encoding="utf-8")
        self.assertIsNone(self.m.load_csv(q)[0]["spread"])

    def test_run_without_spreads_is_not_verified(self):
        _write_bars(self.tmp / "csv" / "M30.csv")
        rc, r, _ = self.run_tool()
        self.assertEqual(rc, 0)
        sq = r["manifest"]["spread_data"]
        self.assertEqual((sq["missing"], sq["zero"], sq["bars"]), (2200, 0, 2200))
        self.assertTrue(sq["status"].startswith("NOT_VERIFIED"), sq["status"])
        self.assertTrue(r["development"]["FIXED_MT5"]["spread_cost_status"].startswith("NOT_VERIFIED"))
        self.assertIn("NOT_VERIFIED", (self.tmp / "r.md").read_text(encoding="utf-8"))

    def test_zero_spread_bars_are_reported(self):
        _write_bars(self.tmp / "csv" / "M30.csv", spread=0)
        rc, r, _ = self.run_tool()
        self.assertEqual(rc, 0)
        sq = r["manifest"]["spread_data"]
        self.assertEqual((sq["missing"], sq["zero"]), (0, 2200))
        self.assertTrue(sq["status"].startswith("NOT_VERIFIED"))

    def test_complete_and_fixed_spread(self):
        _write_bars(self.tmp / "csv" / "M30.csv", spread=25)
        rc, r, _ = self.run_tool()
        self.assertEqual((rc, r["manifest"]["spread_data"]["status"]), (0, "COMPLETE"))
        shutil.rmtree(self.tmp / "data")
        _write_bars(self.tmp / "csv" / "M30.csv")
        rc, r, _ = self.run_tool("--spread-price", "0.2")
        self.assertEqual((rc, r["manifest"]["spread_data"]["status"], r["model_mt5"]["spread_price"]), (0, "FIXED_SPREAD_PRICE", 0.2))


class TestBacktestUnits(_BacktestRun):
    """chunk_50#2: point / tick size come from the CLI and are recorded; a non-gold export or prices off the point grid stop the run."""

    def test_units_from_cli_are_used_and_recorded(self):
        _write_bars(self.tmp / "csv" / "M30.csv", spread=150, decimals=3)
        rc, r, _ = self.run_tool("--point", "0.001", "--tick-size", "0.001")
        self.assertEqual(rc, 0)
        self.assertEqual((r["model_mt5"]["point"], r["model_mt5"]["tick_size"]), (0.001, 0.001))
        self.assertEqual((r["units"]["point"], r["units"]["source"]), (0.001, "CLI"))

    def test_default_units_are_marked_not_verified(self):
        _write_bars(self.tmp / "csv" / "M30.csv", spread=25)
        rc, r, _ = self.run_tool()
        self.assertEqual(rc, 0)
        self.assertEqual((r["units"]["point"], r["units"]["tick_size"]), (0.01, 0.01))
        self.assertIn("NOT_VERIFIED", r["units"]["source"])

    def test_prices_with_more_decimals_than_the_point_stop_the_run(self):
        _write_bars(self.tmp / "csv" / "M30.csv", spread=150, decimals=3)
        rc, r, out = self.run_tool()
        self.assertEqual(rc, 2, out)
        self.assertIsNone(r)
        self.assertIn("point", out)

    def test_non_gold_export_needs_explicit_units(self):
        _write_bars(self.tmp / "csv" / "M30.csv", spread=10, symbol="EURUSD")
        rc, r, out = self.run_tool()
        self.assertEqual(rc, 2, out)
        self.assertIsNone(r)
        (self.tmp / "csv" / "M30.csv").unlink()
        _write_bars(self.tmp / "csv" / "M30.csv", spread=10)
        (self.tmp / "csv" / "MT5_EXPORT_MANIFEST.json").write_text(json.dumps({"symbol": "BTCUSD"}), encoding="utf-8")
        rc, r, out = self.run_tool()
        self.assertEqual(rc, 2, out)


# ============================================================================================== make_strategy_cards (chunk_51#0)
class TestStrategyCards(unittest.TestCase):
    def test_generator_runs_with_s11_s12_in_the_registry(self):
        import make_strategy_cards as cards
        from masterquo.strategies import registry
        self.assertIn("S11", registry.STRATEGIES)
        tmp = Path(tempfile.mkdtemp(prefix="mq_t_cards_"))
        try:
            (tmp / "docs").mkdir()
            with mock.patch.object(cards, "ROOT", tmp), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cards.main(), 0)
            txt = (tmp / "docs" / "PLAYBOOK_10_STRATEGII.md").read_text(encoding="utf-8")
            self.assertEqual(re.findall(r"^## (S\d\d) ", txt, re.MULTILINE), [f"S{i:02d}" for i in range(1, 11)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================================== mr2_native_status (chunk_51#6)
class TestNativeStatusStaleSelftest(unittest.TestCase):
    def setUp(self):
        import mr2_native_status as ns
        self.ns = ns
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_t_native_"))
        self.mql = self.tmp / "MQL5"
        for d in ("Scripts/PMW", "Indicators/PMW", "Include/PMW", "Files/PMW"):
            (self.mql / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, selftest_age: float, flow: bool = False, ctx: bool = False):
        name = "PWM_X" if ctx else "MQ_FlowX" if flow else "PMW_MR2_X"
        st_name = "ctx_selftest.txt" if ctx else "flow_selftest.txt" if flow else "mr2_selftest.txt"
        out_name = "ctx_native_status.json" if ctx else "flow_native_status.json" if flow else "native_status.json"
        ex5 = self.mql / "Scripts" / "PMW" / f"{name}.ex5"
        ex5.write_bytes(b"ex5")
        (self.mql / "Scripts" / "PMW" / f"{name}.mq5").write_text("src", encoding="utf-8")
        st = self.mql / "Files" / "PMW" / st_name
        st.write_text("RESULT=PASS\n", encoding="utf-8")
        now = time.time()
        os.utime(ex5, (now, now))
        os.utime(st, (now + selftest_age, now + selftest_age))
        with redirect_stdout(io.StringIO()):
            self.ns.main(str(self.tmp), "0", "log", flow=flow, ctx=ctx)
        return json.loads((self.mql / "Files" / "PMW" / out_name).read_text(encoding="utf-8"))

    def test_selftest_older_than_the_new_ex5_is_not_evidence(self):
        for kw in ({}, {"flow": True}, {"ctx": True}):
            out = self._run(-3600, **kw)
            self.assertEqual(out["selftest_result"], "NATIVE_NOT_EXECUTED", kw)
            self.assertTrue(out["selftest_stale"], kw)

    def test_selftest_after_the_build_is_read(self):
        out = self._run(+60)
        self.assertEqual((out["selftest_result"], out["selftest_stale"]), ("PASS", False))


# ============================================================================================== ram_benchmark (chunk_51#5, #7)
_FAKE_WORKER = r'''
import json, sys, time
for line in sys.stdin:
    try:
        m = json.loads(line)
    except ValueError:
        continue
    cmd = m.get("cmd")
    if cmd == "quit":
        print(json.dumps({"id": m["id"], "ok": True}), flush=True)
        break
    if cmd == "hang":
        continue                                     # never answered
    if cmd == "slow":
        time.sleep(1.0)
    if cmd == "predict" and MODE == "die":
        sys.exit(3)                                  # the model process dies (OOM-like)
    info = {"params": 1, "device": "CPU", "threads": 1}
    print(json.dumps({"id": m["id"], "ok": True, "info": info, "echo": cmd}), flush=True)
'''


def _fake_worker(tmp: Path, mode: str = "ok") -> Path:
    p = tmp / f"fake_worker_{mode}"
    p.write_text(f"#!{sys.executable}\nMODE = {mode!r}\n" + _FAKE_WORKER, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


@unittest.skipIf(os.name == "nt", "fake worker uses a #! script")
class TestRamBenchmarkWorker(unittest.TestCase):
    def setUp(self):
        import ram_benchmark as rb
        self.rb = rb
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_t_ram_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_timeout_does_not_swallow_the_next_answers(self):
        w = self.rb.Worker("fake", [str(_fake_worker(self.tmp))], dict(os.environ))
        try:
            with self.assertRaises(TimeoutError):
                w.ask({"cmd": "hang"}, 0.3)
            with self.assertRaises(TimeoutError):
                w.ask({"cmd": "slow"}, 0.3)              # answered later - must not be taken by the next request
            got = [w.ask({"cmd": "hello"}, 5)["echo"] for _ in range(6)]
            self.assertEqual(got, ["hello"] * 6)
        finally:
            w.close()
        self.assertIsNotNone(w.p.poll())

    def _bars(self, n: int) -> Path:
        t0 = datetime(2026, 1, 5, tzinfo=UTC)
        rows = [[(t0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%S"), 2000.0, 2001.0, 1999.0, 2000.5] for i in range(n)]
        p = self.tmp / f"bars_{n}.json"
        p.write_text(json.dumps(rows), encoding="utf-8")
        return p

    def _main(self, bars: Path, worker: Path, *extra):
        out = self.tmp / "rep.json"
        with redirect_stdout(io.StringIO()) as so:
            rc = self.rb.main(["--bars", str(bars), "--tsfm-weights", str(self.tmp), "--granite-python", str(worker),
                               "--chronos-python", str(self.tmp / "missing_python"), "--single", "2", "--cycles", "3",
                               "--out", str(out), *extra])
        return rc, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None), so.getvalue()

    def test_a_dead_model_process_is_an_error_not_a_crash(self):
        rc, rep, _ = self._main(self._bars(600), _fake_worker(self.tmp, "die"))
        self.assertEqual(rc, 0)
        self.assertEqual(rep["models"]["granite_ttm"]["single_m5"]["errors"], 2)
        self.assertEqual(rep["sequential"]["errors"], 3)

    def test_short_history_is_rejected(self):
        rc, rep, out = self._main(self._bars(530), _fake_worker(self.tmp))     # 512 + 2 + 3 + 20 = 537 needed
        self.assertEqual(rc, 2, out)
        self.assertIsNone(rep)
        self.assertIn("537", out)


# ============================================================================================== migration_check (chunk_51#17)
@unittest.skipIf(os.name == "nt", "POSIX process handling")
class TestMigrationCheckKillsServer(unittest.TestCase):
    def test_server_that_does_not_answer_is_killed(self):
        import migration_check as mc
        tmp = Path(tempfile.mkdtemp(prefix="mq_t_mig_"))
        try:
            pkg = tmp / "tree" / "backend" / "masterquo"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "__main__.py").write_text("import time\ntime.sleep(300)\n", encoding="utf-8")
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            b = mc.Bot(tmp / "tree", tmp / "data", port)
            with mock.patch.object(mc.Bot, "START_TIMEOUT", 2.0, create=True), self.assertRaises(RuntimeError):
                b.__enter__()
            self.assertIsNotNone(b.proc.poll(), "the server process was left running")
        finally:
            if "b" in locals() and b.proc and b.proc.poll() is None:
                b.proc.kill()
                b.proc.wait()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_server_that_exits_is_reported_at_once(self):
        import migration_check as mc
        tmp = Path(tempfile.mkdtemp(prefix="mq_t_mig_"))
        try:
            pkg = tmp / "tree" / "backend" / "masterquo"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "__main__.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            t0 = time.monotonic()
            with self.assertRaises(RuntimeError) as cm:
                mc.Bot(tmp / "tree", tmp / "data", port).__enter__()
            self.assertLess(time.monotonic() - t0, 30)
            self.assertIn("7", str(cm.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



# ============================================================================================== PDF guides (texts, no reportlab needed)
def _func(src: str, name: str) -> str:
    """Source of one top-level function (up to the next top-level def)."""
    m = re.search(rf"^def {name}\(.*?(?=^def |\Z)", src, re.DOTALL | re.MULTILINE)
    return m.group(0) if m else ""


class TestManualTexts(unittest.TestCase):
    """tools/make_manuals.py: packages to hand out (focus_X7#3), display name (chunk_51#9 / focus_X7#10), OTC (chunk_51#10), removed
    intro / menu (chunk_51#11), contradictions (chunk_51#12)."""
    SRC = _src("make_manuals.py")

    def test_section_5_hands_out_only_the_client_package(self):
        admin = _func(self.SRC, "admin")
        sec5 = admin[admin.index('P("5 / Paczki do przekazania"'):admin.index('P("6 /')]
        self.assertNotIn("jedna wersja programu", sec5)
        self.assertNotIn("Program nie blokuje nikomu dostępu", sec5)
        self.assertIn('"Apollo23_DESKTOP_KLIENT_" + TAG', sec5)
        self.assertIn("tylko właściciel", sec5)
        client = _func(self.SRC, "client")
        prep = client[client.index('P("Co przygotować"'):client.index("Terminal MetaTrader 5")]
        self.assertIn("Apollo23_DESKTOP_KLIENT_", prep)
        self.assertNotIn("PepeMarketWizard_DESKTOP_", prep)
        self.assertNotIn("PepeMarketWizard_KLIENT_", self.SRC)               # 4j: the client package names of build_release / build_desktop
        self.assertNotIn("PepeMarketWizard_DESKTOP_KLIENT_", self.SRC)

    def test_display_name(self):
        from masterquo.version import DISPLAY_NAME
        self.assertIn(f'DISPLAY_NAME = "{DISPLAY_NAME}"', self.SRC)
        self.assertNotIn('"PEPEMARKETWIZARD"', self.SRC)
        self.assertNotIn('author="PepeMarketWizard"', self.SRC)
        self.assertNotIn("tytuł okna: <b>PepeMarketWizard", self.SRC)
        self.assertNotIn("korzystanie z PepeMarketWizard 1.30", self.SRC)
        self.assertNotIn('"PepeMarketWizard – instrukcja', self.SRC)

    def test_no_otc_and_no_removed_intro_in_the_current_chapters(self):
        client = _func(self.SRC, "client")
        admin = _func(self.SRC, "admin")
        ch1 = admin[admin.index('P("1 / Pierwsze uruchomienie"'):admin.index('P("2 /')]
        for txt in (client, ch1):
            self.assertNotIn("OTC", txt)
            self.assertNotIn("$PEPEMARKET WIZARD", txt)
            self.assertNotIn("lotu przez sieć neuronów", txt)
            self.assertNotIn("Galaxy", txt)
            self.assertNotIn("JOIN THE CULT", txt)
            self.assertIn("TraderLifeGame", txt)
        self.assertNotIn("Menu główne ma osiem wież", client)
        self.assertNotIn("sześć wież", self.SRC)


class TestInstallGuideTexts(unittest.TestCase):
    """tools/make_install_guide.py: window title (chunk_50#7) and the interface of 1.42+ (chunk_50#6)."""
    SRC = _src("make_install_guide.py")

    def test_window_title_and_removed_interface(self):
        self.assertNotIn("tytuł okna: PepeMarketWizard", self.SRC)
        self.assertIn("tytuł okna: {D} {V}", self.SRC)
        for gone in ("POMIŃ INTRO", "<b>Menu Galaxy</b>", "menu główne <b>Galaxy</b>", "Poprzednie menu Neural City", "Aktualizacja z 1.38",
                     "System Control → Tryb", '"PepeMarketWizard – instalacja'):
            self.assertNotIn(gone, self.SRC)
        self.assertIn("TraderLifeGame", self.SRC)


class TestEasyGuideTexts(unittest.TestCase):
    """tools/make_easy_guide.py: no OTC planet (chunk_50#4), Apollo23 where the UI shows it (chunk_50#5)."""
    SRC = _src("make_easy_guide.py")

    def test_menu_planets_and_display_name(self):
        self.assertNotIn("<b>OTC</b>", self.SRC)
        self.assertIn("<b>TraderLifeGame</b>", self.SRC)
        self.assertNotIn("PEPEMARKETWIZARD", self.SRC)
        self.assertNotIn('"PepeMarketWizard – instalacja', self.SRC)
        self.assertNotIn('author="PepeMarketWizard"', self.SRC)
        self.assertIn("Apollo23_DESKTOP_KLIENT_", self.SRC)
        splash = (ROOT / "desktop" / "splash.html").read_text(encoding="utf-8")
        dialogs = (ROOT / "frontend" / "src" / "components" / "Dialogs.tsx").read_text(encoding="utf-8")
        self.assertIn("APOLLO23 <span", splash)                 # the texts the guide points to exist in the UI
        self.assertIn("Zatrzymaj Apollo23", dialogs)
        self.assertIn("{DISPLAY.upper()} TEAM", self.SRC)
        self.assertIn("Zatrzymaj {DISPLAY}", self.SRC)


def _has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


@unittest.skipUnless(_has("reportlab") and _has("PIL"), "reportlab / Pillow not installed")
class TestManualImageCache(unittest.TestCase):
    """chunk_51#8: two screenshots with the same file name in different folders get different intermediate JPEGs."""

    def test_same_file_name_in_two_folders(self):
        import make_manuals as M
        from PIL import Image as PILImage
        tmp = Path(tempfile.mkdtemp(prefix="mq_t_manual_"))
        try:
            shots = tmp / "shots"
            for folder, color in (("ui_training_center", (255, 0, 0)), ("ui_license", (0, 0, 255))):
                (shots / folder).mkdir(parents=True)
                PILImage.new("RGB", (1500, 300), color).save(shots / folder / "01_panel.png")
            try:
                M.fonts()
            except SystemExit:
                self.skipTest("DejaVu fonts not installed")
            M.styles()
            with mock.patch.object(M, "ROOT", tmp):
                a = M.shot(shots, "ui_training_center/01_panel.png", "a")[0]._content[0].filename
                b = M.shot(shots, "ui_license/01_panel.png", "b")[0]._content[0].filename
                c = M.shot(shots, "ui_license/01_panel.png", "c", crop=(0, 0, 1, 0.5))[0]._content[0].filename
            self.assertEqual(len({a, b, c}), 3, (a, b, c))
            self.assertGreater(PILImage.open(a).convert("RGB").getpixel((5, 5))[0], 200)       # red stays red
            self.assertGreater(PILImage.open(b).convert("RGB").getpixel((5, 5))[2], 200)       # blue
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================================== integration_matrix (chunk_50#8)
class TestIntegrationMatrixArchival(unittest.TestCase):
    def test_missing_entries_do_not_overwrite_the_documents(self):
        import integration_matrix as im
        with mock.patch.object(Path, "write_text") as wt, redirect_stdout(io.StringIO()):
            rc = im.main([])
            m = im.build(None)
        if not m["summary"]["missing"]:
            self.skipTest("the 1.33 matrix is complete on this tree")
        self.assertEqual(rc, 1)
        wt.assert_not_called()
        self.assertEqual(m["version"], "1.33.0")


# ============================================================================================== launcher (focus_X5#3)
class TestLauncherBanner(unittest.TestCase):
    SRC = _src("launcher/main.go")

    def test_source_has_no_frozen_version(self):
        self.assertNotIn('const version = "1.25.0"', self.SRC)
        self.assertNotIn('fmt.Printf("PepeMarketWizard %s', self.SRC)
        self.assertNotIn("=== PepeMarketWizard %s ===", self.SRC)

    @unittest.skipUnless(shutil.which("go"), "Go toolchain not installed")
    def test_banner_shows_display_name_and_package_version(self):
        tmp = Path(tempfile.mkdtemp(prefix="mq_t_launcher_"))
        try:
            exe = tmp / "launcher"
            r = subprocess.run(["go", "build", "-o", str(exe), "."], cwd=str(TOOLS / "launcher"), capture_output=True, text=True, timeout=300, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            (tmp / "backend" / "masterquo").mkdir(parents=True)
            (tmp / "backend" / "masterquo" / "version.py").write_text('APP_NAME = "PepeMarketWizard"\nAPP_VERSION = "9.8.7"\n', encoding="utf-8")
            r = subprocess.run([str(exe)], cwd=str(tmp), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
            self.assertIn("Apollo23 9.8.7 - launcher", r.stdout)
            self.assertEqual(r.returncode, 2)                          # incomplete folder (no tools\check_python.py ...) - unchanged
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
