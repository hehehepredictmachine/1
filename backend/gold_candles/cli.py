from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from .analysis import analyze
from .data import Config, DataError, clean_json, read_csv, utc, validate_bars, write_json
from .model import load_model, train
from .mt5_reader import read_mt5


def demo_bars(n=240,seed=17,start="2026-01-05T00:00:00Z"):
    rng=np.random.default_rng(seed)
    changes=rng.normal(0,.55,n)
    close=4140+np.cumsum(changes)
    opened=np.r_[4140,close[:-1]]
    high=np.maximum(opened,close)+rng.uniform(.08,.80,n)
    low=np.minimum(opened,close)-rng.uniform(.08,.80,n)
    frame=pd.DataFrame(dict(time_open_utc=pd.date_range(start,periods=n,freq="5min"),
                            open=opened,high=high,low=low,close=close,
                            tick_volume=rng.integers(20,150,n)))
    return validate_bars(frame,5,frame.time_open_utc.iloc[-1]+pd.Timedelta(minutes=5))


def emit(payload,path=None):
    if path:
        write_json(path,payload)
    else:
        print(json.dumps(clean_json(payload),ensure_ascii=False,indent=2,allow_nan=False))


def from_files(args):
    config=Config(symbol=args.symbol,tick_size=args.tick_size)
    m5=read_csv(args.m5,5,args.as_of,args.symbol)
    m30=read_csv(args.m30,30,args.as_of,args.symbol) if args.m30 else None
    return m5,m30,config


def build_parser():
    parser=argparse.ArgumentParser(description="MasterQUO candle analysis; read-only XAUUSD, no orders.")
    sub=parser.add_subparsers(dest="command",required=True)
    demo=sub.add_parser("demo",help="Clearly synthetic morphology demonstration; no trained forecast.")
    demo.add_argument("--output")
    for name in ("analyze","train"):
        p=sub.add_parser(name)
        p.add_argument("--m5",required=True)
        p.add_argument("--m30")
        p.add_argument("--symbol",choices=("XAUUSD","XAUUSD-"),default="XAUUSD-")
        p.add_argument("--tick-size",type=float,default=.01)
        p.add_argument("--as-of",help="UTC ISO timestamp; default current UTC. Forming bars are excluded.")
        if name=="analyze":
            p.add_argument("--model")
            p.add_argument("--mode",choices=("REPLAY","LIVE"),default="REPLAY")
            p.add_argument("--output")
        else:
            p.add_argument("--output-dir",required=True)
            p.add_argument("--trees",type=int,default=80)
            p.add_argument("--data-kind",choices=("REAL_USER_DATA","SYNTHETIC_TEST"),default="REAL_USER_DATA")
    for name in ("mt5-once","mt5-watch","export-mt5"):
        p=sub.add_parser(name)
        p.add_argument("--symbol",choices=("XAUUSD","XAUUSD-"),default="XAUUSD-")
        p.add_argument("--count",type=int,default=3000)
        if name=="export-mt5":
            p.add_argument("--output-dir",required=True)
        else:
            p.add_argument("--model")
            if name=="mt5-once":p.add_argument("--output")
            else:p.add_argument("--interval",type=float,default=1)
    return parser


def main(argv=None):
    args=build_parser().parse_args(argv)
    try:
        if args.command=="demo":
            m5=demo_bars()
            from .data import aggregate_m30
            m30=aggregate_m30(m5)
            emit(analyze(m5,m30,as_of=m5.time_close_utc.iloc[-1],mode="SYNTHETIC_DEMO"),args.output)
        elif args.command in ("analyze","train"):
            m5,m30,config=from_files(args)
            if args.command=="analyze":
                model=load_model(args.model) if args.model else None
                emit(analyze(m5,m30,config,model,args.as_of,args.mode),args.output)
            else:
                artifact,report=train(m5,m30,config,args.trees,args.data_kind)
                out=Path(args.output_dir)
                write_json(out/"forecast_model.json",artifact)
                write_json(out/"forecast_validation.json",report)
                emit(dict(status="RESEARCH_MODEL_CREATED",model=str(out/"forecast_model.json"),
                          report=str(out/"forecast_validation.json"),execution_permission=False))
        elif args.command=="export-mt5":
            m5,m30,config,quote,now=read_mt5(args.symbol,args.count)
            out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
            for name,frame in (("M5",m5),("M30",m30)):
                exported=frame[["time_open_utc","open","high","low","close","tick_volume"]].copy()
                exported["symbol"]=config.symbol
                exported.to_csv(out/f"XAUUSD_{name}.csv",index=False)
            write_json(out/"source_metadata.json",dict(config=config.__dict__,source="MT5_POS_1_CLOSED_BARS",as_of=now.isoformat(),quote=quote))
            emit(dict(status="EXPORTED_CLOSED_BARS",directory=str(out),tick_size=config.tick_size,
                      note="Use this exact tick size and both CSV files for training; 3000 bars are a technical minimum, not sufficient economic history."))
        else:
            model=load_model(args.model) if args.model else None
            last_key=None
            seen={}
            while True:
                m5,m30,config,quote,now=read_mt5(args.symbol,args.count)
                revision=False
                current={}
                for tf,frame in ((5,m5),(30,m30)):
                    for row in frame.itertuples():
                        key=(tf,row.time_open_utc.isoformat())
                        value=(row.open,row.high,row.low,row.close)
                        if key in seen and seen[key]!=value:revision=True
                        current[key]=value
                seen=current
                key=(m5.time_close_utc.iloc[-1].isoformat(),m30.time_close_utc.iloc[-1].isoformat())
                if revision:
                    emit(dict(status="CLOSED_BAR_REVISION_DETECTED",execution_lock="BLOCKED",
                              forecast=None,note="Restart only after investigating and replaying corrected history."))
                    return 3
                if key!=last_key:
                    emit(analyze(m5,m30,config,model,now,"LIVE",quote),getattr(args,"output",None))
                    last_key=key
                if args.command=="mt5-once":break
                time.sleep(max(.2,args.interval))
    except KeyboardInterrupt:
        return 0
    except (DataError,ValueError,OSError,KeyError,TypeError) as error:
        emit(dict(status="BLOCKED",error=str(error),forecast=None,execution_permission=False))
        return 2
    return 0


if __name__=="__main__":
    sys.exit(main())

