import sys, os, json, time, resource, glob
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, torch
from common import *
from chronos import Chronos2Pipeline
torch.set_num_threads(4)
d=glob.glob("/tmp/claude-0/-home-user-1/e704900f-05d3-5cd0-a027-a6973be977c8/scratchpad/tsfm_weights/chronos2/amazon__chronos-2@*")[0]
p=Chronos2Pipeline.from_pretrained(d,device_map="cpu",dtype=torch.float32)
out=[]
for tf,H in (("M5",12),("M15",8),("H1",6)):
    t,o,h,l,c=load(tf); orig=origins(t,H)
    preds=[];t0=time.perf_counter()
    for k in range(0,len(orig),64):
        batch=[torch.tensor(c[i-511:i+1],dtype=torch.float32) for i in orig[k:k+64]]
        with torch.inference_mode(): q,m=p.predict_quantiles(batch,prediction_length=H,quantile_levels=[0.5])
        preds+= [float(x[0][H-1,0]) for x in q]
    ms=(time.perf_counter()-t0)*1000/len(orig)
    r=score("chronos2",preds,orig,h,l,c,H); r.update(tf=tf,H=H,ms_per_origin=round(ms,2)); out.append(r); print(r,flush=True)
print("maxrss_mb",resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
json.dump(out,open(os.path.dirname(__file__)+"/res_chronos.json","w"),indent=1)
