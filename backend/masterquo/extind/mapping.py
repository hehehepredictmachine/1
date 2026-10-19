"""Source manifests + mapping profiles -> typed levels / windows. A mapping is an explicit allow-list of object name
prefixes and types bound to the product version; it is UNVERIFIED until the user approves it after comparing numbers with
the chart (never inferred from colours). A new product version invalidates the approval."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import paths

MANIFEST_REQUIRED = ("title", "vendor", "product_id", "platform", "url", "interface", "kinds", "outputs", "license_allows_export",
                     "repaint_behaviour", "version", "file_sha256")
TRUSTED_DECODERS: dict[str, str] = {"IQ_GOLD_GANN": "objects_v1", "IQ_STAR_LINES": "objects_v1"}   # PAL02M: none until identified


def base_manifests() -> dict:
    return json.loads((paths.ROOT_DIR / "config" / "extind_manifests_v1.json").read_text(encoding="utf-8"))["sources"]


def ext_root() -> Path:
    d = paths.data_dir() / "extind"
    for s in ("inbox", "mappings", "manifests"):
        (d / s).mkdir(parents=True, exist_ok=True)
    return d


def manifest(adapter: str) -> dict:
    """Base manifest; for PAL02M a user manifest is required and validated (data only, never executed)."""
    m = dict(base_manifests().get(adapter) or {})
    user = ext_root() / "manifests" / f"{adapter}.json"
    if user.exists():
        try:
            u = json.loads(user.read_text(encoding="utf-8"))
        except ValueError:
            return dict(m, identity_status="MANIFEST_UNREADABLE")
        miss = [k for k in MANIFEST_REQUIRED if u.get(k) in (None, "", [])]
        if miss:
            return dict(m, identity_status="MANIFEST_INCOMPLETE", manifest_missing=miss, user_manifest=u)
        if u.get("platform") not in ("MT5",):
            return dict(m, identity_status="UNSUPPORTED_PLATFORM", user_manifest=u)
        m.update({k: u[k] for k in MANIFEST_REQUIRED}, identity_confirmed=True, user_manifest=True)
    if not m.get("identity_confirmed"):
        return dict(m, identity_status="BLOCKED_IDENTITY_REQUIRED")
    if adapter not in TRUSTED_DECODERS:
        return dict(m, identity_status="DECODER_NOT_IMPLEMENTED")
    return dict(m, identity_status="IDENTIFIED", decoder=TRUSTED_DECODERS[adapter])


def mapping(adapter: str) -> dict | None:
    p = ext_root() / "mappings" / f"{adapter}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_mapping(adapter: str, m: dict) -> dict:
    if not isinstance(m.get("rules"), list) or not m["rules"]:
        raise ValueError("MAPPING_RULES_REQUIRED")
    for r in m["rules"]:
        if not isinstance(r.get("prefix"), str) or not r["prefix"] or r.get("type") not in ("HLINE", "TREND", "VLINE", "RECTANGLE"):
            raise ValueError("MAPPING_RULE_INVALID")
        if r.get("kind") not in ("LEVEL", "TRENDLINE", "TIME_EVENT", "TIME_WINDOW"):
            raise ValueError("MAPPING_KIND_INVALID")
    out = {"adapter_id": adapter, "product_version": m.get("product_version"), "params_hash": m.get("params_hash"), "rules": m["rules"],
           "approved": bool(m.get("approved")), "approved_at": datetime.now(timezone.utc).isoformat() if m.get("approved") else None,
           "verified_examples": m.get("verified_examples") or [], "version": int(m.get("version") or 1)}
    if out["approved"] and not out["verified_examples"]:
        raise ValueError("APPROVAL_REQUIRES_VERIFIED_EXAMPLES")       # numbers compared with the chart by the user
    p = ext_root() / "mappings" / f"{adapter}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return out


def mapping_status(adapter: str, env: dict | None) -> tuple[str, dict | None]:
    m = mapping(adapter)
    if m is None:
        return "MAPPING_MISSING", None
    if env is not None and m.get("product_version") and (env.get("product") or {}).get("version") != m["product_version"]:
        return "MAPPING_VERSION_CHANGED", m
    return ("MAPPING_APPROVED" if m.get("approved") else "MAPPING_UNVERIFIED"), m


def to_utc(t_server: int, basis: str, offset_s: float | None) -> int | None:
    if basis == "UTC":
        return int(t_server)
    return None if offset_s is None else int(t_server - offset_s)


def decode(env: dict, m: dict, offset_s: float | None) -> dict:
    """Objects -> typed levels / windows by the approved rules only. Unmatched objects are ignored (never re-labelled)."""
    levels, windows, events = [], [], []
    for o in env["objects"]:
        rule = next((r for r in m["rules"] if o["name"].startswith(r["prefix"]) and o["type"] == r["type"]), None)
        if rule is None:
            continue
        if rule["kind"] == "LEVEL" and o["prices"] and o["prices"][0] is not None:
            levels.append({"level_id": f"{env['adapter_id']}:{o['name']}", "kind": "LEVEL", "role": rule.get("role", "UNSPECIFIED"),
                           "price": o["prices"][0], "source_name": o["name"]})
        elif rule["kind"] == "TRENDLINE":
            t = [to_utc(x, env["time_basis"], offset_s) for x in o["times"][:2]]
            levels.append({"level_id": f"{env['adapter_id']}:{o['name']}", "kind": "TRENDLINE", "role": rule.get("role", "UNSPECIFIED"),
                           "points": [{"t_utc": t[0], "price": o["prices"][0]}, {"t_utc": t[1], "price": o["prices"][1]}], "source_name": o["name"]})
        elif rule["kind"] == "TIME_EVENT":
            events.append({"event_id": f"{env['adapter_id']}:{o['name']}", "kind": rule.get("role", "TIME_EVENT"),
                           "scheduled_utc": to_utc(o["times"][0], env["time_basis"], offset_s), "source_time_raw": o["times"][0]})
        elif rule["kind"] == "TIME_WINDOW":
            a, b = sorted(o["times"][:2])
            windows.append({"event_id": f"{env['adapter_id']}:{o['name']}", "kind": rule.get("role", "TIME_WINDOW"),
                            "scheduled_start_utc": to_utc(a, env["time_basis"], offset_s), "scheduled_end_utc": to_utc(b, env["time_basis"], offset_s),
                            "source_time_raw": [a, b]})
    time_ok = env["time_basis"] == "UTC" or offset_s is not None
    return {"levels": levels, "windows": windows, "events": events, "time_status": "OK" if time_ok else "TIME_BASIS_UNVERIFIED"}
