// DIAGNOSTYKA (S6 §3.4) – treść DiagnosticsPage z 1.41.0 (pages/AnalyticsPages.tsx) przeniesiona 1:1: te same źródła
// (GET /api/v1/analytics/diagnostics co 5 s, GET /api/v1/timeframes, stan połączenia ze store), te same pola. Pominięta tylko
// sekcja „Inne rynki” (podgląd rynków starego UI, nie diagnostyka).
import { useEffect, useState } from "react";
import { apiGet } from "../../api";
import { useStore } from "../../store";
import { cls, fmtTime } from "../../util";

const tone = (st?: string) => (st === "CONNECTED" || st === "OK" ? "ok" : st === "ERROR" || st === "FAILED" || st === "DISCONNECTED" ? "bad" : "warn");

export default function DiagnosticsPanel() {
  const { s } = useStore();
  const [diag, setDiag] = useState<any>(null);
  const [tfm, setTfm] = useState<any>(null);
  const load = () => {
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
