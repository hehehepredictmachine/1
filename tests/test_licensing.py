"""1.43.0 Generator licencji PMW1 (Ed25519, offline): format klucza, podpis, wygaśnięcie, HWID, magazyn właściciela, API."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import _env  # noqa: F401 - ścieżki backendu
from _env import TempData

from masterquo.licensing import hwid as H
from masterquo.licensing import license_key as LK
from masterquo.licensing import signing as SG
from masterquo.licensing.owner import LicenseInputError, OwnerLicenses, owner_dir, parse_key_file

import nacl.signing

HW = "A1B2C-D3E4F-G5H6J-K7M8N"


class TestKeyFormat(unittest.TestCase):
    def setUp(self):
        self.sk = nacl.signing.SigningKey(bytes(range(32)))
        self.pub = bytes(self.sk.verify_key)
        self.now = 1_800_000_000

    def key(self, hw=HW, exp=None, user="Jan Kowalski"):
        return SG.sign_license(self.sk, user, hw, self.now, exp)

    def test_generate_and_read_with_hwid(self):
        k = self.key(exp=self.now + 30 * 86400)
        self.assertTrue(k.startswith("PMW1-"))
        r = LK.read_license(k, self.pub, now=self.now + 10, hwid=HW)
        self.assertTrue(r["valid"], r["errors"])
        self.assertTrue(r["signature_ok"])
        self.assertEqual((r["user"], r["hwid"], r["iat"], r["exp"]), ("Jan Kowalski", HW, self.now, self.now + 30 * 86400))
        self.assertEqual(r["payload"], {"v": 1, "u": "Jan Kowalski", "hw": HW, "iat": self.now, "exp": self.now + 30 * 86400})
        self.assertIs(r["hwid_match"], True)
        self.assertIs(r["perpetual"], False)

    def test_without_hwid_and_perpetual(self):
        r = LK.read_license(self.key(hw=None, exp=None), self.pub, now=self.now + 10 ** 9, hwid=HW)
        self.assertTrue(r["valid"], r["errors"])
        self.assertIsNone(r["hwid"])
        self.assertIsNone(r["hwid_match"])                                   # licencja bez HWID działa na każdym komputerze
        self.assertTrue(r["perpetual"])
        self.assertFalse(r["expired"])

    def test_expired(self):
        k = self.key(exp=self.now + 7 * 86400)
        r = LK.read_license(k, self.pub, now=self.now + 7 * 86400 + 1)
        self.assertTrue(r["signature_ok"])
        self.assertTrue(r["expired"])
        self.assertFalse(r["valid"])
        self.assertIn("licencja wygasła", r["errors"])
        self.assertTrue(LK.read_license(k, self.pub, now=self.now + 7 * 86400 - 1)["valid"])

    def test_every_single_character_change_breaks_the_key(self):
        """Zmieniony 1 znak = klucz nieważny (podpis albo zapis) – na KAŻDEJ pozycji części base64url, także na ostatnim znaku."""
        k = self.key(exp=self.now + 86400)
        body_start = len(LK.PREFIX)
        for i in range(body_start, len(k)):
            for repl in ("A", "z", "_"):
                if k[i] == repl:
                    continue
                bad = k[:i] + repl + k[i + 1:]
                r = LK.read_license(bad, self.pub, now=self.now)
                self.assertFalse(r["valid"], f"pozycja {i}: {bad}")
                break
        r = LK.read_license(k[:20] + ("B" if k[20] != "B" else "C") + k[21:], self.pub, now=self.now)
        self.assertFalse(r["signature_ok"])

    def test_last_char_noncanonical_rejected(self):
        k = self.key()
        body = k[len(LK.PREFIX):]
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        same_bytes = [c for c in alphabet if c != body[-1] and LK.base64.urlsafe_b64decode(body[:-1] + c + "=" * (-len(body) % 4))
                      == LK.base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))]
        for c in same_bytes:                                                 # te same bajty, inny tekst -> też odrzucone
            r = LK.read_license(LK.PREFIX + body[:-1] + c, self.pub, now=self.now)
            self.assertFalse(r["valid"])
            self.assertIn("niekanoniczny", " ".join(r["errors"]))

    def test_wrong_owner_key_and_wrong_hwid(self):
        k = self.key(exp=None)
        other = bytes(nacl.signing.SigningKey.generate().verify_key)
        r = LK.read_license(k, other, now=self.now)
        self.assertFalse(r["signature_ok"])
        self.assertFalse(r["valid"])
        r = LK.read_license(k, self.pub, now=self.now, hwid="ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ")
        self.assertTrue(r["signature_ok"])
        self.assertIs(r["hwid_match"], False)
        self.assertFalse(r["valid"])

    def test_bad_prefix_and_garbage(self):
        k = self.key()
        for bad in ("", "PMW2-" + k[5:], k[5:], "PMW1-", "PMW1-@@@", "PMW1-AAAA"):
            self.assertFalse(LK.read_license(bad, self.pub, now=self.now)["valid"], bad)
        self.assertTrue(LK.read_license("  " + k[:40] + "\n" + k[40:] + " ", self.pub, now=self.now)["valid"])   # spacje z kopiowania

    def test_unicode_user(self):
        r = LK.read_license(self.key(user="Łukasz Żółć"), self.pub, now=self.now)
        self.assertTrue(r["valid"])
        self.assertEqual(r["user"], "Łukasz Żółć")


class TestHwid(unittest.TestCase):
    def test_format_and_determinism(self):
        h = H.hwid_from_sources("4c4c4544-0042-3510-8048-b4c04f4d4b32", "00112233-4455-6677-8899-AABBCCDDEEFF")
        self.assertRegex(h, H.HWID_RE)
        self.assertEqual(h, H.hwid_from_sources("4C4C4544-0042-3510-8048-B4C04F4D4B32 ", "00112233-4455-6677-8899-aabbccddeeff"))
        self.assertNotEqual(h, H.hwid_from_sources("4c4c4544-0042-3510-8048-b4c04f4d4b32", None))
        self.assertRegex(H.hwid_from_sources(None, "00112233-4455-6677-8899-AABBCCDDEEFF"), H.HWID_RE)
        with self.assertRaises(H.HwidError):
            H.hwid_from_sources(None, " ")

    def test_normalize(self):
        self.assertEqual(H.normalize_hwid(" a1b2c-d3e4f-g5h6j-k7m8n "), HW)
        for bad in ("A1B2C-D3E4F-G5H6J", "A1B2C-D3E4F-G5H6J-K7M8NX", "I1B2C-D3E4F-G5H6J-K7M8N", "A1B2C-D3E4F-G5H6J-K7M8O",
                    "A1B2CD3E4FG5H6JK7M8N", "", None):
            self.assertIsNone(H.normalize_hwid(bad), bad)

    def test_smbios_type1_uuid(self):
        u = uuid.UUID("4C4C4544-0042-3510-8048-B4C04F4D4B32")
        t0 = bytes([0, 0x18, 0, 0]) + bytes(0x14) + b"Vendor\x00\x00"                   # typ 0 z napisem
        t1 = bytes([1, 0x1B, 1, 0]) + bytes(4) + u.bytes_le + bytes(0x1B - 24) + b"\x00\x00"
        t127 = bytes([127, 4, 2, 0]) + b"\x00\x00"
        self.assertEqual(H.parse_smbios_uuid(t0 + t1 + t127), str(u).upper())
        self.assertIsNone(H.parse_smbios_uuid(bytes([1, 0x1B, 1, 0]) + bytes(4) + b"\xff" * 16 + bytes(3) + b"\x00\x00"))
        self.assertIsNone(H.parse_smbios_uuid(t0 + t127))

    def test_get_hwid_from_env_sources(self):
        os.environ["PMW_TEST_HWID_SOURCES"] = "guid-1|uuid-2"
        H._sources.cache_clear()
        try:
            self.assertEqual(H.get_hwid(), H.hwid_from_sources("guid-1", "uuid-2"))
            self.assertEqual(H.hwid_sources(), {"machine_guid": True, "board_uuid": True})
        finally:
            os.environ.pop("PMW_TEST_HWID_SOURCES")
            H._sources.cache_clear()


class TestOwnerStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pmw_owner_")
        self.t = [1_800_000_000.0]
        self.o = OwnerLicenses(Path(self.tmp) / "owner", clock=lambda: self.t[0])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keys_create_once_export_import(self):
        st = self.o.state()
        self.assertFalse(st["has_key"])
        st = self.o.create_keypair()
        self.assertTrue(st["has_key"])
        self.assertRegex(st["public_key"], r"^[0-9a-f]{64}$")
        if os.name != "nt":
            self.assertEqual(os.stat(self.o.key_path).st_mode & 0o777, 0o600)
        with self.assertRaises(LicenseInputError):
            self.o.create_keypair()                                         # druga para unieważniłaby wydane licencje
        ex = self.o.export_key()
        self.assertTrue(ex["filename"].endswith(".key"))
        self.assertEqual(parse_key_file(ex["content"])[1].hex(), st["public_key"])
        # przywrócenie z kopii na „nowym komputerze”
        o2 = OwnerLicenses(Path(self.tmp) / "owner2", clock=lambda: self.t[0])
        r = o2.import_key(ex["content"])
        self.assertTrue(r["imported"])
        self.assertEqual(r["public_key"], st["public_key"])
        self.assertTrue(o2.import_key(ex["content"])["same_key"])
        # inny klucz: bez potwierdzenia odmowa, z potwierdzeniem zastąpienie + kopia poprzedniego
        other = nacl.signing.SigningKey.generate()
        with self.assertRaises(LicenseInputError) as cm:
            o2.import_key(bytes(other).hex())
        self.assertEqual(cm.exception.field, "key_file")
        r = o2.import_key(bytes(other).hex(), replace=True)
        self.assertEqual(r["public_key"], bytes(other.verify_key).hex())
        self.assertTrue(Path(r["previous_key_backup"]).exists())
        for bad in ("", "abc", "PMW-OWNER-ED25519-PRIVATE-KEY v1\nseed: " + "0" * 64 + "\npublic: " + "1" * 64):
            with self.assertRaises(LicenseInputError):
                o2.import_key(bad, replace=True)

    def test_generate_validation_history_check(self):
        with self.assertRaises(LicenseInputError) as cm:
            self.o.generate("Jan", HW, False, {"kind": "days", "days": 30})
        self.assertEqual(cm.exception.field, "keys")                       # bez kluczy nie da się wydać licencji
        self.o.create_keypair()
        for args, field in [(("  ", HW, False, {"kind": "days", "days": 30}), "user"),
                            (("Jan", "ZLY-HWID", False, {"kind": "days", "days": 30}), "hwid"),
                            (("Jan", "", False, {"kind": "days", "days": 30}), "hwid"),
                            (("Jan", None, True, {"kind": "days", "days": 31}), "validity"),
                            (("Jan", None, True, {"kind": "date", "date": "2020-01-01"}), "validity"),
                            (("Jan", None, True, {"kind": "date", "date": "jutro"}), "validity"),
                            (("Jan", None, True, None), "validity")]:
            with self.assertRaises(LicenseInputError) as cm:
                self.o.generate(*args)
            self.assertEqual(cm.exception.field, field, args)
        a = self.o.generate("Jan Kowalski", "a1b2c-d3e4f-g5h6j-k7m8n", False, {"kind": "days", "days": 30}, "klient VIP")
        self.assertEqual(a["hwid"], HW)
        self.assertEqual(a["exp"], int(self.t[0]) + 30 * 86400)
        b = self.o.generate("Anna", None, True, {"kind": "perpetual"})
        self.assertIsNone(b["hwid"])
        self.assertTrue(b["perpetual"])
        c = self.o.generate("Piotr", HW, False, {"kind": "date", "date": "2027-03-31"})
        self.assertEqual(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(c["exp"])), "2027-03-31 23:59:59")
        self.assertEqual(len(self.o.list()), 3)
        chk = self.o.check(a["key"])
        self.assertTrue(chk["valid"] and chk["signature_ok"])
        self.assertEqual(chk["user"], "Jan Kowalski")
        # po 31 dniach licencja 30-dniowa jest wygasła (status liczony z daty), bezterminowa aktywna
        self.t[0] += 31 * 86400
        st = {r["user"]: r["status"] for r in self.o.list()}
        self.assertEqual(st, {"Jan Kowalski": "WYGASLA", "Anna": "AKTYWNA", "Piotr": "AKTYWNA"})
        self.assertFalse(self.o.check(a["key"])["valid"])
        self.assertEqual(self.o.delete(a["id"]), {"deleted": 1})
        self.assertEqual(len(self.o.list()), 2)

    def test_owner_dir_outside_program(self):
        from masterquo import paths
        prev = os.environ.pop("PMW_OWNER_DIR", None)
        try:
            d = owner_dir().resolve()
            self.assertNotIn(paths.ROOT_DIR.resolve(), [d, *d.parents])     # klucz nigdy w folderze programu / repozytorium
            self.assertEqual(d.name, "owner")
            self.assertEqual(d.parent.name, "PepeMarketWizard")
        finally:
            if prev is not None:
                os.environ["PMW_OWNER_DIR"] = prev


class TestApi(unittest.TestCase):
    """Endpointy na prawdziwym serwerze demo: klucze, generowanie, historia, sprawdzanie, CSRF."""

    @classmethod
    def setUpClass(cls):
        from _demo_server import Server
        cls.S = Server
        cls.own = tempfile.mkdtemp(prefix="pmw_owner_api_")
        os.environ["PMW_OWNER_DIR"] = cls.own
        try:
            Server.start_server()
        finally:
            os.environ.pop("PMW_OWNER_DIR", None)

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()
        import shutil
        shutil.rmtree(cls.own, ignore_errors=True)

    def delete(self, path):
        from _demo_server import BASE
        req = urllib.request.Request(BASE + path, data=b"{}", method="DELETE",
                                     headers={"Content-Type": "application/json", "Origin": BASE, "X-MQ-CSRF": self.S.csrf})
        with self.S.op.open(req, timeout=30) as r:
            return r.status

    def test_flow(self):
        c = self.S.call
        st = c("/api/v1/owner/license/state")[1]
        self.assertTrue(st["crypto_ok"])
        self.assertFalse(st["has_key"])
        self.assertTrue(st["key_path"].startswith(self.own))
        self.assertEqual(c("/api/v1/owner/license/keys", {}, csrf=False)[0], 403)        # bez CSRF – odmowa
        self.assertEqual(c("/api/v1/owner/license/generate", {"user": "x", "no_hwid": True, "validity": {"kind": "perpetual"}})[0], 400)
        code, st = c("/api/v1/owner/license/keys", {})
        self.assertEqual(code, 200)
        self.assertTrue(st["has_key"])
        self.assertTrue(Path(self.own, "private.key").exists())
        self.assertEqual(c("/api/v1/owner/license/keys", {})[0], 400)                     # druga para – odmowa
        hw = c("/api/v1/owner/license/hwid")[1]
        self.assertRegex(hw["hwid"] or HW, H.HWID_RE)
        code, err = c("/api/v1/owner/license/generate", {"user": "", "hwid": HW, "validity": {"kind": "days", "days": 30}})
        self.assertEqual(code, 400)
        self.assertTrue(err["detail"].startswith("user: "))
        code, lic = c("/api/v1/owner/license/generate", {"user": "Klient 1", "hwid": HW, "validity": {"kind": "days", "days": 90}, "note": "test"})
        self.assertEqual(code, 200, lic)
        code, chk = c("/api/v1/owner/license/check", {"key": lic["key"]})
        self.assertTrue(chk["valid"] and chk["signature_ok"])
        self.assertEqual((chk["user"], chk["hwid"]), ("Klient 1", HW))
        bad = lic["key"][:-5] + ("A" if lic["key"][-5] != "A" else "B") + lic["key"][-4:]
        self.assertFalse(c("/api/v1/owner/license/check", {"key": bad})[1]["valid"])
        rows = c("/api/v1/owner/licenses")[1]["licenses"]
        self.assertEqual([(r["user"], r["status"]) for r in rows], [("Klient 1", "AKTYWNA")])
        ex = c("/api/v1/owner/license/keys/export", {})[1]
        self.assertIn("seed:", ex["content"])
        self.assertEqual(c("/api/v1/owner/license/keys/import", {"content": ex["content"]})[1]["same_key"], True)
        self.assertEqual(self.delete(f"/api/v1/owner/licenses/{rows[0]['id']}"), 200)
        self.assertEqual(c("/api/v1/owner/licenses")[1]["licenses"], [])


if __name__ == "__main__":
    unittest.main()
