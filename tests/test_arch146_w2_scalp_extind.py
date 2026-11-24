"""Fala 2 (1.46 arch), grupa scalp_extind: extind (indicator context, archiwum IQ) + scalp SHADOW + rezerwacja holdoutu + 17_.bat.

Każda klasa nazywa pozycję triażu (I0xxx). Dane syntetyczne (SYNTHETIC_TEST) – testy ścieżki kodu, nie jakości modeli."""
from __future__ import annotations

import ast
import contextlib
import json
import math
import os
import pickle
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")            # small fits: OpenMP threads on a shared CPU only spin (minutes instead of seconds)

from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent / "scalp"))

ROOT = Path(__file__).resolve().parent.parent


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one_thread():
    """threadpool limit for the sklearn fits of these tests (the runtime must be loaded before the limit applies to it)."""
    try:
        import sklearn.ensemble
        import sklearn.linear_model  # noqa: F401
        from threadpoolctl import threadpool_limits
        return threadpool_limits(1)
    except ImportError:
        return contextlib.nullcontext()


# ------------------------------------------------------------------------------------------------------------ extind helpers
def _protocol_rows(n=300, t0=datetime(2026, 1, 5, tzinfo=UTC), step_h=1.0, atr_none_every=0, seed=5):
    import numpy as np
    from masterquo.scalp.strategy import SETUP_FEATURES
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n):
        t = t0 + timedelta(hours=step_h * k)
        base = {f: float(rng.normal()) for f in SETUP_FEATURES}
        y = int(rng.random() < 1 / (1 + math.exp(-1.5 * base["er10"])))
        atr = None if (atr_none_every and k % atr_none_every == 0) else 1.0
        rows.append({"side": "BUY" if k % 2 else "SELL", "decision_time": t.isoformat(), "exit_time": (t + timedelta(minutes=20)).isoformat(),
                     "price": 100.0, "atr_m5": atr, "base": base, "y": y, "net_r": 1.0 if y else -1.0, "ext": {}})
    return rows


def _bars_hourly(t0: datetime, n: int, start_back: int = 120) -> list[dict]:
    """'M5' bars for the SAR composer (spacing is not checked by the composer): one per hour, a gentle zig-zag."""
    out = []
    for k in range(-start_back, n):
        o = t0 + timedelta(hours=k) - timedelta(minutes=5)
        c = 100 + 2 * math.sin(k / 7.0)
        out.append({"open_utc": _iso(o), "o": c - 0.1, "h": c + 0.6, "l": c - 0.6, "c": c})
    return out


def _fitted_artifact(td_dir: str, role: str = "shadow_candidate"):
    """run_variant(BASE) on a generated table + _save_artifact -> (run dir, manifest, data, rows)."""
    from masterquo.extind import trainer
    rows = _protocol_rows(400)
    data = {"rows": rows, "bars": {"M5": [], "M15": []}, "symbol": "X", "dataset_id": "fx", "data_kind": "SYNTHETIC_TEST", "profile_id": "p"}
    with _one_thread():
        r = trainer.run_variant(data, ("BASE",), trainer.split(rows))
    assert r["status"] == "EVALUATED", r
    rd = Path(td_dir) / "run"
    rd.mkdir(parents=True, exist_ok=True)
    trainer._save_artifact(rd, "XAUUSD", r, data, {"role": role})
    return rd, json.loads((rd / "model_BASE.json").read_text(encoding="utf-8")), data, rows


