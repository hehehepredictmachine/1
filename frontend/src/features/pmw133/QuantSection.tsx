// 1.35 PMW Quant Core – stan wspólnego silnika obliczeń i meta-modelu w istniejących miejscach diagnostyki (Koordynator decyzji)
// i treningu (Centrum treningu). Odczyt opublikowanej generacji – panel niczego nie liczy. Brak skalibrowanego wyniku pokazujemy jako
// „brak wytrenowanego modelu dla tego zdarzenia”, nigdy jako 0 % / 50 %. ASSIST: tylko po walidacji i jawnym potwierdzeniu.
import { useState } from "react";
import { apiSend } from "../../api";
import { cls, fmtTime } from "../../util";
import { num, usePoll } from "./usePoll";
import "./pmw133.css";

const MODE_TONE: Record<string, string> = { OFF: "muted", SHADOW: "info", ASSIST: "warn" };
const ST_TONE: Record<string, string> = { READY: "ok", NOT_TRAINED: "muted", INVALID_PLAN: "bad", ERROR: "bad", INCOMPATIBLE: "bad" };
const t = (s?: number | null) => (typeof s === "number" ? fmtTime(new Date(s * 1000).toISOString(), true) : "—");

export default function QuantSection({ variant }: { variant: "decision" | "training" }) {
  const st = usePoll<any>("/api/v1/quant/status", 6000);
  const ass = usePoll<any>(variant === "decision" ? "/api/v1/quant/assessment?limit=15" : null, 10000);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const d = st.data;
  const run = async (fn: () => Promise<any>, ok: (r: any) => string) => {
    setMsg(null);
    try { const r = await fn(); setMsg({ ok: true, text: ok(r) }); await st.reload(); }
    catch (e: any) { setMsg({ ok: false, text: String(e?.message || e) }); }
  };
  const snap = d?.snapshot;
  const m = d?.models || {};
  return (
    <section className={variant === "decision" ? "pmw-card" : "panel pmw-fam"} data-testid={`quant-${variant}`}>
      <h3>PMW Quant Core <span className={cls("badge", MODE_TONE[d?.mode] || "muted")} data-testid="quant-mode">{d?.mode ?? "—"}</span>
        {d?.assist_active && <span className="badge warn"> ASSIST aktywny</span>}
        <span className="pmw-sub"> wspólny snapshot danych → adaptery modeli → kontrola kontraktów → meta-model zdarzenia; execution_allowed = false</span></h3>
      {st.err && <p className="pmw-err">{st.err}</p>}
      {msg && <p className={msg.ok ? "pmw-msg" : "pmw-err"} role="status">{msg.text}</p>}
      {d && <>
        <p className="pmw-meta" data-testid="quant-data">
          Dane: <span className={cls("badge", snap?.status === "OK" ? "ok" : "warn")}>{snap?.status ?? "brak"}</span> {snap?.data_kind} · {snap?.symbol} ·
          ostatnia zamknięta świeca M1 {t(snap?.quality?.M1?.last_close_t)} · M5 {t(snap?.quality?.M5?.last_close_t)} · generacja {d.generation ?? "—"}
          ({d.complete ? "kompletna" : "niekompletna"}, cykl {num(d.cycle_ms, 0)} ms) · notowanie {snap?.quote_state ?? "—"}
        </p>
        <p className="pmw-meta" data-testid="quant-models">
          Wyniki gotowe (ważne, świeże): <b>{m.eligible ?? 0}</b> · wykluczone: <b>{m.excluded ?? 0}</b>
          {Object.entries(m.excluded_by_reason || {}).map(([k, v]) => <span key={k} className="badge muted">{k.replace("STATE_", "")} {String(v)}</span>)}
          · aliasy złożone: {m.aliases_dropped ?? 0}
        </p>
        {variant === "decision" && <>
          <div className="pmw-scroll"><table className="pmw-t" data-testid="quant-tasks"><thead><tr><th>zadanie</th><th>właściciel</th><th>stan</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th></tr></thead>
            <tbody>{Object.entries(d.tasks || {}).map(([k, v]: any) => (
              <tr key={k}><td>{k}</td><td>{v.owner}</td><td><span className={cls("badge", v.status === "OK" ? "ok" : "bad")}>{v.status}</span> {v.reason ?? ""}</td>
                <td>{num(d.timings?.[k]?.p50_ms, 1)}</td><td>{num(d.timings?.[k]?.p95_ms, 1)}</td><td>{num(d.timings?.[k]?.p99_ms, 1)}</td></tr>))}</tbody></table></div>
          <h4>Oceny setupów (Quant MetaModel, {d.mode === "ASSIST" ? "ASSIST – może tylko wstrzymać" : "SHADOW – bez wpływu"})</h4>
          <div className="pmw-scroll"><table className="pmw-t" data-testid="quant-assessments">
            <thead><tr><th>czas</th><th>silnik</th><th>strategia</th><th>kierunek</th><th>jakość danych</th><th>wynik heurystyczny</th><th>P(zdarzenia)</th><th>E[net R]</th><th>wpływ</th><th>uwagi</th></tr></thead>
            <tbody>{(ass.data?.items || []).map((a: any) => (
              <tr key={a.assessment_id}><td>{t(a.created_at)}</td><td>{a.engine}</td><td>{a.strategy}</td><td>{a.direction}</td><td>{a.data_quality?.status ?? "—"}</td>
                <td>{a.heuristic_score ?? "—"}</td>
                <td>{a.probability ? <>{num(a.probability.p, 3)} <small>{a.event_id}</small></> : <span className={cls("badge", ST_TONE[a.status] || "muted")}>{a.status === "NOT_TRAINED" ? "brak wytrenowanego modelu dla tego zdarzenia" : a.status}</span>}</td>
                <td>{a.ev?.e_net_r != null ? num(a.ev.e_net_r, 3) : "—"}</td><td>{a.influence ?? "NONE"}{a.would_hold ? <small> (wstrzymałby: {a.would_hold})</small> : null}</td>
                <td><small>{a.reason ?? (a.contributions || []).slice(0, 2).map((c: any) => `${c.input} ${num(c.logit_contribution, 2)}`).join("; ")}</small></td></tr>))}</tbody></table></div>
          {!(ass.data?.items || []).length && <p className="pmw-na">Brak ocen – oceny powstają dla kandydatów setupów obu ścieżek.</p>}
        </>}
        {variant === "training" && <>
          <h4>Dowody w ledgerze Quant (dojrzałe etykiety per zadanie EventSpec)</h4>
          <div className="pmw-scroll"><table className="pmw-t" data-testid="quant-ledger"><thead><tr><th>zadanie</th><th>zdarzenie</th><th>silnik</th><th>wiersze wg stanu</th><th>pozytywne</th><th>zakres</th></tr></thead>
            <tbody>{(d.ledger?.tasks || []).map((x: any) => (
              <tr key={x.task_hash}><td><code>{x.task_hash}</code></td><td>{x.event_id}</td><td>{x.engine}</td>
                <td>{Object.entries(x.by_status || {}).map(([k, v]) => `${k} ${v}`).join(", ")}</td><td>{x.positives}</td><td>{t(x.from)} – {t(x.to)}</td></tr>))}</tbody></table></div>
          {!(d.ledger?.tasks || []).length && <p className="pmw-na">Brak wierszy – meta-model nie ma jeszcze danych (NOT_TRAINED). Wiersze zbierają się w SHADOW z kandydatów setupów.</p>}
          <h4>Artefakty meta-modelu</h4>
          <div className="pmw-scroll"><table className="pmw-t" data-testid="quant-versions"><thead><tr><th>zadanie</th><th>wersja</th><th>status</th><th>wiersze</th><th>test: log loss / prior</th><th>ECE</th><th>niespełnione kryteria</th><th></th></tr></thead>
            <tbody>{(d.metamodel?.versions || []).map((v: any) => {
              const active = d.metamodel?.active?.[v.task_hash] === v.version;
              return (<tr key={v.version}><td><code>{v.task_hash}</code></td><td>{v.version}{active && <span className="badge ok"> aktywna</span>}</td>
                <td><span className={cls("badge", v.status === "VALIDATED_SHADOW" ? "ok" : "bad")}>{v.status}</span></td><td>{v.n_rows}</td>
                <td>{num(v.test?.log_loss, 3)} / {num(v.test?.prior_log_loss, 3)}</td><td>{num(v.test?.ece, 3)}</td><td><small>{(v.failed_gates || []).join(", ")}</small></td>
                <td>{v.status === "VALIDATED_SHADOW" && !active && <button className="link" onClick={() => run(() => apiSend("POST", "/api/v1/quant/models/activate", { task_hash: v.task_hash, version: v.version }), () => `Aktywowano ${v.version} (SHADOW).`)}>aktywuj</button>}
                  {active && <button className="link" onClick={() => run(() => apiSend("POST", "/api/v1/quant/models/rollback", { task_hash: v.task_hash }), () => "Przywrócono poprzednią wersję.")}>rollback</button>}</td></tr>);
            })}</tbody></table></div>
          <div className="pmw-form">
            <button className="btn" data-testid="quant-train" onClick={() => run(() => apiSend("POST", "/api/v1/quant/jobs", { kind: "TRAIN_METAMODEL" }), (r) => `Zadanie ${r.job_id}: ${r.state}. Trening nie aktywuje modelu.`)}>Trenuj meta-model (z ledgera)</button>
            {(d.jobs || []).slice(-3).map((j: any) => <span key={j.job_id} className="badge muted">{j.job_id} {j.state}{j.error ? ` – ${j.error}` : ""}</span>)}
          </div>
        </>}
        <div className="pmw-form" data-testid="quant-mode-form">
          {(["OFF", "SHADOW"] as const).map((x) => <button key={x} className="btn" disabled={d.mode === x} onClick={() => run(() => apiSend("POST", "/api/v1/quant/mode", { mode: x }), () => `Tryb ${x}.`)}>{x}</button>)}
          <label><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} data-testid="quant-assist-confirm" /> rozumiem: ASSIST może wstrzymać kandydata (nie tworzy zleceń, nie zmienia limitów)</label>
          <button className="btn" disabled={!confirm || d.mode === "ASSIST"} data-testid="quant-assist" onClick={() => run(() => apiSend("POST", "/api/v1/quant/mode", { mode: "ASSIST", confirm: true }), () => "Tryb ASSIST aktywny.")}>ASSIST</button>
          {!Object.keys(d.metamodel?.validated_active || {}).length && <small className="pmw-na">ASSIST niedostępny: brak aktywnego, zwalidowanego meta-modelu.</small>}
        </div>
      </>}
    </section>);
}
