// 1.33 chart layers (ChartPanel): Pepe Scalp Plan / Pepe Hedge Plan (PMW-PLAN-1), AVWAP session line with ±1σ/±2σ (PMW-IND-1) and
// SVP zones (PMW-SVP-1). Values come from the backend - the panel only draws them. Switching a layer never changes an order.
import { useEffect, useRef, type RefObject } from "react";
import { LineSeries, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { usePersisted } from "../../router";
import { cls, epochSec } from "../../util";
import { usePoll } from "./usePoll";

export type PmwLayers = { scalp: boolean; hedge: boolean; avwap: boolean; svp: boolean };
const DEF: PmwLayers = { scalp: false, hedge: false, avwap: false, svp: false };
const AVWAP_TFS = ["M1", "M5"];
const COL = { scalp: "#3fe6ff", hedge: "#ffb347", sl: "#ff5470", tp: "#2fe6a0", avwap: "#c8a24a", svp: "#b46bff" };

export function usePmwLayers(): [PmwLayers, (v: PmwLayers) => void] {
  return usePersisted<PmwLayers>("pmwLayers133", DEF, (v) => v && typeof v === "object" && "scalp" in v);
}

type Line = { price: number; title: string; color: string; style: LineStyle; width: 1 | 2 };

export function planLines(payload: any, tag: string, base: string): Line[] {
  const p = (payload?.plans || []).find((x: any) => x.plan_key === payload?.primary) ?? (payload?.plans || [])[0];
  if (!p || !["READY", "ACTIVE"].includes(p.state)) return [];
  const out: Line[] = [];
  for (const l of p.levels || []) {
    if (typeof l.price !== "number") continue;
    const c = l.name === "SL" ? COL.sl : l.name.startsWith("TP") ? COL.tp : base;
    out.push({ price: l.price, title: `${tag}: ${l.label || l.name}`, color: c, style: l.name === "ENTRY" ? LineStyle.Solid : LineStyle.Dashed, width: 1 });
  }
  const ex = p.execution;
  if (ex?.entry_fill != null) out.push({ price: ex.entry_fill, title: `${tag}: fill`, color: base, style: LineStyle.Solid, width: 2 });
  if (ex?.sl_current != null && ex.sl_current !== ex.sl_plan) out.push({ price: ex.sl_current, title: `${tag}: SL v${ex.sl_version}`, color: COL.sl, style: LineStyle.Solid, width: 2 });
  const h = p.hedge;
  if (h?.available && h.activation_level != null) out.push({ price: h.activation_level, title: `${tag}: aktywacja hedge`, color: COL.hedge, style: LineStyle.SparseDotted, width: 1 });
  if (h?.leg?.entry != null) out.push({ price: h.leg.entry, title: `${tag}: noga hedge ${h.leg.side ?? ""}`, color: COL.hedge, style: LineStyle.Solid, width: 2 });
  return out;
}

export function usePmwOverlays({ chart, candles, tf, layers, shift, dataKey }: {
  chart: RefObject<IChartApi | null>; candles: RefObject<ISeriesApi<"Candlestick"> | null>; tf: string; layers: PmwLayers; shift: number; dataKey: unknown;
}) {
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
    if (layers.svp) for (const z of (svp.data as any)?.items || []) {
      if (typeof z.lower !== "number" || typeof z.upper !== "number") continue;
      all.push({ price: z.upper, title: `SVP ${z.source}: ${z.name ?? ""}`, color: z.color || COL.svp, style: LineStyle.Dotted, width: 1 });
      all.push({ price: z.lower, title: "", color: z.color || COL.svp, style: LineStyle.Dotted, width: 1 });
    }
    for (const l of all) lines.current.push(ser.createPriceLine({ price: l.price, color: l.color, title: l.title, lineStyle: l.style, lineWidth: l.width, axisLabelVisible: !!l.title }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.scalp, layers.hedge, layers.svp, scalp.data, hedge.data, svp.data, dataKey]);

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
  return { avwStatus, avwReason: layers.avwap ? (avw.data as any)?.avwap?.SESSION?.reason : null, err: scalp.err || hedge.err || avw.err || svp.err };
}

export function PmwLayerButtons({ layers, onChange, info }: { layers: PmwLayers; onChange: (v: PmwLayers) => void; info?: { avwStatus?: string | null; avwReason?: string | null } }) {
  const b = (k: keyof PmwLayers, label: string, title: string) => (
    <button key={k} className={cls("icon", layers[k] && "on")} data-act={`pmw-${k}`} aria-pressed={layers[k]} title={title}
      onClick={() => onChange({ ...layers, [k]: !layers[k] })}>{label}</button>);
  return (
    <span className="pmw-layers" data-testid="pmw-layers">
      {b("scalp", "Scalp Plan", "Pepe Scalp Plan – poziomy planu SCALPING (wejście, SL, TP, fill, SL v2)")}
      {b("hedge", "Hedge Plan", "Pepe Hedge Plan – plan HEDGING, poziom aktywacji i noga zabezpieczająca")}
      {b("avwap", "AVWAP", "AVWAP sesji z pasmami ±1σ/±2σ (PMW-IND-1)")}
      {b("svp", "SVP", "Strefy SVP (ręczne / algorytm / AI) jako linie granic")}
      {layers.avwap && info?.avwStatus && info.avwStatus !== "OK" &&
        <span className="badge warn" title={info.avwReason ?? ""}>AVWAP: {info.avwStatus}</span>}
    </span>);
}
