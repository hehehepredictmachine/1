"""Windows launchers (static checks - Windows itself is not available in the build environment): ASCII + CRLF, paths
built from %~dp0 are always quoted (folders with spaces), the start goes through masterquo_start (license prompt), the
license key is never passed as an argument."""
import re
import unittest

import _env


class TestLaunchers(unittest.TestCase):
    def bats(self):
        return sorted(list(_env.ROOT.glob("*.bat")) + list((_env.ROOT / "server").glob("*.bat")))

    def test_ascii_crlf_and_quoted_paths(self):
        self.assertGreaterEqual(len(self.bats()), 9)                 # 9 client launchers (+2 server ones in the repo)
        for f in self.bats():
            with self.subTest(f=f.name):
                raw = f.read_bytes()
                raw.decode("ascii")
                self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))           # CRLF only
                for line in raw.decode().splitlines():
                    if line.strip().lower().startswith("rem") or line.strip().startswith("echo"):
                        continue
                    for m in re.finditer(r'%~dp0[^\s"]*', line):
                        before = line[:m.start()]
                        self.assertEqual(before.count('"') % 2, 1, f"unquoted path in {f.name}: {line}")

    def test_start_requires_license_prompt(self):
        start = (_env.ROOT / "masterquo_start.bat").read_text()
        self.assertIn("-m masterquo serve", start)
        code = "\n".join(l for l in start.splitlines() if not l.strip().lower().startswith("rem"))
        self.assertNotRegex(code.upper(), r"MQL72|LICENSE_KEY|--KEY")
        self.assertIn("masterquo_start.bat", (_env.ROOT / "03_START_MASTERQUO.bat").read_text())


if __name__ == "__main__":
    unittest.main()
