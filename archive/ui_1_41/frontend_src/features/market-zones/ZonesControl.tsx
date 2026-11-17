// "Wyznacz strefy" in the main chart area (1.29): pick M1 / M5 / M15 / all three (M30 and all four stay available), start the backend
// computation, switch LIVE on/off, see progress, errors, the last successful computation and the source state of every TF.
// The zones are drawn by the charts of the same instrument and TF (ChartPanel reads the shared store). Analytical only: the calls go to
// /api/v1/market-zones/* - no order, no change of the execution mode or of automatic-trading settings.
import { useEffect, useState } from "react";
import { useStore } from "../../store";
import { cls, fmtNum, fmtTime } from "../../util";
import { computeZones, setZonesLive, stopZones, useMarketZones } from "./mzStore";
import "./market-zones.css";

const SCOPES: [string, string, string[]][] = [
  ["M1-M5-M15", "M1 + M5 + M15 (wszystkie trzy)", ["M1", "M5", "M15"]],
  ["M1", "tylko M1", ["M1"]], ["M5", "tylko M5", ["M5"]], ["M15", "tylko M15", ["M15"]], ["M30", "tylko M30", ["M30"]],
  ["ALL4", "M1 + M5 + M15 + M30", ["M1", "M5", "M15", "M30"]],
];
const TONE: Record<string, string> = { CONNECTED: "ok", STALE: "warn", NO_DATA: "warn", ERROR: "bad", IDLE: "muted" };

const loadScope = () => { try { const v = localStorage.getItem("mq.mzbar.scope"); return SCOPES.some(([k]) => k === v) ? v! : "M1-M5-M15"; } catch { return "M1-M5-M15"; } };

export default function ZonesControl({ chartSymbol }: { chartSymbol?: string | null }) {
  const { s } = useStore();
  const inst: string | null = s.assets?.active || null;
  const st = useMarketZones(inst);
  const [scope, setScope] = useState<string>(loadScope);
  const tfs = SCOPES.find(([k]) => k === scope)![2];
  const v = st.view;
  const job = v?.job;
  const running = job && ["QUEUED", "RUNNING"].includes(job.status);
  const [liveWant, setLiveWant] = useState<boolean | null>(null);         // optimistic switch until the backend state arrives
  const live = liveWant ?? !!v?.live?.enabled;
  useEffect(() => { if (liveWant !== null && (!!v?.live?.enabled === liveWant || st.err)) setLiveWant(null); }, [v, liveWant, st.err]);
  const lastOk = tfs.map((tf) => v?.timeframes?.[tf]?.computed_at).filter(Boolean).sort().pop();
  const mismatch = v?.symbol && chartSymbol && v.symbol !== chartSymbol;
  const pick = (k: string) => { setScope(k); try { localStorage.setItem("mq.mzbar.scope", k); } catch { /* private mode */ } };
  if (!inst) return null;
  return (
    <section className="mzbar" data-testid="mzbar" aria-label="Strefy rynkowe na wykresie" data-instrument={inst}>
      <div className="mzbar-row">
        <b className="mzbar-title">Strefy {inst}</b>
        <select value={scope} onChange={(e) => pick(e.target.value)} data-testid="mzbar-scope" aria-label="Interwały stref">
          {SCOPES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <button className="btn primary" disabled={st.busy === "compute"} data-testid="mzbar-compute"
          onClick={() => void computeZones(inst, tfs)} title="Przelicza strefy w backendzie z zamkniętych świec – nie otwiera pozycji">
          {running ? "Wyznaczanie…" : "Wyznacz strefy"}</button>
        <label className="mzbar-live" title="Przeliczenie po zamknięciu każdej świecy wybranych interwałów">
          <input type="checkbox" checked={live} disabled={st.busy === "live"} data-testid="mzbar-live"
            onChange={(e) => { setLiveWant(e.target.checked); void setZonesLive(inst, e.target.checked, tfs); }} /> LIVE</label>
        {(running || live) && <button className="btn tiny danger" data-testid="mzbar-stop" onClick={() => void stopZones(inst)}>Zatrzymaj</button>}
        <span className="mzbar-meta">ostatnie udane: <b data-testid="mzbar-last">{lastOk ? fmtTime(lastOk, true) : "—"}</b></span>
        <a className="link small" href="#/strefy">szczegóły stref →</a>
      </div>
      <div className="mzbar-row">
        {tfs.map((tf) => {
          const r = v?.timeframes?.[tf];
          const ss = r?.status || { status: "IDLE", status_pl: "nie pobierano" };
          return <span key={tf} className={cls("chip", TONE[ss.status] || "muted")} data-testid={`mzbar-src-${tf}`} data-status={ss.status} title={ss.reason || ""}>
            <i className="dot" />{tf}: {ss.status_pl}{r?.computed ? ` · ${(r.zones || []).length} stref` : ""}{r?.stale && r?.computed ? " · nieaktualne" : ""}</span>;
        })}
        {job && (
          <span className={cls("mzbar-job", job.status === "FAILED" && "bad", job.status === "PARTIAL" && "warn")} data-testid="mzbar-job" data-status={job.status}>
            <span className="mz-progress" aria-label="Postęp"><i style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} /></span>
            {job.status_pl} · {job.stage}{job.duration_s != null ? ` · ${fmtNum(job.duration_s, 1)} s` : ""}{job.error ? ` – ${job.error}` : ""}
          </span>)}
        {mismatch && <span className="chip warn" data-testid="mzbar-mismatch"><i className="dot" />symbol stref {v.symbol} ≠ wykres {chartSymbol} – strefy nie są rysowane</span>}
        {st.err && <span className="bad small" role="alert" data-testid="mzbar-err">{st.err}</span>}
      </div>
    </section>);
}
