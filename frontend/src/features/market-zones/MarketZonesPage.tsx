// "Strefy rynkowe" - zones of XAUUSD / BTC on M1 / M5 / M15 / M30, computed by the backend (zones/market.py) on demand or live after
// each candle close. Analytical only: no button here opens a position or changes automatic-trading settings.
// Responses of an earlier instrument selection are ignored (request sequence); the backend itself refuses to apply an older result
// over a newer one and merges repeated clicks into the running job.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { useStore } from "../../store";
import { telemetry } from "../../telemetry";
import { cls, fmtNum, fmtTime } from "../../util";
import ZoneChart from "./ZoneChart";
import "./market-zones.css";

const TFS = ["M1", "M5", "M15", "M30"];
const INSTRUMENTS = ["XAUUSD", "BTC"];
const TONE: Record<string, string> = { CONNECTED: "ok", STALE: "warn", NO_DATA: "warn", ERROR: "bad", IDLE: "muted" };
const load = (k: string, d: any) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } };
const save = (k: string, v: any) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } };

export default function MarketZonesPage() {
  const { s } = useStore();
  const [inst, setInst] = useState<string>(() => load("mq.mz.inst", "XAUUSD"));
  const [tfs, setTfs] = useState<string[]>(() => load("mq.mz.tfs", TFS));
  const [view, setView] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [liveWant, setLiveWant] = useState<boolean | null>(null);       // optimistic switch until the backend state arrives
  const seq = useRef(0);
  const instRef = useRef(inst);
  instRef.current = inst;

  const refresh = useCallback(async () => {
    const my = ++seq.current;
    const want = instRef.current;
    try {
      const v = await apiGet(`/api/v1/market-zones?instrument=${want}`);
      if (my === seq.current && v.instrument === instRef.current) { setView(v); setErr(null); }
    } catch (e: any) {
      if (my === seq.current) setErr(String(e?.message || e));
    }
  }, []);

  useEffect(() => { save("mq.mz.inst", inst); setView(null); setSel(null); setDetail(null); setLiveWant(null); void refresh(); }, [inst, refresh]);
  useEffect(() => { save("mq.mz.tfs", tfs); }, [tfs]);
  useEffect(() => telemetry.subscribe((m: any) => {
    if (m?.type === "market_zones" && m.data?.instrument === instRef.current) void refresh();
  }), [refresh]);
  const running = view?.job && ["QUEUED", "RUNNING"].includes(view.job.status);
  useEffect(() => {
    if (!running && !view?.live?.enabled) return;
    const t = setTimeout(() => void refresh(), running ? 600 : 5000);
    return () => clearTimeout(t);
  }, [running, view, refresh]);
  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    let alive = true;
    apiGet(`/api/v1/market-zones/zone/${encodeURIComponent(sel)}?instrument=${inst}`).then((d) => alive && setDetail(d)).catch(() => alive && setDetail(null));
    return () => { alive = false; };
  }, [sel, inst, view?.timeframes]);

  const act = async (what: string, path: string, body: any) => {
    setBusy(what);
    try {
      const r = await apiSend("POST", path, body);
      if (what === "compute") setView((v: any) => (v && v.instrument === inst ? { ...v, job: r } : v));
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
      if (what === "live") setLiveWant(null);
    } finally {
      setBusy(null);
    }
  };
  const toggleTf = (tf: string) => setTfs((cur) => (cur.includes(tf) ? (cur.length > 1 ? cur.filter((x) => x !== tf) : cur) : TFS.filter((x) => cur.includes(x) || x === tf)));
  const symOf = (i: string): string | null => s.assets?.assets?.[i]?.broker_symbol || null;
  const sym = view?.symbol || symOf(inst);
  const live = liveWant ?? !!view?.live?.enabled;
  useEffect(() => { if (liveWant !== null && !!view?.live?.enabled === liveWant) setLiveWant(null); }, [view, liveWant]);
  const job = view?.job;
  const lastData = useMemo(() => tfs.map((tf) => view?.timeframes?.[tf]?.status?.last_closed || view?.timeframes?.[tf]?.last_closed).filter(Boolean).sort().pop(), [view, tfs]);
  const lastCompute = useMemo(() => tfs.map((tf) => view?.timeframes?.[tf]?.computed_at).filter(Boolean).sort().pop(), [view, tfs]);

  return (
    <main className="page mz-page" data-testid="page-strefy">
      <section className="panel mz-head">
        <div className="panel-head"><h2>Strefy rynkowe</h2><span className="muted small">M1 · M5 · M15 · M30 – wyznaczane przez backend z zamkniętych świec; informacja analityczna,
          bez otwierania pozycji i bez zmiany ustawień handlu</span></div>
        <div className="mz-controls">
          <label>Instrument{" "}
            <select value={inst} onChange={(e) => setInst(e.target.value)} data-testid="mz-instrument">
              {INSTRUMENTS.map((i) => <option key={i} value={i}>{i}{symOf(i) ? ` (${symOf(i)})` : ""}</option>)}
            </select></label>
          <div className="mz-tfs" role="group" aria-label="Interwały">
            {TFS.map((tf) => (
              <button key={tf} className={cls("btn", "tiny", tfs.includes(tf) && "on")} aria-pressed={tfs.includes(tf)} onClick={() => toggleTf(tf)}
                data-testid={`mz-tf-${tf}`}>{tf}</button>))}
          </div>
          <button className="btn" disabled={busy === "compute"} onClick={() => void act("compute", "/api/v1/market-zones/compute", { instrument: inst, timeframes: tfs })}
            data-testid="mz-compute">{running ? "Wyznaczanie…" : "Wyznacz strefy teraz"}</button>
          <label className="mz-switch">
            <input type="checkbox" checked={live} disabled={busy === "live"} data-testid="mz-live"
              onChange={(e) => { setLiveWant(e.target.checked); void act("live", "/api/v1/market-zones/live", { instrument: inst, enabled: e.target.checked, timeframes: tfs }); }} />
            Aktualizacja na żywo</label>
          <button className="btn danger" disabled={!running && !live} onClick={() => void act("stop", "/api/v1/market-zones/stop", { instrument: inst })}
            data-testid="mz-stop">Zatrzymaj</button>
        </div>
        <div className="mz-meta">
          <span>Symbol brokera: <b>{sym || "brak – ustaw w Ustawieniach"}</b></span>
          <span>Ostatnie dane: <b data-testid="mz-last-data">{lastData ? fmtTime(lastData, true) : "—"}</b></span>
          <span>Ostatnie przeliczenie: <b data-testid="mz-last-compute">{lastCompute ? fmtTime(lastCompute, true) : "—"}</b></span>
          {view?.quote?.bid != null && <span>Cena (bid): <b>{view.quote.bid}</b> <span className="muted">· dotknięcia z ceny na żywo są wstępne</span></span>}
        </div>
        {job && (
          <div className={cls("mz-job", job.status === "FAILED" && "bad", job.status === "PARTIAL" && "warn")} data-testid="mz-job" data-status={job.status}>
            <div className="mz-progress" aria-label="Postęp"><i style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} /></div>
            <span><b>{job.status_pl}</b> · {job.stage}{job.duration_s != null ? ` · ${fmtNum(job.duration_s, 1)} s` : ""} · {job.reason === "manual" ? "ręcznie" : job.reason}</span>
            {job.error && <span className="bad"> – {job.error}</span>}
          </div>)}
        {err && <p className="bad small" role="alert">{err}</p>}
        <table className="mz-status" data-testid="mz-status">
          <thead><tr><th>Interwał</th><th>Źródło</th><th>Ostatnia zamknięta świeca</th><th>Przeliczono</th><th>Aktywne</th><th>Testowane</th><th>Wstępne</th><th>Unieważn./wygasłe</th></tr></thead>
          <tbody>{tfs.map((tf) => {
            const r = view?.timeframes?.[tf];
            const st = r?.status || { status: "IDLE", status_pl: "nie pobierano" };
            const c = r?.counts || {};
            return (
              <tr key={tf} data-testid={`mz-status-${tf}`} data-status={st.status}>
                <td><b>{tf}</b></td>
                <td><span className={cls("chip", TONE[st.status] || "muted")} title={st.reason || ""}><i className="dot" />{st.status_pl}</span>
                  {r?.stale && r?.computed ? <span className="warn small"> strefy z ostatniego udanego przeliczenia</span> : null}</td>
                <td>{fmtTime(r?.last_closed || st.last_closed, true) || "—"}</td>
                <td>{r?.computed_at ? fmtTime(r.computed_at, true) : "—"}</td>
                <td>{c.ACTIVE ?? "—"}</td><td>{c.TESTED ?? "—"}</td><td>{c.PRELIMINARY ?? "—"}</td>
                <td>{c.INVALIDATED != null ? `${c.INVALIDATED} / ${c.EXPIRED}` : "—"}</td>
              </tr>);
          })}</tbody>
        </table>
      </section>
      <div className={cls("mz-body", detail && "with-detail")}>
        <div className={cls("mz-grid", `n${tfs.length}`)}>
          {tfs.map((tf) => {
            const r = view?.timeframes?.[tf];
            return (
              <section key={`${inst}-${tf}`} className="panel mz-tf">
                <div className="panel-head"><b>{inst} {tf}</b>
                  <span className="muted small">{r?.computed ? `${(r.zones || []).length} widocznych z ${(r.counts?.ACTIVE || 0) + (r.counts?.TESTED || 0) + (r.counts?.PRELIMINARY || 0)} żywych`
                    : "brak wyniku – użyj „Wyznacz strefy teraz”"}</span>
                  {r?.stale && r?.computed && <span className="chip warn"><i className="dot" />nieaktualne</span>}</div>
                <ZoneChart instrument={inst} tf={tf} zones={r?.zones || []} stale={!!r?.stale} selected={sel} onPick={setSel}
                  dataKey={`${r?.computed_at || ""}|${r?.last_closed || ""}`} />
                <ul className="mz-list">{(r?.zones || []).map((z: any) => (
                  <li key={z.id}><button className={cls("link", sel === z.id && "on")} onClick={() => setSel(z.id)} data-testid="mz-zone">
                    <span className={cls("mz-dir", z.direction)}>{z.type_pl}</span> {z.lower} – {z.upper} · {z.state_pl}
                    {z.tests ? ` · testy ${z.tests}` : ""} · jakość {Math.round(z.quality?.score ?? 0)}
                    {z.confluence?.count ? ` · konfluencja ${z.confluence.timeframes.join("/")}` : ""}
                    {z.live?.touching ? " · cena w strefie (wstępnie)" : ""}</button></li>))}</ul>
              </section>);
          })}
        </div>
        {detail && <ZoneDetail d={detail} onClose={() => setSel(null)} />}
      </div>
      <details className="panel mz-rules">
        <summary>Reguły wykrywania, potwierdzenia, testów i unieważnienia ({view?.version || "PMW-MZ-1"})</summary>
        <ul>{Object.entries(view?.rules?.detection || {}).map(([k, v]) => <li key={k}><b>{k}</b>: {String(v)}</li>)}
          {["confirmation", "test", "invalidation", "expiry", "liquidity_note", "score_note"].map((k) => view?.rules?.[k] && <li key={k}><b>{k}</b>: {view.rules[k]}</li>)}</ul>
      </details>
    </main>);
}

