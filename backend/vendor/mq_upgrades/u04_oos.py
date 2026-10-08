"""04 Chronological OOS testing; do not mine best OOS result for approval."""
from statistics import mean
from .common import when,num

def validate(trades,dev_end,oos_start,min_oos=50,embargo_seconds=0):
    try:
        if type(min_oos) is not int or min_oos<20:raise ValueError('INVALID_OOS_MINIMUM')
        if type(embargo_seconds) not in (int,float) or embargo_seconds<0:raise ValueError('INVALID_EMBARGO')
        d=when(dev_end);o=when(oos_start)
        if (o-d).total_seconds()<embargo_seconds or o<=d:raise ValueError('EMBARGO_OR_OVERLAP')
        groups={'DEV':[],'OOS':[]};ids=set()
        for tr in trades:
            id=tr['id'];t=when(tr['signal_time']);closed=when(tr['exit_time']);x=num(tr['net_r'])
            if closed<t:raise ValueError('EXIT_BEFORE_SIGNAL')
            if t<d and closed>d:raise ValueError('TRADE_OVERLAPS_DEV_BOUNDARY')
            if t>=o and closed<t:raise ValueError('TRADE_EXIT_INVALID')
            if id in ids:raise ValueError('DUPLICATE_TRADE')
            ids.add(id)
            if t<d:groups['DEV'].append(x)
            elif t>=o:groups['OOS'].append(x)
            else:raise ValueError('EMBARGO_TRADE_PRESENT')
        def stats(a):
            if not a:return {'trades':0,'avg_r':None,'win_rate':None,'profit_factor':None}
            pos=sum(x for x in a if x>0);loss=-sum(x for x in a if x<0)
            return {'trades':len(a),'avg_r':round(mean(a),5),
                    'win_rate':round(sum(x>0 for x in a)/len(a),5),
                    'profit_factor':round(pos/loss,5) if loss else None}
        summary={k:stats(v) for k,v in groups.items()}
        eligible=len(groups['OOS'])>=min_oos
        return {'status':'PASS' if eligible else 'INSUFFICIENT_OOS',
                'metrics':summary,'promotion_allowed':False,'unadjusted_selection_bias':True,
                'reason':None if eligible else 'MINIMUM_OOS_SAMPLE_NOT_MET',
                'execution_permission':'BLOCKED'}
    except (KeyError,ValueError,TypeError) as e:
        return {'status':'NOT_RUN','reason':str(e),'execution_permission':'BLOCKED'}
