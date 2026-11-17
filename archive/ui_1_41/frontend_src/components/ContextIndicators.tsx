// PMW-UPD-14 context indicators card: one lightweight-charts chart with three panes (price + Pullback/SMC structure, VAMD, bounded Katz FD),
// separate render toggles (they never change the analysis), an as-of selector that shows only what was PUBLISHED by then, the SHADOW
// would_block checklist and the Buffer Inspector (imported MT5 reports, explicit mappings, bridge source state). All values come from the
// server; nothing here derives BUY/SELL from a colour or a buffer index. The user's zoom is kept per chart_id + instrument + TF.
import { useEffect, useMemo, useRef, useState } from "react";
import { ColorType, createChart, createSeriesMarkers, CandlestickSeries, CrosshairMode, LineSeries, LineStyle,
  type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time } from "lightweight-charts";
import { apiGet, apiSend } from "../api";
import { loadView, saveView, viewKey, type ChartView } from "../chartview";
import { fmtNum } from "../util";

const TFS = ["M1", "M5", "M15", "H1"];
const ep = (t: string | number) => (typeof t === "number" ? t : Math.floor(Date.parse(t) / 1000));

type SmcEvent = { event_id: string; seq: number; kind: string; bar: number; available_at: number; price?: number; level?: number; reason?: string; point_id?: string };
type SmcPoint = { point_id: string; version: number; side: "H" | "L"; price: number; origin_bar: number; published_bar: number; available_at: number; reason: string };
type PbSwing = { swing_id: string; side: "H" | "L"; price: number; origin_bar: number; confirming_bar: number; available_at: number; reason: string };
type SmcView = { bars: { o: number; h: number; l: number; c: number; t: string | number; i: number }[]; first_bar: number; points: SmcPoint[];
  versions: SmcPoint[]; events: SmcEvent[]; pullback: PbSwing[]; trend: string | null; provisional: any; profile: any; profile_hash: string; epoch: number;
  mode: string; state_hash: string };
type Row = { t: string | number; status?: string; y?: number | null; alpha?: number; fd_smooth?: number | null; fd_bounded?: number | null; zone?: string | null;
  saturated?: boolean; clipped?: boolean };
type Ctx = { status: string; vamd?: any; fd?: any; smc?: any; would_block?: Record<string, { status: string; reasons?: string[]; note?: string }>; profile_hash?: string; epoch?: number };

function usePoll<T>(url: string | null, ms = 20000): [T | null, string | null, () => void] {
  const [d, setD] = useState<T | null>(null);
  const [e, setE] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!url) return;
    let alive = true;                                          // a late answer of an old asset/TF is dropped
    const load = () => apiGet(url).then((x) => { if (alive) { setD(x); setE(null); } }).catch((x) => { if (alive) setE(String(x?.message || x)); });
    load();
    const t = setInterval(load, ms);
    return () => { alive = false; clearInterval(t); };
  }, [url, n]);
  return [d, e, () => setN((k) => k + 1)];
}

