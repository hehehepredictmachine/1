"""Shared typed safety helpers. Standard library only."""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite
from hashlib import sha256
import json


def when(x):
    if isinstance(x, datetime): d=x
    elif isinstance(x,str): d=datetime.fromisoformat(x.replace('Z','+00:00'))
    else: raise ValueError('INVALID_TIMESTAMP')
    if d.utcoffset() is None: raise ValueError('NAIVE_TIMESTAMP')
    return d.astimezone(timezone.utc)


def iso(x):return when(x).isoformat().replace('+00:00','Z')

def num(x,positive=False):
    if isinstance(x,bool) or not isinstance(x,(float,int)) or not isfinite(x):
        raise ValueError('NONFINITE_NUMBER')
    if positive and x<=0:raise ValueError('NONPOSITIVE_NUMBER')
    return float(x)

def fingerprint(obj):
    return sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def safe_json(path,obj):
    from pathlib import Path
    from os import replace,fsync,getpid
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.'+str(getpid())+'.tmp')
    try:
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(obj,f,indent=2,ensure_ascii=False,allow_nan=False)
            f.flush();fsync(f.fileno())
        replace(tmp,p)
    finally:tmp.unlink(missing_ok=True)

def candles(bars,min_count=2):
    if not isinstance(bars,list) or len(bars)<min_count:raise ValueError('INSUFFICIENT_BARS')
    last=None;out=[]
    for b in bars:
        if not isinstance(b,dict):raise ValueError('INVALID_BAR')
        t=when(b['time'])
        if last is not None and t<=last:raise ValueError('UNSORTED_OR_DUPLICATE_BARS')
        last=t
        o,h,l,c=(num(b[k]) for k in ('open','high','low','close'))
        if l>min(o,c,h) or h<max(o,c,l) or l>h:raise ValueError('INVALID_OHLC')
        if b.get('closed') is not True:raise ValueError('FORMING_BAR_FORBIDDEN')
        out.append((t,o,h,l,c))
    return out
