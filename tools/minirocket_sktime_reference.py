"""Generate MiniRocket parity fixtures from the PINNED sktime reference (PMW-UPD-09 T117).

Runs in a SEPARATE interpreter that has sktime installed (tests/fixtures provenance records versions); the project never imports sktime.
Usage: <python-with-sktime> tools/minirocket_sktime_reference.py OUT_DIR [--seed 7] [--n 40] [--L 128]
Writes OUT_DIR/sktime_fixture.npz (X, dilations, counts, biases, features) + provenance.json. The windows X are a deterministic
random walk (test input only). sktime picks its Fit windows internally with numba RNG; parity is therefore checked on the FROZEN state
(dilations/counts/biases taken from sktime) and on the layout - random Fit-window selection is NOT claimed to be reproduced.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np


def main(argv):
    out = Path(argv[0])
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 7
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 40
    L = int(argv[argv.index("--L") + 1]) if "--L" in argv else 128
    import numba
    import sktime
    from sktime.transformations.rocket import MiniRocket
    rng = np.random.default_rng(seed)
    X = np.cumsum(rng.normal(0, 1, (n, L)), axis=1).astype(np.float32)
    X[0] = 0.0                                                            # include a flat window (ties at bias == 0)
    X[1] = np.sin(np.arange(L) / 5.0).astype(np.float32)
    m = MiniRocket(num_kernels=10000, max_dilations_per_kernel=32, random_state=seed)
    m.fit(X[:, None, :])
    d, c, b = m.parameters
    feats = m.transform(X[:, None, :])
    feats = np.asarray(feats, dtype=np.float32)
    m1 = MiniRocket(num_kernels=10000, max_dilations_per_kernel=32, random_state=seed)
    m1.fit(X[2:3, None, :])                                               # ONE training window: no random selection left
    biases_single = np.asarray(m1.parameters[2], dtype=np.float32)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "sktime_fixture.npz", X=X, dilations=np.asarray(d), counts=np.asarray(c), biases=np.asarray(b, dtype=np.float32), features=feats,
                        biases_single_window2=biases_single)
    (out / "provenance.json").write_text(json.dumps({
        "reference": "sktime.transformations.rocket.MiniRocket", "sktime": sktime.__version__, "numba": numba.__version__, "numpy": np.__version__,
        "python": sys.version.split()[0], "seed": seed, "n": n, "L": L, "num_kernels": 10000, "max_dilations_per_kernel": 32,
        "input": "float32 random walk + flat + sinusoid (test-only input)", "license_note": "sktime BSD-3 used as an external test tool only; not distributed",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "features": list(feats.shape)}))


if __name__ == "__main__":
    main(sys.argv[1:])
