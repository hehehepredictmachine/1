"""1.46 audit, group B_misc_3 - regression tests (SYNTHETIC_TEST data / test doubles only, no network, no demo server).

chunk_12#6   kronos walk-forward M1: the session calendar is measured also on M5 bars closed by the end of DEV (was: always
             CALENDAR_INSUFFICIENT); an unusable calendar is reported BEFORE a model is loaded
focus_X7#4   edition: the client-package marker wins over an (empty) owner.py
chunk_18#2   LicenseGate: evaluate() racing activate() no longer restores the old key / locks the program (= focus_X7#5)
chunk_18#6   owner generator: the same key twice in one second returns the stored license, connections are closed (= focus_X7#8)
chunk_18#7   owner generator: a damaged private.key on disk can be replaced from the backup (raw copy kept)
chunk_18#8   owner generator: "Sprawdź klucz" with iat/exp out of the date range -> no exception
chunk_18#12  owner generator: exported key file name uses the display name Apollo23
focus_X4#7   marketdata export: H4/D1 refused explicitly (was COMPLETE with 0 rows); misaligned candles are counted (= chunk_18#4)
chunk_18#10  marketdata import_folder: the temporary folder is removed also when the archive is rejected
chunk_18#5   BridgeSource.offset: a stored / inconsistent clock offset is not labelled BRIDGE_CLOCK_MEASURED
chunk_18#3   signals tracking: no WIN/LOSS after max_hold_hours, TIMEOUT at the end of the window, enough bars are read (normal
             60 s tracking unchanged); an unknown exit price is null and not a breakeven in the stats
chunk_18#14  marketdata Store.first_time (dead code) removed
chunk_18#11  markets.analysis: D1 / 5D change relative to the current session
focus_X2#14  MarketBridge.book: missing provider time -> t None + TIME_UNAVAILABLE (was 0.0 = 1970)
chunk_18#15  signals.validate: one docstring
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import _env  # noqa: F401
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_testkit as K

WED_1200 = datetime(2026, 10, 28, 12, 0, 30, tzinfo=UTC).timestamp()
DAY = 86400


class _InProcStub:
    """Test double of the Kronos worker for the walk-forward mechanics: forecast = last close + 0.01 (no model)."""
    loads = 0

    def ask(self, req, timeout):
        if req["cmd"] == "load":
            type(self).loads += 1
            return {"ok": True, "info": {"device": "cpu"}}
        if req["cmd"] == "predict":
            last = req["candles"]["close"][-1]
            return {"ok": True, "pred": {"close": [last + 0.01] * req["pred_len"]}, "ms": 1.0}
        return {"ok": True}

    def close(self):
        pass


# ============================================================================================ Kronos walk-forward
class TestKronosValidation(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.dbs = []

    def tearDown(self):
        for db in self.dbs:
            db.close()
        self.td.close()

    def svc(self, bars_by: dict, synthetic=True, **settings):
        from masterquo.db.database import Database
        from masterquo.kronos.service import KronosService
        from masterquo.kronos.settings import SettingsStore
        st = SettingsStore(Path(self.td.dir) / "kronos" / "settings.json")
        if settings:
            st.update(settings)
        br = K.FakeBridge(bars_by, synthetic=synthetic)
        self.dbs.append(Database(Path(self.td.dir) / "t.sqlite"))
        return KronosService(K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")})), br, self.dbs[-1], K.Bus(), K.Log(),
                             settings=st), br

    def test_m1_walk_forward_has_a_session_calendar(self):
        """chunk_12#6: 8000 M1 bars < 7 days -> every origin was CALENDAR_INSUFFICIENT; now the calendar also uses M5 (DEV part only)."""
        from masterquo.kronos import validation as V
        m1 = K.make_bars(60, WED_1200, 8)
        m5 = K.make_bars(300, WED_1200, 30)
        svc, br = self.svc({("XAUUSD-", "M1"): m1, ("XAUUSD-", "M5"): m5})
        rep = V.run(svc, "XAUUSD", "M1", max_origins=60, client_factory=_InProcStub)
        self.assertEqual(rep["status"], "DONE", rep.get("verdict"))
        self.assertGreater(rep["evaluated"]["test"], 0, rep["skipped"])
        self.assertGreater(rep["evaluated"]["dev"], 0, rep["skipped"])
        self.assertNotIn("CALENDAR_INSUFFICIENT", rep["skipped"]["calendar_reasons"])
        self.assertEqual(rep["calendar"]["source"], "M5+M1")
        self.assertIn(("XAUUSD-", "M5", 8064), br.calls)

    def test_m1_calendar_uses_only_m5_bars_closed_by_dev_end(self):
        """No look-ahead: an M5 bar is used only when it closed by the close of the last DEV M1 bar."""
        from masterquo.kronos import calendar as CAL
        from masterquo.kronos import validation as V
        seen = {}
        orig = CAL.Calendar

        class Spy(orig):
            def __init__(self, t_raw, slot_sec):
                seen["t_raw"] = list(t_raw)
                super().__init__(t_raw, slot_sec)
        svc, _ = self.svc({("XAUUSD-", "M1"): K.make_bars(60, WED_1200, 8), ("XAUUSD-", "M5"): K.make_bars(300, WED_1200, 30)})
        with mock.patch.object(V.CAL, "Calendar", Spy):
            rep = V.run(svc, "XAUUSD", "M1", max_origins=60, client_factory=_InProcStub)
        self.assertEqual(rep["status"], "DONE")
        test_first = min(r["t"] for r in rep["rows"] if r["split"] == "TEST")     # open (UTC) of the last context bar of the 1st TEST origin
        dev_end_raw = int(datetime.fromisoformat(test_first).timestamp()) + K.OFF
        self.assertTrue(seen["t_raw"])
        self.assertLessEqual(max(seen["t_raw"]), dev_end_raw)

    def test_unusable_calendar_is_blocked_before_the_model_is_loaded(self):
        from masterquo.kronos import validation as V
        _InProcStub.loads = 0
        svc, _ = self.svc({("XAUUSD-", "M5"): K.make_bars(300, WED_1200, 3)})
        rep = V.run(svc, "XAUUSD", "M5", max_origins=60, client_factory=_InProcStub)
        self.assertEqual(rep["status"], "BLOCKED", rep.get("evaluated"))
        self.assertIn("kalendarz sesji", rep["verdict"]["reason"])
        self.assertEqual(_InProcStub.loads, 0)