function ContextChart({ asset, tf, smc, vamd, fd, show }: { asset: string; tf: string; smc: SmcView | null; vamd: Row[]; fd: Row[];
  show: Record<string, boolean> }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const s = useRef<Record<string, ISeriesApi<any>>>({});
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const vkey = viewKey("ctx-ind", asset, tf);
  const view = useRef<ChartView>(loadView(vkey));
  const userUntil = useRef(0);
  const lastKey = useRef("");
  const [hover, setHover] = useState<string>("");
  const evByTime = useRef<Map<number, string>>(new Map());

  useEffect(() => {
    if (!box.current) return;
    view.current = loadView(vkey);
    const c = createChart(box.current, {
      autoSize: true, layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10, textColor: "#9aa0aa" },
      grid: { vertLines: { color: "rgba(128,128,128,.12)" }, horzLines: { color: "rgba(128,128,128,.12)" } },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 4 }, crosshair: { mode: CrosshairMode.Normal },
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " UTC" },
    });
    chart.current = c;
    s.current.candles = c.addSeries(CandlestickSeries, { upColor: "#2e9d5b", downColor: "#c0453b", borderVisible: false, wickUpColor: "#888", wickDownColor: "#888" }, 0);
    s.current.structure = c.addSeries(LineSeries, { color: "#c9a227", lineWidth: 3, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, title: "SMC" }, 0);
    s.current.pullback = c.addSeries(LineSeries, { color: "rgba(160,160,170,.8)", lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }, 0);
    s.current.trail = c.addSeries(LineSeries, { color: "rgba(201,162,39,.55)", lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false,
      title: "provisional" }, 0);
    s.current.vamd = c.addSeries(LineSeries, { color: "#3fa7d6", lineWidth: 2, title: "VAMD y", priceLineVisible: false }, 1);
    s.current.fd = c.addSeries(LineSeries, { color: "#d68a3f", lineWidth: 2, title: "FD", priceLineVisible: false }, 2);
    s.current.vamd.createPriceLine({ price: 0, color: "rgba(128,128,128,.6)", lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "" });
    markers.current = createSeriesMarkers(s.current.candles, []);
    try { c.panes()[1]?.setHeight(90); c.panes()[2]?.setHeight(90); } catch { /* older pane API */ }
    const el = box.current;
    const mark = () => { userUntil.current = performance.now() + 450; };
    el.addEventListener("wheel", mark, { passive: true });
    el.addEventListener("pointerdown", mark);
    c.timeScale().subscribeVisibleLogicalRangeChange(() => {
      if (performance.now() > userUntil.current) return;          // data refreshes never change the saved view
      const r = c.timeScale().getVisibleRange();
      if (!r) return;
      view.current = { ...view.current, follow: false, from: r.from as number, to: r.to as number };
      saveView(vkey, view.current);
    });
    c.subscribeCrosshairMove((p) => setHover(p.time != null ? evByTime.current.get(p.time as number) || "" : ""));
    return () => {
      el.removeEventListener("wheel", mark);
      el.removeEventListener("pointerdown", mark);
      markers.current = null;
      c.remove();
      chart.current = null;
      s.current = {};
      lastKey.current = "";
    };
  }, [vkey]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !smc) return;
    const bars = smc.bars || [];
    const T = (i: number) => { const b = bars[i - smc.first_bar]; return b ? (ep(b.t) as Time) : null; };
    s.current.candles.setData(bars.map((b) => ({ time: ep(b.t) as Time, open: b.o, high: b.h, low: b.l, close: b.c })));
    const pts = (smc.points || []).filter((p) => T(p.origin_bar) != null).sort((a, b) => a.origin_bar - b.origin_bar);
    const line = (xs: { bar: number; price: number }[]) => {
      const m = new Map<number, number>();
      xs.forEach((x) => { const t = T(x.bar); if (t != null) m.set(t as number, x.price); });
      return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time: time as Time, value }));
    };
    s.current.structure.setData(show.smc ? line(pts.map((p) => ({ bar: p.origin_bar, price: p.price }))) : []);
    s.current.pullback.setData(show.pullback ? line((smc.pullback || []).map((p) => ({ bar: p.origin_bar, price: p.price }))) : []);
    const pv = smc.provisional;
    const lastPt = pts[pts.length - 1];
    s.current.trail.setData(show.trail && pv && lastPt && T(pv.origin_bar) != null && pv.origin_bar > lastPt.origin_bar
      ? line([{ bar: lastPt.origin_bar, price: lastPt.price }, { bar: pv.origin_bar, price: pv.tracked }]) : []);
    const mk: SeriesMarker<Time>[] = [];
    const ev = new Map<number, string>();
    for (const e of smc.events || []) {
      const t = T(e.bar);
      if (t == null) continue;
      const txt = `${e.kind}${e.level != null ? " @" + fmtNum(e.level, 2) : e.price != null ? " " + fmtNum(e.price, 2) : ""} · ${e.event_id} · publikacja ${new Date(e.available_at * 1000).toISOString().slice(5, 16)}Z${e.reason ? " · " + e.reason : ""}`;
      ev.set(t as number, (ev.get(t as number) ? ev.get(t as number) + " | " : "") + txt);
      if (!show.events) continue;
      if (/^(BOS|CHOCH)_/.test(e.kind)) mk.push({ time: t, position: e.kind.endsWith("UP") ? "belowBar" : "aboveBar", shape: e.kind.endsWith("UP") ? "arrowUp" : "arrowDown",
        color: e.kind.startsWith("CHOCH") ? "#d65f8a" : "#c9a227", text: e.kind.replace("_", " ") });
      else if (e.kind === "IDM" || e.kind.startsWith("X_")) mk.push({ time: t, position: "inBar", shape: "circle", color: e.kind === "IDM" ? "#3fa7d6" : "#a066d3", text: e.kind });
    }
    evByTime.current = ev;
    markers.current?.setMarkers(mk.sort((a, b) => (a.time as number) - (b.time as number)));
    s.current.vamd.setData(show.vamd ? vamd.map((r) => (r.y != null ? { time: ep(r.t) as Time, value: r.y } : { time: ep(r.t) as Time })) : []);
    s.current.fd.setData(show.fd ? fd.map((r) => (r.fd_smooth != null ? { time: ep(r.t) as Time, value: r.fd_smooth,
      color: r.zone === "TREND" ? "#3fa7d6" : r.zone === "CHOP" ? "#d68a3f" : "#9aa0aa" } : { time: ep(r.t) as Time })) : []);
    const key = `${bars.length}|${bars[0]?.t}|${smc.epoch}`;
    if (key !== lastKey.current) {
      lastKey.current = key;
      const v = view.current;
      try {
        if (!v.follow && v.from && v.to) c.timeScale().setVisibleRange({ from: v.from as Time, to: v.to as Time });
        else c.timeScale().setVisibleLogicalRange({ from: bars.length - (v.width || 150), to: bars.length + 4 });
      } catch { /* outside history */ }
    }
  }, [smc, vamd, fd, show.smc, show.pullback, show.trail, show.events, show.vamd, show.fd]);

  const reset = () => {
    view.current = { ...view.current, follow: true, from: undefined, to: undefined, width: 150 };
    saveView(vkey, view.current);
    const n = smc?.bars?.length || 0;
    chart.current?.timeScale().setVisibleLogicalRange({ from: n - 150, to: n + 4 });
  };
  return <div>
    <div ref={box} data-testid="ctx-chart" style={{ width: "100%", height: 420 }} />
    <p className="small"><button className="btn small ghost" onClick={reset}>Reset widoku</button>{" "}
      <span className="muted" data-testid="ctx-hover">{hover || "najedź na świecę, aby zobaczyć zdarzenia (id, czas publikacji, powód)"}</span></p>
  </div>;
}

