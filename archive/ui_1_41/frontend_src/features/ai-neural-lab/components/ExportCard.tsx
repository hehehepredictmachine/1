// "Eksportuj dane z MT5" (prompt 4A §10): symbol, period, timeframes, optional Bid/Ask ticks, progress, cancel, result with the
// per-model data table and a hand-over to training. The export runs as its own read-only process (no orders); every value shown
// comes from /api/v1/export/* - an export that did not finish is never offered for training.
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "../../../api";
import { cls, fmtNum } from "../../../util";

const TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const STATE_PL: Record<string, string> = {
  STARTING: "uruchamianie", IN_PROGRESS: "w toku", COMPLETE: "ukończony", LEGACY_COMPLETE: "ukończony (starszy format)", FAILED: "błąd",
  CANCELLED: "przerwany", INTERRUPTED: "przerwany (proces zakończony)", MISSING: "brak",
};
const RD_PL: Record<string, string> = { GOTOWE: "gotowe", BRAK_DANYCH: "brak danych", NIEZGODNY_FORMAT: "niezgodny format", NIEKOMPLETNY_EKSPORT: "eksport niekompletny" };

export function useExports(instrument: string) {
  const [d, setD] = useState<any>(null);
  const load = useCallback(() => { apiGet(`/api/v1/export/datasets?instrument=${instrument}`).then(setD).catch(() => setD(null)); }, [instrument]);
  useEffect(() => { load(); }, [load]);
  return { d, reload: load };
}

