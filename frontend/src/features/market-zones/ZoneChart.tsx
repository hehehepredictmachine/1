// One timeframe of the "Strefy rynkowe" page: closed + forming candles of the instrument and the backend's zones drawn as time-bounded
// boxes (series primitive - they follow zoom, scroll and resize). The chart never recomputes zones; a click inside a box selects it.
// 1.29: own settings per chart (instrument + TF): colours, grid, text size, time zone, zone layers with colour / opacity, labels.
import { useCallback, useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { apiGet } from "../../api";
import { layerOf, loadPrefs, prefsKey, resetPrefs, rgba, savePrefs, type ChartPrefs } from "../../chartprefs";
import { ChartSettingsDialog, LayerMenu } from "../../components/ChartSettings";
import { useStore } from "../../store";
import { chartShift } from "../../util";
import { BoundedBoxesPrimitive, type BoundedBox } from "../../zones";

const TF_S: Record<string, number> = { M1: 60, M5: 300, M15: 900, M30: 1800 };
const SHORT: Record<string, string> = { SR_SUPPORT: "S/R▲", SR_RESISTANCE: "S/R▼", DEMAND: "POPYT", SUPPLY: "PODAŻ", FVG_BULL: "FVG▲", FVG_BEAR: "FVG▼",
  OB_BULL: "OB▲", OB_BEAR: "OB▼", EQH: "EQH płynn.?", EQL: "EQL płynn.?" };
const ep = (iso?: string | null) => (iso ? Math.floor(Date.parse(iso) / 1000) : null);

export function zoneColors(z: any, stale: boolean, selected: boolean, p: ChartPrefs): { color: string; border: string } {
  if (stale) return { color: "rgba(150,150,150,0.10)", border: selected ? "#e0e0e0" : "#8a8a8a" };
  const st = p.zones[layerOf(String(z.type || "")) ?? "SR"];
  const base = z.direction === "BEARISH" ? st.down : st.up;
  return { color: rgba(base, selected ? Math.min(0.6, st.opacity * 2.3) : st.opacity), border: selected ? "#ffffff" : base };
}

export default function ZoneChart({ instrument, tf, zones, stale, dataKey, selected, onPick }: {
  instrument: string; tf: string; zones: any[]; stale: boolean; dataKey: string; selected: string | null; onPick: (id: string) => void;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const prim = useRef<BoundedBoxesPrimitive | null>(null);
  const lastT = useRef<number>(0);
  const zref = useRef<any[]>([]);
  const prefsRef = useRef<ChartPrefs | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  const [drawn, setDrawn] = useState(0);
  const { s } = useStore();
  const pkey = prefsKey("mz", instrument, tf);
  const [prefs, setPrefsState] = useState<ChartPrefs>(() => loadPrefs(pkey));
  useEffect(() => { setPrefsState(loadPrefs(pkey)); }, [pkey]);
  const setPrefs = useCallback((p: ChartPrefs) => { savePrefs(pkey, p); setPrefsState(loadPrefs(pkey)); }, [pkey]);
  const [open, setOpen] = useState(false);
  const shift = prefs.tz === "PAGE" || prefs.tz === "UTC" ? 0 : chartShift(prefs.tz, s.connection?.clock?.offset_seconds ?? null);
  const shiftRef = useRef(shift);
  shiftRef.current = shift;
  const tzLabel = prefs.tz === "PAGE" || prefs.tz === "UTC" ? "UTC" : prefs.tz === "LOCAL" ? "lokalny" : "serwer";

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#a9dcc0", fontSize: 10, attributionLogo: true },
      grid: { vertLines: { color: "rgba(15,90,49,0.25)" }, horzLines: { color: "rgba(15,90,49,0.25)" } },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 6 },
      crosshair: { mode: CrosshairMode.Normal },
    });
    chart.current = c;
    series.current = c.addSeries(CandlestickSeries, { upColor: "#2bff88", downColor: "#ff4d5e", borderVisible: false, wickUpColor: "#2bff88",
      wickDownColor: "#ff4d5e" });
    prim.current = new BoundedBoxesPrimitive();
    series.current.attachPrimitive(prim.current);
    c.subscribeClick((p) => {
      if (!p.point || p.time === undefined || !series.current) return;
      const price = series.current.coordinateToPrice(p.point.y);
      const t = p.time as number;
      if (price === null) return;
      const hits = zref.current.filter((z) => z._from + shiftRef.current <= t && t <= z._to + shiftRef.current && z.lower <= price && price <= z.upper);
      hits.sort((a, b) => (a.upper - a.lower) - (b.upper - b.lower));
      if (hits[0]) pick.current(hits[0].id);
    });
    (window as any).__mqZoneCharts = { ...((window as any).__mqZoneCharts || {}), [`${instrument}-${tf}`]: { chart: c, prefs: () => prefsRef.current } };
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
      prim.current = null;
    };
  }, [instrument, tf]);

  // candles: on instrument / TF change and whenever the backend applied a new result for this TF (dataKey)
  useEffect(() => {
    let alive = true;
    apiGet(`/api/v1/market-zones/bars?instrument=${instrument}&tf=${tf}&count=400`).then((r) => {
      if (!alive || !series.current) return;
      if (r.status !== "OK") { setErr(r.reason || r.status); return; }
      setErr(null);
      const rows = (r.bars || []).map((b: any) => ({ time: ((ep(b.open_utc) as number) + shiftRef.current) as Time, open: b.o, high: b.h, low: b.l, close: b.c }));
      series.current.setData(rows);
      lastT.current = rows.length ? (rows[rows.length - 1].time as number) - shiftRef.current : 0;      // UTC, like the zone times
      setN(rows.length);
    }).catch((e) => alive && setErr(String(e?.message || e)));
    return () => { alive = false; };
  }, [instrument, tf, dataKey, shift]);

  // own appearance of this chart (applyOptions - no re-creation, zoom kept)
  prefsRef.current = prefs;
  useEffect(() => {
    const c = chart.current;
    if (!c || !series.current) return;
    c.applyOptions({
      layout: { textColor: prefs.textColor ?? "#a9dcc0", fontSize: prefs.fontSize, background: { type: ColorType.Solid, color: prefs.background ?? "transparent" } },
      grid: { vertLines: { color: prefs.gridColor ?? "rgba(15,90,49,0.25)", visible: prefs.showGrid }, horzLines: { color: prefs.gridColor ?? "rgba(15,90,49,0.25)", visible: prefs.showGrid } },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " " + tzLabel },
    });
    series.current.applyOptions({ upColor: prefs.upColor ?? "#2bff88", downColor: prefs.downColor ?? "#ff4d5e", wickUpColor: prefs.wickUp ?? prefs.upColor ?? "#2bff88",
      wickDownColor: prefs.wickDown ?? prefs.downColor ?? "#ff4d5e" });
  }, [prefs, tzLabel, instrument, tf]);

  // zones (backend values only)
  useEffect(() => {
    const end = (lastT.current || Math.floor(Date.now() / 1000)) + 30 * (TF_S[tf] || 60);
    const zs = zones.filter((z) => { const l = layerOf(String(z.type || "")); return !l || prefs.layers[l]; }).map((z) => {
      const from = ep(z.origin_time) || 0;
      const to = ep(z.invalidated_at) || ep(z.expired_at) || end;
      return { ...z, _from: from, _to: to };
    });
    zref.current = zs;
    const boxes: BoundedBox[] = zs.map((z) => {
      const col = zoneColors(z, stale, z.id === selected, prefs);
      return { from: z._from + shift, to: z._to + shift, low: z.lower, high: z.upper, ...col, dashed: z.preliminary || z.state === "PRELIMINARY",
        label: prefs.labels ? `${SHORT[z.type] || z.type} ${Math.round(z.quality?.score ?? 0)}${z.preliminary ? " (wst.)" : ""}${stale ? " · nieakt." : ""}` : undefined };
    });
    prim.current?.set(boxes);
    setDrawn(boxes.length);
  }, [zones, stale, selected, tf, n, prefs, shift]);

  return (
    <div className="mz-chart-wrap">
      <div className="mz-chart-tools chart-tools" role="toolbar" aria-label={`Wykres stref ${tf}`}>
        <LayerMenu prefs={prefs} onChange={setPrefs} testid={`mz-layers-${tf}`} />
        <button className="icon" title="Ustawienia tego wykresu" aria-label={`Ustawienia wykresu ${tf}`} data-testid={`mz-settings-${tf}`} onClick={() => setOpen(true)}>⚙</button>
        <span className="muted small">czas: {tzLabel}</span>
      </div>
      <div ref={box} className="mz-chart" data-testid={`mz-chart-${tf}`} data-zones={zones.length} data-drawn={drawn} data-bars={n} data-stale={stale ? "1" : "0"} />
      {open && <ChartSettingsDialog title={`${instrument} ${tf} (Strefy)`} prefs={prefs} onChange={setPrefs} onClose={() => setOpen(false)}
        onReset={() => { resetPrefs(pkey); setPrefsState(loadPrefs(pkey)); }}
        fallback={{ upColor: "#2bff88", downColor: "#ff4d5e", wickUp: "#2bff88", wickDown: "#ff4d5e", background: "#06140c", gridColor: "#0f5a31", textColor: "#a9dcc0" }} />}
      {err && <div className="mz-chart-err">Wykres {tf}: {err}</div>}
    </div>);
}
