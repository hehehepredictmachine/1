"""1.46 audit, group B_mq_api: api/app.py, api/owner_routes.py, api/security.py.

Every route is the real one from create_app, called in-process through ASGI (no socket, no demo server; the port number is only the
Host / Origin check). The runtime is a MagicMock with real services where the defect lives in their interplay (liquidity schedule,
config mapping, ML job rows, prediction ledger). All market data is SYNTHETIC."""
import asyncio
import json
import mimetypes
import os
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import _env  # noqa: F401
from _env import TempData

PORT = 18782
ORIGIN = f"http://127.0.0.1:{PORT}"


def make_rt(**kw):
    rt = mock.MagicMock()
    rt.license.locked = False
    rt.cfg.get.return_value.assets.active = "XAUUSD"
    for k, v in kw.items():
        setattr(rt, k, v)
    return rt


def make_app(rt):
    from masterquo.api import app as A
    return A.create_app(rt, PORT)


def call(app, rt, method: str, path: str, qs: dict | None = None, body=None, raw: bytes | None = None, headers: dict | None = None):
    """One HTTP request through the ASGI app -> (status, body bytes, response headers). A route exception that escapes the app counts
    as the 500 the client would see."""
    sid, csrf = rt.security.new_session()
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    hdrs = [(b"host", f"127.0.0.1:{PORT}".encode()), (b"cookie", f"mq_sid={sid}".encode())]
    if method not in ("GET", "HEAD"):
        hdrs += [(b"origin", ORIGIN.encode()), (b"x-mq-csrf", csrf.encode()), (b"content-type", b"application/json"),
                 (b"content-length", str(len(data)).encode())]
    for k, v in (headers or {}).items():
        hdrs.append((k.lower().encode(), v.encode()))
    msgs, sent = [], {"done": False}

    async def receive():
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": data, "more_body": False}
        await asyncio.sleep(3600)

    async def send(m):
        msgs.append(m)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path,
             "raw_path": path.encode(), "root_path": "", "query_string": urlencode(qs or {}).encode(), "headers": hdrs,
             "server": ("127.0.0.1", PORT), "client": ("127.0.0.1", 1)}
    try:
        asyncio.run(app(scope, receive, send))
    except Exception:  # noqa: BLE001, S110 - Starlette re-raises after sending the 500
        pass
    start = next((m for m in msgs if m["type"] == "http.response.start"), None)
    if start is None:
        return 500, b"", {}
    return (start["status"], b"".join(m.get("body", b"") for m in msgs if m["type"] == "http.response.body"),
            {k.decode().lower(): v.decode() for k, v in start["headers"]})


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()


# ------------------------------------------------------------------------------------------------------------- chunk_03#1
class LiquidityForcedPoll(_Base):
    def test_forced_poll_keeps_the_background_schedule(self):
        from masterquo.analytics.liquidation.service import LiquidityService
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from test_liquidity import model1
        cs = ConfigStore()
        cs.update({"liquidity": {"sources": {"BTC": {"enabled": True, "source_symbol": "BTC", "variant": "AGGREGATED", "range": "24h"}}}})
        calls = []

        def fetch(*a):
            calls.append(a)
            return {"data": model1(), "request": {}}
        sec = type("S", (), {"get": lambda s, n: "k", "source": lambda s, n: "LOCAL_STORE"})()
        svc = LiquidityService(cs, Database(), None, None, secrets=sec, fetcher=fetch)
        rt = make_rt(liquidity=svc)
        app = make_app(rt)
        st, body, _ = call(app, rt, "POST", "/api/v1/liquidity/poll", body={})
        self.assertEqual(st, 200, body[:300])
        self.assertEqual(len(json.loads(body)["polled"]), 1)
        key = json.loads(body)["polled"][0]
        poll_s = svc.cfg.poll_seconds
        self.assertLessEqual(svc._next[key] - time.monotonic(), poll_s + 5)          # was ~1e9 s (31 years)
        self.assertEqual(svc.poll_once(), [])                                          # not due right after the forced poll
        self.assertEqual(svc.poll_once(time.monotonic() + poll_s + 1), [key])          # the background loop polls it again
        self.assertEqual(len(calls), 2)


