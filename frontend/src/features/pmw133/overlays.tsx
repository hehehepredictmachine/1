// 1.33 chart layers (ChartPanel): Pepe Scalp Plan / Pepe Hedge Plan (PMW-PLAN-1), AVWAP session line with ±1σ/±2σ (PMW-IND-1) and
// SVP zones (PMW-SVP-1). Values come from the backend - the panel only draws them. Switching a layer never changes an order.
// 1.38: "Pakiet 20" layer (PMW-PLAN-2): the selected variant plan + active positions only (never 20 sets of lines), TP1/TP2 without a
// fictitious TP3, the confirmed-signal arrow on the bar where the information was available (WATCH = neutral circle), one owner per
// drawn level (stable key plan|level|version - a polling refresh never multiplies lines), labels with the source TF.
import { useEffect, useRef, type RefObject } from "react";
import { createSeriesMarkers, LineSeries, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type Time } from "lightweight-charts";
import { usePersisted } from "../../router";
import { cls, epochSec } from "../../util";
import { usePoll } from "./usePoll";

export type PmwLayers = { scalp: boolean; hedge: boolean; avwap: boolean; svp: boolean; pack?: boolean };
const DEF: PmwLayers = { scalp: false, hedge: false, avwap: false, svp: false, pack: false };
export type PackFilter = { family: "ALL" | "SCALPING" | "HEDGING"; strategy: string; history: boolean; levels: boolean };
const PACK_DEF: PackFilter = { family: "ALL", strategy: "ALL", history: false, levels: true };
const TF_SEC: Record<string, number> = { M1: 60, M3: 180, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400, D1: 86400 };

export function usePackFilter(): [PackFilter, (v: PackFilter) => void] {
  return usePersisted<PackFilter>("pmwPack138", PACK_DEF, (v) => v && typeof v === "object" && "family" in v && "strategy" in v);
}
const AVWAP_TFS = ["M1", "M5"];
const COL = { scalp: "#3fe6ff", hedge: "#ffb347", sl: "#ff5470", tp: "#2fe6a0", avwap: "#c8a24a", svp: "#b46bff" };

export function usePmwLayers(): [PmwLayers, (v: PmwLayers) => void] {
  return usePersisted<PmwLayers>("pmwLayers133", DEF, (v) => v && typeof v === "object" && "scalp" in v);
}

type Line = { price: number; title: string; color: string; style: LineStyle; width: 1 | 2 };

export function planLines(payload: any, tag: string, base: string, opts?: { activeToo?: boolean; tf?: string }): Line[] {
  const plans: any[] = payload?.plans || [];
  const p = plans.find((x: any) => x.plan_key === payload?.primary) ?? plans[0];
  const pick = [p, ...(opts?.activeToo ? plans.filter((x) => x !== p && x.state === "ACTIVE") : [])].filter((x) => x && ["READY", "ACTIVE"].includes(x.state));
  const out: Line[] = [];
  const seen = new Map<string, Line>();
  for (const pl of pick) {
    const src = pl.signal_tf && opts?.tf && pl.signal_tf !== opts.tf ? ` (TF ${pl.signal_tf})` : "";
    const nm = pl.strategy_id ? `${pl.strategy_id}` : tag;
    for (const l of pl.levels || []) {
      if (typeof l.price !== "number") continue;
      const key = l.key || `${pl.plan_key}|${l.name}`;
      // one line per price: ENTRY PLAN and ENTRY FILL at the same price become one line with both labels
      const dup = [...seen.values()].find((x) => Math.abs(x.price - l.price) < 1e-9 && (l.name === "ENTRY_FILL" || l.name === "ENTRY"));
      if (seen.has(key)) continue;
      if (dup) { dup.title += ` + ${l.label || l.name}`; continue; }
      const c = l.name === "SL" || l.name === "SL_CURRENT" ? COL.sl : l.name.startsWith("TP") ? COL.tp : l.name.startsWith("HEDGE") ? COL.hedge : base;
      const ln: Line = { price: l.price, title: `${nm}: ${l.label || l.name}${src}`, color: c,
        style: l.name === "ENTRY" ? LineStyle.Solid : l.name === "HEDGE_ACTIVATION" ? LineStyle.SparseDotted : l.kind === "FILL" || l.kind === "HEDGE_FILL" || l.kind === "MANAGED" ? LineStyle.Solid : LineStyle.Dashed,
        width: l.kind === "FILL" || l.kind === "HEDGE_FILL" || l.kind === "MANAGED" ? 2 : 1 };
      seen.set(key, ln);
      out.push(ln);
    }
  }
  return out;
}

