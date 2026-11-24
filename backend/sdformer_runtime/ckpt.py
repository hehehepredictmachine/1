"""Checkpoint reading of SDformerFlow (1.46 arch).

torch.load(weights_only=True) of last.pt (1.46: no pickle code execution for imported ZIPs). Checkpoints written by 1.46.0 carry
deps.torch = torch.__version__ (a TorchVersion, a str subclass) - weights_only refused every one of them ("Unsupported global"), so no
trained SDformerFlow could ever be activated. Only that type is allowed in addition; new checkpoints store a plain str.
"""
from __future__ import annotations

import contextlib


def load_checkpoint(path):
    import torch
    try:
        from torch.torch_version import TorchVersion
        allow = torch.serialization.safe_globals([TorchVersion])
    except (ImportError, AttributeError):          # a torch without safe_globals (or a test double): plain weights_only load
        allow = contextlib.nullcontext()
    with allow:
        return torch.load(path, map_location="cpu", weights_only=True)
