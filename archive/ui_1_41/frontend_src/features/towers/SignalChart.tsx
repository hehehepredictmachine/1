// Signal context chart of PEPE$SIGNAL: OHLCV of the signal's own symbol + TF from the MT5 bridge (/api/v1/markets/chart – works for the
// active instrument and for scanned markets), crosshair, wheel zoom, drag pan, volume, Entry / SL / TP lines, a marker at the moment the
// signal was created and the view scrolled to that moment (not to a random slice). Requests of an older selection are dropped.
import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineStyle, createChart, createSeriesMarkers, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { apiGet } from "../../api";
import type { Sig } from "./signals";

const SEC: Record<string, number> = { M1: 60, M3: 180, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400, D1: 86400 };

export default function SignalChart({ sig, showLevels, resetKey }: { sig: Sig | null; showLevels: boolean; resetKey: number }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const cs = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const vol = useRef<ISeriesApi<"Histogram"> | null>(null);
  const pl = useRef<IPriceLine[]>([]);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  // the signal's own TF (M3 = 180 s); an unknown TF is reported, never silently replaced by M15
  const tf = sig?.tf && SEC[sig.tf] ? sig.tf : sig?.tf ? "" : "M15";
  const symbol = sig?.symbol ?? null;

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#9cc9b2", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: "rgba(57,255,143,.06)" }, horzLines: { color: "rgba(57,255,143,.06)" } }, crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(57,255,143,.25)" }, timeScale: { borderColor: "rgba(57,255,143,.25)", timeVisible: true, secondsVisible: false },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) },
    });
    cs.current = c.addSeries(CandlestickSeries, { upColor: "#2fe08a", downColor: "#ff5d6c", wickUpColor: "#2fe08a", wickDownColor: "#ff5d6c", borderVisible: false });
    vol.current = c.addSeries(HistogramSeries, { priceScaleId: "v", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    c.priceScale("v").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    chart.current = c;
    // own ResizeObserver (not autoSize): it is disconnected BEFORE the chart is removed, so no resize can reach a disposed canvas
    const el = box.current;
    const ro = new ResizeObserver(() => { if (chart.current === c && el.clientWidth > 0) c.resize(el.clientWidth, el.clientHeight); });
    ro.observe(el);
    c.resize(el.clientWidth || 600, el.clientHeight || 280);
    return () => { ro.disconnect(); c.remove(); chart.current = null; cs.current = null; vol.current = null; pl.current = []; };
  }, []);

  useEffect(() => {
    setData(null); setErr(null);
    if (!symbol || !tf) return;
    let alive = true;
    const load = () => apiGet(`/api/v1/markets/chart?symbol=${encodeURIComponent(symbol)}&tf=${tf}&bars=400`)
      .then((d) => { if (alive) { setData(d); setErr(null); } }).catch((e) => { if (alive) setErr(String(e?.message || e)); });
    load();
    const t = setInterval(() => { if (!document.hidden) load(); }, Math.max(15000, (SEC[tf] || 60) * 250));
    return () => { alive = false; clearInterval(t); };
  }, [symbol, tf]);

  useEffect(() => {
    const c = chart.current, s = cs.current, v = vol.current;
    if (!c || !s || !v) return;
    const bars: any[] = (data?.bars || []).filter((b: any) => b.open_utc);
    const t = (b: any) => Math.floor(Date.parse(b.open_utc) / 1000) as Time;
    s.setData(bars.map((b) => ({ time: t(b), open: b.o, high: b.h, low: b.l, close: b.c })));
    v.setData(bars.map((b) => ({ time: t(b), value: b.tv ?? 0, color: b.c >= b.o ? "rgba(47,224,138,.35)" : "rgba(255,93,108,.35)" })));
    pl.current.forEach((p) => s.removePriceLine(p));
    pl.current = [];
    const markers: any[] = [];
    if (sig && bars.length) {
      if (showLevels) {
        const add = (price: number | null, title: string, color: string, style = LineStyle.Dashed) =>
          price != null && Number.isFinite(price) && pl.current.push(s.createPriceLine({ price, title, color, lineStyle: style, lineWidth: 1, axisLabelVisible: true }));
        add(sig.entry, "ENTRY", "#e8fff3", LineStyle.Solid);
        add(sig.sl, "SL", "#ff5d6c");
        sig.targets.forEach((p, i) => add(p, `TP${i + 1}`, "#39ff8f"));
        const zone = sig.raw?.detail?.entry_plan?.zone;
        if (Array.isArray(zone)) { add(zone[0], "strefa", "#5fe3ff", LineStyle.SparseDotted); add(zone[1], "", "#5fe3ff", LineStyle.SparseDotted); }
      }
      const at = sig.at ? Math.floor(Date.parse(sig.at) / 1000) : null;
      if (at) {
        const bar = [...bars].reverse().find((b) => Date.parse(b.open_utc) / 1000 <= at);
        if (bar) markers.push({ time: t(bar), position: sig.scenarioDir === "SELL" ? "aboveBar" : "belowBar", color: sig.scenarioDir === "SELL" ? "#ff5d6c" : "#39ff8f",
          shape: sig.scenarioDir === "SELL" ? "arrowDown" : "arrowUp", text: sig.lifecycle === "WAIT" ? "WAIT" : sig.scenarioDir === "SELL" ? "SELL" : "ENTRY" });
        const sec = SEC[tf];
        c.timeScale().setVisibleRange({ from: (at - sec * 70) as Time, to: (at + sec * 25) as Time });       // scroll to the setup, not a random slice
      } else c.timeScale().fitContent();
    }
    const m = createSeriesMarkers(s, markers);
    // on unmount the chart is removed first (effect order) – detaching then would schedule a repaint of a disposed canvas
    return () => { if (chart.current === c) m.detach(); };
  }, [data, sig?.id, showLevels, resetKey]);           // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="sg-chart-wrap" data-testid="sg-chart" data-symbol={symbol ?? ""} data-tf={tf}>
      <div ref={box} className="sg-chart" />
      {!symbol && <p className="tw-na abs">Wybierz sygnał.</p>}
      {symbol && !tf && <p className="tw-na abs">TF sygnału {sig?.tf} nie jest obsługiwany przez wykres – brak zastępczego interwału.</p>}
      {err && <p className="tw-na abs">Wykres niedostępny: {err}</p>}
      {data && !(data.bars || []).some((b: any) => b.open_utc) && <p className="tw-na abs">Brak świec z czasem UTC dla {symbol} {tf} (zegar serwera jeszcze mierzony).</p>}
    </div>);
}
