"""API routes: websocket.

register(app, ctx): websocket
    (1 routes; create_app before the split, 7ba7ab0: lines 4153-4195)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect

from ..security import SESSION_COOKIE


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 4153-4195: 1 routes."""
    sec = ctx.sec
    rt = ctx.rt
    full_state = ctx.full_state

    # ------------------------------------------------------------ websocket
    @app.websocket("/api/v1/ws")
    async def ws(websocket: WebSocket):
        if not sec.host_ok(websocket.headers.get("host")) or not sec.origin_ok(websocket.headers.get("origin")):
            await websocket.close(code=4403)
            return
        if rt.license.locked:                                          # 1.44.0: bez ważnej licencji brak strumienia danych
            await websocket.close(code=4402)
            return
        sid = websocket.cookies.get(SESSION_COOKIE)
        await websocket.accept()
        try:
            hello = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=10))
        except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
            await websocket.close(code=4400)
            return
        if not isinstance(hello, dict):            # 1.46: valid JSON that is not an object was an AttributeError (1011 instead of 4400)
            await websocket.close(code=4400)
            return
        if not sec.csrf_ok(sid, hello.get("csrf")):
            await websocket.close(code=4403)
            return
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        unsub = rt.bus.subscribe_async(asyncio.get_running_loop(), queue)
        try:
            last = hello.get("last_seq")
            replay = rt.bus.since(int(last)) if isinstance(last, int) and hello.get("boot_id") == rt.bus.boot_id else None
            if replay is None:
                await websocket.send_text(json.dumps({"type": "resync", "seq": rt.bus.seq, "boot_id": rt.bus.boot_id, "state": full_state()}, default=str))
            else:
                for ev in replay:
                    await websocket.send_text(json.dumps(ev, default=str))
            while True:
                ev = await queue.get()
                if ev.get("type") == "__overflow__":
                    while not queue.empty():
                        queue.get_nowait()
                    await websocket.send_text(json.dumps({"type": "resync", "seq": rt.bus.seq, "boot_id": rt.bus.boot_id, "state": full_state()}, default=str))
                    continue
                await websocket.send_text(json.dumps(ev, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsub()
