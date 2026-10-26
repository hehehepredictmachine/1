// One chart panel. Root cause of the old "shared zoom" (fixed here):
//  1) every full analysis (global analysisSeq) reloaded ALL charts and the render step re-created the indicator
//     series and removed/re-added panes -> Lightweight Charts reset the time scale of every chart at once;
//  2) the "sync" option broadcast the visible range of any chart to all others, and the crosshair handler kept a stale
//     copy of the options.
// Now: series are created once and only updated; the visible range is saved before and restored after every data
// refresh (anchored on time, so older candles loaded on the left do not move the view); each chart keeps its own
// view state (chart_id + symbol + TF) changed only by user actions; range sync is off by default and works only
// inside an explicitly chosen group; crosshair sync is a separate switch.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { apiGet } from "../api";
import { loadView, saveView, SYNC, viewKey, type ChartView, type SyncGroup, type SyncMsg } from "../chartview";
import { useStore } from "../store";
import { parseColor, toHex, useTheme, type Tokens } from "../theme";
import { chartShift, cls, epochSec, fmtNum, type TimeZoneMode } from "../util";
import { BoundedBoxesPrimitive, type BoundedBox, type BoxMarker, ZonesPrimitive } from "../zones";

export interface ChartOpts {
  showRsi: boolean;
  showMacd: boolean;
  showStructure: boolean;
  showZones: boolean;
  showVol: boolean;
  syncCrosshair: boolean;
  tz: TimeZoneMode;
  showPatterns?: boolean;        // 1.10: walls snapshot, M5 range + M1 zones, chart patterns, confirmed pivots, candle evidence
  showAiLevels?: boolean;        // 1.10: levels proposed by the AI (marked "AI:", separate from the engine plan)
  showSar?: boolean;             // PMW-UPD-02: shared SAR core points
  showExtInd?: boolean;          // PMW-UPD-02: IQ Gold Gann / Star Lines levels from the approved exporter mapping
  showSessions?: boolean;        // PMW-UPD-06: session sweep boxes (shared engine, time-bounded) + edge events
  showHeatmap?: boolean;         // PMW-UPD-06: liquidation heatmap panel (separate source price axis unless mapping is validated)
  showZoneMap?: boolean;         // PMW zone map (HLZE + DSVIE + UZICE) from /api/v1/zones/map - backend values only
}

export type AiLevels = { zone?: [number, number] | null; invalidation?: number | null; targets?: number[]; label?: string } | null;
export type Highlight = { price: number; label: string } | null;
const ROLE_PL: Record<string, string> = { TRIGGER: "potwierdzenie / trigger", SETUP: "setup", SETUP_CONTEXT: "kontekst setupu", LOCAL_CONTEXT: "kontekst lokalny",
  HTF: "wyższy kontekst", TREND_REGIME_CONTEXT: "kontekst trendu / reżimu", BACKGROUND: "tło rynku" };

const withAlpha = (c: string, a: number) => {
  const p = parseColor(c);
  return p ? toHex({ ...p, a }) : c;
};

declare global {
  interface Window { __mqCharts?: Record<string, any> }
}

