"""07 Cross-market alignment, as-of join only; no fixed DXY/XAU relationship."""
from .common import when,num
from math import sqrt

def analyze(series,as_of,max_delay_seconds=7200,min_pairs=12):
    try:
        now=when(as_of)
        aligned={}
        for name,items in series.items():
            if not isinstance(items,list):raise ValueError('INVALID_SERIES')
            points=[];last=None
            for row in items:
                t=when(row['time']);v=num(row['close'],True)
                if last and t<=last:raise ValueError('UNSORTED_SERIES')
                last=t
                if t<=now:points.append((t,v))
            if not points or (now-points[-1][0]).total_seconds()>max_delay_seconds:
                aligned[name]={'status':'STALE_OR_MISSING'}
            else:aligned[name]={'status':'PASS','last':points[-1][1], 'points':points}
        if 'XAUUSD' not in aligned or aligned['XAUUSD']['status']!='PASS':
            raise ValueError('XAU_BASE_MISSING')
        base={t:v for t,v in aligned['XAUUSD']['points']}
        out={}
        if len(aligned)<=1:
            return {'status':'PENDING','reason':'NO_SECONDARY_MARKET','markets':{},'execution_permission':'BLOCKED'}
        for name,item in aligned.items():
            if name=='XAUUSD':continue
            if item['status']!='PASS':out[name]={'status':item['status']};continue
            other={t:v for t,v in item['points']}
            common=sorted(set(base)&set(other))
            a=[];b=[]
            for prev,curr in zip(common,common[1:]):
                a.append(base[curr]/base[prev]-1)
                b.append(other[curr]/other[prev]-1)
            if len(a)<min_pairs:
                out[name]={'status':'INSUFFICIENT_PAIRS','n':len(a)};continue
            ma=sum(a)/len(a);mb=sum(b)/len(b)
            va=sum((v-ma)**2 for v in a);vb=sum((v-mb)**2 for v in b)
            if va==0 or vb==0:out[name]={'status':'ZERO_VARIANCE','n':len(a)};continue
            corr=sum((x-ma)*(y-mb) for x,y in zip(a,b))/sqrt(va*vb)
            out[name]={'status':'PASS','n':len(a),'sample_correlation':round(corr,6),
                       'last_return':round(b[-1],8),'note':'descriptive; does not prove causality'}
        return {'status':'PASS' if any(x.get('status')=='PASS' for x in out.values()) else 'PENDING',
                'markets':out,'execution_permission':'BLOCKED'}
    except (KeyError,ValueError,TypeError,ZeroDivisionError) as e:
        return {'status':'PENDING','reason':str(e),'execution_permission':'BLOCKED'}
