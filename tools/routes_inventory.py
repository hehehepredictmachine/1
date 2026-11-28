"""Inventory of the HTTP routes of the bot API (1.46 arch, I0113 / I0136) -> docs/arch146/routes_inventory.json.

Routes are read from create_app() itself (a mock runtime, no server, no socket; OWNER edition = superset, `editions` says which are
also in the CLIENT edition), never typed by hand. For every METHOD + PATH: handler (file:function:line), class and static callers.

Classes:
  EXECUTION     the handler reaches the order path or switches automatic trading (ORDER_PATH below: gateway.execute, Manual Pad
                execute / manage, SH plan close, close / adopt positions, AUTO / mode / primary path) - contract tests in
                tests/test_arch146_w2_tools_cli.py (session + CSRF + Origin required; SIGNALS / PAPER never reach order_send);
  PUBLIC        called by a client of the API: frontend/src, desktop (Go), tools, mql5, *.bat / *.cmd or a backend CLI client;
  LEGACY_UI141  only the archived 1.41 UI (archive/ui_1_41, not built) calls it;
  INTERNAL      no client in the repository (tests only, or nothing at all).
Callers are a best-effort static search of the path template ({param} = one path segment); a path built from variables in the client is
not found. EXECUTION is a heuristic (ORDER_PATH regex over the handler source): a switch that does not call the order path itself is not
EXECUTION - e.g. POST /api/v1/kill (rt.modes.set_kill; switching it OFF lifts the block on new entries) is PUBLIC (see NOTE).
Nothing is removed or blocked here - routes are a public contract and their removal is an owner decision.

  python tools/routes_inventory.py            write docs/arch146/routes_inventory.json and print the summary
  python tools/routes_inventory.py --check    compare the file with create_app (exit 1 on a difference)
"""
from __future__ import annotations

import atexit
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "arch146" / "routes_inventory.json"
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

SCHEMA = "pmw-routes-inventory-1"
PORT = 18799
# handler source -> order path / automatic trading switch (keep in sync with the services; a new such call is caught by the test)
ORDER_PATH = re.compile(r"rt\.gateway\.execute\(|rt\.manual\.(?:execute|manage)\(|\bmanual_execute\(|rt\.manager\.(?:close_positions|adopt)\(|"
                        r"rt\.sh\.close_plan\(|rt\.modes\.(?:set_auto|set_mode|set_primary_path)\(|order_send\(")
CALLER_AREAS = {                       # area -> (directory, glob patterns)
    "frontend": ("frontend/src", ("*.ts", "*.tsx", "*.js", "*.jsx")),
    "desktop": ("desktop", ("*.go",)),
    "tools": ("tools", ("*.py", "*.cmd", "*.ps1")),
    "mql5": ("mql5", ("*.mq5", "*.mqh")),
    "launchers": (".", ("*.bat", "*.cmd")),
    "backend": ("backend/masterquo", ("*.py",)),
    "tests": ("tests", ("*.py",)),
    "archive_ui141": ("archive/ui_1_41", ("*.ts", "*.tsx", "*.js", "*.jsx")),
}
CLIENT_AREAS = ("frontend", "desktop", "tools", "mql5", "launchers", "backend")
NOTE = ("trasy z create_app (OWNER = nadzbiór; editions mówi, które są też w wersji klienta); wywołujący = statyczne wyszukiwanie szablonu "
        "ścieżki; klasa EXECUTION = heurystyka (wyrażenie ORDER_PATH na źródle handlera: ścieżka zleceń, AUTO, tryb, ścieżka główna) - "
        "przełącznik bez wywołania ścieżki zleceń nie jest EXECUTION, np. POST /api/v1/kill (rt.modes.set_kill; wyłączenie zdejmuje "
        "blokadę nowych wejść) ma klasę z wywołujących; nic nie jest usuwane ani blokowane (kontrakt publiczny, decyzja właściciela)")
SELF = {"tools/routes_inventory.py"}

def _offline_env(var: str, prefix: str) -> None:
    """Temporary folder for `var` only when it is not set - `os.environ.setdefault(var, tempfile.mkdtemp())` created (and left behind)
    a folder on every call, also with the variable set. The folder created here is removed when the process exits."""
    if os.environ.get(var):
        return
    d = tempfile.mkdtemp(prefix=prefix)
    os.environ[var] = d
    atexit.register(shutil.rmtree, d, ignore_errors=True)


def _app(edition: str):
    from unittest import mock
    _offline_env("MASTERQUO_DATA_DIR", "pmw_routes_")
    from masterquo.api import app as A
    rt = mock.MagicMock()
    rt.license.locked = False
    rt.license.edition = edition
    rt.cfg.get.return_value.assets.active = "XAUUSD"
    return A.create_app(rt, PORT)


