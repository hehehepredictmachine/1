// WTC PEPE 2.1 - NEW CHART LAB + SESSION VOLUME PROFILE (production integration of WTC_PEPE_2_1_HTML).
// The demo of the pack drew synthetic candles on its own canvas; here everything runs on the REAL bars of the MT5 bridge
// (/api/v1/candles - the same feed as every chart of the bot) and the existing Lightweight Charts library:
//   * CUSTOMIZE CHART: theme, chart type (Candles / Hollow / Heikin Ashi / Line / Area), candle colours, grid, line width;
//   * indicators EMA x2 / VWAP / BB / RSI / MACD / ATR / SVP / SMC with on, period, colour, width; RSI, MACD, ATR in their own panes;
//   * presets: several named presets, save / load / delete, JSON import / export (versioned schema, validated), reset;
//   * Session Volume Profile of the window or of the last London / New York / Asia session: POC + Value Area, volume spread over the
//     High-Low of each bar (OHLC approximation - no footprint), biggest price impulse in a 3 / 5 / 8 / 12 bar window.
// Presentation only: nothing here feeds the engine or sends an order.
import { useEffect, useMemo, useRef, useState } from "react";
import { AreaSeries, CandlestickSeries, ColorType, createChart, createSeriesMarkers, HistogramSeries, LineSeries, LineStyle,
  type IChartApi, type ISeriesApi, type SeriesMarker, type Time } from "lightweight-charts";
import { cls } from "../../../util";
import { TFS, fmt, usePolled } from "../data";
import { atr, biggestImpulse, bollinger, ema, heikinAshi, lastSessionBars, macd, rsi, SESSION_LABEL, smc, toBars, volumeProfile, volumeSource,
  vwapDaily, type Session } from "./calc";
import { CHART_TYPES, DEFAULT_LAB, IND_META, loadCurrent, loadPresets, sanitizeLab, saveCurrent, savePresets, THEMES, type IndKey, type LabCfg } from "./presets";

const T = (t: number) => t as Time;
type Tab = "chart" | "ind" | "svp" | "presets";

