// PMW-UPD-11 flow context panel: raw candles next to the SYNTHETIC Heikin Flow series, ranked S/R bands (current map vs history as known),
// StopDistance in points with an ADVISORY SL-price proposal, Markov 3-state / difference-bucket readings and native MQL5 status.
// All values come from the server; display toggles never change the analysis.
import { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api";
import { fmtNum } from "../util";

const TFS = ["M1", "M5", "M15", "H1"];

function usePoll<T>(url: string | null, ms = 20000): [T | null, string | null] {
  const [d, setD] = useState<T | null>(null);
  const [e, setE] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    const load = () => apiGet(url).then((x) => { if (alive) { setD(x); setE(null); } }).catch((x) => { if (alive) setE(String(x?.message || x)); });
    load();
    const t = setInterval(load, ms);
    return () => { alive = false; clearInterval(t); };
  }, [url]);
  return [d, e];
}

function Candles({ raw, ha, bands, showHa, showRaw }: { raw: any[]; ha: any[]; bands: any[]; showHa: boolean; showRaw: boolean }) {
  const n = raw.length;
  const vals = raw.flatMap((b) => [b.h, b.l]).concat(ha.flatMap((b) => [b.h, b.l]));
  if (!n || !vals.length) return null;
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const x = (i: number) => 4 + 592 * i / Math.max(1, n - 1);
  const y = (p: number) => 156 - 150 * (p - lo) / Math.max(1e-9, hi - lo);
  const w = Math.max(1, 400 / n);
  return <svg data-testid="flow-candles" viewBox="0 0 600 160" style={{ width: "100%", height: 220 }}>
    {bands.map((b) => <rect key={b.id} data-channel-id={b.id} x={0} width={600} y={y(b.hi)} height={Math.max(1, y(b.lo) - y(b.hi))}
      fill={b.role === "SUPPORT" ? "rgba(46,157,91,.15)" : b.role === "RESISTANCE" ? "rgba(192,69,59,.15)" : "rgba(201,162,39,.18)"}>
      <title>{`rank ${b.rank} · score ${b.score} (20×${b.score_components.pivots} + ${b.score_components.touch_bars}) · ${fmtNum(b.lo, 2)}–${fmtNum(b.hi, 2)} · ${b.status}`}</title></rect>)}
    {showRaw && raw.map((b, i) => <g key={"r" + i}><line x1={x(i)} x2={x(i)} y1={y(b.h)} y2={y(b.l)} stroke="#888" strokeWidth={0.6} />
      <rect x={x(i) - w / 2} width={w} y={y(Math.max(b.o, b.c))} height={Math.max(0.5, Math.abs(y(b.o) - y(b.c)))} fill={b.c >= b.o ? "#9ad1ad" : "#e3a39c"} /></g>)}
    {showHa && ha.map((b, i) => <rect key={"h" + i} x={x(i) - w / 4} width={w / 2} y={y(Math.max(b.o, b.c))} height={Math.max(0.5, Math.abs(y(b.o) - y(b.c)))}
      fill={b.color === "BULL" ? "#2e9d5b" : b.color === "BEAR" ? "#c0453b" : "#7b7f8a"} opacity={b.quality === "OK" ? 0.9 : 0.4} />)}
  </svg>;
}

