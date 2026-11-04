"""Pinned model sources (stdlib only - imported by the bot too, without torch).

The pair is fixed: Kronos-small was trained with Kronos-Tokenizer-base (upstream README, model zoo). Revisions are git commits of the
Hugging Face repositories - the same ones the upstream regression test uses (tests/test_kronos_regression.py). The installer checks that
each revision exists, downloads exactly that commit and verifies every file against the source metadata (LFS sha256 / git blob sha1).
"""
from __future__ import annotations

MODEL = {"repo": "NeoQuasar/Kronos-small", "revision": "901c26c1332695a2a8f243eb2f37243a37bea320", "kind": "model",
         "max_context": 512, "params_upstream": "24.7M"}
TOKENIZER = {"repo": "NeoQuasar/Kronos-Tokenizer-base", "revision": "0e0117387f39004a9016484a186a908917e22426", "kind": "tokenizer"}
COMPONENTS = (MODEL, TOKENIZER)
# PyTorchModelHubMixin layout. Only safetensors is accepted - a pickle checkpoint (pytorch_model.bin) is never loaded.
REQUIRED_FILES = ("config.json", "model.safetensors")
MAX_CONTEXT = 512
MANIFEST_NAME = "kronos_manifest.json"
MANIFEST_SCHEMA = "PMW-KRONOS-MANIFEST-1"
SOURCE = "https://huggingface.co"
LICENSE = "MIT (kod Kronos, Copyright (c) 2025 ShiYu); wagi: licencja wg kart modeli NeoQuasar na Hugging Face"


def component_dir_name(c: dict) -> str:
    """Folder of one component inside the weights directory: <owner>__<name>@<revision>."""
    return c["repo"].replace("/", "__") + "@" + c["revision"]
