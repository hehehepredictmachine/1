"""Model registry: list / activate / rollback / deactivate (atomic; only compatible REAL_USER_DATA models can be active)."""
from __future__ import annotations

import argparse
import sys
import time

from .common import activate, activatable, read_registry, write_registry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rejestr modeli prognoz XAUUSD (SHADOW).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("activate")
    a.add_argument("run_id")
    sub.add_parser("rollback", help="przywróć poprzedni aktywny model")
    sub.add_parser("deactivate", help="brak aktywnego modelu (monitor pokaże NO_MODEL)")
    args = ap.parse_args(argv)
    reg = read_registry()
    if args.cmd == "list":
        print(f"Aktywny: {reg.get('active') or 'brak'}")
        for rid, e in sorted(reg["runs"].items()):
            ok, why = activatable(e)
            print(f"  {rid}  {e.get('data_kind')}  {e.get('overall_status')}  horyzonty {e.get('horizon_status')}  "
                  f"{'może być aktywny' if ok else 'NIE: ' + str(why)}")
        return 0
    if args.cmd == "activate":
        activate(args.run_id, reason="ręcznie (registry_cli)")
        print(f"Aktywny model: {args.run_id}")
        return 0
    if args.cmd == "rollback":
        hist = reg.get("history") or []
        while hist:
            prev = hist.pop()
            if prev in reg["runs"] and activatable(reg["runs"][prev])[0]:
                cur = reg.get("active")
                reg["active"] = prev
                reg.setdefault("events", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": "ROLLBACK", "from": cur, "to": prev})
                write_registry(reg)
                print(f"Rollback: {cur} -> {prev}")
                return 0
        print("[BLAD] Brak wcześniejszego zgodnego modelu – użyj 'deactivate' (NO_MODEL).")
        return 2
    reg.setdefault("events", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": "DEACTIVATE", "from": reg.get("active")})
    if reg.get("active"):
        reg["history"].append(reg["active"])
    reg["active"] = None
    write_registry(reg)
    print("Brak aktywnego modelu (NO_MODEL).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
