import sys, os, json, time, resource
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, "/home/user/1/backend")
from datetime import datetime, timedelta
from common import *
from kronos_runtime import engine as E
eng=E.Engine(); info=eng.load("/tmp/claude-0/-home-user-1/e704900f-05d3-5cd0-a027-a6973be977c8/scratchpad/kronos_w", device="CPU", threads=4)
print("kronos loaded", info.get("params"), info.get("load_ms"))
out=[]
N={"M5":60,"M15":40,"H1":40}
for tf,H,dt in (("M5",12,5),("M15",8,15),("H1",6,60)):
    t,o,h,l,c=load(tf); orig=origins(t,H,step=max(H,(len([x for x in t if x>='2025-10-01'])//N[tf]) or H))[:N[tf]]
    preds=[];t0=time.perf_counter()
    for i in orig:
        s=i-511
        cand={"open":o[s:i+1],"high":h[s:i+1],"low":l[s:i+1],"close":c[s:i+1],"t":t[s:i+1]}
        last=datetime.fromisoformat(t[i]); yt=[(last+timedelta(minutes=dt*(k+1))).isoformat() for k in range(H)]
        r=eng.predict({"candles":cand,"pred_len":H,"y_t":yt,"T":1.0,"top_p":0.9,"sample_count":1,"seed":7})
        preds.append(float(r["close"][-1]) if "close" in r else float(r["pred"]["close"][-1]))
    ms=(time.perf_counter()-t0)*1000/len(orig)
    r=score("kronos-base",preds,orig,h,l,c,H); r.update(tf=tf,H=H,ms_per_origin=round(ms,1)); out.append(r); print(r,flush=True)
    rn=score("naive_last(same origins)",[c[i] for i in orig],orig,h,l,c,H); rn.update(tf=tf,H=H); out.append(rn); print(rn,flush=True)
print("maxrss_mb",resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
json.dump(out,open(os.path.dirname(__file__)+"/res_kronos.json","w", encoding="utf-8"),indent=1)
