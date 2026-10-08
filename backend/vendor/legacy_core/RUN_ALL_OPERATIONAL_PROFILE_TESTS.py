"""Run existing M10A/M15 regression and new research profile regression from ZIP."""
from pathlib import Path
import os,re,subprocess,sys
ROOT=Path(__file__).resolve().parent

def launch(title,cmd,timeout=210):
    env=os.environ.copy()
    env['PYTHONPATH']=os.pathsep.join([str(ROOT),str(ROOT/'vendor'),str(ROOT/'vendor/M02'),
                                      str(ROOT/'vendor/M03'),str(ROOT/'vendor/M15')])
    p=subprocess.run(cmd,cwd=ROOT,env=env,text=True,capture_output=True,timeout=timeout)
    output=p.stdout+'\n'+p.stderr
    totals=re.findall(r'TOTAL PASS: (\d+)',output)
    if totals and title=='Preserved M10A/M15 regression':n=int(totals[-1])
    else:n=sum(int(x) for x in re.findall(r'Ran (\d+) tests?',output))
    print(title+': '+str(n)+' tests '+('PASS' if p.returncode==0 else 'FAIL'),flush=True)
    if p.returncode:print(output[-8000:])
    return n,p.returncode==0

def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    with_regression='--with-regression' in argv
    if any(x!='--with-regression' for x in argv):
        print('Usage: RUN_ALL_OPERATIONAL_PROFILE_TESTS.py [--with-regression]');return 2
    total=0
    if with_regression:
        n,ok=launch('Preserved M10A/M15 regression',[sys.executable,'RUN_ALL_M10A_M15_TESTS.py'],timeout=300)
        if not ok:return 1
        total+=n
    n,ok=launch('New operational profile tests',[sys.executable,'-m','unittest',
                 '-q','M07_M03E_PROFILE_TESTS','M07_M03E_RUNTIME_TESTS'],timeout=120)
    if not ok:return 1
    total+=n
    print(f'ALL PASS: {total}/{total}')
    if not with_regression:
        print('Note: add --with-regression to rerun 794 preserved tests (long duration)')
    return 0
if __name__=='__main__':raise SystemExit(main())