export default function ExportCard({ instrument, onUse }: { instrument: string; onUse: (dir: string) => void }) {
  const ds = useExports(instrument);
  const [st, setSt] = useState<any>(null);
  const [symbol, setSymbol] = useState("");
  const [mode, setMode] = useState<"months" | "dates">("months");
  const [months, setMonths] = useState(12);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [tfs, setTfs] = useState<string[]>(TFS);
  const [ticks, setTicks] = useState(0);
  const [ask, setAsk] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const running = !!st?.running;
  const poll = useCallback(() => { apiGet("/api/v1/export/status").then(setSt).catch(() => {}); }, []);
  useEffect(() => {
    poll();
    const t = setInterval(poll, running ? 1500 : 8000);
    return () => clearInterval(t);
  }, [poll, running]);
  useEffect(() => { if (!symbol && ds.d?.default_symbol) setSymbol(ds.d.default_symbol); }, [ds.d, symbol]);
  useEffect(() => { if (st && !st.running) ds.reload(); }, [st?.running]); // eslint-disable-line react-hooks/exhaustive-deps
  const start = async (resumeDir?: string) => {
    setAsk(false);
    setMsg(null);
    const body: any = { instrument, symbol: symbol.trim(), timeframes: tfs, ticks_days: ticks };
    if (mode === "months") body.months = months; else { body.from = from; if (to) body.to = to; }
    if (resumeDir) body.resume_dir = resumeDir;
    try {
      const r: any = await apiSend("POST", "/api/v1/export/start", body);
      setMsg(r.started ? "Eksport uruchomiony w osobnym procesie (tylko odczyt historii)." : `Nie uruchomiono: ${r.reason}`);
      poll();
    } catch (e: any) {
      setMsg(`Odmowa: ${e?.message || e}`);
    }
  };
  const cancel = async () => { try { await apiSend("POST", "/api/v1/export/cancel", {}); poll(); } catch (e: any) { setMsg(`Błąd: ${e?.message || e}`); } };
  const job = st?.job && st.job.instrument === instrument ? st : null;
  const p = job?.progress;
  const frac = p && p.total ? Math.min(1, p.done / p.total) : null;
  const ready = job?.readiness?.models || [];
  const resumable = job && !job.running && ["FAILED", "CANCELLED", "INTERRUPTED"].includes(job.state);
  return (
    <section className="t-card" aria-labelledby="nl-export-h" data-testid="nl-export">
      <header className="t-card-head"><div><h2 id="nl-export-h">Eksportuj dane z MT5</h2>
        <span className="t-dim">historia do treningu – tylko odczyt, bez zleceń</span></div>
        <span className={cls("t-badge", job?.state === "COMPLETE" ? "t-badge-ok" : job?.state === "FAILED" ? "t-badge-bad" : "t-badge-muted")} data-testid="nl-export-state">
          {job ? STATE_PL[job.state] ?? job.state : "brak eksportu"}</span></header>
      <div className="t-form">
        <label className="t-field">Symbol brokera (dokładna nazwa)
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} spellCheck={false} data-testid="nl-export-symbol" /></label>
        <div className="t-row" role="radiogroup" aria-label="Okres">
          <label className="t-inline"><input type="radio" checked={mode === "months"} onChange={() => setMode("months")} /> ostatnie miesiące</label>
          <label className="t-inline"><input type="radio" checked={mode === "dates"} onChange={() => setMode("dates")} data-testid="nl-export-dates" /> zakres dat (UTC)</label>
        </div>
        {mode === "months" ? (
          <label className="t-field t-inline">Miesięcy <input type="number" min={1} max={36} value={months} onChange={(e) => setMonths(Number(e.target.value))}
            style={{ width: 72 }} data-testid="nl-export-months" /></label>) : (
          <div className="t-row">
            <label className="t-field t-inline">Od <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} data-testid="nl-export-from" /></label>
            <label className="t-field t-inline">Do <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          </div>)}
        <fieldset className="t-row" aria-label="Interwały">
          <legend className="t-dim">Interwały</legend>
          {TFS.map((t) => (
            <label key={t} className="t-inline"><input type="checkbox" checked={tfs.includes(t)} data-testid={`nl-export-tf-${t}`}
              onChange={(e) => setTfs(e.target.checked ? TFS.filter((x) => x === t || tfs.includes(x)) : tfs.filter((x) => x !== t))} /> {t}</label>))}
        </fieldset>
        <label className="t-field t-inline">Ticki Bid/Ask z ostatnich dni (0 = bez)
          <input type="number" min={0} max={31} step={0.5} value={ticks} onChange={(e) => setTicks(Number(e.target.value))} style={{ width: 72 }} data-testid="nl-export-ticks" /></label>
        <p className="t-note">Ticki zajmują dużo miejsca (dziesiątki tysięcy na dzień) – wybierz kilka dni. Rozstrzygają kolejność TP/SL w jednej świecy.</p>
      </div>
      <div className="t-row">
        <button className="t-btn t-btn-acc" disabled={running || !symbol.trim() || !tfs.length || (mode === "dates" && !from)} onClick={() => setAsk(true)}
          data-testid="nl-export-start">Eksportuj dane z MT5</button>
        {running && <button className="t-btn" onClick={cancel} data-testid="nl-export-cancel">Przerwij</button>}
        {resumable && <button className="t-btn" onClick={() => start(job.job.out)} data-testid="nl-export-resume">Wznów ten eksport</button>}
      </div>
      {ask && (
        <div className="t-confirm" role="alertdialog" aria-label="Potwierdź eksport">
          <p>Eksport {symbol} ({tfs.join(", ")}{ticks ? `, ticki ${ticks} d` : ""}) z terminala MT5 w osobnym procesie. Tylko odczyt – żadne zlecenie nie jest wysyłane.
            Może potrwać kilka minut.</p>
          <div className="t-row"><button className="t-btn t-btn-acc" onClick={() => start()} data-testid="nl-export-yes">Eksportuj</button>
            <button className="t-btn" onClick={() => setAsk(false)}>Anuluj</button></div>
        </div>)}
      {msg && <p className="t-note" role="status">{msg}</p>}
      {job && (
        <div data-testid="nl-export-result">
          {frac != null && job.running && (
            <div className="t-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(frac * 100)}>
              <i style={{ width: `${fmtNum(frac * 100, 0)}%` }} /><span>{p.phase === "ticks" ? "ticki" : p.item} {p.done}/{p.total}</span></div>)}
          <dl className="t-kv">
            <dt>Folder</dt><dd className="t-mono">{job.job.out}</dd>
            <dt>Zakres</dt><dd>{job.range_utc ? `${job.range_utc[0]} – ${job.range_utc[1]}` : "—"}</dd>
            <dt>Dane</dt><dd>{job.data_kind === "SYNTHETIC_TEST" ? "SYNTETYCZNE (symulator) – tylko test techniczny" : job.data_kind === "REAL_USER_DATA" ? "z Twojego terminala MT5" : "—"}</dd>
            {job.reason && <><dt>Powód</dt><dd className="t-neg">{job.reason}</dd></>}
          </dl>
          {ready.length > 0 && (
            <div className="t-table-wrap"><table className="t-table t-table-wrapcells" data-testid="nl-export-readiness">
              <thead><tr><th>Model</th><th>Wymagane dane</th><th>Status</th><th>Próbki</th><th>Uwagi</th></tr></thead>
              <tbody>{ready.map((m: any) => (
                <tr key={m.kind} data-status={m.status}><td>{m.title}</td><td>{m.required.join(", ")}{m.optional.length ? ` (+${m.optional.join(", ")})` : ""}</td>
                  <td className={cls(m.status === "GOTOWE" ? "t-pos" : "t-neg")}>{RD_PL[m.status] ?? m.status}</td><td>{m.samples}</td><td className="t-dim">{m.reason}</td></tr>))}
              </tbody></table></div>)}
          {job.usable && <button className="t-btn t-btn-acc" onClick={() => onUse(job.job.out)} data-testid="nl-export-use">Trenuj na tym eksporcie →</button>}
          {job.log_tail && <details><summary>Dziennik eksportu</summary><pre className="t-log">{job.log_tail}</pre></details>}
        </div>)}
    </section>);
}
