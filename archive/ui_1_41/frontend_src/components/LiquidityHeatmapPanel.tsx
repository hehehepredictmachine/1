// PMW-UPD-06: liquidation heatmap panel. Estimated levels of the provider model (CoinGlass model1) on the SOURCE price axis
// (XAUT / BTC perpetual are not the broker CFD) with a shared UTC time axis; tiles are the real price buckets x candle times of the
// snapshot. Raw intensity is kept; colour = log1p scale (legend). No source / no key / no snapshot -> a clear empty state with the
// reason - never illustrative blobs. The key is sent once to the backend SecretStore and never shown again.
import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { fmtNum, fmtTime } from "../util";

export default function LiquidityHeatmapPanel() {
  const { s } = useStore();
  const asset = s.assets?.active;
  const [d, setD] = useState<any>(null);
  const [tip, setTip] = useState<string | null>(null);
  const [form, setForm] = useState<any>(null);
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [opacity, setOpacity] = useState(0.85);
  const cv = useRef<HTMLCanvasElement>(null);
  const req = useRef(0);
  const load = () => {
    if (!asset) return;
    const id = ++req.current;
    apiGet(`/api/v1/liquidity/heatmap?asset=${asset}&max_cells=20000`).then((r) => {
      if (id !== req.current || r.asset !== asset) return;
      setD(r);
      setForm((f: any) => f ?? { ...(r.source || {}) });
    }).catch(() => undefined);
  };
  useEffect(() => { setD(null); setForm(null); load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [asset]);

  const g = d?.grid;
  useEffect(() => {
    const c = cv.current;
    if (!c || !g || !g.times || !g.cells?.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = c.clientWidth, H = c.clientHeight;
    c.width = W * dpr; c.height = H * dpr;
    const ctx = c.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    const pe: number[] = g.price_edges, tt: number[] = g.times;
    const pMin = pe[0], pMax = pe[pe.length - 1];
    const step = tt.length > 1 ? tt[1] - tt[0] : 60;
    const tMin = tt[0], tMax = tt[tt.length - 1] + (tt.length > 1 ? tt[tt.length - 1] - tt[tt.length - 2] : step);
    const axisW = 56;
    const x = (t: number) => ((t - tMin) / (tMax - tMin)) * (W - axisW);
    const y = (p: number) => H - ((p - pMin) / (pMax - pMin)) * H;
    const vmax = Math.log1p(Math.max(...g.cells.map((q: number[]) => q[2])));
    for (const [ti, pi, v] of g.cells) {
      const t0 = tt[ti], t1 = ti + 1 < tt.length ? tt[ti + 1] : tMax;
      const a = vmax > 0 ? Math.log1p(v) / vmax : 0;
      ctx.fillStyle = `rgba(255,${Math.round(200 - 160 * a)},0,${(0.05 + 0.95 * a) * opacity})`;
      ctx.fillRect(x(t0), y(pe[pi + 1]), Math.max(1, x(t1) - x(t0)), Math.max(1, y(pe[pi]) - y(pe[pi + 1])));
    }
    ctx.fillStyle = "#999";
    ctx.font = "10px Inter, system-ui, sans-serif";
    for (let k = 0; k <= 5; k++) {
      const p = pMin + ((pMax - pMin) * k) / 5;
      ctx.fillText(fmtNum(p, 1), W - axisW + 4, y(p) + 3);
    }
    for (const z of d?.zones?.zones || []) {
      ctx.strokeStyle = "rgba(122,167,255,0.9)";
      ctx.setLineDash([3, 3]);
      ctx.strokeRect(0, y(z.high), W - axisW, Math.max(1, y(z.low) - y(z.high)));
      ctx.setLineDash([]);
    }
  }, [g, opacity, d?.zones]);

  const onMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!g?.times || !g.cells?.length) return;
    const r = e.currentTarget.getBoundingClientRect();
    const W = r.width - 56, H = r.height;
    const fx = (e.clientX - r.left) / W, fy = 1 - (e.clientY - r.top) / H;
    if (fx < 0 || fx > 1) { setTip(null); return; }
    const pe: number[] = g.price_edges, tt: number[] = g.times;
    const p = pe[0] + fy * (pe[pe.length - 1] - pe[0]);
    const tEnd = tt[tt.length - 1] + (tt.length > 1 ? tt[tt.length - 1] - tt[tt.length - 2] : 60);
    const t = tt[0] + fx * (tEnd - tt[0]);
    let ti = 0;
    while (ti + 1 < tt.length && tt[ti + 1] <= t) ti++;
    let pi = 0;
    while (pi + 1 < pe.length - 1 && pe[pi + 1] <= p) pi++;
    const cell = g.cells.find((q: number[]) => q[0] === ti && q[1] === pi);
    setTip(`${new Date(tt[ti] * 1000).toISOString().slice(5, 16)} UTC · ${fmtNum(pe[pi], 2)}–${fmtNum(pe[pi + 1], 2)} · intensywność ${cell ? fmtNum(cell[2], 0) : "brak komórki (nieznane, nie zero)"} · snapshot ${d.snapshot_id}`);
  };

  const save = () => apiSend("PUT", "/api/v1/liquidity/source", { asset, ...form }).then(() => { setMsg("Zapisano źródło."); load(); }).catch((e) => setMsg(String(e.message || e)));
  const saveKey = () => apiSend("PUT", "/api/v1/liquidity/key", { key }).then((r: any) => { setKey(""); setMsg(`Klucz: ${r.key_status}`); load(); }).catch((e) => setMsg(String(e.message || e)));
  const poll = () => apiSend("POST", "/api/v1/liquidity/poll", {}).then(() => { setMsg("Odpytano źródło."); load(); }).catch((e) => setMsg(String(e.message || e)));
  if (!d) return null;
  return (
    <div className="card" data-testid="liq-heatmap" data-status={d.status}>
      <h3>Heatmapa likwidacji (szacowane poziomy) – {asset}</h3>
      <p className="small">Źródło: {d.provider} · {d.data_kind} · {d.source?.variant} {d.source?.source_symbol ?? "—"}{d.source?.exchange ? `@${d.source.exchange}` : ""} · zakres {d.source?.range}
        · klucz: {d.key_status} · status: <b data-testid="liq-status">{d.status}</b>{d.source_status ? ` (ostatnio ${d.source_status.status} ${fmtTime(d.source_status.at, true)})` : ""}</p>
      {d.status === "OK" || d.status === "STALE" ? <>
        <p className="small">Oś ceny: <b>{d.axis}</b> · instrument źródła {d.source_instrument?.symbol} → cel {d.target_instrument} ({d.mapping_status}) · otrzymano {fmtTime(d.first_received_at, true)} ({d.availability_trust})
          · wiek {d.age_s}s{d.status === "STALE" ? " · NIEAKTUALNA" : ""} · jednostka {g?.intensity_unit} (kolor log1p) · brak komórki = {g?.missing_cell_semantics}{g?.lod ? ` · ${g.lod}` : ""}</p>
        {g?.time_axis_status !== "OK" ? <p className="small">TIME_AXIS_UNVERIFIED – siatka bez potwierdzonej osi czasu nie jest rysowana.</p> :
          <canvas ref={cv} style={{ width: "100%", height: 260, display: "block" }} onMouseMove={onMove} onMouseLeave={() => setTip(null)} aria-label="Heatmapa likwidacji" />}
        <p className="small mono">{tip ?? "najedź na kafel – surowa intensywność, przedział ceny i czasu"}</p>
        <p className="small">Strefy analityczne ({d.zones?.status}; {d.zones?.method}): {(d.zones?.zones || []).slice(0, 8).map((z: any) => `#${z.rank} ${fmtNum(z.low, 1)}–${fmtNum(z.high, 1)}`).join(" · ") || "brak"}</p>
        <label className="small">przezroczystość <input type="range" min={0.2} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(+e.target.value)} /></label>
      </> : <p className="small" data-testid="liq-empty">{d.reason ?? "Brak danych heatmapy"} – sesje i bazowy bot działają bez zmian.</p>}
      {form && <details className="small"><summary>Ustawienia źródła (autoryzowane API CoinGlass lub import pliku do data/liquidity/inbox)</summary>
        <label><input type="checkbox" checked={!!form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> włączone</label>{" "}
        <select aria-label="Wariant" value={form.variant} onChange={(e) => setForm({ ...form, variant: e.target.value })}><option value="AGGREGATED">AGGREGATED (moneta)</option><option value="PAIR">PAIR (para + giełda)</option></select>{" "}
        <input aria-label="Symbol źródła" placeholder="symbol dostawcy, np. BTC" value={form.source_symbol ?? ""} onChange={(e) => setForm({ ...form, source_symbol: e.target.value || null })} />{" "}
        <input aria-label="Giełda" placeholder="giełda (PAIR)" value={form.exchange ?? ""} onChange={(e) => setForm({ ...form, exchange: e.target.value || null })} />{" "}
        <select aria-label="Zakres" value={form.range} onChange={(e) => setForm({ ...form, range: e.target.value })}>{["12h", "24h", "3d", "7d", "30d", "90d", "180d", "1y"].map((r) => <option key={r}>{r}</option>)}</select>{" "}
        <button className="btn ghost" onClick={save}>Zapisz źródło</button>
        <div><input aria-label="Klucz API" type="password" placeholder="CG-API-KEY (zapisywany tylko w backendzie)" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />{" "}
          <button className="btn ghost" onClick={saveKey} disabled={!key}>Zapisz klucz</button>{" "}<button className="btn ghost" onClick={poll}>Odpytaj teraz</button></div>
        <p className="muted">Mapowanie na cenę brokera: tylko po zweryfikowanym adapterze basis (domyślnie UNMAPPED – osobna oś). Plan API (Professional/Enterprise) nie jest zakładany; status ENTITLEMENT_REQUIRED pokaże brak uprawnień.</p>
      </details>}
      {msg && <p className="small">{msg}</p>}
    </div>);
}
