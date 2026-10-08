"""Read-only local MT5 indicator dashboard for Bridge JSON (Tkinter stdlib).

This is a DATA VIEWER, not a TradingView chart and not an order terminal.
"""
import argparse
from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk

TF = ('D1','H4','H1','M15','M5','M1')


def metric(ind, *keys):
    for k in keys:
        val = ind.get(k)
        if isinstance(val, dict) and isinstance(val.get('value'),(int,float)):
            return f'{val["value"]:.3f}'
    return 'N/D'


def row_view(result: dict, tf: str) -> tuple[str, ...]:
    section=result.get('indicator_intelligence') or {}
    data=section.get('timeframes',{}).get(tf,{})
    indicators=data.get('indicators') or {}
    market=(result.get('market_state') or {}).get('timeframes',{}).get(tf,{})
    regime = market.get('structure_regime','UNKNOWN')
    ema_keys=[k for k in indicators if k.startswith('ema_') and k[4:].isdigit()]
    ema_display=' · '.join(f'{k[4:]}:{metric(indicators,k)}' for k in sorted(ema_keys,key=lambda x:int(x[4:]))) or 'N/D'
    return (tf,market.get('status','N/D'),data.get('status','N/D'),regime,
            ema_display,metric(indicators,'rsi_9','rsi_14'),
            metric(indicators,'adx_wilder_14'), metric(indicators,'atr_14'))


def run(path: Path, every_ms: int=1200):
    root=tk.Tk()
    root.title('MasterQUO · M01/M02/M02I · ODCZYT MT5')
    root.geometry('1150x510')
    header=tk.Label(root,text='MASTERQUO — WSKAŹNIKI MT5 (TYLKO PODGLĄD · BRAK TRANSAKCJI)',
                    font=('Segoe UI',13,'bold'),pady=12)
    header.pack()
    status=tk.StringVar(value='Ładowanie...')
    ttk.Label(root,textvariable=status).pack(pady=(0,12))
    cols=('TF','M02','M02I','Reżim','EMA','RSI','ADX','ATR')
    table=ttk.Treeview(root,columns=cols,show='headings',height=7)
    widths=(65,100,100,170,320,95,95,95)
    for name,width in zip(cols,widths):
        table.heading(name,text=name)
        table.column(name,width=width,anchor='center')
    table.pack(fill='both',expand=True,padx=12,pady=5)
    for tf in TF:
        table.insert('', 'end', iid=tf, values=(tf,)+('N/D',)*7)
    note=tk.Label(root,text='PENDING = nieukończona produkcyjna walidacja M01. Dane syntetyczne/testowe nie są sygnałami. EXECUTION: BLOCKED.',wraplength=1080)
    note.pack(pady=7)
    def update():
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            q=data.get('quote') or {}
            price=f'Bid {q.get("bid", "N/D")} · Ask {q.get("ask", "N/D")}'
            status.set(f'Połączenie: {data.get("connection_status")}  |  {price}  |  Quote: {data.get("quote_status")}  |  M02: {data.get("m02_status")}  |  M02I: {data.get("m02i_status")}  |  Ostatni zapis: {data.get("updated_at")}')
            for tf in TF:table.item(tf,values=row_view(data,tf))
        except (OSError,ValueError,TypeError) as ex:
            status.set(f'Brak aktualnego raportu JSON ({type(ex).__name__}).')
        root.after(every_ms,update)
    update()
    root.mainloop()


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--monitor-file',default=str(Path(__file__).with_name('runtime')/'monitor_indicators.json'))
    ap.add_argument('--refresh-ms',type=int,default=1200)
    a=ap.parse_args()
    run(Path(a.monitor_file),max(300,a.refresh_ms))
