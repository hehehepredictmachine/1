"""Pinned sources of the additional time-series foundation models (stdlib only - imported by the bot too, without torch).

Every model is fixed to an exact Hugging Face commit and to exact file sizes / SHA-256 values read from the source metadata (LFS sha256)
and confirmed by a real download + load + inference on 2026-11-08. The installer downloads exactly these files, checks the size and the
SHA-256 before a file is accepted and writes the manifest only after every file matched; nothing else is ever loaded.

  chronos2  amazon/chronos-2 (120 M parameters - measured 119 477 664), code: PyPI chronos-forecasting 2.3.2
            (= github.com/amazon-science/chronos-forecasting tag v2.3.2, commit 0aba28e9…), Apache-2.0
  granite_ttm  ibm-granite/granite-timeseries-ttm-r2, branch main = TTM R2 "512-96-r2" (context 512, horizon 96, no frequency prefix;
            805 280 parameters measured), code: PyPI granite-tsfm 0.3.11 (github.com/ibm-granite/granite-tsfm), Apache-2.0 (1.40).
            Chosen on a walk-forward test on real XAUUSD M5 / M15 / H1 (Q4 2025): the lowest error of the R2 / R2.1 variants tried
            (512-96-r2, 512-48-ft-r2.1, 512-96-ft-r2.1, 1024-96-r2) - see docs/MIGRACJA_FINCAST_GRANITE_1_40_PL.md. Point forecast only.
  fincast   RETIRED in 1.40 (replaced by granite_ttm): Vincent05R/FinCast v1.pth (~1 B parameters - measured 991 436 960). The pin stays
            for the history (old forecasts keep their model id and revision); it is no longer installed, loaded or scheduled.

The ids `chronos2` / `fincast` are the persistent model ids of the bot (settings, history, approvals); the checkpoint variant is stored
separately (VARIANT) so a later checkpoint never rewrites the meaning of old records.
"""
from __future__ import annotations

VERIFIED_AT = "2026-11-08"
MANIFEST_NAME = "tsfm_manifest.json"
MANIFEST_SCHEMA = "PMW-TSFM-MANIFEST-1"
SOURCE = "https://huggingface.co"

