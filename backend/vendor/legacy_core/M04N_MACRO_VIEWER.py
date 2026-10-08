"""Local M04N+M15 read-only viewer. Tkinter bundled with many Python installs."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk
ROOT=Path(__file__).resolve().parent
DEFAULT=ROOT/'runtime'/'M04N_GUARDED_MONITOR.json'

class Viewer:
    def __init__(self,file=DEFAULT):
        self.file=Path(file)
        self.root=tk.Tk();self.root.title('MasterQUO — XAUUSD | MAKRO + MT5 | READ ONLY')
        self.root.geometry('1050x720')
        self.status=tk.StringVar(value='Oczekiwanie na aktualne dane. WYKONANIE: BLOCKED')
        ttk.Label(self.root,text='MASTERQUO — ANALIZA TECHNICZNA + KALENDARZ MAKRO',font=('Segoe UI',15,'bold')).pack(pady=12)
        ttk.Label(self.root,textvariable=self.status,font=('Segoe UI',11)).pack(pady=7)
        self.panel=tk.Text(self.root,wrap='word',font=('Consolas',10))
        self.panel.pack(fill='both',expand=True,padx=12,pady=8)
        self.panel.config(state='disabled')
        self.root.after(500,self.tick)
    def tick(self):
        try:
            report=json.loads(self.file.read_text(encoding='utf-8'))
            t=datetime.fromisoformat(report['as_of'].replace('Z','+00:00'))
            age=(datetime.now(timezone.utc)-t).total_seconds()
            if t.tzinfo is None or not 0<=age<=12:raise ValueError('STALE_REPORT')
            if report.get('execution_permission')!='BLOCKED':raise ValueError('EXECUTION_GATE')
            macro=report.get('m04_calendar_context') or {}
            lines=[
              'KIERUNEK TECHNICZNY M14 (KONTEKST): '+str(report.get('m14_original_decision') or 'BRAK'),
              'DECYZJA Z OCHRONĄ MAKRO: '+str(report.get('guarded_display_decision')),
              'BLOKADA MAKRO: '+str(report.get('macro_gate')),
              'RYZYKO WYDARZEŃ M04: '+str(macro.get('event_risk')),
              'M11 RISK GATE: '+str(report.get('m11_risk_gate')),
              'CENA: TYLKO MT5 | WYKONANIE: BLOCKED | BRAK AUTOMATYCZNYCH TRANSAKCJI',
              '\nOSTRZEŻENIA: '+', '.join(report.get('macro_reason_codes',[])[:10]),
              '\nAKTYWNE WYDARZENIA (UTC):',
            ]
            for e in report.get('macro_active_events',[])[:15]:
                lines.append(f"{str(e.get('scheduled_at'))[:19]} | {str(e.get('impact')):7} | {str(e.get('name'))[:72]} | {str(e.get('source_id'))[:20]}")
            if not report.get('macro_active_events'):lines.append('Brak rozpoznanych wydarzeń w częściowym kalendarzu — TO NIE ZNACZY BRAKU RYZYKA.')
            lines.append('\nŚWIEŻO OPUBLIKOWANE NAGŁÓWKI HIGH/EXTREME:')
            for n in report.get('macro_new_high_impact_news',[])[:8]:
                lines.append(str(n.get('title') or '(brak tytułu)')[:125])
            lines.append('\nZDROWIE KANAŁÓW:')
            for key,value in sorted(report.get('source_health',{}).items()):
                lines.append(f"{key:24} {(value or {}).get('state')}")
            lines.append('\nSTATUS TELEGRAM (MAKRO): '+str((report.get('delivery') or {}).get('status')))
            lines.append('\nINDYKATORY Z MT5 (DIAGNOSTYKA):')
            for tf,measurement in (report.get('technical_indicator_timeframes') or {}).items():
                lines.append(str(tf)+': '+str((measurement or {}).get('market_direction'))+' '+str((measurement or {}).get('status')))
            msg='\n'.join(lines)
            self.status.set('MAKRO '+str(report.get('macro_gate'))+' | SYGNAŁ '+str(report.get('guarded_display_decision'))+' | WYKONANIE BLOCKED')
        except (OSError,TypeError,ValueError,KeyError,UnicodeError):
            msg='BRAK AKTUALNEGO MONITORA MAKRO. Nie wykorzystuj wcześniejszego LONG/SHORT ani kalendarza jako danych LIVE.'
            self.status.set('BRAK DANYCH — NO_TRADE / BLOCKED')
        self.panel.config(state='normal');self.panel.delete('1.0','end');self.panel.insert('1.0',msg);self.panel.config(state='disabled')
        self.root.after(1500,self.tick)
    def run(self):self.root.mainloop()

if __name__=='__main__':Viewer(sys.argv[1] if len(sys.argv)>1 else DEFAULT).run()