export default function ChartPanel({ tf, index, opts, onFullscreen, fullscreen, chartId: idProp, variant, onMain, isMain, aiLevels, highlight, roleText, needed }: {
  tf: string;
  index: number;
  opts: ChartOpts;
  onFullscreen: () => void;
  fullscreen: boolean;
  chartId?: string;               // stable id: page + TF (zoom / view state survive moving between slots and pages)
  variant?: "main" | "normal" | "compact";
  onMain?: () => void;            // "Wykres główny": move this TF into the large slot (no 6th chart)
  isMain?: boolean;
  aiLevels?: AiLevels;
  highlight?: Highlight;
  roleText?: string | null;
  needed?: boolean | null;        // TF required by the selected setup's strategy
}) {
  const { s } = useStore();
  const theme = useTheme();
  const chartId = idProp ?? `panel${index}`;
  const symbol = s.symbol?.symbol ?? "XAUUSD-";
  const vkey = viewKey(chartId, symbol, tf);
  const tk: Tokens = { ...theme.chartTokens(`tf:${tf}`), ...(idProp ? {} : theme.chartTokens(chartId)) };
  const tkRef = useRef(tk);
  tkRef.current = tk;
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lines = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const rsi = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiLevels = useRef<IPriceLine[]>([]);
  const macd = useRef<{ line: ISeriesApi<"Line">; sig: ISeriesApi<"Line">; hist: ISeriesApi<"Histogram"> } | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const zones = useRef<ZonesPrimitive | null>(null);
  const volZones = useRef<ZonesPrimitive | null>(null);
  const volLines = useRef<IPriceLine[]>([]);
  const priceLines = useRef<IPriceLine[]>([]);
  const aiLines = useRef<IPriceLine[]>([]);
  const hlLines = useRef<IPriceLine[]>([]);
  const structLines = useRef<IPriceLine[]>([]);
  const structZones = useRef<ZonesPrimitive | null>(null);
  const sessBoxes = useRef<BoundedBoxesPrimitive | null>(null);
  const [sessions, setSessions] = useState<any>(null);
  const zmBoxes = useRef<BoundedBoxesPrimitive | null>(null);
  const [zoneMap, setZoneMap] = useState<any>(null);
  const zoneMapRef = useRef<any>(null);
  zoneMapRef.current = zoneMap;
  const [zoneTip, setZoneTip] = useState<string | null>(null);
  const structMarkers = useRef<SeriesMarker<Time>[]>([]);
  const baseMarkers = useRef<SeriesMarker<Time>[]>([]);
  const [structure, setStructure] = useState<any>(null);
  const [indCtx, setIndCtx] = useState<any>(null);
  const sarSeries = useRef<ISeriesApi<"Line"> | null>(null);
  const extLines = useRef<IPriceLine[]>([]);
  const times = useRef<number[]>([]);                 // chart times of the candles currently in the series
  const initialized = useRef(false);
  const userUntil = useRef(0);                         // range changes before this moment come from the user
  const view = useRef<ChartView>(loadView(vkey));
  const [viewUi, setViewUi] = useState<ChartView>(view.current);
  const [data, setData] = useState<any>(null);
  const [legend, setLegend] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const offset = s.connection?.clock?.offset_seconds ?? null;
  const shift = chartShift(opts.tz, offset);
  const shiftRef = useRef(shift);
  shiftRef.current = shift;
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const T = (iso: string) => (epochSec(iso) + shift) as Time;

  const setView = useCallback((patch: Partial<ChartView>) => {
    view.current = { ...view.current, ...patch };
    saveView(vkey, view.current);
    setViewUi(view.current);
  }, [vkey]);
  const markUser = () => { userUntil.current = performance.now() + 450; };

  // ---------------------------------------------------------------- create chart (once per panel + TF)
  useEffect(() => {
    if (!box.current) return;
    view.current = loadView(vkey);
    setViewUi(view.current);
    initialized.current = false;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10, attributionLogo: true },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 6, shiftVisibleRangeOnNewBar: true },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { autoScale: view.current.autoScale },
    });
    chart.current = c;
    candles.current = c.addSeries(CandlestickSeries, {});
    volume.current = c.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    c.priceScale("right").applyOptions({ scaleMargins: { top: 0.05, bottom: 0.12 } });
    zones.current = new ZonesPrimitive();
    candles.current.attachPrimitive(zones.current);
    volZones.current = new ZonesPrimitive();
    candles.current.attachPrimitive(volZones.current);
    structZones.current = new ZonesPrimitive();
    candles.current.attachPrimitive(structZones.current);
    sessBoxes.current = new BoundedBoxesPrimitive();
    candles.current.attachPrimitive(sessBoxes.current);
    zmBoxes.current = new BoundedBoxesPrimitive();
    candles.current.attachPrimitive(zmBoxes.current);
    markers.current = createSeriesMarkers(candles.current, []);
    const el = box.current;
    const onUser = () => markUser();
    const onMove = (e: PointerEvent) => { if (e.buttons) markUser(); };
    el.addEventListener("wheel", onUser, { passive: true });
    el.addEventListener("pointerdown", onUser);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("touchstart", onUser, { passive: true });
    el.addEventListener("touchmove", onUser, { passive: true });
    el.addEventListener("dblclick", onUser);
    c.subscribeCrosshairMove((p) => {
      if (!p.time || !candles.current) setLegend(null);
      else {
        const b: any = p.seriesData.get(candles.current);
        setLegend(b ? { o: b.open, h: b.high, l: b.low, c: b.close } : null);
      }
      setZoneTip(zoneTipAt(zoneMapRef.current, p.point && candles.current ? candles.current.coordinateToPrice(p.point.y) : null));
      if (optsRef.current.syncCrosshair && p.sourceEvent)
        SYNC.dispatchEvent(new CustomEvent("sync", { detail: { src: chartId, kind: "crosshair", time: (p.time as number) ?? null } as SyncMsg }));
    });
    c.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (!r || !initialized.current || performance.now() > userUntil.current) return;   // only the user's own actions
      const n = times.current.length;
      const follow = n > 0 && r.to >= n - 1;
      const tr = c.timeScale().getVisibleRange();
      view.current = { ...view.current, follow, width: r.to - r.from, rightGap: Math.max(0, r.to - (n - 1)),
        from: tr ? (tr.from as number) : undefined, to: tr ? (tr.to as number) : undefined };
      saveView(vkey, view.current);
      setViewUi(view.current);
      if (view.current.group && tr)
        SYNC.dispatchEvent(new CustomEvent("sync", { detail: { src: chartId, kind: "range", group: view.current.group, from: tr.from as number, to: tr.to as number } as SyncMsg }));
    });
    window.__mqCharts = window.__mqCharts || {};
    window.__mqCharts[chartId] = {
      tf, key: vkey, chart: c,
      logical: () => c.timeScale().getVisibleLogicalRange(),
      range: () => c.timeScale().getVisibleRange(),
      view: () => ({ ...view.current }),
      bars: () => times.current.length,
      volLines: () => volLines.current.map((p) => p.options().title),
      aiLines: () => aiLines.current.map((p) => p.options().title),
      structLines: () => structLines.current.map((p) => p.options().title),
      highlight: () => hlLines.current.map((p) => p.options().title),
      creations: (window.__mqCharts?.[chartId]?.creations ?? 0) + 1,
    };
    return () => {
      el.removeEventListener("wheel", onUser);
      el.removeEventListener("pointerdown", onUser);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("touchstart", onUser);
      el.removeEventListener("touchmove", onUser);
      el.removeEventListener("dblclick", onUser);
      c.remove();
      chart.current = null;
      sarSeries.current = null;
      extLines.current = [];
      lines.current = new Map();
      rsi.current = null;
      rsiLevels.current = [];
      macd.current = null;
      priceLines.current = [];
      aiLines.current = [];
      hlLines.current = [];
      structLines.current = [];
      volLines.current = [];
      times.current = [];
      if (window.__mqCharts?.[chartId]?.chart === c) delete window.__mqCharts[chartId];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tf, vkey]);

  // ---------------------------------------------------------------- theme -> applyOptions (no re-creation, view kept)
  useEffect(() => {
    const c = chart.current;
    if (!c || !candles.current) return;
    c.applyOptions({
      layout: { background: { type: ColorType.Solid, color: String(tk.chartBg) }, textColor: String(tk.chartLabels),
        panes: { separatorColor: String(tk.chartSeparator), separatorHoverColor: String(tk.chartAxis) } },
      grid: { vertLines: { color: String(tk.chartGrid) }, horzLines: { color: String(tk.chartGrid) } },
      rightPriceScale: { borderColor: String(tk.chartAxis) },
      timeScale: { borderColor: String(tk.chartAxis) },
      crosshair: { vertLine: { color: String(tk.chartCrosshair), labelBackgroundColor: String(tk.chartAxis) },
        horzLine: { color: String(tk.chartCrosshair), labelBackgroundColor: String(tk.chartAxis) } },
    });
    candles.current.applyOptions({ upColor: String(tk.upBody), downColor: String(tk.downBody), borderUpColor: String(tk.upBorder),
      borderDownColor: String(tk.downBorder), wickUpColor: String(tk.upWick), wickDownColor: String(tk.downWick), priceLineColor: String(tk.chartCrosshair) });
    let i = 0;
    lines.current.forEach((l) => l.applyOptions({ color: String(tk[`ind${(i++ % 6) + 1}`]) }));
    rsi.current?.applyOptions({ color: String(tk.rsi) });
    rsiLevels.current.forEach((pl) => pl.applyOptions({ color: String(tk.rsiLevels) }));
    macd.current?.line.applyOptions({ color: String(tk.macd) });
    macd.current?.sig.applyOptions({ color: String(tk.macdSignal) });
    if (data) paint(data, false);              // per-point colours (volume, histogram, forming candle), view preserved
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(tk)]);

  // ---------------------------------------------------------------- receive sync messages (no re-broadcast -> no loops)
  useEffect(() => {
    const h = (e: Event) => {
      const m = (e as CustomEvent).detail as SyncMsg;
      const c = chart.current;
      if (m.src === chartId || !c || !candles.current || m.workspace) return;      // dashboard-scoped messages are not for this page
      if (m.kind === "crosshair") {
        if (!optsRef.current.syncCrosshair) return;
        if (m.time == null) { c.clearCrosshairPosition(); return; }
        const ts = times.current;
        let k = -1;
        for (let i = ts.length - 1; i >= 0; i--) if (ts[i] <= m.time) { k = i; break; }
        const bars = data?.bars || [];
        const b = bars.filter((x: any) => x.open_utc)[k];
        if (b) c.setCrosshairPosition(b.c, ts[k] as Time, candles.current);
      } else if (m.kind === "range" && m.group && m.group === view.current.group && m.from && m.to) {
        try {
          c.timeScale().setVisibleRange({ from: m.from as Time, to: m.to as Time });
          const n = times.current.length;
          const r = c.timeScale().getVisibleLogicalRange();
          view.current = { ...view.current, from: m.from, to: m.to, follow: !!r && r.to >= n - 1, width: r ? r.to - r.from : view.current.width };
          saveView(vkey, view.current);
        } catch {
          /* range outside this chart's data */
        }
      }
    };
    SYNC.addEventListener("sync", h);
    return () => SYNC.removeEventListener("sync", h);
  }, [chartId, data, vkey]);

  // ---------------------------------------------------------------- data load (own TF; global analysis refresh only re-reads data)
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      apiGet(`/api/v1/candles?tf=${tf}`)
        .then((d) => alive && (setData(d), setErr(null)))
        .catch((e) => alive && setErr(String(e.message || e)));
    }, 150 + index * 60);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [tf, s.analysisSeq, index]);

  /** Restore the user's view after new data: follow mode keeps zoom at the right edge; otherwise anchor on the first visible candle's time. */
  const restoreView = (prevTimes: number[], prevLogical: { from: number; to: number } | null, newTimes: number[]) => {
    const c = chart.current!;
    const ts = c.timeScale();
    const n = newTimes.length;
    if (!n) return;
    const v = view.current;
    if (!initialized.current) {
      initialized.current = true;
      if (!v.follow && v.from && v.to && v.to > newTimes[0]) {
        try { ts.setVisibleRange({ from: v.from as Time, to: v.to as Time }); return; } catch { /* fall back to follow */ }
      }
      const w = v.width ?? 150;
      ts.setVisibleLogicalRange({ from: n - 1 - w + (v.rightGap ?? 6), to: n - 1 + (v.rightGap ?? 6) });
      return;
    }
    if (!prevLogical) return;
    if (v.follow) {
      const gapR = prevLogical.to - (prevTimes.length - 1);
      const w = prevLogical.to - prevLogical.from;
      ts.setVisibleLogicalRange({ from: n - 1 + gapR - w, to: n - 1 + gapR });
      return;
    }
    const i0 = Math.max(0, Math.min(prevTimes.length - 1, Math.round(prevLogical.from)));
    const anchor = prevTimes[i0];
    let j = newTimes.indexOf(anchor);
    if (j < 0) {                                         // anchor candle gone: nearest later candle
      j = newTimes.findIndex((x) => x >= anchor);
      if (j < 0) j = n - 1;
    }
    const d = j - i0;
    ts.setVisibleLogicalRange({ from: prevLogical.from + d, to: prevLogical.to + d });
  };

  // ---------------------------------------------------------------- paint data into the existing series
  const paint = (d: any, isNewData: boolean) => {
    const c = chart.current;
    if (!c || !candles.current || !volume.current) return;
    const t = tkRef.current;
    const sh = shiftRef.current;
    const TT = (iso: string) => (epochSec(iso) + sh) as Time;
    const ts = c.timeScale();
    const prevTimes = times.current;
    const prevLogical = ts.getVisibleLogicalRange();
    const bars = (d.bars || []).filter((b: any) => b.open_utc);
    const newTimes = bars.map((b: any) => TT(b.open_utc) as number);
    candles.current.setData(bars.map((b: any) => ({ time: TT(b.open_utc), open: b.o, high: b.h, low: b.l, close: b.c,
      ...(b.closed ? {} : { color: String(b.c >= b.o ? t.formingUp : t.formingDown) }) })));
    volume.current.setData(bars.map((b: any) => ({ time: TT(b.open_utc), value: b.tv, color: String(b.c >= b.o ? t.volUp : t.volDown) })));
    times.current = newTimes;
    // indicator lines: update in place; create/remove only when the set of lines changes
    const want = (d.indicators?.lines || []) as any[];
    const labels = new Set(want.map((l) => l.label));
    lines.current.forEach((ser, label) => { if (!labels.has(label)) { c.removeSeries(ser); lines.current.delete(label); } });
    want.forEach((ln, i) => {
      let ser = lines.current.get(ln.label);
      if (!ser) {
        ser = c.addSeries(LineSeries, { color: String(t[`ind${(i % 6) + 1}`]), lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, title: ln.label });
        lines.current.set(ln.label, ser);
      }
      ser.setData(ln.points.map((p: any) => ({ time: TT(p.time), value: p.value })));
    });
    // RSI / MACD panes: created when switched on, removed only when switched off
    const o = optsRef.current;
    const r = d.indicators?.panels?.rsi;
    if (o.showRsi && r) {
      if (!rsi.current) {
        rsi.current = c.addSeries(LineSeries, { color: String(t.rsi), lineWidth: 1, priceLineVisible: false, title: `RSI(${r.period})${r.visual_only ? "*" : ""}` }, 1);
        rsiLevels.current = [70, 30].map((price) => rsi.current!.createPriceLine({ price, color: String(t.rsiLevels), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" }));
      }
      rsi.current.setData(r.points.map((p: any) => ({ time: TT(p.time), value: p.value })));
    } else if (rsi.current) {
      c.removeSeries(rsi.current);
      rsi.current = null;
      rsiLevels.current = [];
    }
    const m = d.indicators?.panels?.macd;
    if (o.showMacd && m) {
      if (!macd.current) {
        const pane = rsi.current ? 2 : 1;
        const hist = c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
        const line = c.addSeries(LineSeries, { color: String(t.macd), lineWidth: 1, priceLineVisible: false,
          title: `MACD(${m.params.fast},${m.params.slow},${m.params.signal} ${m.signal_ma})${m.visual_only ? "*" : ""}` }, pane);
        const sig = c.addSeries(LineSeries, { color: String(t.macdSignal), lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, pane);
        macd.current = { line, sig, hist };
      }
      macd.current.hist.setData(m.histogram.map((p: any) => ({ time: TT(p.time), value: p.value, color: String(p.value >= 0 ? t.macdUp : t.macdDown) })));
      macd.current.line.setData(m.line.map((p: any) => ({ time: TT(p.time), value: p.value })));
      macd.current.sig.setData(m.signal.map((p: any) => ({ time: TT(p.time), value: p.value })));
    } else if (macd.current) {
      c.removeSeries(macd.current.line);
      c.removeSeries(macd.current.sig);
      c.removeSeries(macd.current.hist);
      macd.current = null;
    }
    const panes = c.panes();
    for (let i = panes.length - 1; i >= 1; i--) if (panes[i].getSeries().length === 0) c.removePane(i);
    c.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 3.2 : 1));
    // structure overlays
    const ov = d.overlays || {};
    const mk: SeriesMarker<Time>[] = [];
    if (o.showStructure) {
      for (const b of ov.breaks || []) {
        mk.push({ time: TT(b.bar_open_utc), position: b.direction === "BULLISH" ? "belowBar" : "aboveBar",
          shape: "circle", color: String(b.kind === "BOS" ? t.bos : t.choch),
          text: b.kind === "STRUCTURE_BREAK_UNCLASSIFIED" ? "BRK" : b.kind, size: 0.6 });
      }
      for (const w of ov.sweeps || []) mk.push({ time: TT(w.observed_at), position: w.side === "BSL" ? "aboveBar" : "belowBar", shape: "circle", color: String(t.sweep), text: "SWP", size: 0.5 });
    }
    const first = newTimes.length ? newTimes[0] : 0;
    baseMarkers.current = mk.filter((x) => (x.time as number) >= first);
    setAllMarkers();
    zones.current?.setZones(o.showZones ? [
      ...(ov.fvgs || []).slice(-6).map((f: any) => {
        const col = String(f.direction === "BULLISH" ? t.fvgBull : t.fvgBear);
        return { from: TT(f.formed_at) as number, low: f.low, high: f.high, color: col, border: withAlpha(col, 0.55), label: `FVG ${f.status === "PARTIAL" ? Math.round(f.mitigated * 100) + "%" : ""}` };
      }),
      ...(ov.order_blocks || []).slice(-3).map((ob: any) => ({ from: TT(ob.confirmed_at) as number, low: ob.low, high: ob.high, color: String(t.ob), border: withAlpha(String(t.ob), 0.5), label: "OB?" })),
    ] : []);
    paintVol(d.volatility, o.showVol !== false, TT);
    if (isNewData || !initialized.current) restoreView(prevTimes, prevLogical, newTimes);
    else if (prevLogical) ts.setVisibleLogicalRange(prevLogical);
  };

  /** Daily volatility levels (backend engine/volzones.py): IV wall zones + reference price lines. Never changes the scale. */
  const paintVol = (v: any, show: boolean, TT: (iso: string) => Time) => {
    const ser = candles.current;
    if (!ser) return;
    const t = tkRef.current;
    volLines.current.forEach((p) => ser.removePriceLine(p));
    volLines.current = [];
    if (!show || !v || v.status !== "OK") { volZones.current?.setZones([]); return; }
    volZones.current?.setZones((v.zones || []).map((z: any) => {
      const col = String(z.side === "UP" ? t.ivWallUp : t.ivWallDown);
      return { from: z.from_utc ? (TT(z.from_utc) as number) : 0, low: z.low, high: z.high, color: col, border: withAlpha(col, 0.7), label: z.label };
    }));
    const style: Record<string, [string, LineStyle, number]> = {
      DAILY_OPEN: ["dailyOpen", LineStyle.Solid, 1], EXPECTED_HIGH: ["expectedHL", LineStyle.Dashed, 2], EXPECTED_LOW: ["expectedHL", LineStyle.Dashed, 2],
      STRADDLE_BE: ["straddleBe", LineStyle.Dotted, 1], PDH: ["pdhl", LineStyle.SparseDotted, 1], PDL: ["pdhl", LineStyle.SparseDotted, 1],
      DAY_HIGH: ["dayHL", LineStyle.LargeDashed, 1], DAY_LOW: ["dayHL", LineStyle.LargeDashed, 1],
    };
    for (const ln of v.lines || []) {
      const st = style[ln.kind];
      if (!st || ln.price == null) continue;
      volLines.current.push(ser.createPriceLine({ price: ln.price, color: String(t[st[0]]), title: ln.label, lineStyle: st[1], lineWidth: st[2] as 1 | 2,
        axisLabelVisible: ln.kind !== "STRADDLE_BE" }));
    }
  };

  useEffect(() => {
    if (data) paint(data, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, opts.showRsi, opts.showMacd, opts.showStructure, opts.showZones, opts.showVol, shift]);

  const setAllMarkers = () => {
    const first = times.current.length ? times.current[0] : 0;
    const all = [...baseMarkers.current, ...structMarkers.current].filter((x) => (x.time as number) >= first)
      .sort((a, b) => (a.time as number) - (b.time as number));
    markers.current?.setMarkers(all);
  };

  // ---------------------------------------------------------------- 1.10 structure layers (engine facts only, read-only)
  useEffect(() => {
    if (!opts.showPatterns) { setStructure(null); return; }
    let alive = true;
    apiGet(`/api/v1/structure?tf=${tf}`).then((r) => alive && setStructure(r)).catch(() => alive && setStructure(null));
    return () => { alive = false; };
  }, [tf, opts.showPatterns, s.analysisSeq]);

  useEffect(() => {
    const ser = candles.current;
    if (!ser) return;
    const t = tkRef.current;
    const TT = (iso: string) => (epochSec(iso) + shiftRef.current) as Time;
    structLines.current.forEach((p) => ser.removePriceLine(p));
    structLines.current = [];
    structMarkers.current = [];
    const st = structure;
    if (!opts.showPatterns || !st || st.status !== "OK") { structZones.current?.setZones([]); setAllMarkers(); return; }
    const zs: any[] = [];
    const w = st.walls || {};
    if (w.status === "OK") {
      const src = w.source_type === "HV_PROXY" ? "HV-proxy" : w.source_type === "IV_IMPORT" ? "IV (import)" : w.source_type === "IV_MANUAL" ? "IV (ręczna)" : w.source_type;
      for (const x of w.walls || []) {
        const col = String(x.side === "UPPER" ? t.ivWallUp : t.ivWallDown);
        zs.push({ from: TT(w.anchor_time) as number, low: x.low, high: x.high, color: col, border: withAlpha(col, 0.8),
          label: `${src} wall ${x.side === "UPPER" ? "+" : "−"}${x.k}σ (v${w.snapshot_version ?? 1})` });
      }
    }
    const rg = st.range || {};
    if (rg.status === "OK" && ["M1", "M5", "M15"].includes(tf)) {
      const col = String(t.entry);
      zs.push({ from: TT(rg.start_utc) as number, low: rg.bottom, high: rg.top, color: withAlpha(col, 0.08), border: withAlpha(col, 0.6),
        label: `zakres M5 (zamrożony ${rg.state === "INSIDE" ? "" : "– " + rg.state})` });
      const rz = st.range_zones || {};
      for (const [k, z] of [["dolna", rz.lower], ["górna", rz.upper]] as const) {
        if (z) zs.push({ from: TT(rg.start_utc) as number, low: z.low, high: z.high, color: withAlpha(col, 0.18), border: col, label: `strefa M1 ${k}` });
      }
    }
    structZones.current?.setZones(zs);
    for (const p of (st.chart?.patterns || []).filter((x: any) => x.state === "FORMING" || x.state === "CONFIRMED").slice(0, 3)) {
      const b = p.boundary || {};
      const lv = b.neckline ?? b.level ?? null;
      const label = `${p.type} (${p.state === "CONFIRMED" ? "potwierdzona" : "potencjalna"})`;
      const add = (price: number | null | undefined, title: string) => price != null && structLines.current.push(ser.createPriceLine({ price, color: String(t.choch),
        title, lineStyle: p.state === "CONFIRMED" ? LineStyle.Solid : LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false }));
      if (lv != null) add(lv, label);
      else { add(b.upper, label + " ↑"); add(b.lower, label + " ↓"); }
      if (p.confirm_bar) structMarkers.current.push({ time: TT(p.confirm_bar), position: p.direction_if_confirmed === "SHORT" ? "aboveBar" : "belowBar",
        shape: p.direction_if_confirmed === "SHORT" ? "arrowDown" : "arrowUp", color: String(t.choch), text: p.type.slice(0, 10), size: 0.8 });
    }
    for (const pv of (st.pivots || []).slice(-16)) {
      structMarkers.current.push({ time: TT(pv.t), position: pv.kind === "H" ? "aboveBar" : "belowBar", shape: "circle", color: String(t.sweep), text: "P", size: 0.4 });
      structMarkers.current.push({ time: TT(pv.known_at), position: pv.kind === "H" ? "aboveBar" : "belowBar", shape: "square", color: withAlpha(String(t.sweep), 0.5),
        text: "znany", size: 0.3 });
    }
    for (const ev of (st.candles?.evidence || []).filter((e: any) => e.direction !== "NEUTRAL").slice(-6)) {
      structMarkers.current.push({ time: TT(ev.bar), position: ev.direction === "SHORT" ? "aboveBar" : "belowBar", shape: "circle",
        color: String(ev.direction === "SHORT" ? t.tp : t.entry), text: ev.members[0].slice(0, 8), size: 0.5 });
    }
    setAllMarkers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structure, opts.showPatterns, data, shift]);

  // ---------------------------------------------------------------- PMW-UPD-02: SAR points + IQ levels (backend values only)
  useEffect(() => {
    if (!opts.showSar && !opts.showExtInd) { setIndCtx(null); return; }
    let alive = true;
    apiGet(`/api/v1/indicator-context/chart?tf=${tf}`).then((r) => alive && setIndCtx(r)).catch(() => alive && setIndCtx(null));
    return () => { alive = false; };
  }, [tf, opts.showSar, opts.showExtInd, s.analysisSeq]);

  useEffect(() => {
    const c = chart.current, ser = candles.current;
    if (!c || !ser) return;
    const TT = (iso: string) => (epochSec(iso) + shiftRef.current) as Time;
    if (sarSeries.current && (!opts.showSar || !indCtx?.sar)) { try { c.removeSeries(sarSeries.current); } catch { /* chart gone */ } sarSeries.current = null; }
    if (opts.showSar && indCtx?.sar?.points?.length) {
      if (!sarSeries.current) sarSeries.current = c.addSeries(LineSeries, { color: String(tkRef.current.choch), lineVisible: false, pointMarkersVisible: true,
        pointMarkersRadius: 1.6, priceLineVisible: false, lastValueVisible: false, title: `SAR ${indCtx.sar.params.step}/${indCtx.sar.params.max}` });
      const seen = new Set<number>();
      sarSeries.current.setData(indCtx.sar.points.filter((p: any) => p.t).map((p: any) => ({ time: TT(p.t), value: p.sar }))
        .filter((p: any) => !seen.has(p.time as number) && seen.add(p.time as number)));
    }
    extLines.current.forEach((p) => ser.removePriceLine(p));
    extLines.current = [];
    if (opts.showExtInd) for (const lv of indCtx?.ext_levels || [])
      extLines.current.push(ser.createPriceLine({ price: lv.price, color: String(tkRef.current.sweep), title: lv.title, lineStyle: LineStyle.Dashed,
        lineWidth: 1, axisLabelVisible: false }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indCtx, opts.showSar, opts.showExtInd, data, shift]);

  // ---------------------------------------------------------------- PMW-UPD-06: session sweep boxes (same box ids on every TF)
  useEffect(() => {
    if (!opts.showSessions) { setSessions(null); return; }
    let alive = true;
    apiGet(`/api/v1/liquidity/sessions?tf=${tf}`).then((r) => alive && setSessions(r)).catch(() => alive && setSessions(null));
    return () => { alive = false; };
  }, [tf, opts.showSessions, s.analysisSeq]);

  useEffect(() => {
    const pr = sessBoxes.current;
    if (!pr) return;
    if (!opts.showSessions || !sessions?.boxes) { pr.set([]); return; }
    const TT = (iso: string) => epochSec(iso) + shiftRef.current;
    const t: any = tkRef.current;
    const boxes: BoundedBox[] = [];
    const marks: BoxMarker[] = [];
    const nowT = (times.current[times.current.length - 1] ?? 0) + 60;
    for (const b of sessions.boxes) {
      const from = TT(b.start_utc), to = TT(b.end_utc);
      if (b.state === "FINAL") {
        boxes.push({ from, to, low: b.final_low, high: b.final_high, color: "rgba(212,160,23,0.08)", border: String(t.sweep ?? "#d4a017"),
          label: `${b.session} FINAL (znany ${String(b.known_at).slice(11, 16)} UTC)` });
        const edgeEnd = (e: string) => { const ev = (b.events || []).find((x: any) => x.edge === e || x.edge === "BOTH"); return ev ? TT(ev.bar_open_utc) : Math.min(TT(b.expires_at), nowT); };
        boxes.push({ from: TT(b.known_at), to: edgeEnd("HIGH"), low: b.final_high, high: b.final_high, color: "", border: String(t.sweep ?? "#d4a017"), dashed: true });
        boxes.push({ from: TT(b.known_at), to: edgeEnd("LOW"), low: b.final_low, high: b.final_low, color: "", border: String(t.sweep ?? "#d4a017"), dashed: true });
        for (const e of b.events || []) {
          const up = e.kind === "SWEEP_HIGH" || e.kind === "BREAKOUT_UP";
          marks.push({ time: TT(e.bar_open_utc), price: up ? e.high : e.low, up: !up, color: e.kind.startsWith("SWEEP") ? "#e0a030" : "#7aa7ff",
            label: `${e.kind} ${b.session} (potw. ${String(e.confirmed_at).slice(11, 16)})` });
        }
      } else if (b.state === "DEVELOPING") {
        boxes.push({ from, to: Math.min(to, nowT), low: b.developing_low, high: b.developing_high, color: "rgba(150,150,150,0.06)", border: "#999",
          dashed: true, label: `${b.session} w trakcie` });
      } else if (b.state === "INCOMPLETE") {
        boxes.push({ from, to, low: b.observed_low, high: b.observed_high, color: "rgba(150,150,150,0.04)", border: "#777", dashed: true,
          label: `${b.session} NIEPEŁNY (${b.observed_slots}/${b.expected_slots})` });
      }
    }
    pr.set(boxes, marks);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, opts.showSessions, data, shift]);

  // ---------------------------------------------------------------- PMW zone map (UZICE): backend values only, drawn from the moment of
  // confirmation (a provisional zone from its creation, dashed and labelled "PROW."); the panel never recomputes zones.
  useEffect(() => {
    if (!opts.showZoneMap) { setZoneMap(null); return; }
    let alive = true;
    const ztf = tf === "M5" || tf === "M15" ? tf : "ALL";
    apiGet(`/api/v1/zones/map?tf=${ztf}`).then((r) => alive && setZoneMap(r)).catch(() => alive && setZoneMap(null));
    return () => { alive = false; };
  }, [tf, opts.showZoneMap, s.analysisSeq]);

  useEffect(() => {
    const pr = zmBoxes.current;
    if (!pr) return;
    if (!opts.showZoneMap || zoneMap?.status !== "OK") { pr.set([]); return; }
    const TT = (iso: string) => epochSec(iso) + shiftRef.current;
    const nowT = (times.current[times.current.length - 1] ?? 0) + 60;
    const boxes: BoundedBox[] = [];
    for (const z of zoneMap.zones || []) {
      const from = TT(z.confirmed_at || z.created_at);
      const col = z.polarity === "HIGH" ? "#d9534f" : "#3a9d6b";
      boxes.push({ from, to: nowT, low: z.lower_price, high: z.upper_price, color: withAlpha(col, z.provisional ? 0.04 : 0.09), border: col,
        dashed: !!z.provisional, label: zoneLabel(z) });
    }
    const prof = (p: any, dev: boolean) => {
      if (!p || p.poc == null) return;
      const from = TT(dev ? p.start : p.end);
      for (const [k, v] of [["POC", p.poc], ["VAH", p.vah], ["VAL", p.val]] as [string, number][])
        if (v != null) boxes.push({ from, to: nowT, low: v, high: v, color: "", border: k === "POC" ? "#8a6dd8" : "#6d8ad8", dashed: dev,
          label: `${dev ? "rozw. " : ""}${k} ${p.session ?? ""}`.trim() });
    };
    prof(zoneMap.profile_last_completed, false);
    prof(zoneMap.profile_developing, true);
    pr.set(boxes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoneMap, opts.showZoneMap, data, shift]);

  // ---------------------------------------------------------------- AI levels (marked "AI:" - never merged with the engine plan)
  useEffect(() => {
    const ser = candles.current;
    if (!ser) return;
    aiLines.current.forEach((p) => ser.removePriceLine(p));
    aiLines.current = [];
    if (!aiLevels || opts.showAiLevels === false) return;
    const col = String(tk.choch);
    const add = (price: number | null | undefined, title: string) => price != null && aiLines.current.push(ser.createPriceLine({ price, color: col, title,
      lineStyle: LineStyle.SparseDotted, lineWidth: 1, axisLabelVisible: true }));
    if (aiLevels.zone) { add(aiLevels.zone[0], "AI: strefa"); add(aiLevels.zone[1], ""); }
    add(aiLevels.invalidation, "AI: unieważnienie");
    (aiLevels.targets || []).forEach((x, i) => add(x, `AI: cel ${i + 1}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(aiLevels), opts.showAiLevels, data]);

  // ---------------------------------------------------------------- "Pokaż na wykresie" highlight from the setup page
  useEffect(() => {
    const ser = candles.current;
    if (!ser) return;
    hlLines.current.forEach((p) => ser.removePriceLine(p));
    hlLines.current = [];
    if (highlight && highlight.price != null)
      hlLines.current.push(ser.createPriceLine({ price: highlight.price, color: String(tk.chartCrosshair), title: "▶ " + highlight.label, lineStyle: LineStyle.Solid,
        lineWidth: 2, axisLabelVisible: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlight?.price, highlight?.label, data]);

  // ---------------------------------------------------------------- execution levels (existing values only; never touches the scale)
  useEffect(() => {
    const ser = candles.current;
    if (!ser) return;
    priceLines.current.forEach((p) => ser.removePriceLine(p));
    priceLines.current = [];
    const d = s.decision;
    const lv = d?.levels;
    const st = d?.setup;
    const add = (price: number, color: string, title: string, style = LineStyle.Dashed) =>
      price != null && priceLines.current.push(ser.createPriceLine({ price, color, title, lineStyle: style, lineWidth: 1, axisLabelVisible: true }));
    if (!lv || !st || !["EARLY_SETUP", "EARLY", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED"].includes(st.state)) return;
    add(lv.stop_loss, String(tk.sl), "Plan bota: SL");
    (lv.targets || []).forEach((t: any, i: number) => add(t.price, String(tk.tp), `Plan bota: TP${i + 1}${st.state !== "CONFIRMED" ? " (scen.)" : ""}`));
    if (lv.entry_zone) {
      add(lv.entry_zone.high, String(tk.entry), "strefa wejścia", LineStyle.Dotted);
      add(lv.entry_zone.low, String(tk.entry), "", LineStyle.Dotted);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.decision?.levels, s.decision?.setup?.state, data, tk.sl, tk.tp, tk.entry]);

  // ---------------------------------------------------------------- live ticks: update() only (LWC shifts only when the last bar is visible)
  useEffect(() => {
    const tick = s.barTick?.[tf];
    if (!tick || !candles.current || !volume.current || !tick.bar.open_utc) return;
    const b = tick.bar;
    const t = T(b.open_utc) as number;
    const ts = times.current;
    if (ts.length && t < ts[ts.length - 1]) return;
    if (!ts.length || t > ts[ts.length - 1]) times.current = [...ts, t];
    candles.current.update({ time: t as Time, open: b.o, high: b.h, low: b.l, close: b.c,
      ...(b.closed ? {} : { color: String(b.c >= b.o ? tk.formingUp : tk.formingDown) }) });
    volume.current.update({ time: t as Time, value: b.tv, color: String(b.c >= b.o ? tk.volUp : tk.volDown) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.barTick?.[tf]]);

  useEffect(() => {
    if (!fullscreen) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onFullscreen(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [fullscreen, onFullscreen]);

  // ---------------------------------------------------------------- per-panel controls
  const zoom = (factor: number) => {
    const c = chart.current;
    const r = c?.timeScale().getVisibleLogicalRange();
    if (!c || !r) return;
    markUser();
    const w = Math.max(10, (r.to - r.from) * factor);
    if (view.current.follow) c.timeScale().setVisibleLogicalRange({ from: r.to - w, to: r.to });
    else {
      const mid = (r.from + r.to) / 2;
      c.timeScale().setVisibleLogicalRange({ from: mid - w / 2, to: mid + w / 2 });
    }
  };
  const fit = () => { markUser(); chart.current?.timeScale().fitContent(); };
  const latest = () => {
    const c = chart.current;
    if (!c) return;
    markUser();
    const n = times.current.length;
    const r = c.timeScale().getVisibleLogicalRange();
    const w = r ? r.to - r.from : 150;
    c.timeScale().setVisibleLogicalRange({ from: n - 1 - w + 6, to: n - 1 + 6 });
    setView({ follow: true });
  };
  const toggleAuto = () => {
    const v = !view.current.autoScale;
    chart.current?.priceScale("right").applyOptions({ autoScale: v });
    setView({ autoScale: v });
  };
  const setGroup = (g: SyncGroup) => setView({ group: g });

  const q = data?.quality;
  const qStatus = q?.status;
  const stale = s.connection?.state !== "CONNECTED" || (s.decision && s.decision.data_quality === "BAD");
  const last = data?.bars?.length ? data.bars[data.bars.length - 1] : null;
  const role = data?.indicators?.role;
  const lastClosed = data?.bars?.filter((b: any) => b.closed).slice(-1)[0];
  const freshS = lastClosed?.open_utc ? Math.max(0, Math.round((Date.now() - Date.parse(lastClosed.open_utc)) / 1000)) : null;
  return (
    <div className={cls("panel chart-panel", fullscreen && "fullscreen", variant && "cv-" + variant, isMain && "is-main")} data-chart-id={chartId} data-tf={tf}
      data-needed={needed == null ? undefined : needed ? "1" : "0"}>
      <div className="panel-head">
        <span className="ptf">{tf}</span>
        <span className="ptitle">{symbol}</span>
        <span className="psub" title="rola interwału z rejestru TF backendu">{roleText ?? (role ? ROLE_PL[role] ?? role.toLowerCase().replace(/_/g, " ") : "MT5")}</span>
        {needed && <span className="badge ok" title="interwał wymagany przez strategię wybranego setupu">wymagany</span>}
        {freshS != null && <span className="badge muted" title="czas od otwarcia ostatniej zamkniętej świecy">{freshS < 3600 ? `${Math.round(freshS / 60)} min` : `${Math.round(freshS / 3600)} h`}</span>}
        <span className={cls("badge", qStatus === "OK" ? "ok" : qStatus ? "warn" : "muted")} title={(q?.reasons || []).join(", ") || ""}>
          {qStatus === "INSUFFICIENT_HISTORY" ? `WARMING_UP ${q.closed_bars}/${q.required}` : qStatus ?? "…"}
        </span>
        {stale && <span className="badge bad">STALE</span>}
        <span className="spacer" />
        <span className="legend">
          {legend ? `O ${fmtNum(legend.o)} H ${fmtNum(legend.h)} L ${fmtNum(legend.l)} C ${fmtNum(legend.c)}` : last ? `${fmtNum(last.c)}` : ""}
        </span>
      </div>
      <div className="chart-tools" role="toolbar" aria-label={`Sterowanie wykresem ${index}`}>
        <button className="icon" data-act="zoom-in" title="Przybliż (tylko ten wykres)" onClick={() => zoom(0.75)}>+</button>
        <button className="icon" data-act="zoom-out" title="Oddal (tylko ten wykres)" onClick={() => zoom(1.35)}>−</button>
        <button className="icon" data-act="fit" title="Dopasuj – pokaż wszystkie świece" onClick={fit}>Dopasuj</button>
        <button className={cls("icon", viewUi.follow && "on")} data-act="latest" title="Do najnowszej świecy (wznawia śledzenie)" onClick={latest}>⇥ Najnowsza</button>
        <button className={cls("icon", viewUi.autoScale && "on")} data-act="autoscale" title="Automatyczna skala ceny (oś Y)" onClick={toggleAuto}>A</button>
        <select value={viewUi.group} onChange={(e) => setGroup(e.target.value as SyncGroup)} title="Synchronizacja zakresu czasu tylko w wybranej grupie (domyślnie brak)">
          <option value="">bez sync</option><option value="A">grupa A</option><option value="B">grupa B</option>
        </select>
        <span className="spacer" />
        {!viewUi.follow && <span className="badge muted" title="Widok ręczny – nowe świece nie przesuwają wykresu">widok ręczny</span>}
        {onMain && !isMain && <button className="icon" data-act="main" title="Przenieś ten interwał na wykres główny" onClick={onMain}>Wykres główny</button>}
        <button className="icon" data-act="fullscreen" title={fullscreen ? "Zamknij pełny ekran (Esc)" : "Pełny ekran"} aria-label={fullscreen ? "Zamknij pełny ekran" : "Pełny ekran"} onClick={onFullscreen}>{fullscreen ? "✕" : "⤢"}</button>
      </div>
      <div className="chart-box" ref={box} />
      {err && <div className="chart-msg bad">Błąd danych: {err}</div>}
      {!err && data && data.bars?.length === 0 && <div className="chart-msg">Brak świec z MT5 – {q?.fix_hint || "sprawdź połączenie z terminalem"}</div>}
      {q?.fix_hint && data?.bars?.length > 0 && qStatus === "INSUFFICIENT_HISTORY" && <div className="chart-hint">{q.fix_hint}</div>}
      {opts.showZoneMap && zoneMap && zoneMap.status === "OK" && zoneMap.data?.state !== "OK" &&
        <div className="chart-hint" title={(zoneMap.data?.reasons || []).join(", ")}>Mapa stref: dane {zoneMap.data?.state} – strefy tylko informacyjnie</div>}
      {opts.showZoneMap && zoneTip && <div className="chart-ztip">{zoneTip}</div>}
    </div>
  );
}

/** Text label of a unified zone: type, TFs, status and score - the provisional state is spelled out, not only shown by the dash. */
function zoneLabel(z: any): string {
  const tfs = (z.timeframes || []).join("/");
  return `${z.provisional ? "PROW. " : ""}${z.zone_type} ${tfs} ${z.status} ${z.confluence_score}`;
}

/** Tooltip of the zones under the cursor price (values from the backend map; score 0-100 is not a probability). */
function zoneTipAt(zm: any, price: number | null): string | null {
  if (!zm || zm.status !== "OK" || price == null) return null;
  const hit = (zm.zones || []).filter((z: any) => price >= z.lower_price && price <= z.upper_price);
  if (!hit.length) return null;
  return hit.slice(0, 3).map((z: any) => {
    const rm = z.reaction_metrics || {};
    const fl = (z.flags || []).length ? ` [${z.flags.join(",")}]` : "";
    return `${zoneLabel(z)} | ${fmtNum(z.lower_price)}–${fmtNum(z.upper_price)} | testy ${rm.retests ?? 0}${rm.swept ? ", sweep" : ""}`
      + ` | ${z.confirmed_at ? "potw. " + String(z.confirmed_at).slice(11, 16) : "niepotwierdzona"} | wolumen: ${(zm.volume_source || {}).source ?? "?"}${fl}`;
  }).join("  ·  ") + "  (wynik nie jest prawdopodobieństwem)";
}