# ------------------------------------------------------------------------------------------------------------- chunk_03#2 (+ focus_X1#4 mt5)
class ConfigSaveKeepsConfirmedMapping(_Base):
    def _app(self):
        from masterquo.config import ConfigStore
        self.cs = ConfigStore()
        self.cs.update({"mt5": {"symbol": "XAUUSD-"},
                        "assets": {"mappings": {"XAUUSD": {"broker_symbol": "XAUUSD-", "status": "CONFIRMED", "confirmed_at": "2026-11-01T00:00:00+00:00",
                                                           "fingerprint": {"trade_contract_size": 100.0}}}}})
        secrets = mock.MagicMock()
        secrets.source.return_value = "NONE"
        secrets.mask.return_value = None
        self.rt = make_rt(cfg=self.cs, secrets=secrets)
        return make_app(self.rt)

    def test_unchanged_symbol_keeps_confirmed(self):
        app = self._app()
        st, body, _ = call(app, self.rt, "PUT", "/api/v1/config", body={"mt5": {"symbol": "XAUUSD-"}, "risk": self.cs.get().risk.model_dump()})
        self.assertEqual(st, 200, body[:300])
        m = self.cs.get().assets.mappings["XAUUSD"]
        self.assertEqual((m.status, m.broker_symbol), ("CONFIRMED", "XAUUSD-"))
        self.assertEqual(m.fingerprint, {"trade_contract_size": 100.0})

    def test_new_symbol_is_still_the_users_mapping(self):
        app = self._app()
        st, body, _ = call(app, self.rt, "PUT", "/api/v1/config", body={"mt5": {"symbol": "XAUUSD.pro"}})
        self.assertEqual(st, 200, body[:300])
        m = self.cs.get().assets.mappings["XAUUSD"]
        self.assertEqual((m.status, m.broker_symbol), ("USER_SPECIFIED", "XAUUSD.pro"))

    def test_mt5_not_an_object_is_400(self):
        app = self._app()
        st, _, _ = call(app, self.rt, "PUT", "/api/v1/config", body={"mt5": "x"})
        self.assertEqual(st, 400)


# ------------------------------------------------------------------------------------------------------------- chunk_03#3 (+#6, focus_X1#4)
TRADE_PLAN = {"side": "BUY", "entry": 2400, "sl": 2395, "tp": 2410, "lots": 0.1}


class TradePad(_Base):
    def _rt(self, comm):
        rt = make_rt()
        rt.cfg.get.return_value.scalp.commission_per_lot_side = comm
        rt.assets.check_asset.return_value = "XAUUSD-"
        rt.bridge.symbol_meta.return_value = {"trade_contract_size": 100.0}
        rt.bridge.symbol_info = {"volume_min": 0.01, "volume_step": 0.01}
        rt.bridge.quote_status.return_value = {"bid": 2400.0, "ask": 2400.2}
        return rt

    PLAN = TRADE_PLAN

    def test_unknown_commission_is_unavailable_not_zero(self):
        rt = self._rt(None)
        st, body, _ = call(make_app(rt), rt, "POST", "/api/v1/lab/tradepad", body=self.PLAN)
        self.assertEqual(st, 200, body[:300])
        p = json.loads(body)
        self.assertIsNone(p["pnl_at_tp"])
        self.assertIsNone(p["pnl_at_sl"])
        self.assertIsNone(p["commission_round_turn"])
        self.assertEqual((p["cost_status"], p["cost_reason"]), ("UNAVAILABLE", "COMMISSION_UNKNOWN"))

    def test_known_commission_unchanged(self):
        rt = self._rt(0.5)
        st, body, _ = call(make_app(rt), rt, "POST", "/api/v1/lab/tradepad", body=self.PLAN)
        p = json.loads(body)
        self.assertEqual((st, p["pnl_at_tp"], p["pnl_at_sl"], p["commission_round_turn"]), (200, 99.9, -50.1, 0.1))
        self.assertNotIn("cost_status", p)

    def test_entry_null_is_400(self):
        rt = self._rt(0.5)
        st, _, _ = call(make_app(rt), rt, "POST", "/api/v1/lab/tradepad", body=dict(self.PLAN, entry=None))
        self.assertEqual(st, 400)