export function planArrows(payload: any, tf: string, shift: number, history: boolean) {
  const sec = TF_SEC[tf];
  if (!sec) return [];
  const out: any[] = [];
  for (const p of payload?.plans || []) {
    const a = p.arrow;
    if (!a?.time) continue;
    if (!history && !["READY", "ACTIVE"].includes(p.state) && p.plan_key !== payload?.primary) continue;
    const at = epochSec(a.time);
    const bar = Math.floor(at / sec) * sec;                  // the chart bar containing the moment the information became available
    const ok = a.kind === "CONFIRMED";
    out.push({ time: (bar + shift) as Time, position: a.position, shape: ok ? (a.side === "SELL" ? "arrowDown" : "arrowUp") : "circle",
      color: ok ? (a.side === "SELL" ? COL.sl : COL.tp) : "#8a96a0", text: `${ok ? "" : "WATCH "}${a.label}`, id: `${p.plan_key}|arrow` });
  }
  return out.sort((x, y) => (x.time as number) - (y.time as number));
}

export function usePmwOverlays({ chart, candles, tf, layers, shift, dataKey }: {
  chart: RefObject<IChartApi | null>; candles: RefObject<ISeriesApi<"Candlestick"> | null>; tf: string; layers: PmwLayers; shift: number; dataKey: unknown;
}) {
  const [pf] = usePackFilter();
  const packUrl = layers.pack ? `/api/v1/plans/chart?layer=PACK${pf.family !== "ALL" ? `&family=${pf.family}` : ""}${pf.strategy !== "ALL" ? `&strategy_id=${encodeURIComponent(pf.strategy)}` : ""}&history=${pf.history ? 30 : 8}` : null;
  const pack = usePoll(packUrl, 5000);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const markersOf = useRef<unknown>(null);
  const scalp = usePoll(layers.scalp ? "/api/v1/plans/chart?layer=SCALP" : null, 5000);
  const hedge = usePoll(layers.hedge ? "/api/v1/plans/chart?layer=HEDGE" : null, 5000);
  const avwTf = AVWAP_TFS.includes(tf);                       // config.indicators.avwap_tfs (default M1, M5) - other TFs: no request
  const avw = usePoll(layers.avwap && avwTf ? `/api/v1/indicators/chart?tf=${encodeURIComponent(tf)}` : null, 20000);
  const svp = usePoll(layers.svp ? "/api/v1/svp/zones" : null, 20000);
  const lines = useRef<IPriceLine[]>([]);
  const series = useRef<ISeriesApi<"Line">[]>([]);

  useEffect(() => {
    const ser = candles.current;
    if (!ser) return;
    lines.current.forEach((l) => { try { ser.removePriceLine(l); } catch { /* series recreated */ } });
    lines.current = [];
    const all: Line[] = [];
    if (layers.scalp) all.push(...planLines(scalp.data, "Pepe Scalp Plan", COL.scalp));
    if (layers.hedge) all.push(...planLines(hedge.data, "Pepe Hedge Plan", COL.hedge));
    if (layers.pack && pf.levels) all.push(...planLines(pack.data, "Pakiet", COL.scalp, { activeToo: true, tf }));
    if (layers.svp) for (const z of (svp.data as any)?.items || []) {
      if (typeof z.lower !== "number" || typeof z.upper !== "number") continue;
      all.push({ price: z.upper, title: `SVP ${z.source}: ${z.name ?? ""}`, color: z.color || COL.svp, style: LineStyle.Dotted, width: 1 });
      all.push({ price: z.lower, title: "", color: z.color || COL.svp, style: LineStyle.Dotted, width: 1 });
    }
    for (const l of all) lines.current.push(ser.createPriceLine({ price: l.price, color: l.color, title: l.title, lineStyle: l.style, lineWidth: l.width, axisLabelVisible: !!l.title }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.scalp, layers.hedge, layers.svp, layers.pack, pf.levels, scalp.data, hedge.data, svp.data, pack.data, dataKey, tf]);

  useEffect(() => {                                           // signal arrows: one markers primitive owned by this hook, replaced on every update
    const ser = candles.current;
    if (!ser) return;
    if (markersOf.current !== ser) { markers.current = null; markersOf.current = null; }   // old series went away with its chart: never detach a disposed one
    if (!layers.pack) { try { markers.current?.setMarkers([]); } catch { /* chart recreated */ } return; }
    if (!markers.current) { markers.current = createSeriesMarkers(ser, []); markersOf.current = ser; }
    try { markers.current.setMarkers(planArrows(pack.data, tf, shift, pf.history)); } catch { /* chart recreated */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.pack, pack.data, tf, shift, pf.history, dataKey]);

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    series.current.forEach((s) => { try { c.removeSeries(s); } catch { /* chart recreated */ } });
    series.current = [];
    const line = (avw.data as any)?.avwap?.SESSION?.line as any[] | undefined;
    if (!layers.avwap || !line?.length) return;
    const keys: [string, string, LineStyle, 1 | 2][] = [["avwap", "AVWAP sesji", LineStyle.Solid, 2], ["upper1", "+1σ", LineStyle.Dashed, 1],
      ["lower1", "−1σ", LineStyle.Dashed, 1], ["upper2", "+2σ", LineStyle.Dotted, 1], ["lower2", "−2σ", LineStyle.Dotted, 1]];
    for (const [k, title, style, w] of keys) {
      const s = c.addSeries(LineSeries, { color: COL.avwap, lineWidth: w, lineStyle: style, priceLineVisible: false, lastValueVisible: k === "avwap", title: k === "avwap" ? title : "" });
      const pts = line.filter((p) => typeof p[k] === "number").map((p) => ({ time: (epochSec(p.t) + shift) as Time, value: p[k] as number }));
      const uniq = pts.filter((p, i) => i === 0 || (p.time as number) > (pts[i - 1].time as number));
      s.setData(uniq);
      series.current.push(s);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.avwap, avw.data, shift, dataKey]);

  const avwStatus = layers.avwap ? (avwTf ? (avw.data as any)?.avwap?.SESSION?.status : "TYLKO M1/M5") : null;
  return { avwStatus, avwReason: layers.avwap ? (avw.data as any)?.avwap?.SESSION?.reason : null, err: scalp.err || hedge.err || avw.err || svp.err || pack.err,
    packCount: layers.pack ? ((pack.data as any)?.plans || []).length : null };
}

function PackControls() {
  const [pf, setPf] = usePackFilter();
  const cat = usePoll<any>("/api/v1/sh/strategies", 60000);
  const items: any[] = (cat.data?.items || []).filter((x: any) => pf.family === "ALL" || x.family === pf.family);
  return (
    <span className="pack-controls" data-testid="pack-controls">
      <select value={pf.family} onChange={(e) => setPf({ ...pf, family: e.target.value as any, strategy: "ALL" })} data-testid="pack-family" title="Scalp / Hedge">
        <option value="ALL">Scalp+Hedge</option><option value="SCALPING">Scalp</option><option value="HEDGING">Hedge</option></select>
      <select value={pf.strategy} onChange={(e) => setPf({ ...pf, strategy: e.target.value })} data-testid="pack-strategy" title="konkretna strategia">
        <option value="ALL">wszystkie warianty</option>{items.map((x) => <option key={x.strategy_id} value={x.strategy_id}>{x.strategy_id} {x.name}</option>)}</select>
      <button className={cls("icon", pf.history && "on")} onClick={() => setPf({ ...pf, history: !pf.history })} title="aktywne / historia" data-act="pack-history">hist.</button>
      <button className={cls("icon", pf.levels && "on")} onClick={() => setPf({ ...pf, levels: !pf.levels })} title="Entry / SL / TP" data-act="pack-levels">E/SL/TP</button>
    </span>);
}

export function PmwLayerButtons({ layers, onChange, info }: { layers: PmwLayers; onChange: (v: PmwLayers) => void; info?: { avwStatus?: string | null; avwReason?: string | null; packCount?: number | null } }) {
  const b = (k: keyof PmwLayers, label: string, title: string) => (
    <button key={k} className={cls("icon", layers[k] && "on")} data-act={`pmw-${k}`} aria-pressed={!!layers[k]} title={title}
      onClick={() => onChange({ ...layers, [k]: !layers[k] })}>{label}</button>);
  return (
    <span className="pmw-layers" data-testid="pmw-layers">
      {b("scalp", "Scalp Plan", "Pepe Scalp Plan – poziomy planu SCALPING (wejście, SL, TP, fill, SL v2)")}
      {b("hedge", "Hedge Plan", "Pepe Hedge Plan – plan HEDGING, poziom aktywacji i noga zabezpieczająca")}
      {b("avwap", "AVWAP", "AVWAP sesji z pasmami ±1σ/±2σ (PMW-IND-1)")}
      {b("svp", "SVP", "Strefy SVP (ręczne / algorytm / AI) jako linie granic")}
      {b("pack", "Pakiet 20", "20 strategii SC/HG (PMW-PLAN-2): strzałki potwierdzonych sygnałów, Entry/SL/TP1/TP2, stan hedge")}
      {layers.pack && <PackControls />}
      {layers.pack && info?.packCount === 0 && <span className="badge muted">brak planów</span>}
      {layers.avwap && info?.avwStatus && info.avwStatus !== "OK" &&
        <span className="badge warn" title={info.avwReason ?? ""}>AVWAP: {info.avwStatus}</span>}
    </span>);
}