MODELS: dict[str, dict] = {
    "chronos2": {
        "model_id": "chronos2", "name": "Chronos-2", "variant": "amazon/chronos-2", "params_upstream": "120M", "params_measured": 119477664,
        "repo": "amazon/chronos-2", "revision": "29ec3766d36d6f73f0696f85560a422f50e8498c", "license": "Apache-2.0",
        "files": [
            {"name": "config.json", "size": 1067, "git_blob_sha1": "f3207394965100a2aa18820b87da3d2bbad3b1f0"},
            {"name": "model.safetensors", "size": 477930472, "sha256": "ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42"},
        ],
        "required_files": ("config.json", "model.safetensors"),
        "code": {"kind": "pypi", "package": "chronos-forecasting", "version": "2.3.2", "repo": "https://github.com/amazon-science/chronos-forecasting",
                 "tag": "v2.3.2", "commit": "0aba28e9360b6355d5a919596c90b16c25939f02"},
        "venv": ".venv_chronos2", "requirements": "requirements/requirements-chronos2-win.txt",
        "max_context": 8192, "native_quantiles": [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8,
                                                   0.85, 0.9, 0.95, 0.99],
        "point": "median",            # predict_quantiles() returns the 0.5 quantile as its "mean" output - shown as the MEDIAN
        "deterministic": True,
    },
    "granite_ttm": {
        "model_id": "granite_ttm", "name": "Granite TTM", "variant": "ibm-granite/granite-timeseries-ttm-r2 (TTM R2 512-96-r2)",
        "params_upstream": "0.8M", "params_measured": 805280, "repo": "ibm-granite/granite-timeseries-ttm-r2",
        "revision": "d6a79570cac0f33d526601cd3a0fc7c80a8f9a2f", "license": "Apache-2.0",
        "files": [
            {"name": "config.json", "size": 1563, "git_blob_sha1": "09e937ef5082573c0785a180f23753110b78696c"},
            {"name": "generation_config.json", "size": 69, "git_blob_sha1": "babac55572610cf59da0e8a71a4203ed6f2a7ab9"},
            {"name": "model.safetensors", "size": 3240592, "sha256": "a706726a7eb01bbcb42994b7dcb3c06ea9557898dbae8d480eb04fe8ccb89710"},
        ],
        "required_files": ("config.json", "model.safetensors"),
        "code": {"kind": "pypi", "package": "granite-tsfm", "version": "0.3.11", "repo": "https://github.com/ibm-granite/granite-tsfm"},
        "venv": ".venv_granite", "requirements": "requirements/requirements-granite-win.txt",
        "max_context": 512, "native_quantiles": [], "native_horizon": 96,
        "point": "point",             # MSE-trained head: a point forecast of the close; no quantiles / no OHLC are produced or invented
        "deterministic": True,
        "normalization": "z-score of the context window only (mean / std of the 512 closed bars before the origin), inverted on the output",
    },
    "fincast": {
        "model_id": "fincast", "retired": True, "retired_in": "1.40.0", "replaced_by": "granite_ttm", "name": "FinCast", "variant": "Vincent05R/FinCast v1 (CIKM 2025, 1B)", "params_upstream": "1B",
        "params_measured": 991436960, "repo": "Vincent05R/FinCast", "revision": "2d7d90b159db8961d27c2cf165d51195902ef92b",
        "license": "Apache-2.0",
        "files": [
            {"name": "v1.pth", "size": 3966703063, "sha256": "d5ca999b02c944effa60d2b94174dc4d5a0cd2c0543ae289b2e36f37431492a8"},
            {"name": "checksum_f.txt", "size": 73, "git_blob_sha1": "d83d7be6f33e8d73e0067dd8eee88dddc001fde7"},
        ],
        "required_files": ("v1.pth",),
        "code": {"kind": "vendor", "path": "tsfm_runtime/vendor/fincast", "repo": "https://github.com/vincent05r/FinCast-fts",
                 "commit": "488b19d1d85fa2b3d4b93469530cefdcf1cc97a4"},
        "venv": ".venv_fincast", "requirements": None,      # 1.40: not installed any more (retired)
        # official inference settings of v1 (Inference/inference_future.ipynb + tools/inference_utils.py)
        "hparams": {"num_experts": 4, "gating_top_n": 2, "load_from_compile": True, "use_positional_embedding": False,
                    "input_patch_len": 32, "output_patch_len": 128, "num_layers": 50, "num_heads": 16, "model_dims": 1280},
        "max_context": 2048, "native_quantiles": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        "point": "mean",              # point_forecast_mode="mean" (the mean head); the 0.5 quantile is reported separately as the median
        "deterministic": True,
        # FinCast frequency classes (ffm: 0 high, 1 medium, 2 low); tools/inference_utils.freq_reader_inference maps "MIN"/"H"/"D" -> 0
        "freq_class": {"M1": 0, "M3": 0, "M5": 0, "M15": 0, "M30": 0, "H1": 0, "H4": 0, "D1": 0},
    },
}


ACTIVE = tuple(k for k, v in MODELS.items() if not v.get("retired"))
RETIRED = tuple(k for k, v in MODELS.items() if v.get("retired"))


def model(mid: str) -> dict:
    if mid not in MODELS:
        raise KeyError(f"nieznany model {mid!r} (dostępne: {', '.join(MODELS)})")
    return MODELS[mid]


def component_dir_name(m: dict) -> str:
    """Folder of one model inside the weights root: <owner>__<name>@<revision> (as for Kronos)."""
    return m["repo"].replace("/", "__") + "@" + m["revision"]


def fingerprint(mid: str) -> str:
    """Identity of the loaded artefact for caches / approvals: model id + repo@revision + code pin."""
    m = model(mid)
    code = m["code"]
    return f"{mid}|{m['repo']}@{m['revision']}|{code.get('package', code.get('path'))}@{code.get('version', code.get('commit'))}"
