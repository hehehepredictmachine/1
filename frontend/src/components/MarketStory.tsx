// PMW-UPD-09 panel: Market Story + Swing Inspector (selection by swing ID with as-of adjacency), regime bands with a separate
// volatility axis, SMMA(3) channel and Z-score oscillator, SpikingBrain / MiniRocket diagnostics and native MQL5 status.
// Everything is read from the server; display toggles never change the analysis or the model.
import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api";
import { fmtNum, fmtTime } from "../util";

const TFS = ["M1", "M5", "M15", "H1"];
const REG_COLOR: Record<string, string> = { TREND_UP: "#2e9d5b", TREND_DOWN: "#c0453b", RANGE: "#c9a227", TRANSITION: "#7b7f8a", WARMING_UP: "#3b3f48" };
const VOL_COLOR: Record<string, string> = { LOW: "#4a78c2", NORMAL: "#6b7280", HIGH: "#d9822b", WARMING_UP: "#3b3f48" };

function usePoll<T>(url: string | null, ms = 15000): [T | null, string | null, () => void] {
  const [d, setD] = useState<T | null>(null);
  const [e, setE] = useState<string | null>(null);
  const load = () => { if (url) apiGet(url).then((x) => { setD(x); setE(null); }).catch((x) => setE(String(x?.message || x))); };
  useEffect(() => { load(); if (!url) return; const t = setInterval(load, ms); return () => clearInterval(t); }, [url]);
  return [d, e, load];
}

function TfPicker({ tf, setTf }: { tf: string; setTf: (x: string) => void }) {
  return <span className="seg">{TFS.map((x) => <button key={x} className={"btn small" + (x === tf ? "" : " ghost")} onClick={() => setTf(x)}>{x}</button>)}</span>;
}

function Strip({ items, color, testid }: { items: { state: string | null; t: any }[]; color: Record<string, string>; testid: string }) {
  const n = Math.max(1, items.length);
  return <svg data-testid={testid} viewBox={`0 0 ${n} 10`} preserveAspectRatio="none" style={{ width: "100%", height: 14, display: "block" }}>
    {items.map((b, i) => <rect key={i} x={i} y={0} width={1.02} height={10} fill={color[b.state || "WARMING_UP"] || "#555"}><title>{`${String(b.t)} · ${b.state ?? "—"}`}</title></rect>)}
  </svg>;
}

export function RegimeCard({ asset }: { asset: string }) {
  const [tf, setTf] = useState("M1");
  const [d, err] = usePoll<any>(`/api/v1/structure-intelligence/regimes?asset=${asset}&tf=${tf}&limit=240`);
  const cur = d?.current;
  return (
    <div className="card wide" data-testid="regime-card">
      <h3>Mapa reżimu MQ_REGIME_MULTI_V2 <TfPicker tf={tf} setTf={setTf} /></h3>
      {err ? <p className="small muted">{err}</p> : !cur ? <p className="small muted">Ładowanie…</p> : <>
        <p className="small">Stan <b data-testid="regime-state">{cur.state}</b> · kandydat {cur.candidate ?? "—"} · histereza {cur.hysteresis?.candidate_count}/{cur.hysteresis?.needed} (wejście), {cur.hysteresis?.fail_count}/{cur.hysteresis?.needed} (wyjście)
          · siła dowodów {cur.strength ?? "null"} <span className="muted">(nie prawdopodobieństwo; {cur.strength_formula})</span> · zmienność <b>{cur.volatility?.state ?? "—"}</b> (pctl {cur.volatility?.percentile ?? "—"})</p>
        <div className="small muted">Kierunek / struktura</div>
        <Strip testid="regime-bands" items={(d.bands || []).map((b: any) => ({ state: b.state, t: b.t }))} color={REG_COLOR} />
        <div className="small muted">Zmienność (oddzielna oś)</div>
        <Strip testid="vol-bands" items={(d.bands || []).map((b: any) => ({ state: b.volatility, t: b.t }))} color={VOL_COLOR} />
        {cur.components?.status === "OK" && <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>n</th><th>ER</th><th>d_n</th></tr></thead>
          <tbody>{[8, 20, 50].map((n, i) => <tr key={n}><td>{n}</td><td>{fmtNum(cur.components.er[i], 3)}</td><td>{fmtNum(cur.components.d_n[i], 3)}</td></tr>)}</tbody></table></div>}
        <p className="small muted">Zgodność horyzontów {cur.components?.agreement ?? "—"} · struktura {cur.components?.structure ?? "—"} · odrzucenia: {(cur.rejections || []).join(", ") || "—"}
          · profil {d.profiles_source} · {d.resumed_from_checkpoint ? "wznowiono z checkpointu" : "replay okna"} · źródło parytetu {cur.source_parity}</p></>}
    </div>);
}

