"""Windows launchers (static checks - Windows itself is not available in the build environment): ASCII + CRLF, paths
built from %~dp0 are always quoted (folders with spaces), the start goes through masterquo_start
(no license - 1.9.0)."""
import re
import unittest

import _env


class TestLaunchers(unittest.TestCase):
    def bats(self):
        return sorted(_env.ROOT.glob("*.bat"))

    def test_ascii_crlf_and_quoted_paths(self):
        self.assertGreaterEqual(len(self.bats()), 8)
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

    def test_start_without_license(self):
        start = (_env.ROOT / "masterquo_start.bat").read_text()
        self.assertIn("-m masterquo serve", start)
        self.assertNotRegex(start.upper(), r"LICEN|MQL72|--KEY")
        self.assertIn("masterquo_start.bat", (_env.ROOT / "03_START_MASTERQUO.bat").read_text())


if __name__ == "__main__":
    unittest.main()
