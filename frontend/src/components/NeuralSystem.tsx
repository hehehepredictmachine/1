// PMW-UPD-04 Neural Scalp System (CAUSAL_MTF_TCN_V1): dashboard card + detail page (#/neural). Everything shown comes from ONE
// server snapshot (/api/v1/lab/neural, refreshed on the WS event 'lab_neural'); the browser computes nothing. A response for another
// asset or an older seq is dropped. No model -> static architecture + "Brak wytrenowanego modelu"; no inference -> no activations.
import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { href } from "../router";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";

const CLS_PL: Record<string, string> = { TP1_FIRST: "TP1 przed SL", SL_FIRST: "SL przed TP1", TIMEOUT: "limit czasu" };
const TECH_PL: Record<string, string> = {
  NO_MODEL: "brak wytrenowanego modelu", READY_INFERENCE: "inferencja wykonana", WARMING_UP: "rozgrzewka danych", DATA_GAP: "luka w danych",
  INVALID_FEATURES: "niepoprawne cechy", TIMEOUT: "przekroczony czas", ERROR: "błąd", UNSUPPORTED_ENTRY_POLICY: "wejście nieobsługiwane (tylko MARKET)", STALE: "nieaktualne",
};

export function useNeural() {
  const { s } = useStore();
  const asset = s.assets?.active;
  const tick = (s as any).lab_neural?.seq;
  const [d, setD] = useState<any>(null);
  const req = useRef(0);
  useEffect(() => {
    if (!asset) return;
    const id = ++req.current;
    const load = () => apiGet(`/api/v1/lab/neural?asset=${asset}`).then((r) => {
      if (id !== req.current || r.asset !== asset) return;                   // stale answer (fast asset switch)
      setD((old: any) => (old?.snapshot?.seq && r.snapshot?.seq && r.snapshot.seq < old.snapshot.seq && old.asset === r.asset ? old : r));
    }).catch(() => undefined);
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [asset, tick]);
  return d;
}

function usePulse(id: string | undefined) {
  const [on, setOn] = useState(false);
  const last = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!id || id === last.current) return;
    last.current = id;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    setOn(true);
    const t = setTimeout(() => setOn(false), 1500);                          // the flow animation ends - no fake "continuous thinking"
    return () => clearTimeout(t);
  }, [id]);
  return on;
}

function Probs({ co }: { co: any }) {
  if (!co) return null;
  const cal = co.calibrated_probabilities;
  return (
    <div className="small" data-testid="nss-probs">
      <table className="tbl small"><thead><tr><th>Zdarzenie ({co.side})</th><th>Wynik surowy modelu</th><th>Po kalibracji</th></tr></thead>
        <tbody>{(co.class_order || []).map((c: string, i: number) => (
          <tr key={c} data-class={c}><td>{CLS_PL[c] ?? c}</td><td>{fmtNum(co.raw_probabilities[i] * 100, 1)}%</td>
            <td>{cal ? `${fmtNum(cal[i] * 100, 1)}%` : "niekalibrowane"}</td></tr>))}</tbody></table>
      <p>Estymata net_R całego cyklu (po kosztach, jednostka R): <b>{fmtNum(co.expected_net_R, 3)} R</b> – estymata modelu, nie gwarantowany zarobek.</p>
      <p className="muted">{co.outcome_definition}. Kalibracja: {co.calibration_status}. Filtr polityki: {co.proposed_filter_result == null ? "niedostępny" : co.proposed_filter_result ? "przepuściłby" : "odrzuciłby"}
        {co.policy_thresholds ? ` (P(TP1) ≥ ${co.policy_thresholds.p_tp1_min}, net_R ≥ ${co.policy_thresholds.net_r_min})` : ""}.</p>
    </div>);
}