export function FlowContextCard({ asset, onStart }: { asset: string; onStart: (kind: string, extra: any) => void }) {
  const [tf, setTf] = useState("M15");
  const [mode, setMode] = useState("CURRENT_MAP_FULL_WIDTH");
  const [showHa, setShowHa] = useState(true);
  const [showRaw, setShowRaw] = useState(true);
  const [entry, setEntry] = useState("");
  const [side, setSide] = useState("BUY");
  const [ser, e1] = usePoll<any>(`/api/v1/flow-context/series?asset=${asset}&tf=${tf}&limit=160`);
  const [ch] = usePoll<any>(`/api/v1/flow-context/channels?asset=${asset}&tf=${tf}&mode=${mode}`);
  const [mk] = usePoll<any>(`/api/v1/flow-context/markov?asset=${asset}`, 30000);
  const [nat] = usePoll<any>(`/api/v1/flow-context/native?asset=${asset}`, 30000);
  const [sd] = usePoll<any>(entry ? `/api/v1/flow-context/stopdistance?asset=${asset}&tf=${tf}&entry=${encodeURIComponent(entry)}&side=${side}` :
    `/api/v1/flow-context/stopdistance?asset=${asset}&tf=${tf}`);
  const bands = useMemo(() => mode === "CURRENT_MAP_FULL_WIDTH" ? ((ch?.snapshot?.channels || []).filter((c: any) => c.visible)) : [], [ch, mode]);
  const last = (ser?.heikin || [])[ser?.heikin?.length - 1];
  const m3 = mk?.markov3;
  const bk = mk?.buckets;
  return (
    <div className="card wide" data-testid="flow-context-card">
      <h3>Flow context – Heikin Flow, kanały S/R, StopDistance, Markov (PMW-UPD-11){" "}
        <span className="seg">{TFS.map((x) => <button key={x} className={"btn small" + (x === tf ? "" : " ghost")} onClick={() => setTf(x)}>{x}</button>)}</span></h3>
      <p><button className="btn" onClick={() => onStart("flow_calibrate", {})}>Kalibracja profili (dev)</button>{" "}
        <button className="btn" onClick={() => onStart("flow_markov", {})}>Dopasuj Markov3 + koszyki</button>{" "}
        <button className="btn" onClick={() => onStart("flow_dataset", {})}>Dataset FLOW_CONTEXT</button>{" "}
        <button className="btn" onClick={() => onStart("flow_train", { profile: "quick", families: ["LOGREG", "XGB"] })}>Trening quick</button>{" "}
        <button className="btn" onClick={() => onStart("flow_train", { profile: "standard", families: ["LOGREG", "XGB"] })}>Trening standard</button></p>
      {e1 ? <p className="small muted">{e1}</p> : <>
        <p className="small"><label><input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} /> świece rzeczywiste</label>{" "}
          <label><input type="checkbox" checked={showHa} onChange={(e) => setShowHa(e.target.checked)} /> Heikin Flow (syntetyczne)</label>{" "}
          <select value={mode} onChange={(e) => setMode(e.target.value)}><option value="CURRENT_MAP_FULL_WIDTH">bieżąca mapa S/R</option><option value="HISTORY_AS_KNOWN">historia znana w czasie</option></select>
          {" "}<span className="muted">{ch?.label ?? ""}</span></p>
        <Candles raw={ser?.raw || []} ha={ser?.heikin || []} bands={bands} showHa={showHa} showRaw={showRaw} />
        <p className="small" data-testid="flow-heikin">Heikin Flow {ser?.config?.ma1}{ser?.config?.p1}/{ser?.config?.ma2}{ser?.config?.p2}: kolor <b>{last?.color ?? "—"}</b> · jakość {last?.quality ?? "—"}
          <span className="muted"> – ceny syntetyczne, opóźnione; nie ceny wykonania ani cel treningu (parytet z oryginałem: {ser?.source_parity})</span></p>
        {mode === "HISTORY_AS_KNOWN" && <p className="small muted">Zapisane migawki: {(ch?.snapshots || []).length}; zdarzenia: {(ch?.events || []).slice(-5).map((e: any) => `${e.kind} ${String(e.id).slice(-6)}`).join(", ")}</p>}
        <div className="tbl-wrap" data-testid="flow-channels"><table className="tbl small"><thead><tr><th>#</th><th>Pasmo</th><th>Rola</th><th>Score (20×piv + dotknięcia)</th><th>Status</th></tr></thead>
          <tbody>{(ch?.snapshot?.channels || []).map((c: any) => <tr key={c.id} data-channel-row={c.id}><td>{c.rank}</td><td>{fmtNum(c.lo, 2)}–{fmtNum(c.hi, 2)}</td><td>{c.role}</td>
            <td>{c.score} (20×{c.score_components.pivots} + {c.score_components.touch_bars})</td><td>{c.status}</td></tr>)}
            {!(ch?.snapshot?.channels || []).length && <tr><td colSpan={5} className="muted">Brak pasm (za mało historii/pivotów).</td></tr>}</tbody></table></div>
        <p className="small muted">Score to geometria pasma, nie prawdopodobieństwo odbicia; pełna mapa w tle nie dowodzi, że pasmo istniało wcześniej.</p></>}
      <div data-testid="flow-stopdistance"><p className="small"><b>StopDistance</b> ({tf}): zakres {fmtNum(sd?.row?.range_points, 1)} pkt · średnia {fmtNum(sd?.row?.average_points, 1)} pkt ·
        sugerowany {fmtNum(sd?.row?.suggested_points, 1)} pkt = {fmtNum(sd?.row?.suggested_price_distance, 3)} ceny (point {sd?.row?.point}) · status {sd?.row?.status ?? sd?.status ?? "—"}</p>
        <p className="small">Wejście <input value={entry} onChange={(e) => setEntry(e.target.value)} placeholder="cena" style={{ width: 90 }} />{" "}
          <select value={side} onChange={(e) => setSide(e.target.value)}><option>BUY</option><option>SELL</option></select>
          {sd?.sl_price_proposal != null && <> → propozycja SL <b>{fmtNum(sd.sl_price_proposal, 2)}</b> <span className="muted">({sd.note})</span></>}
          <span className="muted"> · punkty ≠ pips ≠ tick ≠ cena SL; czynnik nie jest prawdopodobieństwem bezpiecznego stopu</span></p></div>
      <div data-testid="flow-markov">{mk?.status === "MODEL_MISSING" ? <p className="small muted">Markov: MODEL_MISSING – „Dopasuj Markov3 + koszyki” (tylko część dev).</p> : <>
        <p className="small"><b>Markov 3-stanowy</b>: stan {m3?.state ?? "—"} · następny DOWN/FLAT/UP {m3?.next ? `${fmtNum(m3.next.DOWN, 2)} / ${fmtNum(m3.next.FLAT, 2)} / ${fmtNum(m3.next.UP, 2)}` : "—"}
          · wsparcie wierszy {(m3?.support || []).join("/")} · stacjonarny {m3?.stationary?.status ?? "—"}
          <span className="muted"> – rozkład stanu jednej zmiany, nie skumulowany zwrot ani p(TP)</span></p>
        <p className="small"><b>Koszyki różnic</b> (K={bk?.K_effective ?? "—"}): {bk?.projection ? Object.entries(bk.projection).map(([h, p]: [string, any]) =>
          `h${h}: śr. ${fmtNum(p.price_mean, 2)}${p.price_q ? ` [${fmtNum(p.price_q[0], 2)}–${fmtNum(p.price_q[2], 2)}]` : ""}`).join(" · ") : (bk?.eligibility?.reason ?? "—")}
          <span className="muted"> – przedziały punktu końcowego, nie high/low ani bezpieczny SL</span></p></>}</div>
      <p className="small" data-testid="flow-native">Native MQL5: kompilacja {nat?.compile?.NATIVE_COMPILED ?? "—"} · wykonanie {nat?.compile?.NATIVE_EXECUTED ?? "—"} · eksport kolektora {nat?.feed?.status ?? "—"}
        {nat?.feed?.reason ? ` (${nat.feed.reason})` : ""} · parytet z oryginałem {nat?.original_parity ?? "—"}</p>
    </div>);
}
