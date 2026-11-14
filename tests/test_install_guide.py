"""1.39 PDF guide "instalacja bota, modeli i trening" (tools/make_install_guide.py): every launcher, CLI command, family id, config key and
API endpoint named in the guide exists in the package, and the PDF builds (embedded DejaVu fonts, Polish characters)."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _env

ROOT = _env.ROOT
SRC = (ROOT / "tools" / "make_install_guide.py").read_text(encoding="utf-8")


class TestInstallGuide(unittest.TestCase):
    def test_launchers_exist(self):
        bats = sorted(set(re.findall(r"\b([0-9]{2}_[A-Z0-9_]+\.bat)", SRC)))
        self.assertGreater(len(bats), 20)
        missing = [b for b in bats if not (ROOT / b).exists()]
        self.assertEqual(missing, [])

    def test_cli_commands_are_valid(self):
        from masterquo.modelhub.families import _ORDER
        for fam in set(re.findall(r"--family ([A-Z_]+)", SRC)):
            self.assertIn(fam, _ORDER)
        for f in re.findall(r"\b(TS_ARIMA|TS_SARIMAX|VOL_GARCH|MICROSTRUCTURE|PAIR_COINT|STATARB|KALMAN_LS|BREAKOUT|TH_RF|TH_XGB|TH_SVM|SEQ_LSTM|SEQ_GRU|RL_PPO|NLP_SENTIMENT)\b", SRC):
            self.assertIn(f, _ORDER)
        cli = (ROOT / "backend" / "masterquo" / "modelhub" / "families" / "cli.py").read_text(encoding="utf-8")
        for c in set(re.findall(r"masterquo families ([a-z-]+)", SRC)):
            self.assertIn(f'"{c}"', cli, c)
        for prof in set(re.findall(r"--profile ([a-z]+)", SRC)):
            self.assertIn(prof, ("smoke", "research", "full"))
        main = (ROOT / "backend" / "masterquo" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn('["families"]', main)
        self.assertIn('["sh"]', main)
        self.assertIn('"pack-replay"', (ROOT / "backend" / "masterquo" / "sh" / "train_cli.py").read_text(encoding="utf-8"))
        self.assertIn("--garch-json", (ROOT / "backend" / "masterquo" / "sh" / "train_cli.py").read_text(encoding="utf-8"))
        for c in set(re.findall(r"masterquo trainhub ([a-z]+)", SRC)):
            self.assertIn(f"trainhub {c}", (ROOT / "32_CENTRUM_TRENINGU.bat").read_text(encoding="utf-8", errors="replace"))

    def test_config_keys_endpoints_and_reasons(self):
        from masterquo.config import AppConfig
        c = AppConfig()
        self.assertEqual(c.execution.start_mode, "AUTO_LIVE")
        self.assertTrue(c.execution.live_autobind)
        for k in ("risk_per_trade_pct", "max_total_open_risk_pct", "daily_loss_limit_pct", "max_drawdown_pct", "max_open_positions"):
            self.assertIn(k, SRC)
            self.assertTrue(hasattr(c.risk, k), k)
        app = (ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        for ep in set(re.findall(r"(/api/v1/[a-z0-9/\-]+)", SRC)):
            self.assertIn(f'"{ep}"', app, ep)
        modes = (ROOT / "backend" / "masterquo" / "execution" / "modes.py").read_text(encoding="utf-8")
        for r in ("PRIMARY_PATH_NOT_SELECTED", "RISK_LIMITS_NOT_CONFIGURED", "NEW_ENTRIES_STOPPED", "LIVE_AUTOBIND", "ACCOUNT_DIFFERS_FROM_CONFIRMED_"):
            self.assertIn(r, SRC)
            self.assertIn(r, modes)
        self.assertIn("GARCH_NOT_READY", (ROOT / "backend" / "masterquo" / "sh" / "pack" / "detectors.py").read_text(encoding="utf-8"))

    @unittest.skipUnless(importlib.util.find_spec("reportlab"), "reportlab not installed")
    def test_pdf_builds(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "make_install_guide.py"), "--out", d, "--shots", str(Path(d) / "none")],
                               capture_output=True, text=True, timeout=300)
            if "brak czcionek DejaVu" in (r.stdout + r.stderr):
                self.skipTest("DejaVu fonts not installed")
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            pdf = Path(d) / "Instrukcja_Instalacja_Modele_Trening_PepeMarketWizard.pdf"
            data = pdf.read_bytes()
            self.assertTrue(data.startswith(b"%PDF"))
            self.assertGreater(len(data), 50_000)
            self.assertIn(b"DejaVuSans", data)


if __name__ == "__main__":
    unittest.main()
