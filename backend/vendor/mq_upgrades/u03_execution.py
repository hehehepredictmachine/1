"""03 Research-only broker quote execution quality and cost sensitivity.
Bid/ask and contract economics must be supplied, not assumed zero.
"""
from .common import when,num

def estimate(quote,side,lots,commission_per_lot_side,money_per_price_unit_per_lot,
             slippage_price,stop_distance=None,target_distance=None,max_quote_age=5,as_of=None):
    try:
        if side not in ('LONG','SHORT'):raise ValueError('INVALID_SIDE')
        t=when(quote['time']);now=when(as_of) if as_of else t
        age=(now-t).total_seconds()
        if age<0 or age>max_quote_age:raise ValueError('STALE_OR_FUTURE_QUOTE')
        bid=num(quote['bid'],True);ask=num(quote['ask'],True)
        if ask<bid:raise ValueError('CROSSED_MARKET')
        lots=num(lots,True);commission=num(commission_per_lot_side)
        value=num(money_per_price_unit_per_lot,True);slip=num(slippage_price)
        if commission<0 or slip<0:raise ValueError('NEGATIVE_COST')
        spread=ask-bid
        slippage_roundtrip=2*slip
        commission_roundtrip=2*commission*lots
        spread_cost=spread*value*lots
        slippage_cost=slippage_roundtrip*value*lots
        total=spread_cost+slippage_cost+commission_roundtrip
        r={'status':'PASS','side':side,'spread_price':round(spread,8),
           'spread_cost':round(spread_cost,6),'slippage_cost':round(slippage_cost,6),
           'commission_roundtrip':round(commission_roundtrip,6),
           'estimated_cost_roundtrip':round(total,6), 'quote_age_s':age,
           'execution_permission':'BLOCKED','note':'scenario estimate; not an execution fill'}
        if stop_distance is not None or target_distance is not None:
            stop=num(stop_distance,True);target=num(target_distance,True)
            stop_money=stop*value*lots
            r['net_reward_risk_estimate']=round((target*value*lots-total)/(stop_money+total),6)
        return r
    except (KeyError,TypeError,ValueError) as e:
        return {'status':'NOT_RUN','reason':str(e),'execution_permission':'BLOCKED'}


def stress(quote,side,lots,commission,value,slippage,slippage_multipliers=(1,2,3)):
    results=[]
    for k in slippage_multipliers:
        r=estimate(quote,side,lots,commission,value,slippage*k)
        r['slippage_multiplier']=k
        results.append(r)
    return results
