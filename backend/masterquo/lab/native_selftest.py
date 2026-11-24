"""Native (MQL5) build / self-test evidence shared by MiniRocket V2, FlowContext and ContextIndicators (1.46 arch I0479 / I0519 / I0522).

The .bat (27_MINIROCKET_NATIVE / 28_FLOW_CONTEXT / 29_CONTEXT_INDICATORS) compiles, then tools/mr2_native_status.py writes the status JSON
at once - the self-test script runs in the terminal only AFTER that. A self-test file in the status file's folder that is NOT OLDER than
the status file therefore belongs to this build and is read live (RESULT=PASS|FAIL, build=N); an older one belongs to a previous build
and the status file's own selftest_result stays. One status name for 'no status file / no MetaEditor' for all three modules."""
from __future__ import annotations

import re
from pathlib import Path

NOT_COMPILED = "NOT_COMPILED_NO_METAEDITOR"
NOT_EXECUTED = "NATIVE_NOT_EXECUTED"


def live_selftest(status_file: Path, name: str) -> dict | None:
    """{result: PASS|FAIL|None, build: int|None, file} of <status dir>/<name> when it exists and is not older than the status file."""
    sf = Path(status_file)
    f = sf.parent / name
    try:
        if not f.is_file() or f.stat().st_mtime < sf.stat().st_mtime:
            return None
        txt = f.read_text(errors="replace")
    except OSError:
        return None
    res = "PASS" if "RESULT=PASS" in txt else ("FAIL" if "RESULT=FAIL" in txt else None)
    m = re.search(r"\bbuild=(\d+)", txt)
    return {"result": res, "build": int(m.group(1)) if m else None, "file": str(f)}


def executed(st: dict, status_file: Path, name: str) -> tuple[str, int | None]:
    """(NATIVE_EXECUTED, self-test terminal build) - the live self-test of this build, else the status file's selftest_result."""
    live = live_selftest(status_file, name)
    if live and live["result"]:
        return live["result"], live["build"]
    return st.get("selftest_result", NOT_EXECUTED), None
