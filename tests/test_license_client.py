"""1.44.0 Wersja KLIENTA: weryfikacja licencji PMW1 (kolejność, komunikaty), license.dat, ochrona przed cofnięciem zegara, czas z internetu,
blokada trybów / API / nowych wejść, edycja, reguły paczki klienta. (Ten plik nie wchodzi do paczki klienta – używa podpisywania.)"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
import nacl.signing

from masterquo.licensing import gate as G
from masterquo.licensing import hwid as H
from masterquo.licensing import license_key as LK
from masterquo.licensing import signing as SG

SK = nacl.signing.SigningKey(bytes(range(1, 33)))
PUB = bytes(SK.verify_key)
DAY = 86400
T0 = 1_800_000_000.0


def env(**kw):
    """Kontekst zmiennych środowiska (None = usuń)."""
    class _E:
        def __enter__(self):
            self.prev = {k: os.environ.get(k) for k in kw}
            for k, v in kw.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            H._sources.cache_clear()

        def __exit__(self, *a):
            for k, v in self.prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            H._sources.cache_clear()
    return _E()


class FakeNet:
    def __init__(self, offset=None):
        self.off = offset

    def offset(self, refresh=False):
        return self.off


class TestCheckOrder(unittest.TestCase):
    """Kolejność: prefiks -> base64url -> podpis -> v == 1 -> exp -> hw; komunikaty po polsku."""

    def key(self, hw="A1B2C-D3E4F-G5H6J-K7M8N", exp=None, user="Klient"):
        return SG.sign_license(SK, user, hw, int(T0), exp)

    def test_codes(self):
        k = self.key(exp=int(T0) + 10 * DAY)
        here = "A1B2C-D3E4F-G5H6J-K7M8N"
        self.assertEqual(LK.check_license(k, PUB, now=T0, hwid=here)["code"], "OK")
        self.assertEqual(LK.check_license("PMW2-" + k[5:], PUB, now=T0, hwid=here)["code"], "FORMAT")
        self.assertEqual(LK.check_license("PMW1-@@@", PUB, now=T0, hwid=here)["code"], "FORMAT")
        bad = k[:30] + ("A" if k[30] != "A" else "B") + k[31:]
        self.assertIn(LK.check_license(bad, PUB, now=T0, hwid=here)["code"], ("SIGNATURE", "FORMAT"))
        other = bytes(nacl.signing.SigningKey.generate().verify_key)
        self.assertEqual(LK.check_license(k, other, now=T0, hwid=here)["code"], "SIGNATURE")
        r = LK.check_license(k, PUB, now=T0 + 11 * DAY, hwid=here)
        self.assertEqual(r["code"], "EXPIRED")
        self.assertIn(LK.fmt_date(int(T0) + 10 * DAY), r["message"])                # data wygaśnięcia w komunikacie
        r = LK.check_license(k, PUB, now=T0, hwid="ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ")
        self.assertEqual(r["code"], "HWID")
        self.assertIn("innego komputera", r["message"])
        self.assertTrue(LK.check_license(self.key(hw=None, exp=None), PUB, now=T0 + 10 ** 9, hwid="ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ")["ok"])

    def test_signature_checked_before_version_and_expiry(self):
        payload = json.dumps({"v": 2, "u": "x", "hw": None, "iat": 1, "exp": 2}, separators=(",", ":")).encode()
        good_v2 = LK.PREFIX + LK.b64u(payload + SK.sign(LK.DOMAIN + payload).signature)
        self.assertEqual(LK.check_license(good_v2, PUB, now=T0)["code"], "VERSION")
        forged = LK.PREFIX + LK.b64u(payload + bytes(64))                         # zły podpis -> SIGNATURE, nawet przy v=2 i wygasłej
        self.assertEqual(LK.check_license(forged, PUB, now=T0)["code"], "SIGNATURE")
        self.assertIsNone(LK.check_license(forged, PUB, now=T0)["payload"])        # danych spoza podpisu nie pokazujemy


class TestGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pmw_lic_")
        self.path = Path(self.tmp) / "license.dat"
        self.t = [T0]
        self.net = FakeNet(None)
        self.e = env(PMW_EDITION="CLIENT", PMW_TEST_PUBLIC_KEY_HEX=PUB.hex(), PMW_TEST_HWID_SOURCES="guid-x|uuid-y")
        self.e.__enter__()
        self.here = H.get_hwid()

    def tearDown(self):
        self.e.__exit__()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gate(self):
        return G.LicenseGate(clock=lambda: self.t[0], net=self.net, path=self.path)

    def lic(self, days=None, hw="here"):
        return SG.sign_license(SK, "Jan", self.here if hw == "here" else hw, int(self.t[0]), None if days is None else int(self.t[0] + days * DAY))

    def test_owner_edition_needs_no_license(self):
        with env(PMW_EDITION=None):
            g = self.gate()
            self.assertFalse(g.required)
            self.assertFalse(g.locked)
            self.assertEqual(g.state()["code"], "OWNER")

    def test_no_public_key_is_config_error(self):
        from masterquo.licensing import client_config
        orig = client_config.PUBLIC_KEY_HEX
        client_config.PUBLIC_KEY_HEX = ""                                           # jak paczka bez wpisanego klucza
        self.addCleanup(setattr, client_config, "PUBLIC_KEY_HEX", orig)
        with env(PMW_TEST_PUBLIC_KEY_HEX=None):
            g = self.gate()
            st = g.evaluate()
            self.assertEqual(st["code"], "NO_PUBLIC_KEY")
            self.assertTrue(g.locked)
            self.assertEqual(g.activate(self.lic(30))["code"], "NO_PUBLIC_KEY")

    def test_activation_persistence_and_unlock(self):
        g = self.gate()
        unlocked = []
        g.on_unlock.append(lambda: unlocked.append(1))
        st = g.evaluate()
        self.assertEqual(st["code"], "NO_LICENSE")
        self.assertTrue(g.locked)
        self.assertEqual(st["hwid"], self.here)
        bad = g.activate("PMW1-zly")
        self.assertFalse(bad["valid"])
        self.assertFalse(self.path.exists())                                       # zły klucz nie jest zapisywany
        ok = g.activate(self.lic(30))
        self.assertTrue(ok["valid"] and ok["activated"])
        self.assertEqual(ok["message"], "Licencja aktywna.")
        self.assertEqual(unlocked, [1])
        self.assertFalse(g.locked)
        d = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(d["key"].startswith("PMW1-"))
        self.assertEqual(d["last_seen"], T0)
        st = self.gate().evaluate()                                                # kolejny start: zapisany klucz ważny -> bez ekranu
        self.assertTrue(st["valid"])
        self.assertEqual((st["user"], st["perpetual"], st["days_left"], st["warn"]), ("Jan", False, 30, False))
        g2 = self.gate()
        g2.evaluate()
        self.assertTrue(g2.activate("PMW1-zly")["valid"] is False)
        self.assertTrue(self.gate().evaluate()["valid"])                           # zły „Zmień klucz” nie psuje zapisanego

    def test_expiry_warning_and_lock(self):
        g = self.gate()
        g.activate(self.lic(5))
        locked = []
        g.on_lock.append(lambda: locked.append(1))
        self.t[0] += 2.5 * DAY
        st = g.evaluate()
        self.assertTrue(st["valid"])
        self.assertEqual(st["days_left"], 3)
        self.assertTrue(st["warn"])                                                 # ≤ 3 dni -> ostrzeżenie
        self.t[0] += 3 * DAY
        st = g.evaluate()
        self.assertEqual(st["code"], "EXPIRED")
        self.assertIn("wygasła", st["message"])
        self.assertEqual(locked, [1])
        with self.assertRaises(G.LicenseRequired):
            g.require("FOREX")

    def test_perpetual_and_other_computer(self):
        g = self.gate()
        self.assertEqual(g.activate(self.lic(None, hw=None))["perpetual"], True)
        self.t[0] += 3650 * DAY
        self.assertTrue(g.evaluate()["valid"])
        r = self.gate().activate(SG.sign_license(SK, "Jan", "ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ", int(self.t[0]), None))
        self.assertEqual(r["code"], "HWID")

    def test_clock_rollback_offline(self):
        g = self.gate()
        g.activate(self.lic(365))
        self.t[0] -= 23 * 3600                                                     # do 24 h wstecz – tolerancja (strefy, korekty)
        self.assertTrue(g.evaluate()["valid"])
        self.t[0] -= 2 * 3600                                                      # razem 25 h wstecz od zapisu
        st = g.evaluate()
        self.assertEqual(st["code"], "CLOCK_ROLLBACK")
        self.assertIn("Wykryto cofnięcie zegara systemowego", st["message"])
        self.assertTrue(g.locked)
        self.assertEqual(g.activate(self.lic(365))["code"], "CLOCK_ROLLBACK")      # aktywacja też zablokowana
        self.t[0] += 26 * 3600
        self.assertTrue(g.evaluate()["valid"])

    def test_internet_time_wins_for_expiry_and_clock_error(self):
        g = self.gate()
        g.activate(self.lic(10))
        self.net.off = 11 * DAY                                                    # zegar komputera cofnięty o 11 dni, internet wie lepiej
        self.assertEqual(g.evaluate()["code"], "CLOCK_ERROR")
        self.net.off = 3600                                                        # mała różnica: czas z internetu liczy wygaśnięcie
        st = g.evaluate()
        self.assertTrue(st["valid"])
        self.assertEqual(st["time_source"], "internet")
        self.t[0] += 10 * DAY - 1800                                               # lokalnie jeszcze ważna, wg internetu już wygasła
        self.assertEqual(g.evaluate()["code"], "EXPIRED")

    def test_internet_time_overrides_wrong_future_last_seen(self):
        g = self.gate()
        g.activate(self.lic(365))
        self.t[0] += 5 * DAY                                                        # komputer chodził 5 dni do przodu (offline)
        g.evaluate()
        self.t[0] -= 5 * DAY                                                        # poprawiony zegar; offline -> wygląda na cofnięcie
        self.assertEqual(g.evaluate()["code"], "CLOCK_ROLLBACK")
        self.net.off = 0.0                                                          # z internetem: czas wiarygodny -> OK i nowy zapis
        self.assertTrue(g.evaluate()["valid"])
        self.net.off = None
        self.assertTrue(g.evaluate()["valid"])

    def test_mode_gate_blocks_new_entries_only(self):
        from masterquo.execution.modes import ModeManager  # noqa: F401 - import kontrolny
        g = self.gate()
        g.evaluate()

        class M:
            license_ok = g.ok
        self.assertFalse(M.license_ok())
        g.activate(self.lic(30))
        self.assertTrue(M.license_ok())

    def test_dev_overrides_ignored_without_owner_module(self):
        from masterquo.licensing import client_config
        from masterquo.licensing import edition as E
        orig, orig_key = E._OWNER_FILE, client_config.PUBLIC_KEY_HEX
        other = bytes(nacl.signing.SigningKey.generate().verify_key)
        client_config.PUBLIC_KEY_HEX = other.hex()                                  # klucz wpisany w paczce
        try:
            E._OWNER_FILE = Path(self.tmp) / "brak_owner.py"                        # jak w paczce klienta
            self.assertEqual(E.edition(), "CLIENT")
            self.assertFalse(E.dev_overrides())
            self.assertEqual(G.public_key()[0], other)                              # PMW_TEST_PUBLIC_KEY_HEX (=PUB) zignorowany
            with env(PMW_LICENSE_FILE=str(Path(self.tmp) / "inny.dat")):
                self.assertNotEqual(G.license_path(), Path(self.tmp) / "inny.dat")
        finally:
            E._OWNER_FILE = orig
            client_config.PUBLIC_KEY_HEX = orig_key


class TestClientPackageRules(unittest.TestCase):
    def test_client_problems(self):
        import sys
        sys.path.insert(0, str(_env.ROOT / "tools"))
        import verify_release as V
        files = {"backend/masterquo/licensing/client_config.py": b'PUBLIC_KEY_HEX = ""\n', "backend/masterquo/x.py": b"print(1)",
                 "frontend/dist/assets/a.js": b"fetch('/api/v1/license/status')"}
        probs = V.client_problems(lambda r: files[r], list(files))
        self.assertTrue(any("PUBLIC_KEY_HEX" in p for p in probs))
        files["backend/masterquo/licensing/client_config.py"] = b'PUBLIC_KEY_HEX = "' + PUB.hex().encode() + b'"\n'
        self.assertEqual(V.client_problems(lambda r: files[r], list(files)), [])
        files["backend/masterquo/licensing/signing.py"] = b"def sign_license(): pass"
        files["frontend/dist/assets/b.js"] = b"x('/api/v1/owner/license/state')"
        probs = V.client_problems(lambda r: files[r], list(files))
        self.assertTrue(any("signing.py: plik wersji właściciela" in p for p in probs))
        self.assertTrue(any("b.js" in p for p in probs))

    def test_build_refuses_empty_or_bad_public_key(self):
        """Na tymczasowej kopii client_config.py (niezależnie od klucza wpisanego w repozytorium)."""
        import sys
        sys.path.insert(0, str(_env.ROOT / "tools"))
        import build_release as B
        tmp = Path(tempfile.mkdtemp(prefix="pmw_cfg_"))
        cfg = tmp / B.CLIENT_CONFIG
        cfg.parent.mkdir(parents=True)
        orig = B.ROOT
        B.ROOT = tmp
        try:
            for val, msg in (("", "PUBLIC_KEY_HEX jest pusty"), ("abc", "64 znaki")):
                cfg.write_text(f'PUBLIC_KEY_HEX = "{val}"\n', encoding="utf-8")
                with self.assertRaises(SystemExit) as cm:
                    B.client_public_key()
                self.assertIn(msg, str(cm.exception))
            cfg.write_text(f'PUBLIC_KEY_HEX = "{PUB.hex()}"\n', encoding="utf-8")
            self.assertEqual(B.client_public_key(allow_foreign=True), PUB.hex())
        finally:
            B.ROOT = orig
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repository_public_key_is_valid(self):
        from masterquo.licensing import client_config
        v = client_config.PUBLIC_KEY_HEX
        if v:                                                                      # wpisany klucz wydawcy: 64 hex i poprawny punkt Ed25519
            import nacl.bindings
            self.assertRegex(v, r"^[0-9a-f]{64}$")
            nacl.bindings.crypto_sign_ed25519_pk_to_curve25519(bytes.fromhex(v))


class TestClientApi(unittest.TestCase):
    """Serwer demo w edycji klienta: zablokowane API (402) do aktywacji, potem silnik startuje i API działa."""

    @classmethod
    def setUpClass(cls):
        from _demo_server import Server
        cls.S = Server
        cls.tmp = tempfile.mkdtemp(prefix="pmw_lic_api_")
        cls.e = env(PMW_EDITION="CLIENT", PMW_TEST_PUBLIC_KEY_HEX=PUB.hex(), PMW_LICENSE_FILE=str(Path(cls.tmp) / "license.dat"),
                    PMW_TEST_NET_OFFSET="none", PMW_TEST_HWID_SOURCES="guid-api|uuid-api")
        cls.e.__enter__()
        cls.here = H.get_hwid()
        try:
            Server.start_server()
        except Exception:
            cls.e.__exit__()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()
        cls.e.__exit__()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_locked_then_activated(self):
        c = self.S.call
        code, st = c("/api/v1/license/status")
        self.assertEqual(code, 200)
        self.assertEqual((st["edition"], st["required"], st["valid"], st["code"]), ("CLIENT", True, False, "NO_LICENSE"))
        self.assertEqual(st["hwid"], self.here)
        self.assertEqual(c("/api/v1/timeframes")[0], 402)                           # ekrany / dane zablokowane
        self.assertEqual(c("/api/v1/mode", {"mode": "PAPER"})[0], 402)               # tryb nie startuje
        self.assertEqual(c("/api/v1/license/require", {"action": "FOREX"})[0], 402)
        code, r = c("/api/v1/license/activate", {"key": "PMW1-zly"})
        self.assertEqual((code, r["valid"], r["code"]), (200, False, "FORMAT"))
        key = SG.sign_license(SK, "Klient API", self.here, int(time.time()), int(time.time() + 2 * DAY))
        code, r = c("/api/v1/license/activate", {"key": key})
        self.assertEqual((code, r["valid"], r["activated"]), (200, True, True))
        self.assertTrue(r["warn"])                                                  # 2 dni -> ostrzeżenie
        self.assertEqual(c("/api/v1/license/require", {"action": "FOREX"})[0], 200)
        self.assertEqual(c("/api/v1/timeframes")[0], 200)
        self.assertEqual(c("/api/v1/owner/license/state")[0], 404)                  # w edycji klienta brak endpointów generatora
        self.assertTrue(Path(self.tmp, "license.dat").exists())


if __name__ == "__main__":
    unittest.main()
