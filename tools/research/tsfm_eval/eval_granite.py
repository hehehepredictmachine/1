"""Granite TTM (several revisions) + naive / drift baselines on the research data (research only).

  python eval_granite.py --data <folder z prep.py> --weights <folder z podfolderami rewizji TTM: main, 512-48-ft-r2.1, ...>
"""
import os
import resource
import sys
import time
from pathlib import Path

import numpy as np
import torch
from tsfm_public.models.tinytimemixer import TinyTimeMixerForPrediction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load, origins, parser, save, score

FREQ = {"M5": 3, "M15": 5, "H1": 7}
REVISIONS = ("main", "512-48-ft-r2.1", "512-96-ft-r2.1", "1024-96-r2")


def main(argv=None):
    a = parser(__doc__, "folder z podfolderami rewizji Granite TTM (main, 512-48-ft-r2.1, 512-96-ft-r2.1, 1024-96-r2)").parse_args(argv)
    torch.set_num_threads(4)
    root = Path(a.weights)
    out = []
    for tf, H in (("M5", 12), ("M15", 8), ("H1", 6)):
        t, _o, h, low, c = load(a.data, tf)
        orig = origins(t, H)
        for rev in REVISIONS:
            m = TinyTimeMixerForPrediction.from_pretrained(str(root / rev)).eval()
            ctx = m.config.context_length
            X = np.stack([np.array(c[i - ctx + 1:i + 1], dtype=np.float64) for i in orig])
            mu = X.mean(1, keepdims=True)
            sd = X.std(1, keepdims=True) + 1e-8
            Z = torch.tensor(((X - mu) / sd)[:, :, None], dtype=torch.float32)
            kw = {}
            if m.config.resolution_prefix_tuning:
                kw["freq_token"] = torch.full((len(orig),), FREQ[tf], dtype=torch.long)
            t0 = time.perf_counter()
            with torch.inference_mode():
                y = m(past_values=Z, **kw).prediction_outputs[:, :, 0].numpy()
            ms = (time.perf_counter() - t0) * 1000 / len(orig)
            P = y * sd + mu
            r = score("granite:" + rev, list(P[:, H - 1]), orig, h, low, c, H)
            r.update(tf=tf, H=H, ms_per_origin=round(ms, 2), params=sum(p.numel() for p in m.parameters()))
            out.append(r)
            print(r, flush=True)
        r = score("naive_last", [c[i] for i in orig], orig, h, low, c, H)
        r.update(tf=tf, H=H)
        out.append(r)
        print(r)
        r = score("drift_20", [c[i] + (c[i] - c[i - 20]) / 20 * H for i in orig], orig, h, low, c, H)
        r.update(tf=tf, H=H)
        out.append(r)
        print(r)
    print("maxrss_mb", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print("zapisano", save(out, a.out, "res_granite.json"))


if __name__ == "__main__":
    main()
