"""Apollo23 workflow v3.2 routes (TASK 001-025). Every new module is read-only / OFF / SHADOW by default; none of these routes can send,
modify or close an order or change risk / STOP / execution mode."""
from __future__ import annotations

import threading

from fastapi import Body, HTTPException

from .. import paths


def register(app, rt) -> None:
    _lock = threading.Lock()
    _svc: dict = {}

    def lazy(name, factory):
        with _lock:
            if name not in _svc:
                _svc[name] = factory()
            return _svc[name]

    # ------------------------------------------------------------------ TASK 019: TraderLifeGame
    from ..trader_life_game import GameError, GameService, ReadOnlyAccountView

    def tlg():
        return lazy("tlg", lambda: GameService(paths.data_dir() / "trader_life_game", ReadOnlyAccountView.from_bridge(getattr(rt, "bridge", None))))

    def g(fn, *a, **k):
        try:
            return fn(*a, **k)
        except GameError as exc:
            raise HTTPException(exc.status, f"{exc.code}: {exc.detail}" if exc.detail else exc.code) from None

    @app.get("/api/v1/tlg/meta")
    def tlg_meta():
        return {**tlg().classes(), "navigation_id": "TRADER_LIFEGAME", "market_profile": None, "execution": "ISOLATED"}

    @app.get("/api/v1/tlg/state")
    def tlg_state():
        s = tlg()
        if s._profile(required=False) is None:
            return {"profile": None, "needs_character": True}
        return g(s.state)

    @app.post("/api/v1/tlg/profile")
    def tlg_profile_create(body: dict = Body(...)):
        return g(tlg().create_profile, body)

    @app.put("/api/v1/tlg/profile")
    def tlg_profile_update(body: dict = Body(...)):
        return g(tlg().update_profile, body)

    @app.get("/api/v1/tlg/xp")
    def tlg_xp(limit: int = 100):
        return {"items": g(tlg().xp_history, limit)}

    @app.get("/api/v1/tlg/journal")
    def tlg_journal():
        return g(tlg().journal)

    @app.put("/api/v1/tlg/journal/{ref}")
    def tlg_annotate(ref: str, body: dict = Body(...)):
        return g(tlg().annotate, ref, body)

    @app.get("/api/v1/tlg/notes")
    def tlg_notes(kind: str | None = None):
        return {"items": g(tlg().notes, kind)}

    @app.post("/api/v1/tlg/notes/{kind}")
    def tlg_note(kind: str, body: dict = Body(...)):
        return g(tlg().add_note, kind.upper(), body)

    @app.get("/api/v1/tlg/academy")
    def tlg_academy():
        return g(tlg().academy)

    @app.post("/api/v1/tlg/academy/lesson/{lesson_id}")
    def tlg_lesson(lesson_id: str):
        return g(tlg().complete_lesson, lesson_id)

    @app.post("/api/v1/tlg/academy/quiz/{level}")
    def tlg_quiz(level: int, body: dict = Body(...)):
        return g(tlg().submit_quiz, level, body.get("answers"))

    @app.get("/api/v1/tlg/academy/risk")
    def tlg_risk():
        return g(tlg().risk_exercise)

    @app.post("/api/v1/tlg/academy/risk")
    def tlg_risk_submit(body: dict = Body(...)):
        return g(tlg().submit_risk_exercise, str(body.get("exercise_id") or ""), body.get("answer"))

    @app.get("/api/v1/tlg/quests")
    def tlg_quests():
        return {"items": g(tlg().quests)}

    @app.post("/api/v1/tlg/quests/{quest_id}/claim")
    def tlg_claim(quest_id: str):
        return g(tlg().claim, quest_id)

    @app.get("/api/v1/tlg/skills")
    def tlg_skills():
        return g(tlg().skills)

    @app.post("/api/v1/tlg/skills/{skill_id}")
    def tlg_unlock(skill_id: str):
        return g(tlg().unlock_skill, skill_id)

    @app.get("/api/v1/tlg/calendar")
    def tlg_calendar(month: str):
        return g(tlg().calendar, month)

    @app.get("/api/v1/tlg/coach")
    def tlg_coach():
        return g(tlg().coach)

    @app.post("/api/v1/tlg/coach/memory")
    def tlg_mem_add(body: dict = Body(...)):
        return g(tlg().coach_memory_add, body.get("text"))

    @app.delete("/api/v1/tlg/coach/memory")
    def tlg_mem_del(memory_id: int | None = None):
        return g(tlg().coach_memory_delete, memory_id)

    @app.get("/api/v1/tlg/sim")
    def tlg_sims():
        return {"items": g(tlg().sim_sessions)}

    @app.post("/api/v1/tlg/sim")
    def tlg_sim_start(body: dict = Body(...)):
        sym = str(body.get("symbol") or getattr(getattr(rt.cfg.get(), "mt5", None), "symbol", "XAUUSD"))
        return g(tlg().sim_start, sym, str(body.get("tf") or "H1"), int(body.get("count") or 400))

    @app.get("/api/v1/tlg/sim/{sid}")
    def tlg_sim_view(sid: int):
        return g(tlg().sim_view, sid)

    @app.post("/api/v1/tlg/sim/{sid}/step")
    def tlg_sim_step(sid: int, body: dict = Body(default={})):
        return g(tlg().sim_step, sid, int(body.get("n") or 1))

    @app.post("/api/v1/tlg/sim/{sid}/open")
    def tlg_sim_open(sid: int, body: dict = Body(...)):
        return g(tlg().sim_open, sid, str(body.get("side") or ""), body.get("size"), body.get("sl"), body.get("tp"))

    @app.post("/api/v1/tlg/sim/{sid}/close/{trade_id}")
    def tlg_sim_close(sid: int, trade_id: int):
        return g(tlg().sim_close, sid, trade_id)

    @app.post("/api/v1/tlg/sim/{sid}/finish")
    def tlg_sim_finish(sid: int):
        return g(tlg().sim_finish, sid)

    @app.get("/api/v1/tlg/lifestyle")
    def tlg_life():
        return g(tlg().lifestyle)

    @app.post("/api/v1/tlg/lifestyle/{item_id}/buy")
    def tlg_buy(item_id: str):
        return g(tlg().buy, item_id)

    @app.post("/api/v1/tlg/lifestyle/{item_id}/equip")
    def tlg_equip(item_id: str):
        return g(tlg().equip, item_id)

    @app.get("/api/v1/tlg/leaderboard")
    def tlg_board():
        return g(tlg().leaderboard)
