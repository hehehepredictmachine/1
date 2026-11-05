// WIND PORTAL – AI ENGINE CORE (ai.jpg + wind.jpg). Sources: /api/v1/models/catalog (model families and their real states),
// /api/v1/models/predictions + /api/v1/models/evidence (consensus matrix: one vote per correlation group, weights from walk-forward
// validation, different units never averaged), /api/v1/montecarlo/status + scenarios (simulation, uncalibrated), /api/v1/ml/status
// (drift), /api/v1/decision (decision trace of the S01–S12 engine), /api/v1/context-tf (multi-timeframe context), /api/v1/telemetry
// and /api/v1/analytics/diagnostics (data flow). Random Forest does not exist in the bot - its card says so.
// The two interactive module maps of the earlier main menu (FlowGraph: data/analyses and models/decisions, impulses only from real
// WebSocket events) are kept here, opened from NEURAL DATA FLOW ("Mapy przepływu modułów").
import { Fragment, lazy, Suspense, useMemo, useState } from "react";
import { href } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { useTerminalContext } from "../shell/useTerminalContext";
import { A } from "./assets";
import CultShell from "./CultShell";
import { MODEL_FAMILIES, familyState, kindOf, num, pct, useEnvKind, useGet } from "./data";
import { Badge, Bar, Icon, Monitor, NA, Stat, StatusBar, Tag } from "./kit";

const FlowGraph = lazy(() => import("../wizard/FlowGraph"));
const REDUCED = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Both module maps; /api/v1/telemetry every 15 s only while they are open. */
function FlowMaps() {
  const tel = useGet<any>("/api/v1/telemetry", 15000);
  const tele = useMemo(() => (tel.d ? { ...tel.d, _received_at: tel.at } : null), [tel.d, tel.at]);
  return (
    <section className="wp-maps" id="wp-maps" data-testid="wp-maps" aria-label="Mapy przepływu modułów">
      <Suspense fallback={<NA>Ładowanie map…</NA>}>
        <div className="wp-map"><FlowGraph kind="data" tele={tele} reduced={REDUCED} /></div>
        <div className="wp-map"><FlowGraph kind="models" tele={tele} reduced={REDUCED} /></div>
      </Suspense>
      {tel.err && <NA>Telemetria modułów niedostępna: {tel.err}</NA>}
    </section>);
}

const MTF = ["M1", "M5", "M15", "M30", "H1", "H4", "H8", "D1"];
const TEX: Record<string, "xgboost" | "forest" | "ml" | "flow"> = { xgb: "xgboost", rf: "forest", nn: "ml", mc: "flow" };

function ModelCard({ fam, cat, mc }: { fam: (typeof MODEL_FAMILIES)[number]; cat: any; mc: any }) {
  const st = familyState(cat, fam.ids);
  const tone = st.ready ? "ok" : fam.ids.length ? "warn" : "muted";
  return (
    <Monitor title={fam.key === "nn" ? "ML ENGINE (DEEP NN)" : fam.key === "xgb" ? "XGBOOST ENGINE" : fam.label.toUpperCase()} icon={fam.key === "rf" ? "dna" : fam.key === "mc" ? "grid" : "bars"}
      className={cls("wp-card", `wp-${fam.key}`)} testid={`wp-card-${fam.key}`}>
      <div className="wp-card-in">
        <img src={A.tex(TEX[fam.key])} alt="" aria-hidden="true" />
        <dl className="cu-kv">
          {fam.key === "mc" ? (
            <>
              <dt>Stan</dt><dd><Badge tone={mc?.last_error ? "bad" : "ok"}>{mc ? (mc.last_error ? "BŁĄD" : "READY") : "…"}</Badge></dd>
              <dt>Simulations</dt><dd>{mc?.runs ?? "—"} przeb.</dd><dt>Wariant</dt><dd>{mc?.variant ?? "—"}</dd>
              <dt>Czas</dt><dd>{mc?.last_ms != null ? `${num(mc.last_ms, 0)} ms` : "—"}</dd>
              <dt>Kalibracja</dt><dd>{mc ? (mc.calibrated ? "tak" : "nieskalibrowany") : "—"}</dd>
            </>) : !fam.ids.length ? (
            <><dt>Stan</dt><dd><Badge tone="muted">BRAK W BOCIE</Badge></dd></>) : (
            <>
              <dt>Stan</dt><dd><Badge tone={tone}>{st.ready ? "READY" : st.state}</Badge></dd>
              <dt>Modele</dt><dd>{st.ready}/{st.total} gotowe</dd>
              {st.items.slice(0, 3).map((it: any) => <Fragment key={it.id}><dt title={it.purpose}>{it.id}</dt><dd>{it.state_pl ?? it.state}</dd></Fragment>)}
            </>)}
        </dl>
      </div>
      {!fam.ids.length && <NA>{fam.none}</NA>}
      {fam.ids.length > 0 && !st.ready && <NA>Model nie jest wytrenowany – wyniki (accuracy, F1, AUC) pojawią się po treningu i walidacji w Centrum treningu.</NA>}
    </Monitor>);
}

