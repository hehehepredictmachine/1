"""Pinned TabICLv2 classifier (stdlib only - imported by the bot too).

  tabicl_v2  jingang/TabICL @ 4dcd344e... file tabicl-classifier-v2-20260212.ckpt (110 368 038 B, LFS sha256 bdc7dbd5...), BSD-3-Clause,
             code: PyPI tabicl 2.2.0 (github.com/soda-inria/tabicl). Pretrained in-context classifier: NO gradient training here - the
             model needs a labelled reference context (X_reference, y_reference) and answers predict_proba for new rows.
Verified 2026-11-16: real download, sha256 match, fit (context 512 x 5) 0.36 s + predict 0.6 s on CPU, peak RSS 656 MB, deterministic.
"""
from __future__ import annotations

SOURCE = "https://huggingface.co"
MANIFEST_NAME = "tabicl_manifest.json"
MANIFEST_SCHEMA = "PMW-TABICL-MANIFEST-1"
PIN = {
    "model_id": "tabicl_v2", "name": "TabICLv2 Classifier", "repo": "jingang/TabICL", "revision": "4dcd344ece2c00be9e831fdd35bed57b5ad83e19",
    "license": "BSD-3-Clause",
    "files": [{"name": "tabicl-classifier-v2-20260212.ckpt", "size": 110368038,
               "sha256": "bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0"}],
    "checkpoint": "tabicl-classifier-v2-20260212.ckpt",
    "code": {"kind": "pypi", "package": "tabicl", "version": "2.2.0", "repo": "https://github.com/soda-inria/tabicl"},
    "venv": ".venv_tabicl", "requirements": "requirements/requirements-tabicl-win.txt",
    # 16 GB budget (resource limits, not quality claims): ensemble 2, batch 1, KV cache off, context target 512 / max 1024 rows
    "inference": {"n_estimators": 2, "batch_size": 1, "kv_cache": False, "context_target": 512, "context_max": 1024, "random_state": 42},
}


def component_dir_name() -> str:
    return PIN["repo"].replace("/", "__") + "@" + PIN["revision"]


def fingerprint() -> str:
    return f"tabicl_v2|{PIN['repo']}@{PIN['revision']}|{PIN['checkpoint']}|tabicl@{PIN['code']['version']}"
