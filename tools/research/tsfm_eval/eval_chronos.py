"""Chronos-2 (amazon/chronos-2, median of the quantile forecast) on the research data (research only).

  python eval_chronos.py --data <folder z prep.py> --weights <folder modelu Chronos-2 (amazon__chronos-2@<rewizja>)>
"""
import os
import resource
import sys
import time

import torch
from chronos import Chronos2Pipeline

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load, origins, parser, save, score


def main(argv=None):
    a = parser(__doc__, "folder modelu Chronos-2 (np. <wagi TSFM>/chronos2/amazon__chronos-2@<rewizja>)").parse_args(argv)
    torch.set_num_threads(4)
    p = Chronos2Pipeline.from_pretrained(a.weights, device_map="cpu", dtype=torch.float32)
    out = []
    for tf, H in (("M5", 12), ("M15", 8), ("H1", 6)):
        t, _o, h, low, c = load(a.data, tf)
        orig = origins(t, H)
        preds = []
        t0 = time.perf_counter()
        for k in range(0, len(orig), 64):
            batch = [torch.tensor(c[i - 511:i + 1], dtype=torch.float32) for i in orig[k:k + 64]]
            with torch.inference_mode():
                q, _m = p.predict_quantiles(batch, prediction_length=H, quantile_levels=[0.5])
            preds += [float(x[0][H - 1, 0]) for x in q]
        ms = (time.perf_counter() - t0) * 1000 / len(orig)
        r = score("chronos2", preds, orig, h, low, c, H)
        r.update(tf=tf, H=H, ms_per_origin=round(ms, 2))
        out.append(r)
        print(r, flush=True)
    print("maxrss_mb", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print("zapisano", save(out, a.out, "res_chronos.json"))


if __name__ == "__main__":
    main()
