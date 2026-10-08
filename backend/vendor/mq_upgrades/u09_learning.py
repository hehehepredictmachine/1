"""09 Constrained research proposals, never auto-apply to LIVE strategy."""
from .common import fingerprint,num,when

ALLOWED={'regime_efficiency_threshold':(0.2,0.65),
         'news_block_pre_minutes':(15,120),
         'news_block_post_minutes':(5,90),
         'max_cost_to_stop_ratio':(0.02,0.5)}

def propose(current,candidate,dev_report,oos_report=None,as_of=None):
    try:
        if set(candidate)!=set(current):raise ValueError('PARAMETER_SET_CHANGED')
        delta={}
        for name,value in candidate.items():
            if name not in ALLOWED:raise ValueError('UNAPPROVED_PARAMETER:'+name)
            lower,upper=ALLOWED[name]
            v=num(value);old=num(current[name])
            if not lower<=v<=upper or not lower<=old<=upper:raise ValueError('PARAM_OUT_OF_RANGE')
            if v!=old:delta[name]={'before':old,'proposed':v}
        if not delta:raise ValueError('NO_CHANGE')
        if dev_report.get('status')!='PASS' or dev_report.get('net_sample_size',0)<50:
            raise ValueError('UNVERIFIED_DEV_PERFORMANCE')
        if as_of is not None and when(as_of)<when(dev_report['evaluated_at']):
            raise ValueError('FUTURE_DEVELOPMENT_REPORT')
        return {'status':'REVIEW_REQUIRED','proposal_id':fingerprint([current,candidate,dev_report])[:24],
                'changes':delta,'source':'DEVELOPMENT_RESEARCH',
                'oos_status':oos_report.get('status') if isinstance(oos_report,dict) else 'NOT_RUN',
                'approval_required':True,'applied':False,'auto_promotion_enabled':False,
                'execution_permission':'BLOCKED',
                'required_next_steps':['PREREGISTER','INDEPENDENT_OOS','FORWARD_DEMO','HUMAN_APPROVAL']}
    except (KeyError,TypeError,ValueError) as e:
        return {'status':'REJECTED','reason':str(e),'applied':False,'execution_permission':'BLOCKED'}