class TestTrainServeParity(unittest.TestCase):
    """I0164 + I0784: build_dataset must give the composer the live inputs - price = plan ref_close_bid (not the replay fill), atr_m5 =
    plan range.atr_m5 (not ATR14 of 40 M5 at the decision); V1 artefacts abstain and cannot be activated."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_replay_cycle_records_decision_inputs(self):
        import scenario as S
        from masterquo.scalp import replay
        from masterquo.scalp import strategy as st
        p = st.load_profile()
        p["context_filter"]["enabled"]["value"] = False
        bars, _ = S.build(p)
        res = replay.run(bars, p, 0.01, {"commission_price_side": 0.035, "slippage_price": 0.02})
        self.assertEqual(len(res["cycles"]), 1)
        c = res["cycles"][0]
        plans = S.run(p, bars)[1]
        self.assertEqual(c["ref_close_bid"], plans[0]["ref_close_bid"])
        self.assertEqual(c["range_atr_m5"], plans[0]["range"]["atr_m5"])
        self.assertNotEqual(c["ref_close_bid"], c["fill"])                    # the fill is the next open + spread + slippage

    def test_dataset_uses_decision_inputs(self):
        from masterquo.extind import trainer
        from masterquo.scalp import replay
        ds = Path(self.td.dir) / "ds"
        ds.mkdir()
        (ds / "source_metadata.json").write_text(json.dumps({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "symbol": "XAUUSD-", "data_kind": "SYNTHETIC_TEST",
                                                             "spec": {"point": 0.01, "trade_contract_size": 100.0}, "tick_size": 0.01}), encoding="utf-8")
        t0 = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
        hdr = "time_open_utc,open,high,low,close,tick_volume,spread_points\n"
        (ds / "XAUUSD_M1.csv").write_text(hdr + f"{_iso(t0)},100,101,99,100,10,10\n", encoding="utf-8")
        m5 = [f"{_iso(t0 - timedelta(minutes=5 * (60 - k)))},{100 + k % 3},{103 + k % 3},{97 + k % 3},{100 + k % 3},10,10" for k in range(60)]
        (ds / "XAUUSD_M5.csv").write_text(hdr + "\n".join(m5) + "\n", encoding="utf-8")
        (ds / "XAUUSD_M15.csv").write_text(hdr, encoding="utf-8")
        cyc = {"setup_id": "SET-1", "range_id": "RNG-1", "direction": "BUY", "decision_time": _iso(t0), "fill_time": _iso(t0 + timedelta(minutes=1)),
               "exits": [{"time": _iso(t0 + timedelta(minutes=9))}], "fill": 100.5, "ref_close_bid": 100.0, "range_atr_m5": 2.0,
               "features": {}, "tp1_before_sl": True, "net_r": 1.0}
        orig = replay.run
        replay.run = lambda *a, **k: {"cycles": [cyc]}
        try:
            data = trainer.build_dataset("XAUUSD", ds, commission=0.5, log=lambda m: None)
        finally:
            replay.run = orig
        row = data["rows"][0]
        self.assertEqual(row["price"], 100.0)                                 # ref_close_bid, not the fill 100.5
        self.assertEqual(row["atr_m5"], 2.0)                                  # range ATR, not ATR14 of the last 40 M5 (= 6.0 here)
        self.assertEqual((data["legacy_price_rows"], data["legacy_atr_rows"]), (0, 0))

    def test_old_schema_abstains(self):
        from masterquo.extind import trainer
        rd, man, _data, rows = _fitted_artifact(self.td.dir)
        man["feature_schema"] = "SCALP_INDICATOR_CONTEXT_V1"
        m = trainer.load_artifact(rd, "BASE", man)
        snap = {"decision_time": datetime(2026, 1, 5, tzinfo=UTC), "side": "BUY", "price": 1, "atr_m5": 1, "base": rows[0]["base"], "bars": {}, "ext": {}}
        out = m.predict(snap, "XAUUSD")
        self.assertEqual(out["status"], "ABSTAIN")
        self.assertTrue(out["reason"].startswith("FEATURE_SCHEMA_MISMATCH"), out)
        man2 = json.loads((rd / "model_BASE.json").read_text(encoding="utf-8"))
        self.assertEqual(trainer.load_artifact(rd, "BASE", man2).predict(snap, "XAUUSD")["status"], "READY_INFERENCE")   # current schema scores

    def test_activate_refuses_old_schema_and_keeps_registry(self):
        from masterquo.extind import trainer
        rd, man, _d, _r = _fitted_artifact(self.td.dir)
        man["feature_schema"] = "SCALP_INDICATOR_CONTEXT_V1"
        (rd / "model_BASE.json").write_text(json.dumps(man), encoding="utf-8")
        reg_p = trainer.root("XAUUSD") / "registry.json"
        reg = {"schema": "pmw-indicator-context-registry-1", "active": None, "runs": {"R1": {"run_dir": str(rd), "artifacts": ["model_BASE.json"]}}}
        reg_p.write_text(json.dumps(reg), encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            trainer.activate("XAUUSD", "R1", "BASE")
        self.assertIn("NOT_ACTIVATABLE_SCHEMA", str(cm.exception))
        self.assertIsNone(json.loads(reg_p.read_text(encoding="utf-8"))["active"])


class TestSarWindowLive(unittest.TestCase):
    """I0165 (+ I0077): live SAR gets SAR_WINDOW closed bars as in training, even when an M5 closed after the decision."""

    def test_live_sar_window_has_full_length(self):
        from masterquo.extind import features as F
        from masterquo.extind import trainer
        from masterquo.scalp.service import ScalpService
        T = datetime(2026, 3, 3, 12, 2, tzinfo=UTC)                         # decision at 12:02, M5 12:00-12:05 closes after it
        m5 = [{"open_utc": _iso(datetime(2026, 3, 3, 12, 0, tzinfo=UTC) - timedelta(minutes=5 * k)), "o": 1.0, "h": 1.5, "l": 0.5, "c": 1.0}
              for k in range(500)][::-1]
        seen = {}

        class Model:
            bars_needed = 404

            def predict(self, snap, inst):
                seen["bars"] = snap["bars"]
                return {"status": "READY_INFERENCE"}

        class Bridge:
            symbol_info = None

            def bars(self, tf, limit, include_forming=False):
                return (m5 if tf == "M5" else [])[-limit:]

        class Ext:
            def active_model(self, inst, why=None):
                return Model()

            def as_of(self, *a, **k):
                return None

        svc = ScalpService.__new__(ScalpService)
        svc.inst, svc.bridge, svc.extind = "XAUUSD", Bridge(), Ext()
        svc._bars = {"M5": Bridge().bars("M5", 400), "M15": []}                # what tick() stores (400 closed bars at 'now')
        orig = trainer.active_model
        trainer.active_model = lambda inst, why=None: Model()                 # the pre-I0077 code path asked extind.trainer directly
        try:
            plan = {"decision_ts": T.timestamp(), "decision_time": _iso(T), "direction": "BUY", "ref_close_bid": 1.0, "range": {"atr_m5": 1.0},
                    "features": {}, "setup_id": "S1"}
            out = svc.indicator_context(plan)
        finally:
            trainer.active_model = orig
        self.assertEqual(out["status"], "READY_INFERENCE")
        self.assertGreaterEqual(len(F._closed(seen["bars"]["M5"], "M5", T)), getattr(F, "SAR_WINDOW", 400))   # the composer's window [-SAR_WINDOW:] is full


class TestScalpDoesNotImportExtind(unittest.TestCase):
    """I0077: one dependency direction extind -> scalp; scalp asks the injected ExtIndService for the model."""

    def test_no_extind_import_in_scalp(self):
        bad = []
        for f in sorted((ROOT / "backend" / "masterquo" / "scalp").glob("*.py")):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module and (node.module == "extind" or node.module.startswith("extind.")
                                                                         or "masterquo.extind" in node.module):
                    bad.append(f"{f.name}:{node.lineno}")
                if isinstance(node, ast.Import) and any("masterquo.extind" in a.name for a in node.names):
                    bad.append(f"{f.name}:{node.lineno}")
        self.assertEqual(bad, [])

    def test_service_delegates_and_no_extind_is_no_model(self):
        from masterquo.extind import service as xs
        from masterquo.extind import trainer
        from masterquo.scalp.service import ScalpService
        got = []
        orig = trainer.active_model
        trainer.active_model = lambda inst, why=None: got.append(inst) or "M"
        try:
            self.assertEqual(xs.ExtIndService(None, None).active_model("XAUUSD"), "M")
        finally:
            trainer.active_model = orig
        self.assertEqual(got, ["XAUUSD"])
        svc = ScalpService.__new__(ScalpService)
        svc.inst, svc.extind, svc.bridge = "XAUUSD", None, None
        self.assertEqual(svc.indicator_context({"setup_id": "S", "decision_ts": 0, "decision_time": "x"})["status"], "NO_MODEL")


class TestProtocolLiveScorable(unittest.TestCase):
    """I0168: a variant with SAR is fitted / calibrated / evaluated only on rows with SAR OK (live abstains on the others)."""

    def test_variant_uses_only_live_scorable_rows(self):
        from masterquo.extind import trainer
        t0 = datetime(2026, 1, 5, tzinfo=UTC)
        rows = _protocol_rows(300, t0=t0, step_h=1.0, atr_none_every=3)       # every 3rd row: no ATR -> SAR WARMING_UP
        bars = _bars_hourly(t0, 300)
        data = {"rows": rows, "bars": {"M5": bars, "M15": bars}, "symbol": "X", "dataset_id": "fx", "data_kind": "SYNTHETIC_TEST", "profile_id": "p"}
        sp = trainer.split(rows)
        with _one_thread():
            r = trainer.run_variant(data, ("BASE", "SAR"), sp)
            base = trainer.run_variant(data, ("BASE",), sp)
        self.assertEqual(r["status"], "EVALUATED", r)
        _, ginfo = trainer.matrix(data, r["spec"])
        hold_ok = [i for i in sp["HOLDOUT"] if ginfo[i]["SAR"] == "OK"]
        self.assertLess(len(hold_ok), len(sp["HOLDOUT"]))
        self.assertEqual(r["holdout"]["n"], len(hold_ok))
        self.assertTrue(all(ginfo[i]["SAR"] == "OK" for i in r["_hold"]))
        self.assertEqual(base["holdout"]["n"], len(sp["HOLDOUT"]))            # BASE keeps every row
        vb = trainer.vs_base(data, r, base)                                     # paired on the same rows (no shape error)
        self.assertEqual(vb["rows"], len(hold_ok))


class TestArtifactEnvironment(unittest.TestCase):
    """I0170: the manifest records numpy / scikit-learn; another major.minor or an unpicklable file is a clear ValueError."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_artifact_env_mismatch(self):
        from masterquo.extind import trainer
        rd, man, _d, _r = _fitted_artifact(self.td.dir)
        self.assertIn("scikit-learn", man.get("dependencies") or {})
        man["dependencies"] = dict(man.get("dependencies") or {}, **{"scikit-learn": "0.1"})
        (rd / "model_BASE.json").write_text(json.dumps(man), encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            trainer.load_artifact(rd, "BASE")
        self.assertIn("ARTIFACT_ENV_MISMATCH", str(cm.exception))

    def test_unpicklable_artifact_is_value_error_and_no_model(self):
        import hashlib

        from masterquo.extind import trainer
        rd, man, _d, _r = _fitted_artifact(self.td.dir)
        blob = b"cno_such_module_xyz\nPrep\n."                                 # a class whose module is gone (refactor / other package)
        with self.assertRaises(ImportError):
            pickle.loads(blob)
        (rd / "model_BASE.pkl").write_bytes(blob)
        man["pkl_sha256"] = hashlib.sha256(blob).hexdigest()
        (rd / "model_BASE.json").write_text(json.dumps(man), encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            trainer.load_artifact(rd, "BASE")
        self.assertIn("ARTIFACT_UNREADABLE", str(cm.exception))


# ------------------------------------------------------------------------------------------------------------ archive (ExtIndService)
def _env_body(seq=1, gen=1, cap=1_800_000_000, objects=None, symbol="XAUUSD-", adapter="IQ_GOLD_GANN"):
    return {"schema_version": "pmw-extind-1", "producer_version": "test", "adapter_id": adapter, "product": {"version": "1.0"},
            "terminal_fingerprint": "Srv:001", "chart_id": "77", "symbol": symbol, "tf": "PERIOD_M5", "time_basis": "UTC",
            "captured_at_server": cap, "generation": gen, "sequence": seq, "complete": True,
            "objects": objects if objects is not None else [{"name": "IQG_major_1", "type": "HLINE", "prices": [2650.0], "times": []}]}


class _ArchiveCase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.extind import contract, mapping, service
        self.c, self.m, self.s = contract, mapping, service
        self.db = Database()
        self.cfg = ConfigStore()
        self.svc = service.ExtIndService(self.cfg, self.db)
        self.m.save_mapping("IQ_GOLD_GANN", {"product_version": "1.0", "approved": True, "verified_examples": [{"name": "IQG_major_1", "chart": 2650.0}],
                                             "rules": [{"prefix": "IQG_major", "type": "HLINE", "kind": "LEVEL", "role": "MAJOR"}]})

    def tearDown(self):
        self.td.close()

    def ing(self, now, **kw):
        return self.svc.ingest_bytes(self.c.wrap(_env_body(**kw)), now=now)

    def rows(self):
        return self.db.one("SELECT COUNT(*) AS n FROM extind_snapshots")["n"]


class TestUnmappedSymbol(_ArchiveCase):
    """I0175 (+ I0178): a read whose symbol is not in assets.mappings is reported, not silently invisible."""

    def test_unmapped_symbol_is_reported(self):
        t0 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
        self.assertEqual(self.ing(t0, symbol="XAUUSD"), 1)                    # mapping XAUUSD -> 'XAUUSD-' (default config)
        self.ing(t0 + timedelta(seconds=2), symbol="XAUUSD", seq=2)
        self.assertEqual([e["reason"] for e in self.svc.errors], ["UNMAPPED_SYMBOL:XAUUSD"])     # once per symbol
        st = self.svc.status("XAUUSD", t0 + timedelta(seconds=3))
        self.assertTrue(any("XAUUSD" in n and "assets.mappings" in n for n in st["adapters"]["IQ_GOLD_GANN"]["needs"]))
        self.assertEqual([(u["symbol"], u["count"]) for u in st["unmapped_symbols"]], [("XAUUSD", 2)])


class TestExporterRestart(_ArchiveCase):
    """I0728: generation / sequence restart from 0 after OnInit - a later capture is a new session, a re-read stays a duplicate."""

    def test_restart_is_archived_and_duplicate_is_not(self):
        t0 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
        for k in range(3):
            self.assertEqual(self.ing(t0 + timedelta(seconds=2 * k), seq=k + 1, cap=1_800_000_000 + 2 * k), 1)
        new_obj = [{"name": "IQG_major_1", "type": "HLINE", "prices": [2700.0], "times": []}]
        t1 = t0 + timedelta(minutes=10)
        self.assertEqual(self.ing(t1, seq=1, gen=1, cap=1_800_000_600, objects=new_obj), 1)        # restarted exporter: kept
        s = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t1 + timedelta(seconds=1))
        self.assertEqual([x["price"] for x in s["levels"]], [2700.0])
        n = self.rows()
        self.assertEqual(self.ing(t1 + timedelta(seconds=5), seq=1, gen=1, cap=1_800_000_600, objects=new_obj), 0)   # the same file again
        self.assertEqual(self.ing(t1 + timedelta(seconds=6), seq=2, gen=1, cap=1_800_000_002), 0)    # an older capture never becomes younger
        self.assertEqual(self.rows(), n)


class TestArchiveDeduplication(_ArchiveCase):
    """I0729: identical reads every 2 s extend one row (last_seen_at, seen_count); as_of age and status counts as before."""

    def test_identical_reads_make_one_row(self):
        t0 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
        for k in range(10):
            self.assertEqual(self.ing(t0 + timedelta(seconds=2 * k), seq=k + 1, cap=1_800_000_000 + 2 * k), 1)
        self.assertEqual(self.rows(), 1)
        s = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t0 + timedelta(seconds=15))
        self.assertEqual([x["price"] for x in s["levels"]], [2650.0])
        self.assertLessEqual(s["age_s"], 2.0)
        self.assertNotIn("last_seen_at", s)                                   # no confirmation after t in the point-in-time read
        self.assertAlmostEqual(self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t0 + timedelta(seconds=60))["age_s"], 42.0)
        self.assertEqual(self.svc.status("XAUUSD", t0 + timedelta(seconds=20))["adapters"]["IQ_GOLD_GANN"]["archived_approved"], 10)
        new_obj = [{"name": "IQG_major_1", "type": "HLINE", "prices": [2660.0], "times": []}]
        self.ing(t0 + timedelta(seconds=20), seq=11, gen=2, cap=1_800_000_020, objects=new_obj)
        self.assertEqual(self.rows(), 2)                                      # changed content -> a new row
        self.ing(t0 + timedelta(seconds=120), seq=12, gen=2, cap=1_800_000_120, objects=new_obj)
        self.assertEqual(self.rows(), 3)                                      # a gap > HEARTBEAT_TTL_S -> a new row (stale period visible)

    def test_reread_after_bot_restart_does_not_refresh(self):
        t0 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
        for k in range(3):
            self.ing(t0 + timedelta(seconds=2 * k), seq=k + 1, cap=1_800_000_000 + 2 * k)
        svc2 = self.s.ExtIndService(self.cfg, self.db)                         # bot restarted, the inbox file (seq 3) is read again
        self.assertEqual(svc2.ingest_bytes(self.c.wrap(_env_body(seq=3, cap=1_800_000_004)), now=t0 + timedelta(minutes=30)), 0)
        self.assertNotIn("IQ_GOLD_GANN", svc2.heartbeat)
        self.assertEqual(svc2.ingest_bytes(self.c.wrap(_env_body(seq=4, cap=1_800_000_006)), now=t0 + timedelta(minutes=30)), 1)
        self.assertEqual(self.rows(), 2)                                      # the next read after 30 min: a new row (gap)


