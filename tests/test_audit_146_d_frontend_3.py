"""1.46 audit, group D_frontend_3: CHARTS renderer (frontend/src/features/forex/screens/charts/chartsRender.ts).

Each test runs one case of tests/js/audit146_d_frontend_3.test.mjs (Node, minimal DOM stub, TZ=Europe/Warsaw):
time per candle / D1 trading day / server offset, engine AVWAP anchor, mock layers unavailable in production, canvas resize, Kronos user choice,
TF buttons, null fields in the plan card, symbol tick, no closed candle, VISIBLE request parameters / back-off, TP labels, announcements,
onSelect unsubscribe, focus kept, common crosshair, dead code."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest

import _env

_JS = _env.ROOT / "tests" / "js" / "audit146_d_frontend_3.test.mjs"


def _run(case: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "TZ": "Europe/Warsaw"}
    return subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_JS), case], check=False, capture_output=True, text=True,
                          timeout=120, env=env, cwd=str(_env.ROOT))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestChartsRender146(unittest.TestCase):
    def _case(self, case: str) -> None:
        r = _run(case)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])
        self.assertIn(f"{case} OK", r.stdout)

    def test_time_local_per_candle(self):            # chunk_47#0
        self._case("time_local_per_candle")

    def test_time_d1_and_server(self):               # chunk_47#0
        self._case("time_d1_and_server")

    def test_avwap_session_anchor(self):             # chunk_47#1
        self._case("avwap_session_anchor")

    def test_mock_layers_unavailable_in_prod(self):  # chunk_47#2, #3, #4
        self._case("mock_layers_unavailable_in_prod")

    def test_canvas_height_follows_view(self):       # chunk_47#5
        self._case("canvas_height_follows_view")

    def test_kronos_user_choice_kept(self):          # chunk_47#6
        self._case("kronos_user_choice_kept")

    def test_tf_buttons_initial(self):               # chunk_47#7
        self._case("tf_buttons_initial")

    def test_card_null_fields(self):                 # chunk_47#8
        self._case("card_null_fields")

    def test_svp_tick_from_vm(self):                 # chunk_47#9
        self._case("svp_tick_from_vm")

    def test_svp_no_closed_candle(self):             # chunk_47#10
        self._case("svp_no_closed_candle")

    def test_vpa_request_params_and_backoff(self):   # chunk_47#11
        self._case("vpa_request_params_and_backoff")

    def test_tp_label_missing(self):                 # chunk_47#12
        self._case("tp_label_missing")

    def test_announce_only_new(self):                # chunk_47#13
        self._case("announce_only_new")

    def test_onselect_unsubscribe(self):             # chunk_47#14
        self._case("onselect_unsubscribe")

    def test_focus_kept_on_refresh(self):            # chunk_47#15
        self._case("focus_kept_on_refresh")

    def test_sync_unavailable_prod(self):            # chunk_47#16
        self._case("sync_unavailable_prod")

    def test_dead_code_removed(self):                # chunk_47#17
        self._case("dead_code_removed")


if __name__ == "__main__":
    unittest.main()
