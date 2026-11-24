// Ustawienia i diagnostyka → „Koordynator decyzji” (1.33, PMW-ARC-1): ostatnia decyzja każdej ścieżki, rezerwacje ryzyka w toku,
// intencje wykonania (deduplikacja, UNKNOWN → rekonsyliacja) i rekordy decyzji z rolami modeli. Tylko podgląd – nic tu nie wysyła zleceń.
import { useState } from "react";
import { apiGet } from "../../api";
import { cls, fmtTime } from "../../util";
import QuantSection from "./QuantSection";
import { usePoll } from "./usePoll";
import "./pmw133.css";

const VT: Record<string, string> = { ENTER: "ok", WAIT: "muted", NO_TRADE: "muted", BLOCKED: "warn" };

export default function DecisionPage() {
  const st = usePoll<any>("/api/v1/decision/status", 5000);
  const [rec, setRec] = useState<any>(null);
  const d = st.data;
  return (
    <div className="pmw-page" data-testid="page-decyzje">
      <header className="pmw-head">
        <h2>Koordynator decyzji (PMW-ARC-1)</h2>
        <span className="pmw-sub">Jedna logika dla ścieżek ACTIVE i SCALPING/HEDGING: role modeli OBSERVE / ASSIST / REQUIRED, wspólna atomowa rezerwacja limitów portfela,
          intencje wykonania z deduplikacją. Rezerwacja odmawia tylko nowego wejścia ponad Twój limit – nie jest blokadą wykonania.</span>
      </header>
      {st.err && <p className="pmw-err">{st.err}</p>}
      <div className="pmw-grid two">
        {(["ACTIVE", "SH"] as const).map((p) => {
          const l = d?.last?.[p];
          return (
            <section key={p} className="pmw-card" data-testid={`dec-last-${p}`}>
              <h3>Ostatnia decyzja – {p === "ACTIVE" ? "ACTIVE (S01–S12)" : "SCALPING / HEDGING"}</h3>
              {l ? <><p><span className={cls("badge", VT[l.final_verdict])}>{l.final_verdict}</span> {fmtTime(l.created_at, true)} · {l.record_id}</p>
                <p className="pmw-meta">{(l.reason_codes || []).slice(-6).join(", ") || "bez kodów blokady"}</p></> : <p className="pmw-na">Brak decyzji od startu.</p>}
            </section>);
        })}
      </div>
      <QuantSection variant="decision" />
      <section className="pmw-card" data-testid="dec-reservations">
        <h3>Rezerwacje ryzyka w toku ({(d?.reservations_live || []).length})</h3>
        <table className="pmw-t"><thead><tr><th>ścieżka</th><th>przedmiot</th><th>tryb</th><th>ryzyko</th><th>stan</th><th>od</th></tr></thead>
          <tbody>{(d?.reservations_live || []).map((r: any) => (
            <tr key={r.reservation_id}><td>{r.path}</td><td>{r.subject}</td><td>{r.mode}</td><td>{r.risk_money ?? "—"}</td><td>{r.state}</td><td>{fmtTime(r.created_at, true)}</td></tr>))}</tbody></table>
        {!(d?.reservations_live || []).length && <p className="pmw-na">Brak – żadne nowe wejście nie jest w trakcie wysyłki.</p>}
      </section>
      <section className="pmw-card" data-testid="dec-intents">
        <h3>Intencje wykonania (ostatnie {(d?.intents || []).length})</h3>
        <table className="pmw-t"><thead><tr><th>czas</th><th>ścieżka</th><th>tryb</th><th>strona</th><th>wolumen</th><th>stan</th><th>źródło</th></tr></thead>
          <tbody>{(d?.intents || []).map((i: any) => (
            <tr key={i.intent_id}><td>{fmtTime(i.created_at, true)}</td><td>{i.path}</td><td>{i.mode}</td><td>{i.side}</td><td>{i.volume}</td>
              <td><span className={cls("badge", ["FILLED", "PARTIAL", "RECONCILED_FILLED"].includes(i.state) ? "ok" : i.state === "UNKNOWN" ? "bad" : "muted")}>{i.state}</span></td>
              <td>{i.source_ref ?? "—"}</td></tr>))}</tbody></table>
      </section>
      <section className="pmw-card" data-testid="dec-records">
        <h3>Rekordy decyzji (ostatnie {(d?.records || []).length})</h3>
        <table className="pmw-t"><thead><tr><th>czas</th><th>ścieżka</th><th>strategia</th><th>kierunek</th><th>kandydat</th><th>wynik</th><th>powody</th><th></th></tr></thead>
          <tbody>{(d?.records || []).map((r: any) => (
            <tr key={r.record_id}><td>{fmtTime(r.created_at, true)}</td><td>{r.path}</td><td>{r.strategy_id}</td><td>{r.direction}</td>
              <td>{r.base_verdict}</td><td><span className={cls("badge", VT[r.final_verdict])}>{r.final_verdict}</span></td>
              <td><small>{(() => { try { return JSON.parse(r.reason_codes || "[]").slice(-4).join(", "); } catch { return ""; } })()}</small></td>
              <td><button className="link" onClick={() => apiGet(`/api/v1/decision/records/${r.record_id}`).then(setRec).catch(() => setRec(null))}>szczegóły</button></td></tr>))}</tbody></table>
      </section>
      {rec && <section className="pmw-card" data-testid="dec-record">
        <h3>Rekord {rec.record_id} <button className="link" onClick={() => setRec(null)}>zamknij</button></h3>
        <table className="pmw-t"><thead><tr><th>model</th><th>rola</th><th>stan</th><th>wpływ</th><th>uwagi</th></tr></thead>
          <tbody>{(rec.models || []).map((m: any) => <tr key={m.model_id}><td>{m.model_id}</td><td>{m.role}</td><td>{m.state}</td><td>{m.influence}</td><td>{m.reason ?? ""}</td></tr>)}</tbody></table>
        {!(rec.models || []).length && <p className="pmw-na">Bez modeli w roli ASSIST/REQUIRED – decyzja jak w 1.32.</p>}
        <p className="pmw-meta">Kody: {(rec.reason_codes || []).join(", ") || "—"} · hash wejść {rec.inputs_hash}</p>
      </section>}
    </div>);
}
