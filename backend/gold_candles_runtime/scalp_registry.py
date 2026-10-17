"""Scalp model registry (data/scalp/registry.json): list / activate / rollback / deactivate / validate - atomic writes;
only compatible REAL_USER_DATA runs with verified checksums can be active (SHADOW forecasts only)."""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from . import scalp_features as SF
from .common import use_instrument, write_json_atomic
from .scalp_infer import ScalpModel, activatable, read_registry, registry_path


def _ev(reg, **kw):
    reg.setdefault("events", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rejestr modeli scalp (SHADOW) – osobny dla każdego instrumentu (--instrument / MQ_INSTRUMENT).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.add_argument("--instrument", help="XAUUSD (domyślnie) albo BTC – osobny rejestr każdego instrumentu")
    sub.add_parser("list")
    a = sub.add_parser("activate")
    a.add_argument("run_id")
    sub.add_parser("rollback")
    sub.add_parser("deactivate")
    sub.add_parser("validate", help="checksumy, kontrakt cech i odczyt przez ścieżkę workera")
    args = ap.parse_args(argv)
    use_instrument(args.instrument)
    reg = read_registry()
    contract = lambda e: SF.contract_hash(e["symbol"], e["tick_size"])  # noqa: E731
    if args.cmd == "list":
        print(f"Aktywny: {reg.get('active') or 'brak'}")
        for rid, e in sorted(reg["runs"].items()):
            ok, why = activatable(e, contract(e))
            print(f"  {rid}  {e.get('data_kind')}  A={e.get('task_a_status')} {e.get('horizon_status')}  B={e.get('task_b_status')}  "
                  f"C={e.get('task_c_status')}  {'może być aktywny' if ok else 'NIE: ' + str(why)}")
        return 0
    if args.cmd == "validate":
        rc = 0
        for rid, e in sorted(reg["runs"].items()):
            ok, why = activatable(e, contract(e))
            line = f"{rid}: {'OK' if ok else why}"
            try:
                m = ScalpModel(e)
                p = m.predict(np.zeros((1, len(SF.FEATURES))))
                line += f", odczyt OK ({', '.join(f'h{k}' for k in p)})"
            except Exception as exc:
                line += f", odczyt BŁĄD {type(exc).__name__}: {exc}"
                rc = 1
            print(line)
        return rc
    if args.cmd == "activate":
        e = reg["runs"].get(args.run_id)
        if not e:
            print(f"[BLAD] nieznany run_id {args.run_id}")
            return 2
        ok, why = activatable(e, contract(e))
        if not ok:
            print(f"[BLAD] {args.run_id} nie może być aktywny: {why}")
            return 2
        if reg.get("active") and reg["active"] != args.run_id:
            reg.setdefault("history", []).append(reg["active"])
        reg["active"] = args.run_id
        _ev(reg, action="ACTIVATE", run_id=args.run_id)
        write_json_atomic(registry_path(), reg)
        print(f"Aktywny model scalp: {args.run_id}")
        return 0
    if args.cmd == "rollback":
        hist = reg.get("history") or []
        while hist:
            prev = hist.pop()
            if prev in reg["runs"] and activatable(reg["runs"][prev], contract(reg["runs"][prev]))[0]:
                _ev(reg, action="ROLLBACK", **{"from": reg.get("active"), "to": prev})
                reg["active"] = prev
                write_json_atomic(registry_path(), reg)
                print(f"Rollback -> {prev}")
                return 0
        print("[BLAD] brak wcześniejszego zgodnego modelu – użyj 'deactivate' (NO_MODEL).")
        return 2
    _ev(reg, action="DEACTIVATE", **{"from": reg.get("active")})
    if reg.get("active"):
        reg.setdefault("history", []).append(reg["active"])
    reg["active"] = None
    write_json_atomic(registry_path(), reg)
    print("Brak aktywnego modelu scalp (NO_MODEL).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