# ============================================================================================ licensing
def _env_vars(**kw):
    from masterquo.licensing import hwid as H

    class _E:
        def __enter__(self):
            self.prev = {k: os.environ.get(k) for k in kw}
            for k, v in kw.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            H._sources.cache_clear()

        def __exit__(self, *a):
            for k, v in self.prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            H._sources.cache_clear()
    return _E()


class TestEdition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pmw_ed_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_client_marker_wins_over_an_empty_owner_file(self):
        from masterquo.licensing import edition as E
        from masterquo.licensing import gate as G
        empty_owner = Path(self.tmp) / "owner.py"
        empty_owner.write_text("", encoding="utf-8")                       # the attack: an empty owner.py added to a client package
        marker = Path(self.tmp) / "_edition.py"
        marker.write_text('EDITION = "CLIENT"\n', encoding="utf-8")       # written by the client build
        with _env_vars(PMW_EDITION=None), mock.patch.object(E, "_OWNER_FILE", empty_owner), mock.patch.object(E, "_CLIENT_MARKER", marker):
            self.assertEqual(E.edition(), "CLIENT")
            self.assertFalse(E.dev_overrides())
            self.assertTrue(G.LicenseGate(path=Path(self.tmp) / "license.dat").required)
        # without the marker (repository / owner edition) nothing changes
        with _env_vars(PMW_EDITION=None), mock.patch.object(E, "_OWNER_FILE", empty_owner), \
                mock.patch.object(E, "_CLIENT_MARKER", Path(self.tmp) / "missing_marker.py"):
            self.assertEqual(E.edition(), "OWNER")
            self.assertTrue(E.dev_overrides())

    def test_repository_has_no_client_marker(self):
        from masterquo.licensing import edition as E
        self.assertFalse(E._CLIENT_MARKER.exists())


