"""Release tooling: build without .git from the explicit list of MANIFEST_SHA256.txt and tools/verify_release.py: ZIP-slip paths,
manifest hashes, forbidden files, secrets, no element of the license system removed in 1.30, the .sha256 sidecar.
Temporary trees only - the repository and release/ are not touched."""
from __future__ import annotations

import contextlib
import hashlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import _env

sys.path.insert(0, str(_env.ROOT / "tools"))
import build_release as BR  # noqa: E402
import verify_release as VR  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class TreeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_root = BR.ROOT
        BR.ROOT = self.root

    def tearDown(self):
        BR.ROOT = self.old_root
        self.tmp.cleanup()

    def put(self, rel: str, data: bytes = b"x\n") -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def manifest(self, rels: list[str], extra_lines: str = "") -> None:
        lines = [f"{sha((self.root / r).read_bytes())}  {r}" for r in rels]
        (self.root / "MANIFEST_SHA256.txt").write_text("# test\n" + "\n".join(lines) + "\n" + extra_lines, encoding="utf-8")


class TestBuildWithoutGit(TreeCase):
    def test_manifest_list_is_used_without_git(self):
        for r in ("backend/masterquo/a.py", "docs/b.md", "frontend/dist/index.html", "START_TUTAJ_PL.md"):
            self.put(r)
        self.manifest(["backend/masterquo/a.py", "docs/b.md", "frontend/dist/index.html", "START_TUTAJ_PL.md"])
        self.put("backend/masterquo/new_untracked.py")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            files = BR.tracked()
        self.assertEqual(files, ["START_TUTAJ_PL.md", "backend/masterquo/a.py", "docs/b.md", "frontend/dist/index.html"])
        self.assertIn("brak .git", out.getvalue())
        self.assertIn("new_untracked.py", out.getvalue())                       # reported, not packed

    def test_incomplete_copy_or_unsafe_line_stops_the_build(self):
        self.put("backend/a.py")
        self.manifest(["backend/a.py"], extra_lines=f"{'0' * 64}  backend/missing.py\n")
        with self.assertRaises(SystemExit) as cm:
            BR.manifest_list()
        self.assertIn("niekompletna", str(cm.exception))
        for bad in ("../evil.py", "/etc/passwd", "C:/x.py", "a\\b.py", "backend/../../x.py"):
            self.manifest(["backend/a.py"], extra_lines=f"{'0' * 64}  {bad}\n")
            with self.assertRaises(SystemExit, msg=bad):
                BR.manifest_list()
        (self.root / "MANIFEST_SHA256.txt").unlink()
        with self.assertRaises(SystemExit):
            BR.manifest_list()

    def test_license_server_folder_never_enters_the_package(self):
        for r in ("backend/a.py", "license_server/pmw_license/app.py"):
            self.put(r)
        self.manifest(["backend/a.py"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(BR.tracked(), ["backend/a.py"])


class TestVerifyRelease(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name: str, entries: dict[str, bytes], manifest: bool = True, sidecar: bool = True, desktop: bool = False) -> Path:
        files = dict(entries)
        if manifest:
            files["MANIFEST_SHA256.txt"] = ("# m\n" + "\n".join(f"{sha(b)}  {k}" for k, b in files.items()) + "\n").encode()
        if desktop:
            files["MANIFEST_DESKTOP_SHA256.txt"] = ("# d\n" + "\n".join(f"{sha(b)}  {k}" for k, b in files.items()) + "\n").encode()
        p = self.dir / name
        with zipfile.ZipFile(p, "w") as z:
            for k, b in files.items():
                z.writestr(k if k.startswith(("/", "..")) or "\\" in k else "PMW/" + k, b)
        if sidecar:
            (self.dir / (name + ".sha256")).write_text(f"{sha(p.read_bytes())}  {name}\n", encoding="utf-8")
        return p

    def test_good_package_passes(self):
        p = self.make("ok.zip", {"backend/a.py": b"print(1)\n", "docs/x.md": b"# doc\n"}, desktop=True)
        self.assertEqual(VR.check_zip(p), [])

    def test_zip_slip_and_unsafe_names(self):
        for bad in ("../evil.py", "/abs.py", "PMW/../../x.py", "PMW\\win.py"):
            p = self.make(f"slip{abs(hash(bad))}.zip", {"backend/a.py": b"1\n", bad: b"2\n"}, manifest=False)
            self.assertTrue(VR.check_zip(p, "PMW/"), bad)

    def test_manifest_mismatch_sidecar_and_forbidden(self):
        p = self.make("m.zip", {"backend/a.py": b"1\n"})
        with zipfile.ZipFile(p, "a") as z:                                    # a file changed after the manifest was written
            z.writestr("PMW/backend/b.py", b"2\n")
            z.writestr("PMW/data/config.json", b"{}")
            z.writestr("PMW/license_owner_key.local.json", b"{}")
            z.writestr("PMW/backend/k.txt", b"-----BEGIN " + b"PRIVATE KEY-----\nabc\n")      # split: the packaged test must not trip the scan
        probs = " | ".join(VR.check_zip(p))
        self.assertIn(".sha256 nie zgadza", probs)
        self.assertIn("data/config.json: plik zabroniony", probs)
        self.assertIn("license_owner_key.local.json: plik zabroniony", probs)
        self.assertIn("PRIVATE_KEY", probs)
        p2 = self.make("m2.zip", {"backend/a.py": b"1\n"}, sidecar=False)
        self.assertIn("brak pliku .sha256", VR.check_zip(p2))
        p3 = self.make("m3.zip", {"backend/a.py": b"1\n"}, desktop=True)
        with zipfile.ZipFile(p3, "a") as z:
            z.writestr("PMW/extra.bin", b"\0\1")
        (self.dir / "m3.zip.sha256").write_text(f"{sha(p3.read_bytes())}  m3.zip\n", encoding="utf-8")
        self.assertTrue(any("spoza manifestu" in x for x in VR.check_zip(p3)))

    def test_bundled_runtime_files_are_not_secrets_but_are_scanned(self):
        ok = self.make("rt.zip", {"runtime/python/Lib/secrets.py": b"# stdlib\n", "runtime/python/Lib/site-packages/certifi/cacert.pem":
                                  b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"})
        self.assertEqual(VR.check_zip(ok), [])
        bad = self.make("rt2.zip", {"runtime/python/x.pem": b"-----BEGIN " + b"PRIVATE KEY-----\nabc\n", "data/secrets.dpapi.json": b"{}",
                                    "secrets.json": b"{}"})
        probs = " | ".join(VR.check_zip(bad))
        self.assertIn("PRIVATE_KEY", probs)
        self.assertIn("data/secrets.dpapi.json: plik zabroniony", probs)
        self.assertIn("secrets.json: plik zabroniony", probs)

    def test_removed_license_system_is_refused(self):
        for extra in ({"backend/masterquo/license/guard.py": b"# old\n"}, {"license_server/pmw_license/app.py": b"# old\n"},
                      {"edition.json": b'{"edition": "CLIENT"}'}):
            p = self.make(f"old{abs(hash(str(extra)))}.zip", {"backend/a.py": b"1\n", **extra})
            self.assertTrue(any("usuniętego systemu licencji" in x for x in VR.check_zip(p)), extra)
        self.assertEqual(VR.check_zip(self.make("clean.zip", {"backend/a.py": b"1\n"})), [])


if __name__ == "__main__":
    unittest.main()
