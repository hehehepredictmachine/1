"""TEST DOUBLE of tsfm_runtime.worker (protocol only, NO model): point_i = last close + STEP * i, quantiles +-0.5.
STUB_MODE: ok | down | timeout | load_fail | crash | oom.  Its numbers are not forecasts."""
import json
import os
import sys
import time

mode = os.environ.get("STUB_MODE", "ok")
model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "chronos2"
step = -0.2 if mode == "down" else 0.2
for line in sys.stdin:
    req = json.loads(line)
    cmd = req.get("cmd")
    if cmd == "hello":
        r = {"ok": True, "runtime": "STUB (test)", "model": model, "versions": {"torch": "none"}, "cuda": {"available": False}, "pid": os.getpid()}
    elif cmd == "ping":
        r = {"ok": True, "loaded": True}
    elif cmd == "load":
        if mode == "load_fail":
            r = {"ok": False, "code": "INCOMPATIBLE", "error": "inny wariant checkpointu (test)"}
        elif mode == "oom":
            r = {"ok": False, "code": "RESOURCE_LIMIT", "error": "za mało pamięci (test)"}
        else:
            r = {"ok": True, "info": {"model_id": model, "params": 123, "device": "cpu", "device_note": "stub", "load_ms": 1.0}}
    elif cmd == "predict":
        if mode == "timeout":
            time.sleep(60)
        if mode == "crash":
            sys.exit(3)
        last = req["close"][-1]
        n = req["pred_len"]
        pt = [last + step * (i + 1) for i in range(n)]
        qs = sorted(set(req.get("quantiles") or [0.1, 0.5, 0.9]) | {0.5})
        vals = {f"{q:g}": [p + (q - 0.5) for p in pt] for q in qs}
        if model == "granite_ttm":                                     # point forecast only (as the real Granite TTM engine)
            r = {"ok": True, "point": pt, "point_kind": "point", "median": None, "quantiles": None, "ms": 0.5, "device": "cpu",
                 "context_bars": len(req["close"]), "profile": req.get("profile"), "input_hash": "stub",
                 "normalization": {"method": "zscore_context_window", "mean": last, "std": 1.0}}
        else:
            r = {"ok": True, "point": pt, "point_kind": "median", "median": pt,
                 "quantiles": {"levels": qs, "values": vals, "crossing_steps": 0}, "ms": 1.5, "device": "cpu", "context_bars": len(req["close"]),
                 "profile": req.get("profile"), "input_hash": "stub"}
    elif cmd == "quit":
        print(json.dumps({"ok": True, "id": req.get("id")}), flush=True)
        break
    else:
        r = {"ok": False, "code": "UNKNOWN_COMMAND"}
    r["id"] = req.get("id")
    print(json.dumps(r), flush=True)
