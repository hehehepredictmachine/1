// 1.14 pages: two assets (XAUUSD / BTC), scenarios + checklist, models and training, research & validation, data & sources,
// settings (asset mapping + execution state; the Execution Lock was withdrawn in 1.24) and the Neural Network Activity view. Everything comes from the backend lab
// (/api/v1/lab*); the browser computes nothing. A response for another asset than the active one is discarded (stale guard).
import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import Section from "../components/Section";
import { href, usePersisted } from "../router";
import { useStore } from "../store";
import { useUi } from "../ui";
import { cls, fmtMoney, fmtNum, fmtTime, tone } from "../util";
import { NeuralCard } from "../components/NeuralSystem";
import { TrainingPanel } from "../components/ShPanels";

const ROLE_PL: Record<string, string> = { active: "aktywny", shadow: "cień (bez wpływu)", research: "badawczy", visual_only: "tylko wizualny", fixture_only: "techniczny (dane syntetyczne)" };
const SCN_PL: Record<string, string> = { WATCH: "obserwacja", ALL_CONDITIONS_MET_SHADOW: "warunki spełnione (cień)", INVALIDATED: "unieważniony", EXPIRED: "wygasł" };
const COND_PL: Record<string, string> = { MET: "spełniony", MISSING: "brakuje", CONFLICT: "sprzeczny", INFO: "info" };

