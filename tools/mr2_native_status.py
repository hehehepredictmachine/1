"""Write MQL5/Files/PMW/native_status.json after 27_MINIROCKET_NATIVE.bat (evidence for NATIVE_COMPILED; self-test result is read
from mr2_selftest.txt only if the terminal script actually produced it). Usage: python -I mr2_native_status.py DATA_DIR ERRORS LOG
[--flow | --context | --mm]. --mm (1.46 arch I0488, 44_MASTERMODELS_NATIVE.bat): master models + Math Fidelity programs,
MQL5/Files/PMW/mm_native_status.json; the parity verdict itself is mm/fixtures.parity (the bot reads it via mm/inventory)."""
import hashlib
import json
import sys
import time
from pathlib import Path

# 1.46 arch (I0488): what 44_MASTERMODELS_NATIVE.bat installs into MQL5\{Scripts,Indicators,Experts}\PMW and MQL5\Include\{PMW,PMW_MathFidelity}
MM_PROGRAMS = ("PMW_MM_*", "PMW_Kalman*", "PMW_GPR*", "PMW_Breakout*", "PMW_AlignMean", "PMW_TickSessionVP", "MathFidelity*", "FidelityMonitor")
MM_INCLUDES = ("PMW_AlignMeanCore.mqh", "PMW_BreakoutCore.mqh", "PMW_GPR.mqh", "PMW_HDC.mqh", "PMW_Kalman.mqh", "PMW_StateStack.mqh",
               "PMW_TSVPCore.mqh")


def _sha(ps: list) -> str | None:
    return hashlib.sha256(b"".join(p.read_bytes() for p in ps)).hexdigest() if ps else None


def _stale(f: Path, ex5: list) -> bool:
    """A self-test output older than the newest EX5 belongs to a previous build and is not evidence for this one."""
    return not ex5 or f.stat().st_mtime < max(p.stat().st_mtime for p in ex5)


def mm_status(data: str, errors: str, log: str) -> dict:
    d = Path(data) / "MQL5"
    ex5, src = [], []
    for sub in ("Scripts", "Indicators", "Experts"):
        for pat in MM_PROGRAMS:
            ex5 += (d / sub / "PMW").glob(pat + ".ex5")
            src += (d / sub / "PMW").glob(pat + ".mq5")
    ex5 = sorted(set(ex5))
    inc = sorted(p for p in (d / "Include" / "PMW" / n for n in MM_INCLUDES) if p.exists())
    src = inc + sorted((d / "Include" / "PMW_MathFidelity").glob("*.mqh")) + sorted(set(src))
    out = {"schema": "PMW-MM-NATIVE-STATUS-1", "compile_errors": int(errors), "ex5_files": [p.name for p in ex5], "ex5_sha256": _sha(ex5),
           "source_sha256": _sha(src), "log": log, "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           # the self-test runs in the terminal AFTER this compilation: the reader compares its output with the newest EX5 time
           "ex5_newest_mtime": max((p.stat().st_mtime for p in ex5), default=None)}
    nat = d / "Files" / "PMW_MM" / "PMW_MM_NATIVE.txt"                  # PMW_MM_SelfTest output, compared by mm/fixtures.parity
    out["selftest_file"] = "PMW_MM/PMW_MM_NATIVE.txt"
    out["selftest_present"] = nat.exists()
    out["selftest_stale"] = _stale(nat, ex5) if nat.exists() else None
    out["selftest_result"] = "NATIVE_OUTPUT_FRESH" if nat.exists() and not out["selftest_stale"] else "NATIVE_NOT_EXECUTED"
    mf = d / "Files" / "PMW_MathFidelity" / "selftest.txt"
    mres = "NATIVE_NOT_EXECUTED"
    if mf.exists() and not _stale(mf, ex5):
        head = mf.read_text(errors="replace").splitlines()[:1]
        mres = "PASS" if head and "/ 0 FAIL" in head[0] else "FAIL"
    out["mathfidelity_selftest_result"] = mres
    (d / "Files" / "PMW").mkdir(parents=True, exist_ok=True)
    (d / "Files" / "PMW" / "mm_native_status.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return out


def main(data: str, errors: str, log: str, flow: bool = False, ctx: bool = False, mm: bool = False) -> int:
    """flow=True: PMW-UPD-11 FlowContext sources (MQ_*), status file flow_native_status.json, self-test flow_selftest.txt.
    ctx=True: PMW-UPD-14 ContextIndicators (PWM_*), ctx_native_status.json, ctx_selftest.txt.
    mm=True: master models + Math Fidelity (44_MASTERMODELS_NATIVE.bat), mm_native_status.json."""
    if mm:
        mm_status(data, errors, log)
        return 0
    d = Path(data) / "MQL5"
    pat_i, pat_s, inc = ("MQ_*", "MQ_Flow*", "PMW_FlowMA.mqh") if flow else ("PMW_MR2_*", "PMW_MR2_*", "PMW_MR2_*.mqh")
    if ctx:
        pat_i, pat_s, inc = "PWM_*", "PWM_*", "PMW_ContextCore.mqh"
    ex5 = sorted(list((d / "Scripts" / "PMW").glob(pat_s + ".ex5")) + list((d / "Indicators" / "PMW").glob(pat_i + ".ex5")))
    src = sorted((d / "Include" / "PMW").glob(inc)) + sorted((d / "Scripts" / "PMW").glob(pat_s + ".mq5")) \
        + sorted((d / "Indicators" / "PMW").glob(pat_i + ".mq5"))
    h = lambda ps: hashlib.sha256(b"".join(p.read_bytes() for p in ps)).hexdigest() if ps else None  # noqa: E731
    st = d / "Files" / "PMW" / ("ctx_selftest.txt" if ctx else "flow_selftest.txt" if flow else "mr2_selftest.txt")
    res, stale = "NATIVE_NOT_EXECUTED", None
    if st.exists():
        # 1.46: the bat deletes the old EX5 but not the self-test file, and the self-test runs in the terminal only AFTER this
        # compilation - a self-test file older than the newest EX5 belongs to a previous build and is not evidence for this one
        stale = not ex5 or st.stat().st_mtime < max(p.stat().st_mtime for p in ex5)
        if not stale:
            txt = st.read_text(errors="replace")
            res = "PASS" if "RESULT=PASS" in txt else ("FAIL" if "RESULT=FAIL" in txt else res)
    out = {"compile_errors": int(errors), "ex5_files": [p.name for p in ex5], "ex5_sha256": h(ex5), "source_sha256": h(src), "log": log,
           "selftest_result": res, "selftest_stale": stale, "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (d / "Files" / "PMW" / ("ctx_native_status.json" if ctx else "flow_native_status.json" if flow else "native_status.json")).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4], flow="--flow" in sys.argv, ctx="--context" in sys.argv, mm="--mm" in sys.argv))