export function MarketStoryCard({ asset }: { asset: string }) {
  const [tf, setTf] = useState("M1");
  const [showLabels, setShowLabels] = useState(true);
  const [showLines, setShowLines] = useState(true);
  const [sel, setSel] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string>("");
  const [insp, setInsp] = useState<any>(null);
  const [d, err] = usePoll<any>(`/api/v1/structure-intelligence/swings?asset=${asset}&tf=${tf}&limit=60`);
  useEffect(() => {
    if (!sel) { setInsp(null); return; }
    let alive = true;
    const q = asOf ? `&as_of=${encodeURIComponent(String(Date.parse(asOf) / 1000))}` : "";
    apiGet(`/api/v1/structure-intelligence/swings/${sel}?asset=${asset}${q}`).then((x) => { if (alive) setInsp(x); })
      .catch((e) => { if (alive) setInsp({ error: String(e?.message || e) }); });
    return () => { alive = false; };
  }, [sel, asOf, asset, d?.swings?.length]);
  const sw = (d?.swings || []) as any[];
  const st = d?.story;
  const geo = useMemo(() => {
    if (!sw.length) return null;
    const ps = sw.map((s) => s.price);
    const lo = Math.min(...ps), hi = Math.max(...ps);
    const i0 = sw[0].origin_index, i1 = sw[sw.length - 1].origin_index;
    return { x: (i: number) => 10 + 580 * (i - i0) / Math.max(1, i1 - i0), y: (p: number) => 110 - 100 * (p - lo) / Math.max(1e-9, hi - lo) };
  }, [sw]);
  return (
    <div className="card wide" data-testid="market-story">
      <h3>Market Story i Swing Inspector <TfPicker tf={tf} setTf={(x) => { setTf(x); setSel(null); }} /></h3>
      {err ? <p className="small muted">{err}</p> : !st ? <p className="small muted">Ładowanie…</p> : <>
        <p className="small" data-testid="story-text">TF {st.tf}: bias <b>{st.bias}</b>
          {st.last_final_leg ? ` · ostatnia FINAL noga ${st.last_final_leg.direction} ${fmtNum(st.last_final_leg.move, 2)} (${st.last_final_leg.bar_count} świec, rola ${st.last_final_leg.role}${st.last_final_leg.retracement_pct != null ? `, retracement ${fmtNum(st.last_final_leg.retracement_pct, 1)}%` : ""})` : " · brak sfinalizowanej nogi"}
          {st.provisional_tail ? ` · PROVISIONAL ogon ${st.provisional_tail.direction} ${fmtNum(st.provisional_tail.move, 2)}` : ""}
          {st.change_condition ? ` · ${st.change_condition}` : ""}</p>
        <p className="small"><label><input type="checkbox" checked={showLines} onChange={(e) => setShowLines(e.target.checked)} /> linie</label>{" "}
          <label><input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} /> etykiety</label>{" "}
          <label>as-of <input type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label> <span className="muted">(puste = retrospektywa)</span></p>
        {geo && <svg data-testid="swing-svg" viewBox="0 0 600 125" style={{ width: "100%", maxHeight: 180 }}>
          {showLines && <polyline fill="none" stroke="#c9a227" strokeWidth={1} points={sw.filter((s) => s.status !== "REPLACED").map((s) => `${geo.x(s.origin_index)},${geo.y(s.price)}`).join(" ")} />}
          {sw.map((s) => <g key={s.id} data-swing-id={s.id} style={{ cursor: "pointer" }} onClick={() => setSel(s.id)}>
            <circle cx={geo.x(s.origin_index)} cy={geo.y(s.price)} r={s.id === sel ? 5 : 3} fill={s.status === "TAIL" ? "#999" : s.kind === "H" ? "#2e9d5b" : "#c0453b"} />
            {showLabels && <text x={geo.x(s.origin_index)} y={geo.y(s.price) + (s.kind === "H" ? -6 : 12)} fontSize={8} textAnchor="middle" fill="currentColor">{s.label}</text>}
          </g>)}
        </svg>}
        <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Swing</th><th>Etykieta</th><th>Cena</th><th>origin</th><th>known</th><th>sealed</th><th>status</th></tr></thead>
          <tbody>{sw.slice(-12).reverse().map((s) => <tr key={s.id} className={s.id === sel ? "sel" : ""} data-swing-row={s.id} onClick={() => setSel(s.id)} style={{ cursor: "pointer" }}>
            <td className="mono">{s.id.slice(-8)}</td><td>{s.label}</td><td>{fmtNum(s.price, 2)}</td><td>{String(s.origin_time).slice(0, 19)}</td>
            <td>{fmtTime(new Date(s.known_at * 1000).toISOString(), true)}</td><td>{s.sealed_at ? fmtTime(new Date(s.sealed_at * 1000).toISOString(), true) : "—"}</td><td>{s.status}</td></tr>)}</tbody></table></div>
        {sel && <div className="card inset" data-testid="swing-inspector">
          {insp?.error ? <p className="small bad">Swing {sel}: {insp.error}</p> : !insp ? <p className="small muted">…</p> : insp.status === "NOT_KNOWN_AT_AS_OF" || insp.id === undefined ? <p className="small">Swing nie był znany w wybranym as-of.</p> : <>
            <p className="small"><b>{insp.label}</b> {insp.kind} @ {fmtNum(insp.price, 2)} · id <span className="mono">{insp.id}</span> · warstwa {insp.layer} · tolerancja {fmtNum(insp.tolerance, 4)} · {insp.label_reason}</p>
            <p className="small">origin {String(insp.origin_time)} · known {fmtTime(new Date(insp.known_at * 1000).toISOString(), true)} · sealed {insp.sealed_at ? fmtTime(new Date(insp.sealed_at * 1000).toISOString(), true) : "jeszcze nie (TAIL)"}
              · poprzedni <span className="mono">{insp.previous_id?.slice(-8) ?? "null"}</span> · następny <span className="mono">{insp.next_id?.slice(-8) ?? "null (nieznany w as-of)"}</span></p>
            {(insp.legs || []).map((lg: any) => <p key={lg.id} className="small">Noga {lg.direction} {fmtNum(lg.move, 2)} · {fmtNum(lg.points, 0)} pkt · {fmtNum(lg.ticks, 0)} ticków · pips {lg.pips == null ? `null (${lg.pip_status})` : fmtNum(lg.pips, 1)}
              · {lg.bar_count} świec / {Math.round(lg.wall_duration_seconds / 60)} min · rola {lg.role} (wstępnie {lg.role_initial}, bias {lg.role_initial_basis}){lg.retracement_pct != null ? ` · retracement ${fmtNum(lg.retracement_pct, 1)}%` : ""}{(lg.flags || []).length ? ` · ${lg.flags.join(",")}` : ""}</p>)}</>}
        </div>}</>}
    </div>);
}

