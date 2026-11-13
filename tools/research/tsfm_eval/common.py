import json, math
def load(tf):
    b=json.load(open(f"/tmp/claude-0/-home-user-1/e704900f-05d3-5cd0-a027-a6973be977c8/scratchpad/xau/{tf}.json", encoding="utf-8"))
    return [x[0] for x in b],[x[1] for x in b],[x[2] for x in b],[x[3] for x in b],[x[4] for x in b]
def atr14(h,l,c,i):
    trs=[max(h[j]-l[j],abs(h[j]-c[j-1]),abs(l[j]-c[j-1])) for j in range(i-13,i+1)]
    return sum(trs)/14
def origins(t,H,start="2025-10-01",ctx=1024,step=None,n=None):
    step=step or H
    idx=[i for i in range(ctx,len(t)-H,step) if t[i]>=start]
    return idx[:n] if n else idx
def score(name,preds,orig,h,l,c,H):
    ae=[];se=[];nae=[];hits=[];flat=0
    for i,p in zip(orig,preds):
        y=c[i+H]; last=c[i]; band=0.25*atr14(h,l,c,i)
        ae.append(abs(p-y)); se.append((p-y)**2); nae.append(abs(last-y))
        dp=p-last; da=y-last
        pd="UP" if dp>band else "DOWN" if dp<-band else "FLAT"; ad="UP" if da>band else "DOWN" if da<-band else "FLAT"
        if pd=="FLAT": flat+=1
        if pd!="FLAT" and ad!="FLAT": hits.append(int(pd==ad))
    m=lambda x:sum(x)/len(x)
    return {"model":name,"n":len(ae),"mae":round(m(ae),3),"rmse":round(math.sqrt(m(se)),3),"naive_mae":round(m(nae),3),
            "skill_vs_naive":round(1-m(ae)/m(nae),4),"dir_n":len(hits),"dir_hit":round(m(hits),3) if hits else None,"pred_flat":flat}
