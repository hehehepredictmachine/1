"""1.46 arch (Etap 3, diagnoza trening#0, K): activation registries read an unreadable file as EMPTY and wrote that view back.

lab ACTIVE.json (lab/protocol.py), mm SHADOW_ACTIVE.json (mm/artifacts.py), Monte Carlo registry.json (montecarlo/validate.py) and the
Quant MetaModel ACTIVE.json (quant/metamodel.py) lost the active model, the rollback history and the seen-test list when the file was
momentarily unreadable (antivirus / indexer lock, truncated write). After the fix every read-modify-write goes through
masterquo.registry_io (strict read, unique tmp + os.replace, file lock): the call fails and the file stays byte-for-byte unchanged.
Display readers still get the empty view (unchanged behaviour). On 1.46.0 every test of the first class fails (file overwritten).
"""
from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

BROKEN = '{"active": {"F": "m1"}, "history": [{"fam'               # truncated write


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _corrupt(self, p: Path) -> bytes:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(BROKEN, encoding="utf-8")
        return p.read_bytes()


class TestUnreadableRegistryIsNeverOverwritten(_Base):
    def test_lab_pointer(self):
        from masterquo import registry_io as RIO
        from masterquo.lab import protocol as P
        root = Path(self.td.dir) / "lab"
        before = self._corrupt(P.pointer_path(root, "XAUUSD"))
        with self.assertRaises(RIO.RegistryUnreadable):
            P.set_active(root, "XAUUSD", "LOGREG", None, "test")
        self.assertEqual(P.pointer_path(root, "XAUUSD").read_bytes(), before)
        with self.assertRaises(RIO.RegistryUnreadable):
            P.rollback_family(root, "XAUUSD", "LOGREG")
        self.assertEqual(P.pointer_path(root, "XAUUSD").read_bytes(), before)
        self.assertEqual(P.read_pointer(root, "XAUUSD").get("active"), {})   # display view unchanged (empty, not a crash)

    def test_mm_shadow_pointer(self):
        from masterquo import registry_io as RIO
        from masterquo.mm import artifacts as A
        aid = A.save("XAUUSD", "hdc_dir3", {"w": [1.0, 2.0]}, {"status": "VALIDATED_SHADOW"})
        p = A._ptr_path("XAUUSD")
        before = self._corrupt(p)
        with self.assertRaises(RIO.RegistryUnreadable):
            A.promote_shadow("XAUUSD", "hdc_dir3", aid, "test")
        self.assertEqual(p.read_bytes(), before)
        with self.assertRaises(RIO.RegistryUnreadable):
            A.rollback("XAUUSD", "hdc_dir3")
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(A.read_pointer("XAUUSD").get("active"), {})

    def test_montecarlo_registry(self):
        from masterquo import registry_io as RIO
        from masterquo.montecarlo import validate as V
        p = V.root("XAUUSD") / "registry.json"
        before = self._corrupt(p)
        with self.assertRaises(RIO.RegistryUnreadable):
            V.save("XAUUSD", {"status": "DONE", "data_kind": "SYNTHETIC_TEST", "verdict": "BRAK_PRZEWAGI"})
        self.assertEqual(p.read_bytes(), before)
        self.assertIsNone(V.active_calibrator("XAUUSD"))

    def test_quant_metamodel_pointer(self):
        from masterquo import registry_io as RIO
        from masterquo.quant import metamodel as M
        p = M._ptr("XAUUSD")
        before = self._corrupt(p)
        for fn in (lambda: M.rollback("XAUUSD", "t1"), lambda: M.record_test("XAUUSD", "t1", ["a"])):
            with self.assertRaises(RIO.RegistryUnreadable):
                fn()
            self.assertEqual(p.read_bytes(), before)
        self.assertEqual(M.pointer("XAUUSD").get("active"), {})


