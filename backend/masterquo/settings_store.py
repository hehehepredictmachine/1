"""1.46 arch (I0097): common base of the small JSON settings files (data/<area>/settings.json) and the documented reload policies.

Two policies exist in the application - each store states which one it follows:

  RELOAD_ALWAYS  every read goes to the disk. A write from another process (e.g. `python -m masterquo quant mode ...`) is seen by the
                 running bot at once. Read-modify-write sequences inside one process run under the store's RLock (`with store.lock:`),
                 so two threads never lose each other's change. Used by quant/settings.json (quant.service.Settings).
  OWNER_CACHED   read once and kept in memory by the ONE owning process - the running bot's Runtime (config.json -> config.ConfigStore,
                 kronos/settings.json -> kronos.settings.SettingsStore, tsfm/settings.json -> tsfm.settings.SettingsStore). Another process
                 must not write such a file while the bot runs (the bot would overwrite it with its own copy); it reads it with a read-only
                 view (config.peek) or, inside the bot, uses the Runtime's instance (rt.cfg / rt.kronos.settings / rt.tsfm.settings).

Defaults on a broken file stay the business of each store (Quant SHADOW, Kronos / TSFM OBSERVE): this base never invents values.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

RELOAD_ALWAYS = "RELOAD_ALWAYS"
OWNER_CACHED = "OWNER_CACHED"


def write_json_atomic(path: Path, obj, *, indent: int | None = None) -> None:
    """Temporary file in the same folder + os.replace (a reader never sees a half-written file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False, indent=indent), encoding="utf-8")
    os.replace(tmp, path)


class JsonSettingsStore:
    """RLock + atomic write + an explicit reload policy. Subclasses implement get() (validation / defaults) on top of read_raw()."""

    policy = RELOAD_ALWAYS

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def read_raw(self):
        """Parsed JSON of the file (FileNotFoundError / OSError / ValueError propagate - the subclass decides the defaults)."""
        with self.lock:
            return json.loads(self.path.read_text(encoding="utf-8"))

    def write_raw(self, obj) -> None:
        with self.lock:
            write_json_atomic(self.path, obj)
