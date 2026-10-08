"""10 Evidence-led explainability. Display only, cannot weaken source gates."""
from .common import fingerprint,iso

def explain(as_of,inputs,technical_decision='WAIT',notes=None):
    if technical_decision not in ('LONG','SHORT','EARLY','WAIT','NO_TRADE'):
        technical_decision='NO_TRADE'
    names=['runtime','regime','execution','oos','calibration','liquidity','cross_market','surprise','learning']
    missing=[x for x in names if x not in inputs]
    blockers=[]
    runtime=inputs.get('runtime',{})
    if runtime.get('system_state')!='RUNNING_DIAGNOSTIC':blockers.append('RUNTIME_NOT_HEALTHY')
    for name in missing:blockers.append('INPUT_MISSING_'+name.upper())
    for name,record in inputs.items():
        if not isinstance(record,dict):blockers.append('INVALID_'+name.upper());continue
        if record.get('execution_permission','BLOCKED')!='BLOCKED':blockers.append('AUTHORITY_VIOLATION_'+name.upper())
        if name in ('regime','liquidity','cross_market','surprise','execution') and record.get('status')!='PASS':
            blockers.append('EVIDENCE_INCOMPLETE_'+name.upper())
    # An explanation cannot replace M14 approval; always report research-only decision.
    status='DIAGNOSTIC' if not blockers else 'BLOCKED'
    out={'module_id':'M00U10','schema_version':'2.0.0','as_of':iso(as_of),
         'technical_decision_observed':technical_decision,
         'display_decision':'WAIT' if status=='DIAGNOSTIC' else 'NO_TRADE',
         'system_status':status,'gates':{key:val.get('status','UNKNOWN') if isinstance(val,dict) else 'INVALID'
                                    for key,val in inputs.items()},
         'reason_codes':blockers or ['RESEARCH_ONLY_NOT_CERTIFIED'],
         'research_only':True,'execution_permission':'BLOCKED',
         'execution_eligible':False,'probability_claim':None,
         'notes':notes or [], 'source_hash':fingerprint(inputs)}
    return out