const REQ = ["indicator_path", "input_hash", "buffer", "units", "direction_semantics", "empty_sentinel", "zero_is_valid", "shift_policy", "plot_shift",
  "confirmation_policy", "symbol", "tf"];

function BufferInspector() {
  const [reps, , reload] = usePoll<any>("/api/v1/lab/buffers/reports", 60000);
  const [maps, , reloadMaps] = usePoll<any>("/api/v1/lab/buffers/mappings", 60000);
  const [src] = usePoll<any>("/api/v1/lab/buffers/source?tf=M5", 15000);
  const [sel, setSel] = useState<string>("");
  const [rep, setRep] = useState<any>(null);
  const [form, setForm] = useState<Record<string, any>>({ buffer: 0, empty_sentinel: "EMPTY_VALUE", zero_is_valid: true, shift_policy: "SHIFT1_CLOSED",
    plot_shift: "UNKNOWN", confirmation_policy: "CLOSED_BAR", direction_semantics: "NONE_LEVEL_ONLY", units: "PRICE", tf: "M5" });
  const [val, setVal] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (sel) apiGet(`/api/v1/lab/buffers/reports/${sel}`).then(setRep).catch((e) => setMsg(String(e?.message || e))); }, [sel]);
  const doImport = async () => { setMsg(null); try { const r = await apiSend("POST", "/api/v1/lab/buffers/reports/import", {}); setMsg(`zaimportowano ${r.report_id} (${r.coverage})`); reload(); } catch (e: any) { setMsg(String(e?.message || e)); } };
  const body = () => ({ ...form, buffer: Number(form.buffer), plot_shift: form.plot_shift === "UNKNOWN" ? "UNKNOWN" : Number(form.plot_shift),
    zero_is_valid: form.zero_is_valid === true || form.zero_is_valid === "true" });
  const validate = async () => setVal(await apiSend("POST", "/api/v1/lab/buffers/mappings/validate", body()));
  const save = async () => { const r = await apiSend("POST", "/api/v1/lab/buffers/mappings", body()); setVal(r.validation); setMsg(`zapisano ${r.mapping_id} v${r.mapper_version}`); reloadMaps(); };
  const rollback = async (id: string) => { await apiSend("POST", `/api/v1/lab/buffers/mappings/${id}/rollback`); reloadMaps(); };
  const bufs = useMemo(() => (rep?.instances || []).flatMap((i: any) => (i.buffers || []).filter((b: any) => b.status !== "UNREADABLE" || b.index < 8)
    .map((b: any) => ({ ...b, inst: i }))), [rep]);
  return <div data-testid="ctx-buffers">
    <h4>Dane i źródła / Bufory (Buffer Inspector)</h4>
    <p className="small muted">Skan uruchamiasz lokalnie w MT5: Skrypty › PMW › PWM_BufferInspector (raport do MQL5\Files\PMW). Panel nie skanuje terminala zdalnie; typ bufora to hipoteza, indeks B jest techniczny,
      kolor nie jest BUY/SELL. Nieznany PLOT_SHIFT / empty / potwierdzenie blokuje użycie jako cechy.</p>
    <p className="small"><button className="btn small" onClick={doImport}>Importuj PWM_BUFFER_REPORT.json</button>{" "}
      <select value={sel} onChange={(e) => setSel(e.target.value)} data-testid="ctx-report-select"><option value="">— raport —</option>
        {(reps?.reports || []).map((r: any) => <option key={r.report_id} value={r.report_id}>{r.report_id} · build {r.terminal_build} · {r.coverage} · {r.instances} inst.</option>)}</select>
      {msg && <span className="muted"> {msg}</span>}</p>
    {rep && <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Instancja</th><th>Okno</th><th>B</th><th>Status</th><th>Hipoteza</th><th>Pewność</th><th>Gęstość</th><th>Zera</th><th>Shift</th></tr></thead>
      <tbody>{bufs.slice(0, 120).map((b: any, k: number) => <tr key={k}><td>{b.inst.short_name}{b.inst.ambiguous ? " ⚠ niejednoznaczna nazwa" : ""}</td><td>{b.inst.window}</td><td>{b.index}</td>
        <td>{b.status}</td><td>{b.hypothesis?.type}</td><td>{fmtNum(b.hypothesis?.confidence, 2)}</td><td>{fmtNum(b.hypothesis?.stats?.density, 2)}</td>
        <td>{b.hypothesis?.stats?.zeros ?? "—"}</td><td>{b.inst.plot_shift ?? "UNKNOWN"}</td></tr>)}</tbody></table>
      <p className="small muted">Pokrycie: {rep.coverage}; capability: {rep.capability ? Object.entries(rep.capability).filter(([k]) => k !== "bars_calculated").map(([k, v]: any) => `${k}=${v?.read ?? v}`).join(", ") : "brak (fixture nie zainstalowany)"}</p></div>}
    <div className="small" data-testid="ctx-mapping-form" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {REQ.map((k) => <label key={k} style={{ minWidth: 150 }}>{k}<br /><input value={String(form[k] ?? "")} onChange={(e) => setForm({ ...form, [k]: e.target.value })} style={{ width: "100%" }} /></label>)}
    </div>
    <p className="small"><button className="btn small" onClick={validate}>Waliduj</button>{" "}<button className="btn small" onClick={save}>Zapisz mapowanie</button>{" "}
      {val && <span data-testid="ctx-mapping-status"><b>{val.status}</b>{val.missing?.length ? ` · brak: ${val.missing.join(", ")}` : ""}{val.problems?.length ? ` · ${val.problems.join("; ")}` : ""}
        <span className="muted"> – {val.note}</span></span>}</p>
    <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Mapowanie</th><th>Wersja</th><th>Wskaźnik / bufor</th><th>Status</th><th></th></tr></thead>
      <tbody>{Object.values(maps?.mappings || {}).map((m: any) => <tr key={m.mapping_id}><td>{m.mapping_id}</td><td>v{m.mapper_version}</td><td>{m.indicator_path} / B{m.buffer}</td>
        <td>{m.validation?.status}</td><td><button className="btn small ghost" onClick={() => rollback(m.mapping_id)}>Rollback</button></td></tr>)}</tbody></table></div>
    <p className="small" data-testid="ctx-source">Źródło zewnętrzne (most): <b>{src?.status ?? "—"}</b> {src?.reason ? `– ${src.reason}` : ""}
      {src?.rows?.length ? ` · ostatnia wartość ${src.rows[src.rows.length - 1].empty ? "pusta" : fmtNum(src.rows[src.rows.length - 1].value, 4)} (${src.units}) · ${src.known_at_basis}` : ""}
      {src?.role ? <span className="muted"> · {src.role}</span> : null}</p>
  </div>;
}

