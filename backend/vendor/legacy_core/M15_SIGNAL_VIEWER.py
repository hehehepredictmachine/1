"""Read-only simple Tkinter monitor for the M15 snapshot JSON.
Only local file IO; refreshes visible state and never sends trades/alerts.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

ROOT=Path(__file__).resolve().parent
SNAP=ROOT/'runtime/M15/M15_MONITOR_SNAPSHOT.json'

class Viewer:
    def __init__(self,filepath=SNAP):
        self.filepath=Path(filepath)
        self.root=tk.Tk();self.root.title('MasterQUO — M10A/M15 | READ ONLY')
        self.root.geometry('830x540')
        self.status=tk.StringVar(value='Czekanie na dane MT5')
        ttk.Label(self.root,text='MASTERQUO — ALERTY ANALITYCZNE / BEZ HANDLU',font=('Segoe UI',15,'bold')).pack(pady=12)
        ttk.Label(self.root,textvariable=self.status,font=('Segoe UI',11)).pack(pady=5)
        self.text=tk.Text(self.root,wrap='word',font=('Consolas',10),state='disabled')
        self.text.pack(fill='both',expand=True,padx=12,pady=12)
        self.root.after(200, self.tick)
    def tick(self):
        try:
            r=json.loads(self.filepath.read_text(encoding='utf-8'))
            stamp=datetime.fromisoformat(r['m15_published_at'].replace('Z','+00:00'))
            age=(datetime.now(timezone.utc)-stamp).total_seconds()
            if stamp.tzinfo is None or age<0 or age>15:
                raise ValueError('OLD_MONITOR_HEARTBEAT')
            from M10A_M15_ADAPTER import short_report
            s=short_report(r)
            s+='\n\nStatus MT5: '+str(r.get('m10a_connection_status'))
            s+='\nKwotowanie: '+str(r.get('m10a_quote_status'))
            s+='\nOstatni etap M10: '+str(r.get('m10a_setup_state'))
            s+='\nPowiadomienia: '+str(r.get('delivery_status'))
            tfs=r.get('indicator_timeframes') or {}
            if tfs:
                s+='\n\nWSKAŹNIKI MT5 (DIAGNOSTYKA — NIE ROZKAZ BUY/SELL):'
                for tf in ('D1','H4','H1','M15','M5','M1'):
                    item=tfs.get(tf)
                    if not isinstance(item,dict):continue
                    measurements=item.get('indicators') or {}
                    values=', '.join(f'{k}={v:.3f}' for k,v in measurements.items()
                                      if isinstance(v,(int,float)) and not isinstance(v,bool))
                    s+=f'\n{tf}: {item.get("status")} / {item.get("market_direction")}  {values}'
            self.status.set('DECYZJA: '+r['decision']+' | WYKONANIE: BLOCKED')
        except (OSError,ValueError,KeyError,TypeError):
            s='Brak aktualnego raportu M15. Nie należy traktować wcześniejszych danych jako aktualnego sygnału.'
            self.status.set('BRAK DANYCH — NO_TRADE / BLOCKED')
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',s)
        self.text.configure(state='disabled');self.root.after(1500,self.tick)
    def run(self):self.root.mainloop()

if __name__=='__main__':Viewer(Path(sys.argv[1]) if len(sys.argv)>1 else SNAP).run()
