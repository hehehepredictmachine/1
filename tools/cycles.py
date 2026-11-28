"""Import graph of backend/masterquo and the LAYER GUARD (1.46 arch, I0084).

The architecture test (tests/test_arch146_architecture.py) only forbids import-TIME cycles (module-level imports). Lazy imports inside
functions closed one SCC of 27 domain packages: the trading core reaches lazily into research / SHADOW layers and nothing stopped a new
such edge. This module defines the layer map (Etap 2, docs/arch146/ETAP2_PROJEKT.md §3a) and collects EVERY internal import with its line
- module level, inside functions / methods, and dynamic `__import__("masterquo...")` / `importlib.import_module("masterquo...")` with a
literal name - so a test can compare today's UPWARD edges (a lower layer importing a higher one) with a recorded baseline.

  L0 leaves / infrastructure    L1 data and external I/O    L2 analyses    L3 trading core    L4 SHADOW / research / models
  L5 composition roots (runtime, API, CLI, Studio, training orchestrator)

An edge between two components of the same layer is allowed; an edge from layer a to layer b > a is UPWARD. Existing upward edges are the
baseline (tests/data/layer_baseline.json, keyed by "source module -> target module"; line numbers are informative only, so editing a file
does not break the guard). A NEW upward pair fails the test; an edge that disappeared is only reported. Moving imports and injected ports
are Etap 4 - nothing here changes the code that runs.

  python tools/cycles.py                      summary: layers, upward edges, new / removed against the baseline
  python tools/cycles.py --write-baseline     rewrite tests/data/layer_baseline.json from the current code (after a REVIEWED change)
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "backend" / "masterquo"
BASELINE = ROOT / "tests" / "data" / "layer_baseline.json"

LAYER_NAMES = {0: "L0 liście", 1: "L1 dane", 2: "L2 analizy", 3: "L3 rdzeń handlowy", 4: "L4 SHADOW/badania", 5: "L5 kompozycja"}
# top-level component of masterquo (sub-package or top-level module) -> layer. A component missing here fails the test (classify it).
LAYERS: dict[str, int] = {
    # L0 - leaves: paths, clocks, version, bus, registry I/O, config and its presets, small shared registries
    "masterquo": 0, "paths": 0, "timeutil": 0, "version": 0, "events": 0, "registry_io": 0, "sysres": 0, "secrets_store": 0,
    "resources": 0, "assets": 0, "media": 0, "prefs": 0, "config": 0, "presets": 0,
    # (after the merge of wave 2b) import-free / stdlib-only leaves: contract records (I0082), settings files (I0097), the local-API
    # client of the CLI entry points (I0075/I0080, imports only config/paths), the model-runtime environment registry (I0117, paths only)
    "contracts": 0, "settings_store": 0, "localapi": 0, "runtimes": 0,
    # (after the merge of training_studio) the registry of the server's training child processes and kill_tree (I0100, stdlib only;
    # one lazy helper import of training.core._proc_start - baseline edge, candidate for L0 in Etap 4)
    "procs": 0,
    # (Etap 4 pkt 4) the cost resolver PMW-COSTS-1: declared per-track cost policies + arithmetic, standard library only - every track
    # (risk / sh in L3, scalp / evaluation / quant in L4) imports it without an upward edge
    "costs": 0,
    # L1 - data and external I/O: database, MT5 bridge, market data stores, data quality, news, notifications, licence
    "db": 1, "mt5": 1, "marketdata": 1, "data": 1, "markets": 1, "news": 1, "notify": 1, "licensing": 1, "stats": 1,
    # L2 - analyses (deterministic, no order path)
    "indicators": 2, "analysis": 2, "analytics": 2, "svp": 2, "zones": 2, "orderflow": 2, "plans": 2,
    # L3 - trading core (decides / sizes / sends orders)
    "strategies": 3, "risk": 3, "engine": 3, "execution": 3, "decision": 3, "sh": 3, "baskets": 3,
    # L4 - SHADOW / research / trained and pretrained models
    "lab": 4, "ml": 4, "tsfm": 4, "kronos": 4, "quant": 4, "modelhub": 4, "trainhub": 4, "mm": 4, "extind": 4, "scalp": 4, "forecast": 4,
    "evaluation": 4, "montecarlo": 4, "research": 4, "apollo": 4, "trader_life_game": 4, "ledgers": 4, "features": 4,
    # L5 - composition roots
    "runtime": 5, "api": 5, "__main__": 5, "train_all": 5, "bootstrap": 5, "diagnostics": 5, "upgrade": 5, "desktop": 5, "agent": 5,
    "exports": 5, "studio": 5, "training": 5,
    "wf32_services": 5,      # services of the workflow v3.2 modules owned and built by the Runtime (I0088/I0092); imported by runtime / api
}


def module_name(p: Path, pkg: Path = PKG) -> str:
    parts = list(p.relative_to(pkg.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def component(mod: str) -> str:
    parts = mod.split(".")
    return parts[1] if len(parts) > 1 else parts[0]


def modules(pkg: Path = PKG) -> dict[str, Path]:
    return {module_name(p, pkg): p for p in sorted(pkg.rglob("*.py")) if "__pycache__" not in p.parts}


def _target(name: str, mods: dict[str, Path]) -> str | None:
    """Longest prefix of a dotted name that is a module of the package (`masterquo.a.b.NAME` -> `masterquo.a.b`)."""
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in mods:
            return cand
    return None


class _Collector(ast.NodeVisitor):
    def __init__(self, mod: str, is_pkg: bool, mods: dict[str, Path], root: str):
        self.mod, self.mods, self.root = mod, mods, root
        self.pkg = mod if is_pkg else mod.rsplit(".", 1)[0]
        self.depth = 0
        self.out: list[tuple[str, int, str]] = []          # (target module, line, kind)

    def _add(self, name: str | None, line: int, kind: str) -> None:
        t = _target(name, self.mods) if name else None
        if t and t != self.mod:
            self.out.append((t, line, kind))

    def _kind(self) -> str:
        return "FUNCTION" if self.depth else "MODULE"

    def visit_FunctionDef(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_Import(self, node):
        for a in node.names:
            self._add(a.name, node.lineno, self._kind())

    def visit_ImportFrom(self, node):
        if node.level:
            base = self.pkg.split(".")
            base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
            mod = ".".join(base + ([node.module] if node.module else []))
        else:
            mod = node.module or ""
        if not (mod == self.root or mod.startswith(self.root + ".")):
            return
        for a in node.names:
            sub = f"{mod}.{a.name}"
            self._add(sub if sub in self.mods else mod, node.lineno, self._kind())

    def visit_Call(self, node):
        f = node.func
        fname = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        if fname in ("__import__", "import_module") and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            name = node.args[0].value
            if name.startswith("."):                       # import_module(".x", package) - relative to the CURRENT package
                lvl = len(name) - len(name.lstrip("."))
                base = self.pkg.split(".")
                base = base[:len(base) - (lvl - 1)] if lvl > 1 else base
                name = ".".join(base + [name.lstrip(".")])
            if name == self.root or name.startswith(self.root + "."):
                self._add(name, node.lineno, "DYNAMIC")
        self.generic_visit(node)


def edges(pkg: Path = PKG) -> list[dict]:
    """Every internal import: {src, dst, line, kind (MODULE | FUNCTION | DYNAMIC)} - same-module imports dropped."""
    mods = modules(pkg)
    root = pkg.name
    out = []
    for m, p in mods.items():
        c = _Collector(m, p.name == "__init__.py", mods, root)
        c.visit(ast.parse(p.read_text(encoding="utf-8"), filename=str(p)))
        out += [{"src": m, "dst": t, "line": ln, "kind": k} for t, ln, k in c.out]
    return out


def unclassified(pkg: Path = PKG, layers: dict[str, int] = LAYERS) -> list[str]:
    return sorted({component(m) for m in modules(pkg)} - set(layers))


def upward(es: list[dict], layers: dict[str, int] = LAYERS) -> dict[str, dict]:
    """Upward edges grouped by "src -> dst" module pair: {from, to (layer names), kind, lines}."""
    out: dict[str, dict] = {}
    for e in es:
        a, b = component(e["src"]), component(e["dst"])
        if a == b or a not in layers or b not in layers or layers[a] >= layers[b]:
            continue
        k = f"{e['src']} -> {e['dst']}"
        r = out.setdefault(k, {"from": LAYER_NAMES[layers[a]], "to": LAYER_NAMES[layers[b]], "kinds": [], "lines": []})
        r["lines"].append(e["line"])
        if e["kind"] not in r["kinds"]:
            r["kinds"].append(e["kind"])
    for r in out.values():
        r["lines"].sort()
        r["kinds"].sort()
    return dict(sorted(out.items()))


def load_baseline(path: Path = BASELINE) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))["edges"]


def compare(current: dict[str, dict], baseline: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(new upward pairs = FAIL, pairs gone since the baseline = information)."""
    return sorted(set(current) - set(baseline)), sorted(set(baseline) - set(current))