function Lines({ series, keys, colors, zero, bands, testid, events }: { series: any[]; keys: string[]; colors: string[]; zero?: boolean; bands?: number[]; testid: string; events?: any[] }) {
  const vals = series.flatMap((r) => keys.map((k) => r[k]).filter((v) => typeof v === "number"));
  if (!vals.length) return <p className="small muted">Brak wartości (WARMUP / LOW_DISPERSION).</p>;
  const all = vals.concat(bands || []).concat(zero ? [0] : []);
  const lo = Math.min(...all), hi = Math.max(...all);
  const x = (i: number) => 600 * i / Math.max(1, series.length - 1);
  const y = (v: number) => 95 - 90 * (v - lo) / Math.max(1e-9, hi - lo);
  return <svg data-testid={testid} viewBox="0 0 600 100" preserveAspectRatio="none" style={{ width: "100%", height: 110 }}>
    {(bands || []).map((b) => <line key={b} x1={0} x2={600} y1={y(b)} y2={y(b)} stroke="#888" strokeDasharray="3 3" strokeWidth={0.5} />)}
    {zero && <line x1={0} x2={600} y1={y(0)} y2={y(0)} stroke="#888" strokeWidth={0.6} />}
    {keys.map((k, j) => <polyline key={k} fill="none" stroke={colors[j]} strokeWidth={1} points={series.map((r, i) => typeof r[k] === "number" ? `${x(i)},${y(r[k])}` : "").filter(Boolean).join(" ")} />)}
    {(events || []).map((e) => { const i = series.findIndex((r) => r.t === e.t); return i < 0 ? null : <circle key={e.event_id} data-event-id={e.event_id} cx={x(i)} cy={y(series[i].close ?? series[i].z ?? 0)} r={3} fill={e.event === "UP" || e.kind === "LONG_CANDIDATE" ? "#2e9d5b" : "#c0453b"}><title>{`${e.event ?? e.hypothesis + " " + e.kind} · ${e.t}`}</title></circle>; })}
  </svg>;
}

