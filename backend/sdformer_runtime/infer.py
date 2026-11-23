"""SDformerFlow inference (one shot, closed bars): python -m sdformer_runtime.infer --checkpoint DIR --bars FILE [--threads 2]
Loads last.pt (strict shapes - an incompatible checkpoint is refused, never partially loaded), normalises with the STORED normaliser,
returns for the newest closed bar: the STFS forecast of the next 24 descriptors (de-normalised), DIRECTION_SCORE_RAW =
tanh(sum of the forecast close-open over the next 6 bars / ATR14) - a raw score, not a probability - and an 8-number summary of the
encoder representation (channel-group means of the last bar) for Quant features. RESULT {json} on the last line."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from . import IMPLEMENTATION_ID


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sdformer_runtime.infer")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--bars", required=True)
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    import numpy as np
    import torch
    from . import data as D
    from .model import SDformerFlow
    torch.set_num_threads(a.threads)
    ck = torch.load(Path(a.checkpoint) / "last.pt", map_location="cpu", weights_only=True)   # 1.46: no pickle code execution (imported ZIP)
    m = SDformerFlow()
    if ck.get("implementation_id") != IMPLEMENTATION_ID or ck.get("arch") != m.arch:
        print("RESULT " + json.dumps({"ok": False, "code": "INCOMPATIBLE", "error": "checkpoint innej implementacji / architektury"}))
        return 1
    m.load_state_dict(ck["model"], strict=True)
    m.eval()
    bars = json.loads(Path(a.bars).read_text(encoding="utf-8"))
    X, _, T, idx = D.samples(bars, with_target=False)
    if not len(X):
        print("RESULT " + json.dumps({"ok": False, "code": "WARMING_UP", "error": f"za mało zamkniętych świec (potrzeba {D.HISTORY} + rozgrzewka wskaźników)"}))
        return 1
    mu, sd = np.asarray(ck["normalizer"]["mu"], np.float32), np.asarray(ck["normalizer"]["sd"], np.float32)
    x = torch.tensor((X[-1:] - mu) / sd)
    with torch.no_grad():
        y, r = m(x, torch.tensor(D.time_features(T[-1:])))
    fc = y[0].numpy() * sd + mu                                            # de-normalised [24, 9]
    if not np.isfinite(fc).all():
        print("RESULT " + json.dumps({"ok": False, "code": "NON_FINITE", "error": "prognoza NaN/Inf"}))
        return 1
    atr = float(X[-1][-1][6])
    body6 = float(fc[:6, 0].sum())
    score = math.tanh(body6 / atr) if atr > 0 else None
    rep = r[0, :, -1].numpy()
    emb = [float(g.mean()) for g in np.array_split(rep, 8)]
    print("RESULT " + json.dumps({"ok": True, "implementation_id": IMPLEMENTATION_ID, "run_id": ck.get("run_id"), "bar_t": float(bars[idx[-1]]["t"]),
                                  "direction_score_raw": score, "forecast_body_6": body6, "atr14": atr, "embedding8": emb,
                                  "forecast_close_open": [float(v) for v in fc[:, 0]], "ms": round((time.perf_counter() - t0) * 1000, 1),
                                  "note": "DIRECTION_SCORE_RAW z prognozy STFS (nie prawdopodobieństwo, nieskalibrowane)"}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