function ZoneDetail({ d, onClose }: { d: any; onClose: () => void }) {
  const z = d.zone;
  return (
    <aside className="panel mz-detail" data-testid="mz-detail" aria-label="Szczegóły strefy">
      <div className="panel-head"><b>{z.type_pl}</b><span className="muted small">{z.timeframe} · {z.id}</span>
        <button className="icon" onClick={onClose} aria-label="Zamknij">✕</button></div>
      <div className="mz-detail-body">
        <table className="mz-kv"><tbody>
          <tr><th>Zakres</th><td>{z.lower} – {z.upper} (szer. {fmtNum(z.quality?.width_atr, 2)} ATR)</td></tr>
          <tr><th>Kierunek</th><td>{z.direction === "BULLISH" ? "wzrostowy" : z.direction === "BEARISH" ? "spadkowy" : "neutralny"}</td></tr>
          <tr><th>Stan</th><td>{z.state_pl}{z.stale ? " – dane nieaktualne" : ""}</td></tr>
          <tr><th>Świeca źródłowa</th><td>{fmtTime(z.origin_time, true)}</td></tr>
          <tr><th>Wykrywalna od</th><td>{fmtTime(z.detectable_from, true)}</td></tr>
          <tr><th>Niezależne testy</th><td>{z.tests}{z.test_times?.length ? ` (${z.test_times.map((t: string) => fmtTime(t)).join(", ")})` : ""}</td></tr>
          <tr><th>Powód</th><td>{z.reason}</td></tr>
          <tr><th>Unieważnienie</th><td>{z.invalidation_rule}</td></tr>
          <tr><th>Konfluencja</th><td>{z.confluence?.count ? z.confluence.timeframes.join(", ") : "brak"}</td></tr>
          <tr><th>Wersja algorytmu</th><td>{z.algo_version}</td></tr>
          {z.members?.length > 0 && <tr><th>Połączona z</th><td>{z.members.map((m: any) => `${m.id} (${m.lower}–${m.upper})`).join("; ")}</td></tr>}
        </tbody></table>
        <h4>Jakość {fmtNum(z.quality?.score, 1)} / 100</h4>
        <p className="muted small">{z.quality?.note}. Prawdopodobieństwo: {z.probability == null ? "brak (nieskalibrowane)" : z.probability}.</p>
        <ul className="mz-comp">{Object.entries(z.quality?.components || {}).map(([k, v]) => <li key={k}><span>{k}</span><b>{String(v)}</b></li>)}</ul>
        <h4>Checklista ({d.checklist.passed}/{d.checklist.evaluated})</h4>
        <ul className="mz-check" data-testid="mz-checklist">{d.checklist.items.map((i: any) => (
          <li key={i.label} className={i.ok === true ? "ok" : i.ok === false ? "bad" : "muted"}>
            <span>{i.ok === true ? "✓" : i.ok === false ? "✗" : "•"}</span> {i.label}{i.value != null ? <em> – {String(i.value)}</em> : null}</li>))}</ul>
        <p className="muted small">{d.checklist.note}</p>
        <h4>Historia</h4>
        <ul className="mz-events">{(d.events || []).map((e: any) => <li key={e.event + e.at}>{fmtTime(e.at, true)} – {e.event} ({e.tf})</li>)}</ul>
      </div>
    </aside>);
}