class _BlockingNet:
    """Internet time double: no internet (None); the call from the 'monitor' thread waits until released (slow NetClock)."""

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def offset(self, refresh=False) -> float | None:
        if threading.current_thread().name == "lic-monitor-test":
            self.entered.set()
            self.release.wait(10)
        return None


class TestGateRace(unittest.TestCase):
    def setUp(self):
        import nacl.signing
        from masterquo.licensing import hwid as H
        self.tmp = tempfile.mkdtemp(prefix="pmw_lic_race_")
        self.sk = nacl.signing.SigningKey(bytes(range(1, 33)))
        self.e = _env_vars(PMW_EDITION="CLIENT", PMW_TEST_PUBLIC_KEY_HEX=bytes(self.sk.verify_key).hex(),
                           PMW_TEST_HWID_SOURCES="guid-x|uuid-y")
        self.e.__enter__()
        self.here = H.get_hwid()
        self.t0 = 1_800_000_000

    def tearDown(self):
        self.e.__exit__()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_monitor_does_not_restore_the_old_key(self):
        from masterquo.licensing import gate as G
        from masterquo.licensing import signing as SG
        path = Path(self.tmp) / "license.dat"
        old = SG.sign_license(self.sk, "Jan", self.here, self.t0 - 40 * DAY, self.t0 - DAY)           # expired
        new = SG.sign_license(self.sk, "Jan", self.here, self.t0, self.t0 + 30 * DAY)
        path.write_text(json.dumps({"schema": "PMW-LIC-1", "key": old}), encoding="utf-8")
        net = _BlockingNet()
        g = G.LicenseGate(clock=lambda: float(self.t0), net=net, path=path)
        out = {}
        th = threading.Thread(target=lambda: out.update(st=g.evaluate()), name="lic-monitor-test", daemon=True)
        th.start()
        self.assertTrue(net.entered.wait(5))                                   # monitor read license.dat (old key), waits for the net
        a = g.activate(new)
        self.assertTrue(a["activated"], a)
        net.release.set()
        th.join(10)
        self.assertFalse(th.is_alive())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["key"], new)     # the new key stays in license.dat
        self.assertTrue(g.state()["valid"], g.state())
        self.assertFalse(g.locked)
        self.assertTrue(out["st"]["valid"], out["st"])

    def test_gate_iso_out_of_range_is_none(self):
        from masterquo.licensing import gate as G
        self.assertIsNone(G._iso(10 ** 20))
        self.assertEqual(G._iso(0), "1970-01-01T00:00:00Z")


