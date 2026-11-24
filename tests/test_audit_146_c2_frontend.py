"""1.46 audit, group C2_frontend (cross-file round): CHARTS data layer, App.tsx, CinematicMenu props, Apollo23 labels, dead brand / router code.

Each test runs one case of tests/js/audit146_c2_frontend.test.mjs (Node, the real react-dom/client on a minimal DOM stub with api.ts /
store.tsx and the heavy children of App.tsx mocked): measured MT5 server offset (VERIFIED only) and symbol tick_size / digits passed to the
CHARTS renderer, one onSelect listener per entry into CHARTS, cancelled FOREX hand-off does not navigate, retired OTC note on
#/menu?retired=otc (URL contract kept), no unused onSettings prop, Apollo23 labels on MODELS & BACKTEST and in Diagnostics, no unused
LEGACY_PRODUCT export and no write-only localStorage "mq.lastHash"."""
from __future__ import annotations

import shutil
import subprocess
import unittest

import _env

_JS = _env.ROOT / "tests" / "js" / "audit146_c2_frontend.test.mjs"
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
class TestFrontendC2Audit146(unittest.TestCase):
    def _case(self, case: str) -> None:
        r = _run(case)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])
        self.assertIn(f"{case} OK", r.stdout)

    def test_charts_server_offset(self):            # chunk_47#0
        self._case("charts_server_offset")

    def test_charts_symbol_tick_digits(self):       # chunk_47#9
        self._case("charts_symbol_tick_digits")

    def test_charts_onselect_unsubscribe(self):     # chunk_47#14
        self._case("charts_onselect_unsubscribe")

    def test_app_forex_handoff_cancel(self):        # chunk_45#1
        self._case("app_forex_handoff_cancel")

    def test_app_otc_retired_note(self):            # focus_X5#10
        self._case("app_otc_retired_note")

    def test_app_cinematic_no_onsettings(self):     # chunk_45#6
        self._case("app_cinematic_no_onsettings")

    def test_labels_apollo23(self):                 # focus_X5#6
        self._case("labels_apollo23")

    def test_dead_brand_and_last_hash(self):        # chunk_43#17
        self._case("dead_brand_and_last_hash")


if __name__ == "__main__":
    unittest.main()