def write_baseline(path: Path = BASELINE) -> dict:
    up = upward(edges())
    doc = {"schema": "pmw-layer-baseline-1", "generated_by": "python tools/cycles.py --write-baseline",
           "note": "krawędzie w górę istniejące w kodzie (warstwa niższa importuje wyższą); nowa para = błąd testu, linie tylko informacyjnie",
           "layers": {k: LAYER_NAMES[v] for k, v in sorted(LAYERS.items())}, "count": len(up), "edges": up}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str]) -> int:
    if "--write-baseline" in argv:
        doc = write_baseline()
        print(f"[cycles] baseline: {doc['count']} par krawędzi w górę -> {BASELINE}")
        return 0
    es = edges()
    miss = unclassified()
    up = upward(es)
    print(f"[cycles] importy wewnętrzne: {len(es)} (MODULE {sum(e['kind'] == 'MODULE' for e in es)}, FUNCTION "
          f"{sum(e['kind'] == 'FUNCTION' for e in es)}, DYNAMIC {sum(e['kind'] == 'DYNAMIC' for e in es)}); par w górę: {len(up)}")
    if miss:
        print("[cycles] komponenty bez warstwy: " + ", ".join(miss))
    if BASELINE.exists():
        new, gone = compare(up, load_baseline())
        for k in new:
            print(f"  NOWA  {k}  ({up[k]['from']} -> {up[k]['to']}, linie {up[k]['lines']})")
        for k in gone:
            print(f"  usunięta (info)  {k}")
        return 1 if new or miss else 0
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