/** Graph built from the model metadata: lanes follow the edges by layer_id (not array order). */
function Graph({ arch, layers, pulse, onPick, picked }: { arch: any; layers?: any[]; pulse: boolean; onPick: (id: string) => void; picked?: string | null }) {
  const byId = useMemo(() => Object.fromEntries((arch?.nodes || []).map((n: any) => [n.layer_id, n])), [arch]);
  const stat = useMemo(() => Object.fromEntries((layers || []).map((l: any) => [l.layer_id, l])), [layers]);
  if (!arch) return null;
  const next = (id: string) => (arch.edges || []).filter((e: any) => e.source_layer_id === id).map((e: any) => e.target_layer_id);
  const lane = (start: string) => {
    const out: string[] = [];
    let cur: string | undefined = start;
    while (cur && byId[cur] && !out.includes(cur) && cur !== "fusion") {
      out.push(cur);
      cur = next(cur)[0];
    }
    return out;
  };
  const box = (id: string) => {
    const n = byId[id];
    const st = stat[id];
    const act = st?.active_fraction;
    return (
      <button key={id} className={cls("nn-box nss-node", picked === id && "sel")} data-layer={id} onClick={() => onPick(id)}
        style={act != null ? { boxShadow: `inset 0 -${Math.round(act * 100) / 4}px 0 var(--accent, #d4a017)` } : undefined}
        title={`${n.operation}${n.dilation ? `, dylatacja ${n.dilation}` : ""}`}>
        <span className="small">{n.name}</span>
        <span className="muted small">{st ? (act != null ? `aktywne ${fmtNum(act * 100, 0)}%` : `|a| ${fmtNum(st.mean_abs, 2)}`) : n.shape_out?.join("×")}</span>
      </button>);
  };
  const heads = (arch.nodes || []).filter((n: any) => n.area === "WYNIK").map((n: any) => n.layer_id);
  return (
    <div className={cls("nss-graph", pulse && "nn-pulse")} data-testid="nss-graph">
      <div className="nss-area"><h4>DANE</h4>{["in_m1", "in_m5", "in_ctx"].filter((x) => byId[x]).map(box)}</div>
      <div className="nss-area"><h4>PRZETWARZANIE</h4>
        {["in_m1", "in_m5", "in_ctx"].map((s) => <div key={s} className="nss-lane">{lane(s).slice(1).map(box)}</div>)}
        <div className="nss-lane">{byId.fusion && box("fusion")}</div></div>
      <div className="nss-area"><h4>WYNIK</h4>{heads.map(box)}</div>
    </div>);
}

function Heatmap({ layer }: { layer: any }) {
  const hm = layer?.heatmap;
  if (!hm) return <p className="muted small">Brak heatmapy dla tej warstwy (warstwa gęsta albo brak inferencji).</p>;
  const span = hm.vmax - hm.vmin || 1;
  return (
    <div data-testid="nss-heatmap">
      <div className="nss-heat" style={{ gridTemplateColumns: `repeat(${hm.values[0]?.length || 1}, 1fr)` }}>
        {hm.values.flatMap((row: number[], i: number) => row.map((v, j) => {
          const t = (v - hm.vmin) / span;
          return <span key={`${i}-${j}`} title={`kanał ${hm.sampled_channel_ids[i]}, krok ${hm.sampled_times[j]}: ${fmtNum(v, 3)}`}
            style={{ background: `rgba(212,160,23,${0.08 + 0.92 * t})` }} />;
        }))}
      </div>
      <p className="muted small">Skala: min {fmtNum(hm.vmin, 3)} → max {fmtNum(hm.vmax, 3)}; kanały × ostatnie {hm.values[0]?.length} kroków (rzeczywiste aktywacje tej inferencji).</p>
    </div>);
}

