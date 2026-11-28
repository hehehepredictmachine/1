"""Etap 4, faza 2, krok B (Apollo23 1.46, docs/arch146/ETAP2_PROJEKT.md §3 "api/routes", §5 wiersz 2, §6 pkt 8): podział api/app.py na
routery. create_app(rt, port) - ta sama sygnatura - zostawia Guard (middleware bezpieczeństwa), lifespan i stronę / sesję (/, _index,
/assets, /static, health, session), a trasy montuje z api/routes/<domena>.py: routes.register_all(app, ctx) woła
routes.REGISTRATION (47 bloków w kolejności z create_app przed podziałem), potem wf32_routes i export_routes jak dotąd. Każdy blok to
dosłownie przeniesiony fragment create_app (jedyna zmiana: o jedną kropkę głębszy import względny); lokalne nazwy create_app, których
blok używa (rt, sec, port, pomocniki, handlery wołane po nazwie), dostaje na początku register z ctx pod tymi samymi nazwami. Modele
Pydantic -> api/schemas.py; SYMBOL_RX / STUDIO_LAUNCH_WAIT_S / MEDIA_SLOTS / MAX_GIF_BYTES -> moduł trasy, która je czyta; api.app
re-eksportuje każdą starą nazwę (alias zgodności).

Dowody neutralności (migawka zamrożona NA BAZIE przed podziałem, 7ba7ab0 = HEAD po kroku A, tests/data/arch146_e4_api_routes_base.json):
1. TestRouteTableVsBase - dla edycji OWNER i CLIENT (CLIENT bez pliku api/owner_routes.py, jak paczka klienta) uporządkowana lista
   app.router.routes (typ, path, methods, name, endpoint.__name__, status_code, response_class, response_model, include_in_schema,
   dependencies), kolejność user_middleware, klucze exception_handlers i app.openapi() (JSON z posortowanymi kluczami: sha256 całości +
   sha256 każdej operacji) - identyczne z bazą (moduł endpointu może się różnić).
2. TestMovedCodeIdenticalToBase - każda instrukcja create_app bazy (503) jest w nowym kodzie dokładnie raz, w tej samej kolejności:
   sha256 ast.dump i tekstu źródła (komentarze w instrukcji włącznie; import względny znormalizowany o jedną kropkę) jak w bazie;
   ciało register = docstring + `x = ctx.x` (tylko nazwy opublikowane przez wcześniejszy blok / _shared / rt, sec, port) + przeniesione
   instrukcje + `ctx.x = x`; część zostająca w create_app (Guard, lifespan, strona / sesja, wf32 / exports) identyczna.
3. TestGetResponsesVsBase - osobny proces: Runtime(demo=True) offline (nie wystartowany), TestClient: każda trasa GET /api/... bez
   parametrów ścieżki - status i klucze najwyższego poziomu ciała JSON jak w bazie (pełne porównanie ciał po normalizacji pól zmiennych w
   czasie: jednorazowy skrypt, raport w opisie commita).
4. TestRouteInventoryVsBase - tools/routes_inventory.routes(): metoda, ścieżka, nazwa funkcji handlera, ścieżka zleceń (ORDER_PATH)
   jak w bazie dla obu edycji; zmienia się wyłącznie plik w polu handler (api/app.py -> api/routes/<moduł>.py) i line.
5. TestOldNamesImportable - pełna lista nazw modułu api.app bazy (poza nieużywanymi już importami stdlib / fastapi / pydantic,
   których nikt nie importuje z api.app - grep backend/, tests/, tools/, desktop/, *.bat) nadal importowalna; modele = te same klasy.
6. TestRoutesPackage - api/routes i api/schemas w warstwie api (tools/cycles.LAYERS), bez znaczników kodu właściciela
   (verify_release.CLIENT_MARKERS), owner_routes tylko w edycji OWNER; paczka klienta (moduły OWNER_ONLY nieimportowalne,
   PMW_EDITION=CLIENT) w osobnym procesie: Runtime(demo=True) + create_app = trasy edycji CLIENT bazy, bez licencji 402 z Guard.

Migawka (polecenie):
  git archive 7ba7ab0 backend tools config frontend/dist | tar -x -C <tmp>
  PMW_BOOTSTRAP=0 python tests/test_arch146_e4_api_split.py --snapshot tests/data/arch146_e4_api_routes_base.json --root <tmp>
(uruchomione dwa razy - identyczne poza kluczami ciał tras zmiennych w czasie, które zapisano jako null = porównywany tylko status).
Nic tu nie łączy się z MT5, nie wysyła zleceń (trasy POST tylko w migawce tabeli tras), nie zapisuje do data/ (katalog tymczasowy).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

PORT = 18804
BASE_FILE = Path(__file__).resolve().parent / "data" / "arch146_e4_api_routes_base.json"
BASE_COMMIT = "7ba7ab091b1deea9b31b523934d22f5af684719f"
# imports of api/app.py that the moved handlers needed and app.py itself no longer uses (stdlib / framework objects, not API names;
# nothing imports them from masterquo.api.app - grep backend/, tests/, tools/, desktop/, *.bat)
DROPPED_IMPORTS = {"json", "os", "re", "sys", "time", "Path", "Body", "Query", "WebSocket", "WebSocketDisconnect", "BaseModel", "Field"}
SHARED_STMTS = (328, 436, 437)        # base create_app statements used before their block -> routes/_shared.define
# route paths are built from V1 here: a literal template would count this file as a caller in tools/routes_inventory.py (tests area)
V1 = "/api/v1"
PAGE_ROUTES = ("/", "/assets/{name:path}", "/static/{name:path}", f"{V1}/health", f"{V1}/session")      # stay in api/app.py


def _sha(s: str | bytes) -> str:
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


# --------------------------------------------------------------------------------------------------------- route table / openapi
def _rc(rc) -> str | None:
    if rc is None:
        return None
    if type(rc).__name__ == "DefaultPlaceholder":
        return f"Default({getattr(rc.value, '__name__', repr(rc.value))})"
    return getattr(rc, "__name__", repr(rc))


def route_rows(app) -> list[list]:
    rows = []
    for r in app.router.routes:
        ep = getattr(r, "endpoint", None)
        rows.append([type(r).__name__, getattr(r, "path", None), sorted(getattr(r, "methods", None) or []), getattr(r, "name", None),
                     getattr(ep, "__name__", None), getattr(r, "status_code", None), _rc(getattr(r, "response_class", None)),
                     repr(getattr(r, "response_model", None)), getattr(r, "include_in_schema", None), repr(getattr(r, "dependencies", None))])
    return rows


def _without_version(spec: dict) -> dict:
    out = json.loads(json.dumps(spec, default=str))
    (out.get("info") or {}).pop("version", None)
    return out


def app_meta(app) -> dict:
    spec = app.openapi()
    ops = {f"{m.upper()} {p}": _sha(json.dumps(op, sort_keys=True, default=str)) for p, item in spec["paths"].items() for m, op in item.items()}
    return {"middleware": [[m.cls.__name__, sorted((getattr(m, "kwargs", None) or getattr(m, "options", None) or {}).keys())]
                           for m in app.user_middleware],
            "exception_handlers": sorted(repr(k) for k in app.exception_handlers),
            "openapi_sha256": _sha(json.dumps(spec, sort_keys=True, default=str)),
            # the spec carries info.version = APP_VERSION (FastAPI(version=...)): a release number is not part of the route contract
            "openapi_sha256_noversion": _sha(json.dumps(_without_version(spec), sort_keys=True, default=str)),
            "openapi_version": (spec.get("info") or {}).get("version"),
            "openapi_components": sorted((spec.get("components") or {}).get("schemas", {})),
            "openapi_operations": dict(sorted(ops.items()))}


def mock_runtime(edition: str):
    from unittest import mock
    rt = mock.MagicMock()
    rt.license.locked = False
    rt.license.edition = edition
    rt.cfg.get.return_value.assets.active = "XAUUSD"
    return rt


def build_app(edition: str):
    """create_app on a MagicMock runtime (as tools/routes_inventory.py); CLIENT: api/owner_routes.py made unimportable, as in the client
    package (verify_release.OWNER_ONLY)."""
    from masterquo.api import app as A
    if edition != "CLIENT":
        return A.create_app(mock_runtime(edition), PORT)
    saved = sys.modules.get("masterquo.api.owner_routes", "<none>")
    sys.modules["masterquo.api.owner_routes"] = None                     # import -> ImportError
    try:
        return A.create_app(mock_runtime(edition), PORT)
    finally:
        if saved == "<none>":
            sys.modules.pop("masterquo.api.owner_routes", None)
        else:
            sys.modules["masterquo.api.owner_routes"] = saved


def editions_snapshot() -> dict:
    out = {}
    for ed in ("OWNER", "CLIENT"):
        app = build_app(ed)
        out[ed] = {"routes": route_rows(app), **app_meta(app)}
    return out


# ------------------------------------------------------------------------------------------------- create_app statements (AST + text)
class _LevelUp(ast.NodeTransformer):
    """routes/*.py sit one package deeper: `from ...x` there is `from ..x` in api/app.py."""

    def visit_ImportFrom(self, n):
        if n.level:
            n.level -= 1
        return n


_REL = re.compile(r"^(\s*from )\.(\.+[\w.]* import )", re.MULTILINE)


def _stmt_text(lines: list[str], s) -> str:
    s0 = s.decorator_list[0].lineno if getattr(s, "decorator_list", None) else s.lineno
    return "".join(lines[s0 - 1:s.end_lineno])


def stmt_digest(lines: list[str], s, deeper: bool) -> list:
    node = _LevelUp().visit(copy.deepcopy(s)) if deeper else s
    txt = _REL.sub(r"\1\2", _stmt_text(lines, s)) if deeper else _stmt_text(lines, s)
    kind = type(s).__name__
    name = getattr(s, "name", None)
    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.decorator_list and isinstance(s.decorator_list[0], ast.Call):
        d = s.decorator_list[0]
        if isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name) and d.func.value.id == "app" and d.args:
            kind = f"route:{d.func.attr}:{ast.literal_eval(d.args[0])}"
    return [kind, name, _sha(ast.dump(node)), _sha(txt)]


def _create_app(tree):
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app")


def base_statements(root: Path) -> list:
    src = (root / "backend/masterquo/api/app.py").read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    return [stmt_digest(lines, s, False) for s in _create_app(ast.parse(src)).body]


def _split_register(fn) -> tuple[list, list, list]:
    body = list(fn.body)
    has_doc = isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
    if not has_doc:
        raise AssertionError(f"{fn.name}: no docstring")
    body = body[1:]
    pre, pub = [], []

    def is_pre(st):
        return isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) and \
            isinstance(st.value, ast.Attribute) and isinstance(st.value.value, ast.Name) and st.value.value.id == "ctx" and \
            st.value.attr == st.targets[0].id

    def is_pub(st):
        return isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Attribute) and \
            isinstance(st.targets[0].value, ast.Name) and st.targets[0].value.id == "ctx" and isinstance(st.value, ast.Name) and \
            st.value.id == st.targets[0].attr
    while body and is_pre(body[0]):
        pre.append(body.pop(0).targets[0].id)
    while body and is_pub(body[-1]):
        pub.insert(0, body.pop().value.id)
    return pre, body, pub


def current_statements(root: Path) -> dict:
    """Moved statements in REGISTRATION order (routes/_shared.define first), the retained part of create_app, and every register
    function's preamble / published names - read from the sources (AST), nothing executed."""
    api = root / "backend/masterquo/api"
    init = ast.parse((api / "routes/__init__.py").read_text(encoding="utf-8"))
    reg = next(n for n in init.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "REGISTRATION").value.elts
    entries = [("_shared", "define")] + [(e.value.id, e.attr) for e in reg]
    moved, blocks, cache = [], [], {}
    for mod, fname in entries:
        if mod not in cache:
            src = (api / "routes" / f"{mod}.py").read_text(encoding="utf-8")
            cache[mod] = (src.splitlines(keepends=True), ast.parse(src))
        lines, tree = cache[mod]
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fname)
        pre, body, pub = _split_register(fn)
        blocks.append({"block": f"{mod}.{fname}", "pre": pre, "pub": pub, "n": len(body),
                       "args": [a.arg for a in fn.args.args]})
        moved += [stmt_digest(lines, s, True) for s in body]
    src = (api / "app.py").read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    ca = _create_app(ast.parse(src))
    kept = [stmt_digest(lines, s, False) for s in ca.body]
    return {"moved": moved, "kept": kept, "blocks": blocks,
            "create_app_args": [a.arg for a in ca.args.args], "create_app_src": [ast.unparse(s) for s in ca.body]}


# ------------------------------------------------------------------------------------------------------------ GET probe (own process)
def _shape(body):
    if isinstance(body, dict):
        return sorted(body)
    return type(body).__name__


def get_probe(root: Path) -> dict:
    """Runtime(demo=True) of the tree at `root` (offline, not started) + create_app + TestClient: every GET /api/... route without path
    parameters -> [status, top-level keys of the JSON body (or its type)]. Run in its own process (sys.path = root/backend)."""
    td = tempfile.mkdtemp(prefix="e4b_get_")
    os.environ.update(MASTERQUO_DATA_DIR=td, PMW_BOOTSTRAP="0", MQ_FAKE_MARKET_ALWAYS_OPEN="1", MQ_BASKETS_OFFLINE="1")
    Path(td, "config.json").write_text(json.dumps({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False},
                                                   "clock": {"reference_url": None}, "first_run_completed": True}), encoding="utf-8")
    from fastapi.testclient import TestClient
    from masterquo.api import app as A
    from masterquo.runtime import Runtime
    rt = Runtime(demo=True)
    app = A.create_app(rt, PORT)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    out = {"index_status": c.get("/").status_code, "routes": {}}

    class _Timeout(Exception):
        pass

    def _alarm(*_):
        raise _Timeout()
    signal.signal(signal.SIGALRM, _alarm)
    for r in app.router.routes:
        path = getattr(r, "path", "")
        if "GET" not in (getattr(r, "methods", None) or ()) or not path.startswith("/api/") or "{" in path:
            continue
        signal.alarm(30)
        try:
            resp = c.get(path)
            try:
                shape = _shape(resp.json())
            except ValueError:
                shape = f"non-json:{resp.headers.get('content-type')}"
            out["routes"][path] = [resp.status_code, shape]
        except _Timeout:
            out["routes"][path] = ["TIMEOUT", None]
        except Exception as exc:  # noqa: BLE001 - recorded, compared with the base
            out["routes"][path] = ["EXC", type(exc).__name__]
        finally:
            signal.alarm(0)
    rt._stop.set()
    import shutil
    shutil.rmtree(td, ignore_errors=True)
    return out


OWNER_ONLY_MODULES = ("masterquo.licensing.owner", "masterquo.licensing.signing", "masterquo.api.owner_routes")   # verify_release.OWNER_ONLY


def client_probe(root: Path) -> dict:
    """Client package as built by tools/build_release.py --edition client, simulated in place: the OWNER_ONLY modules cannot be imported
    (meta path finder) and PMW_EDITION=CLIENT (licensing/edition.py; the build writes the licensing/_edition.py marker instead). A
    Runtime(demo=True) of `root` (offline, not started) + create_app + TestClient: edition, route list, statuses of a few routes."""
    import importlib.abc

    class _OwnerOnly(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name in OWNER_ONLY_MODULES:                 # any other module: None (implicit) = the normal finders decide
                raise ModuleNotFoundError(f"{name} (verify_release.OWNER_ONLY - not in the client package)")
    sys.meta_path.insert(0, _OwnerOnly())
    td = tempfile.mkdtemp(prefix="e4b_client_")
    os.environ.update(MASTERQUO_DATA_DIR=td, PMW_BOOTSTRAP="0", MQ_FAKE_MARKET_ALWAYS_OPEN="1", MQ_BASKETS_OFFLINE="1", PMW_EDITION="CLIENT")
    Path(td, "config.json").write_text(json.dumps({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False},
                                                   "clock": {"reference_url": None}, "first_run_completed": True}), encoding="utf-8")
    from fastapi.testclient import TestClient
    from masterquo.api import app as A
    from masterquo.runtime import Runtime
    rt = Runtime(demo=True)
    app = A.create_app(rt, PORT)
    c = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    out = {"edition": rt.license.edition, "locked": bool(rt.license.locked), "index": c.get("/").status_code,
           "routes": [[getattr(r, "path", None), sorted(getattr(r, "methods", None) or [])] for r in app.router.routes],
           "status": {p: c.get(V1 + p).status_code for p in ("/health", "/session", "/license/status", "/state", "/lab", "/baskets")},
           "owner_modules_loaded": sorted(m for m in OWNER_ONLY_MODULES if sys.modules.get(m) is not None)}
    rt._stop.set()
    import shutil
    shutil.rmtree(td, ignore_errors=True)
    return out


# --------------------------------------------------------------------------------------------------------------- inventory / names
def inventory_rows(root: Path) -> dict:
    sys.path.insert(0, str(root / "tools"))
    import routes_inventory as RI
    if not Path(RI.__file__).resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"routes_inventory from {RI.__file__}, not from {root}")
    out = {}
    for ed in ("OWNER", "CLIENT"):
        out[ed] = [[r["method"], r["path"], r["handler"], r["line"], r["order_path"]] for r in RI.routes(ed)]
    return out


def module_names(root: Path) -> list[str]:
    tree = ast.parse((root / "backend/masterquo/api/app.py").read_text(encoding="utf-8"))
    names = []
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names += [(a.asname or a.name).split(".")[0] for a in n.names if a.name != "annotations"]
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            names.append(n.name)
        elif isinstance(n, ast.Assign):
            names += [t.id for t in n.targets if isinstance(t, ast.Name)]
    return names


def snapshot(root: Path) -> dict:
    sys.path.insert(0, str(root / "backend"))
    if not os.environ.get("MASTERQUO_DATA_DIR"):          # a folder only when unset (setdefault created one on every call)
        os.environ["MASTERQUO_DATA_DIR"] = tempfile.mkdtemp(prefix="e4b_snap_")
    import masterquo
    if not Path(masterquo.__file__).resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"masterquo from {masterquo.__file__}, not from {root}")
    res = {"editions": editions_snapshot(), "statements": base_statements(root), "module_names": module_names(root),
           "inventory": inventory_rows(root)}
    res["get"] = get_probe(root)
    return res


if __name__ == "__main__" and ("--snapshot" in sys.argv or "--get-probe" in sys.argv or "--client-probe" in sys.argv):
    _root = Path(sys.argv[sys.argv.index("--root") + 1]) if "--root" in sys.argv else Path(__file__).resolve().parents[1]
    if "--snapshot" in sys.argv:
        _out = Path(sys.argv[sys.argv.index("--snapshot") + 1])
        _snap = snapshot(_root)
        _old = json.loads(_out.read_text(encoding="utf-8")) if "--merge-stable" in sys.argv and _out.exists() else None
        if _old is not None:                       # second run of the base: keys that differ between two runs -> null (status only)
            for _p, (_st, _shape0) in _snap["get"]["routes"].items():
                if _old["get"]["routes"].get(_p) != [_st, _shape0]:
                    _snap["get"]["routes"][_p] = [_st, None] if _old["get"]["routes"].get(_p, [None])[0] == _st else ["UNSTABLE", None]
        _doc = {"generated": {"base_commit": BASE_COMMIT,
                              "commands": ["git archive 7ba7ab0 backend tools config frontend/dist | tar -x -C <tmp>",
                                           "PMW_BOOTSTRAP=0 python tests/test_arch146_e4_api_split.py --snapshot <this file> --root <tmp>",
                                           "PMW_BOOTSTRAP=0 python tests/test_arch146_e4_api_split.py --snapshot <this file> --root <tmp> --merge-stable"],
                              "note": "Etap 4 krok B: create_app NA BAZIE (przed podziałem na api/routes): tabela tras OWNER / CLIENT, middleware, "
                                      "exception handlers, openapi, instrukcje create_app (sha256 AST + tekst), nazwy modułu api.app, "
                                      "routes_inventory.routes(), GET bez parametrów na Runtime(demo=True) (status + klucze; null = zmienne w czasie)"},
                **_snap}
        with open(_out, "w", encoding="utf-8") as _f:
            _f.write("{\n")
            _items = list(_doc.items())
            for _k_i, (_k, _v) in enumerate(_items):
                _f.write(f" {json.dumps(_k)}: ")
                if _k in ("editions", "inventory"):        # one route per line (diff-friendly, ~1/3 of the indented size)
                    _f.write("{\n")
                    for _e_i, (_ek, _ev) in enumerate(_v.items()):
                        if isinstance(_ev, dict):
                            _f.write(f"  {json.dumps(_ek)}: {{\n")
                            _sub = list(_ev.items())
                            for _s_i, (_sk, _sv) in enumerate(_sub):
                                if _sk == "routes":
                                    _f.write(f"   {json.dumps(_sk)}: [\n" + ",\n".join("    " + json.dumps(x, ensure_ascii=False) for x in _sv) + "\n   ]")
                                else:
                                    _f.write(f"   {json.dumps(_sk)}: {json.dumps(_sv, ensure_ascii=False)}")
                                _f.write(",\n" if _s_i < len(_sub) - 1 else "\n")
                            _f.write("  }")
                        else:
                            _f.write(f"  {json.dumps(_ek)}: [\n" + ",\n".join("   " + json.dumps(x, ensure_ascii=False) for x in _ev) + "\n  ]")
                        _f.write(",\n" if _e_i < len(_v) - 1 else "\n")
                    _f.write(" }")
                elif _k == "statements":
                    _f.write("[\n" + ",\n".join("  " + json.dumps(x, ensure_ascii=False) for x in _v) + "\n ]")
                elif _k == "get":
                    _f.write("{\n  \"index_status\": " + json.dumps(_v["index_status"]) + ",\n  \"routes\": {\n"
                             + ",\n".join(f"   {json.dumps(p)}: {json.dumps(x, ensure_ascii=False)}" for p, x in _v["routes"].items())
                             + "\n  }\n }")
                else:
                    _f.write(json.dumps(_v, ensure_ascii=False))
                _f.write(",\n" if _k_i < len(_items) - 1 else "\n")
            _f.write("}\n")
    elif "--client-probe" in sys.argv:
        sys.path.insert(0, str(_root / "backend"))
        Path(sys.argv[sys.argv.index("--client-probe") + 1]).write_text(json.dumps(client_probe(_root), ensure_ascii=False), encoding="utf-8")
    else:
        sys.path.insert(0, str(_root / "backend"))
        Path(sys.argv[sys.argv.index("--get-probe") + 1]).write_text(json.dumps(get_probe(_root), ensure_ascii=False), encoding="utf-8")
    sys.stdout.flush()
    os._exit(0)                                # service threads of the probed runtime are daemons - never wait for them

import unittest

import _env

TOOLS = _env.ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _base() -> dict:
    return json.loads(BASE_FILE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------------- 1. route table + openapi
class TestRouteTableVsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = _env.TempData()
        cls.base = _base()["editions"]
        cls.cur = json.loads(json.dumps(editions_snapshot(), default=str))

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_route_rows_identical_in_order(self):
        for ed in ("OWNER", "CLIENT"):
            b, c = self.base[ed]["routes"], self.cur[ed]["routes"]
            self.assertEqual(len(c), len(b), ed)
            for i, (rb, rc) in enumerate(zip(b, c)):
                self.assertEqual(rc, rb, f"{ed} route #{i}")
        self.assertEqual(len(self.base["OWNER"]["routes"]), 522)
        self.assertEqual(len(self.base["CLIENT"]["routes"]), 513)

    def test_middleware_exception_handlers_openapi(self):
        for ed in ("OWNER", "CLIENT"):
            for k in ("middleware", "exception_handlers", "openapi_components"):
                self.assertEqual(self.cur[ed][k], self.base[ed][k], f"{ed} {k}")
            ops_b, ops_c = self.base[ed]["openapi_operations"], self.cur[ed]["openapi_operations"]
            self.assertEqual(sorted(ops_c), sorted(ops_b), ed)
            self.assertEqual([k for k in ops_b if ops_b[k] != ops_c[k]], [], ed)
            # whole spec without info.version (1.46.1: the release number moved, routes / schemas / operations did not)
            self.assertEqual(self.cur[ed]["openapi_sha256_noversion"], self.base[ed]["openapi_sha256_noversion"], ed)
            from masterquo.version import APP_VERSION
            self.assertEqual(self.cur[ed]["openapi_version"], APP_VERSION, ed)
        self.assertEqual(self.cur["OWNER"]["middleware"], [["Guard", []]])

    def test_handlers_live_in_route_modules_page_and_session_in_app(self):
        app = build_app("OWNER")
        mods = {}
        for r in app.router.routes:
            ep = getattr(r, "endpoint", None)
            if ep is not None and getattr(r, "path", "").startswith(("/", "/api/")):
                mods[r.path] = ep.__module__
        for p in PAGE_ROUTES:
            self.assertEqual(mods[p], "masterquo.api.app", p)
        self.assertEqual(mods[f"{V1}/state"], "masterquo.api.routes.core")
        self.assertEqual(mods[f"{V1}/execute"], "masterquo.api.routes.trading")
        self.assertEqual(mods[f"{V1}/ws"], "masterquo.api.routes.ws")
        in_app = sorted(p for p, m in mods.items() if m == "masterquo.api.app")
        self.assertEqual(in_app, sorted(PAGE_ROUTES))


# ------------------------------------------------------------------------------------------------- 2. moved code identical to base
class TestMovedCodeIdenticalToBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = _base()["statements"]
        cls.cur = current_statements(_env.ROOT)

    def test_every_base_statement_moved_once_in_order_ast_and_text(self):
        order = list(SHARED_STMTS) + [i for i in range(13, 498) if i not in SHARED_STMTS]
        expected = [self.base[i] for i in order]
        self.assertEqual(len(self.cur["moved"]), len(expected))
        for k, (c, b) in enumerate(zip(self.cur["moved"], expected)):
            self.assertEqual(c, b, f"moved statement #{k} = base create_app statement {order[k]} ({b[0]} {b[1]})")
        self.assertEqual(len(self.base), 503)
        self.assertEqual(sum(1 for s in self.base if s[0].startswith("route:")), 436)       # the 436 routes of ETAP2_PROJEKT §5

    def test_retained_part_of_create_app_identical(self):
        kept = [s for s, src in zip(self.cur["kept"], self.cur["create_app_src"]) if not src.startswith("_routes.register_all(")]
        self.assertEqual(kept, self.base[:13] + self.base[498:])
        self.assertEqual(self.cur["create_app_args"], ["rt", "port"])
        self.assertEqual(self.cur["create_app_src"][13], "_routes.register_all(app, _routes.Ctx(rt=rt, sec=sec, port=port))")

    def test_register_preamble_binds_only_names_published_earlier(self):
        avail = {"rt", "sec", "port"}
        published = set()
        for b in self.cur["blocks"]:
            self.assertEqual(b["args"], ["ctx"] if b["block"] == "_shared.define" else ["app", "ctx"], b["block"])
            self.assertEqual([p for p in b["pre"] if p not in avail], [], b["block"])
            self.assertEqual(set(b["pub"]) & published, set(), b["block"])                # a name is defined once
            published |= set(b["pub"])
            avail |= set(b["pub"])
            self.assertGreater(b["n"], 0, b["block"])
        self.assertEqual(len(self.cur["blocks"]), 48)
        self.assertIn("rt", self.cur["blocks"][1]["pre"])                                 # the runtime variable is still `rt`

    def test_order_path_sources_still_name_rt(self):
        import routes_inventory as RI
        trading = (_env.ROOT / "backend/masterquo/api/routes/trading.py").read_text(encoding="utf-8")
        for call in ("rt.gateway.execute(", "rt.manager.close_positions(", "rt.manager.adopt(", "rt.modes.set_auto(", "rt.modes.set_mode(",
                     "rt.modes.set_primary_path(", "rt.manual.execute(", "rt.manual.manage(", "manual_execute("):
            self.assertIn(call, trading, call)
            self.assertTrue(RI.ORDER_PATH.search(call), call)


def _run_probe(flag: str) -> dict:
    """This file with --get-probe / --client-probe in its own process (sys.path = this tree's backend, temporary data folder)."""
    with tempfile.TemporaryDirectory(prefix="e4b_probe_") as d:
        out = Path(d) / "probe.json"
        env = dict(os.environ, PMW_BOOTSTRAP="0", PYTHONPATH="")
        for k in ("MASTERQUO_DATA_DIR", "PMW_EDITION"):
            env.pop(k, None)
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), flag, str(out), "--root", str(_env.ROOT)],
                           env=env, cwd=d, capture_output=True, text=True, timeout=800, check=False)
        if not out.exists():
            raise AssertionError(f"sonda {flag} nie zapisała wyniku (kod {r.returncode}): {r.stderr[-2000:]}")
        return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------- 3. GET responses
class TestGetResponsesVsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = _base()["get"]
        cls.cur = _run_probe("--get-probe")

    def test_same_routes_same_status_same_top_level_keys(self):
        self.assertEqual(self.cur["index_status"], self.base["index_status"])
        self.assertEqual(sorted(self.cur["routes"]), sorted(self.base["routes"]))
        self.assertEqual(list(self.cur["routes"]), list(self.base["routes"]))              # same registration order
        bad = []
        for p, (st, shape) in self.base["routes"].items():
            cst, cshape = self.cur["routes"][p]
            if st != "UNSTABLE" and cst != st:
                bad.append(f"{p}: status {cst} != {st}")
            if shape is not None and cshape != shape:
                bad.append(f"{p}: keys {cshape} != {shape}")
        self.assertEqual(bad, [])
        self.assertGreater(len(self.base["routes"]), 240)
        self.assertGreater(sum(1 for st, _ in self.base["routes"].values() if st == 200), 200)


# ------------------------------------------------------------------------------------------------------------ 4. routes inventory
class TestRouteInventoryVsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = _env.TempData()
        cls.base = _base()["inventory"]
        import routes_inventory as RI
        cls.RI = RI
        cls.cur = {ed: [[r["method"], r["path"], r["handler"], r["line"], r["order_path"]] for r in RI.routes(ed)] for ed in ("OWNER", "CLIENT")}

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_only_the_file_of_the_handler_and_the_line_change(self):
        for ed in ("OWNER", "CLIENT"):
            b, c = self.base[ed], self.cur[ed]
            self.assertEqual(len(c), len(b), ed)
            for rb, rc in zip(b, c):
                self.assertEqual((rc[0], rc[1], rc[2].split(":")[-1], rc[4]), (rb[0], rb[1], rb[2].split(":")[-1], rb[4]), rb)
            moved_files = {rc[2].rsplit(":", 1)[0] for rb, rc in zip(b, c) if rb[2] != rc[2]}
            base_files = {rb[2].rsplit(":", 1)[0] for rb, rc in zip(b, c) if rb[2] != rc[2]}
            self.assertEqual(base_files, {"backend/masterquo/api/app.py"}, ed)
            self.assertTrue(all(f.startswith("backend/masterquo/api/routes/") for f in moved_files), moved_files)
            kept = {rb[1] for rb, rc in zip(b, c) if rb[2] == rc[2] and rb[2].startswith("backend/masterquo/api/app.py:")}
            self.assertEqual(kept, set(PAGE_ROUTES), ed)

    def test_committed_inventory_matches_app(self):
        self.assertEqual(self.RI.check(), [])
        inv = json.loads(self.RI.OUT.read_text(encoding="utf-8"))
        cur = {(x["method"], x["path"]): x for x in inv["routes"]}
        for m, p, h, line, op in self.cur["OWNER"]:
            if m == "HEAD":
                continue
            self.assertEqual((cur[(m, p)]["handler"], cur[(m, p)]["line"], cur[(m, p)]["class"] == "EXECUTION"), (h, line, op), (m, p))


# ---------------------------------------------------------------------------------------------------------- 5. old names importable
class TestOldNamesImportable(unittest.TestCase):
    GREP = ("create_app", "body_num", "deals_coverage_from_utc", "LocalSecurity", "ExecReq", "SecretReq", "StrategyToggleReq",
            "STUDIO_LAUNCH_WAIT_S")                 # names imported / read / patched from masterquo.api.app before the split

    def test_full_list_of_base_names(self):
        from masterquo.api import app as A
        names = _base()["module_names"]
        self.assertTrue(set(self.GREP) <= set(names))
        missing = [n for n in names if n not in DROPPED_IMPORTS and not hasattr(A, n)]
        self.assertEqual(missing, [])
        self.assertLessEqual(DROPPED_IMPORTS, set(names))

    def test_aliases_are_the_moved_objects(self):
        from masterquo import stats, timeutil
        from masterquo.api import app as A
        from masterquo.api import common, schemas, security
        from masterquo.api.routes import appearance, market, studio
        for n in _base()["module_names"]:
            if isinstance(getattr(A, n, None), type) and n.endswith("Req"):
                self.assertIs(getattr(A, n), getattr(schemas, n), n)
                self.assertEqual(getattr(schemas, n).__module__, "masterquo.api.schemas")
        self.assertIs(A.body_num, common.body_num)
        self.assertIs(A.deals_coverage_from_utc, stats.deals_coverage_from_utc)
        self.assertIs(A.LocalSecurity, security.LocalSecurity)
        self.assertIs(A.TIMEFRAMES, timeutil.TIMEFRAMES)
        self.assertEqual((A.STUDIO_LAUNCH_WAIT_S, A.SYMBOL_RX), (studio.STUDIO_LAUNCH_WAIT_S, market.SYMBOL_RX))
        self.assertEqual((A.STUDIO_LAUNCH_WAIT_S, A.SYMBOL_RX), (5.0, r"^[A-Za-z0-9._#&$!+\-]{1,40}$"))
        self.assertIs(A.MEDIA_SLOTS, appearance.MEDIA_SLOTS)
        self.assertEqual(A.MAX_GIF_BYTES, 15 * 1024 * 1024)

    def test_models_keep_fields_and_constraints(self):
        from masterquo.api import schemas
        self.assertEqual(sorted(schemas.ExecReq.model_fields), ["decision_id"])
        self.assertEqual(schemas.MLModeReq.model_json_schema()["properties"]["mode"]["pattern"], "^(OFF|SHADOW|ASSIST)$")
        self.assertTrue(issubclass(schemas.MarketZonesLiveReq, schemas.MarketZonesReq))


# ------------------------------------------------------------------------------------------------------------- 6. routes package
class TestRoutesPackage(unittest.TestCase):
    def test_route_modules_in_the_api_layer(self):
        import cycles
        for mod in ("masterquo.api.routes", "masterquo.api.routes.core", "masterquo.api.routes._shared", "masterquo.api.schemas"):
            self.assertEqual(cycles.component(mod), "api", mod)
        self.assertEqual(cycles.LAYERS["api"], 5)

    def test_no_owner_code_markers_and_owner_routes_only_in_owner_edition(self):
        import verify_release as VR
        api = _env.ROOT / "backend/masterquo/api"
        files = [api / "app.py", api / "schemas.py", *sorted((api / "routes").glob("*.py"))]
        self.assertGreater(len(files), 30)
        for f in files:
            b = f.read_bytes()
            self.assertEqual([m for m in VR.CLIENT_MARKERS if m in b], [], f.name)
            self.assertNotIn(str(f.relative_to(_env.ROOT)).replace(os.sep, "/"), VR.OWNER_ONLY)
        lic = (api / "routes/licensing.py").read_text(encoding="utf-8")
        self.assertIn('if rt.license.edition == "OWNER":\n        from ..owner_routes import register as _register_owner_routes', lic)
        self.assertEqual({p.name for p in (api / "routes").glob("*.py") if "owner_routes" in p.read_text(encoding="utf-8")}, {"licensing.py"})

    def test_client_edition_builds_without_owner_routes(self):
        td = _env.TempData()
        try:
            app = build_app("CLIENT")
            owner = build_app("OWNER")
        finally:
            td.close()
        paths_c = {r.path for r in app.router.routes}
        paths_o = {r.path for r in owner.router.routes}
        self.assertFalse(any(p.startswith(f"{V1}/owner/") for p in paths_c))
        self.assertTrue(any(p.startswith(f"{V1}/owner/") for p in paths_o))
        self.assertEqual(len(app.router.routes), 513)

    def test_client_package_runtime_builds_the_client_routes(self):
        # paczka klienta: bez plików OWNER_ONLY, edycja CLIENT (licensing/edition.py) - create_app na Runtime(demo=True) buduje dokładnie
        # trasy edycji CLIENT bazy; bez licencji działa tylko zdrowie / sesja / licencja (Guard: 402), owner_routes nigdy nie importowany
        cur = _run_probe("--client-probe")
        base = [[r[1], r[2]] for r in _base()["editions"]["CLIENT"]["routes"]]
        self.assertEqual((cur["edition"], cur["locked"], cur["index"]), ("CLIENT", True, 200))
        self.assertEqual(cur["routes"], base)
        self.assertEqual(cur["owner_modules_loaded"], [])
        self.assertEqual(cur["status"], {"/health": 200, "/session": 200, "/license/status": 200, "/state": 402, "/lab": 402,
                                         "/baskets": 402})

    def test_integration_matrix_still_sees_every_create_app_route(self):
        # tools/integration_matrix._routes() szukał dekoratorów @app.<metoda>("...") tylko w api/app.py - po podziale widział 13 tras
        # zamiast 421 i zgłaszał trasy STU / IND / AUD / ARC jako brakujące; czyta teraz też api/routes/*.py
        import integration_matrix as IM
        base = {k.split(":", 2)[2] for k, *_ in _base()["statements"] if k.startswith("route:") and not k.startswith("route:websocket")}
        self.assertEqual(base - IM._routes(), set())
        self.assertEqual(len(base), 413)                                             # distinct paths of create_app

    def test_registration_covers_every_route_module(self):
        from masterquo.api import routes as R
        mods = {p.stem for p in (_env.ROOT / "backend/masterquo/api/routes").glob("*.py")} - {"__init__", "_shared"}
        used = {fn.__module__.rsplit(".", 1)[1] for fn in R.REGISTRATION}
        self.assertEqual(used, mods)
        self.assertEqual(len(R.REGISTRATION), len(set(R.REGISTRATION)))
        self.assertTrue(all(fn.__name__.startswith("register") for fn in R.REGISTRATION))

    def test_each_create_app_call_gets_its_own_shared_helpers(self):
        import inspect

        from masterquo.api import routes as R
        td = _env.TempData()
        try:
            a1, a2 = build_app("OWNER"), build_app("OWNER")
        finally:
            td.close()
        ep1 = {(r.path, tuple(sorted(getattr(r, "methods", None) or ()))): r.endpoint for r in a1.router.routes if hasattr(r, "endpoint")}
        ep2 = {(r.path, tuple(sorted(getattr(r, "methods", None) or ()))): r.endpoint for r in a2.router.routes if hasattr(r, "endpoint")}
        k = (f"{V1}/lab/neural/train", ("POST",))
        j1, j2 = inspect.getclosurevars(ep1[k]).nonlocals["_nss_job"], inspect.getclosurevars(ep2[k]).nonlocals["_nss_job"]
        self.assertIsNot(j1, j2)                                                          # closures of ONE create_app call each
        lab_train = inspect.getclosurevars(ep1[(f"{V1}/lab/train", ("POST",))]).nonlocals["_nss_job"]
        self.assertIs(lab_train, j1)                                                      # lab and NSS share the same helper
        self.assertTrue(callable(R.register_all))


if __name__ == "__main__":
    unittest.main()
