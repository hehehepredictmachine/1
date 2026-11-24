// 1.41 panels - every value and every button comes from / goes to the backend (no front-end strategy list, no fake percentages):
//  (1.46: the unused 1.41 BasketsPanel - OTC profile button, OTC payout / payoff, Gold OTC declaration - was removed; OTC is retired and
//   the baskets live in the FOREX screens: 2 profiles / 6 baskets / 60 strategies)
//  ResearchModulesPanel  six MQL5-derived modules with separate state axes (/api/v1/research-modules*)
//  TabICLCard            TabICLv2 confidence estimator of Quant (/api/v1/quant/tabicl*)
//  ComponentsCards       Training Center TH_SDFORMERFLOW + ETC_LOG_CHANNEL (/api/v1/trainhub/components*)
import { useEffect, useState } from "react";
import { apiGet, apiSend, apiUpload } from "../api";
import { cls, fmtNum } from "../util";

const TONE: Record<string, string> = { READY: "ok", SIGNAL: "ok", HEDGE_PLAN: "ok", RUNNING: "ok", ACTIVE: "ok", PREDICTION_ACTIVE: "ok", FEATURES_ACTIVE: "ok",
  RAW_SCORE_ACTIVE: "ok", COMPATIBLE: "ok", DONE: "ok", LIVE: "ok", NO_SETUP: "muted", NO_EXPOSURE: "muted", NO_HEDGE: "muted", NOT_SELECTED: "muted",
  DISABLED: "muted", STOPPED: "muted", NOT_REQUIRED: "muted", NOT_APPLICABLE: "muted", WARMUP: "warn", WAITING_FOR_DATA: "warn", WAITING_FOR_OTC_FEED: "warn",
  WAITING_FOR_LABELS: "warn", COLD_START: "warn", MISSING: "warn", TRAINING: "warn", DEGRADED: "warn", CONFLICT: "warn", DUPLICATE_EVENT: "muted",
  COOLDOWN: "muted", LIMIT: "warn", ERROR: "bad", FAILED: "bad", INCOMPATIBLE: "bad", NOT_INSTALLED: "warn" };
const Badge = ({ s }: { s?: string | null }) => <span className={cls("badge", TONE[s || ""] || "muted")}>{s || "—"}</span>;
const errText = (e: any) => String(e?.message || e).slice(0, 300);

function useLoad<T = any>(path: string, every = 10000): [T | null, string | null, () => void] {
  const [d, setD] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => apiGet<T>(path).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(errText(e)));
  useEffect(() => { load(); const t = setInterval(load, every); return () => clearInterval(t); }, [path]);  // eslint-disable-line react-hooks/exhaustive-deps
  return [d, err, load];
}

// ============================================================================ research modules
const MOD_PL: Record<string, string> = { sdformerflow: "SDformerFlow", cellular_feature_graph: "Graf cech (Cellular 10K)", coa_coyote: "COA (Coyote)",
  bchimp: "BChimp", g7_smc_radar: "G7 SMC Radar", exponential_trend_channel: "Exponential Trend Channel" };

export function ResearchModulesPanel() {
  const [d, err, load] = useLoad<any>("/api/v1/research-modules", 8000);
  const [msg, setMsg] = useState<string | null>(null);
  const act = (p: Promise<any>, ok: string) => p.then(() => { setMsg(ok); load(); }).catch((e) => setMsg(errText(e)));
  return (
    <div className="pmw141" data-testid="research-panel">
      {err && <p className="err">{err}</p>}
      {/* 1.46: no loop data (503 / before the first read) is "brak danych", not "0 cykli, błędy 0" */}
      <p className="small muted">{d?.semantics} · polityka {d?.activation_policy} · pętla: {d?.loop ? `${d.loop.cycles ?? "—"} cykli, błędy ${d.loop.errors ?? "—"}` : "brak danych"}</p>
      <div className="table-wrap"><table className="tbl small"><thead><tr><th>Moduł</th><th>Wł.</th><th>Runtime</th><th>Artefakt</th><th>Udział</th><th>Ostatnio</th><th>Szczegóły</th></tr></thead>
        <tbody>{Object.values(d?.modules || {}).map((m: any) => (
          <tr key={m.module_id} data-testid={`rm-${m.module_id}`}><td><b>{MOD_PL[m.module_id] || m.module_id}</b><div className="muted">{m.implementation_id} · {m.author}</div></td>
            <td><input type="checkbox" checked={!!m.enabled} onChange={(e) => act(apiSend("PUT", "/api/v1/research-modules/settings", { modules: { [m.module_id]: { enabled: e.target.checked } } }), `${m.module_id}: ${e.target.checked ? "wł." : "wył."}`)} /></td>
            <td><Badge s={m.runtime_state} /></td><td><Badge s={m.artifact_state} /></td><td><Badge s={m.contribution_state} /></td><td>{m.last_update || "—"}</td>
            <td className="muted" style={{ maxWidth: 420, whiteSpace: "normal" }}>{detail(m)}</td></tr>))}</tbody></table></div>
      {d?.composite && <p className="small">Kompozyt badawczy: wersja <b>{d.composite.version}</b> ({d.composite.status}) wagi [{(d.composite.weights || []).map((w: number) => fmtNum(w, 2)).join(", ")}] dla {(d.composite.names || []).join(", ")}</p>}
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn tiny" onClick={() => act(apiSend("POST", "/api/v1/research-modules/optimizer/run"), "optymalizacja COA → BChimp wykonana")}>Optymalizuj teraz (COA → BChimp)</button>
        <button className="btn tiny ghost" onClick={() => act(apiSend("POST", "/api/v1/research-modules/parameters/rollback"), "przywrócono poprzednie parametry")}>Cofnij parametry</button>
        <button className="btn tiny" onClick={() => act(apiSend("POST", "/api/v1/research-modules/sdformerflow/train", { op: "from_scratch" }), "trening SDformerFlow uruchomiony")}>Trenuj SDformerFlow</button>
        <button className="btn tiny ghost" onClick={() => act(apiSend("POST", "/api/v1/research-modules/sdformerflow/cancel"), "anulowanie zgłoszone")}>Anuluj trening</button>
      </div>
      {msg && <p className="small muted">{msg}</p>}
    </div>);
}

