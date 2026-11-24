"""1.46 arch, grupa „lab” (decyzje D14, D23 z docs/arch146/ETAP2_PROJEKT.md). Każdy test nie przechodzi na kodzie sprzed poprawki.

* D14 (SI quotes, lab/si_service.quote_tick): każdy wiersz quote_forecasts i quote_outcomes był zapisywany osobnym Database.execute =
  osobną transakcją BEGIN IMMEDIATE / COMMIT w głównej bazie bota (migawka co 1 s -> dziesiątki tysięcy commitów na dobę). Teraz jedna
  transakcja na migawkę, zawartość wierszy bez zmian; migawka bez prognoz i ocen nie otwiera transakcji. Retencji NIE dodano (S0(c)).
* D23 (flow context, lab/flow_context/service._Key._load_models): Markov3 / MarkovDiff dopasowany na danych nie-REAL (meta.json role
  TEST_ONLY) był wczytywany do komórki SI M1. Teraz nie jest wczytywany (komórka pokazuje MODEL_TEST_ONLY_NOT_LOADED z data_kind), chyba
  że ustawiono zmienną testów PMW_FLOW_ALLOW_TEST_MODEL=1. RESEARCH (REAL_USER_DATA) i model 1.46.0 bez meta.json (UNKNOWN) - wczytywane
  jak dotąd. Tylko panel: Markov3 nie ma konsumenta w decyzjach.
* D23 - uwagi przeglądu:
  - `models check --smoke --area lab --only 'flow:markov3'` dawał BŁĄD (predykcja i kontrakt FAIL, MODEL_TEST_ONLY_NOT_LOADED), bo smoke
    trenuje Markov na SYNTHETIC_TEST. Teraz smoke sprawdza bramkę D23 (bez zmiennej: MODEL_TEST_ONLY_NOT_LOADED), a ścieżkę komórki SI
    z modelem uruchamia z PMW_FLOW_ALLOW_TEST_MODEL=1 tylko w procesie obszaru (tymczasowy MASTERQUO_DATA_DIR) -> DZIAŁA;
  - `flow-context train-markov --allow-synthetic-fixture` (TEST_ONLY) przestawiał markov/latest.txt z modelu RESEARCH (REAL_USER_DATA)
    na model testowy, którego komórka SI nie wczytuje - panel tracił model REAL. Teraz model TEST_ONLY nie zastępuje RESEARCH w latest.txt;
  - model był wczytywany tylko przy tworzeniu klucza (inst, tf): po nowym treningu komórka pokazywała MODEL_MISSING /
    MODEL_TEST_ONLY_NOT_LOADED aż do restartu. Teraz zmiana markov/latest.txt przeładowuje model.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import _env
from _env import TempData


# ---------------------------------------------------------------------------------------------------------------------------------- D14
class _Bridge:
    state = "CONNECTED"
    session_epoch = 1

    def __init__(self):
        self.symbol_info = {"trade_tick_size": 0.01, "point": 0.01}

    def ticks(self, sym, secs):
        return {"status": "ok", "ticks": [], "source": "TEST", "clock_transform": None}


class _Engine:
    """Deterministic stand-in for lab.quotes.QuoteEngine: N forecasts emitted, M forecasts scored on this snapshot."""

    def __init__(self, n_fc: int, n_sc: int):
        self.n_fc, self.n_sc = n_fc, n_sc
        self.last_tick_ms = 1_780_000_000_000
        self.origin_ms = 1_780_000_000_000

    def ingest(self, ticks):
        pass

    def snapshot(self, now_ms):
        return {"seq": 7, "phase": "OPEN", "_fits": {}}

    def emit(self, snap, now_ms):
        return [{"forecast_id": f"fc{i}", "context": "XAUUSD|XAUUSD-", "side": "BID" if i % 2 else "ASK", "scale": 5 + i,
                 "issued_s": float(i), "target_s": float(i + 5), "price": 2000.0 + i} for i in range(self.n_fc)]

    def score(self, now_ms):
        return [{"forecast_id": f"old{i}", "status": "SCORED", "outcome": 0.5 + i, "error": 0.01 * i} for i in range(self.n_sc)]


class TestSIQuoteSnapshotSingleTransaction(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        self.db = Database()
        self.tx = 0
        orig = self.db.tx

        def spy():
            self.tx += 1
            return orig()
        self.db.tx = spy                                                    # Database.execute opens its transaction through self.tx()

    def tearDown(self):
        self.td.close()

    def _si(self, n_fc: int, n_sc: int):
        from masterquo.lab.si_service import StructureIntelligenceService
        cfg = types.SimpleNamespace(get=lambda: types.SimpleNamespace(mt5=types.SimpleNamespace(symbol="XAUUSD-"),
                                                                      assets=types.SimpleNamespace(active="XAUUSD")))
        bus = types.SimpleNamespace(publish=lambda *a, **k: None)
        b = _Bridge()
        si = StructureIntelligenceService(cfg, b, self.db, bus, lambda *a, **k: None)
        si.quote_engine, si.quote_key = _Engine(n_fc, n_sc), ("XAUUSD", "XAUUSD-", b.session_epoch)
        return si

    def test_one_transaction_per_snapshot_same_rows(self):
        si = self._si(4, 3)
        pub = si.quote_tick(force_snapshot=True)
        self.assertEqual(pub["seq"], 7)
        self.assertEqual(self.tx, 1)                                        # 1.46.0: 4 + 3 = 7 transactions (one per row)
        eng = si.quote_engine
        f = self.db.query("SELECT forecast_id, context, side, scale, issued_at, target_at, payload FROM quote_forecasts ORDER BY forecast_id")
        self.assertEqual([r["forecast_id"] for r in f], ["fc0", "fc1", "fc2", "fc3"])
        for r, fc in zip(f, eng.emit(None, 0)):
            self.assertEqual((r["context"], r["side"], r["scale"]), (fc["context"], fc["side"], fc["scale"]))
            self.assertEqual(json.loads(r["payload"]), fc)
        self.assertEqual(f[1]["issued_at"][:19], "2026-05-28T20:26:41")    # origin 1_780_000_000 s + issued_s 1
        self.assertEqual(f[1]["target_at"][:19], "2026-05-28T20:26:46")
        o = self.db.query("SELECT forecast_id, status, outcome, error, payload FROM quote_outcomes ORDER BY forecast_id")
        self.assertEqual([(r["forecast_id"], r["status"], r["outcome"], r["error"]) for r in o],
                         [(m["forecast_id"], m["status"], m["outcome"], m["error"]) for m in eng.score(0)])
        self.assertEqual([json.loads(r["payload"]) for r in o], eng.score(0))

    def test_repeated_snapshot_ignores_duplicates_in_one_transaction(self):
        si = self._si(2, 2)
        si.quote_tick(force_snapshot=True)
        si.quote_tick(force_snapshot=True)
        self.assertEqual(self.tx, 2)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM quote_forecasts")["n"], 2)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM quote_outcomes")["n"], 2)

    def test_empty_snapshot_opens_no_transaction(self):
        si = self._si(0, 0)
        self.assertIsNotNone(si.quote_tick(force_snapshot=True))
        self.assertEqual(self.tx, 0)


# ---------------------------------------------------------------------------------------------------------------------------------- D23
ALLOW = "PMW_FLOW_ALLOW_TEST_MODEL"


class TestFlowContextTestOnlyNotLoaded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_structure_intelligence import m1_bars
        cls.bars = m1_bars(2600)

    def setUp(self):
        self.td = TempData()
        env = {k: v for k, v in os.environ.items() if k != ALLOW}
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        from masterquo.lab.flow_context import cli as FC
        self.out = FC.train_markov("XAUUSD", self.bars, 0.01, 0.01, {"data_kind": "SYNTHETIC_TEST"})
        self.meta = Path(self.out["dir"]) / "meta.json"

    def tearDown(self):
        self.env.stop()
        self.td.close()

    def _key(self):
        from masterquo.lab.flow_context import service as FS
        fs = FS.FlowSections()
        return fs, fs.update("XAUUSD", "M1", self.bars[-900:], 0.01, 0.01)

    def test_test_only_model_is_not_loaded(self):
        self.assertEqual(self.out["role"], "TEST_ONLY")
        fs, k = self._key()
        self.assertIsNone(k.m3)                                             # 1.46.0: loaded into the SI M1 cell
        self.assertIsNone(k.md)
        m3 = fs.summary(k)["markov3"]
        self.assertEqual(m3["status"], "MODEL_TEST_ONLY_NOT_LOADED")
        self.assertEqual((m3["model_role"], m3["data_kind"]), ("TEST_ONLY", "SYNTHETIC_TEST"))
        self.assertNotIn("next", m3)
        self.assertEqual(fs.summary(k)["buckets"]["status"], "MODEL_TEST_ONLY_NOT_LOADED")
        mk = fs.markov(k)
        self.assertEqual((mk["status"], mk["model_role"], mk["data_kind"]), ("MODEL_TEST_ONLY_NOT_LOADED", "TEST_ONLY", "SYNTHETIC_TEST"))

    def test_test_only_model_loaded_with_the_test_variable(self):
        with mock.patch.dict(os.environ, {ALLOW: "1"}):
            fs, k = self._key()
        self.assertIsNotNone(k.m3)
        m3 = fs.summary(k)["markov3"]
        self.assertIn("next", m3)
        self.assertEqual((m3["model_role"], m3["data_kind"]), ("TEST_ONLY", "SYNTHETIC_TEST"))

    def test_research_model_on_real_data_is_loaded(self):
        self.meta.write_text(json.dumps({"data_kind": "REAL_USER_DATA", "role": "RESEARCH"}), encoding="utf-8")
        fs, k = self._key()
        self.assertIsNotNone(k.m3)
        self.assertEqual(fs.summary(k)["markov3"]["model_role"], "RESEARCH")
        self.assertEqual(fs.markov(k)["status"], "OK")

    def test_model_without_meta_is_loaded_as_unknown(self):
        self.meta.unlink()                                                  # a run of 1.46.0: provenance unknown, still loaded
        fs, k = self._key()
        self.assertIsNotNone(k.m3)
        self.assertEqual(k.model_meta["role"], "UNKNOWN")
        self.assertEqual(fs.summary(k)["markov3"]["model_role"], "UNKNOWN")

    # ------------------------------------------------------------------ review of D23: latest.txt and reload
    def _latest(self) -> Path:
        from masterquo.lab.flow_context import task as FT
        return FT.root("XAUUSD") / "markov" / "latest.txt"

    def _age(self, out: dict, name: str = "20200101T000000Z") -> Path:
        """Move a fit to an older run folder (train_markov names runs by the second) and repoint latest.txt when it named that fit."""
        src = Path(out["dir"])
        dst = src.parent / name
        src.rename(dst)
        if self._latest().exists() and Path(self._latest().read_text(encoding="utf-8").strip()) == src:
            self._latest().write_text(str(dst), encoding="utf-8")
        return dst

    def _fit(self, data_kind: str) -> dict:
        from masterquo.lab.flow_context import cli as FC
        return FC.train_markov("XAUUSD", self.bars, 0.01, 0.01, {"data_kind": data_kind})

    def test_test_only_fit_does_not_replace_research_latest(self):
        self.meta.write_text(json.dumps({"data_kind": "REAL_USER_DATA", "role": "RESEARCH"}), encoding="utf-8")
        research = self._age(self.out)
        out = self._fit("SYNTHETIC_TEST")                                   # manual train-markov --allow-synthetic-fixture on a real folder
        self.assertEqual(out["role"], "TEST_ONLY")
        self.assertTrue((Path(out["dir"]) / "markov3.json").exists())       # the test fit is still saved
        self.assertEqual(Path(self._latest().read_text(encoding="utf-8").strip()), research)   # 1.46.0 arch: latest -> the TEST_ONLY fit
        self.assertEqual(out["latest_unchanged"]["model_role"], "RESEARCH")
        self.assertEqual(out["latest_unchanged"]["model_dir"], str(research))
        self.assertIn("RESEARCH", out["si_cell"])
        fs, k = self._key()
        self.assertIsNotNone(k.m3)                                          # the SI cell keeps the REAL model
        self.assertEqual(fs.summary(k)["markov3"]["model_role"], "RESEARCH")

    def test_test_only_fit_still_replaces_a_test_or_unknown_latest(self):
        self._age(self.out)                                                 # latest = an older TEST_ONLY fit
        out = self._fit("SYNTHETIC_TEST")
        self.assertEqual(Path(self._latest().read_text(encoding="utf-8").strip()), Path(out["dir"]))
        self.assertNotIn("latest_unchanged", out)
        self.assertIn("MODEL_TEST_ONLY_NOT_LOADED", out["si_cell"])

    def test_research_fit_always_becomes_latest(self):
        self._age(self.out)
        out = self._fit("REAL_USER_DATA")
        self.assertEqual(out["role"], "RESEARCH")
        self.assertEqual(Path(self._latest().read_text(encoding="utf-8").strip()), Path(out["dir"]))
        self.assertNotIn("si_cell", out)

    def test_new_fit_is_loaded_without_restart_after_test_only_not_loaded(self):
        self._age(self.out)
        fs, k = self._key()
        self.assertEqual(fs.summary(k)["markov3"]["status"], "MODEL_TEST_ONLY_NOT_LOADED")
        out = self._fit("REAL_USER_DATA")                                   # the hint of the cell: fit Markov on REAL_USER_DATA
        k2 = fs.update("XAUUSD", "M1", self.bars[-900:], 0.01, 0.01)       # same bars, no new candle
        self.assertIs(k2, k)
        self.assertIsNotNone(k2.m3)                                         # 1.46.0: NOT_LOADED until a restart / profile change
        self.assertIsNone(k2.model_skipped)
        m3 = fs.summary(k2)["markov3"]
        self.assertIn("next", m3)
        self.assertEqual(m3["model_role"], "RESEARCH")
        self.assertEqual(fs.markov(k2)["model_dir"], out["dir"])

    def test_new_fit_is_loaded_without_restart_after_model_missing(self):
        self._latest().unlink()
        fs, k = self._key()
        self.assertEqual(fs.summary(k)["markov3"]["status"], "MODEL_MISSING")
        self._age(self.out)
        self._fit("REAL_USER_DATA")
        k2 = fs.update("XAUUSD", "M1", self.bars[-900:], 0.01, 0.01)
        self.assertIsNotNone(k2.m3)                                         # 1.46.0: MODEL_MISSING until a restart
        self.assertIn("next", fs.summary(k2)["markov3"])
        self._latest().unlink()                                             # latest removed -> model unloaded, MODEL_MISSING again
        k3 = fs.update("XAUUSD", "M1", self.bars[-900:], 0.01, 0.01)
        self.assertIsNone(k3.m3)
        self.assertEqual(fs.summary(k3)["markov3"]["status"], "MODEL_MISSING")

    def test_unchanged_latest_does_not_reload(self):
        self.meta.write_text(json.dumps({"data_kind": "REAL_USER_DATA", "role": "RESEARCH"}), encoding="utf-8")
        fs, k = self._key()
        m3, last = k.m3, k.m3_last
        self.assertIsNotNone(m3)
        with mock.patch("masterquo.lab.flow_context.service.MK.Markov3.from_dict", side_effect=AssertionError("reloaded")):
            k2 = fs.update("XAUUSD", "M1", self.bars[-900:], 0.01, 0.01)
        self.assertIs(k2.m3, m3)
        self.assertIs(k2.m3_last, last)


# ------------------------------------------------------------------------------------------------- D23: models check smoke (lab, flow)
class TestModelsCheckFlowSmoke(unittest.TestCase):
    """`models check --smoke --area lab --only 'flow:*'` (43_MODELE_KONTROLA.bat options 2 and 3) on a temporary folder."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_flow_smoke_works_and_reports_the_d23_gate(self):
        out = Path(self.td.dir) / "mc.json"
        backend = _env.ROOT / "backend"
        env = {k: v for k, v in os.environ.items() if k != ALLOW}          # the caller never sets the test opt-in
        env.update(PYTHONPATH=str(backend), PMW_BOOTSTRAP="0", MASTERQUO_DATA_DIR=self.td.dir)
        r = subprocess.run([sys.executable, "-m", "masterquo", "models", "check", "--smoke", "--area", "lab", "--only", "flow:*",
                            "--json", str(out)], cwd=str(backend), env=env, capture_output=True, text=True, timeout=900, check=False)
        self.assertEqual(r.returncode, 0, r.stdout[-2500:] + r.stderr[-1500:])     # after D23 (b): 1 (flow:markov3 BŁĄD)
        rows = {x["id"]: x for x in json.loads(out.read_text(encoding="utf-8"))["rows"]}
        self.assertEqual(sorted(rows), ["flow:markov3", "flow:reaction_m1"])
        for cid, row in rows.items():
            self.assertEqual(row["status"], "DZIAŁA", (cid, row))
            self.assertEqual({k: v["status"] for k, v in row["steps"].items() if k in ("train", "artifact", "predict", "contract")},
                             {"train": "OK", "artifact": "OK", "predict": "OK", "contract": "OK"}, cid)
        st = rows["flow:markov3"]["steps"]
        self.assertIn("MODEL_TEST_ONLY_NOT_LOADED", st["predict"]["detail"])   # the D23 gate itself is checked, not bypassed
        self.assertIn("D23 (b)", st["contract"]["detail"])
        self.assertNotIn("bez zmian", st["contract"]["detail"])
        self.assertEqual(sorted(p.name for p in Path(self.td.dir).iterdir()), ["mc.json"])   # the caller's data folder stays untouched


if __name__ == "__main__":
    unittest.main()
