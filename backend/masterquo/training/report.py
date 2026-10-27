"""HTML + JSON report of a training run (counts come from the run state - nothing is hard-coded)."""
from __future__ import annotations

import html
import json
import os
import webbrowser

from . import core

PL = {"UKONCZONE": "ukończone", "POMINIETE": "pominięte", "BLAD_TECHNICZNY": "błąd techniczny", "ANULOWANE": "anulowane",
      "NIE_URUCHOMIONE": "nie uruchomione", "W_TOKU": "w toku", "NIE_DOTYCZY": "—", "BRAK_PRZESLANEK": "brak przesłanek (za mało danych)",
      "ODRZUCONY": "odrzucony", "NIEZWALIDOWANY": "niezwalidowany", "CZESCIOWO_ZWALIDOWANY": "częściowo zwalidowany",
      "ZWALIDOWANY_SHADOW": "zwalidowany (SHADOW)", "TEST_TECHNICZNY": "test techniczny", "NIEZAPISANY": "niezapisany",
      "ZAPISANY_DO_BADAN": "zapisany do badań", "AKTYWNY_W_REJESTRZE": "aktywny w rejestrze", "ZALADOWANY_DO_SHADOW": "załadowany do SHADOW",
      "ROLLBACK": "rollback"}


def summary(state: dict) -> dict:
    out = {"instruments": {}, "admitted_shadow": 0, "line": ""}
    parts = []
    for inst in state["plan"]["instruments"]:
        ts = [t for t in state["tasks"] if t["instrument"] == inst and t.get("detail") != "nie wybrano w planie"]
        done = sum(t["execution"] == "UKONCZONE" for t in ts)
        skipped = [f"{t['title']}: {t.get('detail')}" for t in ts if t["execution"] == "POMINIETE"]
        errors = [f"{t['title']}: {(t.get('detail') or '')[:600]}" for t in ts if t["execution"] == "BLAD_TECHNICZNY"]
        admitted = sum(1 for t in ts if t["quality"] in ("ZWALIDOWANY_SHADOW", "CZESCIOWO_ZWALIDOWANY")
                       and t["integration"] in ("AKTYWNY_W_REJESTRZE", "ZALADOWANY_DO_SHADOW"))
        lab = next((t for t in ts if t["kind"] == "lab"), {})
        out["instruments"][inst] = {"requested": len(ts), "done": done, "skipped": skipped, "errors": errors, "admitted_shadow": admitted,
                                    "lab_models_saved": len(lab.get("lab_models") or [])}
        out["admitted_shadow"] += admitted
        parts.append(f"{inst}: {done}/{len(ts)} zadań ukończonych")
    no_cycles = [t["instrument"] for t in state["tasks"] if t["kind"] == "scalp_B" and t["quality"] == "BRAK_PRZESLANEK"]
    line = "; ".join(parts) + "."
    if no_cycles:
        line += f" Brak cykli do filtra setupu ({', '.join(no_cycles)})."
    line += f" {out['admitted_shadow']} modeli dopuszczonych do SHADOW. Szczegóły w raporcie."
    out["line"] = line
    return out


def write(run, open_browser: bool | None = None) -> dict:
    st = run.state
    sm = summary(st)
    st["summary"] = sm
    core.write_json_atomic(run.dir / "report.json", st)
    rows = []
    for t in st["tasks"]:
        rows.append(f"<tr class='{t['execution']}'><td>{html.escape(t['instrument'])}</td><td>{html.escape(t['title'])}</td>"
                    f"<td>{PL.get(t['execution'], t['execution'])}</td><td>{PL.get(t['quality'], t['quality'])}</td>"
                    f"<td>{PL.get(t['integration'], t['integration'])}</td><td>{html.escape(str(t.get('model_id') or ''))}</td>"
                    f"<td>{html.escape(str(t.get('detail') or ''))}</td></tr>")
    plan = st["plan"]
    body = f"""<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raport treningu {html.escape(run.run_id)}</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--mut:#666;--line:#ddd;--ok:#e8f6ec;--bad:#fdecea;--skip:#fff8e1}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--mut:#aaa;--line:#333;--ok:#1d3324;--bad:#3a1f1d;--skip:#33301c}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:16px}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid var(--line);padding:6px;vertical-align:top;text-align:left}} .UKONCZONE{{background:var(--ok)}}
.BLAD_TECHNICZNY,.ANULOWANE{{background:var(--bad)}} .POMINIETE{{background:var(--skip)}} .mut{{color:var(--mut)}} .wrap{{overflow-x:auto}}
</style></head><body><h1>Raport treningu {html.escape(run.run_id)}</h1>
<p><b>{html.escape(sm['line'])}</b></p>
<p class="mut">Profil: {html.escape(plan['profile'])} · instrumenty: {html.escape(', '.join(plan['instruments']))} · symbole: {html.escape(json.dumps(plan['symbols'], ensure_ascii=False))}
 · historia: {plan['months']} mies. · dane: {'SYNTETYCZNE (test)' if plan['synthetic'] else 'rzeczywiste z terminala'} · status runu: {html.escape(st.get('status', ''))}</p>
<p class="mut">Trzy osie statusu: wykonanie / jakość / integracja. Ukończone zadanie nie oznacza dobrego modelu. Żadna liczba tutaj nie jest win rate ani
gwarancją wyniku. Trening nie wysyła zleceń i nie zmienia trybu wykonania.</p>
<div class="wrap"><table><tr><th>Instrument</th><th>Zadanie</th><th>Wykonanie</th><th>Jakość</th><th>Integracja</th><th>Model / run</th><th>Szczegóły</th></tr>
{''.join(rows)}</table></div>
<h2>Zasady planu (zamrożone przed treningiem)</h2><pre>{html.escape(json.dumps(plan.get('rules'), indent=1, ensure_ascii=False))}</pre>
<p class="mut">Pełne dane: report.json i logs/ w katalogu runu.</p></body></html>"""
    p = run.dir / "report.html"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, p)
    print("\n" + "=" * 78 + "\nPODSUMOWANIE: " + sm["line"])
    for inst, v in sm["instruments"].items():
        for s in v["skipped"]:
            print(f"  [{inst}] pominięte – {s}")
        for e in v["errors"]:
            print(f"  [{inst}] BŁĄD – {e}")
    print(f"Raport: {p}\n" + "=" * 78, flush=True)
    if open_browser is None:
        open_browser = os.environ.get("MQ_NO_BROWSER") != "1"
    if open_browser:
        try:
            webbrowser.open(p.resolve().as_uri())
        except Exception:  # noqa: BLE001
            pass
    return sm
