"""JSON-lines worker of TabICLv2 (python -m tabicl_runtime.worker inside .venv_tabicl). Commands: hello, ping, load, fit, predict,
selftest, quit. One reference context is kept in RAM (the newest); the bot re-sends it after a restart."""
from __future__ import annotations

import json
import os
import sys
import traceback

from . import RUNTIME_VERSION


def main(argv=None) -> int:
    proto = sys.stdout
    sys.stdout = sys.stderr
    os.environ["HF_HUB_OFFLINE"] = "1"
    from .engine import Engine, EngineError, rss_mb
    eng = Engine()
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
                resp = {"ok": True, "runtime": RUNTIME_VERSION, "pid": os.getpid()}
            elif cmd == "ping":
                resp = {"ok": True, "loaded": eng.loaded, "rss_mb": rss_mb(), "contexts": list(eng.contexts)}
            elif cmd == "load":
                resp = {"ok": True, "info": eng.load(req["weights_root"], threads=req.get("threads"), verify_files=bool(req.get("verify_files", True)))}
            elif cmd == "fit":
                resp = {"ok": True, **eng.fit(req["context_id"], req["X"], req["y"], req.get("names"))}
            elif cmd == "predict":
                resp = {"ok": True, **eng.predict(req["context_id"], req["X"])}
            elif cmd == "selftest":
                resp = {"ok": True, **eng.selftest()}
            elif cmd == "quit":
                proto.write(json.dumps({"ok": True, "id": req.get("id"), "bye": True}) + "\n")
                proto.flush()
                return 0
            else:
                resp = {"ok": False, "code": "UNKNOWN_COMMAND", "error": str(cmd)}
        except EngineError as exc:
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
