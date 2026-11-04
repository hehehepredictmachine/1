"""Kronos inference process (started by masterquo/kronos/service.py with the .venv_kronos interpreter).

Protocol: one JSON object per line on stdin -> one JSON object per line on stdout (the response carries the request "id").
  {"cmd": "hello"}                          -> runtime, library versions, CUDA availability, pid
  {"cmd": "load", "weights_dir", "device", "max_context", "threads", "verify_files"} -> device actually used, load time, versions of the pair
  {"cmd": "predict", "candles": {t, open, high, low, close, volume|null}, "y_t", "pred_len", "T", "top_k", "top_p", "seed", "paths"}
  {"cmd": "selftest", "reference": bool}
  {"cmd": "quit"}
Errors: {"ok": false, "code": ..., "error": ...} - never a made-up forecast. Library output (progress bars, warnings) goes to stderr so
it cannot corrupt the protocol. The process never touches MetaTrader 5, the network after installation, or any account data.
"""
from __future__ import annotations

import json
import os
import sys
import traceback

from . import RUNTIME_VERSION


def main() -> int:
    proto = sys.stdout
    sys.stdout = sys.stderr                                   # stray prints of libraries never reach the protocol stream
    os.environ["HF_HUB_OFFLINE"] = "1"                        # inference uses local, verified files only
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from . import engine as E
    eng = E.Engine()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError as exc:
            proto.write(json.dumps({"ok": False, "code": "BAD_REQUEST", "error": str(exc)[:200]}) + "\n")
            proto.flush()
            continue
        cmd = req.get("cmd")
        try:
            if cmd == "hello":
                resp = {"ok": True, "runtime": RUNTIME_VERSION, "versions": E.versions(), "cuda": E.cuda_info(), "pid": os.getpid()}
            elif cmd == "load":
                info = eng.load(req["weights_dir"], device=req.get("device", "AUTO"), max_context=int(req.get("max_context", 512)),
                                threads=req.get("threads"), verify_files=bool(req.get("verify_files", True)))
                resp = {"ok": True, "info": info}
            elif cmd == "predict":
                resp = {"ok": True, **eng.predict(req)}
            elif cmd == "selftest":
                resp = {"ok": True, **eng.selftest(reference=bool(req.get("reference")))}
            elif cmd == "quit":
                proto.write(json.dumps({"ok": True, "id": req.get("id"), "bye": True}) + "\n")
                proto.flush()
                return 0
            else:
                resp = {"ok": False, "code": "UNKNOWN_COMMAND", "error": str(cmd)}
        except E.EngineError as exc:
            resp = {"ok": False, "code": exc.code, "error": exc.detail}
        except Exception as exc:  # noqa: BLE001 - reported to the bot, never a silent default
            traceback.print_exc(file=sys.stderr)
            resp = {"ok": False, "code": "EXCEPTION", "error": f"{type(exc).__name__}: {exc}"[:400]}
        resp["id"] = req.get("id")
        try:
            proto.write(json.dumps(resp, allow_nan=False) + "\n")
        except ValueError:
            proto.write(json.dumps({"ok": False, "id": req.get("id"), "code": "NON_FINITE", "error": "wynik zawiera NaN/Inf"}) + "\n")
        proto.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