# ------------------------------------------------------------------------------------------------------------- chunk_03#4, focus_X1#1
class InstrumentFromBodyStaysInDataDir(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir) / "data"
        self.data.mkdir()
        os.environ["MASTERQUO_DATA_DIR"] = str(self.data)
        self.rt = make_rt()
        self.rt.quant.jobs = {}
        self.rt.quant.instrument.return_value = "XAUUSD"
        self.rt.ml.inst = "XAUUSD"
        self.app = make_app(self.rt)

    def tearDown(self):
        self.td.close()

    def outside(self):
        return sorted(p.name for p in Path(self.td.dir).iterdir() if p.name != "data")

    def test_quant_models_rollback_activate_jobs(self):
        for path, body in (("/api/v1/quant/models/rollback", {"instrument": "../../../escape_q"}),
                           ("/api/v1/quant/models/activate", {"instrument": "../../../escape_q", "task_hash": "t", "version": "v"}),
                           ("/api/v1/quant/models/activate", {"instrument": {"a": 1}}),
                           ("/api/v1/quant/jobs", {"instrument": "../../../escape_q"})):
            st, body_, _ = call(self.app, self.rt, "POST", path, body=body)
            self.assertEqual(st, 400, (path, body_[:200]))
        self.assertEqual(self.outside(), [])
        self.rt.quant.train.assert_not_called()

    def test_indicator_context_activate_rollback(self):
        for path in ("/api/v1/indicator-context/rollback", "/api/v1/indicator-context/activate"):
            st, _, _ = call(self.app, self.rt, "POST", path, body={"asset": "../../escape_ic"})
            self.assertEqual(st, 403, path)
            st, _, _ = call(self.app, self.rt, "POST", path, body={"asset": 5})
            self.assertEqual(st, 403, path)
        self.assertEqual(self.outside(), [])

    def test_ml_scalp_select_rollback(self):
        for path in ("/api/v1/ml/scalp/select", "/api/v1/ml/scalp/rollback"):
            st, _, _ = call(self.app, self.rt, "POST", path, body={"asset": "../../escape_ml", "side": "BUY", "run_id": "r", "role": "OBSERVE"})
            self.assertEqual(st, 400, path)
        self.assertEqual(self.outside(), [])


# ------------------------------------------------------------------------------------------------------------- chunk_03#5
class SdformerCheckpoint(_Base):
    def _rt(self):
        rt = make_rt()
        self.sdf = Path(self.td.dir) / "sdformer"
        (self.sdf / "SDF-20261101T000000").mkdir(parents=True)
        (self.sdf / "SDF-20261101T000000" / "last.pt").write_bytes(b"x")
        rt.research._sdf_dir.return_value = self.sdf
        rt.research.settings.return_value = {"sdformer": {"active_run": None}}
        rt.research.start_training.return_value = {"ok": True}
        rt.research.components.start_job.return_value = {"ok": True}
        return rt

    def test_checkpoint_must_be_a_version_in_the_sdf_folder(self):
        rt = self._rt()
        app = make_app(rt)
        for ck in (5, "../outside", str(Path(self.td.dir) / "evil"), "SDF-MISSING"):
            st, body, _ = call(app, rt, "POST", "/api/v1/research-modules/sdformerflow/train", body={"op": "fine_tune", "checkpoint": ck})
            self.assertEqual(st, 400, (ck, body[:200]))
            st, _, _ = call(app, rt, "POST", "/api/v1/trainhub/components/TH_SDFORMERFLOW/jobs", body={"kind": "TRAIN", "op": "resume", "checkpoint": ck})
            self.assertEqual(st, 400, ck)
        rt.research.start_training.assert_not_called()
        rt.research.components.start_job.assert_not_called()
        st, _, _ = call(app, rt, "POST", "/api/v1/research-modules/sdformerflow/train", body={"op": "fine_tune", "checkpoint": "SDF-20261101T000000"})
        self.assertEqual(st, 200)
        self.assertEqual(rt.research.start_training.call_args.kwargs["checkpoint"], str(self.sdf / "SDF-20261101T000000"))


