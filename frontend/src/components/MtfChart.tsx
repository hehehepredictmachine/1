// PMW-UPD-05: one chart of the Scalping MTF workspace. Data come ONLY from /api/v1/scalp/dashboard/chart for the given snapshot_id
// (never an independent "latest"); the forming candle is a separate, labelled preview series. Series are created once and updated;
// the user's view (chart_id + instrument + TF) is restored after every refresh. Times are canonical UTC seconds (no display shift).
// Sync messages carry workspace + instrument + session epoch: only charts of the same workspace/instrument/epoch react, a received
// message is never re-broadcast (no loops), the crosshair maps T to the candle whose interval CONTAINS T (no future / nearest bar).
import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, LineSeries, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { apiGet } from "../api";
import { loadView, saveView, SYNC, viewKey, type ChartView, type SyncGroup, type SyncMsg } from "../chartview";
import { useTheme, type Tokens } from "../theme";

const SECS: Record<string, number> = { M1: 60, M5: 300, M15: 900, M30: 1800, H1: 3600 };
const ep = (iso: string) => Math.floor(Date.parse(iso) / 1000);
let SEQ = 0;

export function containing(times: number[], secs: number, t: number): number {
  let lo = 0, hi = times.length - 1, k = -1;
  while (lo <= hi) {                                       // last candle with open <= t (binary search)
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) { k = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return k >= 0 && t < times[k] + secs ? k : -1;           // only if its interval really contains t
}

export default function MtfChart({ tf, snapshotId, chartId, workspace, instrument, epoch, setupId, height, onExpired, focusTime, title }: {
  tf: string; snapshotId: string | null; chartId: string; workspace: string; instrument: string; epoch: string; setupId?: string | null;
  height: number; onExpired?: () => void; focusTime?: number | null; title?: string;
}) {
  const theme = useTheme();
  const tk: Tokens = theme.chartTokens(`tf:${tf}`);
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const preview = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const bb = useRef<ISeriesApi<"Line">[]>([]);
  const sar = useRef<ISeriesApi<"Line"> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const times = useRef<number[]>([]);
  const lastKey = useRef("");
  const vkey = viewKey(chartId, instrument, tf);
  const view = useRef<ChartView>(loadView(vkey));
  const [group, setGroup] = useState<SyncGroup>(view.current.group);
  const [syncCursor, setSyncCursor] = useState(true);
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const userUntil = useRef(0);
  const ctx = useRef({ workspace, instrument, epoch, syncCursor });
  ctx.current = { workspace, instrument, epoch, syncCursor };

  useEffect(() => {
    if (!box.current) return;
    view.current = loadView(vkey);
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10, attributionLogo: true },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " UTC" },
    });
    chart.current = c;
    candles.current = c.addSeries(CandlestickSeries, {});
    preview.current = c.addSeries(CandlestickSeries, { upColor: "rgba(150,150,150,.35)", downColor: "rgba(150,150,150,.35)", borderVisible: true,
      borderUpColor: "#999", borderDownColor: "#999", wickUpColor: "#999", wickDownColor: "#999", lastValueVisible: false, priceLineVisible: false,
      title: "podgląd LIVE" });
    bb.current = [0, 1, 2].map((i) => c.addSeries(LineSeries, { lineWidth: 1, lineStyle: i === 1 ? LineStyle.Dotted : LineStyle.Solid, lastValueVisible: false,
      priceLineVisible: false, crosshairMarkerVisible: false }));
    sar.current = c.addSeries(LineSeries, { lineWidth: 1, lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 1.5, lastValueVisible: false,
      priceLineVisible: false, crosshairMarkerVisible: false });
    const el = box.current;
    const mark = () => { userUntil.current = performance.now() + 450; };
    el.addEventListener("wheel", mark, { passive: true });
    el.addEventListener("pointerdown", mark);
    c.timeScale().subscribeVisibleLogicalRangeChange(() => {
      if (performance.now() > userUntil.current) return;           // only user actions change the saved view
      const r = c.timeScale().getVisibleRange();
      const lr = c.timeScale().getVisibleLogicalRange();
      if (!r || !lr) return;
      const n = times.current.length;
      view.current = { ...view.current, from: r.from as number, to: r.to as number, follow: lr.to >= n - 1, width: lr.to - lr.from };
      saveView(vkey, view.current);
      if (view.current.group) {
        SYNC.dispatchEvent(new CustomEvent("sync", { detail: { src: chartId, kind: "range", group: view.current.group, from: r.from as number, to: r.to as number,
          ...ctx.current, seq: ++SEQ } as SyncMsg }));
      }
    });
    c.subscribeCrosshairMove((p) => {
      if (!ctx.current.syncCursor || !p.sourceEvent) return;         // programmatic moves are not re-broadcast
      SYNC.dispatchEvent(new CustomEvent("sync", { detail: { src: chartId, kind: "crosshair", time: (p.time as number) ?? null, ...ctx.current, seq: ++SEQ } as SyncMsg }));
    });
    return () => {
      el.removeEventListener("wheel", mark);
      el.removeEventListener("pointerdown", mark);
      c.remove();
      chart.current = null;
      lines.current = [];
      times.current = [];
      lastKey.current = "";
    };
  }, [vkey, chartId]);

  useEffect(() => {
    const t: any = tk || {};
    candles.current?.applyOptions({ upColor: t.upBody, downColor: t.downBody, borderUpColor: t.upBorder, borderDownColor: t.downBorder, wickUpColor: t.upWick, wickDownColor: t.downWick });
    chart.current?.applyOptions({ layout: { textColor: t.chartText }, grid: { vertLines: { color: t.chartGrid }, horzLines: { color: t.chartGrid } } });
    bb.current.forEach((s) => s.applyOptions({ color: t.ind2 || "#888" }));
    sar.current?.applyOptions({ color: t.ind4 || "#c80" });
  }, [JSON.stringify(tk)]);

  // receive sync (scoped)
  useEffect(() => {
    const h = (e: Event) => {
      const m = (e as CustomEvent).detail as SyncMsg;
      const c = chart.current;
      if (!c || m.src === chartId || m.workspace !== workspace || m.instrument !== instrument || m.epoch !== epoch) return;
      if (m.kind === "crosshair") {
        if (!syncCursor) return;
        if (m.time == null) { c.clearCrosshairPosition(); return; }
        const k = containing(times.current, SECS[tf], m.time);
        if (k < 0) { c.clearCrosshairPosition(); return; }               // gap / out of history: no match, no distant candle
        const bar = (d?.bars || [])[k];
        if (bar && candles.current) c.setCrosshairPosition(bar.c, times.current[k] as Time, candles.current);
      } else if (m.kind === "range" && m.group && m.group === view.current.group && m.from && m.to) {
        try { c.timeScale().setVisibleRange({ from: m.from as Time, to: m.to as Time }); } catch { /* outside this chart's history */ }
      }
    };
    SYNC.addEventListener("sync", h);
    return () => SYNC.removeEventListener("sync", h);
  }, [chartId, workspace, instrument, epoch, syncCursor, d, tf]);

  // data for THIS snapshot (stale answers dropped)
  useEffect(() => {
    if (!snapshotId) return;
    let alive = true;
    apiGet(`/api/v1/scalp/dashboard/chart?tf=${tf}&snapshot_id=${snapshotId}`).then((r) => {
      if (!alive) return;
      if (r.status === "SNAPSHOT_EXPIRED") { onExpired?.(); return; }
      if (r.status !== "OK") { setErr(r.reason || r.status); setD(r); return; }
      if (r.asset !== instrument) return;
      setErr(null);
      setD(r);
    }).catch((e) => {
      if (!alive) return;
      if (String(e?.message || e).includes("410")) onExpired?.(); else setErr(String(e?.message || e));
    });
    return () => { alive = false; };
  }, [tf, snapshotId, instrument]);

  // paint (setData only when the closed bar set changed; the user's view restored)
  useEffect(() => {
    const c = chart.current;
    if (!c || !d || d.status !== "OK" || !candles.current) return;
    const bars = d.bars || [];
    const key = `${bars.length}|${bars[0]?.open_utc}|${bars[bars.length - 1]?.open_utc}|${d.bar_revision}`;
    if (key !== lastKey.current) {
      lastKey.current = key;
      const ts = bars.map((b: any) => ep(b.open_utc));
      times.current = ts;
      candles.current.setData(bars.map((b: any, i: number) => ({ time: ts[i] as Time, open: b.o, high: b.h, low: b.l, close: b.c })));
      ["upper", "mid", "lower"].forEach((k, j) => bb.current[j].setData((d.indicators?.bb || []).map((x: any, i: number) => (x && x[k] != null ? { time: ts[i] as Time, value: x[k] } : { time: ts[i] as Time }))));
      sar.current?.setData((d.indicators?.sar || []).map((x: any, i: number) => (x && x.sar != null ? { time: ts[i] as Time, value: x.sar } : { time: ts[i] as Time })));
      const v = view.current;
      try {
        if (!v.follow && v.from && v.to) c.timeScale().setVisibleRange({ from: v.from as Time, to: v.to as Time });
        else { const n = ts.length; c.timeScale().setVisibleLogicalRange({ from: n - (v.width || 150), to: n + 4 }); }
      } catch { /* empty */ }
    }
    const f = d.forming_preview;
    preview.current?.setData(f ? [{ time: ep(f.open_utc) as Time, open: f.o, high: f.h, low: f.l, close: f.c }] : []);
    lines.current.forEach((l) => candles.current!.removePriceLine(l));
    lines.current = [];
    for (const o of d.overlays || []) {
      if (o.setup_id && o.setup_id !== setupId) continue;            // viewing setup A never shows the levels of setup B
      const add = (price: number, label: string, style = LineStyle.Dashed) => price != null &&
        lines.current.push(candles.current!.createPriceLine({ price, title: label, lineStyle: style, lineWidth: 1, axisLabelVisible: true, color: String((tk as any).chartCrosshair) }));
      if (o.kind === "RANGE") { add(o.geometry.H, "range H (M5)"); add(o.geometry.L, "range L (M5)"); add(o.geometry.MID, "MID (M5)", LineStyle.Dotted); }
      else if (o.kind === "ZONE") { add(o.geometry.low, `strefa ${o.side} (M5)`, LineStyle.SparseDotted); add(o.geometry.high, "", LineStyle.SparseDotted); }
      else add(o.geometry.price, `${o.kind} ${o.side}`, o.kind === "SL" ? LineStyle.Solid : LineStyle.Dashed);
    }
  }, [d, setupId, JSON.stringify(tk)]);

  // "show evidence": crosshair to a time (only inside this chart's candles)
  useEffect(() => {
    const c = chart.current;
    if (!c || focusTime == null || !candles.current) return;
    const k = containing(times.current, SECS[tf], focusTime);
    if (k >= 0) {
      try { c.timeScale().scrollToPosition(-(times.current.length - 1 - k) + 20, false); } catch { /* empty */ }
      c.setCrosshairPosition((d?.bars || [])[k]?.c, times.current[k] as Time, candles.current);
    }
  }, [focusTime]);

  const reset = () => {
    view.current = { ...view.current, follow: true, from: undefined, to: undefined, width: 150 };
    saveView(vkey, view.current);
    const n = times.current.length;
    chart.current?.timeScale().setVisibleLogicalRange({ from: n - 150, to: n + 4 });
  };
  return (
    <div className="card mtf-chart" data-testid={`mtf-chart-${tf}`} data-snapshot={d?.snapshot_id || ""}>
      <div className="mtf-chart-head small">
        <b>{title || tf}</b>
        <span className="muted">{d?.cutoff ? `do ${d.cutoff.slice(11, 16)} UTC` : ""} {d?.bars_source === "BRIDGE_BUFFER_CUTOFF" ? "· archiwum (bufor MT5)" : ""}</span>
        <span className="mtf-chart-tools">
          <label title="Synchronizacja kursora w tym dashboardzie"><input type="checkbox" checked={syncCursor} onChange={(e) => setSyncCursor(e.target.checked)} /> kursor</label>
          <select aria-label={`Grupa zakresu ${tf}`} value={group} onChange={(e) => { const g = e.target.value as SyncGroup; setGroup(g); view.current = { ...view.current, group: g }; saveView(vkey, view.current); }}>
            <option value="">zakres: niezależny</option><option value="A">grupa A</option><option value="B">grupa B</option></select>
          <button className="btn ghost" onClick={reset} title="Do bieżącej ceny / reset tylko tego wykresu">⟲</button></span></div>
      {err && <p className="small muted" data-testid={`mtf-chart-err-${tf}`}>{err}{d?.history_from ? ` (historia od ${d.history_from})` : ""}</p>}
      <div ref={box} style={{ height }} />
    </div>);
}
