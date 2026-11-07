"""One-shot worker: python -m deep_runtime.worker <request.json> <response.json>

ops: health | train_seq | predict_seq | train_ppo | predict_ppo | nlp_predict. Inputs / outputs are files in the run directory given in
the request (npz arrays prepared by the bot with the shared feature code). Training never touches a broker connection; PPO acts only in
the replay environment. Every error is returned as {"ok": false, "error": ...} with exit code 0 so the caller reads a reason.
"""
from __future__ import annotations

import json
import sys
import time
import traceback


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


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    req = json.loads(open(argv[0], encoding="utf-8").read())
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
        elif op == "nlp_predict":
            from . import nlp
            res = nlp.predict(req)
        else:
            res = {"ok": False, "error": f"unknown op {op}"}
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500], "trace": traceback.format_exc()[-2000:]}
    res["elapsed_s"] = round(time.time() - t0, 3)
    with open(argv[1], "w", encoding="utf-8") as f:
        json.dump(res, f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
