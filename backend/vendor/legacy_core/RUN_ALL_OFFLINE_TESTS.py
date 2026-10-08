"""Reproducible synthetic regression runner; tests immutable upstream sources."""
import os
from pathlib import Path
import re
import subprocess
import sys
BASE=Path(__file__).resolve().parent
TESTS=[
    'M10_AUTO_TRIGGER_TESTS.py',
    'INTEGRATION_TESTS.py','BRIDGE_TESTS.py','M10_TESTS.py',
    'vendor/M01/M01_CONTRACT_TESTS.py',
    'vendor/M01/M01_CONTINUOUS_OBSERVER_TESTS.py',
    'vendor/M02/M02_TESTS.py',
    'vendor/M02I/M02I_TESTS.py',
    'vendor/M02I/M02I_TIMEFRAME_PROFILE_TESTS.py',
    'vendor/M03/M03_TESTS.py',
    'vendor/M09/M09_TESTS.py',
    'vendor/M14/M14_TESTS.py',
]
def main():
    total=0
    for file in TESTS:
        path=BASE/file
        env=os.environ.copy()
        env['PYTHONPATH']=os.pathsep.join([str(BASE),str(BASE/'vendor'),str(path.parent)]+
                          [str(BASE/'vendor'/x) for x in ('M01','M02','M02I','M03','M09','M14')])
        p=subprocess.run([sys.executable,'-m','unittest',path.stem,'-q'],cwd=str(path.parent),env=env,
                         capture_output=True,text=True,timeout=100)
        combined=p.stdout+'\n'+p.stderr
        match=re.search(r'Ran (\d+) tests?',combined)
        n=int(match.group(1)) if match else 0
        print(f'{file}: {n} tests, {"PASS" if p.returncode==0 else "FAIL"}',flush=True)
        if p.returncode:
            print(combined[-4000:]);return 1
        total+=n
    print(f'TOTAL PASS: {total} / {total}',flush=True)
    return 0
if __name__=='__main__':raise SystemExit(main())
