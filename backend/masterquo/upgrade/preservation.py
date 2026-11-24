"""Preservation report of the 1.41 update (reports/strategy_preservation.json): every ORIGINAL strategy id of the before-inventory is
looked up in the after-inventory and compared field by field. The lists are COMPUTED, never pre-filled:
  missing_strategy_ids        before ids absent after
  unexpected_config_changes   parameter hash / enabled-use state differences that no migration step declared
  duplicate_execution_routes  two registries able to send an order intent for the same event (legacy + new catalog alias)
  orphaned_history_keys       history keys of a before entry whose owner disappeared
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "PMW-PRESERVATION-1"


def _key(x: dict) -> str:
    return f"{x.get('source')}|{x.get('strategy_id')}|{x.get('instrument') or ''}"


def compare(before: list[dict], after: list[dict], *, declared_changes: dict | None = None, new_catalog: list[dict] | None = None) -> dict:
    declared = declared_changes or {}
    b = {_key(x): x for x in before if "error" not in x}
    a = {_key(x): x for x in after if "error" not in x}
    rows, missing, changes, orphaned = [], [], [], []
    for k, x in b.items():
        y = a.get(k)
        if y is None:
            missing.append(x["strategy_id"])
            orphaned += list(x.get("history_keys") or [])
            rows.append({"strategy_id": x["strategy_id"], "source": x.get("source"), "after": None, "status": "MISSING"})
            continue
        diffs = []
        if x.get("parameters_hash") != y.get("parameters_hash"):
            diffs.append("parameters")
        if x.get("enabled") != y.get("enabled"):
            diffs.append("enabled/use")
        if x.get("symbols") != y.get("symbols"):
            diffs.append("symbols")
        if x.get("execution_route") != y.get("execution_route"):
            diffs.append("execution_route")
        undeclared = [d for d in diffs if d not in (declared.get(x["strategy_id"]) or [])]
        if undeclared:
            changes.append({"strategy_id": x["strategy_id"], "source": x.get("source"), "fields": undeclared})
        alias = next((c["strategy_id"] for c in (new_catalog or []) if x["strategy_id"] in (c.get("legacy_aliases") or [])), None)
        rows.append({"strategy_id": x["strategy_id"], "source": x.get("source"), "after": {"strategy_id": y["strategy_id"], "source": y.get("source")},
                     "canonical_alias": alias, "parameters_equal": "parameters" not in diffs, "status_equal": "enabled/use" not in diffs,
                     "history_keys_equal": x.get("history_keys") == y.get("history_keys"), "adaptation": declared.get(x["strategy_id"]) or "brak – bez zmian",
                     "status": "PRESERVED" if not undeclared else "CHANGED"})
    dup = []
    for c in new_catalog or []:
        for al in c.get("legacy_aliases") or []:
            if c.get("execution_route") not in (None, "SIGNALS_ONLY", "ALIAS_OF_LEGACY"):
                dup.append({"canonical": c["strategy_id"], "legacy": al, "route": c.get("execution_route")})
    return {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "before_count": len(b), "after_count": len(a),
            "strategies": rows, "missing_strategy_ids": missing, "unexpected_config_changes": changes, "duplicate_execution_routes": dup,
            "orphaned_history_keys": orphaned, "result": "PASS" if not (missing or changes or dup or orphaned) else "ATTENTION"}


def write(report_dir: Path, *, declared_changes: dict | None = None, new_catalog: list[dict] | None = None) -> dict:
    before = json.loads((report_dir / "strategy_inventory_before.json").read_text(encoding="utf-8"))["items"]
    after = json.loads((report_dir / "strategy_inventory_after.json").read_text(encoding="utf-8"))["items"]
    rep = compare(before, after, declared_changes=declared_changes, new_catalog=new_catalog)
    (report_dir / "strategy_preservation.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return rep