class TestKnowledgeRules(unittest.TestCase):
    """I0182: applied_rules / explain_pl (IND-K01..K12) - regression cover (no defect in the functions)."""

    def test_applied_rules(self):
        from masterquo.extind import knowledge as K
        base = {"sar": {"M5": {"interpretation": "PRESSURE_UP"}}, "sources": {"PAL02M": {"identity_status": "IDENTIFIED", "source_status": "RECEIVING"}}}
        self.assertEqual(K.applied_rules(base), ["IND-K07", "IND-K09", "IND-K10", "IND-K11", "IND-K12"])
        r = K.applied_rules({"sar": {"M5": {"interpretation": "NO_DIRECTIONAL_EVIDENCE"}, "M15": {"interpretation": "NO_DIRECTIONAL_EVIDENCE"}},
                             "sources": {"IQ_GOLD_GANN": {"source_status": "STALE", "levels": [{"price": 1.0}]},
                                         "IQ_STAR_LINES": {"source_status": "RECEIVING", "windows": [{"x": 1}]},
                                         "PAL02M": {"identity_status": "BLOCKED_IDENTITY_REQUIRED", "source_status": "BLOCKED_IDENTITY_REQUIRED"}}})
        self.assertEqual(r, sorted(set(r)))
        for k in ("IND-K01", "IND-K02", "IND-K03", "IND-K04", "IND-K05", "IND-K06", "IND-K08"):
            self.assertIn(k, r)

    def test_explain_pl(self):
        from masterquo.extind import knowledge as K
        warm = K.explain_pl({"sar": {"M5": {"status": "WARMING_UP"}}, "sources": {}, "model": {"status": "READY_INFERENCE", "p_tp1_first": 0.62}})
        self.assertIn("rozgrzewka", warm)
        self.assertIn("P(TP1 przed SL)=0.62 (SHADOW)", warm)
        miss = K.explain_pl({"sar": {}, "sources": {"IQ_GOLD_GANN": {"identity_status": "IDENTIFIED", "source_status": "SOURCE_MISSING"}}})
        self.assertIn("brak wartości (nie zero)", miss)
        self.assertIn("IQ_GOLD_GANN: SOURCE_MISSING", miss)
        ok = K.explain_pl({"sar": {}, "sources": {"IQ_GOLD_GANN": {"source_status": "RECEIVING", "levels": [1, 2], "available_at": "T"}}})
        self.assertIn("2 poziomów z zatwierdzonego mappingu (odczyt T)", ok)
        self.assertIn("NO_MODEL", K.explain_pl({}))


