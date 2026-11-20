// Centrum treningu → „Rodziny modeli 1.33” (PMW-FAM-1): 15 rodzin z trzema osiami stanu (implementacja / artefakt / użycie),
// trening (profil smoke / research / full) w osobnym procesie, aktywacja wyłącznie kliknięciem (test zgodności i próbki), rollback,
// rola OFF / SHADOW / ASSIST (ASSIST tylko APPROVED + dane REAL – sprawdza backend). READY ≠ zgoda na handel.
import { useState } from "react";
import { apiSend } from "../../api";
import { cls } from "../../util";
import { STATUS_PL, usePoll } from "./usePoll";
import "./pmw133.css";

const ART_TONE: Record<string, string> = { APPROVED: "ok", CANDIDATE: "info", TRAINING: "info", NOT_TRAINED: "muted", VALIDATION_FAILED: "bad" };

export default function FamiliesSection({ inst }: { inst: string }) {
  const cat = usePoll<any>(`/api/v1/families?instrument=${inst}`, 8000);
  const pr = usePoll<any>(`/api/v1/families/predictions?instrument=${inst}`, 15000);
  const [profile, setProfile] = useState("smoke");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const preds: Record<string, any> = Object.fromEntries((pr.data?.items || []).map((p: any) => [p.family, p]));
  const run = async (fn: () => Promise<any>, ok: (r: any) => string) => {
    setMsg(null);
    try { const r = await fn(); setMsg({ ok: true, text: ok(r) }); await Promise.all([cat.reload(), pr.reload()]); }
    catch (e: any) { setMsg({ ok: false, text: String(e?.message || e) }); }
  };
  const post = (path: string, body: any = {}) => apiSend("POST", path, { instrument: inst, ...body });
  return (
    <section className="panel pmw-fam" data-testid="families-section">
      <h3>Rodziny modeli 1.33 ({(cat.data?.items || []).length})
        <span className="pmw-sub"> {cat.data?.note}</span></h3>
      <div className="pmw-form">
        <label>profil treningu <select value={profile} onChange={(e) => setProfile(e.target.value)} data-testid="fam-profile">
          <option value="smoke">smoke (szybki test)</option><option value="research">research</option><option value="full">full</option></select></label>
        <button className="btn" data-testid="fam-train-all" onClick={() => run(() => post("/api/v1/families/train-all", { profile }), (r) => `Uruchomione: ${(r.started || []).length}, zablokowane: ${(r.blocked || []).length}, delegowane: ${(r.delegated || []).length} (${profile}).`)}>
          Trenuj wszystkie</button>
      </div>
      {msg && <p className={msg.ok ? "pmw-msg" : "pmw-err"} role="status">{msg.text}</p>}
      {cat.err && <p className="pmw-err">{cat.err}</p>}
      <div className="pmw-scroll"><table className="pmw-t" data-testid="families-table">
        <thead><tr><th>rodzina</th><th>zadanie</th><th>TF</th><th>implementacja</th><th>artefakt</th><th>użycie</th><th>prognoza</th><th>wymagane dane</th><th>akcje</th></tr></thead>
        <tbody>{(cat.data?.items || []).map((f: any) => {
          const st = f.status || {};
          const p = preds[f.id];
          const jobRunning = st.job && ["RUNNING", "QUEUED"].includes(st.job.state);
          const ext = ["TH_RF", "TH_XGB", "TH_SVM", "SEQ_GRU_EVENT"].includes(f.id);
          return (
            <tr key={f.id} data-family={f.id}>
              <td title={f.name}><b>{f.id}</b><br /><small>{f.name}</small></td>
              <td>{f.task_type}<br /><small>{f.unit}</small></td>
              <td>{f.tf ?? "—"}</td>
              <td><span className={cls("badge", st.implementation === "AVAILABLE" ? "ok" : "warn")} title={st.implementation_reason ?? ""}>{st.implementation}</span></td>
              <td><span className={cls("badge", ART_TONE[st.artifact] ?? "muted")}>{st.artifact}</span>{st.runs ? <small> · {st.runs} run.</small> : null}
                {st.last_validation && <small> · walidacja: {st.last_validation}</small>}</td>
              <td>{ext ? <span className="badge muted" title="sterowane w trainhub / modelach scalp">{st.use}</span> :
                <select aria-label={`użycie ${f.id}`} value={st.use} disabled={!st.active_run} onChange={(e) => run(() => post(`/api/v1/families/${f.id}/use`, { use: e.target.value }), () => `${f.id}: użycie ${e.target.value}.`)}>
                  {["OFF", "SHADOW", "ASSIST"].map((u) => <option key={u}>{u}</option>)}</select>}</td>
              <td>{p ? <span className={cls("badge", p.state === "READY" ? "ok" : "muted")} title={p.unavailable_reason ?? JSON.stringify(p.result ?? {}).slice(0, 200)}>{STATUS_PL[p.state] ?? p.state}</span> : "—"}</td>
              <td><small>{f.data_requirements?.kind} {f.data_requirements?.tf ?? ""}{f.data_requirements?.min_bars ? ` ≥${f.data_requirements.min_bars}` : ""}</small></td>
              <td className="pmw-acts">{!ext && <>
                {jobRunning ? <button className="link" onClick={() => run(() => post(`/api/v1/families/${f.id}/cancel`), () => `${f.id}: anulowano.`)}>Anuluj</button> :
                  <button className="link" data-act="train" disabled={st.implementation !== "AVAILABLE"} onClick={() => run(() => post(`/api/v1/families/${f.id}/train`, { profile }), () => `${f.id}: w kolejce (${profile}).`)}>Trenuj</button>}
                {st.last_run && st.last_run !== st.active_run && <button className="link" onClick={() => run(() => post(`/api/v1/families/${f.id}/activate`, { run_id: st.last_run }), () => `${f.id}: aktywowano ${st.last_run}.`)}>Aktywuj ostatni</button>}
                {st.active_run && <button className="link" onClick={() => run(() => post(`/api/v1/families/${f.id}/rollback`), () => `${f.id}: rollback.`)}>Rollback</button>}</>}
                {jobRunning && <small> · {st.job.state}</small>}</td>
            </tr>);
        })}</tbody></table></div>
      <p className="pmw-note">Osie stanu: {cat.data?.axes ? Object.entries(cat.data.axes).map(([k, v]) => `${k} = ${v}`).join(" · ") : ""}. Ciężkie modele (LSTM/GRU/PPO) trenują w osobnym środowisku .venv_deep (34_DEEP_INSTALUJ.bat).</p>
    </section>);
}
