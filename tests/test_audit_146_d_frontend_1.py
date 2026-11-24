"""1.46 audit, group D_frontend_1: api.ts LiveSocket, Settings / Power dialogs, leverage limit, error boundary, 1.41 panels, appearance layer,
cinematic menu (React wrapper + menuEngine) and menu shaders.

Each test runs one case of tests/js/audit146_d_frontend_1.test.mjs (Node, the real react-dom/client on a minimal DOM stub with api.ts /
store.tsx mocked; menuEngine.ts on an event-only element stub with the CPU renderer or a failing WebGL context and a manual RAF queue):
reconnect timer cancelled by LiveSocket.stop(), first-run "Zakończ konfigurację" only after a successful save, failed STOP reported,
leverage <select> value = saved value, renderer error keeps STOP visible and retries on the CPU renderer, cancellable FOREX hand-off,
menu shortcuts not acting under the system drawer, AbortError of play() after skipping, dead intro-3D / OTC / appearance code removed,
Settings load / agent errors shown, S01-S12 MANUAL choices, "Menu główne" reset on #/menu, missing research-loop data not shown as 0,
no pow() with a negative base in the GLSL shaders."""
from __future__ import annotations

import shutil
import subprocess
import unittest

import _env

_JS = _env.ROOT / "tests" / "js" / "audit146_d_frontend_1.test.mjs"
_NM = _env.ROOT / "frontend" / "node_modules"


def _node_ok() -> bool:
    if not shutil.which("node") or not (_NM / "react").is_dir() or not (_NM / "react-dom").is_dir() or not (_NM / "typescript").is_dir():
        return False
    r = subprocess.run(["node", "-e", "process.exit(typeof require('node:module').registerHooks === 'function' ? 0 : 1)"], check=False,
                       capture_output=True, timeout=60)
    return r.returncode == 0


def _run(case: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_JS), case], check=False, capture_output=True, text=True,
                          timeout=180, cwd=str(_env.ROOT))


@unittest.skipUnless(_node_ok(), "node >= 22.15 with frontend/node_modules (react, react-dom, typescript) required")
class TestFrontend1Audit146(unittest.TestCase):
    def _case(self, case: str) -> None:
        r = _run(case)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])
        self.assertIn(f"{case} OK", r.stdout)

    def test_live_socket_stop_cancels_reconnect(self):   # chunk_43#6
        self._case("live_socket_stop_cancels_reconnect")

    def test_api_dead_exports(self):                     # chunk_43#17 (api.ts part)
        self._case("api_dead_exports")

    def test_settings_finish_failed_keeps_open(self):    # chunk_43#2
        self._case("settings_finish_failed_keeps_open")

    def test_power_stop_failure_reported(self):          # chunk_43#3
        self._case("power_stop_failure_reported")

    def test_leverage_select_matches_saved(self):        # chunk_43#7
        self._case("leverage_select_matches_saved")

    def test_menu_renderer_error_state(self):            # chunk_45#0
        self._case("menu_renderer_error_state")

    def test_menu_forex_handoff_cancel(self):            # chunk_45#1 (engine part)
        self._case("menu_forex_handoff_cancel")

    def test_menu_shortcuts_scoped(self):                # chunk_45#2
        self._case("menu_shortcuts_scoped")

    def test_menu_visibility_abort(self):                # chunk_45#3
        self._case("menu_visibility_abort")

    def test_menu_dead_state_removed(self):              # chunk_45#9, chunk_45#10
        self._case("menu_dead_state_removed")

    def test_menu_shaders_no_negative_pow(self):         # chunk_45#4, chunk_45#8
        self._case("menu_shaders_no_negative_pow")

    def test_appearance_no_eager_fetch(self):            # chunk_43#11
        self._case("appearance_no_eager_fetch")

    def test_settings_load_error_retry(self):            # chunk_43#13
        self._case("settings_load_error_retry")

    def test_settings_manual_strategy_options(self):     # chunk_43#14
        self._case("settings_manual_strategy_options")

    def test_error_boundary_menu_reset(self):            # chunk_43#16
        self._case("error_boundary_menu_reset")

    def test_baskets_otc_removed(self):                  # chunk_43#12, focus_X2#20
        self._case("baskets_otc_removed")

    def test_research_loop_unavailable(self):            # chunk_43#15
        self._case("research_loop_unavailable")

    def test_cinematic_menu_wrapper(self):               # chunk_45#5, chunk_45#6, chunk_45#7 (+ chunk_45#1 signal forwarding)
        self._case("cinematic_menu_wrapper")


if __name__ == "__main__":
    unittest.main()