// ------------------------------------------------------------------------------------------- dashboard card
export function NeuralCard() {
  const d = useNeural();
  const snap = d?.snapshot;
  const ctx = d?.context;
  const pulse = usePulse(snap?.inference_id);
  if (!d) return null;
  if (d.status === "ASSET_NOT_ACTIVE") return null;
  const cur = snap && !snap.historical ? snap : null;
  return (
    <div className="card nn-card" data-testid="nss-card">
      <div className="nn-head"><h3>Neural System — Scalping</h3>
        <span className="chips-row small">
          <span className="chip">{d.asset}</span><span className="chip">M1 128 · M5 32 · M15/H1</span>
          <span className="chip">rola: {d.selected?.role ?? "brak"}</span>
          <span className="chip">model: {d.trained ? "wytrenowany" : "brak wytrenowanego modelu"}</span>
          <span className="chip">worker: {d.worker_status}</span></span></div>
      <Graph arch={snap?.architecture || d.architecture} layers={cur?.layers || (ctx && !ctx.historical ? ctx.layers : undefined)} pulse={pulse} onPick={() => undefined} />
      {cur?.candidate_output ? <Probs co={cur.candidate_output} /> :
        <p className="small" data-testid="nss-no-setup">{cur ? `Wynik: ${TECH_PL[cur.technical_status] ?? cur.technical_status}${cur.reasons?.length ? " – " + cur.reasons.join("; ") : ""}`
          : "Brak setupu — analiza kontekstu (bez prawdopodobieństwa TP i bez poziomów)."}</p>}
      <p className="muted small">{snap ? `Ostatnia inferencja ${fmtTime(snap.computed_at, true)} · setup ${snap.setup_id} · ${snap.historical ? "HISTORYCZNA (wygasła)" : "ważna do " + fmtTime(snap.expires_at, true)} · model ${snap.model_hash?.slice(0, 10) ?? "—"}`
        : "Brak inferencji w tej sesji."}{" "}
        <a href={href("neural" as any)}>Szczegóły sieci</a> · <a href={href("warunki", { setupId: snap?.setup_id })}>Warunki setupu</a> · <a href={href("neural" as any, { params: { v: "trening" } })}>Model i walidacja</a></p>
    </div>);
}

// ------------------------------------------------------------------------------------------- detail page
const VIEWS = [["przeplyw", "Przepływ i warstwy"], ["aktywacje", "Aktywacje"], ["setup", "Setup"], ["trening", "Trening i walidacja"], ["historia", "Historia i zdrowie"]] as const;

