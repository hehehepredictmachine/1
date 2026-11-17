import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const ST_PL: Record<string, string> = {
  COLLECTING: "zbiera próbki", WAITING_FOR_LABELS: "czeka na etykiety (wyniki setupów)", TRAINING: "trening", VALIDATING: "walidacja",
  SHADOW: "model w cieniu (nie wpływa na decyzje)", ACTIVE: "model aktywny (ASSIST)", DEGRADED: "model zdegradowany – fallback do strategii", ERROR: "błąd",
};

/** 12B: Decision Tree + XGBoost status, data counts, versions, validation, explanations; buttons call the real backend. */
export default function MLPanel({ index }: { index: number }) {
  const { s, refresh } = useStore();
  const ml = s.ml || {};
  const [full, setFull] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [hist, setHist] = useState(false);
  const [expl, setExpl] = useState<any>(null);
  const load = () => apiGet("/api/v1/ml/status").then(setFull).catch(() => undefined);
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, []);
  const sel = s.auto?.selected;
  const pred = s.decision?.ml;
  useEffect(() => {
    if (!sel?.setup_id || !ml.champion) { setExpl(null); return; }
    apiGet(`/api/v1/ml/explain?setup_id=${encodeURIComponent(sel.setup_id)}&version=${sel.version}`).then(setExpl).catch(() => setExpl(null));
  }, [sel?.setup_id, sel?.version, ml.champion]);
  const act = async (path: string, body: any, label: string) => {
    setMsg(null);
    try {
      const r: any = await apiSend("POST", path, body);
      setMsg(`${label}: ${r?.started === false ? "nie uruchomiono – " + (r.reason || "") + (r.reasons ? " " + r.reasons.join(", ") : "") : r?.cancelled === false ? r.reason : "OK"}`);
      await refresh();
      load();
    } catch (e: any) {
      setMsg(`${label}: ${String(e?.message || e)}`);
    }
  };
  const f = full || ml;
  const c = f.counts || {};
  const req = f.required || {};
  const rep = full?.report;
  const st = ml.status ?? f.status;
  return (
    <div className="panel ml-panel" data-testid="ml-panel">
      <div className="panel-head">
        <span className="pnum">{index}</span>
        <span className="ptitle">ML · DECISION TREE + XGBOOST</span>
        <span className={cls("badge", st === "ACTIVE" || st === "SHADOW" ? "ok" : st === "ERROR" || st === "DEGRADED" ? "bad" : "warn")}>{st}</span>
        <span className="psub">{ST_PL[st] ?? ""}</span>
        <span className="spacer" />
        <span className="badge">tryb ML: {ml.mode ?? f.mode}</span>
      </div>
      <div className="ml-body">
        <div className="ml-cols">
          <div>
            <h5>Dane</h5>
            <div className="kv">
              <div><label>Unikalne setupy z etykietą</label><b>{c.unique_setups ?? 0}</b> / {req.min_labeled_setups}</div>
              <div><label>Klasa 1 / klasa 0</label><b>{c.pos ?? 0} / {c.neg ?? 0}</b> (min {req.min_per_class} każda)</div>
              <div><label>Oczekujące na wynik</label><b>{c.by_status?.PENDING ?? 0}</b></div>
              <div><label>Bez wejścia / niejednoznaczne / braki</label><b>{c.by_status?.NO_ENTRY ?? 0} / {c.by_status?.AMBIGUOUS ?? 0} / {(c.by_status?.MISSING_DATA ?? 0) + (c.by_status?.UNRESOLVED ?? 0)}</b></div>
              <div><label>Backfill (APPROX, poza treningiem)</label><b>{c.approx_excluded ?? 0}</b></div>
              <div><label>Wiek ostatniego ticka</label><b>{f.last_tick_age_s != null ? `${fmtNum(f.last_tick_age_s, 1)} s` : "brak danych"}</b></div>
            </div>
            <div className="ml-progress" role="progressbar" aria-valuenow={Math.round((f.progress ?? 0) * 100)}><i style={{ width: `${(f.progress ?? 0) * 100}%` }} /></div>
            <small className="muted">{f.readiness?.note}</small>
            {(f.readiness?.reasons || []).length > 0 && <ul className="cl-why">{f.readiness.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>}
          </div>
          <div>
            <h5>Modele</h5>
            <div className="kv">
              <div><label>Champion</label><b>{f.champion ?? "brak (strategie bez ML)"}</b> {f.champion_family ?? ""}</div>
              <div><label>Challengerzy (cień)</label><b>{(f.challengers || []).join(", ") || "brak"}</b></div>
              <div><label>Dryf / jakość</label><b>{f.drift?.status ?? "—"}</b> {(f.drift?.reasons || []).join(", ")}</div>
              <div><label>Brier: test / na żywo</label><b>{f.drift?.test_brier ?? "—"} / {f.drift?.live_brier ?? "N/A"}</b></div>
            </div>
            {rep ? (
              <table className="tbl small">
                <thead><tr><th>Model</th><th>Brier</th><th>LogLoss</th><th>PR-AUC</th><th>ECE</th><th>Kalibr.</th><th>Trans.</th><th>Śr. R</th><th>Max DD R</th></tr></thead>
                <tbody>
                  {Object.entries(rep.models || {}).map(([fam, m]: any) => (
                    <tr key={fam}><td>{fam === "DECISION_TREE" ? "Drzewo" : "XGBoost"}</td><td>{m.test?.brier}</td><td>{m.test?.log_loss}</td><td>{m.test?.pr_auc}</td>
                      <td>{m.test?.ece}</td><td>{m.calibration}</td><td>{m.policy?.trades}</td><td>{m.policy?.avg_r}</td><td>{m.policy?.max_dd_r}</td></tr>))}
                  <tr className="muted"><td>Bazowy (częstość)</td><td>{rep.baselines?.base_rate?.brier}</td><td>{rep.baselines?.base_rate?.log_loss}</td><td>—</td><td>—</td><td>—</td>
                    <td>{rep.baselines?.no_ml_policy?.trades}</td><td>{rep.baselines?.no_ml_policy?.avg_r}</td><td>{rep.baselines?.no_ml_policy?.max_dd_r}</td></tr>
                </tbody>
              </table>
            ) : <p className="muted small">Brak zakończonego treningu – brak wyników walidacji (nic nie jest symulowane).</p>}
            {rep && <small className="muted">Walidacja chronologiczna z purgingiem/embargo {rep.validation?.embargo_minutes} min; bloki {JSON.stringify(rep.validation?.counts)}; test {rep.validation?.windows?.test?.join(" → ")}</small>}
          </div>
          <div>
            <h5>Wybrany setup</h5>
            {pred ? (
              <div className="kv">
                <div><label>Gotowość</label><b>{pred.readiness}</b> {pred.uncertainty_reason ?? ""}</div>
                <div><label>Prawdopodobieństwo skalibrowane</label><b>{pred.calibrated_probability ?? "N/A"}</b> (próg {pred.threshold ?? "—"})</div>
                <div><label>Surowy wynik</label><b>{pred.raw_score ?? "—"}</b> · kalibracja {pred.calibration_status}</div>
                <div><label>Cel</label><small>{pred.target_definition}</small></div>
              </div>
            ) : <p className="muted small">Brak wybranego setupu lub ML wyłączone.</p>}
            {expl?.available && expl.explanation?.steps && (
              <details open><summary>Ścieżka drzewa ({expl.explanation.steps.length} kroków, liść {expl.explanation.leaf_samples} obs.)</summary>
                <ol className="small">{expl.explanation.steps.map((st2: any) => <li key={st2.node}>{st2.feature} = {st2.value ?? "brak"} → {st2.branch} {st2.threshold}</li>)}</ol>
                <small className="muted">{expl.explanation.note}</small></details>)}
            {expl?.available && expl.explanation?.top && (
              <details open><summary>Wkłady cech XGBoost (TreeSHAP)</summary>
                <ul className="small">{expl.explanation.top.map((t: any) => <li key={t.feature}>{t.feature}: {t.contribution > 0 ? "+" : ""}{t.contribution}</li>)}</ul>
                <small className="muted">{expl.explanation.note}</small></details>)}
            {expl?.challenger && <small className="muted">Challenger {expl.challenger.model_id} ({expl.challenger.family}) ocenia w cieniu.</small>}
          </div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => act("/api/v1/ml/collect", { on: !f.collect }, f.collect ? "Zbieranie wyłączone" : "Zbieraj dane")}>
            {f.collect ? "Zbieraj dane ✓ (wyłącz)" : "Zbieraj dane"}</button>
          <button className="btn" onClick={() => act("/api/v1/ml/train", {}, "Trenuj teraz")} disabled={f.training_paused}>Trenuj teraz</button>
          <button className="btn ghost" onClick={() => act("/api/v1/ml/pause", { on: !f.training_paused }, f.training_paused ? "Trening wznowiony" : "Wstrzymaj trening")}>
            {f.training_paused ? "Wznów trening" : "Wstrzymaj trening"}</button>
          <button className="btn ghost" onClick={() => setHist(!hist)}>Historia modeli</button>
          <button className="btn ghost danger" onClick={() => act("/api/v1/ml/rollback", {}, "Przywróć poprzedni model")}>Przywróć poprzedni model</button>
          <button className="btn ghost" title="Historia z terminala MT5, ta sama logika strategii; jakość APPROX – domyślnie poza treningiem"
            onClick={() => act("/api/v1/ml/backfill", { days: 30 }, "Backfill 30 dni")}>Backfill z MT5 (30 dni)</button>
          {f.backfill?.status && f.backfill.status !== "IDLE" && <span className="badge">backfill: {f.backfill.status}{f.backfill.progress ? ` ${f.backfill.progress.step}/${f.backfill.progress.steps}` : ""}</span>}
        </div>
        {msg && <div className="note" data-testid="ml-msg">{msg}</div>}
        {hist && (
          <div className="ml-hist">
            <table className="tbl small">
              <thead><tr><th>Model</th><th>Rodzina</th><th>Status</th><th>Utworzony</th><th>Brier</th><th>Promocja / powody</th></tr></thead>
              <tbody>{(full?.models || []).map((m: any) => (
                <tr key={m.model_id}><td>{m.model_id}</td><td>{m.family}</td><td>{m.status}</td><td>{fmtTime(m.created_at, true)}</td><td>{m.test?.brier}</td>
                  <td title={(m.promotion?.reasons || []).join(", ")}>{m.promotion?.passed ? "spełnia kryteria" : (m.promotion?.reasons || []).slice(0, 2).join(", ")}</td></tr>))}
                {!full?.models?.length && <tr><td colSpan={6} className="muted">Brak modeli.</td></tr>}</tbody>
            </table>
            <ul className="small">{(full?.events || []).slice(0, 10).map((e: any) => <li key={e.id}>{fmtTime(e.at, true)} {e.kind} {e.model_id ?? ""}</li>)}</ul>
          </div>
        )}
      </div>
    </div>
  );
}
