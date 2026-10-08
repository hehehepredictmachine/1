"""Run Macro Guard, M04N and previous operational-profile tests without network."""
from pathlib import Path
import subprocess,sys,re
BASE=Path(__file__).resolve().parent
jobs=[('M04N Macro Guard 1.0',BASE,['-m','unittest','-q','M04N_MACRO_GUARD_TESTS']),
      ('M04N 1.1 existing',BASE/'macro_sources',['-m','unittest','-q','M04N_TESTS','M04N_FAIR_ECONOMY_TESTS','M04N_M04_CONTRACT_TESTS']),
      ('M07 operational profiles',BASE,['RUN_ALL_OPERATIONAL_PROFILE_TESTS.py'])]
if '--full' in sys.argv:
    jobs.append(('M01-M14 + M15 existing',BASE,['RUN_ALL_M10A_M15_TESTS.py']))
elif len(sys.argv)>1:
    print('Use --full for optional full legacy regression');raise SystemExit(2)
count=0
for name,cwd,args in jobs:
    p=subprocess.run([sys.executable,*args],cwd=cwd,text=True,capture_output=True,timeout=200)
    output=p.stdout+'\n'+p.stderr
    matches=re.findall(r'TOTAL PASS: (\d+)',output)
    if not matches:matches=re.findall(r'ALL PASS: (\d+)',output)
    if not matches:matches=re.findall(r'Ran (\d+) tests?',output)
    n=int(matches[-1]) if matches else 0
    print(name+': '+str(n)+' / '+str(n)+' '+('PASS' if p.returncode==0 else 'FAIL'),flush=True)
    if p.returncode:
        print(output[-4500:]);raise SystemExit(1)
    count+=n
print('TOTAL VERIFIED: '+str(count)+'/'+str(count))
if '--full' not in sys.argv:print('Legacy 794 suite: run separately with --full; this mode intentionally skips it')
