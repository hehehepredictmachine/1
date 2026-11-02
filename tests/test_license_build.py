"""License System v1 - build configurations: OWNER packages never contain the license server; the License API package contains
no keys / database / env file; a CLIENT package stamped from an OWNER package (folder or Windows-app shaped) has a configured
CLIENT edition.json, no owner module, no license server, recomputed manifests, and refuses any private key / admin secret."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

import _env
from _env import TempData

sys.path.insert(0, str(_env.ROOT / "tools"))
import build_release  # noqa: E402
import stamp_client_edition as S  # noqa: E402

PUB = base64.b64encode(bytes(range(32))).decode()


def owner_zip(path: Path, top: str, extra: dict | None = None, desktop: bool = False) -> Path:
    files = {"edition.json": json.dumps({"edition": "OWNER"}).encode(), "backend/masterquo/license/owner.py": b"# owner\n",
             "backend/masterquo/license/guard.py": b"# guard\n", "backend/masterquo/version.py": b'APP_VERSION = "1.27.0"\n',
             "license_server/pmw_license/app.py": b"# server\n", **(extra or {})}
    man = "# PepeMarketWizard 1.27.0 (OWNER)\n" + "\n".join(f"{hashlib.sha256(v).hexdigest()}  {k}" for k, v in sorted(files.items())) + "\n"
    files["MANIFEST_SHA256.txt"] = man.encode()
    if desktop:
        files["PepeMarketWizardDesktop.exe"] = b"MZ"
        dm = "\n".join(f"{hashlib.sha256(v).hexdigest()}  {k}" for k, v in sorted(files.items())) + "\n"
        files["MANIFEST_DESKTOP_SHA256.txt"] = ("# desktop\n" + dm).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(top + k, v)
    path.write_bytes(buf.getvalue())
    return path


class TestBuilds(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.tmp = Path(self.td.dir)

    def tearDown(self):
        self.td.close()

    def test_owner_package_selection_and_server_package(self):
        files = build_release.tracked()
        self.assertFalse([f for f in files if f.startswith("license_server/")])           # the License API never ships in the bot
        self.assertIn("backend/masterquo/license/guard.py", files)
        self.assertIn("tools/stamp_client_edition.py", files)
        self.assertEqual(json.loads((_env.ROOT / "edition.json").read_text(encoding="utf-8"))["edition"], "OWNER")
        srv = build_release.server_files()
        self.assertTrue(all(f.startswith("license_server/") or f.startswith("docs/") for f in srv))
        self.assertFalse([f for f in srv if f.endswith((".pem", ".db", ".env", ".sqlite"))])
        build_release.scan([f for f in srv if (_env.ROOT / f).exists()])                     # no private key / secret assignment

    def run_stamp(self, src: Path, out: Path) -> int:
        return S.main(["--license-url", "https://licencje.example.pl", "--public-key", PUB, "--source", str(src), "--out", str(out), "--yes"])

    def test_stamp_folder_package(self):
        src = owner_zip(self.tmp / "owner.zip", "PepeMarketWizard/")
        out = self.tmp / "client.zip"
        self.assertEqual(self.run_stamp(src, out), 0)
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            ed = json.loads(z.read("PepeMarketWizard/edition.json"))
            man = z.read("PepeMarketWizard/MANIFEST_SHA256.txt").decode()
            edition_bytes = z.read("PepeMarketWizard/edition.json")
        self.assertEqual((ed["edition"], ed["license_api"], ed["public_key"], ed["kid"]),
                         ("CLIENT", "https://licencje.example.pl", PUB, hashlib.sha256(bytes(range(32))).hexdigest()[:16]))
        self.assertNotIn("PepeMarketWizard/backend/masterquo/license/owner.py", names)
        self.assertFalse([n for n in names if "license_server/" in n])
        self.assertIn(f"{hashlib.sha256(edition_bytes).hexdigest()}  edition.json", man)
        self.assertNotIn("owner.py", man)
        self.assertTrue((self.tmp / "client.zip.sha256").exists())

    def test_stamp_desktop_package_and_its_manifests(self):
        src = owner_zip(self.tmp / "desk.zip", "PepeMarketWizard_Desktop/", desktop=True)
        out = self.tmp / "client_desk.zip"
        self.assertEqual(self.run_stamp(src, out), 0)
        with zipfile.ZipFile(out) as z:
            m = z.read("PepeMarketWizard_Desktop/MANIFEST_SHA256.txt")
            d = z.read("PepeMarketWizard_Desktop/MANIFEST_DESKTOP_SHA256.txt").decode()
            self.assertIn("PepeMarketWizard_Desktop/PepeMarketWizardDesktop.exe", z.namelist())
        self.assertIn(f"{hashlib.sha256(m).hexdigest()}  MANIFEST_SHA256.txt", d)
        self.assertNotIn("license_server", d)

    def test_secrets_refused_and_bad_input(self):
        leak = b"-----BEGIN " + b"PRIVATE KEY-----\nMC4CAQ\n"          # assembled at run time: the release secret scan stays strict
        src = owner_zip(self.tmp / "leak.zip", "PepeMarketWizard/", extra={"docs/oops.txt": leak})
        self.assertEqual(self.run_stamp(src, self.tmp / "x.zip"), 3)
        self.assertFalse((self.tmp / "x.zip").exists())
        src2 = owner_zip(self.tmp / "leak2.zip", "PepeMarketWizard/", extra={"data/licenses.db": b"x"})
        self.assertEqual(self.run_stamp(src2, self.tmp / "y.zip"), 3)
        self.assertEqual(S.main(["--license-url", "http://licencje.example.pl", "--public-key", PUB, "--source", str(src), "--yes"]), 2)
        self.assertEqual(S.main(["--license-url", "https://licencje.example.pl", "--public-key", base64.b64encode(b"short").decode(),
                                 "--source", str(src), "--yes"]), 2)

    def test_public_key_fetched_from_the_server(self):
        from test_license_server import Clock, Server
        srv = Server(self.tmp / "srv", Clock())
        try:
            pub, kid = S.fetch_public_key(srv.base)
            self.assertEqual((pub, kid), (srv.signer.public_b64, srv.signer.kid))
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
