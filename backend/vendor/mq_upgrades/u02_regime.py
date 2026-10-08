"""02 Adaptive market regime evidence: closed OHLC only, no model fitting."""
from statistics import median
from .common import candles

def analyze(bars,lookback=30,fast=8,slow=21):
    try:
        if type(lookback) is not int or not 20<=lookback<=200:raise ValueError('INVALID_LOOKBACK')
        if type(slow) is not int or slow<2:raise ValueError('INVALID_SLOW')
        bs=candles(bars,min_count=max(lookback+1,slow+2))
        bs=bs[-(max(lookback,slow)+1):]
        close=[x[4] for x in bs]
        returns=[abs(close[i]-close[i-1]) for i in range(1,len(close))]
        atrs=[max(x[2]-x[3],abs(x[2]-bs[i-1][4]),abs(x[3]-bs[i-1][4])) for i,x in enumerate(bs) if i>0]
        atr=sum(atrs[-14:])/min(14,len(atrs))
        if atr<=0:return {'status':'INSUFFICIENT_VARIATION','regime':'UNKNOWN'}
        net=close[-1]-close[-(lookback+1)]
        path=sum(returns[-lookback:])
        efficiency=abs(net)/path if path>0 else 0
        slope=net/(lookback*atr)
        short_range=median(atrs[-min(7,len(atrs)):])
        long_range=median(atrs)
        volatile=short_range/long_range>=1.8 if long_range>0 else False
        if volatile:regime='VOLATILE'
        elif efficiency>=0.38 and abs(slope)>=0.15:regime='TREND_UP' if net>0 else 'TREND_DOWN'
        else:regime='RANGE'
        return {'status':'PASS','regime':regime,'efficiency':round(efficiency,6),
                'normalized_slope':round(slope,6),'volatility_expansion':round(short_range/long_range,6),
                'direction':'UP' if net>0 else 'DOWN' if net<0 else 'NEUTRAL',
                'as_of':bs[-1][0].isoformat().replace('+00:00','Z'),'evidence_group':'REGIME',
                'execution_permission':'BLOCKED'}
    except (KeyError,ValueError,TypeError,IndexError,ZeroDivisionError) as e:
        return {'status':'PENDING','regime':'UNKNOWN','reason':str(e),'execution_permission':'BLOCKED'}
