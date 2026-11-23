"""Import of implied-volatility observations (CSV or JSON) with validation -> table iv_observations.

Required fields per row:
  observed_at      UTC ISO time of the observation (e.g. 2026-10-12T20:00:00Z)
  available_at     UTC ISO time from which the value was PUBLICLY known (>= observed_at). Historical studies may use the
                   value only from this moment - today's manual reading is not history.
  underlier        instrument of the volatility (e.g. GLD for GVZ, GC futures contract code, or XAUUSD-)
  source           where it comes from (e.g. "Cboe GVZ close", "CME CVOL")
  sigma_annual     the value
  unit             "percent" (e.g. 16.4) or "fraction" (e.g. 0.164) - REQUIRED, never guessed
  day_count_basis  "ACT_365" (calendar days - typical for option IV / indices) or "TRADING_252"
  tenor_days       horizon of the volatility (e.g. 30 for GVZ) - or `expiry` (UTC ISO date of the option expiry)
  quality          "OK" / "ESTIMATED" / "STALE" (rows not "OK"/"ESTIMATED" are stored but never used)
Optional: valid_until (default available_at + 3 days), note.
Validation: ranges (fraction 0.01..3.0, percent 1..300), unit/basis vocabularies, available_at >= observed_at, duplicates
(underlier, source, observed_at, tenor) rejected; tenor_days a finite number > 0, valid_until a UTC ISO time >= available_at.
The report lists every rejected row with its reason - nothing is silently corrected and one bad row never aborts the import.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import timedelta

from ..timeutil import iso, parse_iso, utcnow

REQUIRED = ("observed_at", "available_at", "underlier", "source", "sigma_annual", "unit", "day_count_basis", "quality")


def parse_text(text: str, fmt: str | None = None) -> list[dict]:
    # 1.46: a UTF-8 BOM (Excel "CSV UTF-8") is not whitespace - the first header became '\ufeffobserved_at' and every row was
    # rejected as MISSING_FIELDS:observed_at
    t = text.lstrip("\ufeff").strip()
    if (fmt or "").lower() == "json" or t.startswith("[") or t.startswith("{"):
        data = json.loads(t)
        return data["rows"] if isinstance(data, dict) else list(data)
    lines = [ln for ln in t.splitlines() if not ln.lstrip().startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def validate(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    ok, bad, seen = [], [], set()
    for n, r in enumerate(rows, 1):
        # 1.46: a JSON row that is not an object (r.items() -> AttributeError) aborted the whole import with HTTP 500
        if not isinstance(r, dict):
            bad.append({"row": n, "reason": "ROW_NOT_OBJECT"})
            continue
        r = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k}
        miss = [k for k in REQUIRED if r.get(k) in (None, "")]
        if miss:
            bad.append({"row": n, "reason": "MISSING_FIELDS:" + ",".join(miss)})
            continue
        try:
            obs, av = parse_iso(str(r["observed_at"])), parse_iso(str(r["available_at"]))
        except (ValueError, TypeError) as exc:
            # 1.46: parse_iso raises NAIVE_TIMESTAMP for a time without a zone - the documented TIME_WITHOUT_UTC_ZONE was unreachable
            bad.append({"row": n, "reason": "TIME_WITHOUT_UTC_ZONE" if str(exc) == "NAIVE_TIMESTAMP" else "BAD_TIME_FORMAT"})
            continue
        if av < obs:
            bad.append({"row": n, "reason": "AVAILABLE_BEFORE_OBSERVED"})
            continue
        unit = str(r["unit"]).lower()
        try:
            val = float(r["sigma_annual"])
        except (TypeError, ValueError):
            bad.append({"row": n, "reason": "SIGMA_NOT_A_NUMBER"})
            continue
        if unit == "percent":
            if not 1.0 <= val <= 300.0:
                bad.append({"row": n, "reason": f"SIGMA_PERCENT_OUT_OF_RANGE_{val}"})
                continue
            sig = val / 100.0
        elif unit == "fraction":
            if not 0.01 <= val <= 3.0:
                bad.append({"row": n, "reason": f"SIGMA_FRACTION_OUT_OF_RANGE_{val}"})
                continue
            sig = val
        else:
            bad.append({"row": n, "reason": f"UNKNOWN_UNIT_{unit}"})
            continue
        basis = str(r["day_count_basis"]).upper()
        if basis not in ("ACT_365", "TRADING_252"):
            bad.append({"row": n, "reason": f"UNKNOWN_DAY_COUNT_{basis}"})
            continue
        tenor = r.get("tenor_days")
        expiry = r.get("expiry")
        if tenor in (None, "") and expiry in (None, ""):
            bad.append({"row": n, "reason": "TENOR_OR_EXPIRY_REQUIRED"})
            continue
        # 1.46: float('30d') / a non-scalar expiry / a non-text underlier ('|'.join) / an unparsable or zone-less valid_until raised
        # out of validate() and aborted the whole import (HTTP 500 / CLI traceback); a negative tenor and a valid_until before
        # available_at (a row that can never be used) were accepted silently
        tdays = None
        if tenor not in (None, ""):
            try:
                tdays = float(tenor)
            except (TypeError, ValueError):
                bad.append({"row": n, "reason": "TENOR_NOT_A_NUMBER"})
                continue
            if not math.isfinite(tdays) or tdays <= 0:
                bad.append({"row": n, "reason": "TENOR_NOT_POSITIVE"})
                continue
        if isinstance(expiry, (dict, list, bool)):
            bad.append({"row": n, "reason": "BAD_EXPIRY"})
            continue
        vu = r.get("valid_until")
        try:
            until = parse_iso(str(vu)) if vu else av + timedelta(days=3)
        except (ValueError, TypeError) as exc:
            bad.append({"row": n, "reason": "VALID_UNTIL_WITHOUT_UTC_ZONE" if str(exc) == "NAIVE_TIMESTAMP" else "BAD_VALID_UNTIL"})
            continue
        if until < av:
            bad.append({"row": n, "reason": "VALID_UNTIL_BEFORE_AVAILABLE"})
            continue
        q = str(r["quality"]).upper()
        und, src = str(r["underlier"]), str(r["source"])
        key = (und, src, iso(obs), str(tenor or expiry))
        if key in seen:
            bad.append({"row": n, "reason": "DUPLICATE"})
            continue
        seen.add(key)
        oid = "IV-" + hashlib.sha256("|".join(key).encode()).hexdigest()[:14]
        ok.append({"obs_id": oid, "observed_at": iso(obs), "available_at": iso(av), "valid_until": iso(until), "underlier": und,
                   "source": src, "sigma_annual": round(sig, 6), "unit_in": unit, "day_count_basis": basis,
                   "tenor_days": tdays, "expiry": expiry or None, "quality": q,
                   "note": r.get("note")})
    return ok, bad


def store(db, rows: list[dict], imported_by: str = "USER") -> dict:
    ok, bad = validate(rows)
    added, dup = 0, 0
    now = iso(utcnow())
    for r in ok:
        if db.one("SELECT 1 AS x FROM iv_observations WHERE obs_id=?", (r["obs_id"],)):
            dup += 1
            continue
        db.execute("""INSERT INTO iv_observations(obs_id, observed_at, available_at, valid_until, underlier, source, sigma_annual, day_count_basis,
                      tenor_days, expiry, quality, imported_at, imported_by, json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (r["obs_id"], r["observed_at"], r["available_at"], r["valid_until"], r["underlier"], r["source"], r["sigma_annual"],
                    r["day_count_basis"], r["tenor_days"], r["expiry"], r["quality"], now, imported_by, json.dumps(r)))
        added += 1
    return {"rows": len(rows), "accepted": added, "already_stored": dup, "rejected": bad}


def latest_usable(db, as_of: str, underliers: list[str] | None = None) -> dict | None:
    """Newest observation that was AVAILABLE at `as_of` and is still valid then (quality OK/ESTIMATED)."""
    q = "SELECT json FROM iv_observations WHERE available_at <= ? AND valid_until >= ? AND quality IN ('OK','ESTIMATED')"
    args: list = [as_of, as_of]
    if underliers:
        q += " AND underlier IN (" + ",".join("?" * len(underliers)) + ")"
        args += underliers
    row = db.one(q + " ORDER BY available_at DESC LIMIT 1", args)
    return json.loads(row["json"]) if row else None
