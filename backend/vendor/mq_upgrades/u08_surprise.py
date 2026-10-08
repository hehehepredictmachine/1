"""08 Point-in-time macro surprise, with release and forecast availability audit."""
from .common import when,num

def analyze(events,as_of,shock_baselines=None):
    try:
        now=when(as_of);out=[];shock_baselines=shock_baselines or {}
        if not events:return {'status':'PENDING','reason':'NO_MACRO_EVENT_ARCHIVE','events':[],'execution_permission':'BLOCKED'}
        seen=set()
        for event in events:
            eid=event['event_id']
            if eid in seen:raise ValueError('DUPLICATE_MACRO_EVENT')
            seen.add(eid)
            scheduled=when(event['scheduled_at']);known=when(event['schedule_first_seen_at'])
            if known>now:continue
            row={'event_id':eid,'event_type':event.get('type','OTHER'),
                 'scheduled_at':scheduled.isoformat(),'forecast_available':False,
                 'actual_available':False,'surprise':None,'status':'UPCOMING' if scheduled>now else 'UNVERIFIED'}
            pred_at=event.get('forecast_recorded_at')
            actual_at=event.get('actual_published_at')
            if pred_at and when(pred_at)<=min(now,scheduled):
                forecast=num(event['forecast']);row['forecast_available']=True
            else:forecast=None
            if actual_at and when(actual_at)<=now and when(actual_at)>=scheduled:
                actual=num(event['actual']);row['actual_available']=True
            else:actual=None
            if forecast is not None and actual is not None:
                row['absolute_surprise']=round(actual-forecast,9)
                baseline=shock_baselines.get(event.get('type'))
                if baseline is not None and num(baseline,True)>0:
                    row['surprise']=round((actual-forecast)/baseline,6)
                    row['status']='NORMALIZED'
                else:row['status']='ABSOLUTE_ONLY'
            out.append(row)
        return {'status':'PASS','events':out,'execution_permission':'BLOCKED'}
    except (KeyError,TypeError,ValueError) as e:
        return {'status':'PENDING','reason':str(e),'execution_permission':'BLOCKED'}
