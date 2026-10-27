// AI Neural Lab (approved mockup 02). Model list, statuses, training, validation and deployments come from the engine's registry
// (/api/v1/training/*); the "Neural Universe" drawing is an ILLUSTRATION, labelled as such - no activations, training or metrics are
// invented. A missing value is "—" / N/A.
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiSend } from "../../../api";
import { href, usePersisted } from "../../../router";
import { useStore } from "../../../store";
import { cls, fmtNum, fmtTime } from "../../../util";
import PageBanner from "../../shell/PageBanner";
import { StateView, stateOfError } from "../../shell/StateView";
import NeuralCanvas, { buildGraph, type Shape, type ViewMode } from "../components/NeuralCanvas";

type Tab = "universe" | "training" | "validation" | "deploy";
const TABS: { id: Tab; label: string }[] = [
  { id: "universe", label: "✧ Neural Universe" }, { id: "training", label: "Trening" }, { id: "validation", label: "Walidacja" }, { id: "deploy", label: "Wdrożenia" },
];
const SHAPES: { id: Shape; label: string; sub: string }[] = [
  { id: "mlp", label: "Sieć neuronowa", sub: "Warstwy MLP" },
  { id: "forest", label: "Random Forest", sub: "Las drzew" },
  { id: "xgb", label: "XGBoost", sub: "Kaskada drzew" },
  { id: "mc", label: "Monte Carlo", sub: "Trajektorie" },
];
const STATUS_PL: Record<string, string> = {
  READY: "gotowy", NOT_TRAINED: "niewytrenowany", SHADOW_ONLY: "SHADOW (obserwacja)", DETERMINISTIC_OK: "deterministyczny – działa", NOT_CONNECTED: "niepodłączony",
  DATA_MISSING: "brak danych", INCOMPATIBLE: "niezgodny – wymaga treningu",
};

/** Illustrative shape for a model of the registry (by its name); deterministic models have no network to draw. */
export function shapeOf(m: any): Shape | null {
  if (!m || m.kind !== "TRAINED") return null;
  const n = `${m.id} ${m.name}`.toUpperCase();
  if (n.includes("GPR") || n.includes("MONTE")) return "mc";
  if (n.includes("XGB")) return "xgb";
  if (n.includes("TREE") || n.includes("FOREST") || n.includes("HGB")) return "forest";
  return "mlp";
}

function featuresOf(m: any): string[] | null {
  const ps = m?.per_strategy ? Object.values(m.per_strategy) as any[] : [];
  return ps.find((p) => Array.isArray(p.features))?.features ?? null;
}

/** Last stage a model has reached, only from registry facts: 0 trained, 1 validated, 2 tested (READY / SHADOW). "Decyzja LIVE" is
 *  always a manual decision of the user and is never marked automatically. -1 = not trained yet. */
export function cycleOf(m: any): number {
  if (!m || m.kind !== "TRAINED") return -1;
  if (m.status === "READY" || m.status === "SHADOW_ONLY") return 2;
  const lt = m.last_training;
  if (lt && ["PASS", "PROMOTE", "OK"].includes(String(lt.verdict ?? "").toUpperCase())) return 1;
  return lt ? 0 : -1;
}

function useJson(path: string | null, every = 30000) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const load = useCallback(() => {
    if (!path) return;
    apiGet(path).then((x) => { setD(x); setErr(null); }).catch(setErr);
  }, [path]);
  useEffect(() => {
    load();
    if (!every) return;
    const t = setInterval(load, every);
    return () => clearInterval(t);
  }, [load, every]);
  return { d, err, reload: load };
}

