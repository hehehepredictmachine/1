"""1.46 arch (Etap 4): architecture tests - they keep the single-source-of-truth rules from regressing.

* ONE canonical model registry (quant/ids.py, expanded by quant/inventory.build): every row of every older registry (sh/models.REGISTRY,
  modelhub/families, trainhub/learn.MODELS, mm/inventory.MODULES, lab families) resolves into it; no producer appears twice;
* every producer has a live adapter OR a written reason (no silent gap), and exactly one smoke entry (models check --smoke) unless it is
  NO_SPEC / NOT_IMPLEMENTED; a smoke module never names an id outside the registry;
* the producers added in 1.46 (EXTRA_PRODUCERS) are invisible to resolve(): Quant feature columns are named after canonical ids, a new
  resolution would rename a trained model's inputs; the TiRex-2 aliases change no existing resolution;
* no import-time cycle in backend/masterquo (module-level imports + implicit parent-package imports);
* backend/vendor/ unchanged against the 1.46.0 release commit (reference code, `--legacy` tests run on its copy).
"""
from __future__ import annotations

import ast
import subprocess
import unittest
from collections import Counter
from pathlib import Path

import _env
from _env import TempData

PKG = _env.ROOT / "backend" / "masterquo"
BASE_COMMIT = "ee5888a"                    # 1.46.0 release (start of the architecture branch)


class TestCanonicalRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        from masterquo.quant import inventory as QI
        cls.inv = QI.build(None, "XAUUSD")

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_one_row_per_producer_and_everything_classified(self):
        ids = [e["id"] for e in self.inv["entries"]]
        self.assertEqual([k for k, n in Counter(ids).items() if n > 1], [])
        c = self.inv["coverage"]
        self.assertEqual(c["inventory"]["recognised"], c["inventory"]["classified"])
        self.assertEqual(c["adapters"]["missing"], [])                        # adapter or a written NOT_APPLICABLE reason

    def test_older_registries_are_views_of_the_canonical_one(self):
        from masterquo.lab import protocol as LP
        from masterquo.mm import inventory as MI
        from masterquo.modelhub.families import registry as famreg
        from masterquo.quant import ids as I
        from masterquo.sh import models as SM
        from masterquo.trainhub import learn
        ids = {e["id"] for e in self.inv["entries"]}
        missing = []
        for it in SM.REGISTRY:
            cid = I.resolve(it["id"]) or f"sh:{it['id']}"
            if cid not in ids and f"group:{it['id']}" not in ids:
                missing.append(("sh", it["id"]))
        for fid in famreg():
            if (I.resolve(fid) or f"family:{fid}") not in ids:
                missing.append(("family", fid))
        missing += [("trainhub", m) for m in learn.MODELS if f"trainhub:{m}" not in ids]
        missing += [("lab", f) for f in LP.FAMILIES if f"lab:{f}" not in ids]
        for m in MI.MODULES:
            if not ({f"mm:{m['id']}", I.resolve(m["id"]) or ""} & ids) and not any(m["id"] in a for e in self.inv["entries"] for a in e["aliases"]):
                missing.append(("mm", m["id"]))
        self.assertEqual(missing, [])

    def test_extra_producers_do_not_change_resolution(self):
        from masterquo.quant import ids as I
        for cid in I.EXTRA_PRODUCERS:
            if cid == "tsfm:tirex2":
                continue
            self.assertNotIn(cid, I._ALIAS_TO, cid)                            # never a new feature-column name
            self.assertNotIn(cid, I.ALIASES)
        # TiRex-2: the record always carried model_id tsfm:tirex2 -> canonical unchanged by the new aliases
        rec = {"model_key": "tirex2_M5", "model_id": "tsfm:tirex2", "model_name": "TiRex-2"}
        self.assertEqual(I.canonical(rec), "tsfm:tirex2")
        for c, al in I.ALIASES.items():
            for a in al:
                self.assertEqual(I.resolve(a), c, a)

    def test_every_producer_has_exactly_one_smoke_entry(self):
        from masterquo.modelhub import smoke as S
        need = {e["id"] for e in self.inv["entries"] if e["code_state"] == "IMPLEMENTED"}
        where: dict[str, list[str]] = {}
        for area in S.AREAS:
            smokes, nc = S.load_area(area)
            for cid in list(smokes) + list(nc):
                where.setdefault(cid, []).append(area)
        self.assertEqual({k: v for k, v in where.items() if len(v) > 1}, {})
        self.assertEqual(sorted(set(where) - {e["id"] for e in self.inv["entries"]}), [])   # no id outside the registry
        self.assertEqual(sorted(need - set(where)), [])


def _module_name(p: Path) -> str:
    rel = p.relative_to(PKG.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _import_graph() -> dict[str, set[str]]:
    mods = {_module_name(p): p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts}
    g: dict[str, set[str]] = {m: set() for m in mods}
    for m, p in mods.items():
        pkg = m if p.name == "__init__.py" else m.rsplit(".", 1)[0]
        # the implicit "parent package runs first" edge never fails an import (the parent is already in sys.modules); only an EXPLICIT
        # need of names from a module that is still initialising does - those edges are collected below
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in tree.body:                                                  # module level only (function-level imports run later)
            stmts = [node]
            if isinstance(node, ast.If | ast.Try):
                stmts = [n for n in ast.walk(node) if isinstance(n, ast.Import | ast.ImportFrom)]
            for st in stmts:
                if isinstance(st, ast.Import):
                    names = [a.name for a in st.names]
                elif isinstance(st, ast.ImportFrom):
                    if st.level:
                        base = pkg.split(".")
                        base = base[:len(base) - (st.level - 1)] if st.level > 1 else base
                        mod = ".".join(base + ([st.module] if st.module else []))
                    else:
                        mod = st.module or ""
                    # `from pkg import sub` needs the submodule only; `from pkg import NAME` needs the initialised package
                    names = [f"{mod}.{a.name}" if f"{mod}.{a.name}" in mods else mod for a in st.names]
                else:
                    continue
                for n in names:
                    if n in mods and n != m:
                        g[m].add(n)
    return g


def _sccs(g: dict[str, set[str]]) -> list[list[str]]:
    index, low, on, stack, out, i = {}, {}, set(), [], [], [0]

    def strong(v):
        index[v] = low[v] = i[0]
        i[0] += 1
        stack.append(v)
        on.add(v)
        for w in g[v]:
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(comp)
    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 10000))
    try:
        for v in g:
            if v not in index:
                strong(v)
    finally:
        sys.setrecursionlimit(old)
    return out


class TestNoImportCycles(unittest.TestCase):
    def test_no_import_time_cycle(self):
        cyc = [sorted(c) for c in _sccs(_import_graph()) if len(c) > 1]
        self.assertEqual(cyc, [])


class TestVendorUntouched(unittest.TestCase):
    def test_vendor_unchanged_since_1_46_0(self):
        try:
            known = subprocess.run(["git", "-C", str(_env.ROOT), "cat-file", "-e", BASE_COMMIT], capture_output=True, check=False).returncode == 0
        except OSError:
            known = False
        if not known:
            self.skipTest("brak repozytorium git / commitu 1.46.0 (paczka wydania)")
        r = subprocess.run(["git", "-C", str(_env.ROOT), "diff", "--name-only", BASE_COMMIT, "--", "backend/vendor"], capture_output=True, text=True,
                           check=False)
        u = subprocess.run(["git", "-C", str(_env.ROOT), "status", "--porcelain", "--", "backend/vendor"], capture_output=True, text=True, check=False)
        self.assertEqual((r.stdout + u.stdout).strip(), "")


if __name__ == "__main__":
    unittest.main()
