"""API routes: wygląd.

register(app, ctx): wygląd: media tła / żabki
    (3 routes; create_app before the split, 7ba7ab0: lines 3939-3974)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

from ... import paths
from ...media.gifinfo import gif_info

MEDIA_SLOTS = {"background": ("background-matrix.gif", "background-matrix-static.webp"), "frog": ("frog-dance.gif", "frog-dance-static.png")}
MAX_GIF_BYTES = 15 * 1024 * 1024


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 3939-3974: 3 routes."""
    rt = ctx.rt
    media_dir = ctx.media_dir

    @app.get("/api/v1/appearance/assets")
    def appearance_assets():
        out = {}
        for slot, (anim, static_name) in MEDIA_SLOTS.items():
            user = media_dir() / anim
            built = paths.FRONTEND_DIST / "assets" / "masterquo" / anim
            info = gif_info(user.read_bytes()) if user.is_file() else (gif_info(built.read_bytes()) if built.is_file() else None)
            out[slot] = {"animated_available": user.is_file() or built.is_file(), "source": "USER_UPLOAD" if user.is_file() else ("BUILT_IN" if built.is_file() else "NONE"),
                         "animated_url": f"/media/masterquo/{slot}?v={int(user.stat().st_mtime) if user.is_file() else 0}",
                         "static_url": f"/static/assets/masterquo/{static_name}", "gif": info}
        return out

    @app.post("/api/v1/appearance/upload")
    async def appearance_upload(request: Request, slot: str = Query(..., pattern="^(background|frog)$")):
        data = await request.body()
        if len(data) > MAX_GIF_BYTES:
            raise HTTPException(413, "FILE_TOO_LARGE")
        info = gif_info(data)
        if not info:
            raise HTTPException(400, "NOT_A_GIF")
        target = media_dir() / MEDIA_SLOTS[slot][0]
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        rt.log.info("UI", "ASSET_UPLOADED", f"Wgrano GIF ({slot}): {info['width']}×{info['height']}, {info['frames']} klatek, pętla {info['loop_duration_ms']} ms")
        return {"ok": True, "slot": slot, "gif": info}

    @app.get("/media/masterquo/{slot}")
    def media(slot: str):
        if slot not in MEDIA_SLOTS:
            raise HTTPException(404)
        name = MEDIA_SLOTS[slot][0]
        for f in (media_dir() / name, paths.FRONTEND_DIST / "assets" / "masterquo" / name):
            if f.is_file():
                return FileResponse(f, media_type="image/gif", headers={"Cache-Control": "no-cache"})
        raise HTTPException(404)
