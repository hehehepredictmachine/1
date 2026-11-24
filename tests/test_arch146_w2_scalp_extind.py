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


class TestSchemaTexts(unittest.TestCase):
    """I0164 (review): after the bump to V2 the API status and the extind smoke still named V1 and a train/live ATR skew this fix removed."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_api_status_names_the_current_schema(self):
        from masterquo.extind import features as F
        from test_audit_146_b_mq_api import call, make_app, make_rt
        rt = make_rt()
        rt.extind.status.return_value = {}
        st_, body, _ = call(make_app(rt), rt, "GET", "/api/v1/indicator-context")
        self.assertEqual(st_, 200, body[:200])
        self.assertEqual(json.loads(body)["model"]["schema"], F.FEATURE_SCHEMA)

    def test_smoke_text_has_no_stale_schema_or_skew(self):
        txt = (ROOT / "backend" / "masterquo" / "modelhub" / "smoke" / "extind.py").read_text(encoding="utf-8")
        self.assertFalse("ZNANY PROBLEM" in txt, "smoke extind: stale 'ZNANY PROBLEM' (ATR skew removed by V2)")
        self.assertFalse("model (SCALP_INDICATOR_CONTEXT_V1)" in txt, "smoke extind: docstring names V1")


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


class TestAgentContextConfirmedAt(_ArchiveCase):
    """I0729 (review): after the deduplication available_at is the FIRST read of identical content (maybe hours ago) - the agent context
    and the adapters view also get confirmed_at (the last identical read), the explanation says 'znane od ..., potwierdzone ...'."""

    def test_context_and_adapter_view_carry_confirmed_at(self):
        from types import SimpleNamespace

        from masterquo.engine.service import EngineService
        from masterquo.scalp import adapters
        from masterquo.timeutil import iso, utcnow
        t0 = utcnow().replace(microsecond=0) - timedelta(seconds=40)
        for k in range(10):
            self.ing(t0 + timedelta(seconds=2 * k), seq=k + 1, cap=1_800_000_000 + 2 * k)
        self.assertEqual(self.rows(), 1)
        t = t0 + timedelta(seconds=19)

        class Bridge:
            def bars(self, *a, **kw):
                return []
        ctx = EngineService._indicator_context(SimpleNamespace(bridge=Bridge(), extind=self.svc, cfg_store=self.cfg), {"as_of": iso(t)})
        src = ctx["sources"]["IQ_GOLD_GANN"]
        snap = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t)
        self.assertEqual(src["available_at"], snap["available_at"])
        self.assertEqual(src["confirmed_at"], snap["confirmed_at"])
        self.assertLess(datetime.fromisoformat(src["available_at"]), datetime.fromisoformat(src["confirmed_at"]))
        self.assertEqual(src["source_status"], "RECEIVING")
        self.assertIn(f"znane od {src['available_at']}, potwierdzone {src['confirmed_at']}", ctx["explanation_pl"])
        row = adapters.extind_snapshot("IQ_GOLD_GANN", "XAUUSD-", self.svc, "XAUUSD", t)
        self.assertEqual((row["known_at"], row["confirmed_at"]), (snap["available_at"], snap["confirmed_at"]))

    def test_explain_pl_first_and_last_read(self):
        from masterquo.extind import knowledge as K
        both = K.explain_pl({"sar": {}, "sources": {"IQ_GOLD_GANN": {"source_status": "RECEIVING", "levels": [1], "available_at": "T0",
                                                                       "confirmed_at": "T9"}}})
        self.assertIn("1 poziomów z zatwierdzonego mappingu (znane od T0, potwierdzone T9)", both)
        same = K.explain_pl({"sar": {}, "sources": {"IQ_GOLD_GANN": {"source_status": "RECEIVING", "levels": [1], "available_at": "T0",
                                                                       "confirmed_at": "T0"}}})
        self.assertIn("(odczyt T0)", same)


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


# ------------------------------------------------------------------------------------------------------------ 17_TRENING_SCALP_ML.bat
class TestScalpBatCommission(unittest.TestCase):
    """I0110: without an argument scalp_train keeps its own source order (trade history of the export, then 0.50)."""

    def test_commission_only_when_given(self):
        raw = (ROOT / "17_TRENING_SCALP_ML.bat").read_bytes()
        raw.decode("ascii")                                                    # ASCII
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))                     # CRLF only
        txt = raw.decode("ascii")
        self.assertNotIn('set "COMM=0.50"', txt)                               # no forced default
        call = next(ln for ln in txt.splitlines() if "gold_candles_runtime.scalp_train" in ln)
        self.assertNotIn("--commission-per-lot-side", call)                    # the argument only through a conditional variable
        self.assertIn('if not "%~1"=="" set "COMMARG=--commission-per-lot-side %~1"', txt)
        self.assertIn("%COMMARG%", call)
        msg = next(ln for ln in txt.splitlines() if ln.startswith('set "COMMTXT=z historii'))
        self.assertIn("XAUUSD 0.50", msg)                                       # review: 0.50 is the package default of XAUUSD only
        self.assertIn("inne instrumenty - podaj argument", msg)                 # another instrument: COMMISSION_UNKNOWN (scalp_train)


# ------------------------------------------------------------------------------------------------------------ scalp SHADOW
def _scenario(context=False):
    import scenario as S
    from masterquo.scalp import strategy as st
    p = st.load_profile()
    p["context_filter"]["enabled"]["value"] = context
    bars, info = S.build(p)
    return S, st, p, bars, info


class _ScalpService:
    """The fake bridge / config of tests/test_scalp_core.TestConfigAndService (scenario bars, no orders)."""

    def __init__(self, live, m5, *, account=None, info=None, extra_m5=None, quote=None, slippage_ticks=None):
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        from masterquo.scalp import service as mod
        self.mod = mod
        self.live, self.m5 = live, m5
        acc = dict(account or {"equity": 10000.0, "margin_mode": "HEDGING"})
        sym = dict(info or {"trade_tick_size": 0.01, "point": 0.01, "trade_contract_size": 100.0, "volume_min": 0.01, "volume_step": 0.01,
                            "volume_max": 50, "currency_base": "XAU", "currency_profit": "USD"})
        outer = self

        class Bridge:
            session_epoch = 1
            symbol_info = sym

            def bars(self, tf, limit, include_forming=False):
                if tf == "M1":
                    return [dict(b, spread=10) for b in outer.live][-limit:]
                return [dict(b, spread=10) for b in outer.m5][-limit:] if tf == "M5" else []

            def quote_status(self):
                if quote is not None:
                    return dict(quote, age_seconds=0.5)
                return {"bid": outer.live[-1]["c"], "ask": outer.live[-1]["c"] + 0.1, "age_seconds": 0.5}

            def account_status(self):
                return dict(acc)

        class Bus:
            def publish(self, *a):
                pass

        class Log:
            def info(self, *a):
                pass

            def error(self, *a):
                pass

        class Cfg:
            def get(self):
                c = AppConfig()
                c.scalp.commission_per_lot_side = 3.5
                if slippage_ticks is not None:
                    c.scalp.slippage_ticks = slippage_ticks
                return c
        self.svc = mod.ScalpService(Cfg(), Bridge(), Database(), Bus(), Log(), news=None)

    def tick(self, now: datetime):
        orig = self.mod.time.time
        self.mod.time.time = lambda: now.timestamp()
        try:
            self.svc.tick()
        finally:
            self.mod.time.time = orig
        return self.svc.recent()


def _gate(row, name):
    return next((g for g in row["gates"] if g["name"] == name), None)


class TestScalpTfRace(unittest.TestCase):
    """I0737: a higher TF bar of the decision's close missing in the poll -> the candidate is NOT_VERIFIED (blocked, never a new one);
    a late higher TF bar is fed at the next poll (key over every TF); a range armed by a late M5 gives no candidates."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _live(self):
        S, st, _p, bars, info = _scenario()
        ret = next(k for k, b in enumerate(bars) if b["open_utc"] == info["retest_time"])
        live = bars[:ret + 1]
        return S, st, live, datetime.fromtimestamp(st.ts(live[-1]["open_utc"]) + 61, UTC)

    def test_candidate_with_lagging_m5_is_blocked(self):
        S, _st, live, now = self._live()
        m5 = S.m5_of(live)
        lagging = _ScalpService(live, m5[:-1])                                 # the M5 closing 3 min before the decision is not polled yet
        rows = lagging.tick(now)
        self.assertEqual(len(rows), 1)
        g = _gate(rows[0], "komplet TF w chwili decyzji")
        self.assertIsNotNone(g)
        self.assertFalse(g["ok"])
        self.assertIn("M5", g["detail"])
        self.assertEqual(rows[0]["status"], "BLOCKED")

    def test_complete_poll_passes_the_tf_gate(self):
        S, _st, live, now = self._live()
        complete = _ScalpService(live, S.m5_of(live))
        self.assertTrue(_gate(complete.tick(now)[0], "komplet TF w chwili decyzji")["ok"])

    def test_late_m5_is_fed_without_a_new_m1(self):
        S, st, live, now = self._live()
        m5 = S.m5_of(live)
        h = _ScalpService(live, m5[:-1])
        h.tick(now)
        fed = h.svc.fed["M5"]
        h.m5 = m5                                                              # the late M5 arrives, the M1 is the same
        h.tick(now + timedelta(seconds=2))
        self.assertEqual(h.svc.fed["M5"], st.ts(m5[-1]["open_utc"]))
        self.assertGreater(h.svc.fed["M5"], fed)

    def test_range_armed_by_late_m5_gives_no_candidates(self):
        S, st, _p, bars, _info = _scenario()
        m5_all = S.m5_of(bars)
        arm = None
        for b in m5_all:                                                       # first M5 close where the service machine arms a range
            close = st.ts(b["open_utc"]) + 300
            live = [x for x in bars if st.ts(x["open_utc"]) + 60 <= close]
            h = _ScalpService(live, [x for x in m5_all if st.ts(x["open_utc"]) + 300 <= close])
            h.tick(datetime.fromtimestamp(close + 61, UTC))
            if h.svc.machine.range is not None and h.svc.machine.range["armed_at"] == close:
                arm = close
                break
        self.assertIsNotNone(arm)
        live = [x for x in bars if st.ts(x["open_utc"]) + 60 <= arm]
        m5 = [x for x in m5_all if st.ts(x["open_utc"]) + 300 <= arm]
        h = _ScalpService(live, m5[:-1])                                       # poll 1: the M1 closing at `arm`, the arming M5 not yet there
        h.tick(datetime.fromtimestamp(arm + 1, UTC))
        h.m5 = m5                                                              # poll 2: the M5 arrives late
        h.tick(datetime.fromtimestamp(arm + 3, UTC))
        self.assertIsNotNone(h.svc.machine.range)
        self.assertEqual(h.svc.machine.range["armed_at"], arm)
        for d in h.svc.machine.dirs.values():
            self.assertEqual(d["state"], "BLOCKED")
            self.assertIn("NOT_VERIFIED", d["reason"])


