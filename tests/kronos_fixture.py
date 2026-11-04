"""TEST FIXTURE for the Kronos runtime tests - NOT the Kronos model.

Builds a weights directory in the official layout (pinned repo/revision folder names, config.json + model.safetensors, manifest) with
RANDOMLY INITIALISED weights of the upstream classes, so the real code path (load from local files, checksum check, compatibility check,
KronosPredictor, worker protocol, timing) can be exercised without internet. The manifest carries "fixture": true; outside the test suite
(MQ_KRONOS_ALLOW_FIXTURE != 1) it is rejected as "not an installed model". Forecasts from it are numbers from random weights - they say
nothing about the market and are never shown as forecasts.

Architecture sizes: the published sizes of Kronos-small / Kronos-Tokenizer-base are not reachable from this environment, so the default
here is a configuration of similar scale (about 24-25 M parameters) used for timing only; `small=True` gives a tiny model for fast tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

TOK_SMALL = dict(d_in=6, d_model=32, n_heads=2, ff_dim=64, n_enc_layers=2, n_dec_layers=2, ffn_dropout_p=0.0, attn_dropout_p=0.0,
                 resid_dropout_p=0.0, s1_bits=4, s2_bits=4, beta=0.05, gamma0=1.0, gamma=1.1, zeta=0.05, group_size=4)
MODEL_SMALL = dict(s1_bits=4, s2_bits=4, n_layers=2, d_model=32, n_heads=2, ff_dim=64, ffn_dropout_p=0.0, attn_dropout_p=0.0,
                   resid_dropout_p=0.0, token_dropout_p=0.0, learn_te=True)
TOK_SCALE = dict(d_in=6, d_model=256, n_heads=4, ff_dim=512, n_enc_layers=4, n_dec_layers=4, ffn_dropout_p=0.0, attn_dropout_p=0.0,
                 resid_dropout_p=0.0, s1_bits=10, s2_bits=10, beta=0.05, gamma0=1.0, gamma=1.1, zeta=0.05, group_size=5)
MODEL_SCALE = dict(s1_bits=10, s2_bits=10, n_layers=8, d_model=512, n_heads=8, ff_dim=1024, ffn_dropout_p=0.0, attn_dropout_p=0.0,
                   resid_dropout_p=0.0, token_dropout_p=0.0, learn_te=True)


def build(dest: Path, small: bool = True, model_override: dict | None = None, seed: int = 0) -> dict:
    import torch
    from kronos_runtime import lock
    from kronos_runtime import manifest as M
    from kronos_runtime.vendor.kronos import Kronos, KronosTokenizer
    torch.manual_seed(seed)
    tok = KronosTokenizer(**(TOK_SMALL if small else TOK_SCALE))
    model = Kronos(**{**(MODEL_SMALL if small else MODEL_SCALE), **(model_override or {})})
    comps = []
    for c, obj in ((lock.MODEL, model), (lock.TOKENIZER, tok)):
        d = Path(dest) / lock.component_dir_name(c)
        obj.save_pretrained(str(d))
        files = []
        for name in ("config.json", "model.safetensors"):
            p = d / name
            files.append({"name": name, "size": p.stat().st_size, "sha256": M.sha256_file(p), "source_check": "fixture", "source_value": None})
        comps.append({"kind": c["kind"], "repo": c["repo"], "revision": c["revision"], "dir": d.name, "files": files})
    man = {"schema": lock.MANIFEST_SCHEMA, "installed_at": "2026-01-01T00:00:00Z", "source": "TEST_FIXTURE (losowe wagi)", "fixture": True,
           "components": comps, "tools": {}}
    M.write(dest, man)
    return {"params_model": sum(p.numel() for p in model.parameters()), "params_tokenizer": sum(p.numel() for p in tok.parameters())}


if __name__ == "__main__":
    out = build(Path(sys.argv[1]), small=(sys.argv[2:3] != ["scale"]))
    print(json.dumps(out))