# ------------------------------------------------------------------------------------------------------------- chunk_03#6
class SymbolNotAllowedIsNot500(_Base):
    def test_structure_intelligence_and_lab_routes(self):
        from masterquo.assets.registry import SymbolNotAllowed
        rt = make_rt()
        app = make_app(rt)
        rt.assets.check_asset.side_effect = SymbolNotAllowed("ASSET_NOT_ALLOWED:STRUCTURE_INTELLIGENCE:FOO")
        st, body, _ = call(app, rt, "GET", "/api/v1/structure-intelligence/forecasts", qs={"asset": "FOO"})
        self.assertEqual(st, 403, body[:200])
        self.assertIn(b"ASSET_NOT_ALLOWED", body)
        rt.assets.check_asset.side_effect = SymbolNotAllowed("ASSET_NOT_USABLE:STRUCTURE_INTELLIGENCE:BTC:BRAK_SYMBOLU_W_TERMINALU")
        st, _, _ = call(app, rt, "GET", "/api/v1/flow-context", qs={"asset": "BTC"})
        self.assertEqual(st, 409)
        st, _, _ = call(app, rt, "POST", "/api/v1/lab/zones", body={"asset": "BTC", "tf": "M5", "kind": "DEMAND", "top": 2, "bottom": 1,
                                                                    "origin_time": "2026-11-01T00:00:00Z"})
        self.assertEqual(st, 409)
        st, _, _ = call(app, rt, "POST", "/api/v1/lab/tradepad", body={"side": "BUY", "entry": 1, "sl": 0.5, "tp": 2})
        self.assertEqual(st, 409)


# ------------------------------------------------------------------------------------------------------------- chunk_03#7, focus_X1#2
class MlScalpStatusIsReadOnly(_Base):
    def test_get_of_the_other_instrument_does_not_interrupt_its_jobs(self):
        from masterquo.ml.router import ml_store
        db, _ = ml_store("BTC")
        db.execute("INSERT INTO ml_jobs(job_id, kind, status, created_at, started_at, snapshot_id, detail_json) VALUES (?,?,?,?,?,?,?)",
                   ("OFF-BTC-1", "TRAIN", "RUNNING", "2026-11-23T10:00:00+00:00", "2026-11-23T10:00:00+00:00", "snap", "{}"))
        rt = make_rt()
        rt.ml.inst = "XAUUSD"
        app = make_app(rt)
        st, body, _ = call(app, rt, "GET", "/api/v1/ml/scalp", qs={"asset": "BTC"})
        self.assertEqual(st, 200, body[:300])
        self.assertEqual(json.loads(body)["instrument"], "BTC")
        self.assertEqual(db.one("SELECT status FROM ml_jobs WHERE job_id='OFF-BTC-1'")["status"], "RUNNING")      # was INTERRUPTED
        st, _, _ = call(app, rt, "GET", "/api/v1/ml/scalp", qs={"asset": "FOO"})
        self.assertEqual(st, 400)
        db.close()


# ------------------------------------------------------------------------------------------------------------- chunk_03#8
class ImportsRunOutsideTheEventLoop(_Base):
    def test_component_and_training_import(self):
        seen = []
        rt = make_rt()
        rt.research.components.import_zip.side_effect = lambda cid, data: seen.append(threading.current_thread()) or {"ok": True}
        app = make_app(rt)
        st, body, _ = call(app, rt, "POST", "/api/v1/trainhub/components/ETC_LOG_CHANNEL/import", raw=b"PK-zip-bytes")
        self.assertEqual(st, 200, body[:200])
        with mock.patch("masterquo.training.panel.import_package", side_effect=lambda data: seen.append(threading.current_thread()) or {"ok": True}):
            st, body, _ = call(app, rt, "POST", "/api/v1/training/import", raw=b"PK-zip-bytes")
        self.assertEqual(st, 200, body[:200])
        self.assertEqual(len(seen), 2)
        for t in seen:
            self.assertIsNot(t, threading.main_thread())                 # the event loop runs in the main thread here