class TestScalpSizeAccountCurrency(unittest.TestCase):
    """I0738: the budget is in the account currency - lots with the larger per-lot risk of contract size / tick value (never more),
    risk_cash in the account currency; commission in price with the larger conversion; another currency without tick value blocks."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_size_with_money_per_price(self):
        from masterquo.scalp import strategy as st
        p = st.load_profile()
        usd = st.size(2.0, 100.0, 10000.0, p, 0.01, 0.01, 100)
        eur = st.size(2.0, 100.0, 10000.0, p, 0.01, 0.01, 100, money_per_price=92.0)        # tick value 0.92 EUR / 0.01
        self.assertEqual(eur["lots"], usd["lots"])                             # never more lots than before
        self.assertEqual(eur["risk_cash"], round(eur["lots"] * 2.0 * 92.0, 2))  # account-currency risk
        pln = st.size(2.0, 100.0, 10000.0, p, 0.01, 0.01, 100, money_per_price=400.0)       # 4 PLN per USD: 400 PLN per 1.0 per lot
        self.assertLess(pln["lots"], usd["lots"])
        self.assertEqual(pln["lots"], 0.03)                                    # 25 PLN budget / 800 PLN per lot -> 0.031 -> 0.03
        same = st.size(2.0, 100.0, 10000.0, p, 0.01, 0.01, 100, money_per_price=100.0)
        self.assertEqual((same["lots"], same["risk_cash"]), (usd["lots"], usd["risk_cash"]))

    def test_commission_price_and_tick_value_gate(self):
        from masterquo.scalp import service as mod
        self.assertAlmostEqual(mod.commission_price(7.0, 100.0, 92.0), 7.0 / 92.0)
        self.assertAlmostEqual(mod.commission_price(28.0, 100.0, 400.0), 0.28)   # never below com / contract size
        self.assertAlmostEqual(mod.commission_price(3.5, 100.0, None), 0.035)
        self.assertEqual(mod.money_per_price({"trade_tick_value": 0.92, "trade_tick_size": 0.01}), 92.0)
        self.assertIsNone(mod.money_per_price({"trade_tick_size": 0.01}))
        S, st, _p, bars, info = _scenario()
        ret = next(k for k, b in enumerate(bars) if b["open_utc"] == info["retest_time"])
        live = bars[:ret + 1]
        now = datetime.fromtimestamp(st.ts(live[-1]["open_utc"]) + 61, UTC)
        h = _ScalpService(live, S.m5_of(live), account={"equity": 10000.0, "margin_mode": "HEDGING", "currency": "EUR"})
        g = _gate(h.tick(now)[0], "wartość ticka (waluta konta)")
        self.assertIsNotNone(g)
        self.assertFalse(g["ok"])                                              # EUR account, USD quote, no tick value -> NOT_VERIFIED
        self.assertIn("NOT_VERIFIED", g["detail"])


def _economics_before(plan, fill, spread, extra, prof) -> bool:
    """scalp/strategy.economics()['ok'] at c8277f4 (before 1.46 arch) - the reference of 'never looser than before'."""
    from masterquo.scalp.strategy import V
    sgn = 1 if plan["direction"] == "BUY" else -1
    gross1, g2 = sgn * (plan["tp1"] - fill), sgn * (plan["tp2"] - fill)
    risk = sgn * (fill - plan["sl"]) + extra
    f1 = V(prof, "exits", "tp1_fraction")
    net_w = f1 * (gross1 - extra) + (1 - f1) * (g2 - extra)
    cost_tp1 = (spread + extra) / (gross1 + spread) if gross1 + spread > 0 else None
    rr = net_w / risk if risk > 0 else None
    return bool(gross1 > 0 and g2 > 0 and risk > 0 and cost_tp1 is not None and cost_tp1 <= V(prof, "economics", "max_cost_to_tp1_gross")
                and rr is not None and rr >= V(prof, "economics", "min_weighted_net_rr"))


_EUR_SYMBOL = {"trade_tick_size": 0.01, "trade_tick_value": 0.92, "point": 0.01, "trade_contract_size": 100.0, "volume_min": 0.01,
               "volume_step": 0.01, "volume_max": 50, "currency_base": "XAU", "currency_profit": "USD"}      # EUR account: 0.92 EUR / tick


class TestScalpEconomicsNeverLooser(unittest.TestCase):
    """I0738 (review): commission_price = max(com / contract, com / money_per_price) is a larger cost, but economics' risk = side + cost
    crosses 0 for an execution price at / beyond the SL - a larger cost turned a BLOCKED entry beyond the stop into READY_SHADOW (EUR
    account, fill = SL - 9 ticks). The SL must be on the right side of the execution price, and the live gate ANDs the economics at the
    cost before 1.46 arch: never a READY_SHADOW (user signal, markets/signals.py on_scalp_setup) that the code before gave not."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_economics_entry_at_or_beyond_stop(self):
        from masterquo.scalp import strategy as st
        p = st.load_profile()
        buy = {"direction": "BUY", "sl": 1996.22, "tp1": 2000.0, "tp2": 2002.98}
        old_extra, new_extra = 2 * 3.5 / 100 + 2 * 0.01, 2 * 3.5 / 92 + 2 * 0.01       # 0.0900 / 0.0961 (EUR account, slippage 1 tick)
        e = st.economics(buy, round(buy["sl"] - 0.09, 2), 0.1, new_extra, p)              # the review case: risk 0.00609 > 0 -> was OK
        self.assertFalse(e["ok"])
        self.assertIn("SL", e["reason"])
        for ticks in (3, 1, 0):                                                           # the gap of the code before 1.46 arch closes too
            for extra in (old_extra, new_extra):
                self.assertFalse(st.economics(buy, round(buy["sl"] - ticks * 0.01, 2), 0.1, extra, p)["ok"], (ticks, extra))
        sell = {"direction": "SELL", "sl": 2003.78, "tp1": 2000.0, "tp2": 1997.02}
        self.assertFalse(st.economics(sell, round(sell["sl"] + 0.09, 2), 0.1, new_extra, p)["ok"])
        self.assertTrue(st.economics(buy, 1997.9, 0.1, new_extra, p)["ok"])               # a normal entry is unchanged

    def test_live_entry_beyond_stop_is_blocked(self):
        S, st, p, bars, info = _scenario()
        ret = next(k for k, b in enumerate(bars) if b["open_utc"] == info["retest_time"])
        live = bars[:ret + 1]
        now = datetime.fromtimestamp(st.ts(live[-1]["open_utc"]) + 61, UTC)
        sl = S.run(p, bars)[1][0]["sl"]
        ask = round(sl - 0.09, 2)                                                          # BUY fill = SL - 9 ticks
        h = _ScalpService(live, S.m5_of(live), account={"equity": 10000.0, "margin_mode": "HEDGING", "currency": "EUR"}, info=_EUR_SYMBOL,
                          quote={"bid": round(ask - 0.1, 2), "ask": ask}, slippage_ticks=1)
        row = h.tick(now)[0]
        self.assertEqual(row["plan"]["sl"], sl)
        self.assertEqual(row["plan"]["fill_shadow"], ask)
        g = _gate(row, "koszt i RR (filtr geometrii)")
        self.assertFalse(g["ok"], g)
        self.assertEqual(row["status"], "BLOCKED")

    def test_gate_never_looser_than_before(self):
        from masterquo.scalp import service as mod
        from masterquo.scalp import strategy as st
        p = st.load_profile()
        plans = ({"direction": "BUY", "sl": 1996.22, "tp1": 2000.0, "tp2": 2002.98}, {"direction": "SELL", "sl": 2003.78, "tp1": 2000.0, "tp2": 1997.02})
        n_ok = n_beyond = 0
        for plan in plans:
            sgn = 1 if plan["direction"] == "BUY" else -1
            for k in range(-30, 400, 3):                                                   # fill from 30 ticks beyond the SL to past TP1
                fill = round(plan["sl"] + sgn * k * 0.01, 2)
                for sp in (0.05, 0.3):
                    for com in (0.0, 3.5, 7.0):
                        for slip in (0, 1, 2):
                            old = 2 * com / 100.0 + 2 * slip * 0.01
                            before = _economics_before(plan, fill, sp, old, p)
                            old_size = st.size(sgn * (fill - plan["sl"]) + old, 100.0, 10000.0, p, 0.01, 0.01, 50)
                            for mpp in (None, 50.0, 92.0, 100.0, 400.0):
                                eco, extra, ok, _detail = mod.economics_gate(plan, fill, sp, com, 100.0, mpp, slip, 0.01, p)
                                self.assertGreaterEqual(extra, old)
                                if not ok:
                                    continue
                                n_ok += 1
                                self.assertTrue(before, (plan["direction"], k, sp, com, slip, mpp))   # never a new pass
                                new_size = st.size(eco["risk_per_unit"], 100.0, 10000.0, p, 0.01, 0.01, 50, money_per_price=mpp)
                                self.assertLessEqual(new_size["lots"], old_size["lots"])            # never more lots
                            if k <= 0:
                                n_beyond += 1
        self.assertGreater(n_ok, 100)
        self.assertGreater(n_beyond, 0)