export function NeuralPage({ params }: { params?: URLSearchParams }) {
  const d = useNeural();
  const { s } = useStore();
  const [view, setView] = useState<string>(params?.get("v") || "przeplyw");
  const [picked, setPicked] = useState<string | null>(null);
  const [rep, setRep] = useState<any>(null);
  const [hist, setHist] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [doc, setDoc] = useState<any>(null);
  const asset = s.assets?.active;
  useEffect(() => {
    if (!asset) return;
    apiGet(`/api/v1/lab/neural/report?asset=${asset}`).then((r) => r.asset === asset && setRep(r)).catch(() => undefined);
    apiGet("/api/v1/lab/neural/history").then((r) => r.asset === asset && setHist(r.rows)).catch(() => undefined);
  }, [asset, d?.snapshot?.inference_id]);
  if (!d) return <div className="lab-page"><p className="muted">Ładowanie…</p></div>;
  const snap = d.snapshot;
  const layers = snap?.layers || d.context?.layers;
  const layer = (layers || []).find((l: any) => l.layer_id === picked) || (layers || [])[1];
  const node = (d.architecture?.nodes || []).find((n: any) => n.layer_id === (picked || layer?.layer_id));
  const act = (path: string, body: any = {}) => apiSend("POST", path, { asset, ...body }).then((x: any) => setMsg(x.ok === false || x.started === false ? x.reason : x.started ? `Zadanie ${x.job_id} uruchomione w osobnym procesie.` : "OK"))
    .catch((e: any) => setMsg(String(e?.message || e)));
  const r = rep?.report;
  return (
    <div className="lab-page" data-testid="page-neural">
      <h2>Neural System — Scalping ({d.asset})</h2>
      <p className="muted small">{d.architecture_id} · zadanie {d.task_id} · parametry {d.architecture?.params_total} · MACs {d.architecture?.macs_per_inference} · pole recepcyjne M1 {d.architecture?.receptive_field?.M1} / M5 {d.architecture?.receptive_field?.M5}
        · rola {d.selected?.role ?? "brak"} · bez wpływu na zlecenia i tryb wykonania.</p>
      <div className="chips-row">
        <button className="btn ghost" data-testid="nss-doctor" onClick={() => apiSend("POST", "/api/v1/lab/neural/doctor", { asset }).then(setDoc)}>Sprawdź gotowość</button>
        <button className="btn ghost" onClick={() => act("/api/v1/lab/neural/prepare")}>Przygotuj dane</button>
        <button className="btn ghost" data-testid="nss-train" onClick={() => act("/api/v1/lab/neural/train")}>Trenuj kandydata</button>
        <button className="btn ghost" onClick={() => apiGet("/api/v1/lab/neural/jobs").then((j) => { const run = j.jobs.find((x: any) => x.running); return run ? act("/api/v1/lab/neural/cancel", { job_id: run.job_id }) : setMsg("Brak działającego zadania."); })}>Anuluj</button>
        <button className="btn ghost" onClick={() => setView("trening")}>Otwórz raport</button>
        <button className="btn ghost" disabled={!r?.model_hash || r?.role === "FIXTURE_ONLY"} title={r?.role === "FIXTURE_ONLY" ? "dane syntetyczne – nigdy do wyboru" : ""}
          onClick={() => act("/api/v1/lab/neural/select", { run_id: rep?.run_id, role: "OBSERVE" })}>Wybierz model do obserwacji</button>
        <button className="btn ghost" onClick={() => act("/api/v1/lab/neural/rollback")}>Przywróć poprzedni</button></div>
      {msg && <p className="small">{msg}</p>}
      {doc && <pre className="small mono wrap-cell" data-testid="nss-doctor-out">{JSON.stringify({ blocked: doc.blocked, latest_real_export: doc.latest_real_export, costs: doc.costs, live_inferences: doc.live_inferences }, null, 1)}</pre>}
      <div className="chips-row" role="tablist">{VIEWS.map(([k, l]) => <button key={k} role="tab" aria-selected={view === k} className={cls("chip", view === k && "on")} onClick={() => setView(k)}>{l}</button>)}</div>

      {view === "przeplyw" && <div className="card">
        <Graph arch={snap?.architecture || d.architecture} layers={layers} pulse={false} onPick={setPicked} picked={picked} />
        {node && <div className="small" data-testid="nss-layer"><b>{node.name}</b> ({node.layer_id}) – {node.operation}{node.dilation ? `, dylatacja ${node.dilation}, pole recepcyjne ${node.receptive_field}` : ""};
          wejście {JSON.stringify(node.shape_in)} → wyjście {JSON.stringify(node.shape_out)}; parametry {node.params}
          {layer && layer.layer_id === node.layer_id ? ` · średnia ${fmtNum(layer.mean, 3)}, odch. ${fmtNum(layer.std, 3)}, |a| ${fmtNum(layer.mean_abs, 3)}, L2 ${fmtNum(layer.l2_norm, 2)}${layer.active_fraction != null ? `, aktywne ${fmtNum(layer.active_fraction * 100, 0)}%` : ""}` : " · brak statystyk (brak inferencji)"}</div>}
        {!d.trained && <p className="muted">Brak wytrenowanego modelu – schemat architektury bez aktywacji.</p>}
      </div>}

      {view === "aktywacje" && <div className="card">
        <label className="small">Warstwa: <select value={layer?.layer_id || ""} onChange={(e) => setPicked(e.target.value)} aria-label="Warstwa heatmapy">
          {(layers || []).filter((l: any) => l.heatmap).map((l: any) => <option key={l.layer_id} value={l.layer_id}>{l.layer_id}</option>)}</select></label>
        {layers ? <Heatmap layer={layer} /> : <p className="muted">Brak inferencji – brak aktywacji (nic nie jest symulowane).</p>}
        {snap?.telemetry_member && <p className="muted small">Warstwy członka {snap.telemetry_member}; wynik = średnia {snap.ensemble_member_ids?.length} członków (nie średnia aktywacji).</p>}
      </div>}

      {view === "setup" && <div className="card">
        {snap ? <>
          <p className="small">Setup <a href={href("warunki", { setupId: snap.setup_id })}>{snap.setup_id}</a> · strona {snap.side} · sygnał {fmtTime(snap.signal_time, true)} · decyzja {fmtTime(snap.decision_time, true)}
            · TP1 {snap.candidate_output?.tp1 ?? "—"} · SL {snap.candidate_output?.sl ?? "—"} · ważność {fmtTime(snap.expires_at, true)} {snap.historical ? "(HISTORYCZNY)" : ""}</p>
          <p className="small">Stan: {TECH_PL[snap.technical_status] ?? snap.technical_status} · tryb {snap.mode}{snap.shadow_gate_active ? " (SHADOW_GATE aktywny dla tej strony)" : ""} · archiwum {snap.archived ? "zapisane" : "NIEZAPISANE"} · snapshot {snap.snapshot_hash}</p>
          <p className="small">Wejścia: {(snap.inputs || []).map((i: any) => `${i.tf}: ${i.quality} (${fmtTime(i.last_bar_close, true)})`).join(" · ")}</p>
          <Probs co={snap.candidate_output} />
          <p className="small muted">Czasy: cechy {snap.timings?.feature_ms} ms · kolejka {snap.timings?.queue_ms} ms · forward {snap.timings?.inference_ms ?? "—"} ms · razem {snap.timings?.total_ms} ms</p>
        </> : <p className="muted">Brak setupu — analiza kontekstu. Wynik modelu pojawia się tylko dla rzeczywistego kandydata strategii.</p>}
      </div>}

      {view === "trening" && <div className="card" data-testid="nss-report">
        {!r ? <p className="muted">Brak raportu treningu dla {asset} – potrzebny eksport REAL_USER_DATA (00_TRENING_START.bat), potem „Trenuj kandydata” albo 23_NEURAL_SCALP.bat.</p> : <>
          <p className="small"><b>{r.run_id}</b> · {r.status}{r.reason ? ` – ${r.reason}` : ""} · rola {r.role} · próbek {r.candidates} · pominięte {JSON.stringify(r.skipped)} · dane {r.data_kind} ({r.dataset_id}) · precyzja {r.precision}
            · koszty {r.costs?.commission_per_lot_side ?? "—"}/lot ({r.costs?.commission_source ?? "?"}) · model {r.model_hash?.slice(0, 12) ?? "—"}</p>
          <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Fold</th><th>Status</th><th>Bloki</th><th>Log loss LONG</th><th>Log loss SHORT</th><th>Prior LONG/SHORT</th><th>LogReg LONG/SHORT</th><th>ResNet1D</th></tr></thead>
            <tbody>{(r.folds || []).map((f: any) => <tr key={f.fold}><td>{f.fold + 1}</td><td>{f.status}</td><td className="mono">{JSON.stringify(f.sizes)}</td>
              <td>{fmtNum(f.sides?.["0"]?.log_loss, 4)}</td><td>{fmtNum(f.sides?.["1"]?.log_loss, 4)}</td>
              <td>{fmtNum(f.baselines?.["0"]?.prior_log_loss, 4)} / {fmtNum(f.baselines?.["1"]?.prior_log_loss, 4)}</td>
              <td>{fmtNum(f.baselines?.["0"]?.logreg_log_loss, 4)} / {fmtNum(f.baselines?.["1"]?.logreg_log_loss, 4)}</td><td>{fmtNum(f.baselines?.resnet1d?.log_loss, 4)}</td></tr>)}</tbody></table></div>
          {Object.entries(r.final?.history || {}).map(([seed, h]: [string, any]) => <p key={seed} className="small mono">członek {seed}: {h.history.map((e: any) => `${e.epoch}:${fmtNum(e.train_loss, 3)}/${fmtNum(e.val_loss, 3)}`).join(" ")}</p>)}
          {Object.entries(r.sides || {}).map(([side, v]: [string, any]) => <div key={side} className="small">
            <b>{side}: {v.status}</b> · kalibracja {v.calibration} · holdout n={v.holdout?.n}, dni {v.holdout?.days}, klasy {JSON.stringify(v.holdout?.class_counts)} · log loss {fmtNum(v.holdout?.log_loss, 4)} vs prior {fmtNum(v.holdout?.prior_log_loss, 4)}
            · ECE {fmtNum(v.holdout?.ece_top, 3)} · Brier {fmtNum(v.holdout?.brier, 3)} · net_R RMSE {fmtNum(v.holdout?.net_r_rmse, 3)} (bias {fmtNum(v.holdout?.net_r_bias, 3)})
            · polityka {JSON.stringify(v.holdout?.policy)} wybrała {v.holdout?.policy_selected} (pokrycie {fmtNum((v.holdout?.coverage ?? 0) * 100, 1)}%), średnio {fmtNum(v.holdout?.policy_net_r_mean, 3)} R vs baseline {fmtNum(v.holdout?.baseline_net_r_mean, 3)} R
            · CI95 {JSON.stringify(v.holdout?.policy_boot?.ci95 ?? v.holdout?.policy_boot?.status)} · przyrost CI95 {JSON.stringify(v.holdout?.incremental_boot?.ci95 ?? v.holdout?.incremental_boot?.status)}
            · stres {fmtNum(v.holdout?.stress_net_r_mean, 3)} R · DD {fmtNum(v.holdout?.policy_max_dd_r, 2)} R (baseline {fmtNum(v.holdout?.baseline_max_dd_r, 2)} R)
            {v.holdout?.reliability_tp1?.length ? <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Koszyk P(TP1)</th><th>n</th><th>P średnie</th><th>Częstość</th></tr></thead>
              <tbody>{v.holdout.reliability_tp1.map((b: any) => <tr key={b.bin}><td>{b.bin / 10}–{(b.bin + 1) / 10}</td><td>{b.n}</td><td>{fmtNum(b.p_mean, 3)}</td><td>{fmtNum(b.freq, 3)}</td></tr>)}</tbody></table></div> : null}
          </div>)}
          <p className="muted small">„Trening wykonany” ≠ „przewaga potwierdzona”. HOLDOUT_PASSED wymaga wszystkich zamrożonych kryteriów na nieużytym okresie.</p>
        </>}
      </div>}

      {view === "historia" && <div className="card">
        <p className="small">Kolejka {d.queue} · statystyki {JSON.stringify(d.stats)}</p>
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Czas</th><th>Setup</th><th>Strona</th><th>Stan</th><th>P(TP1)</th><th>net_R</th><th>Etykieta</th><th>Wynik</th><th>Model</th></tr></thead>
          <tbody>{hist.map((h) => { const o = h.output ? JSON.parse(h.output) : null; return (
            <tr key={h.inference_id}><td>{fmtTime(h.computed_at, true)}</td><td>{h.setup_id}</td><td>{h.side}</td><td>{h.technical_status}</td>
              <td>{o?.calibrated_probabilities ? fmtNum(o.calibrated_probabilities[0] * 100, 1) + "%" : "—"}</td><td>{o ? fmtNum(o.expected_net_R, 3) : "—"}</td>
              <td>{h.label_status}{h.label_event ? ` (${CLS_PL[h.label_event] ?? h.label_event})` : ""}</td><td>{h.label_net_r == null ? "—" : fmtNum(h.label_net_r, 3) + " R"}</td>
              <td className="mono">{h.model_hash?.slice(0, 10) ?? "—"}</td></tr>); })}</tbody></table></div>
        {!hist.length && <p className="muted small">Brak inferencji w archiwum.</p>}
      </div>}
    </div>);
}