function Universe({ models }: { models: any[] }) {
  const [shape, setShape] = useState<Shape>("mlp");
  const [modelId, setModelId] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("structure");
  const [playing, setPlaying] = useState(true);
  const [intensity, setIntensity] = useState(0.6);
  const [zoom, setZoom] = useState(1);
  const [step, setStep] = useState(0);
  const [sel, setSel] = useState<{ i: number; label: string } | null>(null);
  const model = models.find((m) => m.id === modelId) ?? null;
  const feats = featuresOf(model);
  const inputs = feats?.length ?? null;
  const pathLen = buildGraph(shape, inputs).path.length;
  const pickModel = (m: any) => {
    setModelId(m.id);
    const sh = shapeOf(m);
    if (sh) setShape(sh);
    setStep(0);
    setSel(null);
  };
  const trained = models.filter((m) => m.kind === "TRAINED");
  const real = model?.status === "READY" && !!feats;
  return (
    <div className="t-nl-grid">
      <aside className="t-card t-nl-list" aria-label="Modele">
        <p className="t-sub">Kształty poglądowe</p>
        {SHAPES.map((s) => (
          <button key={s.id} className={cls("t-nl-item", !modelId && shape === s.id && "on")} onClick={() => { setModelId(null); setShape(s.id); setStep(0); setSel(null); }}
            data-testid={`nl-shape-${s.id}`}><b>{s.label}</b><small>{s.sub}</small></button>))}
        <p className="t-sub" style={{ marginTop: 12 }}>Modele bota ({trained.length})</p>
        <div className="t-nl-models" data-testid="nl-models">
          {trained.map((m) => (
            <button key={m.id} className={cls("t-nl-item", modelId === m.id && "on")} onClick={() => pickModel(m)} data-model={m.id} data-status={m.status}>
              <b>{m.name}</b><small className={cls(m.status === "READY" ? "t-pos" : m.status === "SHADOW_ONLY" ? "" : "t-dim")}>{STATUS_PL[m.status] ?? m.status}</small></button>))}
        </div>
        <p className="t-note">Dostępność i wytrenowanie modeli pokazuje rejestr silnika. Rysunek jest ilustracją rodziny modelu.</p>
      </aside>
      <section className="t-card t-nl-stage" aria-label="Neural Constellation">
        <header className="t-card-head"><h2>Neural Constellation</h2>
          <span className="t-dim">{real ? `wejścia: ${inputs} cech z rejestru · warstwy ukryte poglądowe` : "graf poglądowy · bez telemetrii"}</span></header>
        <span className="t-badge t-badge-gold t-nl-flag" data-testid="nl-illustration">PRZYKŁAD · NIE DANE MODELU</span>
        <div className="t-nl-canvas-wrap">
          <NeuralCanvas shape={shape} inputs={inputs} mode={mode} playing={playing} intensity={intensity} zoom={zoom} step={step}
            selected={sel?.i ?? null} onSelect={(i, label) => setSel(i == null ? null : { i, label: label! })} onZoom={setZoom} />
          <span className="t-nl-hint">Przeciągnij, aby obrócić · kółko myszy przybliża</span>
        </div>
        <div className="t-row" role="toolbar" aria-label="Sterowanie wizualizacją">
          <div className="t-seg-switch" role="group" aria-label="Widok">
            {([["structure", "Struktura"], ["flow", "Przepływ"], ["path", "Ścieżka"]] as const).map(([v, l]) => (
              <button key={v} className={cls(mode === v && "on")} aria-pressed={mode === v} onClick={() => { setMode(v); setStep(0); }} data-testid={`nl-mode-${v}`}>{l}</button>))}
          </div>
          <span className="t-spacer" />
          <button className="t-btn" onClick={() => setZoom(Math.max(0.5, zoom * 0.85))} aria-label="Oddal">−</button>
          <button className="t-btn" onClick={() => setZoom(Math.min(2.5, zoom * 1.15))} aria-label="Przybliż">+</button>
          <label className="t-dim t-inline">Intensywność <input type="range" min={0} max={1} step={0.05} value={intensity} onChange={(e) => setIntensity(Number(e.target.value))}
            data-testid="nl-intensity" /></label>
          <button className="t-btn t-btn-acc" onClick={() => setPlaying(!playing)} aria-pressed={playing} data-testid="nl-play">{playing ? "❚❚ Pauza" : "▶ Animacja"}</button>
        </div>
        <div className="t-row" aria-label="Replay ścieżki">
          <span className="t-dim">Replay · przykład</span>
          <button className="t-btn" disabled={step <= 0} onClick={() => { setMode("path"); setStep(step - 1); }} aria-label="Poprzedni krok">‹</button>
          <b data-testid="nl-step">Krok {Math.min(step + 1, pathLen)} / {pathLen}</b>
          <button className="t-btn" disabled={step >= pathLen - 1} onClick={() => { setMode("path"); setStep(step + 1); }} aria-label="Następny krok">›</button>
          <button className="t-btn" onClick={() => { setMode("path"); setStep((step + 1) % pathLen); }} data-testid="nl-next">Następny węzeł</button>
        </div>
      </section>
      <aside className="t-card t-nl-details" aria-label="Szczegóły modelu" data-testid="nl-details">
        <p className="t-sub">Szczegóły modelu</p>
        <dl className="t-kv">
          <dt>Model</dt><dd>{model?.name ?? "kształt poglądowy"}</dd>
          <dt>Rodzina</dt><dd>{SHAPES.find((s) => s.id === shape)?.label}{model ? ` · ${model.group}` : ""}</dd>
          <dt>Status</dt><dd>{model ? STATUS_PL[model.status] ?? model.status : "nieznany"}</dd>
          <dt>Wersja</dt><dd>{(model?.per_strategy && (Object.values(model.per_strategy)[0] as any)?.version) ?? model?.last_training?.version ?? "—"}</dd>
          <dt>Walidacja</dt><dd>{model?.last_training?.verdict ?? (model?.per_strategy && (Object.values(model.per_strategy)[0] as any)?.last_run?.verdict) ?? "—"}</dd>
          <dt>Telemetria</dt><dd>Brak danych</dd>
          <dt>Wyjście</dt><dd>{model?.output ?? "—"}</dd>
        </dl>
        {model?.blockers?.length > 0 && <ul className="t-blockers">{model.blockers.map((b: string) => <li key={b}>{b}</li>)}</ul>}
        <div className="t-nl-sel" data-testid="nl-selected">
          <b>Wybrany element</b>
          <span>{sel ? sel.label : "Kliknij węzeł lub wybierz „Następny węzeł”."}</span>
        </div>
        <p className="t-note">Animacja i replay są ilustracją, nie aktywnością modelu. Telemetria sieci pojawi się tylko z działającego modelu.</p>
      </aside>
    </div>);
}

