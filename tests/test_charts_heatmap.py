"""CHARTS · HEATMAPA (mapa płynności w stylu Bookmap): historia arkusza MT5 z archiwum bota (book_snapshots) w siatce czasu, bieżący
arkusz (COB), brak bąbli transakcji dla arkusza brokera, kubełek bez snapshotów = przerwa (nie zero), skończone kubełki z pamięci
podręcznej. Na końcu trasa GET /api/v1/orderflow/mt5/heatmap na serwerze demo (syntetyczny terminal zapisuje arkusz co 1 s)."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import unittest

import _env

from masterquo.orderflow import depth_history as DH


def snap(t, mid, sizes_b=(1, 2), sizes_a=(3, 4), gap=0.1):
    return (t, [[round(mid - 0.05 - k * gap, 2), q] for k, q in enumerate(sizes_b)],
            [[round(mid + 0.05 + k * gap, 2), q] for k, q in enumerate(sizes_a)])


class TestDepthHistory(unittest.TestCase):
    def test_auto_row_is_level_spacing_not_below_tick(self):
        self.assertEqual(DH.auto_row([[100.0, 1], [99.9, 1], [99.8, 1]], [[100.1, 1], [100.2, 1]], 0.01), 0.1)
        self.assertEqual(DH.auto_row([[100.0, 1], [99.999, 1]], [[100.1, 1]], 0.01), 0.01)
        self.assertEqual(DH.auto_row([], [], 0.05), 0.05)

    def test_bucket_mean_counts_missing_level_as_zero_and_gap_is_omitted(self):
        s = [(0.5, [[99.95, 2.0]], [[100.05, 4.0]]),
             (1.5, [[99.95, 4.0]], [[100.15, 6.0]]),          # 100.05 missing in this snapshot -> 0
             (7.5, [[99.95, 1.0]], [[100.05, 1.0]])]          # buckets 1..2 empty -> omitted
        out = DH.columns(s, 0.0, 10.0, 4, 0.1)
        self.assertEqual([c["t"] for c in out], [0.0, 7.5])
        c0 = dict((p, q) for p, q in out[0]["cells"])
        self.assertAlmostEqual(c0[99.9], 3.0)                 # row_of(99.95, 0.1) = 99.9 -> (2 + 4) / 2
        self.assertAlmostEqual(c0[100.0], 2.0)                # (4 + 0) / 2
        self.assertAlmostEqual(c0[100.1], 3.0)                # (0 + 6) / 2
        self.assertEqual((out[0]["n"], out[0]["bid"], out[0]["ask"]), (2, 99.95, 100.15))   # best bid / ask = last snapshot
        self.assertTrue(all(q > 0 for c in out for _, q in c["cells"]))

    def test_grid_is_epoch_aligned_and_contains_now(self):
        t0, t1, step = DH.grid(1000.7, 60, 20)
        self.assertEqual((t0, t1, step), (942.0, 1002.0, 3.0))
        self.assertTrue(t0 <= 1000.7 < t1)

    def test_cache_reads_only_unfinished_buckets(self):
        calls = []
        store = [snap(float(t), 100 + (t % 7) * 0.1) for t in range(0, 120)]

        def fetch(a, b):
            calls.append((a, b))
            return [x for x in store if a <= x[0] <= b]

        c = DH.ColumnCache()
        t0, _, step = DH.grid(100.0, 60, 20)
        first = c.build(("X", step, 0.1), t0, step, 20, 0.1, fetch, finished_before=99.0)
        self.assertEqual(calls[0][0], t0)
        again = c.build(("X", step, 0.1), t0, step, 20, 0.1, fetch, finished_before=99.0)
        self.assertGreaterEqual(calls[1][0], 96.0)            # only the live bucket(s) are read again
        self.assertEqual([x["cells"] for x in first[:-2]], [x["cells"] for x in again[:-2]])
        self.assertEqual(c.reads, 2)

    def test_status_reasons_and_no_trade_bubbles(self):
        r = DH.heatmap([], t0=0, t1=60, cols=20, row=0.1, ref=None, book={"status": "NO_DATA", "reason": "market_book_add odrzucone – brak DOM dla symbolu"})
        self.assertEqual((r["status"], r["reason"]), ("NO_DATA", "market_book_add odrzucone – brak DOM dla symbolu"))
        cols = DH.columns([snap(10.0, 100)], 0, 60, 20, 0.1)
        old = DH.heatmap(cols, t0=0, t1=60, cols=20, row=0.1, ref={"t": 10.0, "bids": [[99.95, 1]], "asks": [[100.05, 3]]}, now=60, max_age_s=5)
        self.assertEqual((old["status"], old["reason"], old["dom"]["fresh"]), ("STALE", "BOOK_AGE_50S", False))
        ok = DH.heatmap(cols, t0=0, t1=60, cols=20, row=0.1, ref={"t": 59.0, "bids": [[99.95, 1]], "asks": [[100.05, 3]]}, now=60)
        self.assertEqual(ok["status"], "READY")
        self.assertEqual(ok["trades"]["status"], "NOT_AVAILABLE")
        self.assertEqual(ok["mode"], "READ_ONLY")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestHeatAdapters(unittest.TestCase):
    def test_adapters_and_colour_scale(self):
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "charts_heat.test.mjs")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIn("charts heat OK", r.stdout)


class TestHeatmapRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PMW_BOOTSTRAP"] = "0"
        from _demo_server import Server
        cls.S = Server
        Server.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_route_returns_archived_book_grid(self):
        body, deadline = None, time.time() + 60
        while time.time() < deadline:
            code, body = self.S.call("/api/v1/orderflow/mt5/heatmap?seconds=300&cols=100")
            self.assertEqual(code, 200, body)
            if body["status"] == "READY" and body["snapshots"] >= 3 and body["bars"]:
                break
            time.sleep(1.0)
        self.assertEqual(body["status"], "READY", body.get("reason"))
        self.assertEqual((body["cols"], body["step_s"]), (100, 3.0))
        self.assertGreater(body["row_size"], 0)
        self.assertTrue(body["columns"] and all(c["cells"] and c["bid"] < c["ask"] for c in body["columns"]))
        self.assertTrue(body["dom"]["bids"] and body["dom"]["asks"] and body["dom"]["fresh"])
        self.assertEqual(body["trades"]["status"], "NOT_AVAILABLE")
        self.assertTrue(body["bars"])                                     # M1 tick volume panel
        code, again = self.S.call("/api/v1/orderflow/mt5/heatmap?seconds=300&cols=100")
        first = {c["t"]: c for c in body["columns"]}
        finished = [c for c in again["columns"] if c["t"] in first and c["t1"] <= body["now"] - 2]
        self.assertTrue(all(c == first[c["t"]] for c in finished))         # finished buckets do not change between polls


if __name__ == "__main__":
    unittest.main()