export function SmmaZCard({ asset }: { asset: string }) {
  const [tf, setTf] = useState("M1");
  const [mode, setMode] = useState("INCLUSIVE_N");
  const [sm, e1] = usePoll<any>(`/api/v1/structure-intelligence/smma?asset=${asset}&tf=${tf}&limit=150`);
  const [z, e2] = usePoll<any>(`/api/v1/structure-intelligence/zscore?asset=${asset}&tf=${tf}&mode=${mode}`);
  const ser = (sm?.series || []).filter((r: any) => r.status === "OK");
  const last = ser[ser.length - 1];
  return (
    <div className="card wide" data-testid="smma-z-card">
      <h3>Kanał SMMA(3) High/Low i Z-Score <TfPicker tf={tf} setTf={setTf} /></h3>
      {e1 ? <p className="small muted">{e1}</p> : <>
        <p className="small">Profil {sm?.profile?.boundary} · lag {sm?.profile?.analytical_lag} · deadband {sm?.profile?.deadband} · stan <b data-testid="smma-location">{last?.location ?? "—"}</b> · zdarzenie {last?.event ?? "—"}
          <span className="muted"> – UP/DOWN to przejście zamknięcia przez kanał (marker = czas potwierdzenia), ABOVE/BELOW to stan; nie wejście</span></p>
        <Lines testid="smma-svg" series={ser.slice(-120)} keys={["U", "L", "close"]} colors={["#2e9d5b", "#c0453b", "#c9a227"]} events={(sm?.events || []).filter((e: any) => ser.slice(-120).some((r: any) => r.t === e.t))} /></>}
      <p className="small">Okno Z: <select value={mode} onChange={(e) => setMode(e.target.value)}><option value="INCLUSIVE_N">INCLUSIVE_N (C t-n+1..t)</option><option value="PREVIOUS_N">PREVIOUS_N (C t-n..t-1)</option></select>
        {" "}z = <b data-testid="z-value">{z?.current?.z == null ? `null (${z?.current?.status ?? "—"})` : fmtNum(z.current.z, 2)}</b>
        {z?.current?.bound ? <span className="muted"> · |z|≤√(n−1)={fmtNum(z.current.bound, 2)} w tym profilu</span> : null}
        <span className="muted"> · Z to odległość od wskazanego okna, nie p-value ani pewność odwrócenia</span></p>
      {e2 ? <p className="small muted">{e2}</p> : <Lines testid="z-svg" series={(z?.series || []).slice(-120)} keys={["z"]} colors={["#c9a227"]} zero bands={[-2, 2]} events={(z?.events || []).filter((e: any) => (z?.series || []).slice(-120).some((r: any) => r.t === e.t))} />}
      <p className="small muted">Hipotezy H_MR/H_BO/H_TP: osobne strumienie zdarzeń i polityki; progi to start kalibracji na dev ({z?.hypotheses?.version}). Żadna hipoteza nie włącza handlu.</p>
    </div>);
}

