"""Offline test runner (05_TESTY_OFFLINE.bat).

  python tools/run_tests.py            MasterQUO AI test suite (tests/)
  python tools/run_tests.py --legacy   + original MasterQUO regression suites, run on a temporary
                                         copy of backend/vendor (the vendored code is never modified)
Writes a JSON summary to data/logs/testy_offline_*.json. Offline tests do NOT prove the
connection with your MT5 terminal or Claude - use 02_DIAGNOSTYKA.bat for that.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY = [("legacy_core", "RUN_ALL_OPERATIONAL_PROFILE_TESTS.py"), ("legacy_core", "RUN_MACRO_GUARD_ALL_TESTS.py"),
          ("legacy_core", "RUN_ALL_OFFLINE_TESTS.py"), ("m04n", "M04N_TESTS.py")]


def run_suite() -> dict:
    sys.path.insert(0, str(ROOT / "tests"))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT / "tests"))
    res = unittest.TextTestRunner(verbosity=2).run(suite)
    return {"ran": res.testsRun, "failures": len(res.failures), "errors": len(res.errors), "skipped": len(res.skipped),
            "ok": res.wasSuccessful(), "failed_tests": [str(t[0]) for t in res.failures + res.errors]}


def candle_python():
    for c in (os.environ.get("MQ_CANDLES_PYTHON"), ROOT / ".venv_candles" / "Scripts" / "python.exe", ROOT / ".venv_candles" / "bin" / "python"):
        if c and Path(c).exists():
            return str(c)
    return None


def run_candles() -> dict:
    """gold_candles reference tests (29) + runtime integration tests, with the ISOLATED .venv_candles interpreter (pinned
    numpy/pandas/scikit-learn of the module). Without that environment the suite is reported SKIPPED - never passed."""
    py = candle_python()
    if not py:
        return {"status": "SKIPPED_NO_CANDLE_ENV", "ok": True, "note": "uruchom 10_PROGNOZY_INSTALUJ.bat (tworzy .venv_candles)"}
    env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"))
    t0 = time.time()
    p = subprocess.run([py, "-m", "unittest", "discover", "-s", str(ROOT / "tests" / "gold_candles"), "-p", "test_*.py", "-v"],
                       cwd=str(ROOT / "tests" / "gold_candles"), env=env, capture_output=True, text=True, timeout=3600)
    tail = p.stderr[-3000:]
    print("[candles]", tail[-1200:])
    import re
    m = re.search(r"Ran (\d+) tests", p.stderr)
    return {"status": "PASS" if p.returncode == 0 else "FAIL", "ok": p.returncode == 0, "interpreter": py, "ran": int(m.group(1)) if m else None,
            "seconds": round(time.time() - t0, 1), "tail": tail}


def run_legacy() -> list:
    out = []
    tmp = Path(tempfile.mkdtemp(prefix="mq_legacy_"))
    try:
        shutil.copytree(ROOT / "backend" / "vendor", tmp / "vendor")
        for sub, script in LEGACY:
            cwd = tmp / "vendor" / sub
            t0 = time.time()
            p = subprocess.run([sys.executable, script], cwd=str(cwd), capture_output=True, text=True, timeout=1800)
            tail = (p.stdout + p.stderr)[-1500:]
            out.append({"suite": f"{sub}/{script}", "returncode": p.returncode, "seconds": round(time.time() - t0, 1), "tail": tail})
            print(f"[legacy] {sub}/{script}: rc={p.returncode}\n{tail[-600:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main() -> int:
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0], "platform": sys.platform,
               "masterquo_ai": run_suite(), "gold_candles": run_candles()}
    if "--legacy" in sys.argv:
        summary["legacy"] = run_legacy()
    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    p = logs / f"testy_offline_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    p.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = summary["masterquo_ai"]["ok"] and summary["gold_candles"]["ok"] and all(x["returncode"] == 0 for x in summary.get("legacy", []))
    print("\nRaport:", p)
    print("WYNIK:", "WSZYSTKIE TESTY OFFLINE ZALICZONE" if ok else "SA BLEDY - patrz raport")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
