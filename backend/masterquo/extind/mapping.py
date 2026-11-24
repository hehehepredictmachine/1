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
# 1.46: object types whose geometry (guaranteed by contract.validate) carries what decode() reads for each kind
KIND_TYPES: dict[str, tuple[str, ...]] = {"LEVEL": ("HLINE", "TREND"), "TRENDLINE": ("TREND",), "TIME_EVENT": ("VLINE",),
                                          "TIME_WINDOW": ("RECTANGLE", "TREND")}


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
        if not isinstance(u, dict):                            # 1.46: a JSON list / number broke status() (AttributeError -> 500)
            return dict(m, identity_status="MANIFEST_UNREADABLE")
        miss = [k for k in MANIFEST_REQUIRED if u.get(k) in (None, "", [])]
        if miss:
            return dict(m, identity_status="MANIFEST_INCOMPLETE", manifest_missing=miss, user_manifest=u)
        if u.get("platform") not in ("MT5",):
            return dict(m, identity_status="UNSUPPORTED_PLATFORM", user_manifest=u)
        if u.get("license_allows_export") is not True:        # 1.46: 'false' (licence forbids export) was accepted as identified
            return dict(m, identity_status="LICENSE_FORBIDS_EXPORT", user_manifest=u)
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
        # 1.46: a non-object rule was an AttributeError (HTTP 500)
        if not isinstance(r, dict) or not isinstance(r.get("prefix"), str) or not r["prefix"] or r.get("type") not in ("HLINE", "TREND", "VLINE", "RECTANGLE"):
            raise ValueError("MAPPING_RULE_INVALID")
        if r.get("kind") not in ("LEVEL", "TRENDLINE", "TIME_EVENT", "TIME_WINDOW"):
            raise ValueError("MAPPING_KIND_INVALID")
        if r["type"] not in KIND_TYPES[r["kind"]]:                    # 1.46: e.g. VLINE as TIME_WINDOW crashed decode() on every ingest
            raise ValueError(f"MAPPING_KIND_TYPE_MISMATCH:{r['kind']}/{r['type']}")
    try:
        ver = int(m.get("version") or 1)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("MAPPING_VERSION_INVALID") from None          # 1.46: version=[1] was a TypeError (HTTP 500)
    ex = m.get("verified_examples") or []
    if not isinstance(ex, list) or not all(isinstance(x, dict) and x for x in ex):
        raise ValueError("VERIFIED_EXAMPLES_INVALID")                   # 1.46: examples are objects (name + number read from the chart)
    out = {"adapter_id": adapter, "product_version": m.get("product_version"), "params_hash": m.get("params_hash"), "rules": m["rules"],
           "approved": bool(m.get("approved")), "approved_at": datetime.now(timezone.utc).isoformat() if m.get("approved") else None,
           "verified_examples": ex, "version": ver}
    if out["approved"] and not out["verified_examples"]:
        raise ValueError("APPROVAL_REQUIRES_VERIFIED_EXAMPLES")       # numbers compared with the chart by the user
    if out["approved"] and not out["product_version"]:
        # 1.46: an approval is bound to the product version; without it a new version could never invalidate it -> not effective
        out["approval_note"] = "PRODUCT_VERSION_REQUIRED: zatwierdzenie bez product_version nie jest aktywne (MAPPING_UNVERIFIED)"
    p = ext_root() / "mappings" / f"{adapter}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return out


def mapping_status(adapter: str, env: dict | None) -> tuple[str, dict | None]:
    m = mapping(adapter)
    if m is None:
        return "MAPPING_MISSING", None
    if not isinstance(m, dict):
        return "MAPPING_MISSING", None
    if m.get("approved") and not m.get("product_version"):
        return "MAPPING_UNVERIFIED", m              # 1.46: approval not bound to a product version is not an approval (see module doc)
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
    # 1.46: rules of a mapping file written before the kind/type check may be malformed - they are skipped, never an exception
    # that drops every later read of the adapter
    rules = [r for r in (m.get("rules") or []) if isinstance(r, dict) and isinstance(r.get("prefix"), str) and r["prefix"]]
    for o in env["objects"]:
        rule = next((r for r in rules if o["name"].startswith(r["prefix"]) and o["type"] == r.get("type")), None)
        if rule is None:
            continue
        kind, nt, npx = rule.get("kind"), len(o["times"]), len(o["prices"])
        if (kind in ("TRENDLINE", "TIME_WINDOW") and nt < 2) or (kind == "TIME_EVENT" and nt < 1) or (kind == "TRENDLINE" and npx < 2):
            continue                                          # 1.46: the geometry does not carry what this kind needs
        if kind == "LEVEL" and o["prices"] and o["prices"][0] is not None:
            levels.append({"level_id": f"{env['adapter_id']}:{o['name']}", "kind": "LEVEL", "role": rule.get("role", "UNSPECIFIED"),
                           "price": o["prices"][0], "source_name": o["name"]})
        elif kind == "TRENDLINE":
            t = [to_utc(x, env["time_basis"], offset_s) for x in o["times"][:2]]
            levels.append({"level_id": f"{env['adapter_id']}:{o['name']}", "kind": "TRENDLINE", "role": rule.get("role", "UNSPECIFIED"),
                           "points": [{"t_utc": t[0], "price": o["prices"][0]}, {"t_utc": t[1], "price": o["prices"][1]}], "source_name": o["name"]})
        elif kind == "TIME_EVENT":
            events.append({"event_id": f"{env['adapter_id']}:{o['name']}", "kind": rule.get("role", "TIME_EVENT"),
                           "scheduled_utc": to_utc(o["times"][0], env["time_basis"], offset_s), "source_time_raw": o["times"][0]})
        elif kind == "TIME_WINDOW":
            a, b = sorted(o["times"][:2])
            windows.append({"event_id": f"{env['adapter_id']}:{o['name']}", "kind": rule.get("role", "TIME_WINDOW"),
                            "scheduled_start_utc": to_utc(a, env["time_basis"], offset_s), "scheduled_end_utc": to_utc(b, env["time_basis"], offset_s),
                            "source_time_raw": [a, b]})
    time_ok = env["time_basis"] == "UTC" or offset_s is not None
    return {"levels": levels, "windows": windows, "events": events, "time_status": "OK" if time_ok else "TIME_BASIS_UNVERIFIED"}