export function ContextIndicatorsCard({ asset, onStart }: { asset: string; onStart: (kind: string, extra: any) => void }) {
  const [tf, setTf] = useState("M5");
  const [asOf, setAsOf] = useState<number | null>(null);
  const [show, setShow] = useState<Record<string, boolean>>({ smc: true, pullback: true, trail: true, events: true, vamd: true, fd: true });
  const [smc, e1] = usePoll<SmcView>(`/api/v1/lab/smc?asset=${asset}&tf=${tf}&limit=300${asOf != null ? `&as_of=${asOf}` : ""}`);
  const [vm] = usePoll<{ series: Row[]; config: any; profile: string }>(`/api/v1/lab/vamd?asset=${asset}&tf=${tf}&limit=300`);
  const [fd] = usePoll<{ series: Row[]; config: any; profile: string }>(`/api/v1/lab/fractal-regime?asset=${asset}&tf=${tf}&limit=300`);
  const [sum] = usePoll<{ tfs: Record<string, Ctx>; profile: any }>(`/api/v1/lab/context?asset=${asset}`);
  const cur = sum?.tfs?.[tf];
  const evTimes = useMemo(() => [...new Set((smc?.events || []).map((e) => e.available_at))].sort((a, b) => a - b), [smc?.state_hash, asOf == null]);
  const lastV = (vm?.series || []).filter((r) => r.y != null).slice(-1)[0];
  const lastF = (fd?.series || []).filter((r) => r.zone).slice(-1)[0];
  const tog = (k: string, label: string) => <label key={k} style={{ display: "inline-flex", alignItems: "center", gap: 4, marginRight: 10 }}><input type="checkbox" checked={!!show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} /> {label}</label>;
  return (
    <div className="card wide" data-testid="ctx-ind-card">
      <h3>Kontekst: VAMD · FD (Katz bounded) · Pullback + SMC · Buffer Inspector (PMW-UPD-14){" "}
        <span className="seg">{TFS.map((x) => <button key={x} className={"btn small" + (x === tf ? "" : " ghost")} onClick={() => { setTf(x); setAsOf(null); }}>{x}</button>)}</span></h3>
      <p><button className="btn" onClick={() => onStart("context_calibrate", {})}>Kalibracja VAMD/FD/SMC (dev, ≤24 konfiguracje)</button>{" "}
        <button className="btn" onClick={() => onStart("context_dataset", {})}>Dataset CONTEXT_MOVE_M5_V1</button>{" "}
        <button className="btn" onClick={() => onStart("context_train", { profile: "quick", families: ["LOGREG", "XGB"] })}>Trening quick</button>{" "}
        <button className="btn" onClick={() => onStart("context_train", { profile: "standard", families: ["LOGREG", "XGB"] })}>Trening standard</button></p>
      {e1 ? <p className="small muted">{e1}</p> : <>
        <p className="small" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 4 }}>{tog("smc", "struktura SMC")} {tog("pullback", "pullback")} {tog("trail", "provisional trail")} {tog("events", "zdarzenia")} {tog("vamd", "VAMD")} {tog("fd", "FD")}
          {" "}<select data-testid="ctx-asof" value={asOf ?? ""} onChange={(e) => setAsOf(e.target.value ? Number(e.target.value) : null)}>
            <option value="">bieżący stan (z późniejszymi relokacjami)</option>
            {evTimes.slice(-60).map((t) => <option key={t} value={t}>stan znany {new Date(t * 1000).toISOString().slice(5, 16)}Z</option>)}</select>
          <span className="muted"> {smc?.mode === "AS_OF_KNOWN" ? "widok as-of: tylko punkty/zdarzenia opublikowane do tej chwili" : ""}</span></p>
        <ContextChart asset={asset} tf={tf} smc={smc} vamd={vm?.series || []} fd={fd?.series || []} show={show} />
        <div className="tbl-wrap" data-testid="ctx-readout"><table className="tbl small"><tbody>
          <tr><td>VAMD ({vm?.profile})</td><td>y {lastV ? fmtNum(lastV.y, 3) : "—"} · alpha {lastV ? fmtNum(lastV.alpha, 3) : "—"} · P={vm?.config?.P} A={vm?.config?.A} B={vm?.config?.B}</td>
            <td className="muted">znak = momentum, nie p(win); brak targetu ≠ decay do 0</td></tr>
          <tr><td>FD ({fd?.profile})</td><td>strefa {lastF?.zone ?? "—"} · smooth {lastF ? fmtNum(lastF.fd_smooth, 3) : "—"}{lastF?.saturated ? " · saturacja" : ""}{lastF?.clipped ? " · clipped" : ""}</td>
            <td className="muted">TREND bez strony</td></tr>
          <tr><td>SMC ({smc?.profile?.profile})</td><td>trend {smc?.trend ?? "—"} · punkty {smc?.points?.length ?? 0} · zdarzenia {smc?.events?.length ?? 0} · epoch {smc?.epoch} · hash {smc?.state_hash}</td>
            <td className="muted">pending wick = kandydat; x dopiero po potwierdzeniu</td></tr>
        </tbody></table></div>
        <div data-testid="ctx-wouldblock"><h4>Setupy: filtr kontekstu (SHADOW, would_block)</h4>
          {cur?.would_block ? <table className="tbl small"><thead><tr><th>Strona</th><th>Status</th><th>Powody</th></tr></thead><tbody>
            {Object.entries(cur.would_block).map(([side, w]) => <tr key={side}><td>{side}</td><td>{w.status}</td><td>{(w.reasons || []).join(", ") || "—"}</td></tr>)}</tbody></table>
            : <p className="small muted">{cur?.status ?? "brak stanu – powstaje przy pierwszym snapshocie Structure Intelligence"}</p>}
          <p className="small muted">Filtr nie jest triggerem: wejście wymaga istniejącego triggera i ryzyka; FD TREND + VAMD&gt;0 samo nie wystarcza do BUY; nowa warstwa SMC nie jest czwartą niezależną zgodą.
            Profil: {sum?.profile?.source} (hash {sum?.profile?.hash}).</p></div>
        <BufferInspector />
      </>}
    </div>
  );
}
