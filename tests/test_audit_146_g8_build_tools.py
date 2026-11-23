"""1.46 audit (group G8_build_tools) - regression tests for tools/build_desktop.py, tools/build_release.py, tools/verify_release.py.

Temporary trees and archives only: the repository, release/ and build/ are never touched; Go, NuGet, PyPI and uv are not called (the
build steps that need them are replaced by fakes). Secret-shaped strings are assembled at run time, so this file never trips the secret
scan of the packages it ships in."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import _env

sys.path.insert(0, str(_env.ROOT / "tools"))
import build_desktop as BD
import build_release as BR
import verify_release as VR

SEED = "0f1e2d3c4b5a69788796a5b4c3d2e1f00112233445566778899aabbccddeeff7"
KEY_TEXT = "PMW-OWNER-ED25519-" + "PRIVATE-KEY v1\n" + "seed: " + SEED + "\npublic: " + "ab" * 32 + "\n"
TG_TOKEN = "987654" + "321:AAH" + "q7Lr2xVb9KpWm3Tz8YcNd4Fg6Hj1Qs5Ue"           # Telegram-shaped, not a real token
PEM = "-----BEGIN " + "PRIVATE KEY-----\nabc\n"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class ZipCase(unittest.TestCase):
    """Archives in a temp folder, same layout as tests/test_release_tools.py (top folder PMW/, manifest + .sha256 sidecar)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.n = 0
        env = mock.patch.dict(os.environ, {"PMW_OWNER_DIR": str(self.dir / "no_owner_key_here")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, entries: dict[str, bytes], name: str | None = None, manifest: bool = True, desktop: bool = False,
             sidecar: bool = True) -> Path:
        self.n += 1
        name = name or f"pkg{self.n}.zip"
        files = dict(entries)
        if manifest:
            files["MANIFEST_SHA256.txt"] = ("# m\n" + "\n".join(f"{sha(b)}  {k}" for k, b in files.items()) + "\n").encode()
        if desktop:
            files["MANIFEST_DESKTOP_SHA256.txt"] = ("# d\n" + "\n".join(f"{sha(b)}  {k}" for k, b in files.items()) + "\n").encode()
        p = self.dir / name
        with zipfile.ZipFile(p, "w") as z:
            for k, b in files.items():
                z.writestr("PMW/" + k, b)
        if sidecar:
            (self.dir / (name + ".sha256")).write_text(f"{sha(p.read_bytes())}  {name}\n", encoding="utf-8")
        return p

    def probs(self, entries: dict[str, bytes], **kw) -> str:
        return " | ".join(VR.check_zip(self.make({"backend/a.py": b"print(1)\n", **entries}, **kw)))


# ------------------------------------------------------------------------------------------------ focus_X7#0 (+ chunk_50#0)
class DesktopBuildCase(unittest.TestCase):
    """build_desktop.main() in a temp ROOT: Go build, NuGet download and the uv requirements check replaced by fakes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "release").mkdir()
        (self.root / "src").mkdir()
        exe = self.root / "fake.exe"
        exe.write_bytes(b"MZ fake windows exe\n")
        nupkg = self.root / "python.nupkg"
        with zipfile.ZipFile(nupkg, "w") as z:
            z.writestr("tools/python.exe", b"MZ python\n")
            z.writestr("tools/Lib/secrets.py", b"# stdlib\n")
        self.calls: list[str] = []
        patches = [mock.patch.object(BD, "ROOT", self.root), mock.patch.object(BR, "ROOT", self.root),
                   mock.patch.object(BD, "version", lambda: "9.9.9"),
                   mock.patch.object(BD, "build_exe", lambda ver, mode="bot": exe),
                   mock.patch.object(BD, "fetch_python", lambda: nupkg),
                   mock.patch.object(BR, "check_windows_requirements", lambda: self.calls.append("requirements")),
                   mock.patch.dict(os.environ, {"PMW_OWNER_DIR": str(self.root / "no_owner_key_here")}),
                   mock.patch.object(sys, "argv", ["build_desktop.py"])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def entries(self, extra: dict[str, bytes]) -> list[tuple[str, Path]]:
        out = []
        for rel, data in {"backend/masterquo/a.py": b"print(1)\n", **extra}.items():
            p = self.root / "src" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            out.append((rel, p))
        return out

    def run_main(self, entries):
        with mock.patch.object(BR, "edition_entries", lambda *a, **k: entries), contextlib.redirect_stdout(io.StringIO()):
            BD.main()


class TestDesktopPackageIsVerified(DesktopBuildCase):
    """build_desktop.main(): the Windows app package goes through check_windows_requirements() and verify_release.check_zip, and a
    package that fails verification never lands in release/."""

    def test_secret_in_the_desktop_package_stops_the_build_and_leaves_nothing_in_release(self):
        # an entry that slipped past the file-selection scan (e.g. a key copy in docs/) must be caught by verify_release
        with self.assertRaises(SystemExit) as cm:
            self.run_main(self.entries({"docs/kopia_klucza.txt": KEY_TEXT.encode()}))
        self.assertIn("PMW_OWNER_PRIVATE_KEY", str(cm.exception))
        self.assertEqual(self.calls, ["requirements"])                               # Windows requirements gate ran before the build
        self.assertEqual(sorted(p.name for p in (self.root / "release").iterdir()), [])  # no ZIP, no .sha256, no staging folder

    def test_clean_desktop_package_is_published_and_passes_verify_release(self):
        self.run_main(self.entries({"docs/x.md": b"# doc\n"}))
        out = self.root / "release" / "PepeMarketWizard_DESKTOP_9_9_9.zip"
        self.assertEqual(sorted(p.name for p in (self.root / "release").iterdir()), [out.name, out.name + ".sha256"])
        self.assertEqual(VR.check_zip(out, BD.TOP), [])
        self.assertEqual(self.calls, ["requirements"])

    def test_build_release_scan_uses_the_verify_release_rules(self):
        """build_release.scan() (file selection of BOTH builds) knows the owner key format and the forbidden key/database names."""
        BR.ROOT.joinpath("docs").mkdir()
        (BR.ROOT / "docs" / "kopia_klucza.txt").write_text(KEY_TEXT, encoding="ascii")
        with self.assertRaises(SystemExit) as cm:
            BR.scan(["docs/kopia_klucza.txt"])
        self.assertIn("PMW_OWNER_PRIVATE_KEY", str(cm.exception))
        for rel in ("backend/masterquo/licensing/private.key", "tests/fixtures/licenses.db", "config/prod.env", ".env.local"):
            p = BR.ROOT / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x\n")
            with self.assertRaises(SystemExit, msg=rel):
                BR.scan([rel])
        (BR.ROOT / "ok.py").write_bytes(b"print(1)\n")
        BR.scan(["ok.py"])                                                            # clean file passes


# ------------------------------------------------------------------------------------------------ focus_X7#2
class TestFailedVerificationKeepsRelease(unittest.TestCase):
    """build_release.main(): the ZIP is built in a staging folder and moved into release/ only after verify_release passed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "release").mkdir()
        self.old_zip = self.root / "release" / BR.APP_ZIP
        self.old_zip.write_bytes(b"previous release of this version")
        (self.root / "release" / (BR.APP_ZIP + ".sha256")).write_text(f"{sha(b'previous release of this version')}  {BR.APP_ZIP}\n")
        for rel, data in {"backend/masterquo/a.py": b"print(1)\n", "docs/x.md": b"# doc\n"}.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        self.manifest = "# old\n" + "\n".join(f"{sha((self.root / r).read_bytes())}  {r}" for r in ("backend/masterquo/a.py", "docs/x.md")) + "\n"
        (self.root / "MANIFEST_SHA256.txt").write_text(self.manifest, encoding="utf-8")
        patches = [mock.patch.object(BR, "ROOT", self.root), mock.patch.object(BR, "check_windows_requirements", lambda: None),
                   mock.patch.dict(os.environ, {"PMW_OWNER_DIR": str(self.root / "no_owner_key_here")}),
                   mock.patch.object(sys, "argv", ["build_release.py"])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_failed_verification_leaves_previous_release_and_manifest_untouched(self):
        (self.root / "docs" / "x.md").write_text(PEM, encoding="ascii")              # a secret the (bypassed) file scan did not stop
        with mock.patch.object(BR, "scan", lambda files: None), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as cm:
            BR.main()
        self.assertIn("weryfikacja nieudana", str(cm.exception))
        self.assertEqual(self.old_zip.read_bytes(), b"previous release of this version")
        self.assertEqual(sorted(p.name for p in (self.root / "release").iterdir()), [BR.APP_ZIP, BR.APP_ZIP + ".sha256"])
        self.assertEqual((self.root / "MANIFEST_SHA256.txt").read_text(encoding="utf-8"), self.manifest)

    def test_client_entries_failing_verification_are_not_published(self):
        src = self.root / "docs" / "x.md"
        src.write_text(PEM, encoding="ascii")
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            BR.write_zip_entries("PepeMarketWizard_KLIENT_9_9_9.zip", "PepeMarketWizard/", [("docs/x.md", src)],
                                 {"MANIFEST_SHA256.txt": f"{sha(src.read_bytes())}  docs/x.md\n".encode()})
        self.assertFalse(any("KLIENT" in p.name for p in (self.root / "release").iterdir()))

    def test_successful_build_publishes_zip_and_manifest(self):
        with contextlib.redirect_stdout(io.StringIO()):
            BR.main()
        out = self.root / "release" / BR.APP_ZIP
        self.assertNotEqual(out.read_bytes(), b"previous release of this version")
        self.assertEqual(VR.check_zip(out, "PepeMarketWizard/"), [])
        self.assertIn("backend/masterquo/a.py", (self.root / "MANIFEST_SHA256.txt").read_text(encoding="utf-8"))
        self.assertEqual(sorted(p.name for p in (self.root / "release").iterdir()), [BR.APP_ZIP, BR.APP_ZIP + ".sha256"])


# ------------------------------------------------------------------------------------------------ chunk_50#3
class TestOfflineWheels(DesktopBuildCase):
    def test_only_wheels_pinned_in_requirements_win_are_packed(self):
        wheels = self.root / "build" / "wheels"
        wheels.mkdir(parents=True)
        (wheels / "pkg-2.0-py3-none-any.whl").write_bytes(b"current wheel")
        (wheels / "pkg-1.0-py3-none-any.whl").write_bytes(b"stale wheel of an earlier release")
        (self.root / "requirements").mkdir()
        (self.root / "requirements" / "requirements-win.txt").write_text(
            f"pkg==2.0 \\\n    --hash=sha256:{sha(b'current wheel')}\n", encoding="utf-8")
        with mock.patch.object(BD, "fetch_wheels", lambda: wheels), mock.patch.object(sys, "argv", ["build_desktop.py", "--offline"]):
            self.run_main(self.entries({}))
        out = self.root / "release" / "PepeMarketWizard_DESKTOP_9_9_9_OFFLINE.zip"
        with zipfile.ZipFile(out) as z:
            names = [n for n in z.namelist() if n.endswith(".whl")]
        self.assertEqual(names, [BD.TOP + "runtime/wheels/pkg-2.0-py3-none-any.whl"])
        self.assertEqual(VR.check_zip(out, BD.TOP), [])


# ------------------------------------------------------------------------------------------------ focus_X7#1
class TestSecretScanCoverage(ZipCase):
    def test_raw_token_bat_json_utf16_and_env_suffix_are_found(self):
        cases = {
            "config/secrets.env": (("TELEGRAM_BOT_TOKEN = " + TG_TOKEN + "\n").encode(), "plik zabroniony"),
            "uruchom.bat": (("@echo off\nset TELEGRAM_BOT_TOKEN=" + TG_TOKEN + "\n").encode(), "TELEGRAM"),
            "uruchom2.bat": (b"set FRED_API_KEY=0123456789abcdef0123456789abcdef\n", "SECRET_ASSIGNMENT"),
            "docs/ustawienia.json": (json.dumps({"MT5_PASSWORD": "Hunter2!xyz"}).encode(), "SECRET_ASSIGNMENT"),
            "docs/ustawienia2.json": (json.dumps({"TELEGRAM_BOT_TOKEN": TG_TOKEN}).encode(), "TELEGRAM"),
            "docs/klucz_utf16.txt": (("ANTHROPIC_API_KEY=sk-ant-" + "api03-" + "Zx9" * 10 + "\r\n").encode("utf-16"), "ANTHROPIC_KEY"),
            "docs/notatka.md": (("token bota: " + TG_TOKEN + "\n").encode(), "TELEGRAM_TOKEN"),
        }
        for rel, (data, kind) in cases.items():
            probs = self.probs({rel: data})
            self.assertIn(rel, probs, rel)
            self.assertIn(kind, probs, rel)

    def test_repository_style_placeholders_and_test_dummies_pass(self):
        ok = {".env.example": b"# opis\nANTHROPIC_API_KEY=\nFRED_API_KEY=\nTELEGRAM_BOT_TOKEN=\n",
              "backend/vendor/README.md": '$env:FRED_API_KEY = "TWÓJ_KLUCZ_TUTAJ"\n'.encode(),
              "backend/vendor/M15_TESTS.py": b"with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'synthetic','TELEGRAM_CHAT_ID':'123'}):\n",
              "tests/test_x.py": b'TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")\nkey = "sk-ant-api03-SECRETVALUE-1234567890"\n',
              "frontend/dist/assets/a.js": b'const n="TELEGRAM_BOT_TOKEN";fetch("/api/v1/secrets/"+n)\n'}
        self.assertEqual(self.probs(ok), "")


# ------------------------------------------------------------------------------------------------ chunk_52#0
class TestSecretNamesAndEnvFiles(ZipCase):
    def test_every_store_secret_name_and_env_variants_are_refused(self):
        cases = {".env.local": b"X=1\n", "config/.env.production": b"X=1\n", "secrets.env": b"X=1\n",
                 ".env.example": b"FRED_API_KEY=0123456789abcdef0123456789abcdef\n",
                 "cfg/a.env.txt": b"MT5_PASSWORD = Hunter2!xyz\n",
                 "cfg/b.txt": b"COINGLASS_API_KEY=0123456789abcdef0123456789abcdef\n",
                 "cfg/c.ps1": b'$env:MT5_PASSWORD = "Hunter2!xyz"\n',
                 "cfg/d.sh": b"export COINGLASS_API_KEY=0123456789abcdef0123456789abcdef\n",
                 "docs/e.md": b"FRED_API_KEY=0123456789abcdef0123456789abcdef\n"}
        for rel, data in cases.items():
            self.assertIn(rel, self.probs({rel: data}), rel)

    def test_secret_names_match_the_app_secret_store(self):
        from masterquo import secrets_store
        self.assertLessEqual(set(secrets_store.ALLOWED), set(VR.SECRET_NAMES))


# ------------------------------------------------------------------------------------------------ chunk_52#1
class TestOwnerKeyForms(ZipCase):
    def test_json_export_mid_line_and_compact_forms(self):
        cases = {"docs/dump.json": json.dumps({"filename": "k.key", "content": KEY_TEXT}).encode(),
                 "docs/log.txt": ("eksport: " + KEY_TEXT).encode(),
                 "docs/k.txt": (SEED + "\n").encode(),
                 "docs/k2.txt": (SEED + "ab" * 32).encode(),
                 "docs/k3.ini": ("seed = " + SEED.upper() + "\n").encode()}
        for rel, data in cases.items():
            probs = self.probs({rel: data})
            self.assertIn(f"{rel}: PMW_OWNER_PRIVATE_KEY", probs, rel)

    def test_seed_of_the_owner_key_on_this_machine_is_found_in_any_form(self):
        kd = self.dir / "owner"
        kd.mkdir()
        (kd / "private.key").write_text(KEY_TEXT, encoding="ascii")
        with mock.patch.dict(os.environ, {"PMW_OWNER_DIR": str(kd)}):
            probs = self.probs({"backend/masterquo/licensing/client_config.py": ('PUBLIC_KEY_HEX = "' + SEED.upper() + '"\n').encode()})
            self.assertIn("client_config.py: PMW_OWNER_SEED", probs)
            self.assertEqual(self.probs({"docs/x.md": b"# doc\n"}), "")


# ------------------------------------------------------------------------------------------------ chunk_52#2
class TestManifestsRequired(ZipCase):
    def test_package_without_manifest_fails(self):
        self.assertIn("brak MANIFEST_SHA256.txt", self.probs({}, manifest=False))

    def test_desktop_package_without_desktop_manifest_fails(self):
        self.assertIn("brak MANIFEST_DESKTOP_SHA256.txt", self.probs({}, name="PepeMarketWizard_DESKTOP_9_9_9.zip"))
        self.assertEqual(self.probs({}, name="PepeMarketWizard_DESKTOP_9_9_8.zip", desktop=True), "")

    def test_folder_package_lists_every_file(self):
        p = self.make({"backend/a.py": b"1\n"})
        with zipfile.ZipFile(p, "a") as z:
            z.writestr("PMW/backend/extra.py", b"2\n")
        (self.dir / (p.name + ".sha256")).write_text(f"{sha(p.read_bytes())}  {p.name}\n", encoding="utf-8")
        self.assertIn("pliki spoza manifestu", " | ".join(VR.check_zip(p)))

    def test_files_required_by_the_installers_must_be_present(self):
        bat = b'for %%F in ("tools\\check_python.py" "frontend\\dist\\index.html" "MANIFEST_SHA256.txt") do (\n'
        probs = self.probs({"01_INSTALUJ.bat": bat, "tools/check_python.py": b"# ok\n"})
        self.assertIn("frontend/dist/index.html", probs)
        self.assertNotIn("check_python.py']", probs)
        self.assertEqual(self.probs({"01_INSTALUJ.bat": bat, "tools/check_python.py": b"# ok\n", "frontend/dist/index.html": b"<html>"}), "")


# ------------------------------------------------------------------------------------------------ chunk_52#3
class TestManifestLines(ZipCase):
    def test_upper_case_line_of_a_changed_file_is_checked(self):
        files = {"backend/a.py": b"tampered\n"}
        man = f"# m\n{sha(b'original').upper()}  backend/a.py\n".encode()
        self.assertIn("inna suma backend/a.py", self.probs_raw(files, man))

    def test_binary_mode_lines_are_read_and_garbage_is_reported(self):
        files = {"backend/a.py": b"1\n"}
        self.assertEqual(self.probs_raw(files, f"{sha(b'1' + bytes([10]))} *backend/a.py\n".encode()), "")
        probs = self.probs_raw(files, f"{sha(b'1' + bytes([10]))}  backend/a.py\nzepsuty wiersz\n".encode())
        self.assertIn("nieczytelny wiersz 2", probs)

    def probs_raw(self, files: dict[str, bytes], manifest: bytes) -> str:
        return " | ".join(VR.check_zip(self.make({**files, "MANIFEST_SHA256.txt": manifest}, manifest=False)))


# ------------------------------------------------------------------------------------------------ chunk_52#4
class TestBrokenInputs(ZipCase):
    def test_empty_sidecar_and_non_zip_are_problems_not_exceptions(self):
        p = self.make({"backend/a.py": b"1\n"})
        (self.dir / (p.name + ".sha256")).write_text("", encoding="utf-8")
        self.assertIn("pusty plik .sha256", VR.check_zip(p))
        bad = self.dir / "bad.zip"
        bad.write_bytes(b"not a zip at all")
        (self.dir / "bad.zip.sha256").write_text(f"{sha(bad.read_bytes())}  bad.zip\n", encoding="utf-8")
        self.assertTrue(any("nieczytelne" in x for x in VR.check_zip(bad)))
        p2 = self.make({"backend/a.py": b"1\n", "MANIFEST_SHA256.txt": b"\xff\xfe\xfa bad utf-8\n"}, manifest=False)
        self.assertTrue(VR.check_zip(p2))

    def test_upper_case_and_bom_sidecar_match(self):
        p = self.make({"backend/a.py": b"1\n"})
        side = self.dir / (p.name + ".sha256")
        side.write_text(f"{sha(p.read_bytes()).upper()}  {p.name}\r\n", encoding="utf-8-sig")
        self.assertEqual(VR.check_zip(p), [])

    def test_main_reports_every_archive(self):
        bad = self.dir / "bad.zip"
        bad.write_bytes(b"not a zip")
        good = self.make({"backend/a.py": b"1\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = VR.main([str(bad), str(good)])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL bad.zip", out.getvalue())
        self.assertIn(f"OK   {good.name}", out.getvalue())


# ------------------------------------------------------------------------------------------------ chunk_52#5
class TestCaseOnlyDuplicates(ZipCase):
    def test_names_differing_only_in_case_are_refused(self):
        self.assertIn("wielkością liter", self.probs({"backend/A.py": b"1\n", "backend/b.py": b"2\n", "backend/B.py": b"3\n"}))


if __name__ == "__main__":
    unittest.main()