export default function ChartLab({ initialTf, digits, symbol, open, setOpen }: { initialTf: string; digits: number; symbol: string; open: boolean; setOpen: (v: boolean) => void }) {
  const [tf, setTf] = useState(TFS.includes(initialTf) ? initialTf : "M5");
  const [cfg, setCfgState] = useState<LabCfg>(loadCurrent);
  const setCfg = (c: LabCfg) => { setCfgState(c); saveCurrent(c); };
  const [tab, setTab] = useState<Tab>("chart");
  const [presets, setPresetsState] = useState(loadPresets);
  const [pname, setPname] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const g = usePolled<any>(`/api/v1/candles?tf=${tf}`, 15000);
  const raw: any[] = g.d?.bars || [];
  // 1.40 performance: the poll returns a new object every 15 s even when nothing changed - the chart is rebuilt only when the bars change
  // (count, last bar time and close of the last two bars), never on an identical poll.
  const sig = raw.length ? `${raw.length}|${raw[raw.length - 1]?.open_utc}|${raw[raw.length - 1]?.c}|${raw[raw.length - 2]?.c}` : "";
  const bars = useMemo(() => toBars(raw), [sig]);                      // eslint-disable-line react-hooks/exhaustive-deps
  const vsrc = useMemo(() => volumeSource(raw), [sig]);                // eslint-disable-line react-hooks/exhaustive-deps
  const sessBars = useMemo(() => lastSessionBars(bars, cfg.svp.session), [bars, cfg.svp.session]);
  const prof = useMemo(() => (cfg.ind.svp.on ? volumeProfile(sessBars, cfg.svp.bins, cfg.svp.va) : null), [sessBars, cfg.ind.svp.on, cfg.svp.bins, cfg.svp.va]);
  const imp = useMemo(() => (cfg.svp.showImpulse ? biggestImpulse(sessBars, cfg.svp.impulse) : null), [sessBars, cfg.svp.showImpulse, cfg.svp.impulse]);
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const [panes, setPanes] = useState(1);

  useEffect(() => { if (!note) return; const t = setTimeout(() => setNote(null), 4000); return () => clearTimeout(t); }, [note]);

  // one chart per configuration (type / theme / indicators / panes); data refresh re-uses the same build (new series data only)
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const th = THEMES[cfg.theme];
    const c = createChart(el, { autoSize: true, layout: { background: { type: ColorType.Solid, color: th.bg }, textColor: th.text, attributionLogo: false, panes: { separatorColor: th.grid } },
      grid: { vertLines: { visible: cfg.grid, color: th.grid }, horzLines: { visible: cfg.grid, color: th.grid } },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 4 }, rightPriceScale: { borderVisible: false }, crosshair: { mode: 0 } });
    chart.current = c;
    const I = cfg.ind;
    const src = cfg.type === "HEIKIN_ASHI" ? heikinAshi(bars) : bars;
    let price: ISeriesApi<any>;
    if (cfg.type === "LINE") {
      price = c.addSeries(LineSeries, { color: cfg.up, lineWidth: cfg.lineWidth as any, priceLineVisible: true });
      price.setData(src.map((b) => ({ time: T(b.time), value: b.c })));
    } else if (cfg.type === "AREA") {
      price = c.addSeries(AreaSeries, { lineColor: cfg.up, topColor: cfg.up + "55", bottomColor: cfg.up + "00", lineWidth: cfg.lineWidth as any });
      price.setData(src.map((b) => ({ time: T(b.time), value: b.c })));
    } else {
      const hollow = cfg.type === "HOLLOW";
      price = c.addSeries(CandlestickSeries, { upColor: hollow ? "rgba(0,0,0,0)" : cfg.up, downColor: cfg.down, borderUpColor: cfg.up, borderDownColor: cfg.down,
        wickUpColor: cfg.up, wickDownColor: cfg.down, priceFormat: { type: "price", precision: digits, minMove: 1 / 10 ** digits } });
      price.setData(src.map((b) => ({ time: T(b.time), open: b.o, high: b.h, low: b.l, close: b.c })));
    }
    const line = (data: { time: number; value: number }[], color: string, width: number, pane = 0, dashed = false, title = "") => {
      const s = c.addSeries(LineSeries, { color, lineWidth: width as any, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false, lastValueVisible: !!title, title,
        crosshairMarkerVisible: false }, pane);
      s.setData(data.map((p) => ({ time: T(p.time), value: p.value })));
      return s;
    };
    if (I.ema1.on) line(ema(bars, I.ema1.period), I.ema1.color, I.ema1.width, 0, false, `EMA ${I.ema1.period}`);
    if (I.ema2.on) line(ema(bars, I.ema2.period), I.ema2.color, I.ema2.width, 0, false, `EMA ${I.ema2.period}`);
    if (I.vwap.on) line(vwapDaily(bars), I.vwap.color, I.vwap.width, 0, false, "VWAP");
    if (I.bb.on) { const b = bollinger(bars, I.bb.period); line(b.mid, I.bb.color, I.bb.width, 0, true); line(b.up, I.bb.color, I.bb.width); line(b.lo, I.bb.color, I.bb.width); }
    let pane = 0;
    if (I.rsi.on) { pane++; const s = line(rsi(bars, I.rsi.period), I.rsi.color, I.rsi.width, pane, false, `RSI ${I.rsi.period}`);
      s.createPriceLine({ price: 70, color: "rgba(255,93,108,.6)", lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "" });
      s.createPriceLine({ price: 30, color: "rgba(57,255,143,.6)", lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "" }); }
    if (I.macd.on) { pane++; const m = macd(bars);
      const h = c.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      h.setData(m.hist.map((p) => ({ time: T(p.time), value: p.value, color: p.value >= 0 ? cfg.up + "aa" : cfg.down + "aa" })));
      line(m.macd, I.macd.color, I.macd.width, pane, false, "MACD"); line(m.signal, "#ffcf5c", 1, pane, false, "signal"); }
    if (I.atr.on) { pane++; line(atr(bars, I.atr.period), I.atr.color, I.atr.width, pane, false, `ATR ${I.atr.period}`); }
    try { const ps = c.panes(); for (let i = 1; i < ps.length; i++) ps[i].setHeight(90); } catch { /* older pane API */ }
    setPanes(pane + 1);
    // SVP levels + impulse + SMC
    if (prof) {
      price.createPriceLine({ price: prof.poc, color: "#ffcf5c", lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "SVP POC" });
      price.createPriceLine({ price: prof.vah, color: I.svp.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "VAH" });
      price.createPriceLine({ price: prof.val, color: I.svp.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "VAL" });
    }
    const marks: SeriesMarker<Time>[] = [];
    if (imp) {
      const col = imp.dir === "BUY" ? cfg.up : cfg.down;
      price.createPriceLine({ price: imp.high, color: col, lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: false, title: `IMPULS ${imp.dir} H` });
      price.createPriceLine({ price: imp.low, color: col, lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: false, title: `IMPULS ${imp.dir} L` });
      marks.push({ time: T(imp.from), position: imp.dir === "BUY" ? "belowBar" : "aboveBar", color: col, shape: "circle", text: `start ${cfg.svp.impulse}` });
      marks.push({ time: T(imp.to), position: imp.dir === "BUY" ? "aboveBar" : "belowBar", color: col, shape: imp.dir === "BUY" ? "arrowUp" : "arrowDown", text: `IMPULS ${imp.dir}` });
    }
    if (I.smc.on) {
      const s = smc(bars, I.smc.period);
      for (const e of s.events.slice(-30)) marks.push({ time: T(e.time), position: e.dir === "UP" ? "aboveBar" : "belowBar", color: I.smc.color, shape: "square", text: `${e.kind}${e.dir === "UP" ? "↑" : "↓"}`, size: 0.6 });
    }
    marks.sort((a, b) => (a.time as number) - (b.time as number));
    if (marks.length) createSeriesMarkers(price, marks);
    el.dataset.series = String(c.panes ? c.panes().length : 1);
    return () => { chart.current = null; c.remove(); };
  }, [cfg, bars, prof, imp, digits]);

  // ---- presets
  const savePreset = () => {
    const n = pname.trim().slice(0, 40);
    if (!n) { setNote("Podaj nazwę presetu"); return; }
    const p = { ...presets, [n]: cfg }; setPresetsState(p); savePresets(p); setNote(`Zapisano preset „${n}”`);
  };
  const delPreset = (n: string) => { const p = { ...presets }; delete p[n]; setPresetsState(p); savePresets(p); };
  const exportCfg = () => {
    const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" });
    const u = URL.createObjectURL(blob), a = document.createElement("a"); a.href = u; a.download = "WTC_PEPE_ChartLab_preset.json"; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1500);
  };
  const importCfg = async (f: File | undefined) => {
    if (!f) return;
    try { setCfg(sanitizeLab(JSON.parse(await f.text()))); setNote("Zaimportowano preset"); } catch (e: any) { setNote(`Import odrzucony: ${e?.message || e}`); }
  };
  const setInd = (k: IndKey, patch: Partial<LabCfg["ind"][IndKey]>) => setCfg({ ...cfg, ind: { ...cfg.ind, [k]: { ...cfg.ind[k], ...patch } } });

  const noTime = raw.length > 0 && bars.length === 0;
  const maxVol = prof ? Math.max(...prof.bins.map((b) => b.vol)) || 1 : 1;
  return (
    <section className="tw-card wtc-lab" data-testid="wtc-chartlab" aria-label="Chart Lab 2.1">
      <header className="tw-card-h">
        <h2><span className="tw-ico">✦</span>CHART LAB 2.1 · {symbol} · {tf} <small>Session Volume Profile</small></h2>
        <span className="tw-grow" />
        <label className="tw-field sm"><span className="sr">Interwał</span>
          <select value={tf} onChange={(e) => setTf(e.target.value)} data-testid="wtc-lab-tf" aria-label="Interwał Chart Lab">{TFS.map((t) => <option key={t}>{t}</option>)}</select></label>
        <button type="button" className={cls("tw-btn sm acc", open && "on")} aria-expanded={open} onClick={() => setOpen(!open)} data-testid="wtc-lab-customize">⚙ CUSTOMIZE CHART</button>
      </header>
      {note && <div className="tw-msg" role="status" data-testid="wtc-lab-note">{note}</div>}
      <div className={cls("wtc-lab-row", open && "open")}>
        <div className="wtc-lab-chart" ref={box} data-testid="wtc-lab-chart" data-bars={bars.length} data-type={cfg.type} data-panes={panes} data-theme={cfg.theme}
          data-poc={prof ? prof.poc.toFixed(digits) : ""} />
        {cfg.ind.svp.on && (
          <aside className="wtc-lab-svp" data-testid="wtc-lab-svp" aria-label="Session Volume Profile">
            <header>SVP · {SESSION_LABEL[cfg.svp.session]}</header>
            {prof ? (
              <>
                <svg viewBox={`0 0 100 ${prof.bins.length}`} preserveAspectRatio="none" role="img" aria-label={`POC ${fmt(prof.poc, digits)}`}>
                  {[...prof.bins].reverse().map((b, i) => {
                    const inVa = b.price >= prof.val && b.price <= prof.vah, poc = Math.abs(b.price - prof.poc) < prof.binSize / 2;
                    const wu = (b.up / maxVol) * 100, wd = (b.down / maxVol) * 100;
                    return <g key={i} opacity={inVa ? 1 : .45}>
                      <rect x={100 - wu - wd} y={i} width={wd} height={.82} fill={poc ? "#ffcf5c" : cfg.down} />
                      <rect x={100 - wu} y={i} width={wu} height={.82} fill={poc ? "#ffcf5c" : cfg.up} /></g>;
                  })}
                </svg>
                <ul>
                  <li>VAH <b>{fmt(prof.vah, digits)}</b></li>
                  <li className="poc">POC <b data-testid="wtc-lab-poc">{fmt(prof.poc, digits)}</b></li>
                  <li>VAL <b>{fmt(prof.val, digits)}</b></li>
                </ul>
              </>) : <p className="tw-na" data-testid="wtc-lab-svp-na">{bars.length ? `Brak świec sesji ${SESSION_LABEL[cfg.svp.session]} w oknie ${tf}` : "Brak danych"}</p>}
          </aside>)}
        {open && (
          <aside className="wtc-lab-cfg" data-testid="wtc-lab-panel" aria-label="Customize chart">
            <div className="tw-seg wide" role="tablist">
              {([["chart", "Wykres"], ["ind", "Wskaźniki"], ["svp", "SVP / Impuls"], ["presets", "Presety"]] as [Tab, string][]).map(([k, l]) => (
                <button key={k} type="button" role="tab" aria-selected={tab === k} className={cls(tab === k && "on")} onClick={() => setTab(k)} data-testid={`wtc-lab-tab-${k}`}>{l}</button>))}
            </div>
            {tab === "chart" && (
              <div className="wtc-lab-form">
                <label>Motyw<select value={cfg.theme} onChange={(e) => setCfg({ ...cfg, theme: e.target.value as any })} data-testid="wtc-lab-theme">
                  {Object.entries(THEMES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
                <div className="tw-seg" role="group" aria-label="Typ wykresu">
                  {CHART_TYPES.map(([t, l]) => <button key={t} type="button" className={cls(cfg.type === t && "on")} aria-pressed={cfg.type === t} onClick={() => setCfg({ ...cfg, type: t })} data-testid={`wtc-lab-type-${t}`}>{l}</button>)}
                </div>
                <label>Świeca wzrostowa<input type="color" value={cfg.up} onChange={(e) => setCfg({ ...cfg, up: e.target.value })} /></label>
                <label>Świeca spadkowa<input type="color" value={cfg.down} onChange={(e) => setCfg({ ...cfg, down: e.target.value })} /></label>
                <label>Grubość linii (Line / Area)<input type="range" min={1} max={4} value={cfg.lineWidth} onChange={(e) => setCfg({ ...cfg, lineWidth: Number(e.target.value) })} /></label>
                <label className="chk"><input type="checkbox" checked={cfg.grid} onChange={(e) => setCfg({ ...cfg, grid: e.target.checked })} /> Siatka</label>
              </div>)}
            {tab === "ind" && (
              <table className="tw-tbl compact wtc-lab-ind">
                <thead><tr><th>Wskaźnik</th><th>On</th><th>Okres</th><th>Kolor</th><th>Grub.</th></tr></thead>
                <tbody>{(Object.keys(IND_META) as IndKey[]).map((k) => (
                  <tr key={k} data-ind={k}><td>{IND_META[k].label}{IND_META[k].pane === "osc" ? <small> · panel</small> : null}</td>
                    <td><input type="checkbox" checked={cfg.ind[k].on} onChange={(e) => setInd(k, { on: e.target.checked })} data-testid={`wtc-lab-ind-${k}`} aria-label={`${IND_META[k].label} włącz`} /></td>
                    <td>{IND_META[k].hasPeriod ? <input type="number" min={IND_META[k].min} max={IND_META[k].max} value={cfg.ind[k].period}
                      onChange={(e) => setInd(k, { period: Math.min(IND_META[k].max, Math.max(IND_META[k].min, Number(e.target.value) || IND_META[k].min)) })} data-testid={`wtc-lab-per-${k}`} aria-label={`${IND_META[k].label} okres`} /> : "—"}</td>
                    <td><input type="color" value={cfg.ind[k].color} onChange={(e) => setInd(k, { color: e.target.value })} aria-label={`${IND_META[k].label} kolor`} /></td>
                    <td><select value={cfg.ind[k].width} onChange={(e) => setInd(k, { width: Number(e.target.value) })} aria-label={`${IND_META[k].label} grubość`}>{[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</select></td></tr>))}
                </tbody>
              </table>)}
            {tab === "svp" && (
              <div className="wtc-lab-form">
                <label>Sesja<select value={cfg.svp.session} onChange={(e) => setCfg({ ...cfg, svp: { ...cfg.svp, session: e.target.value as Session } })} data-testid="wtc-lab-session">
                  {(Object.keys(SESSION_LABEL) as Session[]).map((s) => <option key={s} value={s}>{SESSION_LABEL[s]}</option>)}</select></label>
                <div className="tw-seg" role="group" aria-label="Okno impulsu"><span>Impuls</span>
                  {([3, 5, 8, 12] as const).map((n) => <button key={n} type="button" className={cls(cfg.svp.impulse === n && "on")} aria-pressed={cfg.svp.impulse === n}
                    onClick={() => setCfg({ ...cfg, svp: { ...cfg.svp, impulse: n } })} data-testid={`wtc-lab-imp-${n}`}>{n}</button>)}</div>
                <label className="chk"><input type="checkbox" checked={cfg.svp.showImpulse} onChange={(e) => setCfg({ ...cfg, svp: { ...cfg.svp, showImpulse: e.target.checked } })} /> Pokaż największy impuls</label>
                <label>Liczba przedziałów ceny<input type="number" min={12} max={120} value={cfg.svp.bins} onChange={(e) => setCfg({ ...cfg, svp: { ...cfg.svp, bins: Math.min(120, Math.max(12, Number(e.target.value) || 48)) } })} /></label>
                <label>Value Area<select value={cfg.svp.va} onChange={(e) => setCfg({ ...cfg, svp: { ...cfg.svp, va: Number(e.target.value) } })}>{[0.6, 0.68, 0.7, 0.8].map((v) => <option key={v} value={v}>{Math.round(v * 100)}%</option>)}</select></label>
                <p className="tw-note">Godziny sesji w UTC (stałe, bez czasu letniego). Profil = wolumen ({vsrc}) rozłożony równo na High–Low świecy – przybliżenie z OHLC, nie footprint. Kierunek (zielony/czerwony) to proxy ze świec wzrostowych/spadkowych, nie agresja bid/ask.</p>
              </div>)}
            {tab === "presets" && (
              <div className="wtc-lab-form">
                <label>Nazwa presetu<input value={pname} maxLength={40} onChange={(e) => setPname(e.target.value)} data-testid="wtc-lab-pname" placeholder="np. Scalp M5" /></label>
                <div className="tw-row">
                  <button type="button" className="tw-btn sm acc" onClick={savePreset} data-testid="wtc-lab-psave">💾 Zapisz</button>
                  <button type="button" className="tw-btn sm" onClick={exportCfg} data-testid="wtc-lab-export">↓ Eksport JSON</button>
                  <label className="tw-btn sm">↑ Import JSON<input type="file" accept="application/json,.json" hidden onChange={(e) => { importCfg(e.target.files?.[0]); e.target.value = ""; }} data-testid="wtc-lab-import" /></label>
                  <button type="button" className="tw-btn sm" onClick={() => { setCfg(structuredClone(DEFAULT_LAB)); setNote("Przywrócono ustawienia domyślne"); }} data-testid="wtc-lab-reset">↺ Domyślne</button>
                </div>
                <ul className="wtc-lab-plist" data-testid="wtc-lab-presets">
                  {Object.keys(presets).length ? Object.keys(presets).map((n) => (
                    <li key={n}><button type="button" className="tw-btn xs" onClick={() => { setCfg(presets[n]); setNote(`Wczytano „${n}”`); }} data-testid="wtc-lab-pload">{n}</button>
                      <button type="button" className="tw-btn xs" aria-label={`Usuń preset ${n}`} onClick={() => delPreset(n)}>×</button></li>))
                    : <li className="tw-dim">Brak zapisanych presetów</li>}
                </ul>
              </div>)}
          </aside>)}
      </div>
      <div className="wtc-lab-foot" data-testid="wtc-lab-foot">
        <span>Źródło: <b>{g.err ? `błąd: ${g.err}` : noTime ? "brak czasu UTC świec (zegar serwera mierzony)" : `MT5 /api/v1/candles · ${bars.length} świec ${tf}`}</b></span>
        {prof && <span>SVP {SESSION_LABEL[cfg.svp.session]}: {prof.bars} świec · POC <b>{fmt(prof.poc, digits)}</b> · VA {fmt(prof.val, digits)}–{fmt(prof.vah, digits)} · wolumen: {vsrc}</span>}
        {imp && <span data-testid="wtc-lab-impulse">Największy impuls ({cfg.svp.impulse} św.): <b className={imp.dir === "BUY" ? "ok" : "bad"}>{imp.dir}</b> Δ {fmt(imp.delta, digits)} · {fmt(imp.low, digits)}–{fmt(imp.high, digits)} · {new Date(imp.from * 1000).toISOString().slice(5, 16).replace("T", " ")} UTC</span>}
        <span className="tw-dim">Wizualizacja – nie składa zleceń i nie zasila silnika.</span>
      </div>
    </section>);
}