function detail(m: any): string {
  const d = m.detail || {};
  if (m.module_id === "exponential_trend_channel" && d.channel) return `okno ${d.channel.bars} · fit ${fmtNum(d.channel.fit, 3)} · kanał ${fmtNum(d.channel.lower, 2)}–${fmtNum(d.channel.upper, 2)} · ${d.parameter_version}`;
  if (m.module_id === "g7_smc_radar" && d.rule_confluence_score != null) return `confluence ${d.rule_confluence_score}/100 (reguła, nie prawdopodob.) · pokrycie ${fmtNum(d.coverage, 2)} · ${d.reason || ""}`;
  if (m.module_id === "cellular_feature_graph" && d.targets) return Object.entries(d.targets).map(([k, v]: any) => `${k}: ${fmtNum(v.raw_score, 3)} (v${v.model_update_version}, oczek. ${v.pending})`).join(" · ");
  if (m.module_id === "sdformerflow") return d.result ? `run ${d.active_run} · DIRECTION_SCORE_RAW ${fmtNum(d.result.direction_score_raw, 3)} · ${fmtNum(d.result.ms, 0)} ms` : (d.reason || d.state || "");
  return "";
}

// ============================================================================ TabICLv2
export function TabICLCard() {
  const [d, err, load] = useLoad<any>("/api/v1/quant/tabicl", 10000);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="panel" data-testid="tabicl-card">
      <div className="panel-head"><b>TabICLv2 – estymator confidence Quant</b> <Badge s={d?.state} /></div>
      {err && <p className="err">{err}</p>}
      <p className="small muted">confidence_score = 100 × p_event_raw (UNCALIBRATED) zdarzenia z EventSpec; kontekst z ledgera lub przyczynowej rekonstrukcji. Brak kontekstu = brak wartości (nie 50%).</p>
      <pre className="small" style={{ whiteSpace: "pre-wrap", maxHeight: 160, overflow: "auto" }}>{d ? JSON.stringify({ state: d.state, reason: d.reason, contexts: d.contexts, reconstruction: d.reconstruction, worker: d.worker }, null, 1) : "…"}</pre>
      <div className="row wrap" style={{ gap: 6 }}>
        <button className="btn tiny" onClick={() => apiSend("POST", "/api/v1/quant/tabicl/install").then(() => { setMsg("instalacja uruchomiona"); load(); }).catch((e) => setMsg(errText(e)))}>Zainstaluj / napraw</button>
        <button className="btn tiny ghost" onClick={() => apiSend("POST", "/api/v1/quant/tabicl/reconstruct").then(() => { setMsg("rekonstrukcja kontekstu uruchomiona"); load(); }).catch((e) => setMsg(errText(e)))}>Odbuduj kontekst</button>
      </div>
      {msg && <p className="small muted">{msg}</p>}
    </div>);
}

