"""Persistent local research-plan selection for unmodified M03E/M10A/M15.

The SQLite lock is NOT an M08 registry. It only prevents setup identity churn
when polling the same market. It does not authorize orders or Telegram sends.
"""
from __future__ import annotations
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from M07_M03E_PROFILE_DETECTOR import (discover,hashed,_bars,_age_closed_bars,
                                     utc,read_config,GOOD)
from vendor.M03.M03_REFERENCE_ENGINE import early_assessment
from M03E_M10_PIPELINE import construct_early

class ResearchPlanLock:
    def __init__(self, filename, config=None):
        self.db=Path(filename)
        self.db.parent.mkdir(parents=True,exist_ok=True)
        self.config=config or read_config()
        with closing(sqlite3.connect(self.db,timeout=10)) as con:
            con.execute('CREATE TABLE IF NOT EXISTS research_plan_lock('
                'symbol TEXT NOT NULL,mode TEXT NOT NULL,plan_json TEXT NOT NULL,plan_hash TEXT NOT NULL,'
                'PRIMARY KEY(symbol,mode))')

    def _is_valid_old(self,plan, snap, market, m03, mode):
        if not isinstance(plan,dict):return False
        name=plan.get('profile_name')
        if name not in self.config['profiles']:return False
        if mode!='AUTO' and name!=mode:return False
        template={**self.config['profiles'][name],'algorithm':'OP_DETECTOR_1.0.0','mode':name}
        if plan.get('spec_hash')!=hashed(template):return False
        if plan.get('frozen_plan_hash')!=hashed({k:v for k,v in plan.items() if k!='frozen_plan_hash'}):
            return False
        tf=plan.get('setup_tf');bars=_bars(snap,tf)
        if not bars:return False
        age=_age_closed_bars(bars,plan.get('created_at'))
        if age is None or age>self.config['profiles'][name]['max_fvg_age_bars']:
            return False
        location=plan.get('location_evidence_id')
        fvgs=(m03.get('timeframes') or {}).get(tf,{}).get('fvgs') or []
        valid_fvg=next((f for f in fvgs if f.get('event_id')==location),None)
        frozen_geometry=plan.get('source_fvg_geometry') or {}
        if (valid_fvg and any(valid_fvg.get(k)!=frozen_geometry.get(k)
                              for k in ('zone_low','zone_high','formed_at'))):
            return False
        if (not valid_fvg or valid_fvg.get('direction') !=
            ('BULLISH' if plan.get('intended_direction')=='LONG' else 'BEARISH') or
            not isinstance(valid_fvg.get('mitigated_fraction'),(int,float)) or
            valid_fvg['mitigated_fraction']>self.config['profiles'][name]['max_mitigation_fraction']):
            return False
        last=bars[-1]['close'];inv=plan.get('invalidation',{}).get('condition',{})
        stop=inv.get('level')
        if not isinstance(stop,(int,float)):return False
        if plan.get('intended_direction')=='LONG' and last<=stop:return False
        if plan.get('intended_direction')=='SHORT' and last>=stop:return False
        a=early_assessment(m03,market,plan)
        if a.get('status')!='EARLY_SETUP':return False
        early,_=construct_early({**m03,'early_evidence':a},market,snap,plan)
        return early is not None

    def choose(self,snap,market,m03,mode='AUTO'):
        fresh=discover(snap,market,m03,mode=mode,config=self.config)
        symbol=snap.get('exact_symbol') or ''
        if (not symbol or (snap.get('analysis_gate') or {}).get('status') not in GOOD or
            market.get('status') not in GOOD or m03.get('status') not in GOOD or
            snap.get('snapshot_id') != market.get('snapshot_id') or
            snap.get('snapshot_id') != m03.get('snapshot_id')):
            return None,fresh
        with closing(sqlite3.connect(self.db,timeout=10,isolation_level=None)) as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                row=con.execute('SELECT plan_json,plan_hash FROM research_plan_lock WHERE symbol=? AND mode=?',
                                (symbol,mode)).fetchone()
                old=None
                if row:
                    try:
                        candidate=json.loads(row[0])
                        if hashed(candidate)==row[1] and self._is_valid_old(candidate,snap,market,m03,mode):
                            old=candidate
                    except (ValueError,TypeError,KeyError):pass
                if old:
                    fresh['selected_plan']=old
                    fresh['candidate_status']='RESEARCH_HYPOTHESIS_LOCKED'
                    fresh['selection_reason']='PERSISTENT_SAME_SETUP_ID'
                    result=old
                else:
                    result=fresh.get('selected_plan')
                    if row and result:
                        try:
                            previous=json.loads(row[0])
                            if (previous.get('created_event_id')==result.get('created_event_id') and
                                previous.get('frozen_plan_hash')!=result.get('frozen_plan_hash')):
                                fresh['candidate_status']='BLOCKED_REVIEW_REQUIRED'
                                fresh['reason_codes'].append('SAME_EVENT_NEW_RULES_REQUIRES_NEW_RESEARCH_EVENT')
                                result=None
                        except (TypeError,ValueError,AttributeError):
                            result=None
                            fresh['reason_codes'].append('LOCK_CORRUPT_REQUIRES_MANUAL_REVIEW')
                    if result:
                        encoded=json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False)
                        con.execute('INSERT OR REPLACE INTO research_plan_lock VALUES(?,?,?,?)',
                                    (symbol,mode,encoded,hashed(result)))
                    else:
                        con.execute('DELETE FROM research_plan_lock WHERE symbol=? AND mode=?',(symbol,mode))
                con.execute('COMMIT')
            except Exception:
                con.execute('ROLLBACK');raise
        return copy.deepcopy(result),fresh
