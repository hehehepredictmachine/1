"""1.37 Chronos-2 / Granite TTM (1.40, FinCast retired) + Kronos-base migration - bot side, no torch (stub worker = test double, its numbers are not forecasts):
installer + manifest (size / SHA-256, wrong file rejected, no manifest = never READY, pinned revision, tamper detected, resume),
service (not installed -> no terminal reads, one shared snapshot for both models, queue dedup, ledger + settlement from real closed bars,
pinball / coverage, a result for an older bar never current, timeout / crash / load failure -> no value + reason, MT5 disconnect),
contract rows (REGRESSION / price / UNCALIBRATED, null result when unavailable), coordinator roles for REGRESSION forecasts (ASSIST only on
fresh contrary, REQUIRED unavailable / stale / FLAT / contrary blocked, no_required = OBSERVE, no duplicate Kronos gate), SH receiver,
approvals (no report -> refused, binding change -> stale), Kronos migration (largest public variant pinned, Small history labelled Small,
old approval stale)."""
from __future__ import annotations

import json
import os
import stat
import sys
import time
import unittest
from pathlib import Path

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_testkit as K  # noqa: E402

HERE = Path(__file__).resolve().parent
POSIX = os.name != "nt"
from datetime import datetime, timezone  # noqa: E402

WED_1200 = datetime(2026, 10, 28, 12, 0, 30, tzinfo=timezone.utc).timestamp()