# ------------------------------------------------------------------------------------------------------------- chunk_03#9 (+#12 commission)
class OneTrainingProcessAtATime(_Base):
    def test_second_start_while_running_is_409(self):
        procs = []

        class P:
            pid = 4242

            def __init__(self, *a, **k):
                procs.append(self)
                self.rc = None

            def poll(self):
                return self.rc
        rt = make_rt()
        app = make_app(rt)
        with mock.patch.object(subprocess, "Popen", P):
            for path in ("/api/v1/indicator-context/train", "/api/v1/ml/scalp/train"):
                st, body, _ = call(app, rt, "POST", path, body={"asset": "XAUUSD"})
                self.assertEqual(st, 200, body[:200])
                st, _, _ = call(app, rt, "POST", path, body={"asset": "XAUUSD"})
                self.assertEqual(st, 409, path)
                procs[-1].rc = 0                                         # finished -> a new start is allowed
                st, _, _ = call(app, rt, "POST", path, body={"asset": "XAUUSD"})
                self.assertEqual(st, 200, path)
            self.assertEqual(len(procs), 4)
            for path in ("/api/v1/indicator-context/train", "/api/v1/ml/scalp/train"):
                for bad in ("abc", -1, "nan"):
                    procs[-1].rc = 0
                    st, _, _ = call(app, rt, "POST", path, body={"asset": "XAUUSD", "commission": bad})
                    self.assertEqual(st, 400, (path, bad))
            self.assertEqual(len(procs), 4)


# ------------------------------------------------------------------------------------------------------------- chunk_03#10
class MmLedgerNewest(_Base):
    def test_ledger_route_returns_the_newest_window(self):
        from masterquo.mm.ledger import Ledger
        led = Ledger(Path(self.td.dir) / "ledger.sqlite")
        for i in range(500):
            led.log(pred_id=f"p{i}", model_id="m", artifact_id=None, feature_schema=None, symbol="XAUUSD", timeframe="M5", source_ts=1000.0 + i,
                    available_at=1000.0 + i, matures_at=2000.0 + i, horizon="1", kind="k", payload={"i": i}, quality="OK")
        rt = make_rt()
        rt.mm._ledger.return_value = led
        st, body, _ = call(make_app(rt), rt, "GET", "/api/v1/mm/ledger", qs={"instrument": "XAUUSD", "model": "m", "limit": 200})
        self.assertEqual(st, 200, body[:200])
        rows = json.loads(body)["rows"]
        self.assertEqual(len(rows), 200)
        self.assertEqual((rows[0]["pred_id"], rows[-1]["pred_id"]), ("p300", "p499"))             # was p0 .. p199
        self.assertEqual(rows[-1]["payload"], {"i": 499})
        self.assertEqual([r["source_ts"] for r in rows], sorted(r["source_ts"] for r in rows))
        led.c.close()


# ------------------------------------------------------------------------------------------------------------- chunk_03#11
class ShPackStatsMoney(_Base):
    def test_missing_money_is_null_not_zero(self):
        rt = make_rt()
        rows = [{"strategy_id": "A", "signal_tf": "M5", "exec_mode": "PAPER", "result": json.dumps({"r_multiple": 1.0})},
                {"strategy_id": "A", "signal_tf": "M5", "exec_mode": "PAPER", "result": json.dumps({"r_multiple": -0.5})},
                {"strategy_id": "B", "signal_tf": "M5", "exec_mode": "PAPER", "result": json.dumps({"r_multiple": 1.0, "net_money": 12.5})},
                {"strategy_id": "B", "signal_tf": "M5", "exec_mode": "PAPER", "result": json.dumps({"r_multiple": -1.0})}]
        rt.db.query.return_value = rows
        st, body, _ = call(make_app(rt), rt, "GET", "/api/v1/sh/pack/stats")
        self.assertEqual(st, 200, body[:200])
        g = {x["strategy_id"]: x for x in json.loads(body)["items"]}
        self.assertIsNone(g["A"]["net_money"])                                                     # was 0.0
        self.assertEqual((g["A"]["n"], g["A"]["n_money"]), (2, 0))
        self.assertEqual((g["B"]["net_money"], g["B"]["n_money"], g["B"]["n"]), (12.5, 1, 2))


