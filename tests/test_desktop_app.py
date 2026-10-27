"""Desktop application (PepeMarketWizardDesktop.exe) - engine side: window preferences, opt-in autostart (HKCU Run, simulated
registry here), restart request for the shell, and the same endpoints on a real server process behind session + CSRF."""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

import _env
from _env import TempData, wait_for

from masterquo import desktop


class FakeRunKey:
    def __init__(self, value=None):
        self.value = value
        self.writes = []

    def get(self):
        return self.value

    def set(self, command):
        self.value = command
        self.writes.append(("set", command))

    def delete(self):
        self.value = None
        self.writes.append(("delete", None))


class DesktopEnv:
    def __init__(self, exe="C:\\PMW\\PepeMarketWizardDesktop.exe"):
        self.exe = exe

    def __enter__(self):
        self.prev = {k: os.environ.get(k) for k in ("PMW_DESKTOP", "PMW_DESKTOP_EXE")}
        if self.exe:
            os.environ.update(PMW_DESKTOP="1", PMW_DESKTOP_EXE=self.exe)
        else:
            os.environ.pop("PMW_DESKTOP", None)
            os.environ.pop("PMW_DESKTOP_EXE", None)
        return self

    def __exit__(self, *a):
        for k, v in self.prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestDesktopPrefs(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_defaults_autostart_off(self):
        with DesktopEnv():
            i = desktop.info(FakeRunKey())
        self.assertEqual(i["prefs"], {"close_action": "ask", "autostart": False, "start_minimized": False})
        self.assertTrue(i["desktop"])
        self.assertFalse(i["autostart_registered"])

    def test_autostart_is_written_only_when_chosen_and_removed_when_switched_off(self):
        reg = FakeRunKey()
        with DesktopEnv("C:\\Apps\\PMW\\PepeMarketWizardDesktop.exe"):
            out = desktop.save_prefs("background", False, False, reg)
            self.assertEqual(reg.writes, [], "saving other preferences must not touch the autostart entry")
            out = desktop.save_prefs("background", True, True, reg)
            self.assertEqual(reg.value, '"C:\\Apps\\PMW\\PepeMarketWizardDesktop.exe" --autostart')
            self.assertTrue(out["autostart_registered"])
            self.assertFalse(out["autostart_other_exe"])
            self.assertEqual(out["prefs"], {"close_action": "background", "autostart": True, "start_minimized": True})
            desktop.save_prefs("exit", False, False, reg)
            self.assertIsNone(reg.value)
            self.assertEqual(reg.writes[-1], ("delete", None))
        on_disk = json.loads((self.td_path() / "desktop_prefs.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, {"close_action": "exit", "autostart": False, "start_minimized": False})

    def test_entry_of_a_moved_copy_is_reported(self):
        reg = FakeRunKey('"D:\\old\\PepeMarketWizardDesktop.exe" --autostart')
        with DesktopEnv("C:\\new\\PepeMarketWizardDesktop.exe"):
            self.assertTrue(desktop.info(reg)["autostart_other_exe"])

    def test_invalid_and_unsupported(self):
        with DesktopEnv():
            with self.assertRaises(desktop.DesktopError):
                desktop.save_prefs("minimize", False, False, FakeRunKey())
        with DesktopEnv(None):  # engine started by the BAT launcher: no shell, no autostart, no restart
            with self.assertRaises(desktop.DesktopError):
                desktop.save_prefs("ask", True, False, FakeRunKey())
            with self.assertRaises(desktop.DesktopError):
                desktop.request_restart()
            self.assertFalse(desktop.info(FakeRunKey())["autostart_supported"])

    def test_broken_prefs_file_falls_back_to_defaults(self):
        (self.td_path() / "desktop_prefs.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(desktop.load_prefs()["close_action"], "ask")
        (self.td_path() / "desktop_prefs.json").write_text('{"close_action": "explode", "autostart": 1}', encoding="utf-8")
        p = desktop.load_prefs()
        self.assertEqual((p["close_action"], p["autostart"]), ("ask", True))

    def test_restart_request_file(self):
        with DesktopEnv():
            desktop.request_restart()
        self.assertTrue((self.td_path() / "runtime" / "restart.request").exists())

    def td_path(self):
        from pathlib import Path
        return Path(self.td.dir)


PORT = 8796
BASE = f"http://127.0.0.1:{PORT}"


class TestDesktopApi(unittest.TestCase):
    """Real server process started the way the shell starts it (PMW_DESKTOP=1, PMW_DESKTOP_EXE, MASTERQUO_DATA_DIR)."""

    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        with open(os.path.join(cls.td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None}}, f)
        env = dict(os.environ, MASTERQUO_DATA_DIR=cls.td.dir, PYTHONPATH=str(_env.ROOT / "backend"), PMW_DESKTOP="1",
                   PMW_DESKTOP_EXE="C:\\PMW\\PepeMarketWizardDesktop.exe")
        env.pop("ANTHROPIC_API_KEY", None)
        cls.proc = subprocess.Popen([sys.executable, "-m", "masterquo", "serve", "--demo", "--no-browser"], env=env,
                                    cwd=str(_env.ROOT / "backend"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_for(lambda: cls.status("/api/v1/health")[0] == 200, 90, 0.5):
            cls.proc.kill()
            raise RuntimeError("server did not start")
        cls.jar = http.cookiejar.CookieJar()
        cls.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cls.jar))
        cls.op.open(BASE + "/", timeout=30).read()
        cls.csrf = cls.call("/api/v1/session")[1]["csrf"]

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.kill()
            cls.proc.wait(30)
        cls.td.close()

    @classmethod
    def status(cls, path):
        try:
            with urllib.request.urlopen(BASE + path, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
        except OSError:
            return 0, b""

    @classmethod
    def call(cls, path, body=None, csrf=True, origin=BASE):
        h = {"Content-Type": "application/json"}
        if csrf:
            h["X-MQ-CSRF"] = cls.csrf if hasattr(cls, "csrf") else ""
        if origin:
            h["Origin"] = origin
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                     method="POST" if body is not None else "GET")
        try:
            with cls.op.open(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_1_info_and_prefs(self):
        st, i = self.call("/api/v1/desktop")
        self.assertEqual(st, 200)
        self.assertTrue(i["desktop"])
        self.assertTrue(i["restart_supported"])
        self.assertEqual(i["prefs"]["close_action"], "ask")
        self.assertFalse(i["prefs"]["autostart"])
        st, out = self.call("/api/v1/desktop/prefs", {"close_action": "background", "autostart": False, "start_minimized": True})
        self.assertEqual(st, 200, out)
        self.assertEqual(out["prefs"]["close_action"], "background")
        with open(os.path.join(self.td.dir, "desktop_prefs.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["close_action"], "background")
        # Linux test machine: no Windows registry - autostart is refused with a reason, never pretended
        st, out = self.call("/api/v1/desktop/prefs", {"close_action": "ask", "autostart": True})
        self.assertEqual(st, 400)
        self.assertIn("AUTOSTART_NEEDS_DESKTOP_APP", json.dumps(out))
        st, _ = self.call("/api/v1/desktop/prefs", {"close_action": "hide"})
        self.assertEqual(st, 400)

    def test_2_protected_like_every_other_change(self):
        st, _ = self.call("/api/v1/desktop/prefs", {"close_action": "exit"}, csrf=False)
        self.assertEqual(st, 403)
        st, _ = self.call("/api/v1/desktop/prefs", {"close_action": "exit"}, origin="http://evil.example")
        self.assertEqual(st, 403)
        st, _ = self.call("/api/v1/desktop/restart-engine", {}, origin="http://evil.example")
        self.assertEqual(st, 403)
        self.assertIsNone(self.proc.poll())

    def test_3_restart_request_ends_engine_for_the_shell(self):
        st, out = self.call("/api/v1/desktop/restart-engine", {})
        self.assertEqual(st, 200, out)
        self.assertTrue(os.path.exists(os.path.join(self.td.dir, "runtime", "restart.request")))
        self.proc.wait(60)  # the shell starts it again; here nobody does


if __name__ == "__main__":
    unittest.main()


class TestDesktopFolder(unittest.TestCase):
    """The program folder of the Windows app also holds the launcher and the .bat scripts (training, diagnostics). They must find
    the files they check for and work on the SAME data folder as the app (desktop/layout.go)."""

    def setUp(self):
        import tempfile
        self.td = tempfile.TemporaryDirectory()
        self.root = _env.Path(self.td.name) / "Pepe Market Wizard ąę"          # spaces and Polish letters in the path
        self.root.mkdir()
        self.env = {k: os.environ.pop(k) for k in ("MASTERQUO_DATA_DIR", "PMW_HOME", "LOCALAPPDATA") if k in os.environ}

    def tearDown(self):
        for k in ("PMW_HOME", "LOCALAPPDATA"):
            os.environ.pop(k, None)
        os.environ.update(self.env)
        self.td.cleanup()

    def test_data_folder_rules_match_the_app(self):
        from mq_instruments import default_data_dir
        self.assertEqual(default_data_dir(self.root), self.root / "data")                      # classic package: unchanged
        (self.root / "PepeMarketWizardDesktop.exe").write_bytes(b"MZ")
        os.environ["LOCALAPPDATA"] = str(self.root / "lad")
        self.assertEqual(default_data_dir(self.root), self.root / "lad" / "PepeMarketWizard" / "data")
        os.environ["PMW_HOME"] = str(self.root / "home")
        self.assertEqual(default_data_dir(self.root), self.root / "home" / "data")
        os.environ.pop("PMW_HOME")
        (self.root / "portable.txt").write_text("1")
        self.assertEqual(default_data_dir(self.root), self.root / "data")
        os.environ["MASTERQUO_DATA_DIR"] = str(self.root / "explicit")
        try:
            import mq_instruments
            self.assertEqual(mq_instruments.data_dir(), self.root / "explicit")              # explicit setting always wins
        finally:
            os.environ.pop("MASTERQUO_DATA_DIR")

    def test_package_holds_every_file_the_launcher_and_installers_check(self):
        import re
        root = _env.ROOT
        tracked = set(subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout.split("\n"))
        src = (root / "tools" / "launcher" / "main.go").read_text(encoding="utf-8")
        need = set(re.findall(r"`([^`]+)`", re.search(r"var required = \[\]string\{(.*?)\}", src, re.S).group(1)))
        for bat in ("00_TRENING_START.bat", "01_INSTALUJ.bat", "INSTALUJ_TRENING.bat"):
            m = re.search(r'for %%F in \((.*?)\) do', (root / bat).read_text(encoding="ascii"))
            need |= set(re.findall(r'"([^"]+)"', m.group(1)))
        need = {n.replace("\\", "/") for n in need}
        self.assertIn("MANIFEST_SHA256.txt", need)
        for n in need - {"MANIFEST_SHA256.txt"}:
            self.assertIn(n, tracked, n)
        # MANIFEST_SHA256.txt is generated by the build: the client package AND the Windows app package must contain it
        self.assertIn('client + ["MANIFEST_SHA256.txt"]', (root / "tools" / "build_release.py").read_text(encoding="utf-8"))
        self.assertIn('z.writestr(TOP + "MANIFEST_SHA256.txt"', (root / "tools" / "build_desktop.py").read_text(encoding="utf-8"))

    def test_installers_prefer_the_python_of_the_package(self):
        for bat in ("01_INSTALUJ.bat", "10_PROGNOZY_INSTALUJ.bat"):
            t = (_env.ROOT / bat).read_text(encoding="ascii")
            self.assertLess(t.index("runtime\\python\\python.exe"), t.index("for %%V in (3.13 3.12)"), bat)
            self.assertIn("tools\\check_python.py", t[t.index("runtime\\python\\python.exe"):])
