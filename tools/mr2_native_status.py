"""Write MQL5/Files/PMW/native_status.json after 27_MINIROCKET_NATIVE.bat (evidence for NATIVE_COMPILED; self-test result is read
from mr2_selftest.txt only if the terminal script actually produced it). Usage: python -I mr2_native_status.py DATA_DIR ERRORS LOG"""
import hashlib
import json
import sys
import time
from pathlib import Path


def main(data: str, errors: str, log: str) -> int:
    d = Path(data) / "MQL5"
    ex5 = sorted(list((d / "Scripts" / "PMW").glob("PMW_MR2_*.ex5")) + list((d / "Indicators" / "PMW").glob("PMW_MR2_*.ex5")))
    src = sorted((d / "Include" / "PMW").glob("PMW_MR2_*.mqh")) + sorted((d / "Scripts" / "PMW").glob("PMW_MR2_*.mq5")) \
        + sorted((d / "Indicators" / "PMW").glob("PMW_MR2_*.mq5"))
    h = lambda ps: hashlib.sha256(b"".join(p.read_bytes() for p in ps)).hexdigest() if ps else None  # noqa: E731
    st = d / "Files" / "PMW" / "mr2_selftest.txt"
    res = "NATIVE_NOT_EXECUTED"
    if st.exists():
        txt = st.read_text(errors="replace")
        res = "PASS" if "RESULT=PASS" in txt else ("FAIL" if "RESULT=FAIL" in txt else res)
    out = {"compile_errors": int(errors), "ex5_files": [p.name for p in ex5], "ex5_sha256": h(ex5), "source_sha256": h(src), "log": log,
           "selftest_result": res, "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (d / "Files" / "PMW" / "native_status.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
