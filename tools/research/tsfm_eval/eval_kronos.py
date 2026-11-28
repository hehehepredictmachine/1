"""Kronos (kronos_runtime.Engine, the bot's own adapter) on the research data vs the last price (research only).

  python eval_kronos.py --data <folder z prep.py> --weights <folder wag Kronos (kronos_manifest.json)>
"""
import os
import resource
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BACKEND, load, origins, parser, save, score

sys.path.insert(0, str(BACKEND))
from kronos_runtime import engine as E
from kronos_runtime import lock

N = {"M5": 60, "M15": 40, "H1": 40}


def main(argv=None):
    a = parser(__doc__, "folder wag Kronos (kronos_manifest.json, przypięta para lock.py)").parse_args(argv)
    eng = E.Engine()
    info = eng.load(a.weights, device="CPU", threads=4)
    print("kronos loaded", info.get("params_model"), info.get("load_ms"))
    out = []
    for tf, H, dt in (("M5", 12, 5), ("M15", 8, 15), ("H1", 6, 60)):
        t, o, h, low, c = load(a.data, tf)
        orig = origins(t, H, step=max(H, (len([x for x in t if x >= "2025-10-01"]) // N[tf]) or H))[:N[tf]]
        preds = []
        t0 = time.perf_counter()
        for i in orig:
            s = i - 511
            cand = {"open": o[s:i + 1], "high": h[s:i + 1], "low": low[s:i + 1], "close": c[s:i + 1], "t": t[s:i + 1]}
            last = datetime.fromisoformat(t[i])
            yt = [(last + timedelta(minutes=dt * (k + 1))).isoformat() for k in range(H)]
            r = eng.predict({"candles": cand, "pred_len": H, "y_t": yt, "T": 1.0, "top_p": 0.9, "seed": 7})
            preds.append(float(r["pred"]["close"][-1]))
        ms = (time.perf_counter() - t0) * 1000 / len(orig)
        r = score(f"kronos:{lock.MODEL_NAME}", preds, orig, h, low, c, H)
        r.update(tf=tf, H=H, ms_per_origin=round(ms, 1))
        out.append(r)
        print(r, flush=True)
        rn = score("naive_last(same origins)", [c[i] for i in orig], orig, h, low, c, H)
        rn.update(tf=tf, H=H)
        out.append(rn)
        print(rn, flush=True)
    print("maxrss_mb", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print("zapisano", save(out, a.out, "res_kronos.json"))


if __name__ == "__main__":
    main()