function Training({ instrument }: { instrument: string }) {
  const tr = useJson("/api/v1/training", 5000);
  const rd = useJson(`/api/v1/training/readiness?instrument=${instrument}`, 30000);
  const runs = useJson("/api/v1/training/runs", 30000);
  const [profile, setProfile] = useState("PELNY_TRENING");
  const [ask, setAsk] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const run = tr.d?.run;
  const start = async () => {
    setAsk(false);
    setMsg(null);
    try {
      const r: any = await apiSend("POST", "/api/v1/training/start", { instruments: [instrument], profile });
      setMsg(r.started ? "Trening uruchomiony w osobnym procesie." : `Nie uruchomiono: ${r.reason}`);
      tr.reload();
    } catch (e: any) {
      setMsg(`Błąd: ${e?.message || e}`);
    }
  };
  const cancel = async () => {
    try { await apiSend("POST", "/api/v1/training/cancel", {}); tr.reload(); } catch (e: any) { setMsg(`Błąd: ${e?.message || e}`); }
  };
  return (
    <div className="t-two">
      <section className="t-card" aria-label="Trening" data-testid="nl-training">
        <header className="t-card-head"><h2>Trening – {instrument}</h2>
          <span className={cls("t-badge", run?.status === "RUNNING" ? "t-badge-ok" : "t-badge-muted")}>{run ? run.status ?? "—" : "brak uruchomień"}</span></header>
        {tr.err ? <StateView state={stateOfError(tr.err)} detail={String((tr.err as any)?.message ?? tr.err)} /> : run ? (
          <dl className="t-kv">
            <dt>Uruchomienie</dt><dd>{run.run_id ?? "—"}</dd>
            <dt>Profil</dt><dd>{run.profile ?? "—"}</dd>
            <dt>Postęp</dt><dd>{run.progress != null ? `${fmtNum(run.progress * 100, 0)} %` : "—"}</dd>
            <dt>Etap</dt><dd>{run.current_task ?? run.phase ?? "—"}</dd>
            <dt>Rozpoczęto</dt><dd>{fmtTime(run.started_at, true)}</dd>
          </dl>) : <p className="t-dim">Jeszcze nie uruchamiano treningu w tej instalacji.</p>}
        <div className="t-row">
          <label className="t-field t-inline">Profil
            <select value={profile} onChange={(e) => setProfile(e.target.value)}>
              {Object.entries(tr.d?.profiles || {}).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}
            </select></label>
          <button className="t-btn t-btn-acc" disabled={!rd.d?.ready || run?.status === "RUNNING"} onClick={() => setAsk(true)} data-testid="nl-train-start">Rozpocznij trening</button>
          {run?.status === "RUNNING" && <button className="t-btn" onClick={cancel}>Przerwij</button>}
        </div>
        {ask && (
          <div className="t-confirm" role="alertdialog" aria-label="Potwierdź trening">
            <p>Trening {instrument} ({profile}) działa w osobnym procesie, może trwać długo i obciąża komputer. Nie składa zleceń; nowy model zostaje aktywowany
              tylko po walidacji poza próbą.</p>
            <div className="t-row"><button className="t-btn t-btn-acc" onClick={start} data-testid="nl-train-yes">Uruchom</button>
              <button className="t-btn" onClick={() => setAsk(false)}>Anuluj</button></div>
          </div>)}
        {msg && <p className="t-note" role="status">{msg}</p>}
        <p className="t-sub" style={{ marginTop: 12 }}>Zadania treningu</p>
        <ol className="t-steps">{(tr.d?.tasks || []).map((t: any) => <li key={t.kind}>{t.title}</li>)}</ol>
      </section>
      <section className="t-card" aria-label="Gotowość i historia">
        <header className="t-card-head"><h2>Gotowość danych</h2>
          <span className={cls("t-badge", rd.d?.ready ? "t-badge-ok" : "t-badge-muted")}>{rd.d ? (rd.d.ready ? "można trenować" : "brak gotowości") : "—"}</span></header>
        <ul className="t-checks">{(rd.d?.checks || []).map((c: any) => (
          <li key={c.id} className={c.ok ? "ok" : c.blocking ? "bad" : "warn"}><i aria-hidden="true">{c.ok ? "✓" : c.blocking ? "✕" : "!"}</i>
            <span><b>{c.id}</b><small>{c.detail}</small></span></li>))}</ul>
        <p className="t-sub" style={{ marginTop: 12 }}>Historia uruchomień</p>
        {(runs.d?.items || []).length === 0 ? <p className="t-dim">Brak.</p> : (
          <table className="t-table"><thead><tr><th>Uruchomienie</th><th>Status</th><th>Start</th></tr></thead>
            <tbody>{runs.d.items.slice(0, 10).map((r: any) => <tr key={r.run_id}><td>{r.run_id}</td><td>{r.status}</td><td>{fmtTime(r.started_at, true)}</td></tr>)}</tbody></table>)}
      </section>
    </div>);
}

