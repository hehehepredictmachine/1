"""CLI of the exporters (Apollo23 1.46): `python -m masterquo export-<name> [--out DIR] [--format csv|jsonl|both] [params]`,
`python -m masterquo export-list`, `python -m masterquo import-trader-life-game --from DIR [--dry-run]`.

Sources that live in the memory of the running app (order flow ledger, ASGE trials, SFB snapshots, MT5 bars for the SHADOW models, the
PT / DT journal) are exported BY the running app: the CLI calls its local API (same session cookie as the monitor page) and copies the
finished folder to --out. Without a running app such an export is written with status UNAVAILABLE (exit code 3) - never with made-up rows."""
from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from .. import paths
from . import registry as R
from .core import Collected, ExportError, export_dir, list_exports, write_export
from .sources import SourceContext

EXIT_OK, EXIT_BAD, EXIT_UNAVAILABLE = 0, 2, 3


def add_parsers(sub) -> None:
    for e in R.EXPORTERS.values():
        p = sub.add_parser(f"export-{e.name}", help=f"{e.title} ({e.task}) – CSV + JSONL + manifest.json")
        p.add_argument("--out", default=None, help="folder docelowy (domyślnie <dane>/exports); eksport trafia do podfolderu <nazwa>-<czas UTC>-<id>")
        p.add_argument("--format", choices=("csv", "jsonl", "both"), default="both")
        for prm in e.params:
            flag = "--" + prm.name.replace("_", "-")
            if prm.kind == "bool":
                p.add_argument(flag, dest=prm.name, default=None, choices=("true", "false"), help=prm.help or None)
            else:
                p.add_argument(flag, dest=prm.name, default=None, help=(prm.help or "") + (f" (domyślnie {prm.default})" if prm.default not in (None, "") else ""))
    sub.add_parser("export-list", help="lista eksporterów i ostatnich eksportów")
    ti = sub.add_parser("import-trader-life-game", help="import kopii zapasowej TraderLifeGame (addytywny, idempotentny, z kopią bazy przed importem)")
    ti.add_argument("--from", dest="src", required=True, help="folder eksportu trader-life-game (z manifest.json)")
    ti.add_argument("--dry-run", action="store_true", help="tylko podgląd – nic nie zapisuje")


def _formats(f: str) -> tuple:
    return ("csv", "jsonl") if f == "both" else (f,)


def _print_manifest(man: dict, where: str) -> None:
    print(f"[Apollo23] Eksport {man['export_name']}: {man['status']} · wierszy {man['total_rows']} · {where}")
    for f in man.get("files", []):
        print(f"  {f['path']:<40} {f['rows']:>8} wierszy  sha256 {f['sha256'][:16]}…  ({f['data_kind']})")
    for n in man.get("notes") or []:
        print(f"  uwaga: {n}")


def _via_app(name: str, params: dict, fmt: str) -> dict | None:
    """Ask the running app to export (it owns the in-memory source). None = app not running."""
    from .. import localapi
    port = localapi.port()
    h = localapi.health(port, 1.5)
    if not h:
        return None
    base = f"http://127.0.0.1:{port}"
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    hdr = {"Host": f"127.0.0.1:{port}"}
    op.open(urllib.request.Request(base + "/", headers=hdr), timeout=15).read(0)            # session cookie, as the monitor page gets it
    q = {k: (",".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v) for k, v in params.items() if v is not None}
    q["format"] = fmt
    url = f"{base}/api/v1/exports/{urllib.parse.quote(name)}?{urllib.parse.urlencode(q)}"
    try:
        with op.open(urllib.request.Request(url, headers=hdr), timeout=600) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except Exception:  # noqa: BLE001
            detail = None
        raise ExportError(f"APP_EXPORT_FAILED: HTTP {exc.code} {detail or ''}".strip()) from None


def run_export(name: str, args) -> int:
    ex = R.EXPORTERS[name]
    raw = {p.name: getattr(args, p.name, None) for p in ex.params}
    try:
        params = ex.parse_params({k: v for k, v in raw.items() if v is not None})
        out_root = Path(args.out).expanduser() if args.out else None
        if ex.needs_app:
            man = _via_app(name, {k: v for k, v in raw.items() if v is not None}, args.format)
            if man is None:
                col = Collected([], {"source": ex.title, "unavailable_reason": "APP_NOT_RUNNING"}, status="UNAVAILABLE",
                                notes=["APP_NOT_RUNNING: to źródło istnieje tylko w pamięci działającej aplikacji – uruchom Apollo23 i powtórz"])
                man = write_export(name, col, out_root=out_root, formats=_formats(args.format), params=params)
                _print_manifest(man, man["path"])
                return EXIT_UNAVAILABLE
            src = Path(man.get("path") or export_dir(man["export_id"]))
            where = str(src)
            if out_root:
                out_root.mkdir(parents=True, exist_ok=True)
                dst = out_root / src.name
                if dst.exists():
                    raise ExportError(f"OUT_EXISTS: {dst}")
                shutil.copytree(src, dst)
                where = str(dst)
            _print_manifest(man, where)
            return EXIT_OK if man["status"] != "UNAVAILABLE" else EXIT_UNAVAILABLE
        man = R.run(name, SourceContext(paths.data_dir()), params, formats=_formats(args.format), out_root=out_root)
        _print_manifest(man, man["path"])
        return EXIT_OK if man["status"] != "UNAVAILABLE" else EXIT_UNAVAILABLE
    except ExportError as exc:
        print(f"[Apollo23] [BŁĄD] eksport {name}: {exc}", file=sys.stderr)
        return EXIT_BAD


def list_cmd() -> int:
    print("[Apollo23] Eksportery (python -m masterquo export-<nazwa> --out <folder>):")
    for e in R.EXPORTERS.values():
        prm = " ".join(f"--{p.name.replace('_', '-')}" for p in e.params)
        print(f"  export-{e.name:<20} {e.task:<18} {'[wymaga działającej aplikacji] ' if e.needs_app else ''}{e.title}  {prm}")
    rec = list_exports(paths.data_dir(), limit=15)
    if rec:
        print("Ostatnie eksporty (<dane>/exports):")
        for r in rec:
            print(f"  {r['export_id']}  {r['status']}  wierszy {r['total_rows']}")
    return EXIT_OK


def import_tlg_cmd(args) -> int:
    from .tlg_import import import_backup
    try:
        rep = import_backup(Path(args.src).expanduser(), paths.data_dir(), dry_run=args.dry_run)
    except ExportError as exc:
        print(f"[Apollo23] [BŁĄD] import TraderLifeGame: {exc}", file=sys.stderr)
        return EXIT_BAD
    print(f"[Apollo23] Import TraderLifeGame{' (podgląd)' if rep['dry_run'] else ''}: dodano {rep['total_inserted']} wierszy; profil: {rep['profile']}")
    for t, n in rep["inserted"].items():
        print(f"  {t:<14} dodano {n:>6}  pominięto (już są) {rep['skipped_existing'].get(t, 0):>6}  odrzucono {rep['rejected'].get(t, 0):>4}")
    if rep.get("pre_import_copy"):
        print(f"  kopia bazy sprzed importu: {rep['pre_import_copy']}")
    return EXIT_OK