/** Lab state of the ACTIVE asset; responses for a different asset (fast switching) are dropped. */
export function useLab() {
  const { s } = useStore();
  const active = s.assets?.active;
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const req = useRef(0);
  useEffect(() => {
    if (!active) return;
    const id = ++req.current;
    const load = () => apiGet(`/api/v1/lab?asset=${active}`).then((r) => {
      if (id !== req.current || r.asset !== active) return;          // stale answer for an earlier asset
      setD(r);
      setErr(null);
    }).catch((e) => id === req.current && setErr(String(e?.message || e)));
    setD((x: any) => (x && x.asset === active ? x : null));
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [active, s.lab?.seq]);
  return { lab: d, err, active };
}

function Badge({ k, children, title }: { k: string; children: React.ReactNode; title?: string }) {
  return <span className={cls("badge", k)} title={title}>{children}</span>;
}

function Missing({ why }: { why?: string | null }) {
  return <span className="muted" title={why || ""}>brak danych{why ? ` – ${why}` : ""}</span>;
}

// ------------------------------------------------------------------------------------------- Neural Network Activity
export function NNActivity({ model, stale, scenarios }: { model: any; stale: boolean; scenarios: any[] }) {
  if (!model) return <div className="card nn-card" data-testid="nn-activity" data-state="waiting"><h3>Aktywność modelu</h3><Missing why="brak obliczenia lab" /></div>;
  if (model.status !== "ready") {
    return (
      <div className="card nn-card nn-off" data-testid="nn-activity" data-state="inactive">
        <h3>Aktywność sieci neuronowej</h3>
        <p className="nn-inactive"><b>Sieć nieaktywna</b> – {model.reason || model.nn_reason || model.status}</p>
        <p className="muted small">Wizualizacja pokazuje wyłącznie rzeczywiste inferencje załadowanego artefaktu. Bez modelu nie ma żadnej animacji ani prognozy.</p>
      </div>);
  }
  const t = model.telemetry || {};
  const layers: any[] = t.layer_summaries || [];
  const arch: any[] = t.architecture || [];
  const linked = (scenarios || []).filter((x) => x.model?.inference_id === t.inference_id);
  const spikes = t.spike_metrics;
  return (
    <div className={cls("card nn-card", stale && "nn-stale")} data-testid="nn-activity" data-state={stale ? "stale" : "live"} data-inference={t.inference_id}>
      <div className="nn-head">
        <h3>Aktywność modelu {model.nn_status?.startsWith("ACTIVE") ? "(sieć neuronowa)" : "(model niebędący siecią)"}</h3>
        <Badge k={model.role === "shadow" ? "warn" : model.role === "active" ? "ok" : "muted"}>{ROLE_PL[model.role] ?? model.role}</Badge>
        {stale && <Badge k="bad">dane nieaktualne – aktywność zatrzymana</Badge>}
      </div>
      {model.nn_reason && <p className="muted small">Status sieci neuronowej: {model.nn_reason}</p>}
      <p className="muted small mono">{t.model_id} · {t.architecture_id} · inferencja {t.inference_id} · {fmtTime(t.as_of_time, true)} · {t.latency_ms} ms
        (telemetria +{t.telemetry_overhead_ms} ms) · ważne do {fmtTime(t.expires_at, true)}</p>
      <div className="nn-flow" key={stale ? "stale" : t.inference_id}>
        <div className="nn-col">
          <label>Wejście</label>
          <div className="mono small">{t.canonical_asset} · M5 · {t.state_mode}</div>
          {(t.feature_groups || []).map((g: any) => <div key={g.group} className={cls("nn-feat", g.quality !== "OK" && "warn")} title={g.features.join(", ")}>{g.group} {g.quality === "OK" ? "✓" : "⚠ " + g.quality}</div>)}
        </div>
        {arch.map((a: any, i: number) => {
          const L = layers[i] && a.stage !== "pooling" && a.stage !== "output" ? layers[i] : null;
          const level = L ? (L.active_fraction ?? L.firing_rate ?? null) : null;
          return (
            <div key={i} className={cls("nn-col nn-layer", !stale && "nn-pulse")} style={{ animationDelay: `${i * 120}ms` }} data-stage={a.stage}>
              <label>{a.stage}</label>
              <div className="nn-box"><b>{a.name}</b>{a.shape && <small>{a.shape}</small>}</div>
              {level != null && <div className="nn-bar" title={L.firing_rate != null ? "firing rate" : "udział aktywnych neuronów (ReLU>0)"}><i style={{ width: `${Math.min(100, level * 100)}%` }} /></div>}
              {L && <small className="muted mono">{Object.entries(L).filter(([k]) => k !== "layer" && k !== "contributions_coef_x_value" && k !== "decision_path_nodes").map(([k, v]) => `${k}=${typeof v === "number" ? fmtNum(v, 3) : v}`).join(" · ")}</small>}
            </div>);
        })}
        <div className="nn-col">
          <label>Wynik</label>
          {(t.output_schema?.classes || []).map((c: string, i: number) => (
            <div key={c} className="nn-out"><span>{c}</span><div className="nn-bar"><i style={{ width: `${(t.raw_output?.[i] ?? 0) * 100}%` }} /></div><b>{fmtNum((t.raw_output?.[i] ?? 0) * 100, 1)}%</b></div>))}
          <small className="muted">{t.output_schema?.event}</small>
          <small className="muted">Skalibrowane: {t.calibrated_output == null ? `brak – ${t.calibration_note}` : String(t.calibrated_output)}</small>
        </div>
      </div>
      {layers.some((l) => l.contributions_coef_x_value) && (
        <p className="small muted">Udział cech w logicie (współczynnik × wartość; {layers[0].method}): {layers[0].contributions_coef_x_value.map((c: any) => `${c.feature} ${fmtNum(c.value, 3)}`).join(", ")}</p>)}
      {spikes && (
        <div className="nn-raster" data-testid="nn-raster">
          {(["raster_l1", "raster_l2"] as const).map((k) => (
            <figure key={k}>
              <svg viewBox={`0 0 ${(spikes[k]?.[0]?.length || 16) * 6} ${(spikes[k]?.length || 32) * 4}`} role="img" aria-label={`Raster spike'ów ${k === "raster_l1" ? "LIF-1" : "LIF-2"}`}>
                {(spikes[k] || []).map((row: number[], ti: number) => row.map((v, ni) => v ? <rect key={`${ti}-${ni}`} x={ni * 6} y={ti * 4} width="5" height="3" className="spike" /> : null))}
              </svg>
              <figcaption className="small muted">{k === "raster_l1" ? "LIF-1" : "LIF-2 (SEW)"} · czas ↓ · neurony →</figcaption>
            </figure>))}
          <p className="small muted">próg θ={spikes.threshold} · β={spikes.beta} · firing rate {fmtNum(spikes.firing_rate_total * 100, 1)}% · operacje synaptyczne {spikes.synaptic_ops}</p>
        </div>)}
      {(t.warnings || []).length > 0 && <ul className="warn-list">{t.warnings.map((w: string) => <li key={w}>⚠ {w}</li>)}</ul>}
      <p className="small">Powiązane scenariusze: {linked.length ? linked.map((x) => <a key={x.setup_id} href={href("setupy", { params: { id: x.setup_id } })}>{x.kind} {x.side} </a>) : <span className="muted">brak (model dotyczy strony {model.side})</span>}</p>
    </div>);
}

// ------------------------------------------------------------------------------------------- Pulpit (1.14 top)
function ScenarioCard({ lab }: { lab: any }) {
  const sc = (lab?.scenarios || []).filter((x: any) => x.status === "WATCH" || x.status === "ALL_CONDITIONS_MET_SHADOW")
    .sort((a: any, b: any) => (b.checklist_completeness.met - b.checklist_completeness.total) - (a.checklist_completeness.met - a.checklist_completeness.total))[0];
  if (!sc) return (
    <div className="card scn-card" data-testid="scenario-card"><h3>Scenariusz</h3>
      <p>Brak aktywnego scenariusza dla {lab?.asset ?? "aktywa"}. {(lab?.scenarios || []).length ? `Ostatnie: ${lab.scenarios.map((x: any) => `${x.kind} ${SCN_PL[x.status] ?? x.status}`).join(", ")}` : ""}</p>
      <p className="muted small">Czekam na: sekwencję sweep → MSS → FVG (M15), hipotezy Z-score (M5) lub wybicie poziomu dnia ze zmianą momentum (M15).</p></div>);
  const cc = sc.checklist_completeness;
  return (
    <div className="card scn-card" data-testid="scenario-card">
      <div className="nn-head"><h3>Scenariusz: {sc.kind} · {sc.side} · {sc.tf}</h3><Badge k={sc.status === "WATCH" ? "warn" : "ok"}>{SCN_PL[sc.status] ?? sc.status}</Badge></div>
      <p className="scn-wait"><b>{sc.waiting_for}</b></p>
      <div className="scn-grid">
        <div><label>Spełnione</label><ul>{sc.checklist.filter((c: any) => c.state === "MET").map((c: any) => <li key={c.name} className="ok">✓ {c.name}</li>)}</ul></div>
        <div><label>Brakuje</label><ul>{sc.checklist.filter((c: any) => c.state === "MISSING").map((c: any) => <li key={c.name} className="warn">○ {c.name}</li>)}</ul></div>
        <div><label>Sprzeczne</label><ul>{sc.checklist.filter((c: any) => c.state === "CONFLICT").map((c: any) => <li key={c.name} className="bad">✕ {c.name} {c.detail}</li>)}</ul></div>
      </div>
      <p className="small">Unieważnienie: <b>{sc.invalidation ?? "—"}</b> · trigger: {sc.trigger} · wygasa {fmtTime(sc.expires_at, true)}</p>
      <p className="small muted">Kompletność checklisty {cc.met}/{cc.total} (to NIE jest prawdopodobieństwo) · Model: {sc.model?.raw_score != null ? `wynik ${fmtNum(sc.model.raw_score * 100, 1)}% (${sc.model.family}, ${ROLE_PL[sc.model.role] ?? sc.model.role}; ${sc.model.event})` : sc.model?.reason ?? "brak modelu"}</p>
      <a className="btn ghost" href={href("setupy", { params: { id: sc.setup_id } })}>Pełna checklista</a>
    </div>);
}

export function LabDashboardTop() {
  const { s } = useStore();
  const { lab, err, active } = useLab();
  const it = s.assets?.assets?.[active || ""] || {};
  const q = s.quote;
  const reg = lab?.modules?.M15?.regime;
  const vol = lab?.modules?.M15?.vol;
  const sess = (lab?.modules?.M15?.sessions?.boxes || []).filter((b: any) => b.state === "DEVELOPING").map((b: any) => b.session);
  const a = s.account;
  return (
    <div className="lab-top" data-testid="lab-dashboard">
      <div className="card asset-card" data-testid="asset-card">
        <div className="nn-head"><h3>{active ?? "…"} <small className="muted">→ {it.broker_symbol ?? "niezmapowane"}</small></h3>
          <Badge k={s.synthetic ? "warn" : "ok"}>{lab?.data_mode === "fixture" || s.synthetic ? "dane: fixture (syntetyczne)" : "dane: live MT5"}</Badge>
          <Badge k={s.mode?.kill_switch ? "bad" : s.mode?.mode === "AUTO_LIVE" ? "warn" : "ok"}>{s.mode?.kill_switch ? "STOP nowych wejść" : `Tryb: ${s.mode?.mode_label ?? s.mode?.mode ?? "—"}`}</Badge></div>
        <div className="kv-grid">
          <div><label>Bid / Ask</label><b className="mono">{q ? `${q.bid} / ${q.ask}` : "—"}</b></div>
          <div><label>Spread</label><b className="mono">{q?.spread_points != null ? `${q.spread_points} pkt` : q?.spread ?? "—"}</b></div>
          <div><label>Wiek notowania</label><b className={cls(q?.age_seconds != null && q.age_seconds > 10 && "warn")}>{q?.age_seconds != null ? `${Math.round(q.age_seconds)} s` : "—"}</b></div>
          <div><label>Sesja (rozwijająca się)</label><b>{sess.length ? sess.join(", ") : "poza zdefiniowanymi sesjami"}</b></div>
          <div><label>Reżim M15 (M10)</label><b>{reg?.state ?? "—"}</b></div>
          <div><label>Zmienność M15 (M11)</label><b>{vol?.state ?? "—"}{vol?.atr_percentile != null ? ` · pct ${fmtNum(vol.atr_percentile * 100, 0)}` : ""}</b></div>
          <div><label>Instrument</label><b className="mono small">{it.instrument?.instrument_id ?? "—"}</b></div>
          <div><label>Kontrakt</label><b className="small">{it.instrument?.contract_size != null ? `${it.instrument.contract_size} · ${it.instrument.quote_currency} · ${it.instrument.instrument_type}` : "—"}</b></div>
          <div><label>Balance / Equity</label><b>{a ? `${fmtMoney(a.balance, a.currency)} / ${fmtMoney(a.equity, a.currency)}` : "—"}</b></div>
          <div><label>Zdrowie</label><b className={tone(s.connection?.state)}>MT5 {s.connection?.state ?? "?"}{s.engine?.last_error ? " · błąd silnika" : ""}{lab?.stale ? " · lab nieaktualny" : ""}</b></div>
        </div>
        {err && <p className="bad small">{err}</p>}
        {lab?.status === "warming_up" && <p className="muted small">Lab: {lab.reason}</p>}
      </div>
      <ScenarioCard lab={lab} />
      <AllModels lab={lab} />
      <NeuralCard />
    </div>);
}

/** Every model artefact of the active asset runs on each closed M5 bar; pick which one the activity view shows. */
function AllModels({ lab }: { lab: any }) {
  const [sel, setSel] = usePersisted<string>("lab.nnModel", "", (x) => typeof x === "string");
  const list: any[] = lab?.models || [];
  const byFam = list.find((m) => m.family === sel && m.status === "ready");
  const shown = byFam || lab?.model;
  return (
    <>
      <NNActivity model={shown} stale={!!lab?.stale || !lab?.fresh} scenarios={lab?.scenarios || []} />
      {list.length > 0 && (
        <div className="card nn-card" data-testid="all-models">
          <div className="nn-head"><h3>Wszystkie modele {lab?.asset} ({list.length})</h3>
            <label className="small">Pokaż w wizualizacji: <select aria-label="Model w wizualizacji" value={byFam ? sel : ""} onChange={(e) => setSel(e.target.value)}>
              <option value="">automatycznie ({lab?.model?.family ?? "—"})</option>
              {list.filter((m) => m.status === "ready").map((m) => <option key={m.family} value={m.family}>{m.family}</option>)}</select></label></div>
          <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Model</th><th>Rodzina</th><th>Rola</th><th>Wynik (TP przed SL)</th><th>Czas</th><th>Status</th></tr></thead>
            <tbody>{list.map((m) => (
              <tr key={m.model_id ?? m.family} className={m.status === "ready" ? "" : "warn"}>
                <td className="mono">{m.model_id}</td><td>{m.family}</td><td>{ROLE_PL[m.role] ?? m.role ?? "—"}</td>
                <td>{m.raw_score != null ? `${fmtNum(m.raw_score * 100, 1)}%` : "—"}</td><td>{m.telemetry?.latency_ms != null ? `${m.telemetry.latency_ms} ms` : "—"}</td>
                <td>{m.status}{m.reason ? ` – ${m.reason}` : ""}</td></tr>))}</tbody></table></div>
          <p className="muted small">Wszystkie modele liczą się na każdej zamkniętej świecy M5. Żaden nie składa zleceń; rola „badawczy”/„techniczny” = bez wpływu na decyzje.</p>
        </div>)}
    </>);
}

// ------------------------------------------------------------------------------------------- Setupy
function TradePad({ lab }: { lab: any }) {
  const [f, setF] = useState({ side: "BUY", entry: "", sl: "", tp: "", lots: "0.01" });
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const sim = async () => {
    setErr(null);
    try {
      setR(await apiSend("POST", "/api/v1/lab/tradepad", { ...f, entry: +f.entry, sl: +f.sl, tp: +f.tp, lots: +f.lots }));
    } catch (e: any) { setErr(String(e?.message || e)); setR(null); }
  };
  return (
    <div className="card" data-testid="tradepad">
      <h3>Trade Pad – plan i symulacja (M42)</h3>
      <p className="muted small">Tylko symulacja z parametrów kontraktu {lab?.symbol ?? ""}. Ta karta nie wysyła zleceń – rzeczywiste zlecenie składa się w Manual Trade Pad (plan → intencja → wykonanie, zgodnie z trybem).</p>
      <div className="form-row">
        <select aria-label="Strona" value={f.side} onChange={(e) => setF({ ...f, side: e.target.value })}><option>BUY</option><option>SELL</option></select>
        {(["entry", "sl", "tp", "lots"] as const).map((k) => <input key={k} aria-label={k} placeholder={k} value={(f as any)[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} inputMode="decimal" />)}
        <button className="btn" onClick={sim}>Symuluj</button>
      </div>
      {err && <p className="bad small">{err}</p>}
      {r && <p className="small mono">RR {r.rr} · TP {fmtNum(r.pnl_at_tp)} · SL {fmtNum(r.pnl_at_sl)} · prowizja {fmtNum(r.commission_round_turn)} · lot {r.lot_valid ? "OK" : "niepoprawny krok/min"} · {r.execution}</p>}
    </div>);
}

export function SetupsPage() {
  const { s } = useStore();
  const { lab, active } = useLab();
  const want = new URLSearchParams(location.hash.split("?")[1] || "").get("id");
  const list: any[] = lab?.scenarios || [];
  return (
    <div className="lab-page" data-testid="page-setupy">
      <h2>Scenariusze {active} <small className="muted">(silnik lab – tryb cienia, bez zleceń)</small></h2>
      {active === "XAUUSD" && s.decision?.setup && <p className="small">Silnik S01–S12 (XAUUSD): <a href={href("warunki")}>{s.decision.setup.strategy_id} {s.decision.setup.direction} – {s.decision.setup.state}</a></p>}
      {active === "BTC" && <p className="small muted">Silnik S01–S12 jest skalibrowany wyłącznie dla XAUUSD – dla BTC działają tylko scenariusze lab (LEGACY_ENGINE_XAUUSD_ONLY).</p>}
      {!list.length && <p className="muted">Brak scenariuszy {lab ? `(obliczenie ${fmtTime(lab.as_of, true)})` : "– oczekiwanie na pierwsze obliczenie"}.</p>}
      {list.map((sc) => (
        <details key={sc.setup_id} className="card scn-detail" open={want ? want === sc.setup_id : undefined} data-testid="scenario-row">
          <summary><b>{sc.kind}</b> {sc.side} {sc.tf} · <Badge k={sc.status === "WATCH" ? "warn" : sc.status === "ALL_CONDITIONS_MET_SHADOW" ? "ok" : "muted"}>{SCN_PL[sc.status] ?? sc.status}</Badge>
            {" "}· {sc.checklist_completeness.met}/{sc.checklist_completeness.total} · {sc.waiting_for}</summary>
          <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Warunek</th><th>Stan</th><th>Szczegół</th></tr></thead>
            <tbody>{sc.checklist.map((c: any) => <tr key={c.name} className={c.state === "MET" ? "ok" : c.state === "CONFLICT" ? "bad" : "warn"}><td>{c.name}</td><td>{COND_PL[c.state]}</td><td>{c.detail}</td></tr>)}</tbody></table></div>
          <p className="small mono">setup_id {sc.setup_id} · {sc.version} · utworzony {fmtTime(sc.created_at, true)} · wygasa {fmtTime(sc.expires_at, true)} · trace {sc.trace_id}</p>
          <p className="small">Trigger: {sc.trigger} · Unieważnienie: {sc.invalidation ?? "—"} · Poziomy: {(sc.levels || []).map((l: any) => l.price ?? `${l.bottom}–${l.top}`).join(", ") || "—"}</p>
          <p className="small">Model: {sc.model?.raw_score != null ? `${sc.model.family} · wynik ${fmtNum(sc.model.raw_score * 100, 1)}% · prawdopodobieństwo skalibrowane: brak kalibratora (ECE ${fmtNum(sc.model.calibration_ece, 3)}) · ${sc.model.event}` : sc.model?.reason ?? "brak"}</p>
          <p className="small">Historia: {(sc.history || []).map((h: any) => `${fmtTime(h.at, true)} ${SCN_PL[h.status] ?? h.status}`).join(" → ")}</p>
          <p className="small muted">Źródła: zamknięte świece {sc.tf} z MT5 ({lab?.data_mode}), moduły M10/M14/M16/M23/M25, notowanie bid/ask (koszt).</p>
        </details>))}
      <TradePad lab={lab} />
    </div>);
}

// ------------------------------------------------------------------------------------------- Modele i trening
const FAMS = ["DUMMY", "RULE", "LOGREG", "TREE", "MINIROCKET", "XGB", "RESNET1D", "SEW_SNN"];
const EXPS = ["LOGREG_PCA", "LOGREG_GMM_AUG", "LOGREG_NEUTRALIZED"];

function Curve({ curve }: { curve: any[] }) {
  if (!curve?.length) return null;
  const vals = curve.flatMap((c) => [c.train_loss, c.val_loss]).filter((v) => v != null);
  const lo = Math.min(...vals), hi = Math.max(...vals), W = 220, H = 70;
  const pt = (k: string) => curve.filter((c) => c[k] != null).map((c, i) => `${(i / Math.max(1, curve.length - 1)) * W},${H - ((c[k] - lo) / Math.max(1e-9, hi - lo)) * H}`).join(" ");
  return <svg className="curve" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Krzywa uczenia (strata treningowa i walidacyjna)">
    <polyline points={pt("train_loss")} className="c-train" /><polyline points={pt("val_loss")} className="c-val" /></svg>;
}

export function ModelsPage() {
  const { s } = useStore();
  const active = s.assets?.active;
  const [models, setModels] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [fams, setFams] = useState<string[]>(["DUMMY", "RULE", "LOGREG", "TREE", "MINIROCKET", "SEW_SNN"]);
  const [exps, setExps] = useState<string[]>([]);
  const [art, setArt] = useState("auto");
  const [err, setErr] = useState<string | null>(null);
  const load = () => {
    if (!active) return;
    apiGet(`/api/v1/lab/models?asset=${active}`).then((r) => r.asset === active && setModels(r.models)).catch(() => undefined);
    apiGet("/api/v1/lab/jobs").then((r) => setJobs(r.jobs)).catch(() => undefined);
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);
  const start = async () => {
    setErr(null);
    try {
      const r = await apiSend("POST", "/api/v1/lab/train", { asset: active, families: fams, experiments: exps, artifact_family: art });
      if (!r.started) setErr(r.reason);
      load();
    } catch (e: any) { setErr(String(e?.message || e)); }
  };
  const tog = (arr: string[], set: (x: string[]) => void, k: string) => set(arr.includes(k) ? arr.filter((x) => x !== k) : [...arr, k]);
  const running = jobs.find((j) => j.status === "RUNNING");
  return (
    <div className="lab-page" data-testid="page-modele">
      <h2>Modele i trening – {active}</h2>
      <TrainingPanel instrument={active} />
      <TrainingCard />
      <IndicatorModulesCard />
      <ScalpMlCard asset={active} />
      <p className="muted small">Każde aktywo i horyzont ma osobną ścieżkę. Model z danych syntetycznych ma rolę „techniczny” i nigdy nie wpływa na decyzje. Brak danych lub przewagi → INSUFFICIENT_EVIDENCE / NO_VALIDATED_EDGE.</p>
      <div className="card" data-testid="train-card">
        <h3>Nowe badanie (protokół VP – zamrożony przed startem)</h3>
        <div className="chips-row">{FAMS.map((f) => <label key={f} className="chk"><input type="checkbox" checked={fams.includes(f)} onChange={() => tog(fams, setFams, f)} />{f}</label>)}</div>
        <div className="chips-row">{EXPS.map((f) => <label key={f} className="chk"><input type="checkbox" checked={exps.includes(f)} onChange={() => tog(exps, setExps, f)} />{f}</label>)}</div>
        <label className="small">Artefakt po badaniu: <select aria-label="Artefakt" value={art} onChange={(e) => setArt(e.target.value)} data-testid="artifact-family">
          <option value="auto">tylko kandydat, który przeszedł walidację</option>
          {fams.filter((f) => f !== "DUMMY").map((f) => <option key={f} value={f}>{f} – badawczy (bez wpływu na decyzje)</option>)}</select></label>{" "}
        <button className="btn" onClick={start} disabled={!!running} data-testid="start-study">Uruchom badanie dla {active}</button>
        {err && <p className="bad small">{err}</p>}
      </div>
      <div className="card" data-testid="jobs">
        <h3>Zadania</h3>
        {!jobs.length && <p className="muted">Brak zadań w tej sesji programu.</p>}
        {jobs.map((j) => (
          <div key={j.job_id} className="job" data-status={j.status}>
            <b className="mono">{j.job_id}</b> {j.asset} · <Badge k={j.status === "COMPLETED" ? "ok" : j.status === "RUNNING" ? "warn" : "bad"}>{j.status}</Badge>
            {j.status === "RUNNING" && <> · {j.progress}/{j.total} ({j.stage}) <progress max={j.total || 1} value={j.progress} /> <button className="btn ghost" onClick={() => apiSend("POST", `/api/v1/lab/jobs/${j.job_id}/cancel`).then(load)}>Anuluj</button></>}
            {j.verdict && <> · werdykt <b>{j.verdict}</b></>} {j.model_id && <> · artefakt <span className="mono">{j.model_id}</span></>} · źródło {j.data_source}
            {j.error && <p className="bad small">{j.error}</p>}
            <details><summary className="small">log</summary><pre className="small">{(j.logs || []).join("\n")}</pre></details>
          </div>))}
      </div>
      <div className="card" data-testid="models">
        <h3>Artefakty {active} (champion / challenger)</h3>
        {!models.length && <p className="muted">Brak artefaktów – sieć i modele nieaktywne dla {active}.</p>}
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Model</th><th>Rodzina</th><th>Horyzont</th><th>Rola</th><th>Werdykt</th><th>Źródło</th><th>Odcięcie</th><th>Log loss</th><th>ECE</th><th>Krzywa</th></tr></thead>
          <tbody>{models.map((m, i) => (
            <tr key={m.model_id}><td className="mono">{m.model_id}{i === 0 ? " (bieżący)" : ""}</td><td>{m.family}</td><td>{m.horizon}</td><td>{ROLE_PL[m.role] ?? m.role}</td><td>{m.verdict}</td>
              <td>{m.data_source}</td><td>{fmtTime(m.cutoff, true)}</td><td>{fmtNum(m.metrics?.log_loss_mean, 4)}</td><td>{fmtNum(m.metrics?.ece_mean, 3)}</td><td><Curve curve={m.curve} /></td></tr>))}</tbody></table></div>
      </div>
    </div>);
}

// ------------------------------------------------------------------------------------------- Trening XAUUSD / BTC (instalator)
const EX_PL: Record<string, string> = { NIE_URUCHOMIONE: "czeka", W_TOKU: "w toku", UKONCZONE: "ukończone", POMINIETE: "pominięte", BLAD_TECHNICZNY: "błąd", ANULOWANE: "anulowane" };
const Q_PL: Record<string, string> = { NIE_DOTYCZY: "—", BRAK_PRZESLANEK: "za mało danych", ODRZUCONY: "odrzucony", NIEZWALIDOWANY: "niezwalidowany",
  CZESCIOWO_ZWALIDOWANY: "częściowo zwalidowany", ZWALIDOWANY_SHADOW: "zwalidowany SHADOW", TEST_TECHNICZNY: "test techniczny" };
const I_PL: Record<string, string> = { NIEZAPISANY: "—", ZAPISANY_DO_BADAN: "do badań", AKTYWNY_W_REJESTRZE: "aktywny w rejestrze", ZALADOWANY_DO_SHADOW: "załadowany do SHADOW", ROLLBACK: "rollback" };

export function TrainingCard() {
  const [st, setSt] = useState<any>(null);
  const [inst, setInst] = useState<string[]>(["XAUUSD"]);
  const [prof, setProf] = useState("PELNY_TRENING");
  const [months, setMonths] = useState("12");
  const [btcSym, setBtcSym] = useState("");
  const [comBtc, setComBtc] = useState("");
  const [act, setAct] = useState<any>(null);
  const [actInst, setActInst] = useState("XAUUSD");
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => {
    apiGet("/api/v1/training").then(setSt).catch(() => undefined);
    apiGet(`/api/v1/training/active?instrument=${actInst}`).then(setAct).catch(() => undefined);
  };
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [actInst]);
  const run = st?.run;
  const busy = run?.status === "RUNNING";
  const start = async () => {
    setMsg(null);
    const r = await apiSend("POST", "/api/v1/training/start", { instruments: inst, profile: prof, months: Number(months) || undefined,
      symbol_btc: btcSym || undefined, commission_btc: comBtc ? Number(comBtc.replace(",", ".")) : undefined }).catch((e) => ({ started: false, reason: String(e?.message || e) }));
    setMsg(r.started ? "Trening uruchomiony w osobnym procesie – postęp poniżej." : `Nie uruchomiono: ${r.reason}`);
    setTimeout(load, 1500);
  };
  const rollback = async (family: string) => {
    const r = await apiSend("POST", "/api/v1/training/rollback", { instrument: actInst, family }).catch((e) => ({ ok: false, reason: String(e?.message || e) }));
    setMsg(r.ok ? `Rollback ${actInst} ${family}: wykonany.` : `Rollback ${actInst} ${family}: ${r.reason || r.output || "brak poprzedniego modelu"}`);
    load();
  };
  const tog = (k: string) => setInst(inst.includes(k) ? inst.filter((x) => x !== k) : [...inst, k]);
  const tasks: any[] = run?.tasks || [];
  const done = tasks.filter((t) => ["UKONCZONE", "POMINIETE", "BLAD_TECHNICZNY", "ANULOWANE"].includes(t.execution)).length;
  return (
    <div className="card" data-testid="training-card">
      <h3>Trening XAUUSD / BTC (ten sam mechanizm co 00_TRENING_START.bat)</h3>
      <p className="muted small">Offline, bez zleceń; tryb wykonania bez zmian. Aktywowane są tylko modele dopuszczone walidacją; odrzucone zostają do badań. Strona modeli lab: LONG.</p>
      <div className="chips-row">
        {["XAUUSD", "BTC"].map((k) => <label key={k} className="chk"><input type="checkbox" checked={inst.includes(k)} onChange={() => tog(k)} data-testid={`tr-inst-${k}`} />{k}</label>)}
        <select aria-label="Profil" value={prof} onChange={(e) => setProf(e.target.value)} data-testid="tr-profile">
          {Object.entries(st?.profiles || { PELNY_TRENING: "PEŁNY TRENING", TEST_INSTALACJI: "TEST INSTALACJI" }).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}</select>
        <label className="small">miesięcy <input aria-label="Miesiące historii" className="num" value={months} onChange={(e) => setMonths(e.target.value)} size={3} /></label>
        {inst.includes("BTC") && <>
          <label className="small">symbol BTC <input aria-label="Symbol BTC" value={btcSym} placeholder="BTCUSDT-" onChange={(e) => setBtcSym(e.target.value)} size={10} /></label>
          <label className="small">prowizja BTC/lot/strona <input aria-label="Prowizja BTC" value={comBtc} placeholder="z historii" onChange={(e) => setComBtc(e.target.value)} size={6} /></label></>}
        <button className="btn" onClick={start} disabled={busy || !inst.length} data-testid="tr-start">Start</button>
        {busy && <button className="btn ghost" onClick={() => apiSend("POST", "/api/v1/training/cancel").then(load)} data-testid="tr-cancel">Anuluj</button>}
      </div>
      {msg && <p className="small">{msg}</p>}
      {run && <>
        <p className="small" data-testid="tr-summary"><b className="mono">{run.run_id}</b> · {run.status} · {done}/{tasks.length} <progress max={tasks.length || 1} value={done} />
          {run.summary?.line && <> · {run.summary.line}</>}</p>
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Instr.</th><th>Zadanie</th><th>Wykonanie</th><th>Jakość</th><th>Integracja</th><th>Szczegóły</th></tr></thead>
          <tbody>{tasks.map((t) => <tr key={t.id} data-exec={t.execution}><td>{t.instrument}</td><td>{t.title}</td><td>{EX_PL[t.execution] ?? t.execution}</td>
            <td>{Q_PL[t.quality] ?? t.quality}</td><td>{I_PL[t.integration] ?? t.integration}</td><td className="wrap-cell">{t.detail}</td></tr>)}</tbody></table></div></>}
      <h4>Aktywne modele <select aria-label="Instrument aktywnych modeli" value={actInst} onChange={(e) => setActInst(e.target.value)}><option>XAUUSD</option><option>BTC</option></select></h4>
      {act && <ul className="small" data-testid="tr-active">
        {["forecast", "scalp", "ml"].map((f) => <li key={f}>{f}: <span className="mono">{act.families[f]?.active || "brak"}</span> {act.families[f]?.status && `(${act.families[f].status})`}
          {" "}<button className="btn ghost" onClick={() => rollback(f)}>Rollback</button></li>)}
        {Object.entries(act.families.lab?.pinned || {}).map(([fam, mid]) => <li key={fam}>lab {fam}: <span className="mono">{String(mid)}</span>{" "}
          <button className="btn ghost" onClick={() => rollback(`lab:${fam}`)}>Rollback</button></li>)}
      </ul>}
    </div>);
}

// ------------------------------------------------------------------------------------------- PMW-UPD-02 Moduły IQ / PAL / SAR
const SRC_PL: Record<string, string> = { RECEIVING: "odbiera dane", SOURCE_MISSING: "brak źródła (eksporter/wskaźnik)", STALE: "dane nieaktualne",
  BLOCKED_IDENTITY_REQUIRED: "wymagana identyfikacja narzędzia", DECODER_NOT_IMPLEMENTED: "brak zaufanego dekodera", MANIFEST_INCOMPLETE: "manifest niekompletny",
  UNSUPPORTED_PLATFORM: "nieobsługiwana platforma", IDENTIFIED: "zidentyfikowany" };
const MAP_PL: Record<string, string> = { MAPPING_MISSING: "brak mappingu", MAPPING_UNVERIFIED: "mapping niezweryfikowany", MAPPING_APPROVED: "mapping zatwierdzony",
  MAPPING_VERSION_CHANGED: "zmiana wersji produktu – mapping do ponownej weryfikacji" };

export function IndicatorModulesCard() {
  const [st, setSt] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => apiGet("/api/v1/indicator-context").then(setSt).catch(() => undefined);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  if (!st) return null;
  const src = st.sources?.adapters || {};
  const runs = Object.entries(st.model?.runs || {}) as [string, any][];
  const act = st.model?.active;
  return (
    <div className="card" data-testid="ind-modules">
      <h3>Moduły IQ / PAL / SAR – {st.instrument}</h3>
      <p className="muted small">Odczyt oryginalnych wskaźników tylko przez eksporter (mql5/PMW_ExtIndicatorExporter.mq5) i zatwierdzony mapping. Brak źródła = brak
        wartości, nie zero. Model reakcji przewiduje P(TP1 przed SL) istniejącego setupu – to nie P(zysk) ani sygnał; działa w SHADOW.</p>
      <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Moduł</th><th>Tożsamość</th><th>Źródło</th><th>Mapping</th><th>Runtime</th><th>Archiwum</th><th>Trening</th><th>Czego brakuje</th></tr></thead>
        <tbody>
          <tr data-adapter="SAR"><td>Parabolic SAR ({st.sar?.profile}, {st.sar?.live_params?.step}/{st.sar?.live_params?.max})</td><td>własna implementacja</td>
            <td>MT5 (bary bota)</td><td>—</td><td>działa</td><td>—</td><td>kalibracja: {st.sar?.calibration}; wagi: nie dotyczy</td><td>parytet iSAR: {st.sar?.mt5_parity}</td></tr>
          {Object.values(src).map((v: any) => (
            <tr key={v.adapter} data-adapter={v.adapter}><td>{v.title}</td><td>{SRC_PL[v.identity_status] ?? v.identity_status}</td>
              <td>{SRC_PL[v.source_status] ?? v.source_status}{v.heartbeat ? ` (${fmtTime(v.heartbeat.at, true)})` : ""}</td>
              <td>{MAP_PL[v.mapping_status] ?? v.mapping_status}</td><td>{v.runtime_status}</td><td>{v.archived_approved}</td><td>{v.training_status}</td>
              <td className="wrap-cell">{(v.needs || []).join("; ") || "—"}</td></tr>))}
        </tbody></table></div>
      <h4>Model reakcji SCALP_INDICATOR_CONTEXT_V1 (zadanie {st.model?.task_id})</h4>
      <p className="small">Aktywny (SHADOW): <span className="mono">{act ? `${act.run_id} / ${act.variant}` : "brak"}</span>{" "}
        <button className="btn ghost" onClick={() => apiSend("POST", "/api/v1/indicator-context/train", { asset: st.instrument }).then(() => setMsg("Trening uruchomiony w osobnym procesie."))}
          data-testid="ind-train">Trenuj / oceń</button>{" "}
        {act && <button className="btn ghost" onClick={() => apiSend("POST", "/api/v1/indicator-context/rollback", { asset: st.instrument }).then(load)}>Rollback</button>}</p>
      {msg && <p className="small">{msg}</p>}
      {!runs.length && <p className="muted small">Brak runów – potrzebny eksport REAL_USER_DATA (trening XAUUSD/BTC) albo MODULY_IQ_PAL_SAR.bat.</p>}
      {runs.map(([rid, r]) => (
        <div key={rid} className="small"><span className="mono">{rid}</span> · {r.status} · rola {r.role}
          {(r.artifacts || []).map((a: string) => { const v = a.replace(/^model_/, "").replace(/\.json$/, "");
            return <button key={a} className="btn ghost" disabled={r.role === "fixture_only"} title={r.role === "fixture_only" ? "dane syntetyczne – nigdy aktywne" : "aktywuj do obserwacji SHADOW"}
              onClick={() => apiSend("POST", "/api/v1/indicator-context/activate", { asset: st.instrument, run_id: rid, variant: v }).then((x: any) => { setMsg(x.ok ? `Aktywny: ${v}` : x.reason); load(); })}>{v}</button>; })}
        </div>))}
    </div>);
}

/** PMW-UPD-03 SCALP_NET_PROFIT_MARKET_V1: candidates, runs, roles (OBSERVE / SHADOW_GATE chosen by the user), predictions with
 * TreeSHAP explanation. The probability is P(positive NET result of the whole scalp cycle) - not P(price up). */
export function ScalpMlCard({ asset }: { asset?: string }) {
  const [st, setSt] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [ex, setEx] = useState<any>(null);
  const load = () => asset && apiGet(`/api/v1/ml/scalp?asset=${asset}`).then((r) => r.instrument === asset && setSt(r)).catch(() => undefined);
  useEffect(() => { setSt(null); load(); const t = setInterval(load, 7000); return () => clearInterval(t); }, [asset]);
  if (!st) return null;
  const sel = st.selected || {};
  const runs = Object.entries(st.runs || {}) as [string, any][];
  const act = (path: string, body: any) => apiSend("POST", path, { asset, ...body }).then((x: any) => { setMsg(x.ok === false ? x.reason : x.started ? "Uruchomiono w osobnym procesie." : "OK"); load(); });
  return (
    <div className="card" data-testid="ml-scalp">
      <h3>Scalp ML – wynik netto cyklu ({st.task_id}) – {st.instrument}</h3>
      <p className="muted small">XGBoost osobno dla LONG i SHORT: P(dodatni wynik netto całego cyklu po kosztach) i oczekiwany net_R. Nie jest to P(wzrost ceny) ani sygnał.
        Model nigdy nie jest wybierany automatycznie; rola SHADOW_GATE tylko po zaliczonym holdoucie i tylko jako hipotetyczny filtr – bez wpływu na zlecenia.</p>
      <p className="small">Kandydaci (live): {Object.entries(st.live_samples || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "brak"} · klasy: {Object.entries(st.classes || {}).map(([k, v]: [string, any]) => `${k} +${v.pos}/−${v.neg}`).join(" · ") || "—"}</p>
      <p className="small">Wybrane: {["BUY", "SELL"].map((s) => <span key={s}>{s}: <span className="mono">{sel[s] ? `${sel[s].run_id} (${sel[s].role})` : "brak"}</span>
        {sel[s] && <button className="btn ghost" onClick={() => act("/api/v1/ml/scalp/rollback", { side: s })}>Rollback</button>} </span>)}</p>
      <p className="small"><button className="btn ghost" data-testid="ml-scalp-prepare" onClick={() => act("/api/v1/ml/scalp/prepare", {})}>Przygotuj dane</button>{" "}
        <button className="btn ghost" data-testid="ml-scalp-train" onClick={() => act("/api/v1/ml/scalp/train", {})}>Trenuj i oceń (bez aktywacji)</button></p>
      {msg && <p className="small">{msg}</p>}
      {!runs.length && <p className="muted small">Brak runów – potrzebny eksport REAL_USER_DATA (00_TRENING_START.bat) albo 24_SCALP_ML.bat.</p>}
      {runs.map(([rid, r]) => (
        <div key={rid} className="small"><span className="mono">{rid}</span> · {r.status} · rola {r.role}
          {Object.entries(r.sides || {}).map(([side, v]: [string, any]) => <span key={side}> · {side}: {v.status}
            {v.model_hash && r.role !== "FIXTURE_ONLY" && <>
              <button className="btn ghost" onClick={() => act("/api/v1/ml/scalp/select", { run_id: rid, side, role: "OBSERVE" })}>OBSERVE</button>
              <button className="btn ghost" disabled={v.status !== "HOLDOUT_PASSED"} title={v.status !== "HOLDOUT_PASSED" ? "wymaga HOLDOUT_PASSED" : "hipotetyczny filtr w cieniu"}
                onClick={() => act("/api/v1/ml/scalp/select", { run_id: rid, side, role: "SHADOW_GATE" })}>SHADOW_GATE</button></>}</span>)}
        </div>))}
      {(st.recent_predictions || []).length > 0 && <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Czas</th><th>Strona</th><th>P(net&gt;0)</th><th>E[net_R]</th><th>Filtr</th><th>Rola</th><th></th></tr></thead>
        <tbody>{st.recent_predictions.map((p: any) => <tr key={p.prediction_id}><td>{fmtTime(p.computed_at, true)}</td><td>{p.side}</td><td>{p.p == null ? "niekalibrowane" : fmtNum(p.p * 100, 1) + "%"}</td>
          <td>{fmtNum(p.expected_net_r, 3)}</td><td>{p.proposed_filter == null ? "—" : p.proposed_filter ? "przepuść" : "odrzuć"}</td><td>{p.role}</td>
          <td><button className="btn ghost" onClick={() => apiGet(`/api/v1/ml/scalp/explain?prediction_id=${p.prediction_id}`).then(setEx)}>Dlaczego?</button></td></tr>)}</tbody></table></div>}
      {ex && <div className="small" data-testid="ml-scalp-explain">{ex.status === "MODEL_CHANGED" ? ex.reason : <>
        <b>{ex.method}</b> ({ex.units}); bias {fmtNum(ex.bias, 3)}, margines {fmtNum(ex.raw_margin, 3)}, suma {ex.sum_check ? "zgodna" : "NIEZGODNA"}
        <ul>{(ex.top || []).map((t: any) => <li key={t.feature}><span className="mono">{t.feature}</span> = {t.value == null ? "brak" : fmtNum(t.value, 3)} → {t.contribution > 0 ? "+" : ""}{fmtNum(t.contribution, 3)}</li>)}</ul>
        pozostałe cechy: {fmtNum(ex.other_features, 3)}</>}</div>}
    </div>);
}

// ------------------------------------------------------------------------------------------- Badania i walidacja
export function ResearchPage() {
  const { s } = useStore();
  const active = s.assets?.active;
  const [tr, setTr] = useState<any>(null);
  const [study, setStudy] = useState<any>(null);
  const [trials, setTrials] = useState<any>(null);
  const [flt, setFlt] = useState("");
  useEffect(() => {
    apiGet("/api/v1/lab/traceability").then(setTr).catch(() => undefined);
    if (!active) return;
    apiGet(`/api/v1/lab/trials?asset=${active}`).then((r) => r.asset === active && setTrials(r)).catch(() => undefined);
    apiGet("/api/v1/lab/jobs").then(async (r) => {
      const j = r.jobs.find((x: any) => x.asset === active && x.result_file);
      setStudy(j ? await apiGet(`/api/v1/lab/studies/${j.job_id}`) : null);
    }).catch(() => undefined);
  }, [active]);
  const rows = (tr?.rows || []).filter((r: any) => !flt || JSON.stringify(r).toLowerCase().includes(flt.toLowerCase()));
  return (
    <div className="lab-page" data-testid="page-badania">
      <h2>Badania i walidacja – {active}</h2>
      <div className="card" data-testid="study">
        <h3>Ostatnie badanie</h3>
        {!study ? <p className="muted">Brak wykonanego badania dla {active} w tej sesji (Modele i trening → Uruchom badanie). Bez danych MT5: BLOCKED_NO_REAL_DATA.</p> : (<>
          <p><b>Werdykt: {study.verdict}</b> {study.candidate?.reason ? `– ${study.candidate.reason}` : ""}</p>
          <p className="small mono">{study.protocol_id} · dane {study.data_source} · hash {study.data_hash} · zdarzeń {study.samples} (dev {study.dev_samples} / holdout {study.holdout_samples}) · niejednoznaczne SL/TP w świecy {study.ambiguous_same_bar}
            · okres {fmtTime(study.period?.from, true)} – {fmtTime(study.period?.to, true)} · holdout od {fmtTime(study.holdout_from, true)} (hash {study.holdout_hash})</p>
          <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Rodzina</th><th>Status</th><th>Log loss</th><th>Brier</th><th>ECE</th><th>AUC</th><th>Expectancy R</th><th>Pokrycie</th><th>Transakcje</th></tr></thead>
            <tbody>{Object.entries(study.families || {}).map(([k, v]: [string, any]) => (
              <tr key={k}><td>{k}</td><td>{v.status}{v.note ? ` (${v.note})` : ""}</td><td>{fmtNum(v.log_loss_mean, 4)} ±{fmtNum(v.log_loss_std, 4)}</td><td>{fmtNum(v.brier_mean, 4)}</td>
                <td>{fmtNum(v.ece_mean, 3)}</td><td>{fmtNum(v.auc_mean, 3)}</td><td>{v.expectancy_r_mean == null ? "—" : fmtNum(v.expectancy_r_mean, 3)}</td><td>{fmtNum((v.coverage_mean ?? 0) * 100, 1)}%</td><td>{v.trades_total}</td></tr>))}</tbody></table></div>
          <p className="small">Kontrole negatywne: {Object.entries(study.controls || {}).map(([k, v]: [string, any]) => `${k}: zysk vs dummy ${fmtNum(v.logloss_gain_vs_dummy, 4)}${v.suspicious ? " ⚠ PODEJRZANE" : " (OK)"}`).join(" · ")}</p>
          <p className="small">Holdout: {study.holdout ? (study.holdout.refused ? study.holdout.refused : `użyty raz – ${study.holdout.passed ? "zaliczony" : "niezaliczony"}`) : "nie użyty (brak kandydata po danych rozwojowych)"}</p>
        </>)}
      </div>
      <Section id="lab.trials" title={`Rejestr prób (${trials?.trials?.length ?? 0}) i dostęp do holdoutu`}>
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Czas</th><th>Rodzina</th><th>Horyzont</th><th>Status</th><th>Protokół</th><th>Dane</th></tr></thead>
          <tbody>{(trials?.trials || []).slice(0, 60).map((t: any) => <tr key={t.trial_id}><td>{fmtTime(t.created_at, true)}</td><td>{t.model_family}</td><td>{t.horizon}</td><td>{t.status}</td><td className="mono">{t.protocol_id}</td><td className="mono">{t.data_hash}</td></tr>)}</tbody></table></div>
        <p className="small">Użycia holdoutu: {(trials?.holdout_access || []).length}</p>
      </Section>
      <div className="card" data-testid="traceability">
        <h3>Macierz pokrycia M01–M42 {tr?.summary ? `· ${JSON.stringify(tr.summary.implementation_status)}` : ""}</h3>
        <input className="filter" placeholder="filtr (np. blocked, shadow, M16)" value={flt} onChange={(e) => setFlt(e.target.value)} aria-label="Filtr macierzy" />
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>ID</th><th>Element</th><th>Status</th><th>Dostępność</th><th>Rola</th><th>Pliki</th><th>Integracja</th><th>Ograniczenia</th></tr></thead>
          <tbody>{rows.map((r: any) => (
            <tr key={r.id} className={r.implementation_status === "blocked" ? "bad" : r.implementation_status === "verified" ? "" : "warn"}>
              <td>{r.id}</td><td>{r.element}</td><td>{r.implementation_status}</td><td>{r.availability}</td><td>{ROLE_PL[r.decision_role] ?? r.decision_role}</td>
              <td className="mono">{r.files}</td><td>{r.integration}</td><td>{r.limits}</td></tr>))}</tbody></table></div>
      </div>
      <p><a className="btn ghost" href={href("formacje")}>Pattern Library – VALIDATE ALL / SHOW ON CHART →</a></p>
    </div>);
}

// ------------------------------------------------------------------------------------------- Dane i źródła
export function DataPage() {
  const { s } = useStore();
  const { lab, active } = useLab();
  const [rep, setRep] = useState<any>(null);
  const [tr, setTr] = useState<any>(null);
  useEffect(() => {
    apiGet("/api/v1/lab/repaint").then(setRep).catch(() => undefined);
    apiGet("/api/v1/lab/traceability").then(setTr).catch(() => undefined);
  }, [lab?.seq]);
  const tk = lab?.ticks;
  return (
    <div className="lab-page" data-testid="page-dane">
      <h2>Dane i źródła – {active}</h2>
      <div className="an-grid">
        <div className="card"><h3>Połączenie i świeżość</h3>
          <p>MT5: <b className={tone(s.connection?.state)}>{s.connection?.state}</b> · symbol {s.symbol?.symbol} ({s.symbol?.status}) · notowanie {s.quote?.age_seconds != null ? `${Math.round(s.quote.age_seconds)} s` : "—"}</p>
          <p className="small">Lab: obliczenie {fmtTime(lab?.computed_at, true)} · dane do {fmtTime(lab?.as_of, true)} · {lab?.latency_ms} ms · trace {lab?.trace_id} · {lab?.stale ? `NIEAKTUALNE (${lab.stale_reason})` : "aktualne"}</p>
          <p className="small">Pokrycie: {Object.entries(lab?.modules || {}).map(([tf, m]: [string, any]) => `${tf} ${m.bars ?? 0} świec`).join(" · ")}</p>
        </div>
        <div className="card" data-testid="ticks-card"><h3>Ticki: aktywność (M28) i kinematyka (M31)</h3>
          {!tk ? <Missing why="brak odczytu" /> : (<>
            <p className="small">Źródło {tk.source ?? "—"} · {tk.count} ticków · status {tk.status}{tk.reason ? ` (${tk.reason})` : ""}</p>
            {tk.acd?.status === "ready" ? <p className="small">ACD(1,1): α={fmtNum(tk.acd.fit.alpha, 3)} β={fmtNum(tk.acd.fit.beta, 3)} · oczekiwane czekanie {tk.acd.expected_wait_s} s · od ostatniej zmiany {tk.acd.elapsed_since_last_change_s} s · ratio {tk.acd.activity_ratio ?? "—"} · <b>{tk.acd.state}</b> · przerwy usunięte {tk.acd.gaps_removed}</p>
              : <p className="small muted">ACD: {tk.acd?.reason ?? "brak"}</p>}
            {tk.kinematics?.status === "ready" ? <p className="small">Prędkość {fmtNum(tk.kinematics.velocity_per_s, 5)}/s (±{fmtNum(tk.kinematics.velocity_se, 5)}) · przysp. {fmtNum(tk.kinematics.acceleration_per_s2, 6)} · istotna: {tk.kinematics.significant_velocity ? "tak" : "nie"} · weryfikacja: {tk.kinematics_verification?.verified ?? 0} prognoz, pokrycie 2σ {tk.kinematics_verification?.coverage_2se != null ? fmtNum(tk.kinematics_verification.coverage_2se * 100, 0) + "%" : "—"}</p>
              : <p className="small muted">Kinematyka: {tk.kinematics?.reason ?? "brak"}</p>}
            <p className="small muted">{tk.acd?.policy}</p></>)}
        </div>
        <div className="card"><h3>Repaint Inspector (M39)</h3>
          <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Moduł</th><th>TF</th><th>Obserwacje</th><th>Zmiany</th><th>Nowe</th><th>Zniknięte</th><th>Od</th></tr></thead>
            <tbody>{(rep?.report || []).map((r: any) => <tr key={r.module + r.tf + r.asset}><td>{r.asset} {r.module}</td><td>{r.tf}</td><td>{r.observations}</td><td>{r.changed}</td><td>{r.appeared}</td><td>{r.vanished}</td><td>{fmtTime(r.observing_since, true)}</td></tr>)}</tbody></table></div>
          <p className="small muted">Brak zmian w okresie obserwacji nie dowodzi braku repaintingu.</p></div>
        <div className="card"><h3>Strefy S/D (M18) i archiwum prognoz (M29)</h3>
          <p className="small">Strefy: {(lab?.zones || []).length} (zapis transakcyjny + snapshot .bak) {lab?.zone_events?.length ? `· zdarzenia: ${lab.zone_events.map((e: any) => e.event).join(", ")}` : ""}</p>
          {Object.entries(lab?.fourier || {}).map(([tf, f]: [string, any]) => <p key={tf} className="small">Fourier {tf}: {f.forecast.harmonics.length} harmonicznych · ocena z archiwum: {f.archive_evaluation.evaluated_points} punktów{f.archive_evaluation.mae != null ? `, MAE ${fmtNum(f.archive_evaluation.mae, 3)}` : ""}</p>)}
        </div>
        <div className="card"><h3>Źródła zewnętrzne i licencje</h3>
          <ul className="small">{(tr?.rows || []).filter((r: any) => r.implementation_status === "blocked" || r.availability !== "available").map((r: any) => <li key={r.id}><b>{r.id}</b> {r.element}: {r.availability} – {r.limits}</li>)}</ul></div>
      </div>
    </div>);
}

// ------------------------------------------------------------------------------------------- Ustawienia
export function LabSettingsPage() {
  const { s, refresh } = useStore();
  const { openSettings } = useUi();
  const a = s.assets;
  const [cands, setCands] = useState<Record<string, any[]>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const find = async (asset: string) => {
    setMsg(null);
    try { setCands({ ...cands, [asset]: (await apiGet(`/api/v1/assets/${asset}/candidates`)).candidates }); } catch (e: any) { setMsg(String(e?.message || e)); }
  };
  const confirm = async (asset: string, sym: string) => {
    setMsg(null);
    try { await apiSend("POST", "/api/v1/assets/confirm", { asset, broker_symbol: sym }); await refresh(); setMsg(`${asset} → ${sym} potwierdzone.`); } catch (e: any) { setMsg(String(e?.message || e)); }
  };
  return (
    <div className="lab-page" data-testid="page-ustawienia">
      <h2>Ustawienia</h2>
      <div className="card" data-testid="asset-mapping">
        <h3>Aktywa (tylko XAUUSD i BTC)</h3>
        <p className="muted small">Bot używa symboli włączonych na Twoim rachunku. Brak zapisanego symbolu → bierze pasujący symbol z terminala (najpierw z Market Watch). Metadane są tylko informacją – nic nie jest blokowane. Możesz wybrać inny symbol przyciskiem „Użyj”.</p>
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Aktywo</th><th>Symbol brokera</th><th>Mapowanie</th><th>Metadane</th><th>Użyteczne</th><th></th></tr></thead>
          <tbody>{(a?.allowed || []).map((id: string) => {
            const it = a.assets[id];
            return (<tr key={id} data-asset={id}><td><b>{id}</b>{a.active === id ? " (aktywne)" : ""}</td><td className="mono">{it.broker_symbol ?? "—"}</td><td>{it.mapping_status}</td>
              <td>{it.metadata_check?.status}{it.metadata_check?.reasons?.length ? ` – ${it.metadata_check.reasons.join(", ")}` : ""}</td><td>{it.usable ? "tak" : `nie – ${it.blocked_reason}`}</td>
              <td><button className="btn ghost" onClick={() => find(id)}>Szukaj kandydatów</button></td></tr>);
          })}</tbody></table></div>
        {Object.entries(cands).map(([asset, list]) => (
          <div key={asset} className="small" data-testid={`cands-${asset}`}><b>{asset}:</b> {!list.length ? "brak kandydatów w terminalu" : list.map((c) => (
            <span key={c.broker_symbol} className="cand">{c.broker_symbol} ({c.currency_base}/{c.currency_profit}, kontrakt {c.contract_size}{c.conflicts.length ? `, ${c.conflicts.join(",")}` : ""})
              {c.eligible && <button className="btn" onClick={() => confirm(asset, c.broker_symbol)}>Użyj</button>}</span>))}</div>))}
      </div>
      <div className="card" data-testid="exec-card">
        <h3>Wykonanie zleceń</h3>
        <p>Tryb: <b>{s.mode?.mode_label ?? s.mode?.mode ?? "—"}</b>{s.mode?.bound_account ? <> · rachunek <span className="mono">{s.mode.bound_account}</span></> : null}
          {" "}· nowe wejścia: <b className={s.mode?.kill_switch ? "bad" : "ok"}>{s.mode?.kill_switch ? "STOP" : "dozwolone wg trybu"}</b></p>
        {s.mode?.mode_note && <p className="warn small" data-testid="mode-note">{s.mode.mode_note}</p>}
        <p className="muted small">Execution Lock został wycofany (1.24, decyzja użytkownika). O wysyłce decydują: tryb wykonania (zmiana przyciskiem „Wykonanie” –
          tryby AUTO z potwierdzeniem rachunku), STOP nowych wejść, limity ryzyka, aktualne dane i warunki brokera.</p>
      </div>
      <div className="card"><h3>Pozostałe ustawienia</h3>
        <p className="muted small">MT5, ryzyko, koszty, AI, Telegram, motyw i paleta – w dotychczasowym oknie ustawień.</p>
        <button className="btn" onClick={openSettings}>Otwórz ustawienia MT5 / ryzyko / koszty</button></div>
      {msg && <p className="small" role="status">{msg}</p>}
    </div>);
}
