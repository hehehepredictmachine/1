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
import { ZonesPrimitive } from "../zones";

export interface ChartOpts {
  showRsi: boolean;
  showMacd: boolean;
  showStructure: boolean;
  showZones: boolean;
  showVol: boolean;
  syncCrosshair: boolean;
  tz: TimeZoneMode;
}

const withAlpha = (c: string, a: number) => {
  const p = parseColor(c);
  return p ? toHex({ ...p, a }) : c;
};

declare global {
  interface Window { __mqCharts?: Record<string, any> }
}

export default function ChartPanel({ tf, index, opts, onFullscreen, fullscreen }: {
  tf: string;
  index: number;
  opts: ChartOpts;
  onFullscreen: () => void;
  fullscreen: boolean;
}) {
  const { s } = useStore();
  const theme = useTheme();
  const chartId = `panel${index}`;
  const symbol = s.symbol?.symbol ?? "XAUUSD-";
  const vkey = viewKey(chartId, symbol, tf);
  const tk: Tokens = theme.chartTokens(chartId);
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
      lines.current = new Map();
      rsi.current = null;
      rsiLevels.current = [];
      macd.current = null;
      priceLines.current = [];
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
      if (m.src === chartId || !c || !candles.current) return;
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
    markers.current?.setMarkers(mk.filter((x) => (x.time as number) >= first).sort((a, b) => (a.time as number) - (b.time as number)));
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
    add(lv.stop_loss, String(tk.sl), "SL");
    (lv.targets || []).forEach((t: any, i: number) => add(t.price, String(tk.tp), `TP${i + 1}${st.state !== "CONFIRMED" ? " (scen.)" : ""}`));
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
  return (
    <div className={cls("panel chart-panel", fullscreen && "fullscreen")} data-chart-id={chartId} data-tf={tf}>
      <div className="panel-head">
        <span className="pnum">{index}</span>
        <span className="ptitle">{symbol}</span>
        <span className="ptf">{tf}</span>
        <span className="psub">MT5{role ? ` · ${role}` : ""}</span>
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
        <button className="icon" title={fullscreen ? "Zamknij pełny ekran" : "Pełny ekran"} onClick={onFullscreen}>{fullscreen ? "✕" : "⤢"}</button>
      </div>
      <div className="chart-box" ref={box} />
      {err && <div className="chart-msg bad">Błąd danych: {err}</div>}
      {!err && data && data.bars?.length === 0 && <div className="chart-msg">Brak świec z MT5 – {q?.fix_hint || "sprawdź połączenie z terminalem"}</div>}
      {q?.fix_hint && data?.bars?.length > 0 && qStatus === "INSUFFICIENT_HISTORY" && <div className="chart-hint">{q.fix_hint}</div>}
    </div>
  );
}
