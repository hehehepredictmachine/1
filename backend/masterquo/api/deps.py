"""Shared request validators of the API route modules.

1.46 arch (I0087): the canonical instrument of a request was checked by three different closures in api/app.py (_mm_inst: as given,
UNKNOWN_INSTRUMENT; _th_inst: upper-cased, INSTRUMENT_NOT_ALLOWED; _fam_inst: upper-cased, default = active asset, INSTRUMENT_INVALID)
against literal ("XAUUSD", "BTC") tuples. One helper now, against config.ALLOWED_ASSETS (the trading list defined in code); each route
keeps TODAY's normalisation and error code (the frontend may rely on them - unifying them is a separate decision)."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException

from ..config import ALLOWED_ASSETS


def instrument(value, *, normalize: bool = False, default: str | Callable[[], str] | None = None, error_code: str = "UNKNOWN_INSTRUMENT") -> str:
    """The canonical instrument of a request, or HTTP 400 `error_code`.

    normalize=False: the value must be exactly one of ALLOWED_ASSETS ('xauusd' -> 400, as /api/v1/mm/* did);
    normalize=True:  str(value).upper() first ('xauusd' -> 'XAUUSD', as /api/v1/trainhub/* and /api/v1/families/* did);
    default:         used for an empty (falsy) value, as `instrument or active` did; a callable is evaluated only then (the active
                     asset of /families)."""
    v = value
    if not v:
        v = default() if callable(default) else default
    if normalize:
        v = str(v).upper() if v is not None else ""
    if v not in ALLOWED_ASSETS:
        raise HTTPException(400, error_code)
    return v