# ------------------------------------------------------------------------------------------------------------- chunk_03#12, focus_X1#4
class InputErrorsAre4xxNot500(_Base):
    def test_listed_requests(self):
        rt = make_rt()
        rt.ml.inst = "XAUUSD"
        rt.bridge.bars.side_effect = KeyError("BAD")
        rt.svp.create_manual.side_effect = lambda spec: float(spec["lower"])
        app = make_app(rt)
        cases = [("GET", "/api/v1/svp/zones", {"as_of": "garbage"}, None, None, 400),
                 ("PUT", "/api/v1/liquidity/key", None, {"key": 5}, None, 400),
                 ("POST", "/api/v1/quant/assessment", None, {"candidate": [1, 2]}, None, 400),
                 ("POST", "/api/v1/quant/assessment", None, {"candidate": "x"}, None, 400),
                 ("GET", "/api/v1/trainhub/components/FOO/export.zip", {"version": "ETC-INITIAL"}, None, None, 404),
                 ("POST", "/api/v1/trainhub/components/FOO/activate", None, {"version": "v"}, None, 404),
                 ("POST", "/api/v1/trainhub/components/FOO/rollback", None, {}, None, 404),
                 ("POST", "/api/v1/trainhub/components/FOO/cancel", None, {}, None, 404),
                 ("POST", "/api/v1/lab/zones", None, {"tf": "M5", "kind": "DEMAND", "top": None, "bottom": 1, "origin_time": "t"}, None, 400),
                 ("PATCH", "/api/v1/lab/zones/Z1", None, {"expected_revision": None}, None, 400),
                 ("PATCH", "/api/v1/lab/zones/Z1", None, {"expected_revision": 1, "top": "abc"}, None, 400),
                 ("POST", "/api/v1/training/resume", None, {"run_id": 1234567}, None, 404),
                 ("POST", "/api/v1/montecarlo/run", None, None,
                  b'{"side": "BUY", "sl_distance": 1, "tp_distances": [1], "horizon": Infinity}', 400),
                 ("POST", "/api/v1/svp/zones", None, {"lower": None, "upper": 1}, None, 400),
                 ("POST", "/api/v1/kronos/strategy-use", None, {"strategy": "S", "use": "OFF", "timeframe": 5}, None, 400),
                 ("POST", "/api/v1/models/foundation/use", None, {"model": "chronos2", "path": "P", "use": "OFF", "timeframe": 5}, None, 400),
                 ("POST", "/api/v1/models/foundation/use", None, {"model": 5}, None, 400),
                 ("GET", "/api/v1/indicator-context/chart", {"tf": "BAD"}, None, None, 400)]
        rt.lab.zones.patch.return_value = {"ok": True}
        for method, path, qs, body, raw, want in cases:
            st, out, _ = call(app, rt, method, path, qs=qs, body=body, raw=raw)
            self.assertEqual(st, want, (method, path, body, out[:200]))
        rt.lab.zones.patch.assert_not_called()
        with mock.patch("masterquo.studio.importer.import_package", side_effect=KeyError("task")):
            st, _, _ = call(app, rt, "POST", "/api/v1/studio/import", body={"package": "x"})
        self.assertEqual(st, 400)


# ------------------------------------------------------------------------------------------------------------- chunk_34#7
class SignalsLimit(_Base):
    def test_negative_limit_is_not_unbounded(self):
        rt = make_rt()
        rt.engine.lifecycle.recent.return_value = []
        rt.engine.active.tracker.recent.return_value = []
        rt.db.query.return_value = []
        rt.gateway.recent_attempts.return_value = []
        st, body, _ = call(make_app(rt), rt, "GET", "/api/v1/signals", qs={"limit": -1})
        self.assertEqual(st, 200, body[:200])
        self.assertGreaterEqual(rt.engine.lifecycle.recent.call_args.args[0], 1)               # was -1 = SQLite LIMIT -1 (all rows)
        self.assertGreaterEqual(rt.engine.active.tracker.recent.call_args.args[0], 1)


# ------------------------------------------------------------------------------------------------------------- chunk_03#13
class BasketPlanIdFilter(_Base):
    def test_basket_plan_id_is_accepted(self):
        rt = make_rt()
        app = make_app(rt)
        with mock.patch("masterquo.plans.service.collect_pack", return_value={"items": []}) as cp:
            st, _, _ = call(app, rt, "GET", "/api/v1/plans/chart", qs={"layer": "PACK", "plan_id": "PL-BK" + "a1" * 10})
            self.assertEqual(st, 200)
            self.assertEqual(cp.call_args.kwargs["plan_id"], "PL-BK" + "a1" * 10)
            st, _, _ = call(app, rt, "GET", "/api/v1/plans/chart", qs={"layer": "PACK", "plan_id": "PL-" + "0f" * 7})
            self.assertEqual(st, 200)
            st, _, _ = call(app, rt, "GET", "/api/v1/plans/chart", qs={"layer": "PACK", "plan_id": "PL-../x"})
            self.assertEqual(st, 400)


