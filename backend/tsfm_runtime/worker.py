"""Inference process of Chronos-2 / Granite TTM (started by masterquo/tsfm/service.py with the model's own interpreter).

  python -m tsfm_runtime.worker --model chronos2|granite_ttm
Protocol: one JSON object per line on stdin -> one JSON object per line on stdout carrying the request "id".
  {"cmd": "hello"}  {"cmd": "load", "weights_root", "device", "threads", "verify_files"}  {"cmd": "predict", ...}  {"cmd": "selftest"}
  {"cmd": "ping"} (heartbeat)  {"cmd": "quit"}
Errors: {"ok": false, "code", "error"} - never a made-up forecast. Library output goes to stderr (log file), never into the protocol.
Requests are processed strictly one at a time (no interleaved random states); the process never touches MT5 or the network.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import RUNTIME_VERSION


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=["chronos2", "granite_ttm"])
    a = ap.parse_args(argv)
    proto = sys.stdout
    sys.stdout = sys.stderr
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from . import engines as E
    eng = E.make(a.model)
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
                resp = {"ok": True, "runtime": RUNTIME_VERSION, "model": a.model, "versions": E.versions(), "cuda": E.cuda_info(), "pid": os.getpid()}
            elif cmd == "ping":
                resp = {"ok": True, "loaded": eng.loaded, "rss_mb": E.rss_mb()}
            elif cmd == "load":
                kw = {"checkpoint": req.get("checkpoint"), "finetune_dir": req.get("finetune_dir")} if a.model == "granite_ttm" else {}
                resp = {"ok": True, "info": eng.load(req["weights_root"], device=req.get("device", "AUTO"), threads=req.get("threads"),
                                                     verify_files=bool(req.get("verify_files", True)), **kw)}
            elif cmd == "predict":
                resp = {"ok": True, **eng.predict(req)}
            elif cmd == "selftest":
                resp = {"ok": True, **eng.selftest()}
            elif cmd == "quit":
                proto.write(json.dumps({"ok": True, "id": req.get("id"), "bye": True}) + "\n")
                proto.flush()
                return 0
            else:
                resp = {"ok": False, "code": "UNKNOWN_COMMAND", "error": str(cmd)}
        except E.EngineError as exc:
            resp = {"ok": False, "code": exc.code, "error": exc.detail}
        except MemoryError as exc:
            resp = {"ok": False, "code": "RESOURCE_LIMIT", "error": f"MemoryError: {exc}"[:300]}
        except Exception as exc:  # noqa: BLE001
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
