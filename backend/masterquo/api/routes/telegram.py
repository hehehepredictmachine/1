"""API routes: Telegram.

register(app, ctx): Telegram (tylko informacje)
    (6 routes; create_app before the split, 7ba7ab0: lines 4028-4065)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

from fastapi import HTTPException

from ..schemas import TelegramTemplateReq


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 4028-4065: 6 routes."""
    rt = ctx.rt

    # ------------------------------------------------------------ Telegram (information only; token = local secret, never returned)
    @app.get("/api/v1/telegram")
    def telegram_status():
        return rt.telegram.status()

    @app.get("/api/v1/telegram/template")
    def telegram_template_get():
        """1.32 Message Studio: the saved signal template (own file, not config.json) and the allowed variables."""
        return rt.telegram.templates.info()

    @app.put("/api/v1/telegram/template")
    def telegram_template_put(req: TelegramTemplateReq):
        try:
            tpl = rt.telegram.templates.set(req.template)
        except ValueError as exc:
            raise HTTPException(400, f"TEMPLATE: {exc}") from exc
        rt.log.info("TELEGRAM", "TEMPLATE_SAVED", "Szablon sygnału Telegram: " + ("własny" if tpl else "format wbudowany"))
        return rt.telegram.templates.info()

    @app.post("/api/v1/telegram/preview")
    def telegram_preview(req: TelegramTemplateReq):
        """1.32 Message Studio: the signal message as it would be sent (last real signal, else an example marked as such)."""
        try:
            return rt.telegram.preview(req.template)
        except ValueError as exc:
            raise HTTPException(400, f"TEMPLATE: {exc}") from exc

    @app.post("/api/v1/telegram/test")
    def telegram_test(req: TelegramTemplateReq | None = None):
        try:
            r = rt.telegram.send_test(req.template if req and req.template is not None else None)
        except ValueError as exc:
            raise HTTPException(400, f"TEMPLATE: {exc}") from exc
        rt.log.info("TELEGRAM", "TEST", "Wiadomość testowa Telegram: " + ("dostarczona" if r["ok"] else f"błąd – {r['error']}"))
        return r

    @app.post("/api/v1/telegram/stats-now")
    def telegram_stats_now():
        return {"sent": rt.telegram.send_daily_stats(force=True), "status": rt.telegram.status()}