def routes(edition: str = "OWNER") -> list[dict]:
    out = []
    for r in _app(edition).routes:
        fn = getattr(r, "endpoint", None)
        if fn is None:
            continue
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            src = ""
        code = getattr(fn, "__code__", None)
        file = Path(code.co_filename).resolve() if code else None
        rel = str(file.relative_to(ROOT)) if file and ROOT in file.parents else (file.name if file else "?")
        for m in sorted(getattr(r, "methods", None) or {"WS"}):
            if m == "HEAD":
                continue
            out.append({"method": m, "path": r.path, "handler": f"{rel}:{fn.__name__}", "line": code.co_firstlineno if code else None,
                        "order_path": bool(ORDER_PATH.search(src))})
    return out


def _texts() -> dict[str, str]:
    out = {}
    for area, (d, pats) in CALLER_AREAS.items():
        base = ROOT / d
        files = []
        for pat in pats:
            files += base.glob(pat) if d == "." else base.rglob(pat)
        buf = []
        for f in sorted(set(files)):
            rel = str(f.relative_to(ROOT))
            if rel in SELF or "node_modules" in f.parts or "__pycache__" in f.parts or rel.startswith("backend/masterquo/api/"):
                continue                                        # definitions are not callers
            try:
                buf.append(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        out[area] = "\n".join(buf)
    return out


def _path_re(path: str) -> re.Pattern | None:
    if not path.startswith("/api/"):
        return None                                             # page, assets, static: served to the browser, not "called"
    parts = re.split(r"(\{[^}]+\})", path)
    rx = "".join(r"[^/\"'`?\s]+" if p.startswith("{") else re.escape(p) for p in parts)
    return re.compile(rx + r"(?![\w/-])")


def classify(order_path: bool, callers: dict[str, int]) -> str:
    if order_path:
        return "EXECUTION"
    if any(callers.get(a) for a in CLIENT_AREAS):
        return "PUBLIC"
    if callers.get("archive_ui141"):
        return "LEGACY_UI141"
    return "INTERNAL"


def build() -> dict:
    owner = routes("OWNER")
    client = {(r["method"], r["path"]) for r in routes("CLIENT")}
    texts = _texts()
    out = []
    for r in owner:
        rx = _path_re(r["path"])
        callers = {a: (len(rx.findall(t)) if rx else 0) for a, t in texts.items()}
        out.append({"method": r["method"], "path": r["path"], "handler": r["handler"], "line": r["line"],
                    "class": classify(r["order_path"], callers),
                    "editions": ["CLIENT", "OWNER"] if (r["method"], r["path"]) in client else ["OWNER"],
                    "callers": {a: n for a, n in callers.items() if n},
                    "no_client": not any(callers.get(a) for a in CLIENT_AREAS)})
    out.sort(key=lambda x: (x["path"], x["method"]))
    counts: dict[str, int] = {}
    for x in out:
        counts[x["class"]] = counts.get(x["class"], 0) + 1
    return {"schema": SCHEMA, "generated_by": "python tools/routes_inventory.py",
            "note": NOTE,
            "total": len(out), "by_class": dict(sorted(counts.items())),
            "execution_without_client": [f"{x['method']} {x['path']}" for x in out if x["class"] == "EXECUTION" and x["no_client"]],
            "routes": out}


def key_set(inv_routes: list[dict]) -> set[tuple]:
    """What the consistency test compares: METHOD, PATH, handler and whether the route is EXECUTION (lines and callers informative)."""
    return {(x["method"], x["path"], x["handler"], x["class"] == "EXECUTION") for x in inv_routes}


def check() -> list[str]:
    cur = {(r["method"], r["path"], r["handler"], r["order_path"]) for r in routes("OWNER")}
    saved = key_set(json.loads(OUT.read_text(encoding="utf-8"))["routes"])
    return [f"+ {k}" for k in sorted(cur - saved)] + [f"- {k}" for k in sorted(saved - cur)]


def main(argv: list[str]) -> int:
    if "--check" in argv:
        diff = check()
        for d in diff:
            print(d)
        print(f"[routes] {'ZGODNE' if not diff else f'{len(diff)} różnic – odśwież: python tools/routes_inventory.py'}")
        return 1 if diff else 0
    inv = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(inv, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[routes] {inv['total']} tras: {inv['by_class']}; EXECUTION bez klienta: {', '.join(inv['execution_without_client']) or 'brak'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
