// DIAGNOSTYKA (S6 §3.4) – treść DiagnosticsPage z 1.41.0 (pages/AnalyticsPages.tsx) przeniesiona 1:1: te same źródła
// (GET /api/v1/analytics/diagnostics co 5 s, GET /api/v1/timeframes, stan połączenia ze store), te same pola. Pominięta tylko
// sekcja „Inne rynki” (podgląd rynków starego UI, nie diagnostyka).
import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../../api";
import { BRAND } from "../../brand";
import { useStore } from "../../store";
import { cls, fmtTime } from "../../util";

const tone = (st?: string) => (st === "CONNECTED" || st === "OK" ? "ok" : st === "ERROR" || st === "FAILED" || st === "DISCONNECTED" ? "bad" : "warn");

export default function DiagnosticsPanel() {
  const { s } = useStore();
  const [diag, setDiag] = useState<any>(null);
  const [tfm, setTfm] = useState<any>(null);
  const [res, setRes] = useState<any>(null);
  const [resErr, setResErr] = useState<string | null>(null);
  const [askProf, setAskProf] = useState<string | null>(null);
  const setProfile = (p: string) => apiSend("PUT", "/api/v1/resources/profile", { profile: p }).then((x: any) => { setRes(x); setResErr(null); setAskProf(null); })
    .catch((e) => setResErr(String(e?.message || e)));
  const load = () => {
    apiGet("/api/v1/resources").then(setRes).catch(() => setRes(null));
    apiGet("/api/v1/analytics/diagnostics").then(setDiag).catch(() => setDiag(null));
    apiGet("/api/v1/timeframes").then(setTfm).catch(() => setTfm(null));
  };
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  const con = s.connection || {};
  return (
    <div className="sys-diag" data-testid="page-diagnostyka">
      <div className="sys-row"><span className="sys-note">{s.synthetic ? "DANE SYNTETYCZNE – symulator terminala" : "Dane z terminala MT5"}</span>
        <button type="button" className="act" onClick={load}>ODŚWIEŻ</button></div>
      <section><h4>MT5 / BRIDGE</h4><dl className="sys-kv">
        <dt>Stan</dt><dd><span className={cls("sys-st", tone(con.state))}>{con.state ?? "?"}</span> {con.reason ?? ""}</dd>
        <dt>Terminal</dt><dd>{con.terminal?.path ?? con.terminal?.name ?? "—"}</dd><dt>Rachunek</dt><dd>{con.account_key ?? "—"}</dd>
        <dt>Połączony od</dt><dd>{fmtTime(con.connected_since, true) || "—"}</dd><dt>Heartbeat</dt><dd>{fmtTime(con.last_heartbeat, true) || "—"}</dd>
        <dt>Próby / epoka</dt><dd>{con.attempts ?? 0} / {con.session_epoch ?? "—"}</dd>
        <dt>Czas serwera</dt><dd>{con.clock?.status ?? "?"} {con.clock?.offset_hours != null ? `UTC${con.clock.offset_hours >= 0 ? "+" : ""}${con.clock.offset_hours}` : ""}</dd>
        <dt>Ostatnie błędy</dt><dd>{(con.errors || []).slice(-3).map((e: any) => (typeof e === "string" ? e : JSON.stringify(e))).join(" · ") || "brak"}</dd>
        <dt>Backend WS</dt><dd>{s.ws}</dd><dt>Wersja</dt><dd>{s.app_version} · kontrakt API {s.contract}</dd></dl></section>
      <section data-testid="diag-tf"><h4>AKTUALNOŚĆ DANYCH PER TF</h4>
        <table className="sys-tbl"><thead><tr><th>TF</th><th>ROLA</th><th>DANE</th><th>ZAMKNIĘTE</th><th>WYMAGANE</th></tr></thead>
          <tbody>{(tfm?.timeframes || []).map((t: any) => <tr key={t.tf}><td>{t.tf}</td><td>{t.role}</td><td><span className={cls("sys-st", t.data === "OK" ? "ok" : "warn")}>{t.data ?? "?"}</span></td>
            <td>{t.closed_bars ?? "—"}</td><td>{t.required ?? "—"}</td></tr>)}</tbody></table></section>
      <section data-testid="diag-resources"><h4>ZASOBY – MEMORY GOVERNOR</h4>
        {res ? (<>
          <p className="sys-note">Poziom: <span className={cls("sys-st", res.level === "OK" ? "ok" : res.level === "WARN" ? "warn" : "bad")}>{res.level}</span> {res.level_pl} ·
            RAM {res.system?.used_pct ?? "—"} % z {res.system?.total_mb != null ? Math.round(res.system.total_mb / 1024) + " GB" : "—"} · procesy {BRAND} {res.pmw_total_mb ?? "—"} MB</p>
          {/* 1.46: marka Apollo23 w etykiecie zamiast „PMW” (pole API pmw_total_mb bez zmian) */}
          <div className="sys-row" role="group" aria-label="Profil pamięci">
            {Object.keys(res.profiles || {}).filter((k) => k !== "MANUAL").map((k) => (
              <button key={k} type="button" className={cls("act", res.profile === k && "on")} aria-pressed={res.profile === k} data-testid={"res-prof-" + k}
                title={res.profiles[k]?.label} onClick={() => (res.profile === k ? undefined : setAskProf(k))}>{k}</button>))}</div>
          <p className="sys-note" data-testid="res-effective">{res.profile_pl}{res.effective_profile && res.effective_profile !== res.profile ? ` · stosowany: ${res.effective_profile} (${res.effective_profile_pl ?? "dopasowany do RAM"})` : ""}</p>
          {askProf && <div className="sys-row"><span className="sys-note">Zmienić profil na {askProf}? ({res.profiles[askProf]?.label})</span>
            <button type="button" className="act" data-testid="res-prof-confirm" onClick={() => setProfile(askProf)}>ZMIEŃ</button>
            <button type="button" className="act" onClick={() => setAskProf(null)}>ANULUJ</button></div>}
          {resErr && <p className="sys-note">{resErr}</p>}
          <table className="sys-tbl"><thead><tr><th>PROCES</th><th>RODZAJ</th><th>RAM [MB]</th><th>SZCZYT [MB]</th></tr></thead>
            <tbody>{Object.entries(res.processes || {}).map(([k, v]: any) => <tr key={k}><td>{k}</td><td>{v.kind}</td><td>{v.running ? v.rss_mb ?? "?" : "—"}</td><td>{v.peak_mb ?? "—"}</td></tr>)}</tbody></table></>)
          : <p className="sys-note">BRAK DANYCH</p>}</section>
      <section data-testid="diag-analytics"><h4>MODUŁY ANALITYCZNE</h4>
        {diag ? (<>
          <table className="sys-tbl"><thead><tr><th>MODUŁ</th><th>WERSJA</th><th>P50 [MS]</th><th>P95 [MS]</th><th>N</th></tr></thead>
            <tbody>{Object.entries(diag.versions || {}).map(([m, v]: any) => { const l = diag.latency_ms?.[m] || diag.latency_ms?.[m === "ta" ? "bollinger" : m] || {}; return (
              <tr key={m}><td>{m}</td><td>{v}</td><td>{l.p50 ?? "—"}</td><td>{l.p95 ?? "—"}</td><td>{l.n ?? 0}</td></tr>); })}</tbody></table>
          <p className="sys-note">Kolejka: {diag.queue} · policzone {diag.counters?.computed} · odrzucone przestarzałe {diag.counters?.discarded_stale} · cache {diag.counters?.cache_hits}/{diag.cache_size} ·
            timeouty {diag.counters?.timeouts} · zarchiwizowane {diag.counters?.archived ?? 0}</p>
          {(diag.errors || []).length > 0 && <ul className="sys-err">{diag.errors.map((e: any, i: number) => <li key={i}>{fmtTime(e.at, true)} {e.where}: {e.error}</li>)}</ul>}</>)
          : <p className="sys-note">BRAK DANYCH</p>}</section>
    </div>);
}
