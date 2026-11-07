"""Profile zones (PMW-SVP-ZONES-1): sources MANUAL / ALGORITHM / AI kept apart.

ALGORITHM (deterministic, rules v1, from ONE profile snapshot): POC zone (POC bin), HVN zones (their bin), VA edges (VAH / VAL +/- one
bin), LVN zones (low-activity bins between peaks). The justification names the profile snapshot and its data time. These zones are
activity areas of the profile, NOT evidence of institutional orders.

States (causal: evaluated on CLOSED bars after the snapshot's known_at; a forming tick never confirms):
  CANDIDATE    created from the profile;
  CONFIRMED    a later closed bar touched the zone and closed back on its origin side (reaction);
  TESTED       touched again after confirmation (retests counted);
  BROKEN       `break_closes` consecutive closes beyond the far edge (naruszona);
  INVALIDATED  broken and accepted beyond for `accept_closes` more closes;
  EXPIRED      older than ttl_hours.
Profile events (v1): ACCEPTANCE_ABOVE_VA / ACCEPTANCE_BELOW_VA (N consecutive closes outside the value area), RETURN_TO_VA (a close back
inside after acceptance), POC_MIGRATION (developing POC moved >= k bins between two snapshots).

AI proposals (structured) are validated in the backend against the SOURCE snapshot: same symbol, existing snapshot, not stale, both
bounds within the profile range and each bound anchored to a profile level (POC / VAH / VAL / HVN / LVN / a bin edge) within one bin;
type / justification / confirmation / invalidation / valid_until required. Invented prices are rejected.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime

VERSION = "PMW-SVP-ZONES-1"
SOURCES = ("MANUAL", "ALGORITHM", "AI")
STATES = ("CANDIDATE", "CONFIRMED", "TESTED", "BROKEN", "INVALIDATED", "EXPIRED")
AI_TYPES = ("POC", "HVN", "LVN", "VA_EDGE", "VALUE_AREA", "ACCEPTANCE", "REJECTION")


def _ts(x) -> float:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def zone_id(source: str, symbol: str | None, snapshot_id: str | None, kind: str, lo: float, hi: float) -> str:
    return "SZ-" + hashlib.sha256(f"{source}|{symbol}|{snapshot_id}|{kind}|{lo:.10g}|{hi:.10g}".encode()).hexdigest()[:12]


def algorithmic(p: dict) -> list[dict]:
    if p.get("status") not in ("READY", "PARTIAL") or p.get("poc") is None:
        return []
    bs = p["bin_size"]
    t = p.get("known_at")
    out = []

    def add(kind, lo, hi, why):
        lo, hi = round(min(lo, hi), 10), round(max(lo, hi), 10)
        out.append({"zone_id": zone_id("ALGORITHM", p.get("symbol"), p.get("snapshot_id"), kind, lo, hi), "source": "ALGORITHM", "kind": kind,
                    "lower": lo, "upper": hi, "profile_geometry_id": p.get("geometry_id"), "snapshot_id": p.get("snapshot_id"),
                    "symbol": p.get("symbol"), "instrument": p.get("instrument"), "available_at": t, "state": "CANDIDATE", "pinned": False,
                    "justification": f"{why} – profil {p.get('geometry_id')} ({p.get('start')} → {p.get('known_at')}), źródło {p.get('volume_source')}, "
                                     "strefa aktywności profilu, nie dowód zleceń instytucjonalnych", "rules_version": VERSION})
    add("POC", p["poc"] - bs / 2, p["poc"] + bs / 2, "POC (koszyk o największej wadze)")
    add("VA_EDGE_HIGH", p["vah"] - bs, p["vah"], "krawędź VAH")
    add("VA_EDGE_LOW", p["val"], p["val"] + bs, "krawędź VAL")
    for h in p.get("hvn") or []:
        add("HVN", h - bs / 2, h + bs / 2, "HVN (lokalne maksimum aktywności)")
    for lv in p.get("lvn") or []:
        add("LVN", lv - bs / 2, lv + bs / 2, "LVN (obszar niskiej aktywności między szczytami)")
    return out


def evolve(z: dict, bars: list[dict], *, tf_s: int, break_closes: int = 2, accept_closes: int = 3, ttl_hours: float = 72.0,
           as_of: float | None = None) -> dict:
    """Zone state from closed bars after its available_at (pure function of bars <= as_of)."""
    z = dict(z)
    t0 = _ts(z["available_at"]) if z.get("available_at") else 0.0
    as_of = as_of if as_of is not None else time.time()
    lo, hi = z["lower"], z["upper"]
    seq = [b for b in bars if b.get("closed", True) and b.get("open_utc") and _ts(b["open_utc"]) >= t0 - 1e-6 and _ts(b["open_utc"]) + tf_s <= as_of + 1e-6]
    if not seq:
        z.update(state="CANDIDATE", touches=0)
        return z
    first = float(seq[0]["c"])
    origin = "ABOVE" if first > hi else "BELOW" if first < lo else "INSIDE"
    state, touches, beyond, accepted, history = "CANDIDATE", 0, 0, 0, []
    for b in seq[1:]:
        c, h, l = float(b["c"]), float(b["h"]), float(b["l"])
        touched = l <= hi and h >= lo
        far = (c < lo) if origin == "ABOVE" else (c > hi) if origin == "BELOW" else False
        if state in ("BROKEN",):
            accepted = accepted + 1 if far else 0
            if accepted >= accept_closes:
                state = "INVALIDATED"
                history.append({"t": b["open_utc"], "state": state})
                break
            continue
        if far:
            beyond += 1
            if beyond >= break_closes:
                state = "BROKEN"
                history.append({"t": b["open_utc"], "state": state})
            continue
        beyond = 0
        if touched:
            back = (c > hi) if origin == "ABOVE" else (c < lo) if origin == "BELOW" else False
            if back:
                touches += 1
                new = "CONFIRMED" if state == "CANDIDATE" else "TESTED"
                if new != state:
                    history.append({"t": b["open_utc"], "state": new})
                state = new
    if state not in ("INVALIDATED",) and as_of - t0 > ttl_hours * 3600 and not z.get("pinned"):
        state = "EXPIRED"
    z.update(state=state, touches=touches, origin_side=origin, state_history=history[-10:], evaluated_until=seq[-1]["open_utc"])
    return z


def profile_events(p: dict, bars: list[dict], *, tf_s: int, n_accept: int = 3, prev_poc: float | None = None, migration_bins: int = 2) -> list[dict]:
    if p.get("vah") is None:
        return []
    t0 = _ts(p["known_at"]) if p.get("known_at") else 0.0
    seq = [b for b in bars if b.get("open_utc") and _ts(b["open_utc"]) >= t0]
    ev, run_up, run_dn, accepted = [], 0, 0, None
    for b in seq:
        c = float(b["c"])
        run_up = run_up + 1 if c > p["vah"] else 0
        run_dn = run_dn + 1 if c < p["val"] else 0
        if run_up == n_accept:
            accepted = "ABOVE"
            ev.append({"kind": "ACCEPTANCE_ABOVE_VA", "t": b["open_utc"]})
        if run_dn == n_accept:
            accepted = "BELOW"
            ev.append({"kind": "ACCEPTANCE_BELOW_VA", "t": b["open_utc"]})
        if accepted and p["val"] <= c <= p["vah"]:
            ev.append({"kind": "RETURN_TO_VA", "t": b["open_utc"], "from": accepted})
            accepted = None
    if prev_poc is not None and p.get("poc") is not None and abs(p["poc"] - prev_poc) >= migration_bins * p["bin_size"] - 1e-9:
        ev.append({"kind": "POC_MIGRATION", "from": prev_poc, "to": p["poc"], "bins": round((p["poc"] - prev_poc) / p["bin_size"], 2)})
    return ev


def validate_ai(prop: dict, snap: dict | None, *, symbol: str, now: float, max_snapshot_age_s: float = 6 * 3600) -> tuple[bool, str | None, dict | None]:
    """(ok, reason, normalised zone). snap = the stored source snapshot of prop['snapshot_id']."""
    need = ("profile_id", "snapshot_id", "lower", "upper", "type", "justification", "confirmation", "invalidation", "valid_until")
    miss = [k for k in need if prop.get(k) in (None, "")]
    if miss:
        return False, "brak pól: " + ", ".join(miss), None
    if snap is None or snap.get("snapshot_id") != prop["snapshot_id"]:
        return False, "nieznany snapshot profilu", None
    if snap.get("symbol") != symbol or (prop.get("symbol") and prop["symbol"] != symbol):
        return False, "niezgodny symbol", None
    if prop.get("profile_id") not in (snap.get("profile_id"), snap.get("geometry_id")):
        return False, "profil nie odpowiada snapshotowi", None
    if prop["type"] not in AI_TYPES:
        return False, f"nieznany typ strefy {prop['type']}", None
    try:
        lo, hi = float(prop["lower"]), float(prop["upper"])
        vu = _ts(prop["valid_until"])
    except (TypeError, ValueError):
        return False, "niepoprawne liczby / czas", None
    if not (lo < hi):
        return False, "dolna granica musi być niższa od górnej", None
    known = _ts(snap["known_at"]) if snap.get("known_at") else None
    if known is None or now - known > max_snapshot_age_s:
        return False, "snapshot profilu jest nieaktualny", None
    if vu <= now:
        return False, "termin ważności w przeszłości", None
    bs = snap["bin_size"]
    if lo < snap["low"] - bs or hi > snap["high"] + bs:
        return False, "strefa poza zakresem cen profilu", None
    anchors = [snap["poc"], snap["vah"], snap["val"]] + list(snap.get("hvn") or []) + list(snap.get("lvn") or [])
    edges = {round(x["lo"], 10) for x in snap.get("histogram") or []} | {round(x["hi"], 10) for x in snap.get("histogram") or []}

    def anchored(x):
        return any(abs(x - a) <= bs + 1e-9 for a in anchors) or any(abs(x - e) <= 1e-6 for e in edges)
    if not (anchored(lo) and anchored(hi)):
        return False, "granice nie mają podstawy w profilu (POC/VAH/VAL/HVN/LVN/krawędź koszyka)", None
    z = {"zone_id": zone_id("AI", symbol, snap["snapshot_id"], prop["type"], lo, hi), "source": "AI", "kind": prop["type"], "lower": lo,
         "upper": hi, "snapshot_id": snap["snapshot_id"], "profile_geometry_id": snap.get("geometry_id"), "symbol": symbol,
         "instrument": snap.get("instrument"), "available_at": snap.get("known_at"), "state": "CANDIDATE", "pinned": False,
         "justification": str(prop["justification"])[:600], "confirmation": str(prop["confirmation"])[:300],
         "invalidation": str(prop["invalidation"])[:300], "valid_until": prop["valid_until"], "rules_version": VERSION}
    return True, None, z