// ============================================================================ Training Center components
export function ComponentsCards() {
  const [d, err, load] = useLoad<any>("/api/v1/trainhub/components", 5000);
  const [msg, setMsg] = useState<string | null>(null);
  const call = (p: Promise<any>, ok: string) => p.then((r) => { setMsg(`${ok}${r?.reason ? ` – ${r.reason}` : ""}`); load(); }).catch((e) => setMsg(errText(e)));
  const job = (cid: string, body: any, ok: string) => call(apiSend("POST", `/api/v1/trainhub/components/${cid}/jobs`, body), ok);
  const imp = (cid: string) => { const i = document.createElement("input"); i.type = "file"; i.accept = ".zip";
    i.onchange = () => { const f = i.files?.[0]; if (f) call(apiUpload(`/api/v1/trainhub/components/${cid}/import`, f), "zaimportowano"); }; i.click(); };
  return (
    <section className="tc-panel" data-testid="tc-components">
      <div className="panel-head"><b>Komponenty 1.41: SDformerFlow (wagi) i Exponential Trend Channel (transformacja cech)</b>
        <span className="muted small">polityka {d?.activation_policy} · profil {d?.profile} · jedno ciężkie zadanie naraz</span></div>
      {err && <p className="err">{err}</p>}
      {(d?.components || []).map((c: any) => (
        <div key={c.component_id} className="panel" data-testid={`tc-comp-${c.component_id}`}>
          <div className="panel-head"><b>{c.component_id}</b> <span className="muted small">{c.kind} · {c.implementation_id} · {c.runtime_backend}</span>
            {c.runtime_state && <Badge s={c.runtime_state} />}</div>
          <p className="small">Aktywna wersja: <b>{c.active_version || "brak"}</b> {c.previous_version ? `(poprzednia ${c.previous_version})` : ""} · cel {c.target_id} · horyzont {c.horizon} · kontekst {c.market_context_key || "—"}</p>
          {c.job && <p className="small">Zadanie: <Badge s={c.job.state} /> {c.job.kind || ""} {c.job.op || ""} {c.job.reason || ""}
            {c.job.result?.steps != null && ` · kroki ${c.job.result.steps} · epoki ${c.job.result.epochs_done}`}
            {c.job.computation && ` · strata ${fmtNum(c.job.computation.incumbent_loss, 4)} → ${fmtNum(c.job.computation.candidate_loss, 4)} (${c.job.computation.winner}, oceny ${c.job.computation.evaluations?.join("+")})`}
            {c.job.activation && <> · aktywacja <Badge s={c.job.activation.state} /> {c.job.activation.reason || ""}</>}
            {c.job.error && <span className="err"> {c.job.error}</span>}</p>}
          <div className="row wrap" style={{ gap: 6 }}>
            {c.component_id === "TH_SDFORMERFLOW" ? <>
              <button className="btn tiny ghost" onClick={() => job(c.component_id, { kind: "DATASET" }, "dataset przygotowany")}>Przygotuj dane</button>
              <button className="btn tiny" onClick={() => job(c.component_id, { kind: "TRAIN", op: "from_scratch" }, "trening od zera uruchomiony")}>Trenuj od zera</button>
              <button className="btn tiny" disabled={!c.active_version} onClick={() => job(c.component_id, { kind: "TRAIN", op: "fine_tune" }, "fine-tune uruchomiony")}>Fine-tune</button>
              <button className="btn tiny" disabled={!c.active_version} onClick={() => job(c.component_id, { kind: "TRAIN", op: "resume" }, "wznowienie uruchomione")}>Wznów</button></> : <>
              <button className="btn tiny ghost" onClick={() => job(c.component_id, { kind: "DATASET" }, "cechy przygotowane")}>Przygotuj cechy</button>
              <button className="btn tiny" onClick={() => job(c.component_id, { kind: "OPTIMIZE" }, "optymalizacja uruchomiona")}>Optymalizuj parametry</button></>}
            <button className="btn tiny ghost" onClick={() => call(apiSend("POST", `/api/v1/trainhub/components/${c.component_id}/cancel`), "anulowanie zgłoszone")}>Anuluj</button>
            <button className="btn tiny ghost" onClick={() => call(apiSend("POST", `/api/v1/trainhub/components/${c.component_id}/rollback`), "cofnięto wersję")}>Cofnij wersję</button>
            <button className="btn tiny ghost" onClick={() => imp(c.component_id)}>Import ZIP</button>
          </div>
          <div className="table-wrap"><table className="tbl small"><thead><tr><th>Wersja</th><th>Szczegóły</th><th /></tr></thead>
            <tbody>{(c.versions || []).map((v: any) => (
              <tr key={v.version}><td>{v.version}{v.version === c.active_version && <> <Badge s="ACTIVE" /></>}</td>
                <td className="muted">{c.component_id === "TH_SDFORMERFLOW" ? `epoki ${v.epochs_done ?? "?"} · kroki ${v.steps ?? "?"} · próbki ${v.samples ?? "?"} · strata ${fmtNum(v.history?.slice(-1)?.[0]?.train_loss, 4)} · ${v.ok === false ? v.code : "OK"}`
                  : `${v.params?.price} · ${v.params?.window_set} · szer. ${v.params?.width} · ${v.source || ""}`}</td>
                <td className="row" style={{ gap: 4 }}>
                  {v.version !== c.active_version && <button className="btn tiny" onClick={() => call(apiSend("POST", `/api/v1/trainhub/components/${c.component_id}/activate`, { version: v.version }), `aktywowano ${v.version}`)}>Aktywuj</button>}
                  <a className="btn tiny ghost" href={`/api/v1/trainhub/components/${c.component_id}/export.zip?version=${encodeURIComponent(v.version)}`}>Eksport</a></td></tr>))}</tbody></table></div>
          {c.metrics && <p className="small muted">Metryki skuteczności: {c.metrics.status} (strata treningowa to nie prawdopodobieństwo trafienia)</p>}
        </div>))}
      {msg && <p className="small muted">{msg}</p>}
    </section>);
}
