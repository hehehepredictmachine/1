import csv, json, sys
from datetime import datetime
rows=[]
for fn in ("m1_2025.csv","m1_202601.csv"):
    for r in csv.reader(open(fn, encoding="utf-8")):
        t=datetime.strptime(r[0]+" "+r[1],"%Y.%m.%d %H:%M")
        rows.append((t,float(r[2]),float(r[3]),float(r[4]),float(r[5])))
rows.sort()
def agg(mins):
    out=[];cur=None
    for t,o,h,l,c in rows:
        k=t.replace(minute=(t.minute//mins)*mins) if mins<60 else t.replace(minute=0)
        if cur and cur[0]==k: cur[2]=max(cur[2],h);cur[3]=min(cur[3],l);cur[4]=c
        else:
            if cur: out.append(cur)
            cur=[k,o,h,l,c]
    out.append(cur); return out
for name,m in (("M5",5),("M15",15),("H1",60)):
    b=agg(m); json.dump([[x[0].isoformat(),x[1],x[2],x[3],x[4]] for x in b],open(f"{name}.json","w", encoding="utf-8"))
    print(name,len(b),b[0][0],b[-1][0])