function Validation({ models }: { models: any[] }) {
  const trained = models.filter((m) => m.kind === "TRAINED");
  return (
    <section className="t-card" aria-label="Walidacja" data-testid="nl-validation">
      <header className="t-card-head"><h2>Walidacja poza próbą</h2><span className="t-dim">tylko wyniki zapisane w rejestrze – brak = „—”</span></header>
      <div className="t-table-wrap">
        <table className="t-table">
          <thead><tr><th>Model</th><th>Status</th><th>Ostatni trening</th><th>Werdykt</th><th>N</th><th>Holdout</th><th>Źródło danych</th></tr></thead>
          <tbody>
            {trained.map((m) => {
              const ps = m.per_strategy ? Object.entries(m.per_strategy) as [string, any][] : [];
              const lt = m.last_training;
              return ps.length ? ps.map(([k, p]) => (
                <tr key={m.id + k}><td>{m.name} · {k}</td><td>{STATUS_PL[p.status?.status] ?? p.status?.status ?? "—"}</td><td>{fmtTime(p.last_run?.created_at, true)}</td>
                  <td>{p.last_run?.verdict ?? "—"}</td><td>{p.last_run?.n ?? "—"}</td><td>{p.active_holdout ? JSON.stringify(p.active_holdout).slice(0, 60) : "—"}</td>
                  <td>{p.last_run?.provenance ?? "—"}</td></tr>)) : (
                <tr key={m.id}><td>{m.name}</td><td>{STATUS_PL[m.status] ?? m.status}</td><td>{fmtTime(lt?.finished_at ?? lt?.created_at, true)}</td>
                  <td>{lt?.verdict ?? lt?.status ?? "—"}</td><td>{lt?.n ?? "—"}</td><td>{lt?.holdout ? JSON.stringify(lt.holdout).slice(0, 60) : "—"}</td>
                  <td>{lt ? (lt.synthetic ? "dane syntetyczne (test)" : "historia MT5 użytkownika") : "—"}</td></tr>);
            })}
          </tbody>
        </table>
      </div>
      <p className="t-note">Werdykt i holdout pochodzą z protokołu walidacji (podział czasowy, okres poza próbą). Wynik na danych syntetycznych jest testem technicznym, nie oceną skuteczności.</p>
    </section>);
}

