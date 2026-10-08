import { useEffect, useMemo, useRef, useState } from "react";
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
import { useStore } from "../store";
import { chartShift, cls, epochSec, fmtNum, type TimeZoneMode } from "../util";
import { ZonesPrimitive } from "../zones";

const LINE_COLORS = ["#f5d76e", "#4dd0ff", "#c792ea", "#ff9f43", "#9cff57", "#ff6b9a"];
const UP = "#16e07a";
const DOWN = "#ff4d5e";

// cross-chart synchronisation (crosshair & visible range by *time*)
type SyncMsg = { src: string; kind: "crosshair" | "range"; time?: number | null; from?: number; to?: number };
const SYNC = new EventTarget();

export interface ChartOpts {
  showRsi: boolean;
  showMacd: boolean;
  showStructure: boolean;
  showZones: boolean;
  sync: boolean;
  tz: TimeZoneMode;
}

export default function ChartPanel({ tf, index, opts, onFullscreen, fullscreen }: {
  tf: string;
  index: number;
  opts: ChartOpts;
  onFullscreen: () => void;
  fullscreen: boolean;
}) {
  const { s } = useStore();
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const lines = useRef<ISeriesApi<"Line">[]>([]);
  const rsi = useRef<ISeriesApi<"Line"> | null>(null);
  const macd = useRef<{ line: ISeriesApi<"Line">; sig: ISeriesApi<"Line">; hist: ISeriesApi<"Histogram"> } | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const zones = useRef<ZonesPrimitive | null>(null);
  const priceLines = useRef<IPriceLine[]>([]);
  const lastBarTime = useRef<number>(0);
  const [data, setData] = useState<any>(null);
  const [legend, setLegend] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const id = useMemo(() => `${tf}-${index}`, [tf, index]);
  const offset = s.connection?.clock?.offset_seconds ?? null;
  const shift = chartShift(opts.tz, offset);
  const T = (iso: string) => (epochSec(iso) + shift) as Time;

  // ---------------------------------------------------------------- create chart
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#8fd8ad", fontSize: 10,
        attributionLogo: true, panes: { separatorColor: "#0f3d24", separatorHoverColor: "#1f7a46" } },
      grid: { vertLines: { color: "rgba(40,255,140,0.05)" }, horzLines: { color: "rgba(40,255,140,0.06)" } },
      rightPriceScale: { borderColor: "#124d2c" },
      timeScale: { borderColor: "#124d2c", timeVisible: true, secondsVisible: false, rightOffset: 6 },
      crosshair: { mode: CrosshairMode.Normal },
    });
    chart.current = c;
    candles.current = c.addSeries(CandlestickSeries, { upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN, priceLineColor: "#7dffb6" });
    volume.current = c.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    c.priceScale("right").applyOptions({ scaleMargins: { top: 0.05, bottom: 0.12 } });
    zones.current = new ZonesPrimitive();
    candles.current.attachPrimitive(zones.current);
    markers.current = createSeriesMarkers(candles.current, []);
    c.subscribeCrosshairMove((p) => {
      if (!p.time || !candles.current) {
        setLegend(null);
      } else {
        const b: any = p.seriesData.get(candles.current);
        setLegend(b ? { o: b.open, h: b.high, l: b.low, c: b.close } : null);
      }
      if (opts.sync && p.sourceEvent) SYNC.dispatchEvent(new CustomEvent("sync", { detail: { src: id, kind: "crosshair", time: (p.time as number) ?? null } as SyncMsg }));
    });
    c.timeScale().subscribeVisibleTimeRangeChange((r) => {
      if (!r || !syncing.current.allow) return;
      if (optsRef.current.sync)
        SYNC.dispatchEvent(new CustomEvent("sync", { detail: { src: id, kind: "range", from: r.from as number, to: r.to as number } as SyncMsg }));
    });
    return () => {
      c.remove();
      chart.current = null;
      lines.current = [];
      rsi.current = null;
      macd.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tf]);

  const optsRef = useRef(opts);
  optsRef.current = opts;
  const syncing = useRef({ allow: true });

  // receive sync messages
  useEffect(() => {
    const h = (e: Event) => {
      const m = (e as CustomEvent).detail as SyncMsg;
      if (m.src === id || !optsRef.current.sync || !chart.current || !candles.current) return;
      if (m.kind === "crosshair") {
        if (m.time == null) chart.current.clearCrosshairPosition();
        else {
          const bars = data?.bars || [];
          // nearest bar at or before the time
          let best: any = null;
          for (let i = bars.length - 1; i >= 0; i--) {
            if (epochSec(bars[i].open_utc) + shift <= m.time) { best = bars[i]; break; }
          }
          if (best) chart.current.setCrosshairPosition(best.c, T(best.open_utc), candles.current);
        }
      } else if (m.kind === "range" && m.from && m.to) {
        syncing.current.allow = false;
        try {
          chart.current.timeScale().setVisibleRange({ from: m.from as Time, to: m.to as Time });
        } catch {
          /* range outside data */
        }
        setTimeout(() => (syncing.current.allow = true), 50);
      }
    };
    SYNC.addEventListener("sync", h);
    return () => SYNC.removeEventListener("sync", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, data, shift]);

  // ---------------------------------------------------------------- data load
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

  // ---------------------------------------------------------------- render data
  useEffect(() => {
    const c = chart.current;
    if (!c || !data || !candles.current || !volume.current) return;
    const bars = (data.bars || []).filter((b: any) => b.open_utc);
    candles.current.setData(bars.map((b: any) => ({ time: T(b.open_utc), open: b.o, high: b.h, low: b.l, close: b.c,
      ...(b.closed ? {} : { color: b.c >= b.o ? "rgba(22,224,122,0.45)" : "rgba(255,77,94,0.45)" }) })));
    volume.current.setData(bars.map((b: any) => ({ time: T(b.open_utc), value: b.tv, color: b.c >= b.o ? "rgba(22,224,122,0.28)" : "rgba(255,77,94,0.28)" })));
    lastBarTime.current = bars.length ? (T(bars[bars.length - 1].open_utc) as number) : 0;
    // indicator lines
    lines.current.forEach((l) => c.removeSeries(l));
    lines.current = [];
    (data.indicators?.lines || []).forEach((ln: any, i: number) => {
      const ser = c.addSeries(LineSeries, { color: LINE_COLORS[i % LINE_COLORS.length], lineWidth: 1, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false, title: ln.label });
      ser.setData(ln.points.map((p: any) => ({ time: T(p.time), value: p.value })));
      lines.current.push(ser);
    });
    // RSI / MACD panes
    if (rsi.current) { c.removeSeries(rsi.current); rsi.current = null; }
    if (macd.current) { c.removeSeries(macd.current.line); c.removeSeries(macd.current.sig); c.removeSeries(macd.current.hist); macd.current = null; }
    let pane = 1;
    if (opts.showRsi && data.indicators?.panels?.rsi) {
      const r = data.indicators.panels.rsi;
      rsi.current = c.addSeries(LineSeries, { color: "#c792ea", lineWidth: 1, priceLineVisible: false, title: `RSI(${r.period})${r.visual_only ? "*" : ""}` }, pane);
      rsi.current.setData(r.points.map((p: any) => ({ time: T(p.time), value: p.value })));
      rsi.current.createPriceLine({ price: 70, color: "#3b6b50", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
      rsi.current.createPriceLine({ price: 30, color: "#3b6b50", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
      pane++;
    }
    if (opts.showMacd && data.indicators?.panels?.macd) {
      const m = data.indicators.panels.macd;
      const hist = c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      hist.setData(m.histogram.map((p: any) => ({ time: T(p.time), value: p.value, color: p.value >= 0 ? "rgba(22,224,122,0.6)" : "rgba(255,77,94,0.6)" })));
      const line = c.addSeries(LineSeries, { color: "#4dd0ff", lineWidth: 1, priceLineVisible: false, title: `MACD(${m.params.fast},${m.params.slow},${m.params.signal} ${m.signal_ma})${m.visual_only ? "*" : ""}` }, pane);
      line.setData(m.line.map((p: any) => ({ time: T(p.time), value: p.value })));
      const sig = c.addSeries(LineSeries, { color: "#ff9f43", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }, pane);
      sig.setData(m.signal.map((p: any) => ({ time: T(p.time), value: p.value })));
      macd.current = { line, sig, hist };
      pane++;
    }
    const panes = c.panes();
    for (let i = panes.length - 1; i >= pane; i--) c.removePane(i);
    // proportional pane heights (independent of the container size at render time)
    c.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 3.2 : 1));
    // structure overlays
    const ov = data.overlays || {};
    const mk: SeriesMarker<Time>[] = [];
    if (opts.showStructure) {
      for (const b of ov.breaks || []) {
        mk.push({ time: T(b.bar_open_utc), position: b.direction === "BULLISH" ? "belowBar" : "aboveBar",
          shape: b.direction === "BULLISH" ? "arrowUp" : "arrowDown", color: b.kind === "BOS" ? "#7dffb6" : "#ffcc4d",
          text: b.kind === "STRUCTURE_BREAK_UNCLASSIFIED" ? "BRK" : b.kind, size: 0.6 });
      }
      for (const w of ov.sweeps || []) {
        mk.push({ time: T(w.observed_at), position: w.side === "BSL" ? "aboveBar" : "belowBar", shape: "circle", color: "#c792ea", text: "SWP", size: 0.5 });
      }
    }
    const sel = s.decision?.setup;
    if (sel && sel.setup_tf === tf) {
      for (const ch of sel.change_log || []) {
        if (ch.bar_open_utc && ["QUALIFICATION", "ARMING", "TRIGGER", "CONFIRMATION", "INVALIDATE"].includes(ch.event)) {
          mk.push({ time: T(ch.bar_open_utc), position: sel.direction === "LONG" ? "belowBar" : "aboveBar", shape: "square",
            color: ch.event === "INVALIDATE" ? DOWN : "#ffffff", text: ch.event.slice(0, 4), size: 0.5 });
        }
      }
    }
    const firstTime = bars.length ? (T(bars[0].open_utc) as number) : 0;
    markers.current?.setMarkers(mk.filter((m) => (m.time as number) >= firstTime).sort((a, b) => (a.time as number) - (b.time as number)));
    zones.current?.setZones(opts.showZones ? [
      ...(ov.fvgs || []).slice(-6).map((f: any) => ({ from: T(f.formed_at) as number, low: f.low, high: f.high,
        color: f.direction === "BULLISH" ? "rgba(22,224,122,0.10)" : "rgba(255,77,94,0.10)",
        border: f.direction === "BULLISH" ? "rgba(22,224,122,0.55)" : "rgba(255,77,94,0.55)", label: `FVG ${f.status === "PARTIAL" ? Math.round(f.mitigated * 100) + "%" : ""}` })),
      ...(ov.order_blocks || []).slice(-3).map((o: any) => ({ from: T(o.confirmed_at) as number, low: o.low, high: o.high,
        color: "rgba(77,208,255,0.07)", border: "rgba(77,208,255,0.5)", label: "OB?" })),
    ] : []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, opts.showRsi, opts.showMacd, opts.showStructure, opts.showZones, shift]);

  // ---------------------------------------------------------------- execution levels (only computed, existing values)
  useEffect(() => {
    const ser = candles.current;
    if (!ser) return;
    priceLines.current.forEach((p) => ser.removePriceLine(p));
    priceLines.current = [];
    const d = s.decision;
    const lv = d?.levels;
    const st = d?.setup;
    if (!lv || !st || !["EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED"].includes(st.state)) return;
    const add = (price: number, color: string, title: string, style = LineStyle.Dashed) =>
      priceLines.current.push(ser.createPriceLine({ price, color, title, lineStyle: style, lineWidth: 1, axisLabelVisible: true }));
    add(lv.stop_loss, DOWN, "SL");
    (lv.targets || []).forEach((t: any, i: number) => add(t.price, "#16e07a", `TP${i + 1}${st.state !== "CONFIRMED" ? " (scen.)" : ""}`));
    if (lv.entry_zone) {
      add(lv.entry_zone.high, "#d8ff7a", "strefa wejścia", LineStyle.Dotted);
      add(lv.entry_zone.low, "#d8ff7a", "", LineStyle.Dotted);
    }
  }, [s.decision?.levels, s.decision?.setup?.state, data]);

  // ---------------------------------------------------------------- live bar updates
  useEffect(() => {
    const tick = s.barTick?.[tf];
    if (!tick || !candles.current || !volume.current || !tick.bar.open_utc) return;
    const b = tick.bar;
    const t = T(b.open_utc) as number;
    if (t < lastBarTime.current) return;
    lastBarTime.current = t;
    candles.current.update({ time: t as Time, open: b.o, high: b.h, low: b.l, close: b.c,
      ...(b.closed ? {} : { color: b.c >= b.o ? "rgba(22,224,122,0.45)" : "rgba(255,77,94,0.45)" }) });
    volume.current.update({ time: t as Time, value: b.tv, color: b.c >= b.o ? "rgba(22,224,122,0.28)" : "rgba(255,77,94,0.28)" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.barTick?.[tf]]);

  const q = data?.quality;
  const qStatus = q?.status;
  const stale = s.connection?.state !== "CONNECTED" || (s.decision && s.decision.data_quality === "BAD");
  const last = data?.bars?.length ? data.bars[data.bars.length - 1] : null;
  const role = data?.indicators?.role;
  return (
    <div className={cls("panel chart-panel", fullscreen && "fullscreen")}>
      <div className="panel-head">
        <span className="pnum">{index}</span>
        <span className="ptitle">{s.symbol?.symbol ?? "XAUUSD-"}</span>
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
        <button className="icon" title={fullscreen ? "Zamknij pełny ekran" : "Pełny ekran"} onClick={onFullscreen}>{fullscreen ? "✕" : "⤢"}</button>
      </div>
      <div className="chart-box" ref={box} />
      {err && <div className="chart-msg bad">Błąd danych: {err}</div>}
      {!err && data && data.bars?.length === 0 && <div className="chart-msg">Brak świec z MT5 – {q?.fix_hint || "sprawdź połączenie z terminalem"}</div>}
      {q?.fix_hint && data?.bars?.length > 0 && qStatus === "INSUFFICIENT_HISTORY" && <div className="chart-hint">{q.fix_hint}</div>}
    </div>
  );
}