# ------------------------------------------------------------------------------------------------------------- chunk_03#14
class WebSocketHello(_Base):
    def test_non_object_hello_closes_with_4400(self):
        rt = make_rt()
        app = make_app(rt)
        sid, _ = rt.security.new_session()
        inbox = [{"type": "websocket.connect"}, {"type": "websocket.receive", "text": "[1, 2]"}]
        out = []

        async def receive():
            if inbox:
                return inbox.pop(0)
            return {"type": "websocket.disconnect", "code": 1000}

        async def send(m):
            out.append(m)
        scope = {"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "ws", "path": "/api/v1/ws", "raw_path": b"/api/v1/ws", "root_path": "",
                 "query_string": b"", "headers": [(b"host", f"127.0.0.1:{PORT}".encode()), (b"origin", ORIGIN.encode()),
                                                  (b"cookie", f"mq_sid={sid}".encode())], "server": ("127.0.0.1", PORT), "client": ("127.0.0.1", 1),
                 "subprotocols": []}
        try:
            asyncio.run(app(scope, receive, send))
        except Exception:  # noqa: BLE001, S110 - the close code below is what the client sees
            pass
        closes = [m for m in out if m["type"] == "websocket.close"]
        self.assertEqual([c.get("code") for c in closes], [4400], out)


# ------------------------------------------------------------------------------------------------------------- chunk_03#15
class SubprocessTimeouts(_Base):
    def test_timeout_is_an_answer_not_500(self):
        rt = make_rt()
        rt.ml.inst = "BTC"
        app = make_app(rt)
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            st, body, _ = call(app, rt, "POST", "/api/v1/training/rollback", body={"instrument": "XAUUSD", "family": "forecast"})
            self.assertEqual(st, 200, body[:200])
            self.assertEqual((json.loads(body)["ok"], json.loads(body)["reason"]), (False, "TIMEOUT"))
            rt.forecast.reload.assert_called()
            st, body, _ = call(app, rt, "POST", "/api/v1/lab/neural/doctor", body={"asset": "XAUUSD"})
            self.assertEqual(st, 200, body[:200])
            self.assertEqual(json.loads(body)["reason"], "TIMEOUT")


# ------------------------------------------------------------------------------------------------------------- chunk_03#16, focus_X1#6
class PanelFiles(_Base):
    def test_placeholder_shows_display_name(self):
        from masterquo import paths
        from masterquo.version import DISPLAY_NAME
        rt = make_rt()
        app = make_app(rt)
        with mock.patch.object(paths, "FRONTEND_DIST", Path(self.td.dir) / "no_dist"):
            st, body, _ = call(app, rt, "GET", "/")
        self.assertEqual(st, 503)
        self.assertIn(f"<h1>{DISPLAY_NAME}</h1>".encode(), body)
        self.assertNotIn(b"MasterQUO AI", body)

    def test_js_mime_does_not_depend_on_the_registry(self):
        from masterquo import paths
        dist = Path(self.td.dir) / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "assets" / "main-x.js").write_text("export {}", encoding="utf-8")
        (dist / "assets" / "main-x.css").write_text("a{}", encoding="utf-8")
        rt = make_rt()
        app = make_app(rt)
        prev_js, prev_css = mimetypes.guess_type("a.js")[0], mimetypes.guess_type("a.css")[0]
        mimetypes.add_type("text/plain", ".js")                      # what a Windows registry entry HKCR\.js "Content Type" does
        mimetypes.add_type("text/plain", ".css")
        try:
            with mock.patch.object(paths, "FRONTEND_DIST", dist):
                st, _, h = call(app, rt, "GET", "/assets/main-x.js")
                st2, _, h2 = call(app, rt, "GET", "/assets/main-x.css")
        finally:
            mimetypes.add_type(prev_js or "text/javascript", ".js")
            mimetypes.add_type(prev_css or "text/css", ".css")
        self.assertEqual((st, st2), (200, 200))
        self.assertTrue(h["content-type"].startswith("text/javascript"), h["content-type"])
        self.assertTrue(h2["content-type"].startswith("text/css"), h2["content-type"])