export default function WindPortal() {
  const { s } = useStore();
  const ctx = useTerminalContext();
  const env = useEnvKind();                                   // market-derived panels carry the kind of the feed (DEMO on the simulator)
  const inst = ctx.instrument;
  const cat = useGet<any>("/api/v1/models/catalog", 60000);
  const preds = useGet<any>(inst ? `/api/v1/models/predictions?instrument=${inst}` : null, 30000);
  const ev = useGet<any>(inst ? `/api/v1/models/evidence?instrument=${inst}` : null, 30000);
  const mcs = useGet<any>("/api/v1/montecarlo/status", 30000);
  const mc = useGet<any>("/api/v1/montecarlo/scenarios", 60000);
  const ml = useGet<any>("/api/v1/ml/status", 30000);
  const dec = useGet<any>("/api/v1/decision", 10000);
  const mtf = useGet<any>("/api/v1/context-tf", 30000);
  const an = useGet<any>("/api/v1/analytics/diagnostics", 30000);
  const liq = useGet<any>("/api/v1/liquidity/context", 60000);
  const news = useGet<any>("/api/v1/news", 60000);
  const [showRules, setShowRules] = useState(false);
  const [maps, setMaps] = useState(false);
  const ready = (preds.d?.items || []).filter((p: any) => p.state === "READY" && p.result);
  const groups: any[] = ev.d?.groups || [];
  const fams = MODEL_FAMILIES.map((f) => ({ f, st: familyState(cat.d, f.ids) }));
  const trainable = (cat.d?.items || []).filter((x: any) => x.category === "TRAINABLE");
  const readyTrain = trainable.filter((x: any) => x.state === "READY").length;
  const ctxTf = mtf.d?.context || {};
  const dirs = MTF.map((tf) => ({ tf, dir: ctxTf[tf]?.direction ?? (tf === "M1" || tf === "M5" || tf === "M15" ? null : null), st: ctxTf[tf]?.status }));
  const known = dirs.filter((d) => d.dir === "UP" || d.dir === "DOWN");
  const up = known.filter((d) => d.dir === "UP").length;
  const align = known.length ? Math.max(up, known.length - up) / known.length : null;
  const tree: any[] = dec.d?.decision_tree || dec.d?.tree || [];
  const sc = mc.d?.scenarios;
  const drift = ml.d?.drift;
  const agree = groups.length ? `${groups.length} grup` : ready.length ? `${ready.length} model.` : "—";
  return (
    <CultShell page="wind" tower="wind" title="WIND PORTAL – AI ENGINE CORE" sub="MULTI-MODEL NEURAL INTELLIGENCE | MODELE BOTA | REAL-TIME MARKET COGNITION"
      accent="#39ff8f" bg={A.panelBg("wind")} emblem={{ title: "WIND PORTAL", sub: "AI ENGINE" }}>
      <div className="wp-grid">
        <img className="cu-pepe wp-pepe" src={A.panelPepe("wind")} alt="" aria-hidden="true" />
        {fams.map(({ f }) => <ModelCard key={f.key} fam={f} cat={cat.d} mc={mcs.d} />)}
        <div className="wp-core" data-testid="wp-core">
          <div className="wp-core-in">
            <img src={A.coreTree} alt="Drzewo neuronowe AI Consensus Core" />
            <div className="wp-core-c" data-testid="wp-core-value"><small>AI CONSENSUS</small><b>CORE</b><strong>{agree}</strong>
              <em>{groups.length || ready.length ? "gotowe głosy" : "brak gotowych modeli"}</em></div>
          </div>
        </div>
        <Monitor title="NEURAL DATA FLOW" icon="db" className="wp-flow" testid="wp-flow">
          <ol className="wp-pipe">
            <li className={ctx.mt5 === "CONNECTED" ? "ok" : "bad"}><Icon n="db" /><b>MT5 Data</b><small>{s.quote?.age_seconds != null ? `tick ${num(s.quote.age_seconds, 1)} s` : "—"}</small></li>
            <li className={s.engine?.last_error ? "bad" : "ok"}><Icon n="gear" /><b>Feature Engineering</b><small>{s.engine?.cycle_ms != null ? `${num(s.engine.cycle_ms, 0)} ms / cykl` : "—"}</small></li>
            <li className={an.d ? "ok" : "warn"}><Icon n="grid" /><b>5D Processing</b><small title="analityka FFT/EMD/VMD">{an.d?.latency_ms != null ? `${num(typeof an.d.latency_ms === "object" ? an.d.latency_ms.p50 ?? an.d.latency_ms.last : an.d.latency_ms, 0)} ms` : "analityka"}</small></li>
            <li className={readyTrain ? "ok" : "warn"}><Icon n="brain" /><b>AI Models</b><small>{cat.d ? `${readyTrain}/${trainable.length} gotowych` : "…"}</small></li>
            <li className={groups.length ? "ok" : "warn"}><Icon n="target" /><b>Consensus Output</b><small>{groups.length ? `${groups.length} grup` : "brak głosów"}</small></li>
          </ol>
          <button type="button" className="cu-link-btn" aria-expanded={maps} aria-controls="wp-maps" onClick={() => setMaps(!maps)} data-testid="wp-maps-toggle">
            {maps ? "Ukryj mapy przepływu modułów" : "Mapy przepływu modułów (dane · modele) ›"}</button>
        </Monitor>
        <Monitor title="AI CONSENSUS MATRIX" icon="grid" className="wp-matrix" testid="wp-matrix" right={<Tag kind={kindOf(ev, env, true)} title="dowody modeli z bota (z danych bieżącego źródła)" />}>
          {!groups.length && !ready.length ? (
            <NA>Brak gotowych predykcji – {(ev.d?.excluded || []).length} modeli wyłączonych (np. „{ev.d?.excluded?.[0]?.reason ?? "brak środowiska"}”).</NA>) : (
            <table className="cu-tbl"><thead><tr><th>Model</th><th>Signal</th><th>Wartość</th><th>Weight</th><th>Status</th></tr></thead>
              <tbody>{(groups.length ? groups : ready).slice(0, 6).map((g: any, i: number) => (
                <tr key={i}><td>{g.group ?? g.model_name}</td><td>{g.direction ?? g.result?.direction ?? "—"}</td>
                  <td>{g.probability != null ? pct(g.probability * 100) : g.result?.probability != null ? pct(g.result.probability * 100) : "—"}</td>
                  <td>{g.weight != null ? pct(g.weight * 100, 0) : "—"}</td><td>{g.state ?? "READY"}</td></tr>))}</tbody></table>)}
          <button type="button" className="cu-link-btn" onClick={() => setShowRules(!showRules)}>{showRules ? "Ukryj zasady" : "Zasady konsensusu"}</button>
          {showRules && <NA>{ev.d?.rules}</NA>}
        </Monitor>
        <Monitor title="DECISION TRACE (SILNIK S01–S12)" icon="log" className="wp-trace" testid="wp-trace" right={<Tag kind={kindOf(dec, env)} />}>
          {!tree.length ? <NA>Brak śladu decyzji.</NA> : tree.map((n: any) => (
            <Bar key={n.node} label={n.node} value={n.status === "PASS" ? 1 : n.status === "PENDING" ? 0.5 : n.status === "FAIL" ? 0.15 : 0}
              text={n.status} color={n.status === "PASS" ? "var(--cu-green)" : n.status === "FAIL" ? "#ff5f7a" : "#ffcc4d"} title={n.reason ?? n.detail ?? ""} />))}
          <p className="cu-dim">Decyzja: <b>{dec.d?.decision ?? "—"}</b> · etap {dec.d?.signal_stage ?? "—"}</p>
        </Monitor>
        <Monitor title="SCENARIO SIMULATION (MONTE CARLO)" icon="chart" className="wp-mc" testid="wp-mc" right={<Badge tone="muted">nieskalibrowane</Badge>}>
          {!sc ? <NA>{mc.err ? `Błąd: ${mc.err}` : "Brak symulacji."}</NA> : (
            <>
              <div className="wp-mc-bars">{(sc.levels_price || []).map((lv: number, i: number) => (
                <div key={lv} className="wp-mc-col" title={`ruch ${lv} w ${sc.horizon_bars} świecach`}>
                  <i className="up" style={{ height: `${(sc.p_up_reach?.[i] ?? 0) * 100}%` }} /><i className="dn" style={{ height: `${(sc.p_down_reach?.[i] ?? 0) * 100}%` }} /><small>{lv}</small></div>))}</div>
              <ul className="wp-mc-l">
                <li className="buy">P(+{sc.levels_price?.[0]}): {pct((sc.p_up_reach?.[0] ?? 0) * 100)}</li>
                <li className="sell">P(−{sc.levels_price?.[0]}): {pct((sc.p_down_reach?.[0] ?? 0) * 100)}</li>
              </ul>
              <NA>{mc.d?.n_paths} ścieżek, {sc.horizon_bars} świec {mc.d?.tf}; {sc.note}</NA>
            </>)}
        </Monitor>
        <Monitor title="MODEL ANOMALY DETECTOR" icon="alert" className="wp-anom" testid="wp-anomaly">
          <ul className="cu-checks">
            <li className={drift?.status === "OK" || drift?.status === "STABLE" ? "ok" : "warn"}><Icon n="check" size={14} />Model Drift<em>{drift?.status ?? "—"}{drift?.reason ? ` (${drift.reason})` : ""}</em></li>
            <li className={(ev.d?.excluded || []).length ? "warn" : "ok"}><Icon n="check" size={14} />Prediction Anomaly<em>{(ev.d?.excluded || []).length} wyłączonych</em></li>
            <li className={s.decision?.data_quality === "GOOD" ? "ok" : "warn"}><Icon n="check" size={14} />Data Quality<em>{s.decision?.data_quality ?? "—"}</em></li>
            <li className={ctx.mt5 === "CONNECTED" ? "ok" : "bad"}><Icon n="check" size={14} />Sync Status<em>{ctx.mt5State ?? "—"}</em></li>
          </ul>
        </Monitor>
        <Monitor title="MULTI-TIMEFRAME AI CONTEXT" icon="chart" className="wp-mtf" testid="wp-mtf" right={<Tag kind={kindOf(mtf, env)} />}>
          <div className="wp-mtf-row">{dirs.map((d) => (
            <span key={d.tf} className={cls(d.dir === "UP" && "up", d.dir === "DOWN" && "dn")} title={d.st ?? "brak danych"}><b>{d.tf}</b><i>{d.dir === "UP" ? "↑" : d.dir === "DOWN" ? "↓" : "–"}</i></span>))}</div>
          <Bar label="Trend Alignment" value={align} text={align != null ? pct(align * 100, 0) : "—"} title={`${known.length} interwałów z kierunkiem`} />
        </Monitor>
        <Monitor title="MARKET COGNITION" icon="target" className="wp-cog" testid="wp-cognition">
          <ul className="cu-checks">
            <li className={liq.d ? "ok" : "warn"}><Icon n="check" size={14} /><a href={href("indykatory")}>Liquidity Heatmap</a><em>{liq.d?.status ?? (liq.err ? "błąd" : "…")}</em></li>
            <li className="ok"><Icon n="check" size={14} /><a href={href("struktura")}>Smart Money Flow (SMC)</a><em>{s.decision?.market_state ?? "—"}</em></li>
            <li className={news.d?.status === "OK" ? "ok" : "warn"}><Icon n="check" size={14} />News Impact<em>{news.d?.status ?? "—"}</em></li>
            <li className="ok"><Icon n="check" size={14} />Volatility Regime<em>{ctxTf.M30?.regime ?? ctxTf.H1?.regime ?? "—"}</em></li>
          </ul>
        </Monitor>
      </div>
      {maps && <FlowMaps />}
      <StatusBar testid="wp-bar">
        <Stat icon="brain" label="AI ENGINE STATUS" value={ctx.backend === "OPEN" ? "ONLINE" : "OFFLINE"} tone={ctx.backend === "OPEN" ? "ok" : "bad"} />
        <Stat icon="db" label="ACTIVE MODELS" value={cat.d ? `${readyTrain}/${trainable.length}` : "—"} sub="trenowalne gotowe" />
        <Stat icon="grid" label="MODUŁY KATALOGU" value={cat.d ? String(cat.d.items?.length ?? 0) : "—"} sub={cat.d ? `${cat.d.counts_by_state?.READY ?? 0} READY` : ""} />
        <Stat icon="clock" label="PROCESSING" value={s.engine?.cycle_ms != null ? `${num(s.engine.cycle_ms, 0)} ms` : "—"} sub="cykl silnika" />
        <Stat icon="target" label="MODEL AGREEMENT" value={agree} sub="grupy niezależnych głosów" />
        <Stat icon="chart" label="PREDICTION EDGE" value="—" sub="brak walidacji na danych rzeczywistych" tone="muted" />
        <Stat icon="gear" label="LEARNING MODE" value={ml.d?.mode ?? "—"} sub={ml.d?.status ?? ""} />
      </StatusBar>
    </CultShell>);
}
