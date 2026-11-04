"""TEST DOUBLE of kronos_runtime.worker (protocol only, NO model): close_i = last close + 0.1 * i. STUB_MODE: ok | timeout | load_fail | crash."""
import json
import os
import sys
import time

mode = os.environ.get("STUB_MODE", "ok")
for line in sys.stdin:
    req = json.loads(line)
    cmd = req.get("cmd")
    if cmd == "hello":
        r = {"ok": True, "runtime": "STUB (test)", "versions": {"torch": "none"}, "cuda": {"available": False}, "pid": os.getpid()}
    elif cmd == "load":
        if mode == "load_fail":
            r = {"ok": False, "code": "CHECKSUM", "error": "model.safetensors: SHA-256 inny niż w manifeście (test)"}
        else:
            r = {"ok": True, "info": {"device": "cpu", "device_note": "stub", "load_ms": 1.0, "components": [
                {"kind": "model", "repo": "NeoQuasar/Kronos-small", "revision": "901c26c1332695a2a8f243eb2f37243a37bea320"},
                {"kind": "tokenizer", "repo": "NeoQuasar/Kronos-Tokenizer-base", "revision": "0e0117387f39004a9016484a186a908917e22426"}]}}
    elif cmd == "predict":
        if mode == "timeout":
            time.sleep(60)
        if mode == "crash":
            sys.exit(3)
        last = req["candles"]["close"][-1]
        n = req["pred_len"]
        cl = [last + 0.1 * (i + 1) for i in range(n)]
        r = {"ok": True, "pred": {"t": req["y_t"], "open": [c - 0.05 for c in cl], "high": [c + 0.1 for c in cl], "low": [c - 0.1 for c in cl],
                                  "close": cl, "volume": None}, "ms": 1.0, "device": "cpu", "seed": req.get("seed"),
             "sampling": {"T": req.get("T"), "top_k": req.get("top_k"), "top_p": req.get("top_p"), "sample_count": 1},
             "context_bars": len(req["candles"]["close"]), "paths": None}
    elif cmd == "quit":
        print(json.dumps({"ok": True, "id": req.get("id")}), flush=True)
        break
    else:
        r = {"ok": False, "code": "UNKNOWN_COMMAND"}
    r["id"] = req.get("id")
    print(json.dumps(r), flush=True)
