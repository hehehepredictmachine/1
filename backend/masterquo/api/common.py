"""Request helpers shared by the API route modules (api/app.py, api/wf32_routes.py, ...).

1.46 arch (I0081): ``body_num`` lived in api/app.py and api/wf32_routes.py imported it from there at module level, while app.py imported
wf32_routes lazily inside create_app - an import cycle between the two route modules. The helper lives here now; api/app.py re-exports
the old name (tests and callers keep working)."""
from __future__ import annotations

from fastapi import HTTPException


def body_num(body: dict, key: str, default, cast=int, lo=None, hi=None):
    """1.46: number from a JSON body - a wrong type / NaN / out-of-range value is a 400 with the field name (was an unhandled 500)."""
    raw = body.get(key) if isinstance(body, dict) else None
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        raise HTTPException(400, f"INVALID_{key.upper()}")
    try:
        v = cast(raw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, f"INVALID_{key.upper()}") from None
    # v != v is the NaN check (code moved unchanged from api/app.py)
    if v != v or v in (float("inf"), float("-inf")) or (lo is not None and v < lo) or (hi is not None and v > hi):  # noqa: PLR0124
        raise HTTPException(400, f"{key.upper()}_OUT_OF_RANGE" + (f" ({lo}..{hi})" if lo is not None or hi is not None else ""))
    return v