class TestOwnerGenerator(unittest.TestCase):
    def setUp(self):
        from masterquo.licensing.owner import OwnerLicenses
        self.tmp = tempfile.mkdtemp(prefix="pmw_owner_")
        self.t = [1_800_000_000.0]
        self.o = OwnerLicenses(Path(self.tmp) / "owner", clock=lambda: self.t[0])
        self.o.create_keypair()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_license_twice_in_one_second(self):
        """chunk_18#6 / focus_X7#8: IntegrityError (HTTP 500) and an unclosed SQLite connection."""
        from masterquo.licensing import owner as O
        opened = []
        real_connect = sqlite3.connect

        class Conn(sqlite3.Connection):
            closed = False

            def close(self):
                type(self).closed = True
                self.closed_here = True
                super().close()

        def connect(*a, **kw):
            c = real_connect(*a, factory=Conn, **kw)
            c.closed_here = False
            opened.append(c)
            return c
        v = {"kind": "days", "days": 30}
        with mock.patch.object(O.sqlite3, "connect", connect):
            a = self.o.generate("Jan", "A1B2C-D3E4F-G5H6J-K7M8N", False, v, "pierwsza")
            b = self.o.generate("Jan", "A1B2C-D3E4F-G5H6J-K7M8N", False, v, "druga")
            rows = self.o.list()
        self.assertEqual(a["key"], b["key"])
        self.assertEqual(a["id"], b["id"])
        self.assertTrue(b.get("already_generated"))
        self.assertEqual(len(rows), 1)
        self.assertTrue(opened)
        self.assertTrue(all(c.closed_here for c in opened), [c.closed_here for c in opened])

    def test_damaged_private_key_can_be_restored_from_backup(self):
        """chunk_18#7: import refused with 400 because the FILE ON DISK was damaged; create_keypair refused too."""
        backup = self.o.export_key()
        damaged = self.o.key_path.read_text(encoding="ascii")[:60]
        self.o.key_path.write_text(damaged, encoding="ascii")
        self.assertIsNotNone(self.o.state()["key_error"])
        r = self.o.import_key(backup["content"])
        self.assertTrue(r["imported"], r)
        self.assertTrue(r["has_key"])
        self.assertEqual(r["public_key"], backup["public_key"])
        self.assertIn("uszkodzony", r["previous_key_damaged"])
        kept = Path(r["previous_key_backup"])
        self.assertEqual(kept.read_text(encoding="ascii"), damaged)                    # the damaged file is kept, byte for byte
        self.assertEqual(kept.parent, self.o.key_path.parent)

    def test_backup_names_never_collide(self):
        import nacl.signing
        from masterquo.licensing.owner import _key_text
        k1 = nacl.signing.SigningKey.generate()
        k2 = nacl.signing.SigningKey.generate()
        r1 = self.o.import_key(_key_text(bytes(k1), bytes(k1.verify_key), "x"), replace=True)
        r2 = self.o.import_key(_key_text(bytes(k2), bytes(k2.verify_key), "x"), replace=True)       # same second
        self.assertNotEqual(r1["previous_key_backup"], r2["previous_key_backup"])
        self.assertTrue(Path(r1["previous_key_backup"]).exists() and Path(r2["previous_key_backup"]).exists())

    def test_check_key_with_out_of_range_dates(self):
        """chunk_18#8: datetime.fromtimestamp(10**20) -> OverflowError -> HTTP 500."""
        from masterquo.licensing import license_key as LK
        payload = json.dumps({"v": 1, "u": "x", "iat": 10 ** 20, "exp": 10 ** 21}, separators=(",", ":")).encode()
        key = LK.PREFIX + LK.b64u(payload + bytes(64))
        r = self.o.check(key)
        self.assertIsNone(r["iat_iso"])
        self.assertIsNone(r["exp_iso"])
        self.assertFalse(r["valid"])

    def test_export_file_name_uses_display_name(self):
        """chunk_18#12."""
        self.assertTrue(self.o.export_key()["filename"].startswith("Apollo23_klucz_prywatny_"))


# ============================================================================================ marketdata
class _RowsSource:
    """Source double: copy_rates_range returns the given rows (server time)."""

    def __init__(self, rows):
        self.rows = rows

    def call(self, fn):
        m = NS(copy_rates_range=lambda *a: self.rows, TIMEFRAME_M5=5, TIMEFRAME_H1=16385)
        return fn(m)


