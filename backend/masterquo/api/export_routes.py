"""Export API (Apollo23 1.46): GET /api/v1/exports[/<name>] writes ONLY into <data>/exports/<id> (no path parameter exists).

The GET endpoints need the monitor session cookie (SameSite=Strict, Guard middleware) like every /api/v1 GET, so a foreign web page cannot
trigger an export; the TraderLifeGame import is a POST (Origin + CSRF) and reads only an export folder by its validated id."""
from __future__ import annotations

import threading

from fastapi import Body, HTTPException, Request

from .. import paths


def register(app, rt) -> None:
    from ..exports import core as C
    from ..exports import registry as R
    from ..exports import sources as S
    _busy = threading.Lock()

    def ctx() -> S.SourceContext:
        own = getattr(rt, "wf32", None)                  # 1.46 arch (I0088): the Runtime's objects (app.state.wf32 is the same dict)
        return S.SourceContext(paths.data_dir(), rt=rt, wf32=own if isinstance(own, dict) else (getattr(app.state, "wf32", None) or {}))

    def _formats(fmt: str | None) -> tuple:
        f = (fmt or "both").lower()
        if f == "both":
            return C.FORMATS
        if f not in C.FORMATS:
            raise HTTPException(400, "format: csv | jsonl | both")
        return (f,)

    @app.get("/api/v1/exports")
    def exports_index():
        return {"schema_version": C.SCHEMA_VERSION, "folder": "<dane>/exports",
                "exporters": [{"name": e.name, "title": e.title, "task": e.task, "needs_running_app": e.needs_app,
                               "params": [{"name": p.name, "type": p.kind, "default": p.default, "choices": p.choices, "min": p.lo, "max": p.hi,
                                           "help": p.help} for p in e.params]} for e in R.EXPORTERS.values()],
                "recent": C.list_exports(paths.data_dir(), limit=50)}

    @app.get("/api/v1/exports/{name}/{export_id}/manifest")
    def export_manifest(name: str, export_id: str):
        if name not in R.EXPORTERS:
            raise HTTPException(404, "UNKNOWN_EXPORTER")
        try:
            d = C.export_dir(export_id, paths.data_dir())
        except C.ExportError as exc:
            raise HTTPException(404, str(exc)) from None
        v = C.verify_export(d)
        if not v["manifest"] or v["manifest"].get("export_name") != name:
            raise HTTPException(404, "EXPORT_NOT_FOUND")
        return {**v["manifest"], "verification": {"ok": v["ok"], "problems": v["problems"]}}

    @app.get("/api/v1/exports/{name}")
    def export_run(name: str, request: Request):
        if name not in R.EXPORTERS:
            raise HTTPException(404, f"UNKNOWN_EXPORTER: {name} ({', '.join(R.EXPORTERS)})")
        q = dict(request.query_params)
        fmts = _formats(q.pop("format", None))
        if not _busy.acquire(blocking=False):
            raise HTTPException(409, "EXPORT_BUSY: trwa inny eksport")
        try:
            man = R.run(name, ctx(), q, formats=fmts)
        except C.ExportError as exc:
            raise HTTPException(400, str(exc)[:400]) from None
        except Exception as exc:  # noqa: BLE001 - provider / store failure: reported, nothing half-written (atomic folder)
            raise HTTPException(503, f"EXPORT_FAILED: {type(exc).__name__}: {exc}"[:300]) from None
        finally:
            _busy.release()
        return {**man, "relative_path": f"exports/{man['export_id']}"}

    @app.post("/api/v1/exports/trader-life-game/import")
    def tlg_import(body: dict = Body(...)):
        from ..exports.tlg_import import import_backup
        eid = body.get("export_id")
        dry = body.get("dry_run", False)
        if not isinstance(dry, bool):
            raise HTTPException(400, "dry_run: bool")
        try:
            folder = C.export_dir(str(eid or ""), paths.data_dir())
        except C.ExportError as exc:
            raise HTTPException(404, str(exc)) from None
        if not _busy.acquire(blocking=False):
            raise HTTPException(409, "EXPORT_BUSY: trwa inny eksport / import")
        try:
            return import_backup(folder, paths.data_dir(), dry_run=dry)
        except C.ExportError as exc:
            raise HTTPException(400, str(exc)[:400]) from None
        finally:
            _busy.release()
