"""Interpreter check used by 01_INSTALUJ.bat BEFORE creating the virtual environment.

Exit 0 and print PY_OK when: CPython 3.12/3.13, 64-bit, venv + ensurepip importable and the
Windows venv launcher files exist (the earlier venvlauncher.exe WinError 2 problem).
Uses only the standard library; never modifies the interpreter.
"""
import os
import platform
import struct
import sys
import sysconfig


def main() -> int:
    problems = []
    ver = sys.version_info
    bits = struct.calcsize("P") * 8
    if platform.python_implementation() != "CPython":
        problems.append("NOT_CPYTHON")
    if (ver.major, ver.minor) not in ((3, 12), (3, 13)):
        problems.append(f"UNSUPPORTED_VERSION_{ver.major}.{ver.minor}_USE_3.13_x64")
    if bits != 64:
        problems.append("NOT_64_BIT")
    try:
        import ensurepip  # noqa: F401
        import venv  # noqa: F401
    except ImportError as exc:
        problems.append("VENV_OR_ENSUREPIP_MISSING:" + str(exc))
    if os.name == "nt":
        nt_dir = os.path.join(sysconfig.get_paths()["stdlib"], "venv", "scripts", "nt")
        for f in ("venvlauncher.exe", "venvwlauncher.exe"):
            if not os.path.isfile(os.path.join(nt_dir, f)):
                problems.append("MISSING_" + f)
    print(f"PYTHON {platform.python_version()} {bits}-bit {sys.executable}")
    if problems:
        print("PY_PROBLEMS " + " ".join(problems))
        return 1
    print("PY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
