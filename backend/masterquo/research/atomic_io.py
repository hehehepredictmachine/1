"""Atomic JSON writer of the research modules (leaf module). 1.46 arch I0085: components imported _atomic lazily from service, and service
imports components (the components <-> service cycle). Moved unchanged; research.service re-exports it under the old name."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


def _atomic(p: Path, obj) -> None:
    # 1.46: the temp name is unique per writer thread - two threads writing the same file shared "<file>.tmp" (one os.replace failed
    # with FileNotFoundError, the other could publish a half-written file)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
