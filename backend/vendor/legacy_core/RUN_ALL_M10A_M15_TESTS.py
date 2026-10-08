"""One-command local verification for new bridge + upstream engines + M15."""
from pathlib import Path
import re, subprocess, sys, os
root=Path(__file__).resolve().parent

def go(label,argv,cwd,env):
    res=subprocess.run(argv,cwd=cwd,env=env,text=True,capture_output=True,timeout=150)
    out=res.stdout+'\n'+res.stderr
    count=sum(int(x) for x in re.findall(r'Ran (\d+) tests?',out))
    if label=='M01-M14 original regression':
        count=int(re.search(r'TOTAL PASS: (\d+)',out).group(1)) if res.returncode==0 else 0
    print(label+': '+str(count)+' tests '+('PASS' if res.returncode==0 else 'FAIL'),flush=True)
    if res.returncode:
        print(out[-5000:]);return count,False
    return count,True

def main():
    total=0
    env=os.environ.copy()
    env['PYTHONPATH']=os.pathsep.join([str(root),str(root/'vendor'),str(root/'vendor/M15'),str(root/'vendor/M14')])
    jobs=[('M01-M14 original regression',[sys.executable,'RUN_ALL_OFFLINE_TESTS.py'],root),
          ('M15 original regression',[sys.executable,'-m','unittest','M15_TESTS','-q'],root/'vendor/M15'),
          ('M10A-M15 new integration',[sys.executable,'-m','unittest','M10A_M15_TESTS','-q'],root)]
    for label,command,cwd in jobs:
        count,ok=go(label,command,cwd,env)
        if not ok:return 1
        total+=count
    print('TOTAL PASS: '+str(total)+' / '+str(total))
    return 0
if __name__=='__main__':raise SystemExit(main())