class TestRegistryWritesKeepWorking(_Base):
    """Same results as 1.46.0 on readable files (the fix only adds the strict read, the lock and the unique tmp)."""

    def test_lab_set_and_rollback(self):
        from masterquo.lab import protocol as P
        root = Path(self.td.dir) / "lab"
        for mid in ("m1", "m2"):
            d = root / "models" / "XAUUSD" / mid
            d.mkdir(parents=True)
            (d / "manifest.json").write_text("{}", encoding="utf-8")
        P.set_active(root, "XAUUSD", "LOGREG", "m1", "a")
        P.set_active(root, "XAUUSD", "LOGREG", "m2", "b")
        self.assertEqual(P.read_pointer(root, "XAUUSD")["active"], {"LOGREG": "m2"})
        P.rollback_family(root, "XAUUSD", "LOGREG")
        self.assertEqual(P.read_pointer(root, "XAUUSD")["active"], {"LOGREG": "m1"})
        self.assertEqual(sorted(x.name for x in (root / "models" / "XAUUSD").iterdir() if x.suffix == ".tmp"), [])

    def test_quant_pointer_seen_tests_survive(self):
        from masterquo.quant import metamodel as M
        M.record_test("XAUUSD", "t1", ["a"])
        M.record_test("XAUUSD", "t1", ["b"])
        self.assertEqual(M.pointer("XAUUSD")["seen_tests"]["t1"], [["a"], ["b"]])

    def test_montecarlo_save_keeps_runs(self):
        from masterquo.montecarlo import validate as V
        r1 = V.save("XAUUSD", {"status": "DONE", "data_kind": "SYNTHETIC_TEST", "verdict": "BRAK_PRZEWAGI", "n": 1})
        r2 = V.save("XAUUSD", {"status": "DONE", "data_kind": "SYNTHETIC_TEST", "verdict": "BRAK_PRZEWAGI", "n": 2})
        reg = json.loads((V.root("XAUUSD") / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(reg["runs"]), sorted([r1["run_id"], r2["run_id"]]))
        self.assertIsNone(reg["active"])                                       # synthetic never activates (unchanged)

    def test_concurrent_writers_do_not_lose_updates(self):
        from masterquo.quant import metamodel as M
        errs = []

        def w(i):
            try:
                for k in range(10):
                    M.record_test("XAUUSD", f"t{i}", [str(k)])
            except Exception as exc:  # noqa: BLE001
                errs.append(exc)
        ts = [threading.Thread(target=w, args=(i,)) for i in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        seen = M.pointer("XAUUSD")["seen_tests"]
        self.assertEqual({k: len(v) for k, v in seen.items()}, {f"t{i}": 10 for i in range(4)})


class TestRegistryIo(_Base):
    def test_read_json_modes(self):
        from masterquo import registry_io as RIO
        p = Path(self.td.dir) / "r.json"
        self.assertEqual(RIO.read_json(p, dict, strict=True), {})
        p.write_text("[1, 2]", encoding="utf-8")                              # valid JSON but not an object
        with self.assertRaises(RIO.RegistryUnreadable):
            RIO.read_json(p, dict, strict=True)
        self.assertEqual(RIO.read_json(p, dict, strict=False), {"error": "REGISTRY_UNREADABLE"})
        RIO.write_json_atomic(p, {"a": 1})
        self.assertEqual(RIO.read_json(p, dict, strict=True), {"a": 1})
        self.assertEqual([x.name for x in p.parent.iterdir() if x.name.endswith(".tmp")], [])

    def test_trainhub_reg_lock_uses_the_shared_lock(self):
        from masterquo import registry_io as RIO
        from masterquo.trainhub import registry as R
        with R.reg_lock("XAUUSD"), R.reg_lock("XAUUSD"):                    # re-entrant, as before
            key = str(Path(R._reg_path("XAUUSD").with_name("registry.lock")).resolve())
            self.assertEqual(RIO._HELD.__dict__["n"].get(key), 2)


if __name__ == "__main__":
    unittest.main()
