"""05 Strict heldout reliability for frozen predicted probabilities."""
from .common import when,num

def evaluate(rows,frozen_at,oos_start,min_oos=50,bins=10):
    try:
        if type(min_oos) is not int or min_oos<20:raise ValueError('INVALID_OOS_MINIMUM')
        if type(bins) is not int or bins not in range(2,21):raise ValueError('INVALID_BIN_COUNT')
        freeze=when(frozen_at);oos=when(oos_start)
        if freeze>oos:raise ValueError('MODEL_FROZEN_AFTER_OOS')
        taken=[]
        for r in rows:
            t=when(r['as_of']);p=num(r['predicted_probability']);y=r['outcome']
            if p<0 or p>1 or type(y) is not int or y not in (0,1):raise ValueError('INVALID_PROBABILITY_OR_LABEL')
            if t>=oos:
                if when(r['prediction_recorded_at'])>t:raise ValueError('POSTHOC_PREDICTION')
                taken.append((p,y))
        if len(taken)<min_oos:return {'status':'INSUFFICIENT_OOS','n':len(taken),'calibrated':False,'execution_permission':'BLOCKED'}
        if bins not in range(2,21):raise ValueError('INVALID_BIN_COUNT')
        grouped=[[] for _ in range(bins)]
        for p,y in taken:grouped[min(bins-1,int(p*bins))].append((p,y))
        bs=sum((p-y)**2 for p,y in taken)/len(taken)
        ece=sum(len(b)/len(taken)*abs(sum(p for p,y in b)/len(b)-sum(y for p,y in b)/len(b))
                for b in grouped if b)
        return {'status':'PASS','n':len(taken),'brier':round(bs,6),'ece':round(ece,6),
                'reliability_bins':[{'count':len(b),'mean_predicted':round(sum(p for p,y in b)/len(b),5),
                                      'observed_rate':round(sum(y for p,y in b)/len(b),5)} for b in grouped if b],
                'calibrated':False,'note':'diagnostics only; no auto probability recalibration',
                'execution_permission':'BLOCKED'}
    except (KeyError,ValueError,TypeError) as e:
        return {'status':'NOT_RUN','reason':str(e),'execution_permission':'BLOCKED'}
