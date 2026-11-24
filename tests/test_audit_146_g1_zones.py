"""1.46 audit, group G1 (zones): GET /api/v1/zones/context answered 500 whenever a zone feature was missing.

The zone features of one setup mark missing data as NaN (zones.features.compute - also the ML FeatureEngine input). The context
for the evaluation layer / panel returned that dict unchanged, and NaN is not JSON: the API route (Starlette JSONResponse,
allow_nan=False) raised ValueError -> 500 for practically every request (relative volume / POC migration are missing outside a
developing session, the R distances whenever no stop is given). Missing must be reported as null (never 0, never a crash).
All market data here is SYNTHETIC (tests/test_zones.py generators)."""
import asyncio
import json
import math
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import _env  # noqa: F401
import test_zones as TZ
from _env import TempData
from masterquo.zones import features as ZF


def zone_map():
    return TZ.cmap(TZ.market(), TZ.T0 + 2016 * 300)


class ZoneContextFeaturesAreJson(unittest.TestCase):
    def test_missing_features_are_null_in_the_context_and_nan_stays_in_compute(self):
        zm = zone_map()
        for stop in (None, zm["price"] - 3):
            raw = ZF.compute(zm, direction="LONG", entry=zm["price"], stop=stop, cost_price=0.3)
            missing = {k for k, v in raw.items() if math.isnan(v)}
            self.assertTrue({"zone_relvol", "zone_poc_migration"} <= missing, missing)      # the case the audit found
            if stop is None:
                self.assertIn("zone_opp_dist_r", missing)                                     # no stop -> no R
            ctx = ZF.context_for(zm, direction="LONG", entry=zm["price"], stop=stop, cost_price=0.3, cfg=TZ.CFG)
            json.dumps(ctx, allow_nan=False)                                                  # strict JSON (what the API sends)
            self.assertEqual(set(ctx["features"]), set(ZF.NAMES))
            for k in missing:
                self.assertIsNone(ctx["features"][k], k)                                      # missing = null, never 0
            for k in set(raw) - missing:
                self.assertEqual(ctx["features"][k], raw[k], k)                               # known values unchanged
            self.assertTrue(all(math.isnan(raw[k]) for k in missing))                         # ML path (compute) keeps NaN


class ZoneContextRoute(unittest.TestCase):
    """The real route of create_app, called in-process through ASGI (no socket is opened; the port number is only the Host check)."""
    PORT = 18781

    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.zones.service import ZoneService
        self.zones = ZoneService(ConfigStore(), object(), data_dir=Path(self.td.dir) / "zones", clock=lambda: TZ.T0 + 2016 * 300)
        self.zm = zone_map()
        self.zones.map = self.zm                                       # the live map, as after refresh()

    def tearDown(self):
        self.zones.db.close()
        self.td.close()

    def get(self, path: str, qs: dict) -> tuple[int, bytes]:
        from masterquo.api import app as A
        rt = mock.MagicMock()
        rt.license.locked = False
        rt.zones = self.zones
        app = A.create_app(rt, self.PORT)
        sid, _ = rt.security.new_session()
        msgs = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(m):
            msgs.append(m)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
                 "raw_path": path.encode(), "root_path": "", "query_string": urlencode(qs).encode(),
                 "headers": [(b"host", f"127.0.0.1:{self.PORT}".encode()), (b"cookie", f"mq_sid={sid}".encode())],
                 "server": ("127.0.0.1", self.PORT), "client": ("127.0.0.1", 1)}
        try:
            asyncio.run(app(scope, receive, send))
        except ValueError:
            pass                                    # Starlette re-raises after sending the 500 - the status below is what the panel sees
        start = next(m for m in msgs if m["type"] == "http.response.start")
        return start["status"], b"".join(m.get("body", b"") for m in msgs if m["type"] == "http.response.body")

    def test_context_route_answers_200_with_null_for_missing_features(self):
        price = self.zm["price"]
        for qs in ({"direction": "LONG", "entry": price, "stop": price - 3, "cost": 0.3}, {"direction": "SHORT", "entry": price}):
            status, body = self.get("/api/v1/zones/context", qs)
            self.assertEqual(status, 200, body[:200])
            ctx = json.loads(body)
            self.assertEqual(ctx["map_id"], self.zm["map_id"])
            self.assertIsNone(ctx["features"]["zone_relvol"])
            self.assertIsNone(ctx["features"]["zone_poc_migration"])
            self.assertEqual(ctx["features"]["zone_data_ok"], 1.0)


if __name__ == "__main__":
    unittest.main()
