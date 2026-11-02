// One timeframe of the "Strefy rynkowe" page: closed + forming candles of the instrument and the backend's zones drawn as time-bounded
// boxes (series primitive - they follow zoom, scroll and resize). The chart never recomputes zones; a click inside a box selects it.
import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { apiGet } from "../../api";
import { BoundedBoxesPrimitive, type BoundedBox } from "../../zones";

const TF_S: Record<string, number> = { M1: 60, M5: 300, M15: 900, M30: 1800 };
const SHORT: Record<string, string> = { SR_SUPPORT: "S/R▲", SR_RESISTANCE: "S/R▼", DEMAND: "POPYT", SUPPLY: "PODAŻ", FVG_BULL: "FVG▲", FVG_BEAR: "FVG▼",
  OB_BULL: "OB▲", OB_BEAR: "OB▼", EQH: "EQH płynn.?", EQL: "EQL płynn.?" };
const ep = (iso?: string | null) => (iso ? Math.floor(Date.parse(iso) / 1000) : null);

export function zoneColors(z: any, stale: boolean, selected: boolean): { color: string; border: string } {
  if (stale) return { color: "rgba(150,150,150,0.10)", border: selected ? "#e0e0e0" : "#8a8a8a" };
  const a = selected ? 0.30 : 0.13;
  if (z.direction === "BULLISH") return { color: `rgba(43,255,136,${a})`, border: selected ? "#b8ffd8" : "#2bff88" };
  if (z.direction === "BEARISH") return { color: `rgba(255,77,94,${a})`, border: selected ? "#ffd0d5" : "#ff4d5e" };
  return { color: `rgba(255,204,77,${a * 0.8})`, border: selected ? "#fff0c0" : "#ffcc4d" };
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
  const pick = useRef(onPick);
  pick.current = onPick;
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#a9dcc0", fontSize: 10, attributionLogo: true },
      grid: { vertLines: { color: "rgba(15,90,49,0.25)" }, horzLines: { color: "rgba(15,90,49,0.25)" } },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 6 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " UTC" },
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
      const hits = zref.current.filter((z) => z._from <= t && t <= z._to && z.lower <= price && price <= z.upper);
      hits.sort((a, b) => (a.upper - a.lower) - (b.upper - b.lower));
      if (hits[0]) pick.current(hits[0].id);
    });
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
      const rows = (r.bars || []).map((b: any) => ({ time: ep(b.open_utc) as Time, open: b.o, high: b.h, low: b.l, close: b.c }));
      series.current.setData(rows);
      lastT.current = rows.length ? (rows[rows.length - 1].time as number) : 0;
      setN(rows.length);
    }).catch((e) => alive && setErr(String(e?.message || e)));
    return () => { alive = false; };
  }, [instrument, tf, dataKey]);

  // zones (backend values only)
  useEffect(() => {
    const end = (lastT.current || Math.floor(Date.now() / 1000)) + 30 * (TF_S[tf] || 60);
    const zs = zones.map((z) => {
      const from = ep(z.origin_time) || 0;
      const to = ep(z.invalidated_at) || ep(z.expired_at) || end;
      return { ...z, _from: from, _to: to };
    });
    zref.current = zs;
    const boxes: BoundedBox[] = zs.map((z) => {
      const col = zoneColors(z, stale, z.id === selected);
      return { from: z._from, to: z._to, low: z.lower, high: z.upper, ...col, dashed: z.preliminary || z.state === "PRELIMINARY",
        label: `${SHORT[z.type] || z.type} ${Math.round(z.quality?.score ?? 0)}${z.preliminary ? " (wst.)" : ""}${stale ? " · nieakt." : ""}` };
    });
    prim.current?.set(boxes);
  }, [zones, stale, selected, tf, n]);

  return (
    <div className="mz-chart-wrap">
      <div ref={box} className="mz-chart" data-testid={`mz-chart-${tf}`} data-zones={zones.length} data-bars={n} data-stale={stale ? "1" : "0"} />
      {err && <div className="mz-chart-err">Wykres {tf}: {err}</div>}
    </div>);
}
