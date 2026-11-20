"""1.42.2: python tools/venv_repair.py <venv> [<venv> ...] - re-points a .venv_* after the program folder was moved (pyvenv.cfg ->
the Python running this script) or sets it aside for a fresh one. Exit 0 = OK / REPAIRED / MISSING / SET_ASIDE, 1 = FAILED."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import mq_venv  # noqa: E402


def main(argv=None) -> int:
    base = getattr(sys, "_base_executable", None) or sys.executable
    bad = 0
    for v in (argv if argv is not None else sys.argv[1:]):
        r = mq_venv.repair(Path(v), base, lambda m: print("[VENV]", m, flush=True))
        print(f"[VENV] {Path(v).name}: {r['state']}" + (f" – {r['detail']}" if r.get("detail") else ""), flush=True)
        bad += r["state"] == "FAILED"
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