export function ModelLabCard({ asset, onStart }: { asset: string; onStart: (kind: string, extra: any) => void }) {
  const [diag] = usePoll<any>(`/api/v1/structure-intelligence/model-diagnostics?asset=${asset}`, 30000);
  const [nat] = usePoll<any>(`/api/v1/structure-intelligence/native-status?asset=${asset}`, 30000);
  const [attention, setAttention] = useState("HYBRID");
  const [encoder, setEncoder] = useState("BAR_EVENT_V1");
  const sb = (diag?.diagnostics || {}).MQ_SPIKE_BRAIN_FINANCE_V1 as any[] | undefined;
  const mr = (diag?.diagnostics || {}).MQ_MINIROCKET_RIDGE_V2 as any[] | undefined;
  const tel = sb?.[sb.length - 1]?.telemetry || {};
  return (
    <div className="card wide" data-testid="model-lab-card">
      <h3>SpikingBrain Finance i MiniRocket V2 (PMW-UPD-09)</h3>
      <p><select value={encoder} onChange={(e) => setEncoder(e.target.value)}><option>BAR_EVENT_V1</option><option>QUOTE_EVENT_V1</option></select>{" "}
        <select value={attention} onChange={(e) => setAttention(e.target.value)}><option>HYBRID</option><option>LINEAR</option><option>SLIDING</option></select>{" "}
        <button className="btn" onClick={() => onStart("train", { profile: "quick", families: ["MQ_SPIKE_BRAIN_FINANCE_V1"], encoder, attention })}>SpikingBrain quick</button>{" "}
        <button className="btn" onClick={() => onStart("train", { profile: "standard", families: ["MQ_SPIKE_BRAIN_FINANCE_V1"], encoder, attention })}>SpikingBrain standard</button>{" "}
        <button className="btn" onClick={() => onStart("train", { profile: "standard", families: ["MQ_MINIROCKET_RIDGE_V2"], transform: "MQ_MINIROCKET_UNIVARIATE_V2" })}>MiniRocket V2 standard</button>{" "}
        <button className="btn" onClick={() => onStart("calibrate_market", {})}>Kalibracja reżim/SMMA/Z/struktura (dev)</button></p>
      <div className="tbl-wrap" data-testid="spike-diag"><table className="tbl small"><thead><tr><th>Run</th><th>Enkoder / uwaga</th><th>Spike rate (blok 0/1)</th><th>Udział ekspertów</th><th>Entropia routera</th><th>Overflow</th><th>energy_j</th></tr></thead>
        <tbody>{sb?.length ? <tr><td className="mono">{diag?.run_id}</td><td>{sb[sb.length - 1].encoder} / {sb[sb.length - 1].attention}</td>
          <td>{fmtNum(tel.spike_rate_block0, 3)} / {fmtNum(tel.spike_rate_block1, 3)}</td><td>{(tel.experts_block0?.share || []).map((x: number) => fmtNum(x, 2)).join(" · ")}</td>
          <td>{fmtNum(tel.experts_block0?.router_entropy, 3)}</td><td>{fmtNum(tel.experts_block0?.overflow_ratio, 3)}</td><td>null (NOT_MEASURED)</td></tr>
          : <tr><td colSpan={7} className="muted">Brak runu SpikingBrain w ostatnim raporcie.</td></tr>}</tbody></table></div>
      <p className="small">MiniRocket V2: {mr?.length ? `F=${mr[mr.length - 1].transform?.layout?.F} · dylatacje ${(mr[mr.length - 1].transform?.layout?.dilations || []).length} · fit ${mr[mr.length - 1].transform?.fit?.source} · λ ${JSON.stringify(mr[mr.length - 1].lambda)}` : "brak runu"}</p>
      <p className="small" data-testid="native-status">Native MQL5: eksport {nat?.export?.status ?? "—"} · kompilacja {nat?.compile?.NATIVE_COMPILED ?? "—"} · wykonanie {nat?.compile?.NATIVE_EXECUTED ?? "—"}
        · feed {nat?.feed?.status ?? "—"}{nat?.feed?.reason ? ` (${nat.feed.reason})` : ""}<br /><span className="muted">{nat?.parity_scope} · {nat?.role}</span></p>
      <p className="small muted">Rzadkie impulsy na NumPy nie dowodzą mniejszej latencji ani energii; PPV nie jest prawdopodobieństwem transakcji; bit-exact tylko w sprawdzonym zakresie fixture.</p>
    </div>);
}

export function MarketSummaryCells({ m }: { m: any }) {
  if (!m || m.status !== "OK") return <><td className="muted">{m?.status ?? "—"}</td><td /><td /><td /></>;
  const z = m.zscore?.inclusive?.z;
  return <>
    <td title={`siła ${m.regime?.strength ?? "null"} (nie prawdopodobieństwo)`}><span style={{ color: REG_COLOR[m.regime?.state] }}>{m.regime?.state}</span> / {m.regime?.volatility ?? "—"}</td>
    <td>{m.behavior?.bias ?? "—"}</td>
    <td>{m.smma?.location ?? "—"}{m.smma?.event && m.smma.event !== "NONE" ? ` · ${m.smma.event}` : ""}</td>
    <td>{z == null ? "null" : fmtNum(z, 2)} / {m.zscore?.previous?.z == null ? "null" : fmtNum(m.zscore.previous.z, 2)}</td></>;
}