# ------------------------------------------------------------------------------------------------------------- chunk_03#17
class BasketsDeclare(_Base):
    def test_fomo_declaration_defaults_to_perp_and_otc_stays_retired(self):
        rt = make_rt()
        rt.baskets.ledger.declare.return_value = "D1"
        app = make_app(rt)
        st, body, _ = call(app, rt, "POST", "/api/v1/baskets/declared/CRYPTO_FOMO_PERPS", body={"instrument": "BTC", "side": "LONG", "size": 1})
        self.assertEqual((st, json.loads(body)), (200, {"id": "D1"}))
        self.assertEqual(rt.baskets.ledger.declare.call_args.args[:2], ("CRYPTO_FOMO_PERPS", "PERP"))
        st, _, _ = call(app, rt, "POST", "/api/v1/baskets/declared/CRYPTO_FOMO_PERPS", body={"instrument": "BTC"})
        self.assertEqual(st, 400)
        st, _, _ = call(app, rt, "POST", "/api/v1/baskets/declared/OTC_GOLD_POCKETOPTION", body={"dir": "UP"})
        self.assertEqual(st, 410)


# ------------------------------------------------------------------------------------------------------------- chunk_03#19
class LabTrainNeedsPoint(_Base):
    def test_missing_point_is_409_not_001(self):
        rt = make_rt()
        rt.assets.check_asset.return_value = "XAUUSD-"
        rt.bridge.state = "CONNECTED"
        rt.bridge.symbol_bars.return_value = []
        rt.bridge.symbol_meta.return_value = {"digits": 2}
        rt.lab.trainer.start.return_value = {"ok": True}
        app = make_app(rt)
        st, body, _ = call(app, rt, "POST", "/api/v1/lab/train", body={"asset": "XAUUSD"})
        self.assertEqual(st, 409, body[:200])
        self.assertIn(b"NO_SYMBOL_METADATA", body)
        rt.lab.trainer.start.assert_not_called()
        rt.bridge.symbol_meta.return_value = {"point": 0.001}
        st, _, _ = call(app, rt, "POST", "/api/v1/lab/train", body={"asset": "XAUUSD"})
        self.assertEqual(st, 200)
        self.assertEqual(rt.lab.trainer.start.call_args.kwargs["point"], 0.001)


# ------------------------------------------------------------------------------------------------------------- chunk_03#18
class OwnerLicenseHwid(_Base):
    def test_numeric_hwid_is_400(self):
        from fastapi import FastAPI
        from masterquo.api import owner_routes
        from masterquo.api.security import LocalSecurity
        with mock.patch.dict(os.environ, {"PMW_OWNER_DIR": str(Path(self.td.dir) / "owner")}):      # never the owner's real key folder
            app = FastAPI()                                               # the owner routes alone (no Guard): the input check is tested
            owner_routes.register(app)
            rt = make_rt(security=LocalSecurity(PORT))
            st, body, _ = call(app, rt, "POST", "/api/v1/owner/license/generate", body={"user": "u", "hwid": 123})
        self.assertEqual(st, 400, body[:200])
        self.assertIn(b"hwid", body)


# ------------------------------------------------------------------------------------------------------------- chunk_04#23
class CsrfCompare(unittest.TestCase):
    def test_non_ascii_or_non_text_token_is_false(self):
        from masterquo.api.security import LocalSecurity
        s = LocalSecurity(PORT)
        sid, csrf = s.new_session()
        self.assertTrue(s.csrf_ok(sid, csrf))
        for bad in ("ab\xe9", 5, ["x"], None, ""):
            self.assertFalse(s.csrf_ok(sid, bad), bad)


# ------------------------------------------------------------------------------------------------------------- focus_X1#3
class CrossSiteGet(_Base):
    def test_same_site_page_of_another_port_cannot_use_the_session_on_get(self):
        rt = make_rt()
        app = make_app(rt)
        for site in ("same-site", "cross-site"):
            st, body, _ = call(app, rt, "GET", "/api/v1/lab/traceability", headers={"Sec-Fetch-Site": site})
            self.assertEqual(st, 403, (site, body[:200]))
        for hdr in ({"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}):
            st, _, _ = call(app, rt, "GET", "/api/v1/lab/traceability", headers=hdr)
            self.assertEqual(st, 200, hdr)
        rt.bus.boot_id = "b"
        rt.demo = False
        rt.bridge.state = "CONNECTED"
        rt.start_failures = []
        st, _, _ = call(app, rt, "GET", "/api/v1/health", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 200)                                         # health stays open (desktop shell / probes)


if __name__ == "__main__":
    unittest.main()
