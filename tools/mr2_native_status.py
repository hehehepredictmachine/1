"""Write MQL5/Files/PMW/native_status.json after 27_MINIROCKET_NATIVE.bat (evidence for NATIVE_COMPILED; self-test result is read
from mr2_selftest.txt only if the terminal script actually produced it). Usage: python -I mr2_native_status.py DATA_DIR ERRORS LOG"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path


def main(data: str, errors: str, log: str, flow: bool = False, ctx: bool = False) -> int:
    """flow=True: PMW-UPD-11 FlowContext sources (MQ_*), status file flow_native_status.json, self-test flow_selftest.txt.
    ctx=True: PMW-UPD-14 ContextIndicators (PWM_*), ctx_native_status.json, ctx_selftest.txt."""
    d = Path(data) / "MQL5"
    pat_i, pat_s, inc = ("MQ_*", "MQ_Flow*", "PMW_FlowMA.mqh") if flow else ("PMW_MR2_*", "PMW_MR2_*", "PMW_MR2_*.mqh")
    if ctx:
        pat_i, pat_s, inc = "PWM_*", "PWM_*", "PMW_ContextCore.mqh"
    ex5 = sorted(list((d / "Scripts" / "PMW").glob(pat_s + ".ex5")) + list((d / "Indicators" / "PMW").glob(pat_i + ".ex5")))
    src = sorted((d / "Include" / "PMW").glob(inc)) + sorted((d / "Scripts" / "PMW").glob(pat_s + ".mq5")) \
        + sorted((d / "Indicators" / "PMW").glob(pat_i + ".mq5"))
    h = lambda ps: hashlib.sha256(b"".join(p.read_bytes() for p in ps)).hexdigest() if ps else None  # noqa: E731
    st = d / "Files" / "PMW" / ("ctx_selftest.txt" if ctx else "flow_selftest.txt" if flow else "mr2_selftest.txt")
    res, stale, build = "NATIVE_NOT_EXECUTED", None, None
    if st.exists():
        # 1.46: the bat deletes the old EX5 but not the self-test file, and the self-test runs in the terminal only AFTER this
        # compilation - a self-test file older than the newest EX5 belongs to a previous build and is not evidence for this one
        stale = not ex5 or st.stat().st_mtime < max(p.stat().st_mtime for p in ex5)
        if not stale:
            txt = st.read_text(errors="replace")
            res = "PASS" if "RESULT=PASS" in txt else ("FAIL" if "RESULT=FAIL" in txt else res)
            # 1.46 (I0480): the self-test line carries the terminal build (PMW_MR2_SelfTest.mq5: `build=%d`) - minirocket_v2.native_status
            # reads `terminal_build`, which was never written (always None); only a fresh self-test is evidence for this build
            m = re.search(r"\bbuild=(\d+)", txt)
            build = int(m.group(1)) if m else None
    out = {"compile_errors": int(errors), "ex5_files": [p.name for p in ex5], "ex5_sha256": h(ex5), "source_sha256": h(src), "log": log,
           "selftest_result": res, "selftest_stale": stale, "terminal_build": build, "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (d / "Files" / "PMW" / ("ctx_native_status.json" if ctx else "flow_native_status.json" if flow else "native_status.json")).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4], flow="--flow" in sys.argv, ctx="--context" in sys.argv))
