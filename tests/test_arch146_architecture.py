"""1.46 arch (Etap 4): architecture tests - they keep the single-source-of-truth rules from regressing.

* ONE canonical model registry (quant/ids.py, expanded by quant/inventory.build): every row of every older registry (sh/models.REGISTRY,
  modelhub/families, trainhub/learn.MODELS, mm/inventory.MODULES, lab families) resolves into it; no producer appears twice;
* every producer has a live adapter OR a written reason (no silent gap), and exactly one smoke entry (models check --smoke) unless it is
  NO_SPEC / NOT_IMPLEMENTED; a smoke module never names an id outside the registry;
* the producers added in 1.46 (EXTRA_PRODUCERS) are invisible to resolve(): Quant feature columns are named after canonical ids, a new
  resolution would rename a trained model's inputs; the TiRex-2 aliases change no existing resolution;
* no second source of producer ids (Etap 4, TestNoSecondIdSource): the inventory lists exactly quant/ids.PRODUCERS (+ the GROUPS rows);
  every SH row, MM module, catalog row, inventory overlay key and model-map overlay id is derived from / declared in quant/ids; no module
  outside quant/ids keeps an alias table, and the view modules keep no literal list of producer names;
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


VIEW_MODULES = ("backend/masterquo/sh/models.py", "backend/masterquo/modelhub/catalog.py", "backend/masterquo/mm/inventory.py",
                "backend/masterquo/quant/inventory.py", "tools/model_map.py", "backend/masterquo/modelhub/families/service.py",
                "backend/masterquo/modelhub/families/run.py", "backend/masterquo/studio/registry.py")
# dicts mapping a name to another name of the SAME producer outside quant/ids, with the reason they are not a second alias table
ALIAS_DICT_ALLOWED = {
    ("backend/masterquo/tsfm/service.py", "NAMES"): "display names of the TSFM owner (tsfm/service) - quant/ids.ALIASES lists them as aliases",
}


def _names_of_one_producer_pairs(node, I) -> list[tuple[str, str]]:
    out = []
    for k, v in zip(node.keys, node.values):
        if isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Constant) and isinstance(v.value, str):
            ck, cv = I.resolve(k.value), I.resolve(v.value)
            if ck and ck == cv and k.value != v.value:
                out.append((k.value, v.value))
    return out


class TestNoSecondIdSource(unittest.TestCase):
    """1.46 arch Etap 4 (ETAP2 §3/§4 "tożsamość modelu"): quant/ids (+ PRODUCERS) is the ONLY source of producer ids; sh/models.REGISTRY,
    modelhub/catalog, mm/inventory, quant/inventory and tools/model_map are views - they describe producers and derive their ids there."""

    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        from masterquo.modelhub import catalog as CT
        from masterquo.quant import inventory as QI
        cls.inv = QI.build(None, "XAUUSD")
        cls.cat = CT.build(None, "XAUUSD")

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_inventory_lists_exactly_the_declared_producers(self):
        from masterquo.quant import ids as I
        rows = [e["id"] for e in self.inv["entries"] if e["code_state"] != "GROUP"]
        self.assertEqual(sorted(set(rows) - set(I.PRODUCERS)), [])          # no view adds an id quant/ids does not declare
        self.assertEqual(sorted(set(I.PRODUCERS) - set(rows)), [])          # no declared producer is missing from the inventory
        self.assertEqual(sorted(e["id"] for e in self.inv["entries"] if e["code_state"] == "GROUP"), sorted(f"group:{g}" for g in I.GROUPS))
        self.assertEqual(sorted(set(I.PRODUCERS) & set(I.HISTORY_IDS)), [])

    def test_declared_tables_change_no_resolution(self):
        """The Etap 4 tables are metadata: resolve() / canonical() (Quant feature column names) never see their names."""
        from masterquo.quant import ids as I
        for name in list(I.SERVICES) + list(I.NOT_IMPLEMENTED) + list(I.MM_MODULES) + list(I.CATALOG_ROWS):
            self.assertNotIn(name, I._ALIAS_TO, name)
        for name in I.MM_MODULES:
            self.assertIsNone(I.resolve(name), name)

    def test_views_derive_every_id_from_quant_ids(self):
        from masterquo.mm import inventory as MI
        from masterquo.modelhub import catalog as CT
        from masterquo.quant import ids as I
        from masterquo.quant import inventory as QI
        from masterquo.sh import models as SM
        known = set(I.PRODUCERS) | {f"group:{g}" for g in I.GROUPS}
        sh_ids = [it["id"] for it in SM.REGISTRY]
        self.assertEqual([s for s in sh_ids if I.sh_row_id(s) not in known], [])           # every SH row = alias / group of quant/ids
        self.assertEqual({I.sh_row_id(it["id"]) for it in SM.REGISTRY if it["kind"] == "DETERMINISTIC" and not it["id"].startswith("mm_")},
                         {f"rule:{r}" for r in I.RULES})
        self.assertEqual([m["id"] for m in MI.MODULES if I.mm_module_id(m["id"]) not in known], [])
        self.assertEqual(set(I.MM_MODULES), {m["id"] for m in MI.MODULES if I.resolve(m["id"]) is None})
        self.assertEqual({r["id"]: r.get("canonical_id") for r in self.cat["items"] if r.get("canonical_id") not in known}, {})
        self.assertEqual(set(CT.LOCATION), set(sh_ids))                                       # description overlay of the SH rows only
        self.assertEqual(sorted(set(I.CATALOG_ROWS.values()) - known), [])
        self.assertEqual(sorted(set(QI._OVR) - known), [])
        self.assertEqual(list(QI._ANALYSIS), list(I.SERVICES))
        self.assertEqual(set(QI._NOT_IMPLEMENTED), set(I.NOT_IMPLEMENTED))
        self.assertEqual(sorted(set(I.REQUIRED_EXTENDED) - known), [])
        self.assertEqual(sorted(set(I.REQUIRED_RESEARCH) - known), [])
        import importlib
        import sys
        sys.path.insert(0, str(_env.ROOT / "tools"))
        try:
            MM = importlib.import_module("model_map")
        finally:
            sys.path.remove(str(_env.ROOT / "tools"))
        self.assertEqual(sorted(set(MM.CANON.values()) - known), [])

    def test_owner_lists_match_quant_ids(self):
        from masterquo.modelhub.families import registry as famreg
        from masterquo.quant import ids as I
        from masterquo.tsfm import settings as TS
        self.assertEqual(I.TSFM_MODELS, TS.MODEL_IDS)
        fams = famreg()
        self.assertEqual(set(I.FAMILY_OWNED), {f for f in fams if (I.resolve(f) or "").startswith("family:")})
        self.assertEqual([f for f in fams if I.resolve(f) is None], [])                        # no family outside quant/ids

    def test_no_second_alias_table(self):
        """No module outside quant/ids maps a name of a producer to another name of the same producer (the I0009 class: '"mm_gpr":
        "gpr_logret"', _MM_TO_CANON); the view modules hold no literal list of >= 3 producer names (they read quant/ids)."""
        from masterquo.quant import ids as I
        files = [p for p in list(PKG.rglob("*.py")) + list((_env.ROOT / "tools").glob("*.py")) if "__pycache__" not in p.parts]
        bad = []
        for p in files:
            rel = p.relative_to(_env.ROOT).as_posix()
            if rel == "backend/masterquo/quant/ids.py":
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            names = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign | ast.AnnAssign):
                    tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    if isinstance(tgt, ast.Name):
                        names[id(node.value)] = tgt.id
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    pairs = _names_of_one_producer_pairs(node, I)
                    if len(pairs) >= 2 and (rel, names.get(id(node))) not in ALIAS_DICT_ALLOWED:
                        bad.append((rel, node.lineno, pairs[:3]))
                if rel in VIEW_MODULES and isinstance(node, ast.Tuple | ast.List | ast.Set):
                    strs = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                    ids = [s for s in strs if I.resolve(s) and ":" not in s]
                    if len(ids) >= 3 and len(ids) == len(node.elts):
                        bad.append((rel, node.lineno, ids[:4]))
        self.assertEqual(bad, [])


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
