"""1.46 audit, group B_frontend_2: FOREX scene, usePoll, SIGNALS / MODELS screens, CHARTS data hook, chart zone primitives, FOREX engine.

Each test runs one case of tests/js/audit146_b_frontend_2.test.mjs (Node, real react-dom/client in a minimal DOM stub, api / store / router
mocked): static (no WebGL) and lost-context mode of ForexScene, MODEL B bar closes, stale usePoll answers, signal consensus / prediction
matching / lifecycle sets / mode gate / SH fields, model versions and the SH replay report, BTC timeframes, bar-close reloads, CHARTS
listeners, S01-S12 details from the list, zones / boxes / markers between candles, dead code."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest

import _env

_JS = _env.ROOT / "tests" / "js" / "audit146_b_frontend_2.test.mjs"


def _run(case: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "TZ": "Europe/Warsaw"}
    return subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_JS), case], check=False, capture_output=True, text=True,
                          timeout=180, env=env, cwd=str(_env.ROOT))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestForexFrontend146(unittest.TestCase):
    def _case(self, case: str) -> None:
        r = _run(case)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])
        self.assertIn(f"{case} OK", r.stdout)

    def test_forex_static_interactive(self):        # chunk_46#10
        self._case("forex_static_interactive")

    def test_forex_context_lost_static(self):       # chunk_46#11
        self._case("forex_context_lost_static")

    def test_forex_model_b_bar_close(self):         # chunk_46#12 (MODEL B)
        self._case("forex_model_b_bar_close")

    def test_forex_screenref_removed(self):         # chunk_46#17
        self._case("forex_screenref_removed")

    def test_usepoll_stale_path(self):              # chunk_46#5
        self._case("usepoll_stale_path")

    def test_signals_agree_flat(self):              # chunk_46#1
        self._case("signals_agree_flat")

    def test_signals_pred_match(self):              # chunk_46#2
        self._case("signals_pred_match")

    def test_signals_status_sets(self):             # chunk_46#6
        self._case("signals_status_sets")

    def test_signals_mode_gate(self):               # chunk_46#7
        self._case("signals_mode_gate")

    def test_signals_sh_fields(self):               # chunk_46#8
        self._case("signals_sh_fields")

    def test_models_versions_case(self):            # chunk_46#3
        self._case("models_versions_case")

    def test_models_backtest_report(self):          # chunk_46#4
        self._case("models_backtest_report")

    def test_charts_btc_tf_unsupported(self):       # chunk_46#9
        self._case("charts_btc_tf_unsupported")

    def test_charts_bar_close_once(self):           # chunk_46#12 (CHARTS)
        self._case("charts_bar_close_once")

    def test_charts_onselect_unsubscribe(self):     # chunk_46#13
        self._case("charts_onselect_unsubscribe")

    def test_charts_legacy_from_list(self):         # chunk_46#14
        self._case("charts_legacy_from_list")

    def test_zones_between_candles(self):           # chunk_44#0
        self._case("zones_between_candles")

    def test_boxes_between_candles(self):           # chunk_44#1
        self._case("boxes_between_candles")

    def test_engine_dead_code(self):                # chunk_46#16
        self._case("engine_dead_code")


if __name__ == "__main__":
    unittest.main()
