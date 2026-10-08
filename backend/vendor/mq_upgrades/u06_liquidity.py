"""06 Observable session + confirmed swing/sweep diagnostics; not true order flow."""
from zoneinfo import ZoneInfo
from .common import candles

def analyze(bars,pivot_left=2,pivot_right=2):
    try:
        if pivot_left<1 or pivot_right<1:raise ValueError('INVALID_PIVOT')
        seq=candles(bars,min_count=pivot_left+pivot_right+5)
        events=[]
        # A swing is only published after right-side candles have closed.
        for k in range(pivot_left,len(seq)-pivot_right):
            window=seq[k-pivot_left:k+pivot_right+1]
            high=seq[k][2];low=seq[k][3]
            is_high=all(high>x[2] for j,x in enumerate(window) if j!=pivot_left)
            is_low=all(low<x[3] for j,x in enumerate(window) if j!=pivot_left)
            if is_high or is_low:
                events.append({'kind':'SWING_HIGH' if is_high else 'SWING_LOW',
                               'level':high if is_high else low,
                               'pivot_time':seq[k][0].isoformat(),
                               'available_at':seq[k+pivot_right][0].isoformat()})
        latest=seq[-1];known=[e for e in events if e['available_at']<latest[0].isoformat()]
        sweeps=[]
        for side in ('SWING_HIGH','SWING_LOW'):
            chosen=next((e for e in reversed(known) if e['kind']==side),None)
            if chosen:
                lev=chosen['level']
                if side=='SWING_HIGH' and latest[2]>lev and latest[4]<lev:
                    sweeps.append({'kind':'POTENTIAL_BUY_SIDE_SWEEP','ref':chosen})
                if side=='SWING_LOW' and latest[3]<lev and latest[4]>lev:
                    sweeps.append({'kind':'POTENTIAL_SELL_SIDE_SWEEP','ref':chosen})
        t=latest[0]
        london=t.astimezone(ZoneInfo('Europe/London'))
        newyork=t.astimezone(ZoneInfo('America/New_York'))
        # These are approximate research windows; broker tick volume != exchange depth.
        return {'status':'PASS','session':{'london_active':8<=london.hour<17,
                  'new_york_active':8<=newyork.hour<17,
                  'london_local':london.isoformat(),'new_york_local':newyork.isoformat()},
                'confirmed_swings':events[-15:],'potential_sweeps':sweeps,
                'real_order_flow_available':False,'execution_permission':'BLOCKED'}
    except (KeyError,ValueError,TypeError,IndexError) as e:
        return {'status':'PENDING','reason':str(e),'execution_permission':'BLOCKED'}