def stub_python(tmp: Path, mode: str = "ok") -> str:
    p = Path(tmp) / f"tsfm_stub_python_{mode}"
    p.write_text(f'#!/bin/sh\nSTUB_MODE={mode} exec {sys.executable} {HERE / "tsfm_stub_worker.py"} "$@"\n', encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def fixture_weights(root: Path, mid: str) -> None:
    from tsfm_runtime import lock as L
    from tsfm_runtime import manifest as M
    pin = L.model(mid)
    d = M.model_dir(root, mid)
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for name in pin["required_files"]:
        (d / name).write_bytes(b"\0" * 32)
        files.append({"name": name, "size": 32, "sha256": M.sha256_file(d / name), "source_check": "fixture"})
    M.write(root, mid, {"schema": L.MANIFEST_SCHEMA, "model_id": mid, "repo": pin["repo"], "revision": pin["revision"], "fixture": True,
                        "installed_at": "2026-01-01T00:00:00Z", "files": files})


class TestCoordinatorRegressionRoles(unittest.TestCase):
    def ev(self, preds, side="BUY", required=(), now=1000.0):
        from masterquo.decision.coordinator import evaluate_models
        return evaluate_models(preds, side, required=set(required), assist_threshold=0.6, max_age_s=900, now=now)

    def p(self, d, use="SHADOW", age=10.0, state="READY", **kw):
        return {"family": "tsfm:chronos2", "state": state, "use": use, "task_type": "REGRESSION",
                "result": {"direction": d, "pred_close": 1.0} if state == "READY" else None, "data_time": 1000.0 - age, **kw}

    def test_observe_never_influences(self):
        m, r = self.ev([self.p("DOWN")])
        self.assertEqual((m[0]["role"], m[0]["influence"], r), ("OBSERVE", "NONE", []))

    def test_assist_holds_only_fresh_contrary(self):
        m, r = self.ev([self.p("DOWN", use="ASSIST")])
        self.assertEqual((m[0]["influence"], r), ("HOLD", ["MODEL_ASSIST_HOLD:tsfm:chronos2"]))
        m, r = self.ev([self.p("UP", use="ASSIST"), self.p("FLAT", use="ASSIST", family="tsfm:fincast")])
        self.assertEqual(r, [])
        m, r = self.ev([self.p("DOWN", use="ASSIST", age=5000)])               # stale optional forecast: no effect, never a block
        self.assertEqual((m[0]["influence"], r), ("NONE", []))
        self.assertIn("nieaktualna", m[0]["reason"])
        m, r = self.ev([self.p("DOWN", use="ASSIST", state="ERROR", unavailable_reason="x")])
        self.assertEqual(r, [])

    def test_required_regression_rules(self):
        cases = {("UP", "READY", 10): [], ("DOWN", "READY", 10): ["MODEL_REQUIRED_CONTRARY:tsfm:chronos2"],
                 ("FLAT", "READY", 10): ["MODEL_REQUIRED_NOT_CONFIRMING:tsfm:chronos2"],
                 ("UP", "READY", 5000): ["MODEL_REQUIRED_STALE:tsfm:chronos2"], ("UP", "ERROR", 10): ["MODEL_REQUIRED_UNAVAILABLE:tsfm:chronos2"]}
        for (d, st, age), want in cases.items():
            pr = self.p(d, use="REQUIRED", age=age, state=st, unavailable_reason=None if st == "READY" else "x")
            m, r = self.ev([pr])
            self.assertEqual(r, want, (d, st, age))
        m, r = self.ev([self.p("DOWN", use="REQUIRED", max_age_s=20.0, age=30.0)])     # per-row freshness limit
        self.assertEqual(r, ["MODEL_REQUIRED_STALE:tsfm:chronos2"])

    def test_no_required_is_observe_even_if_listed(self):
        row = {"family": "kronos:Kronos-base@M5", "state": "READY", "use": "SHADOW", "no_required": True, "task_type": "REGRESSION",
               "result": {"direction": "DOWN"}, "data_time": 990.0}
        m, r = self.ev([row], required=["kronos:Kronos-base@M5"])
        self.assertEqual((m[0]["role"], r), ("OBSERVE", []))                   # Kronos keeps its own SH condition - never a second gate


class TestInstallerManifest(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(self.td.dir) / "w"
        self.src = Path(self.td.dir) / "src"
        self.src.mkdir()
        from tsfm_runtime import lock as L
        from tsfm_runtime import manifest as M
        self.L, self.M = L, M
        self._orig = json.loads(json.dumps(L.MODELS["chronos2"]))
        (self.src / "config.json").write_bytes(b'{"a": 1}')
        (self.src / "model.safetensors").write_bytes(b"\1" * 1000)
        L.MODELS["chronos2"]["files"] = [{"name": "config.json", "size": 8, "git_blob_sha1": M.git_blob_sha1(self.src / "config.json")},
                                         {"name": "model.safetensors", "size": 1000, "sha256": M.sha256_file(self.src / "model.safetensors")}]

    def tearDown(self):
        self.L.MODELS["chronos2"] = self._orig
        self.td.close()

    def test_download_from_dir_verify_and_tamper(self):
        from tsfm_runtime import install as I
        r = I.download("chronos2", str(self.root), from_dir=str(self.src))
        self.assertTrue(r["ok"], r)
        s = self.M.summary(self.root, "chronos2")
        self.assertTrue(s["installed"], s)
        self.assertEqual(s["revision"], self.L.MODELS["chronos2"]["revision"])
        self.assertTrue(self.M.verify(self.root, "chronos2")["ok"])
        f = self.M.model_dir(self.root, "chronos2") / "model.safetensors"
        f.write_bytes(b"\2" * 1000)                                             # same size, other content
        with self.assertRaises(self.M.ManifestError) as cm:
            self.M.verify(self.root, "chronos2")
        self.assertEqual(cm.exception.code, "CHECKSUM")
        r = I.download("chronos2", str(self.root), from_dir=str(self.src))     # re-run repairs only the bad file
        self.assertTrue(r["ok"])
        self.assertTrue(self.M.verify(self.root, "chronos2")["ok"])

    def test_wrong_file_rejected_and_no_manifest(self):
        from tsfm_runtime import install as I
        (self.src / "model.safetensors").write_bytes(b"\3" * 1000)
        r = I.download("chronos2", str(self.root), from_dir=str(self.src))
        self.assertEqual((r["ok"], r["code"]), (False, "CHECKSUM"))
        self.assertFalse(self.M.summary(self.root, "chronos2")["installed"])
        self.assertFalse((self.M.model_dir(self.root, "chronos2") / "model.safetensors").exists())
        self.assertFalse((self.M.model_dir(self.root, "chronos2") / "model.safetensors.part").exists())

    def test_other_revision_is_not_installed_and_fixture_needs_env(self):
        from tsfm_runtime import install as I
        I.download("chronos2", str(self.root), from_dir=str(self.src))
        m = self.M.read(self.root, "chronos2")
        m["revision"] = "0" * 40
        self.M.write(self.root, "chronos2", m)
        s = self.M.summary(self.root, "chronos2")
        self.assertFalse(s["installed"])
        self.assertIn("inna rewizja", s["reason"])
        fixture_weights(self.root, "granite_ttm")
        os.environ.pop("MQ_TSFM_ALLOW_FIXTURE", None)
        self.assertFalse(self.M.summary(self.root, "granite_ttm")["installed"])

    def test_disk_space_check(self):
        from tsfm_runtime import install as I
        self.L.MODELS["chronos2"]["files"][1]["size"] = 10 ** 15                # 1 PB never fits
        r = I.download("chronos2", str(self.root), from_dir=str(self.src))
        self.assertEqual((r["ok"], r["code"]), (False, "DISK_SPACE"))

    def test_real_pins_are_complete(self):
        for mid in ("chronos2", "granite_ttm"):
            pin = self._orig if mid == "chronos2" else self.L.MODELS[mid]
            self.assertRegex(pin["revision"], r"^[0-9a-f]{40}$")
            big = [f for f in pin["files"] if f["name"] in pin["required_files"] and f["name"].endswith((".safetensors", ".pth"))]
            self.assertTrue(big and all(len(f["sha256"]) == 64 and f["size"] > 10 ** 6 for f in big))
        g = self.L.MODELS["granite_ttm"]
        self.assertEqual((g["repo"], g["params_measured"], g["license"], g["max_context"]), ("ibm-granite/granite-timeseries-ttm-r2", 805280, "Apache-2.0", 512))
        self.assertEqual(self.L.ACTIVE, ("chronos2", "granite_ttm"))
        self.assertEqual(self.L.RETIRED, ("fincast",))                          # pin kept for the history, never installed
        self.assertTrue(self.L.MODELS["fincast"]["retired"])
        self.assertEqual(self.L.MODELS["fincast"]["params_measured"], 991436960)
        self.assertEqual(self._orig["params_measured"], 119477664)


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.dir = Path(self.td.dir)
        os.environ["MQ_TSFM_ALLOW_FIXTURE"] = "1"
        self.now = [WED_1200]
        self.bars = K.make_bars(300, WED_1200, 10)
        self.bars15 = K.make_bars(900, WED_1200, 20)
        self.bridge = K.FakeBridge({("XAUUSD-", "M5"): self.bars, ("XAUUSD-", "M15"): self.bars15})
        self.cfg = K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")}))

    def tearDown(self):
        os.environ.pop("MQ_TSFM_ALLOW_FIXTURE", None)
        if getattr(self, "svc", None):
            self.svc.stop()
        self.td.close()

    def make(self, mode="ok", weights=True, tfs=("M5",), **models):
        from masterquo.db.database import Database
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        st = SettingsStore(self.dir / "tsfm" / "settings.json")
        root = self.dir / ("w" if weights else "w_empty")
        if weights:
            fixture_weights(root, "chronos2")
            fixture_weights(root, "granite_ttm")
        py = stub_python(self.dir, mode) if mode else str(self.dir / "missing")
        mc = {m: {"python_path": py, "timeframes": list(tfs), "instruments": ["XAUUSD"], "request_timeout_s": 5.0, **models.get(m, {})}
              for m in ("chronos2", "granite_ttm")}
        st.update({"weights_root": str(root), "models": mc})
        self.svc = TsfmService(self.cfg, self.bridge, Database(self.dir / "t.sqlite"), K.Bus(), K.Log(), clock=lambda: self.now[0], settings=st)
        return self.svc

    def run_queue(self):
        out = []
        while self.svc.queue:
            k, job = self.svc.queue.popitem(last=False)
            out.append(self.svc.run_job(job))
        return out

    def test_not_installed_states_and_no_terminal_reads(self):
        from unittest import mock
        svc = self.make(mode=None)
        with mock.patch("masterquo.tsfm.service.find_python", return_value=None):    # no model environment on this machine
            svc.tick()
        self.assertEqual({w.state["status"] for w in svc.workers.values()}, {"NOT_INSTALLED"})
        self.assertEqual(self.bridge.calls, [])
        from masterquo.tsfm import predictions as TP
        rows = TP.contract_predictions(svc, "XAUUSD")
        self.assertTrue(rows and all(r["state"] == "DISABLED" and r["result"] is None for r in rows))
        svc.stop()
        svc = self.make(weights=False)
        svc.tick()
        self.assertEqual({w.state["status"] for w in svc.workers.values()}, {"NO_WEIGHTS"})

    def test_shared_snapshot_contract_ledger_settlement(self):
        from masterquo.tsfm import predictions as TP
        svc = self.make()
        svc.tick()
        self.assertEqual(set(svc.queue), {("chronos2", "XAUUSD", "M5"), ("granite_ttm", "XAUUSD", "M5")})
        snaps = {j["snapshot_id"] for j in svc.queue.values()}
        self.assertEqual(len(snaps), 1)                                         # one data read, one snapshot for both models
        fcs = self.run_queue()
        self.assertTrue(all(fcs))
        c, f = fcs
        self.assertEqual((c["point_kind"], f["point_kind"]), ("median", "point"))
        self.assertEqual((f["quantile_levels"], f["path"][0].get("q0.1"), f["normalization"]["method"]), (None, None, "zscore_context_window"))
        self.assertIn("z-score", f["preprocessing"])
        self.assertEqual(c["target_times"], f["target_times"])                 # the SAME target bars
        self.assertEqual((c["mode"], c["execution_permission"], c["unit"], c["task_type"]), ("SHADOW", False, "price", "REGRESSION"))
        self.assertEqual(c["direction"], "UP")
        rows = {r["model_id"]: r for r in TP.contract_predictions(svc, "XAUUSD")}
        r = rows["tsfm:chronos2"]
        self.assertEqual((r["state"], r["calibration"]["status"], r["result"]["point_kind"]), ("READY", "UNCALIBRATED", "median"))
        self.assertNotIn("probability", json.dumps(r["result"]))
        n = svc.db.one("SELECT COUNT(*) AS n FROM tsfm_forecasts WHERE outcome_status='PENDING'")["n"]
        self.assertEqual(n, 2)                                                  # stored BEFORE the outcome
        later = K.make_bars(300, WED_1200 + 3 * 3600, 10)
        svc.settle("XAUUSD", "M5", [b for b in later if b["closed"]])
        rows = svc.db.query("SELECT * FROM tsfm_forecasts")
        self.assertTrue(all(x["outcome_status"] == "SETTLED" for x in rows), [x["outcome_status"] for x in rows])
        self.assertTrue(all(x["naive_abs_err_h"] is not None and x["abs_err_h"] is not None for x in rows))
        q = {x["model_id"]: x for x in rows}
        self.assertTrue(q["chronos2"]["pinball_h"] is not None and q["chronos2"]["covered_80"] in (0, 1))
        self.assertTrue(q["granite_ttm"]["pinball_h"] is None and q["granite_ttm"]["covered_80"] is None)   # point model: no invented quantiles
        g = {r["model_id"]: r for r in TP.contract_predictions(svc, "XAUUSD")}["tsfm:granite_ttm"]
        self.assertEqual((g["result"]["quantiles_h"], g["checkpoint_revision"][:8], g["snapshot_id"], g["data_profile"]),
                         ({}, "d6a79570", c["snapshot_id"], "CLOSE_V1"))
        self.assertNotIn("median", g["result"])                                # point model: field absent, never null / invented
        self.assertEqual((g["validation_status"], g["freshness"]["current"]), ("NOT_VALIDATED", True))
        self.assertIsNotNone(g["latency_ms"])
        cmp = svc.compare("XAUUSD", "M5")
        self.assertEqual(cmp["summary"]["n"], 2)
        self.assertNotIn("%", cmp["summary"]["text"])
        self.assertEqual((cmp["summary"]["leading"], cmp["summary"]["agree"]), ("UP", 2))
        svc.latest[("granite_ttm", "XAUUSD", "M5")]["direction"] = "DOWN"          # 1 up / 1 down: a tie has no leading direction
        cmp = svc.compare("XAUUSD", "M5")
        self.assertEqual((cmp["summary"]["leading"], cmp["summary"]["agree"], cmp["summary"]["conflict"]), (None, None, True))
        self.assertIn("brak przewagi", cmp["summary"]["text"])

    def test_dedup_and_result_for_older_bar_is_not_current(self):
        svc = self.make()
        svc.tick()
        job = dict(svc.queue[("chronos2", "XAUUSD", "M5")])
        svc.enqueue(dict(job))
        self.assertEqual(svc.counters["deduplicated"], 1)
        svc.queue.clear()
        svc._target(("XAUUSD", "M5"))["bar_key"] = "2099-01-01T00:00:00Z"      # a newer bar closed while computing
        fc = svc.run_job(job)
        self.assertTrue(fc["superseded"])
        self.assertNotIn(("chronos2", "XAUUSD", "M5"), svc.latest)
        self.assertFalse(svc.target_view(("chronos2", "XAUUSD", "M5"))["forecast_current"])

    def test_timeout_crash_load_failure_give_no_value(self):
        from masterquo.tsfm import predictions as TP
        for mode, code in (("timeout", "TIMEOUT"), ("crash", None), ("load_fail", "INCOMPATIBLE"), ("oom", "RESOURCE_LIMIT")):
            svc = self.make(mode=mode)
            svc.tick()
            self.run_queue()
            w = svc.workers["chronos2"]
            self.assertIn(w.state["status"], ("ERROR",), (mode, w.state))
            if code:
                self.assertIn(code, (w.state.get("code") or "") + (w.state.get("reason") or ""), (mode, w.state))
            self.assertNotIn(("chronos2", "XAUUSD", "M5"), svc.latest)
            r = [x for x in TP.contract_predictions(svc, "XAUUSD") if x["model_id"] == "tsfm:chronos2"][0]
            self.assertIsNone(r["result"])
            self.assertTrue(r["unavailable_reason"])
            svc.stop()

    def test_mt5_disconnected(self):
        svc = self.make()
        self.bridge.connected = False
        svc.tick()
        self.assertEqual(svc.mstate[("chronos2", "XAUUSD", "M5")]["state"], "MT5_DISCONNECTED")
        self.assertEqual(svc.queue, {})

    def test_sh_receiver_roles_and_approvals(self):
        from masterquo.tsfm import predictions as TP
        from masterquo.tsfm import validation as V
        svc = self.make(mode="down")
        svc.tick()
        self.run_queue()
        ctx = TP.context(svc, "chronos2", "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual((ctx["use"], ctx["relation"]), ("OBSERVE", "PRZECIWNY"))
        su = TP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)
        self.assertEqual(su["status"], "READY")                               # OBSERVE: information only
        r = svc.set_use("chronos2", "SCALPING", "ASSIST", timeframe="M5", confirm=True)
        self.assertFalse(r["ok"])
        self.assertIn("VALIDATION_REQUIRED", r["reason"])
        # a positive REAL report bound to the current settings -> ASSIST accepted; the contrary fresh forecast holds READY -> WAIT
        b = V.binding(svc, "chronos2", "XAUUSD", "M5")
        rep = {"schema": V.SCHEMA, "instrument": "XAUUSD", "timeframe": "M5", "status": "DONE", "bindings": {"chronos2": b},
               "models": {"chronos2": {"verdict": {"positive": True, "reason": "test"}}}}
        rep = V._save(rep)
        self.assertTrue(svc.set_use("chronos2", "SCALPING", "ASSIST", timeframe="M5", confirm=True)["ok"])
        ctx = TP.context(svc, "chronos2", "XAUUSD", "SCALPING", side="BUY")
        su = TP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)
        self.assertEqual(su["status"], "WAIT")
        self.assertIn("ASSIST", su["status_reason"])
        # a binding change (horizon) makes the approval stale: ASSIST -> no effect, REQUIRED -> hold (fail-closed)
        svc.settings.update({"horizon_bars": {"M5": 6}})
        ctx = TP.context(svc, "chronos2", "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual(ctx["use"], "OBSERVE")
        self.assertIn("nieaktualne", ctx["reason"])
        svc.settings.update({"horizon_bars": {"M5": 12}})
        self.assertTrue(svc.set_use("chronos2", "SCALPING", "REQUIRED", timeframe="M5", confirm=True)["ok"])
        svc.settings.update({"models": {"chronos2": {"context_len": 256}}})
        ctx = TP.context(svc, "chronos2", "XAUUSD", "SCALPING", side="SELL")
        self.assertEqual(ctx["state"], "STALE_APPROVAL")
        su = TP.apply_to_setup({"status": "READY", "side": "SELL"}, ctx)
        self.assertEqual(su["status"], "WAIT")
        rows = TP.sh_record_rows(su)
        self.assertTrue(rows and all(x["no_required"] and x["use"] == "SHADOW" for x in rows))   # already applied: recorded only

    def test_coordinator_rows_active_role(self):
        from masterquo.tsfm import predictions as TP
        svc = self.make(tfs=("M5", "M15"))
        svc.tick()
        self.run_queue()
        rows = TP.coordinator_rows(svc, "XAUUSD")
        self.assertEqual({r["family"] for r in rows}, {"tsfm:chronos2", "tsfm:granite_ttm"})
        self.assertTrue(all(r["timeframe"] == "M15" and r["use"] == "SHADOW" for r in rows))   # ACTIVE role reads M15 by default


class TestKronosMigration(unittest.TestCase):
    def test_largest_public_variant_pinned(self):
        from kronos_runtime import lock as LK
        self.assertEqual((LK.MODEL["repo"], LK.MODEL_NAME, LK.MODEL["params_measured"]), ("NeoQuasar/Kronos-base", "Kronos-base", 102310592))
        self.assertEqual(LK.TOKENIZER["repo"], "NeoQuasar/Kronos-Tokenizer-base")
        self.assertEqual(LK.MAX_CONTEXT, 512)
        self.assertEqual(LK.name_of(None, "901c26c1332695a2a8f243eb2f37243a37bea320"), "Kronos-small")     # history stays Small
        self.assertEqual(LK.name_of("NeoQuasar/Kronos-base"), "Kronos-base")
        self.assertEqual(LK.REFERENCE_DATA_MODEL, "NeoQuasar/Kronos-small")

    def test_old_small_approval_is_stale_for_base(self):
        from masterquo.kronos import validation as KV
        from kronos_runtime import lock as LK
        old = {"model_revision": LK.LEGACY[0]["revision"], "tokenizer_revision": LK.TOKENIZER["revision"]}
        cur = {"schema": "x", "model_revision": LK.MODEL["revision"], "tokenizer_revision": LK.TOKENIZER["revision"]}
        d = KV.binding_diff(old, cur)
        self.assertTrue(any(x.startswith("model_revision") for x in d))

    def test_ids_keep_history_separate(self):
        from masterquo.quant import ids as I
        self.assertEqual(I.resolve("Kronos-base"), "kronos:Kronos-base")
        self.assertEqual(I.resolve("Kronos-small"), "kronos:Kronos-small")
        self.assertEqual(I.resolve("Chronos-2"), "tsfm:chronos2")
        self.assertEqual(I.resolve("FinCast"), "tsfm:fincast")                   # history id stays FinCast (retired)
        self.assertEqual(I.resolve("Granite TTM"), "tsfm:granite_ttm")


class TestFinCastRetirement(unittest.TestCase):
    def test_settings_of_139_migrated_backup_and_history(self):
        from masterquo.tsfm.settings import SettingsStore
        td = TempData()
        try:
            p = Path(td.dir) / "tsfm" / "settings.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            old = {"models": {"chronos2": {"enabled": True, "timeframes": ["M5"]}, "fincast": {"enabled": True, "use": {"SCALPING": {"use": "ASSIST",
                   "timeframe": "M5", "validation_report": "R1", "confirmed_at": "x"}}}}, "horizon_bars": {"M5": 12}}
            p.write_text(json.dumps(old), encoding="utf-8")
            st = SettingsStore(p)
            s = st.get()
            self.assertIsNone(st.load_error)
            self.assertEqual(set(s.models), {"chronos2", "granite_ttm"})
            self.assertEqual(s.models["chronos2"].timeframes, ["M5"])             # user values kept
            self.assertEqual(s.models["granite_ttm"].use["SCALPING"].use, "OBSERVE")  # FinCast role NOT carried over
            self.assertEqual(s.retired["fincast"]["status"], "RETIRED")
            self.assertEqual(json.loads((p.parent / "settings.v139.bak.json").read_text(encoding="utf-8")), old)
            h = st.history()
            self.assertEqual(h[-1]["who"], "migration")
            st.update({"models": {"granite_ttm": {"enabled": False}}}, who="test")
            self.assertEqual(st.history()[-1]["change"], {"models": {"granite_ttm": {"enabled": False}}})
            self.assertNotIn("fincast", json.loads(p.read_text(encoding="utf-8"))["models"])
        finally:
            td.close()

    def test_engine_and_installer_refuse_fincast(self):
        from tsfm_runtime import engines as E
        from tsfm_runtime import install as I
        with self.assertRaises(E.EngineError) as cm:
            E.make("fincast")
        self.assertEqual(cm.exception.code, "RETIRED")
        with self.assertRaises(SystemExit):
            I.main(["download", "--model", "fincast", "--weights-root", "/nonexistent"])


if __name__ == "__main__":
    unittest.main()