# ------------------------------------------------------------------------------------------------------------ holdout ledger
class TestReserveHoldoutAtomic(unittest.TestCase):
    """I0038: two parallel reservations of the same period - exactly one FRESH (SELECT + INSERT in one transaction)."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_parallel_reservations(self):
        import threading

        from masterquo.db.database import Database
        from masterquo.ml import scalp_task as stk
        db = Database()
        orig = db.query
        gate = threading.Barrier(2)

        def query(sql, args=()):
            out = orig(sql, args)
            if "eval_ledger" in sql:                                           # both trainings have read the ledger before either writes
                try:
                    gate.wait(timeout=3)
                except threading.BrokenBarrierError:
                    pass
            return out
        db.query = query
        got: list = []
        th = [threading.Thread(target=lambda h=h: got.append(stk.reserve_holdout(db, "XAUUSD", "2026-05-01T00:00:00+00:00",
                                                                                   "2026-06-01T00:00:00+00:00", h)["status"])) for h in ("a", "b")]
        for t in th:
            t.start()
        for t in th:
            t.join(30)
        self.assertEqual(sorted(got), ["FRESH", "REUSED_PERIOD_EXPLORATORY"])
        self.assertEqual(orig("SELECT COUNT(*) AS n FROM eval_ledger")[0]["n"], 2)


if __name__ == "__main__":
    unittest.main()
