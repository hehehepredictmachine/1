"""Worker of the .venv_deep runtime.

One-shot:   python -m deep_runtime.worker <request.json> <response.json>      (training, health - a process per request)
Persistent: python -m deep_runtime.worker --serve                              (1.46, I0215: live predictions)
            one JSON request per line on stdin -> one JSON answer per line on stdout carrying the request "id"; {"op": "quit"} ends it,
            and so does a closed stdin (the bot ended). Only SERVE_OPS are accepted; library output goes to stderr so it cannot corrupt
            the protocol. A loaded SEQ network stays in memory (deep_runtime.seq cache keyed by the files' mtime / size).

ops: health | train_seq | predict_seq | train_ppo | predict_ppo | nlp_predict (experimental, NOT CONNECTED - no caller in the bot in
1.46). Inputs / outputs are files in the run directory given in
the request (npz arrays prepared by the bot with the shared feature code). Training never touches a broker connection; PPO acts only in
the replay environment. Every error is returned as {"ok": false, "error": ...} with exit code 0 so the caller reads a reason.
"""
from __future__ import annotations

import json
import sys
import time
import traceback

SERVE_OPS = ("health", "predict_seq", "predict_ppo")


def health(req):
    out = {"python": sys.version.split()[0]}
    for m in ("torch", "gymnasium", "stable_baselines3", "numpy", "transformers"):
        try:
            mod = __import__(m)
            out[m] = getattr(mod, "__version__", "?")
        except Exception:  # noqa: BLE001
            out[m] = None
    try:
        import torch
        out["cuda"] = bool(torch.cuda.is_available())
        out["threads"] = torch.get_num_threads()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **out}


def dispatch(req: dict) -> dict:
    """One request -> its answer (with elapsed_s); never raises."""
    t0 = time.time()
    try:
        op = req["op"]
        if op == "health":
            res = health(req)
        elif op in ("train_seq", "predict_seq"):
            from . import seq
            res = seq.train(req) if op == "train_seq" else seq.predict(req)
        elif op in ("train_ppo", "predict_ppo"):
            from . import rl
            res = rl.train(req) if op == "train_ppo" else rl.predict(req)
        elif op == "nlp_predict":                         # experimental - no caller in the bot (1.46, I0223 / I0471)
            from . import nlp
            res = nlp.predict(req)
        else:
            res = {"ok": False, "error": f"unknown op {op}"}
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500], "trace": traceback.format_exc()[-2000:]}
    res["elapsed_s"] = round(time.time() - t0, 3)
    return res


def serve() -> int:
    proto = sys.stdout
    sys.stdout = sys.stderr                                   # stray prints of libraries never reach the protocol stream
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError as exc:
            proto.write(json.dumps({"ok": False, "error": f"BAD_REQUEST: {exc}"[:200]}) + "\n")
            proto.flush()
            continue
        if req.get("op") == "quit":
            proto.write(json.dumps({"ok": True, "id": req.get("id"), "bye": True}) + "\n")
            proto.flush()
            return 0
        if req.get("op") in SERVE_OPS:
            res = dispatch(req)
        else:
            res = {"ok": False, "error": f"op {req.get('op')} not served by the persistent worker (one-shot only)"}
        res["id"] = req.get("id")
        proto.write(json.dumps(res) + "\n")
        proto.flush()
    return 0


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if argv[:1] == ["--serve"]:
        return serve()
    req = json.loads(open(argv[0], encoding="utf-8").read())
    res = dispatch(req)
    with open(argv[1], "w", encoding="utf-8") as f:
        json.dump(res, f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
