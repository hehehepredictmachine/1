import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

export default function AgentDrawer({ onClose }: { onClose: () => void }) {
  const { s } = useStore();
  const st = s.agent || {};
  const last = s.agent_last;
  const rec = last?.record;
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [mem, setMem] = useState<any[]>([]);
  useEffect(() => {
    apiGet("/api/v1/agent").then((r) => setRuns(r.runs || [])).catch(() => undefined);
    apiGet("/api/v1/agent/memory").then(setMem).catch(() => undefined);
  }, [s.agent_last_any?.run_id, st.state]);
  const ask = async () => {
    setMsg(null);
    try {
      const r = await apiSend("POST", "/api/v1/agent/ask", { question: q });
      setMsg(r.queued ? "Pytanie przekazane agentowi." : "Agent niedostępny.");
      setQ("");
    } catch (e: any) {
      setMsg(String(e.message || e));
    }
  };
  const analyze = async () => {
    try {
      const r = await apiSend("POST", "/api/v1/agent/analyze");
      setMsg(r.queued ? "Analiza zlecona." : "Agent niedostępny.");
    } catch (e: any) {
      setMsg(String(e.message || e));
    }
  };
  const setMemStatus = async (id: number, status: string) => {
    await apiSend("POST", `/api/v1/agent/memory/${id}`, { status });
    apiGet("/api/v1/agent/memory").then(setMem);
  };
  const lastAny = s.agent_last_any;
  return (
    <aside className="drawer">
      <div className="drawer-head">
        <b>✦ Agent Claude</b>
        <span className={cls("badge", st.state === "OK" || st.state === "IDLE" ? "ok" : st.state === "RUNNING" ? "warn" : "bad")}>{st.state}</span>
        <span className="spacer" />
        <button className="icon" onClick={onClose}>✕</button>
      </div>
      <div className="drawer-body">
        <div className="kv">
          <div><label>Model</label><b>{st.model ?? "nie wybrano"}</b></div>
          <div><label>Klucz</label><b>{st.key_source === "MISSING" ? "brak" : `${st.key_source} ${st.key_masked ?? ""}`}</b></div>
          <div><label>Koszt dziś (szac.)</label><b>{fmtNum(st.spent_today_usd_estimate, 3)} / {fmtNum(st.daily_budget_usd)} USD</b></div>
          <div><label>Rola AI</label><b>{st.gate_policy ?? (st.required_for_entry ? "REQUIRED" : "ADVISORY")}</b></div>
          <div><label>Ostatnia analiza</label><b>{st.last_run ? `${fmtTime(st.last_run.finished_at)} · ${st.last_run.status} · ${st.last_run.latency_ms} ms` : "—"}</b></div>
          <div><label>Tokeny (in/out)</label><b>{st.last_run ? `${st.last_run.input_tokens}/${st.last_run.output_tokens}` : "—"}</b></div>
        </div>
        {st.detail && <div className="note warn">Status: {st.detail}</div>}
        {lastAny && lastAny.status !== "OK" && <div className="note bad">Ostatni przebieg: {lastAny.status} {lastAny.error ?? ""} – brak decyzji AI (nie zastępujemy jej fikcyjną odpowiedzią).</div>}
        <h4>Ostatnia ocena AI {rec ? <small>({rec.decision_id}, snapshot {rec.snapshot_id?.slice(0, 12)}…, ważna do {fmtTime(rec.expires_at_utc)})</small> : null}</h4>
        {rec ? (
          <div className="ai-rec">
            <div className="row"><span className={cls("badge", rec.proposed_action === "BUY" ? "ok" : rec.proposed_action === "SELL" ? "bad" : "muted")}>{rec.proposed_action}</span>
              <span>kierunek {rec.analysis_direction} · etap {rec.signal_stage} · {rec.strategy_id ?? "—"}</span></div>
            <p>{rec.explanation_pl}</p>
            {rec.answer_pl && <p className="answer"><b>Odpowiedź:</b> {rec.answer_pl}</p>}
            {(["bullish", "bearish", "wait"] as const).map((k) => (
              <div key={k} className="scen"><b>{{ bullish: "Scenariusz wzrostowy", bearish: "Scenariusz spadkowy", wait: "Oczekiwanie" }[k]}:</b> {rec.scenarios[k].summary}
                {rec.scenarios[k].activation.length > 0 && <div className="small">Aktywacja: {rec.scenarios[k].activation.join("; ")}</div>}
                {rec.scenarios[k].invalidation.length > 0 && <div className="small">Unieważnienie: {rec.scenarios[k].invalidation.join("; ")}</div>}
              </div>
            ))}
            {rec.contradictions.length > 0 && <div className="small warn">Sprzeczności: {rec.contradictions.join("; ")}</div>}
            {rec.missing_data.length > 0 && <div className="small warn">Brakujące dane: {rec.missing_data.join("; ")}</div>}
            <div className="small muted">Dowody: {rec.evidence_refs.slice(0, 8).join(", ")}</div>
            <div className="small muted">model {rec.model_id} · prompt {rec.prompt_version}</div>
          </div>
        ) : <div className="muted">Brak ważnej analizy AI.</div>}
        <h4>Pytanie do bieżącego snapshotu</h4>
        <textarea value={q} onChange={(e) => setQ(e.target.value)} maxLength={2000} placeholder="np. Dlaczego setup nie jest potwierdzony? (pytanie nie zmienia blokad)" />
        <div className="row"><button className="btn" disabled={q.trim().length < 2} onClick={ask}>Zapytaj</button>
          <button className="btn ghost" onClick={analyze}>Analizuj teraz</button>{msg && <span className="small">{msg}</span>}</div>
        <h4>Propozycje playbooka i wnioski (nie zmieniają strategii LIVE)</h4>
        <ul className="list">
          {mem.slice(0, 20).map((m) => {
            const c = JSON.parse(m.content_json || "{}");
            return (
              <li key={m.id}><span className="tag">{m.kind}</span> {c.title ? <b>{c.title}: </b> : null}{c.text || c.change}
                <span className="tag muted">{m.status}</span>
                {m.kind === "PLAYBOOK_PROPOSAL" && m.status === "PROPOSED" && <>
                  <button className="btn tiny" onClick={() => setMemStatus(m.id, "ACCEPTED_FOR_OOS_TEST")}>do testu OOS</button>
                  <button className="btn tiny ghost" onClick={() => setMemStatus(m.id, "REJECTED")}>odrzuć</button></>}
              </li>
            );
          })}
          {!mem.length && <li className="muted">Brak zapisanych wniosków.</li>}
        </ul>
        <h4>Historia przebiegów</h4>
        <table className="tbl small">
          <thead><tr><th>Czas</th><th>Wyzwalacz</th><th>Status</th><th>ms</th><th>USD≈</th></tr></thead>
          <tbody>{runs.slice(0, 15).map((r) => <tr key={r.run_id}><td>{fmtTime(r.started_at)}</td><td>{r.trigger}</td>
            <td title={r.error_code || ""}>{r.status}{r.error_code ? ` (${r.error_code})` : ""}</td><td>{r.latency_ms ?? ""}</td><td>{r.est_cost_usd ? fmtNum(r.est_cost_usd, 4) : ""}</td></tr>)}</tbody>
        </table>
      </div>
    </aside>
  );
}
