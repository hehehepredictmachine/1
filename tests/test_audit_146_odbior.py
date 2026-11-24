"""1.46 ETAP 4 (odbiór): usterki wykryte przy budowie paczek.

- backend/masterquo/exports/core.py (eksportery z ETAPU 3) zawierał dosłownie nagłówek klucza prywatnego właściciela (wzorzec redakcji),
  więc `build_release.py --edition client` odmawiał zbudowania paczki klienta (tools/verify_release.py CLIENT_MARKERS: kod generatora
  licencji w paczce klienta). Redakcja klucza w eksportach musi przy tym nadal działać.
"""
from __future__ import annotations

import importlib.util
import subprocess
import unittest

import _env  # noqa: F401
from _env import ROOT
from masterquo.exports import core as EC


def _verify_release():
    spec = importlib.util.spec_from_file_location("verify_release_odbior", ROOT / "tools" / "verify_release.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# the header is assembled at run time so that this file never carries it literally either
HEADER = "PMW-OWNER-ED25519-" + "PRIVATE-KEY v1"


class TestClientPackageMarkers(unittest.TestCase):
    def test_backend_files_of_the_client_package_carry_no_owner_marker(self):
        vr = _verify_release()
        files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "backend"], capture_output=True, text=True, check=True).stdout.split()
        rels = [f for f in files if f.endswith(".py") and f not in vr.OWNER_ONLY]
        self.assertIn("backend/masterquo/exports/core.py", rels)
        bad = [p for p in vr.client_problems(lambda r: (ROOT / r).read_bytes(), rels) if "kod generatora" in p]
        self.assertEqual(bad, [])

    def test_owner_key_is_still_redacted_in_exports(self):
        seed = "ab" * 32
        red = EC.Redactor([])
        for blob in (f"{HEADER}\nseed: {seed}\n", f"{HEADER}\r\nseed: {seed}", f'"{HEADER}\\nseed: {seed}"'):
            out = red.text(blob)
            self.assertNotIn(seed, out, blob)
            self.assertIn(EC.REDACTED, out)
            self.assertTrue(red.leaks(blob))


if __name__ == "__main__":
    unittest.main()