class TestCandidateSpreadUnknown(unittest.TestCase):
    """I0809: no spread on the retest bar -> no candidate (the SL / TP2 buffers were built with spread 0)."""

    def test_no_candidate_without_spread(self):
        S, _st, p, bars, info = _scenario()
        self.assertEqual(len(S.run(p, bars)[1]), 1)                            # with the spread: one candidate
        no_sp = [dict(b, spread_price=None) if b["open_utc"] == info["retest_time"] else b for b in bars]
        m, plans = S.run(p, no_sp)
        self.assertEqual(plans, [])
        self.assertTrue(any(j["state"] == "BLOCKED" and "SPREAD_UNKNOWN" in j["reason"] and j.get("direction") == "BUY" for j in m.journal))


class TestScalpLossReferenceAtDayStart(unittest.TestCase):
    """I0810 (+ I0859): the daily reference is the first equity of the UTC day (observed by tick), never looser than the first
    candidate's; unreadable file / start during the day -> blocked instead of a fresh baseline that passes."""

    def setUp(self):
        self.td = TempData()
        from masterquo.scalp import strategy as st
        from masterquo.scalp.service import ScalpService
        self.svc = ScalpService.__new__(ScalpService)
        self.svc.prof = st.load_profile()
        self.d0 = datetime(2026, 3, 3, tzinfo=UTC)

    def tearDown(self):
        self.td.close()

    def test_reference_from_day_start(self):
        self.svc._risk_reference({"equity": 1000.0}, now=self.d0 + timedelta(minutes=1))      # tick at 00:01
        ok, why = self.svc._loss_limits({"equity": 960.0}, now=self.d0 + timedelta(hours=15))  # first candidate at 15:00
        self.assertFalse(ok)
        self.assertIn("dzień 4.00%", why)

    def test_never_looser_than_first_candidate(self):
        self.svc._risk_reference({"equity": 1000.0}, now=self.d0 + timedelta(minutes=1))
        self.assertTrue(self.svc._loss_limits({"equity": 1100.0}, now=self.d0 + timedelta(hours=10))[0])
        ok, why = self.svc._loss_limits({"equity": 1080.0}, now=self.d0 + timedelta(hours=15))   # -1.82% from the first candidate
        self.assertFalse(ok)
        self.assertIn("dzień 1.82%", why)

    def test_unreadable_file_blocks(self):
        p = self.svc._root() / "risk_reference.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{broken", encoding="utf-8")
        ok, why = self.svc._loss_limits({"equity": 1000.0}, now=self.d0 + timedelta(minutes=2))
        self.assertFalse(ok)
        self.assertIn("UNAVAILABLE", why)

    def test_start_during_the_day_is_not_verified(self):
        ok, why = self.svc._loss_limits({"equity": 1000.0}, now=self.d0 + timedelta(hours=9))
        self.assertFalse(ok)
        self.assertIn("NOT_VERIFIED", why)
        self.assertIn("do 00:00 UTC żaden kandydat nie dostanie READY_SHADOW", why)    # review: the whole-day effect is stated in the gate
        self.assertIn("do 00:10", why)
        ok2, _ = self.svc._loss_limits({"equity": 1000.0}, now=self.d0 + timedelta(days=1, minutes=1))   # next day from 00:01: verified
        self.assertTrue(ok2)


