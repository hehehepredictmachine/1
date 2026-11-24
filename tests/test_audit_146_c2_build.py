"""1.46 audit (group C2_build) - regression tests for tools/build_release.py, tools/build_desktop.py, tools/verify_release.py and the
archived 1.41 asset generator.

  focus_X7#4   the client edition marker backend/masterquo/licensing/_edition.py (masterquo.licensing.edition: present = CLIENT even when an
               owner.py is added) is written ONLY into client packages (build_release --edition client, build_desktop --edition client);
               verify_release requires it in a client package and refuses it in an owner package
  chunk_51#14  tools/research/ (one-off research scripts with session paths) never goes into a package
  chunk_52#6   the dead 1.41 "three towers" asset generator lives in archive/ui_1_41/tools/ (archive/ is never packaged)

Temporary trees and archives only: the repository, release/ and build/ of the repository are never written; Go, NuGet, npm, PyPI and uv are
not called (the build steps that need them are replaced by fakes)."""
from __future__ import annotations

import contextlib
import hashlib
import io
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

MARKER = "backend/masterquo/licensing/_edition.py"
OWNER = "backend/masterquo/licensing/owner.py"
CFG = "backend/masterquo/licensing/client_config.py"
PUB_HEX = "ab" * 32                                                     # any 64-hex public key (not a key of anyone)
TREE = {"backend/masterquo/a.py": b"print(1)\n",
        "backend/masterquo/licensing/edition.py": b"# edition\n",
        OWNER: b"# owner module (owner edition only)\n",
        CFG: ('PUBLIC_KEY_HEX = "' + PUB_HEX + '"\n').encode(),
        "frontend/dist/index.html": b"<html>owner panel</html>",
        "docs/x.md": b"# doc\n"}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class ClientTree(unittest.TestCase):
    """A temp ROOT with a few program files; tracked() / the client panel build / the public-key check are fakes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "release").mkdir()
        self.files = dict(TREE)
        for rel, data in self.files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        dist = self.root / "fake_client_dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_bytes(b"<html>client panel</html>")
        (dist / "assets" / "a.js").write_bytes(b"fetch('/api/v1/license/status')")
        exe = self.root / "fake.exe"
        exe.write_bytes(b"MZ fake windows exe\n")
        nupkg = self.root / "python.nupkg"
        with zipfile.ZipFile(nupkg, "w") as z:
            z.writestr("tools/python.exe", b"MZ python\n")
        patches = [mock.patch.object(BR, "ROOT", self.root), mock.patch.object(BD, "ROOT", self.root),
                   mock.patch.object(BR, "tracked", lambda: sorted(self.files)),
                   mock.patch.object(BR, "client_public_key", lambda allow_foreign=False: PUB_HEX),
                   mock.patch.object(BR, "build_client_frontend", lambda: dist),
                   mock.patch.object(BR, "check_windows_requirements", lambda: None),
                   mock.patch.object(BD, "version", lambda: "9.9.9"),
                   mock.patch.object(BD, "build_exe", lambda ver, mode="bot": exe),
                   mock.patch.object(BD, "fetch_python", lambda: nupkg),
                   mock.patch.dict(os.environ, {"PMW_OWNER_DIR": str(self.root / "no_owner_key_here")})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def names(zp: Path, top: str) -> set[str]:
        with zipfile.ZipFile(zp) as z:
            return {n[len(top):] for n in z.namelist()}


# ------------------------------------------------------------------------------------------------ focus_X7#4
class TestClientEditionMarkerBuild(ClientTree):
    def test_client_entries_carry_the_marker_owner_entries_do_not(self):
        from masterquo.licensing import edition as E
        with contextlib.redirect_stdout(io.StringIO()):
            client = dict(BR.edition_entries("client"))
            owner = dict(BR.edition_entries("owner"))
        # the path inside the package is exactly the marker masterquo.licensing.edition looks for
        self.assertEqual(MARKER, "backend/masterquo/licensing/" + E._CLIENT_MARKER.name)
        self.assertIn(MARKER, client)
        self.assertNotIn(OWNER, client)
        self.assertIn('EDITION = "CLIENT"', client[MARKER].read_text(encoding="utf-8"))
        # written into the git-ignored build/ folder of the (temp) ROOT, never into the source tree
        self.assertTrue(client[MARKER].resolve().is_relative_to((self.root / "build").resolve()))
        self.assertFalse((self.root / MARKER).exists())
        self.assertNotIn(MARKER, owner)
        self.assertIn(OWNER, owner)

    def test_marker_from_the_build_makes_the_program_a_client_edition_even_with_an_owner_file(self):
        from masterquo.licensing import edition as E
        with contextlib.redirect_stdout(io.StringIO()):
            marker = dict(BR.edition_entries("client"))[MARKER]
        empty_owner = self.root / "pkg" / "owner.py"
        empty_owner.parent.mkdir()
        empty_owner.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"PMW_EDITION": ""}), mock.patch.object(E, "_OWNER_FILE", empty_owner), \
                mock.patch.object(E, "_CLIENT_MARKER", marker):
            self.assertEqual(E.edition(), "CLIENT")
            self.assertFalse(E.dev_overrides())

    def test_tracked_marker_is_not_doubled_in_the_client_package(self):
        self.files[MARKER] = b'EDITION = "CLIENT"\n'                          # a no-git copy built from a client manifest
        (self.root / MARKER).write_bytes(self.files[MARKER])
        with contextlib.redirect_stdout(io.StringIO()):
            rels = [r for r, _ in BR.edition_entries("client")]
        self.assertEqual(rels.count(MARKER), 1)

    def test_client_folder_package_has_the_marker_and_passes_verify_release(self):
        with mock.patch.object(sys, "argv", ["build_release.py", "--edition", "client"]), contextlib.redirect_stdout(io.StringIO()):
            BR.main()
        zp = self.root / "release" / f"Apollo23_KLIENT_{BR.VERSION.replace('.', '_')}.zip"
        self.assertEqual(VR.check_zip(zp, "PepeMarketWizard/"), [])
        names = self.names(zp, "PepeMarketWizard/")
        self.assertIn(MARKER, names)
        self.assertNotIn(OWNER, names)
        with zipfile.ZipFile(zp) as z:
            manifest = z.read("PepeMarketWizard/MANIFEST_SHA256.txt").decode("utf-8")
        self.assertIn(f"  {MARKER}\n", manifest)

    def test_desktop_client_package_has_the_marker_owner_desktop_package_does_not(self):
        with mock.patch.object(sys, "argv", ["build_desktop.py", "--edition", "client"]), contextlib.redirect_stdout(io.StringIO()):
            BD.main()
        zp = self.root / "release" / "Apollo23_DESKTOP_KLIENT_9_9_9.zip"
        self.assertEqual(VR.check_zip(zp, BD.TOP), [])
        self.assertIn(MARKER, self.names(zp, BD.TOP))
        with mock.patch.object(sys, "argv", ["build_desktop.py"]), contextlib.redirect_stdout(io.StringIO()):
            BD.main()
        zo = self.root / "release" / "Apollo23_DESKTOP_9_9_9.zip"
        self.assertEqual(VR.check_zip(zo, BD.TOP), [])
        self.assertNotIn(MARKER, self.names(zo, BD.TOP))
        self.assertIn(OWNER, self.names(zo, BD.TOP))


class TestVerifyEditionMarker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"PMW_OWNER_DIR": str(self.dir / "no_owner_key_here")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def probs(self, name: str, entries: dict[str, bytes]) -> str:
        files = {"backend/masterquo/a.py": b"print(1)\n", **entries}
        files["MANIFEST_SHA256.txt"] = ("# m\n" + "\n".join(f"{sha(b)}  {k}" for k, b in files.items()) + "\n").encode()
        p = self.dir / name
        with zipfile.ZipFile(p, "w") as z:
            for k, b in files.items():
                z.writestr("PMW/" + k, b)
        (self.dir / (name + ".sha256")).write_text(f"{sha(p.read_bytes())}  {name}\n", encoding="utf-8")
        return " | ".join(VR.check_zip(p))

    def test_client_package_needs_the_marker_and_no_owner_module(self):
        cfg = {CFG: ('PUBLIC_KEY_HEX = "' + PUB_HEX + '"\n').encode()}
        self.assertIn("znacznik edycji klienta", self.probs("Apollo23_KLIENT_9_9_1.zip", cfg))
        self.assertEqual(self.probs("Apollo23_KLIENT_9_9_2.zip", {**cfg, MARKER: b'EDITION = "CLIENT"\n'}), "")
        probs = self.probs("Apollo23_KLIENT_9_9_3.zip", {**cfg, MARKER: b'EDITION = "CLIENT"\n', OWNER: b""})
        self.assertIn(f"{OWNER}: plik wersji właściciela", probs)

    def test_owner_package_must_not_carry_the_marker(self):
        self.assertEqual(self.probs("Apollo23_9_9_4.zip", {OWNER: b"# owner\n"}), "")
        self.assertIn("znacznik edycji klienta w paczce właściciela",
                      self.probs("Apollo23_9_9_5.zip", {OWNER: b"# owner\n", MARKER: b'EDITION = "CLIENT"\n'}))


# ------------------------------------------------------------------------------------------------ chunk_51#14
class TestResearchScriptsAreNotPackaged(unittest.TestCase):
    def test_tools_research_is_excluded_without_git(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rels = ["tools/a.py", "tools/research/tsfm_eval/common.py", "tools/research/tsfm_eval/res_granite.json"]
            for r in rels:
                (root / r).parent.mkdir(parents=True, exist_ok=True)
                (root / r).write_bytes(b"x\n")
            (root / "MANIFEST_SHA256.txt").write_text("".join(f"{sha(b'x' + bytes([10]))}  {r}\n" for r in rels), encoding="utf-8")
            with mock.patch.object(BR, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(BR.tracked(), ["tools/a.py"])

    def test_tools_research_is_excluded_from_the_git_file_list(self):
        with mock.patch.object(BR, "_git_list", lambda *a: ["tools/a.py", "tools/research/tsfm_eval/eval_kronos.py", "tools/researcher.py"]):
            self.assertEqual(BR.tracked(), ["tools/a.py", "tools/researcher.py"])


# ------------------------------------------------------------------------------------------------ chunk_52#6
class TestWizardAssetGeneratorArchived(unittest.TestCase):
    ROOT = _env.ROOT

    def test_generator_moved_to_archive_with_the_1_41_ui(self):
        self.assertFalse((self.ROOT / "tools" / "wizard_assets.py").exists())
        self.assertFalse((self.ROOT / "tools" / "wizard_backgrounds").exists())
        arch = self.ROOT / "archive" / "ui_1_41" / "tools"
        self.assertTrue((arch / "wizard_assets.py").is_file())
        self.assertTrue((arch / "wizard_backgrounds" / "profits_vault.html").is_file())
        # archive/ never goes into a package
        with mock.patch.object(BR, "_git_list", lambda *a: ["archive/ui_1_41/tools/wizard_assets.py", "tools/a.py"]):
            self.assertEqual(BR.tracked(), ["tools/a.py"])

    def test_docs_point_to_the_archived_generator(self):
        doc = (self.ROOT / "docs" / "MENU_WIEZE_1_26_PL.md").read_text(encoding="utf-8")
        self.assertTrue("archive/ui_1_41/tools/wizard_assets.py" in doc, "docs: path of the archived generator")
        self.assertFalse("`tools/wizard_assets.py`" in doc or "python tools/wizard_assets.py" in doc, "docs: old generator path")


if __name__ == "__main__":
    unittest.main()