class TestMarketDataExport(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_h4_d1_refused_instead_of_complete_with_zero_rows(self):
        """focus_X4#7 / chunk_18#4."""
        from masterquo.marketdata import export as EX
        from masterquo.marketdata.sources import DirectSource
        from masterquo.marketdata.store import Store
        from masterquo.mt5.fake import FakeMT5
        f = FakeMT5(history_days=10)
        f.initialize()
        src = DirectSource(f, offset=3 * 3600, offset_basis="TEST")
        for tfs in (("H4",), ("D1",), ("M5", "H4")):
            with self.assertRaises(ValueError) as cm:
                EX.run(src, Store(), "XAUUSD", "XAUUSD-", timeframes=tfs, lookback_days=3, sleep=lambda s: None)
            self.assertIn("UNSUPPORTED_TF", str(cm.exception))

    def test_misaligned_candles_are_counted(self):
        from masterquo.marketdata import export as EX
        off = 3 * 3600
        base = 1_800_000_000 // 300 * 300
        rows = [{"time": base + off + i * 300, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 1} for i in range(4)]
        rows.append({"time": base + off + 4 * 300 + 60, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "tick_volume": 1})
        tm = {"model": "UNIFORM", "offset_seconds": off}
        st: dict = {}
        out = EX._fetch(_RowsSource(rows), "X", "M5", base, base + 3600, base + 3600, tm, lambda s: None, st)
        self.assertEqual(len(out), 4)
        self.assertEqual(st["misaligned"], 1)

    def test_store_first_time_dead_code_removed(self):
        """chunk_18#14: Store.first_time had no caller anywhere (backend, tests, tools)."""
        from masterquo.marketdata.store import Store
        self.assertFalse(hasattr(Store, "first_time"))

    def test_import_folder_removes_temp_dir_on_rejected_archive(self):
        """chunk_18#10."""
        from masterquo.marketdata import export as EX
        from masterquo.marketdata.store import Store
        work = Path(tempfile.mkdtemp(prefix="pmw_imp_test_"))
        tmp_root = work / "tmp"
        tmp_root.mkdir()
        try:
            bad_path = work / "bad.zip"
            with zipfile.ZipFile(bad_path, "w") as z:
                z.writestr("../evil.txt", "x")
            no_manifest = work / "nomanifest.zip"
            with zipfile.ZipFile(no_manifest, "w") as z:
                z.writestr("XAUUSD/M5/x.csv", "x")
            broken = work / "broken.zip"
            broken.write_bytes(b"not a zip")
            with mock.patch("tempfile.tempdir", str(tmp_root)):
                for p in (bad_path, no_manifest, broken):
                    with self.assertRaises((ValueError, zipfile.BadZipFile)):
                        EX.import_folder(Store(), "XAUUSD", p)
                    self.assertEqual(list(tmp_root.iterdir()), [], p.name)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_bridge_source_offset_basis(self):
        """chunk_18#5: STORED_UNVERIFIED / INCONSISTENT offsets were labelled BRIDGE_CLOCK_MEASURED."""
        from masterquo.marketdata.sources import BridgeSource
        from masterquo.mt5.clock import OffsetEvidence, ServerClock
        clock = ServerClock()
        src = BridgeSource(NS(clock=clock, state="CONNECTED"))
        self.assertEqual(src.offset("X"), (None, "UNKNOWN"))
        clock.load_stored(10800, datetime(2026, 10, 1, tzinfo=UTC))
        off, basis = src.offset("X")
        self.assertEqual(off, 10800.0)
        self.assertTrue(basis.startswith("STORED_"), basis)
        self.assertIn("2026-10-01", basis)
        clock.evidence = OffsetEvidence(offset_seconds=10800, status="INCONSISTENT")
        self.assertEqual(src.offset("X"), (None, "BRIDGE_CLOCK_INCONSISTENT"))
        clock.evidence = OffsetEvidence(offset_seconds=7200, status="VERIFIED")
        self.assertEqual(src.offset("X"), (7200.0, "BRIDGE_CLOCK_MEASURED"))

    def test_inconsistent_offset_stops_the_export_time_model(self):
        from masterquo.marketdata import export as EX
        from masterquo.marketdata.sources import SourceError
        src = NS(offset=lambda s: (None, "BRIDGE_CLOCK_INCONSISTENT"))
        with self.assertRaises(SourceError) as cm:
            EX.time_model(src, "X", 1_800_000_000.0, None)
        self.assertIn("BRIDGE_CLOCK_INCONSISTENT", str(cm.exception))


# ============================================================================================ markets
def _bar(t, o, h, low, c, closed=True):
    return {"open_utc": t, "o": o, "h": h, "l": low, "c": c, "closed": closed, "tv": 1}


def _sig(**kw):
    s = {"signal_id": "BOT-1", "created_at": "2026-11-16T00:00:00Z", "status": "OPEN", "action": "BUY", "entry_type": "MARKET",
         "entry_price": 100.0, "stop_loss": 99.0, "take_profits_json": "[102.0]", "filled_at": "2026-11-16T00:00:00Z", "tp_hit": 0}
    s.update(kw)
    return s


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestSignalTracking(unittest.TestCase):
    T0 = datetime(2026, 11, 16, tzinfo=UTC).timestamp()

    def bars(self, hours, tp_at=None):
        out = []
        for i in range(int(hours * 4)):
            t = self.T0 + i * 900
            hi = 102.5 if tp_at is not None and t >= self.T0 + tp_at * 3600 else 100.6
            out.append(_bar(_iso(t), 100.4, hi, 99.6, 100.5 if t < self.T0 + 72 * 3600 else 101.5))
        return out

    def test_no_win_after_max_hold(self):
        """chunk_18#3: TP touched 80 h after a 72 h signal, tracked at 90 h -> was WIN; now TIMEOUT at the end of the window."""
        from masterquo.markets.signals import evaluate
        bars = self.bars(90, tp_at=80)
        u = evaluate(_sig(), bars, _iso(self.T0 + 90 * 3600), 72)
        self.assertEqual(u["status"], "TIMEOUT", u)
        self.assertEqual(u["closed_at"], _iso(self.T0 + 72 * 3600))           # the bar holding the end of the window
        self.assertEqual(u["exit_price"], 101.5)
        u = evaluate(_sig(), bars[: 72 * 4 - 2], _iso(self.T0 + 90 * 3600), 72)   # no bar at the window end (gap): last bar before it
        self.assertEqual((u["status"], u["exit_price"]), ("TIMEOUT", 100.5))

    def test_normal_tracking_timeout_is_unchanged(self):
        """Tracking every 60 s: at the end of the window the bar opening at the end is still forming - the exit is the last closed bar,
        exactly as before 1.46 (no delay, same price)."""
        from masterquo.markets.signals import evaluate
        bars = self.bars(72) + [_bar(_iso(self.T0 + 72 * 3600), 100.4, 102.5, 99.6, 100.7, closed=False)]
        u = evaluate(_sig(), bars, _iso(self.T0 + 72 * 3600 + 30), 72)
        self.assertEqual((u["status"], u["closed_at"], u["exit_price"]), ("TIMEOUT", _iso(self.T0 + 72 * 3600 - 900), 100.5))

    def test_window_not_covered_by_the_bars_read(self):
        """No bar of the window among the bars read: the exit price is unknown (null), not the price at resumption."""
        from masterquo.markets.signals import evaluate, stats
        late = [_bar(_iso(self.T0 + (100 + i / 4) * 3600), 101, 101.2, 100.8, 101.0) for i in range(8)]
        u = evaluate(_sig(), late, _iso(self.T0 + 103 * 3600), 72)
        self.assertEqual((u["status"], u["exit_price"], u["outcome_r"]), ("TIMEOUT", None, None))
        self.assertEqual(u["closed_at"], _iso(self.T0 + 72 * 3600))
        self.assertIsNone(evaluate(_sig(), [], _iso(self.T0 + 103 * 3600), 72))          # no bars at all: nothing decided (as before)
        s = stats([{"status": "TIMEOUT", "action": "BUY", "outcome_r": None}, {"status": "WIN", "action": "BUY", "outcome_r": 2.0}])
        self.assertEqual((s["closed"], s["wins"], s["breakeven"], s["losses"]), (2, 1, 0, 0))

    def test_loss_inside_the_window_still_counts(self):
        from masterquo.markets.signals import evaluate
        bars = self.bars(10)
        bars[8] = _bar(bars[8]["open_utc"], 100.0, 100.2, 98.5, 99.0)
        u = evaluate(_sig(), bars, _iso(self.T0 + 90 * 3600), 72)
        self.assertEqual((u["status"], u["outcome_r"]), ("LOSS", -1.0))

    def test_track_reads_bars_back_to_the_oldest_open_signal(self):
        from masterquo.markets.signals import BotSignalService
        from masterquo.timeutil import utcnow
        created = _iso(utcnow().timestamp() - 300 * 3600)
        calls = []

        def symbol_bars(sym, tf, n):
            calls.append((sym, tf, n))
            return []
        fake = NS(db=NS(query=lambda *a: [{"symbol": "EURUSD-", **_sig(created_at=created)}], execute=lambda *a: None),
                  bridge=NS(state="CONNECTED", symbol_bars=symbol_bars), cfg=NS(max_hold_hours=720))
        BotSignalService.track(fake)
        self.assertEqual(len(calls), 1)
        self.assertGreaterEqual(calls[0][2], 300 * 4)

    def test_validate_has_one_docstring(self):
        """chunk_18#15."""
        from masterquo.markets.signals import validate
        self.assertIn("Checks of a CONFIRMED setup", validate.__doc__)
        self.assertIn("rr_block_below", validate.__doc__)


class TestMarketAnalysisChange(unittest.TestCase):
    """chunk_18#11: change_5d_pct used closed[-6] (6 sessions); with the market closed change_d1_pct was ~0."""

    @staticmethod
    def series(step, n, start=100.0):
        t0 = datetime(2026, 6, 1, tzinfo=UTC).timestamp()
        return [_bar(_iso(t0 + i * step), start + i - 0.5, start + i + 1, start + i - 1, start + i) for i in range(n)]

    def run_analyze(self, d1):
        from masterquo.markets import analysis
        bars = {"H1": self.series(3600, 80), "H4": self.series(14400, 80), "D1": d1}
        with mock.patch.object(analysis.volzones, "compute", return_value={"status": "UNAVAILABLE"}):
            return analysis.analyze("EURUSD-", bars, {"digits": 2}, {"bid": 200.0}, None)

    def test_forming_d1(self):
        d1 = self.series(DAY, 70) + [_bar(_iso(datetime(2026, 6, 1, tzinfo=UTC).timestamp() + 70 * DAY), 170, 171, 169, 170.5,
                                          closed=False)]
        a = self.run_analyze(d1)
        self.assertEqual(a["status"], "OK", a)
        closes = [b["c"] for b in d1 if b["closed"]]
        self.assertEqual(a["change_d1_pct"], round(100 * (200.0 / closes[-1] - 1), 2))
        self.assertEqual(a["change_5d_pct"], round(100 * (200.0 / closes[-5] - 1), 2))

    def test_market_closed_last_d1_closed(self):
        d1 = self.series(DAY, 70)
        a = self.run_analyze(d1)
        closes = [b["c"] for b in d1]
        self.assertEqual(a["change_d1_pct"], round(100 * (200.0 / closes[-2] - 1), 2))
        self.assertEqual(a["change_5d_pct"], round(100 * (200.0 / closes[-6] - 1), 2))


class TestBookTime(unittest.TestCase):
    """focus_X2#14."""

    def bridge(self, book):
        from masterquo.markets import universe as MU
        ins = NS(instrument_id="HL|core|BTC|0", native_symbol="BTC", display="BTC", market="CRYPTO")
        return MU.CryptoMarketBridge(NS(post=lambda req: book), NS(instruments=lambda: [ins], error=None))

    def test_missing_time_is_null(self):
        b = self.bridge({"levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "2"}]]}).book("BTC")
        self.assertIsNone(b["t"])
        self.assertEqual(b["time_status"], "TIME_UNAVAILABLE")
        self.assertEqual(b["bids"], [[100.0, 1.0]])

    def test_time_is_kept(self):
        b = self.bridge({"time": 1_800_000_000_000, "levels": [[], []]}).book("BTC")
        self.assertEqual(b["t"], 1_800_000_000.0)
        self.assertEqual(b["time_status"], "OK")


if __name__ == "__main__":
    unittest.main()
