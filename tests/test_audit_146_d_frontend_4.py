"""1.46 audit, group D_frontend_4: licence generator / panel / gate, training centre, system drawer, TraderLifeGame, store, Studio header, theme.

Each test runs one case of tests/js/audit146_d_frontend_4.test.mjs (Node, the real react-dom/client on a minimal DOM stub, api.ts mocked):
crafted PMW1 key in "Sprawdź klucz", TraderLifeGame decimal comma / failed saves / rule compliance / simulator resume / meta error,
seq-aware /api/v1/state snapshot and start-up retry of the store, licence re-check message, training-queue remove feedback, display name
(Apollo23) on the licence screen, system drawer and Studio, theme migration persistence / preset base tokens / hsl hue / chart_overrides null."""
from __future__ import annotations

import shutil
import subprocess
import unittest

import _env

_JS = _env.ROOT / "tests" / "js" / "audit146_d_frontend_4.test.mjs"
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
class TestFrontend4Audit146(unittest.TestCase):
    def _case(self, case: str) -> None:
        r = _run(case)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])
        self.assertIn(f"{case} OK", r.stdout)

    def test_lic_check_object_user(self):            # chunk_48#0
        self._case("lic_check_object_user")

    def test_tlg_risk_comma(self):                   # chunk_48#1
        self._case("tlg_risk_comma")

    def test_tlg_sim_sl_comma(self):                 # chunk_48#2
        self._case("tlg_sim_sl_comma")

    def test_tlg_act_failure_keeps_form(self):       # chunk_48#3
        self._case("tlg_act_failure_keeps_form")

    def test_store_full_not_older(self):             # chunk_43#4
        self._case("store_full_not_older")

    def test_store_startup_retry(self):              # chunk_43#5
        self._case("store_startup_retry")

    def test_license_panel_refresh_fail(self):       # chunk_48#8
        self._case("license_panel_refresh_fail")

    def test_system_drawer_label(self):              # focus_X5#6
        self._case("system_drawer_label")

    def test_training_remove_feedback(self):         # chunk_48#7
        self._case("training_remove_feedback")

    def test_tlg_rule_compliance_clear(self):        # chunk_48#4
        self._case("tlg_rule_compliance_clear")

    def test_tlg_sim_resume(self):                   # chunk_48#5
        self._case("tlg_sim_resume")

    def test_tlg_meta_error(self):                   # chunk_48#6
        self._case("tlg_meta_error")

    def test_license_gate_brand(self):               # chunk_43#8
        self._case("license_gate_brand")

    def test_studio_brand(self):                     # chunk_43#9
        self._case("studio_brand")

    def test_theme_gold_migration_persisted(self):   # chunk_44#4
        self._case("theme_gold_migration_persisted")

    def test_theme_missing_tokens_from_preset(self): # chunk_44#5
        self._case("theme_missing_tokens_from_preset")

    def test_theme_parse_color_hsl(self):            # chunk_44#6
        self._case("theme_parse_color_hsl")

    def test_theme_parse_file_null_overrides(self):  # chunk_44#7 (hidden TypeError of the kept import API)
        self._case("theme_parse_file_null_overrides")


if __name__ == "__main__":
    unittest.main()