def _flat_m5_m1(t0: datetime):
    """30 M5 bars with identical closes (100.0) whose highs / lows touch 101 / 99 every 3 bars, and M1 bars with narrow edge sections."""
    m5, m1 = [], []
    for k in range(30):
        o = t0 + timedelta(minutes=5 * k)
        h, lo = {0: (101.0, 99.9), 1: (100.1, 99.0), 2: (100.1, 99.9)}[k % 3]
        m5.append({"open_utc": _iso(o), "o": 100.0, "h": h, "l": lo, "c": 100.0, "tv": 100, "spread_price": 0.1})
        for j in range(5):
            if j == 2 and k % 3 == 0:
                b = (100.95, 101.0, 100.9, 100.95)
            elif j == 2 and k % 3 == 1:
                b = (99.05, 99.1, 99.0, 99.05)
            else:
                b = (100.0, 100.05, 99.95, 100.0)
            m1.append({"open_utc": _iso(o + timedelta(minutes=j)), "o": b[0], "h": b[1], "l": b[2], "c": b[3], "tv": 100, "spread_price": 0.1})
    return m5, m1


class TestDetectRangeFlat(unittest.TestCase):
    """I0860: 10 identical M5 closes (ER denominator 0) passed the ER filter as 0.0 - the flat range gives no candidates (it stays armed
    for its TTL as before, so no other range is detected earlier)."""

    def test_flat_range_has_no_candidates(self):
        from masterquo.scalp import strategy as st
        p = st.load_profile()
        m5, m1 = _flat_m5_m1(datetime(2026, 3, 3, 8, 0, tzinfo=UTC))
        m = st.ScalpMachine(p, 0.01)
        for k, b in enumerate(m5):
            for x in m1[5 * k:5 * k + 5]:
                m.on_m1_close(x)
            m.on_m5_close(b)
            if m.range:
                break
        self.assertIsNotNone(m.range)                                          # armed as before (TTL unchanged)
        self.assertTrue(m.range.get("flat"))
        self.assertEqual({d["state"] for d in m.dirs.values()}, {"BLOCKED"})
        self.assertTrue(all("płaski rynek" in d["reason"] for d in m.dirs.values()))


class TestScalpForecastNoPoint(unittest.TestCase):
    """I0025: without symbol_info.point the scalp A forecast is UNAVAILABLE (no guessed 0.01 spread scale), the worker is not asked."""

    def test_forecast_without_point(self):
        from masterquo.scalp.service import ScalpService
        asked = []

        class Fc:
            proc = True

            def _ask(self, msg, timeout):
                asked.append(msg)
                return {"status": "SHADOW"}

        class Bridge:
            symbol_info: dict | None = None

            def bars(self, tf, limit, include_forming=False):
                return [{"open_utc": "2026-03-03T10:00:00Z", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "tv": 1, "spread": 10}]
        svc = ScalpService.__new__(ScalpService)
        svc.forecast, svc.bridge = Fc(), Bridge()
        svc.registry = lambda: {"active": "R1", "runs": {}}
        out = svc.forecasts()
        self.assertEqual(out["status"], "UNAVAILABLE")
        self.assertIn("point", out["reason"])
        self.assertEqual(asked, [])
        Bridge.symbol_info = {"point": 0.01}
        self.assertEqual(svc.forecasts()["status"], "SHADOW")
        self.assertEqual(len(asked), 1)


if __name__ == "__main__":
    unittest.main()
