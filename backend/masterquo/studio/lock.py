"""Cross-process lock (PMW-LOCK-1) shared by Studio instances and the bot's export: lock file created with O_EXCL holding the owner
(pid, app, job, host) and a heartbeat. A lock is stale when its pid is dead or the heartbeat is older than `stale_s`; a stale lock is taken
over atomically (rename + re-create). Only the owner releases it.

1.46 arch Etap 4: przeniesione do masterquo/locks.py (OwnerLock, mechanizm OWNER_HEARTBEAT usługi blokad 'export[:<inst>]'), alias
zgodności - the Studio queue and older code import Lock / _alive from here; the code, the lock file and the owner record are the same."""
from __future__ import annotations

from ..locks import OwnerLock


def _alive(pid) -> bool:
    """1.46: on Windows os.kill(pid, 0) is GenerateConsoleCtrlEvent(CTRL_C_EVENT) - for a process outside the caller's console it fails, so
    every owner looked dead and the shared export lock never excluded anything. Same check as training.core (OpenProcess + STILL_ACTIVE)."""
    try:
        from ..training.core import _pid_alive
        return _pid_alive(int(pid))
    except (OSError, ValueError, TypeError):
        return False


class Lock(OwnerLock):
    """Alias zgodności: masterquo.locks.OwnerLock (same constructor, records and answers); owner liveness through this module's _alive."""

    def _owner_alive(self, pid) -> bool:
        return _alive(pid)