function Deploy({ instrument }: { instrument: string }) {
  const { s } = useStore();
  const act = useJson(`/api/v1/training/active?instrument=${instrument}`, 30000);
  const fams = act.d?.families || {};
  return (
    <section className="t-card" aria-label="Wdrożenia" data-testid="nl-deploy">
      <header className="t-card-head"><h2>Wdrożenia – {instrument}</h2><span className="t-dim">tryb ML: {s.ml?.mode ?? "—"}</span></header>
      <table className="t-table"><thead><tr><th>Rodzina</th><th>Aktywny model</th></tr></thead>
        <tbody>{Object.entries(fams).map(([k, v]: [string, any]) => (
          <tr key={k}><td>{k}</td><td>{v?.active ? (typeof v.active === "string" ? v.active : JSON.stringify(v.active).slice(0, 80)) : (v?.models?.length ? `${v.models.length} modeli` : "brak – nie wdrożono")}</td></tr>))}</tbody></table>
      <p className="t-note">Model wpływa na decyzje dopiero po walidacji i ręcznej decyzji. Użycie w handlu LIVE wymaga świadomego wyboru trybu w Centrum sterowania
        (z potwierdzeniem rachunku); przywracanie poprzedniej wersji – <a href={href("modele")}>panel Modele i trening</a>.</p>
    </section>);
}

export default function AiNeuralLabPage() {
  const { s } = useStore();
  const instrument = s.assets?.active ?? "XAUUSD";
  const [tab, setTab] = usePersisted<Tab>("nl.tab", "universe", (v) => TABS.some((t) => t.id === v));
  const reg = useJson(`/api/v1/training/models?instrument=${instrument}`, 30000);
  const models: any[] = reg.d?.models || [];
  const trained = models.filter((m) => m.kind === "TRAINED");
  const ready = trained.filter((m) => m.status === "READY").length;
  const stages = ["Trening", "Walidacja", "Testy", "Decyzja LIVE"];
  const best = Math.max(-1, ...trained.map(cycleOf));
  return (
    <div className="t-page" data-testid="page-ai-neural-lab">
      <PageBanner testId="nl-banner" kicker="Pepe Market Wizard / Modele" title="AI Neural Lab" subtitle="Wizualizacja, trening i walidacja modeli."
        badges={<>
          <span className="t-badge t-badge-gold">WIZUALIZACJA POGLĄDOWA</span>
          <span className="t-badge t-badge-muted" data-testid="nl-ready">modele gotowe: {reg.d ? `${ready} / ${trained.length}` : "—"}</span>
        </>} />
      <div className="t-tabs" role="tablist" aria-label="AI Neural Lab">
        {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} data-testid={`nl-tab-${t.id}`}>{t.label}</button>)}
      </div>
      {reg.err ? <StateView state={stateOfError(reg.err)} detail={String((reg.err as any)?.message ?? reg.err)} /> : !reg.d ? <StateView state="loading" /> : (
        <div role="tabpanel">
          {tab === "universe" && <Universe models={models} />}
          {tab === "training" && <Training instrument={instrument} />}
          {tab === "validation" && <Validation models={models} />}
          {tab === "deploy" && <Deploy instrument={instrument} />}
        </div>)}
      {reg.d?.mode_note && <p className="t-note" data-testid="nl-mode-note">{reg.d.mode_note}</p>}
      <nav className="t-card t-cycle" aria-label="Cykl modelu" data-testid="nl-cycle">
        <b>Cykl modelu</b>
        {stages.map((st, i) => <span key={st} className={cls(i <= best && "on")}>{i > 0 && <i aria-hidden="true">›</i>}{st}</span>)}
        <span className="t-dim">{best < 0 ? "· żaden model nie przeszedł jeszcze treningu" : ""}</span>
      </nav>
    </div>);
}
