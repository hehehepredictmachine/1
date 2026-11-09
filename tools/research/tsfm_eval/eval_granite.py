import sys, json, time, os, resource
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, torch
from common import *
from tsfm_public.models.tinytimemixer import TinyTimeMixerForPrediction
torch.set_num_threads(4)
R="/tmp/claude-0/-home-user-1/e704900f-05d3-5cd0-a027-a6973be977c8/scratchpad/ttm/"
FREQ={"M5":3,"M15":5,"H1":7}
out=[]
for tf,H in (("M5",12),("M15",8),("H1",6)):
    t,o,h,l,c=load(tf); orig=origins(t,H)
    for rev in ("main","512-48-ft-r2.1","512-96-ft-r2.1","1024-96-r2"):
        m=TinyTimeMixerForPrediction.from_pretrained(R+rev).eval(); ctx=m.config.context_length
        X=np.stack([np.array(c[i-ctx+1:i+1],dtype=np.float64) for i in orig])
        mu=X.mean(1,keepdims=True); sd=X.std(1,keepdims=True)+1e-8
        Z=torch.tensor(((X-mu)/sd)[:,:,None],dtype=torch.float32)
        kw={}
        if m.config.resolution_prefix_tuning: kw["freq_token"]=torch.full((len(orig),),FREQ[tf],dtype=torch.long)
        t0=time.perf_counter()
        with torch.inference_mode(): y=m(past_values=Z,**kw).prediction_outputs[:,:,0].numpy()
        ms=(time.perf_counter()-t0)*1000/len(orig)
        P=y*sd+mu
        r=score("granite:"+rev,list(P[:,H-1]),orig,h,l,c,H); r.update(tf=tf,H=H,ms_per_origin=round(ms,2),params=sum(p.numel() for p in m.parameters()))
        out.append(r); print(r, flush=True)
    r=score("naive_last",[c[i] for i in orig],orig,h,l,c,H); r.update(tf=tf,H=H); out.append(r); print(r)
    r=score("drift_20",[c[i]+(c[i]-c[i-20])/20*H for i in orig],orig,h,l,c,H); r.update(tf=tf,H=H); out.append(r); print(r)
print("maxrss_mb",resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
json.dump(out,open(os.path.dirname(__file__)+"/res_granite.json","w"),indent=1)
