"""Single-process M01/M02/M02I/M03/M09/M10A/M14/M15 diagnostic monitor.
No order execution. Telegram only after explicit --telegram-send and env vars.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time
from M02I_M01_M02_LIVE_BRIDGE import IntegratedReadOnlyMonitor
from RUN_MT5_AUTOMATIC_TRIGGER_READONLY import publish as publish_m10, decision_from_auto
from M02I_M01_M02_LIVE_BRIDGE import atomic_json
from M03E_M10_PIPELINE import load
from M10A_M15_ADAPTER import render

ROOT=Path(__file__).resolve().parent

def run(args,mt5):
    settings=load(args.settings)
    settings['full_refresh_seconds']=min(settings['full_refresh_seconds'],10.0)
    if args.bars:settings['history_closed_bars']=args.bars
    mon=IntegratedReadOnlyMonitor(mt5,args.symbol,settings,
      load(args.m02_profile),load(args.m02i_profile),args.raw_monitor_file,
      dxy_symbol=args.dxy_symbol)
    plan=load(args.strategy_plan) if args.strategy_plan else None
    started=time.monotonic();next_try=0.0;next_quote=next_bar=next_full=0.0;attempt=0
    def output():
        upstream=publish_m10(mon,args.upstream_file,args.state_db,plan)
        # The upstream M10A pipeline omits analysis_id from its outer wrapper.
        # Bind it to the *actual in-process MT5 snapshot*, not external JSON.
        if (mon.connected and isinstance(mon.snapshot,dict) and
            upstream.get('snapshot_id')==mon.snapshot.get('snapshot_id') and
            upstream.get('as_of')==mon.snapshot.get('as_of')):
            upstream['analysis_id']=mon.snapshot.get('analysis_id')
            auto=upstream.get('auto_trigger') or {}
            if auto.get('status')=='PASS_WITH_LIMITATIONS' and auto.get('validated_record'):
                decision=decision_from_auto(upstream,auto)
                if decision is not None:
                    upstream['decision_result']=decision
                    upstream['analysis_decision']=decision['decision']
                    upstream['intended_direction']=decision['intended_direction']
                    upstream['signal_tier']=decision['signal_tier']
                    upstream['signal_validity']=decision['signal_validity']
            atomic_json(args.upstream_file,upstream)
        result=render(upstream,args.output_dir,telegram_enabled=args.telegram_send)
        print(upstream.get('published_at'),result['payload']['decision'],
            result['payload']['m10a_setup_state'],result['delivery']['delivery_status'],
            'EXECUTION=BLOCKED',flush=True)
    try:
        while args.duration_seconds is None or time.monotonic()-started<args.duration_seconds:
            t=time.monotonic()
            if not mon.connected:
                if t>=next_try:
                    if mon.start(args.terminal_path):
                        attempt=0;next_quote=next_bar=t;next_full=t+settings['full_refresh_seconds']
                    else:
                        attempt+=1;next_try=t+min(30,2**min(attempt,5))
                output()
            elif t>=next_quote or t>=next_bar or t>=next_full:
                if t>=next_full:
                    try:mon.refresh()
                    except (ValueError,TypeError,KeyError,RuntimeError) as exc:
                        mon.disconnect('REFRESH_FAILED_'+type(exc).__name__)
                    next_full=t+settings['full_refresh_seconds']
                if mon.connected:mon.poll(check_bars=t>=next_bar)
                if t>=next_quote:next_quote=t+settings['quote_poll_seconds']
                if t>=next_bar:next_bar=t+settings['bar_poll_seconds']
                output()
            time.sleep(.1)
    except KeyboardInterrupt:
        pass
    finally:
        mon.disconnect('STOPPED_BY_USER')
        # Last monitor render is necessarily blocked on disconnection.
        output()
    return 0

def main(argv=None):
    ap=argparse.ArgumentParser(description='MasterQUO MT5 + M10A + M15 (READ ONLY)')
    ap.add_argument('--symbol',default='XAUUSD');ap.add_argument('--dxy-symbol',default=None)
    ap.add_argument('--terminal-path',default=None);ap.add_argument('--duration-seconds',type=float,default=None)
    ap.add_argument('--bars',type=int,default=None)
    ap.add_argument('--settings',default=str(ROOT/'BRIDGE_SETTINGS.example.json'))
    ap.add_argument('--m02-profile',default=str(ROOT/'vendor/M02/M02_PROFILE.example.json'))
    ap.add_argument('--m02i-profile',default=str(ROOT/'vendor/M02I/M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json'))
    ap.add_argument('--strategy-plan',default=None,help='Frozen tested strategy rules; do NOT use synthetic examples live')
    ap.add_argument('--upstream-file',default=str(ROOT/'runtime/M10A_UPSTREAM_MONITOR.json'))
    ap.add_argument('--raw-monitor-file',default=str(ROOT/'runtime/MT5_RAW_DIAGNOSTIC.json'))
    ap.add_argument('--state-db',default=str(ROOT/'runtime/M10_STATE.sqlite'))
    ap.add_argument('--output-dir',default=str(ROOT/'runtime/M15'))
    ap.add_argument('--telegram-send',action='store_true',help='Explicit opt-in: ANALYTICAL alerts only; NO trading orders')
    args=ap.parse_args(argv)
    try:import MetaTrader5 as mt5
    except ImportError:
        print('Windows: py -3 -m pip install MetaTrader5 numpy',file=sys.stderr);return 2
    return run(args,mt5)

if __name__=='__main__':raise SystemExit(main())
