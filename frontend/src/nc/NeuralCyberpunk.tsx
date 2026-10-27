// Neural Cyberpunk workspace (handoff "PepeMarketWizard_Claude_Handoff_V1", 11 screens) built on the bot's REAL endpoints.
// Rule from the handoff: never display mock values as live. Every block shows the status of its source:
//   VERIFIED  data from the connected MT5 terminal (real account) / validated artefact
//   DEMO      data from the terminal SIMULATOR (--demo) - real code path, synthetic market
//   STALE     source connected but data older than the freshness limit
//   DISCONNECTED / UNAVAILABLE / NOT_IMPLEMENTED / NOT_RUN / ERROR - nothing is drawn as if it existed
// Nothing here sends an order. The only state change offered is the existing STOP (kill switch: stop new entries), the active
// instrument switch (same endpoint as the classic header) and SH config changes - all go through the backend's own checks.
import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, LineSeries, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { apiGet, apiSend } from "../api";
import LiquidityHeatmapPanel from "../components/LiquidityHeatmapPanel";
import { TrainingPanel } from "../components/ShPanels";
import { navigate, type Route } from "../router";
import { useStore } from "../store";
import { useUi } from "../ui";
import { fmtNum } from "../util";
import NeuralBrain from "./NeuralBrain";
import MasterModels from "./MasterModels";
import "./nc.css";

export const NC_PAGES = [
  { id: "dashboard", n: "01", label: "Dashboard", title: "AI Command Center", icon: "◈" },
  { id: "market", n: "02", label: "Market Analysis", title: "Market Analysis", icon: "▥" },
  { id: "pattern", n: "03", label: "Pattern Intelligence", title: "Pattern Intelligence", icon: "◇" },
  { id: "validation", n: "04", label: "Validation & OOS", title: "Validation & Learning", icon: "▤" },
  { id: "training", n: "05", label: "Neural Training", title: "Neural Training Center", icon: "◎" },
  { id: "decision", n: "06", label: "AI Decision", title: "AI Decision & Execution", icon: "⚡" },
  { id: "mt5", n: "07", label: "MT5 & Safety", title: "MT5 Bridge & Safety", icon: "⛨" },
  { id: "liquidity", n: "08", label: "Liquidity & Flow", title: "Liquidity & Order Flow", icon: "◉" },
  { id: "statistics", n: "09", label: "Statistics", title: "Statistics & Performance", icon: "▦" },
  { id: "operations", n: "10", label: "System Monitor", title: "Operations Center", icon: "⌁" },
  { id: "settings", n: "11", label: "Settings", title: "Settings & Users", icon: "⚙" },
  { id: "models", n: "12", label: "Master Models", title: "Master Models (SHADOW)", icon: "⬡" },
] as const;
type NcPage = (typeof NC_PAGES)[number]["id"];
const TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

// ------------------------------------------------------------------------------------------------ shared helpers
export type SrcStatus = "VERIFIED" | "DEMO" | "STALE" | "DISCONNECTED" | "UNAVAILABLE" | "NOT_IMPLEMENTED" | "NOT_RUN" | "ERROR" | "LOCKED" | "PARTIAL";
const TONE: Record<string, string> = { VERIFIED: "g", DEMO: "p", STALE: "y", DISCONNECTED: "r", UNAVAILABLE: "y", NOT_IMPLEMENTED: "y", NOT_RUN: "y",
  ERROR: "r", LOCKED: "r", PARTIAL: "y" };
export function St({ s, children }: { s: SrcStatus | string; children?: any }) {
  return <span className={`nc-st ${TONE[s] || "y"}`} data-status={s}>{children ?? s}</span>;
}
/** Status of the market feed: DEMO when the bot runs on the terminal simulator, VERIFIED only for a connected real terminal with a fresh quote. */
export function feedStatus(s: any): SrcStatus {
  if (s?.connection?.state !== "CONNECTED") return "DISCONNECTED";
  if (s?.synthetic) return "DEMO";
  const age = s?.quote?.age_seconds;
  if (age === null || age === undefined || age > 10) return "STALE";
  return "VERIFIED";
}
function usePoll<T = any>(path: string | null, ms = 5000): [T | null, string | null] {
  const [d, setD] = useState<T | null>(null);
  const [e, setE] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    const load = () => apiGet<T>(path).then((r) => { if (alive) { setD(r); setE(null); } }).catch((x) => alive && setE(String(x?.message || x)));
    load();
    const t = setInterval(load, ms);
    return () => { alive = false; clearInterval(t); };
  }, [path, ms]);
  return [d, e];
}
const Panel = ({ title, right, children, id }: { title: any; right?: any; children: any; id?: string }) => (
  <section className="nc-panel" data-testid={id}><div className="nc-ph"><span>{title}</span><div className="nc-ctrl">{right}</div></div><div className="nc-body">{children}</div></section>);
const Kpi = ({ label, value, tone = "", st }: { label: string; value: any; tone?: string; st?: SrcStatus | string }) => (
  <div className="nc-kpi"><div className="nc-small">{label}</div><div className={`nc-big ${tone}`}>{value ?? "—"}</div>{st && <St s={st} />}</div>);
const Line = ({ a, b }: { a: any; b: any }) => <div className="nc-line"><span>{a}</span><strong>{b ?? "—"}</strong></div>;
const Note = ({ children }: { children: any }) => <div className="nc-note">{children}</div>;
const ema = (v: number[], p: number) => { let prev = v[0]; const k = 2 / (p + 1); return v.map((x) => (prev = prev + (x - prev) * k)); };
const ep = (iso: string) => Math.floor(Date.parse(iso) / 1000) as Time;
const useGlobal = (key: string, def: string): [string, (v: string) => void] => {
  const [v, setV] = useState<string>(() => { try { return localStorage.getItem(key) || def; } catch { return def; } });
  return [v, (x: string) => { setV(x); try { localStorage.setItem(key, x); } catch { /* storage unavailable */ } }];
};

// ------------------------------------------------------------------------------------------------ candle chart (lightweight-charts)
function NcChart({ tf, height = 340, mini = false, emaOn = true, overlaysOn = true, levels, onPickLevel, testId }: {
  tf: string; height?: number; mini?: boolean; emaOn?: boolean; overlaysOn?: boolean; levels?: number[]; onPickLevel?: (p: number) => void; testId?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const ser = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const e20 = useRef<ISeriesApi<"Line"> | null>(null);
  const e50 = useRef<ISeriesApi<"Line"> | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  const pick = useRef(onPickLevel);
  pick.current = onPickLevel;
  const [d] = usePoll<any>(`/api/v1/candles?tf=${tf}&limit=${mini ? 120 : 400}`, mini ? 10000 : 4000);
  const [ohlc, setOhlc] = useState<string>("");
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, { autoSize: true, layout: { background: { type: ColorType.Solid, color: "#0c1426" }, textColor: "#93a4c1", fontSize: 10 },
      grid: { vertLines: { color: "#1b2640" }, horzLines: { color: "#1b2640" } }, crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, visible: !mini }, rightPriceScale: { visible: !mini }, handleScroll: !mini, handleScale: !mini,
      localization: { timeFormatter: (t: number) => new Date(t * 1000).toISOString().slice(5, 16).replace("T", " ") + " UTC" } });
    chart.current = c;
    ser.current = c.addSeries(CandlestickSeries, { upColor: "#41e1b4", downColor: "#fb849e", borderUpColor: "#41e1b4", borderDownColor: "#fb849e",
      wickUpColor: "#41e1b4", wickDownColor: "#fb849e" });
    e20.current = c.addSeries(LineSeries, { color: "#b49aff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    e50.current = c.addSeries(LineSeries, { color: "#f0c582", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    if (!mini) {
      c.subscribeCrosshairMove((p) => {
        const b: any = p.seriesData.get(ser.current!);
        if (b) setOhlc(`O ${fmtNum(b.open)} H ${fmtNum(b.high)} L ${fmtNum(b.low)} C ${fmtNum(b.close)}`);
      });
      c.subscribeClick((p) => { if (pick.current && p.point) { const pr = ser.current!.coordinateToPrice(p.point.y); if (pr !== null) pick.current(Number(pr)); } });
    }
    return () => { c.remove(); chart.current = null; lines.current = []; };
  }, [mini]);
  useEffect(() => {
    const s = ser.current;
    if (!s || !d?.bars) return;
    const bars = d.bars.filter((b: any) => b.open_utc && b.closed !== false);
    s.setData(bars.map((b: any) => ({ time: ep(b.open_utc), open: b.o, high: b.h, low: b.l, close: b.c })));
    const closes = bars.map((b: any) => b.c);
    const mk = (vals: number[]) => vals.map((v, i) => ({ time: ep(bars[i].open_utc), value: v }));
    e20.current!.setData(emaOn && closes.length ? mk(ema(closes, 20)) : []);
    e50.current!.setData(emaOn && closes.length ? mk(ema(closes, 50)) : []);
    lines.current.forEach((l) => s.removePriceLine(l));
    lines.current = [];
    const add = (price: number, title: string, color: string, style = LineStyle.Dotted) =>
      lines.current.push(s.createPriceLine({ price, title, color, lineStyle: style, lineWidth: 1, axisLabelVisible: !mini }));
    if (overlaysOn && !mini && d.overlays) {
      (d.overlays.fvgs || []).slice(-3).forEach((f: any) => { add(f.high, `FVG ${f.direction}`, "#76dcfc"); add(f.low, "", "#76dcfc"); });
      (d.overlays.order_blocks || []).slice(-2).forEach((o: any) => { add(o.high, `OB ${o.direction}`, "#b49aff"); add(o.low, "", "#b49aff"); });
      (d.overlays.sweeps || []).slice(-2).forEach((w: any) => add(w.level, `sweep ${w.side}`, "#f4c883"));
      (d.overlays.breaks || []).slice(-2).forEach((b: any) => add(b.level, `${b.kind} ${b.direction}`, "#46e2b6", LineStyle.Dashed));
    }
    (levels || []).forEach((p, i) => add(p, `poziom ${i + 1}`, "#f4c883", LineStyle.Solid));
  }, [d, emaOn, overlaysOn, JSON.stringify(levels)]);
  const q = d?.quality;
  return (<div data-testid={testId}>
    <div ref={box} style={{ height }} className="nc-chart" />
    {!mini && <div className="nc-small nc-row">{ohlc || "Kółko: zoom · przeciągnij: przesuwanie · najedź: OHLC"}
      <span>{d?.symbol} {tf} · świece zamknięte {q?.closed_bars ?? "—"} · {q?.stale ? <St s="STALE" /> : q ? <St s="VERIFIED">jakość {q.status}</St> : null}</span></div>}
  </div>);
}

// ------------------------------------------------------------------------------------------------ neural system (brain of neurons; modules from the registry)
function NeuralSystem({ inst }: { inst: string }) {
  const [reg] = usePoll<any>(`/api/v1/training/models?instrument=${inst}`, 15000);
  const [full, setFull] = useState(false);
  const ms: any[] = reg?.models || [];
  const ready = ms.filter((n) => n.readiness === "READY" || n.readiness === "DETERMINISTIC_OK").length;
  useEffect(() => {
    if (!full) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && setFull(false);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [full]);
  return (
    <section className={`nc-panel ${full ? "nc-full" : ""}`} data-testid="nc-neural">
      <div className="nc-ph"><span>◎ NEURAL SYSTEM – mózg modułów {inst} <St s={reg ? "VERIFIED" : "UNAVAILABLE"}>{reg ? "stan z rejestru" : "brak danych"}</St></span>
        <div className="nc-ctrl"><span className="nc-small">moduły gotowe {ready}/{ms.length} · tryb {reg?.mode || "—"}</span>
          <button className="nc-btn" onClick={() => setFull(!full)} data-testid="nc-neural-full">{full ? "✕ Zamknij (Esc)" : "⛶ Pełny ekran"}</button></div></div>
      <NeuralBrain models={ms} mode={reg?.mode} height={full ? Math.max(420, window.innerHeight - 150) : 640} />
    </section>);
}

// ------------------------------------------------------------------------------------------------ screens
function Dashboard({ ctx }: { ctx: Ctx }) {
  const { s, sh, strat } = ctx;
  const card = (k: string) => {
    const ev = sh?.last_eval?.[k];
    const ready = ev?.status === "READY";
    return (<Panel id={`nc-watch-${k}`} title={<>{ev?.side === "SELL" ? "▼" : "▲"} {k} · {sh?.instrument}</>} right={<St s={ready ? (s.synthetic ? "DEMO" : "VERIFIED") : "NOT_RUN"}>{ev?.status || "BRAK OCENY"}</St>}>
      {!ev && <p className="nc-small">Brak oceny – czekam na zamkniętą świecę M1.</p>}
      {ev && !ready && <p className="nc-small">{ev.status_reason}</p>}
      {ready && <><Line a="Kierunek / tryb" b={`${ev.side} · ${ev.mode}`} /><Line a="Wejście (ref.)" b={ev.entry_ref} /><Line a="SL" b={ev.sl} />
        <Line a="TP1 / TP2 / TP3" b={(ev.tps || []).map((t: any) => t.price).join(" / ")} />
        <Line a="Score (heurystyka)" b={`${fmtNum(ev.score?.value, 0)}/100`} /></>}
    </Panel>);
  };
  return (<>
    <div className="nc-two">{card("SCALPING")}{card("HEDGING")}</div>
    <div className="nc-grid nc-gap">
      <Kpi label="POŁĄCZENIE MT5" value={s.connection?.state} tone={s.connection?.state === "CONNECTED" ? "green" : "red"} st={feedStatus(s)} />
      <Kpi label="AKTYWNY SYMBOL" value={s.symbol?.symbol} tone="purple" st={s.symbol?.status === "OK" || s.symbol?.status === "READY" ? (s.synthetic ? "DEMO" : "VERIFIED") : s.symbol?.status} />
      <Kpi label="STRATEGIA" value={strat} tone="cyan" st={sh?.models?.mode === "PEŁNA" ? "VERIFIED" : "PARTIAL"} />
      <Kpi label="WYKONANIE" value={execView(s).label} tone={execView(s).tone} st={execView(s).st} />
    </div>
    <div className="nc-gap"><NeuralSystem inst={sh?.instrument || "XAUUSD"} /></div>
    <div className="nc-two nc-gap">
      <Panel id="nc-checklist" title={`AI DECISION INTELLIGENCE · ${strat}`} right={<St s={sh?.last_eval?.[strat] ? (s.synthetic ? "DEMO" : "VERIFIED") : "NOT_RUN"} />}>
        {(sh?.last_eval?.[strat]?.checklist || []).map((c: any) => <Line key={c.id} a={c.label} b={<span className={c.status === "PASS" ? "green" : c.status === "FAIL" ? "red" : "gold"}>{c.status} <span className="nc-small">{c.detail}</span></span>} />)}
        {!sh?.last_eval?.[strat] && <p className="nc-small">Brak oceny setupu.</p>}
        <Note>Checklista to wynik deterministycznego silnika setupu bota (nie opis z modelu językowego). Score nie jest prawdopodobieństwem.</Note>
      </Panel>
      <Panel title="MARKET SNAPSHOT" right={<St s={feedStatus(s)} />}><NcChart tf="M5" height={260} overlaysOn={false} testId="nc-dash-chart" /></Panel>
    </div>
  </>);
}

function Market({ ctx }: { ctx: Ctx }) {
  const { s, tf, setTf } = ctx;
  const [emaOn, setEma] = useState(true);
  const [ovl, setOvl] = useState(true);
  const [draw, setDraw] = useState(false);
  const [levels, setLevels] = useState<number[]>([]);
  const [an] = usePoll<any>("/api/v1/analytics", 15000);
  const q = s.quote;
  return (<>
    <div className="nc-grid">
      <Kpi label="SYMBOL" value={s.symbol?.symbol} tone="purple" /><Kpi label="INTERWAŁ" value={tf} tone="cyan" />
      <Kpi label="BID / ASK" value={q ? `${q.bid} / ${q.ask}` : null} st={feedStatus(s)} />
      <Kpi label="SPREAD / WIEK" value={q ? `${fmtNum(q.spread, 2)} · ${fmtNum(q.age_seconds, 1)} s` : null} tone="gold" />
    </div>
    <Panel id="nc-market" title="▥ ADVANCED CANDLESTICK WORKSPACE" right={TFS.map((x) => <button key={x} className={`nc-btn ${x === tf ? "on" : ""}`} onClick={() => setTf(x)} data-testid={`nc-tf-${x}`}>{x}</button>)}>
      <div className="nc-ctrl nc-mb">
        <button className={`nc-btn ${emaOn ? "on" : ""}`} onClick={() => setEma(!emaOn)}>EMA 20/50</button>
        <button className={`nc-btn ${ovl ? "on" : ""}`} onClick={() => setOvl(!ovl)}>FVG / OB / sweep / BOS-CHoCH</button>
        <button className={`nc-btn ${draw ? "on" : ""}`} onClick={() => setDraw(!draw)} data-testid="nc-draw">{draw ? "Kliknij wykres…" : "Rysuj poziom"}</button>
        <button className="nc-btn" onClick={() => setLevels([])}>Wyczyść poziomy</button>
        <span className="nc-small">EMA liczone w przeglądarce z zamkniętych świec MT5; strefy z silnika struktury bota (M03).</span>
      </div>
      <NcChart tf={tf} emaOn={emaOn} overlaysOn={ovl} levels={levels} onPickLevel={draw ? (p) => { setLevels([...levels, Number(p.toFixed(2))]); setDraw(false); } : undefined} testId="nc-main-chart" />
    </Panel>
    <div className="nc-three nc-gap">{["M1", "M5", "M15", "M30", "H1", "H4"].map((x) => (
      <section key={x} className="nc-panel nc-click" onClick={() => setTf(x)} data-minitf={x}><div className="nc-ph">{x} · wybierz</div><NcChart tf={x} mini height={130} /></section>))}</div>
    <div className="nc-two nc-gap">
      <Panel title="WSKAŹNIKI">
        <Line a="EMA 20/50" b={<St s="VERIFIED">obliczane z barów</St>} />
        <Line a="Bollinger / MA (silnik bota)" b={<St s={an ? "VERIFIED" : "UNAVAILABLE"}>{an ? "dostępne – zakładka Indykatory BB/MA" : "brak"}</St>} />
        <Line a="FFT / EMD / VMD" b={<St s={an?.timeframes ? "VERIFIED" : "UNAVAILABLE"}>{an?.timeframes ? `TF: ${Object.keys(an.timeframes).join(", ")}` : "brak"}</St>} />
        <Line a="VWAP / RSI / MACD" b={<St s="NOT_IMPLEMENTED" />} />
      </Panel>
      <Panel title="STRUKTURA CENY">
        <Line a="Źródło notowań" b={<St s={feedStatus(s)}>{q?.source || "—"}</St>} />
        <Line a="Czas notowania (UTC)" b={q?.time_utc} />
        <Line a="Specyfikacja symbolu" b={s.symbol?.info ? `tick ${s.symbol.info.trade_tick_size} · cyfry ${s.symbol.info.digits}` : "—"} />
      </Panel>
    </div>
  </>);
}

// 36 names from the handoff mapped to the bot's REAL detector ids (analysis/candles.py, chart_patterns.py, M03 structure)
const PATTERNS: [string, string[] | null, string][] = [
  ["Bullish Engulfing", ["ENGULFING_BULL"], "świece"], ["Bearish Engulfing", ["ENGULFING_BEAR"], "świece"], ["Hammer", ["HAMMER"], "świece"],
  ["Shooting Star", ["SHOOTING_STAR"], "świece"], ["Doji", ["DOJI", "LONG_LEGGED_DOJI"], "świece"], ["Inside Bar", ["INSIDE_BAR", "INSIDE_BAR_BREAK_UP", "INSIDE_BAR_BREAK_DOWN"], "świece"],
  ["Outside Bar", ["OUTSIDE_BAR_EXPANSION", "OUTSIDE_BAR_REJECTION"], "świece"], ["Bullish Pin Bar", ["PIN_BAR_BULL"], "świece"], ["Bearish Pin Bar", ["PIN_BAR_BEAR"], "świece"],
  ["Morning Star", ["MORNING_STAR"], "świece"], ["Evening Star", ["EVENING_STAR"], "świece"], ["Three White Soldiers", ["THREE_WHITE_SOLDIERS"], "świece"],
  ["Three Black Crows", ["THREE_BLACK_CROWS"], "świece"], ["Bullish Harami", null, "świece"], ["Bearish Harami", null, "świece"], ["Piercing Line", null, "świece"],
  ["Dark Cloud Cover", null, "świece"], ["Marubozu", ["MARUBOZU_DISPLACEMENT"], "świece"], ["Tweezer Bottom", ["TWEEZER_BOTTOM"], "świece"], ["Tweezer Top", ["TWEEZER_TOP"], "świece"],
  ["Double Bottom", ["DOUBLE_BOTTOM"], "formacje"], ["Double Top", ["DOUBLE_TOP"], "formacje"], ["Head & Shoulders", ["HEAD_SHOULDERS"], "formacje"],
  ["Inverse Head & Shoulders", ["INVERSE_HEAD_SHOULDERS"], "formacje"], ["Ascending Triangle", ["TRIANGLE_ASCENDING"], "formacje"],
  ["Descending Triangle", ["TRIANGLE_DESCENDING"], "formacje"], ["Symmetrical Triangle", ["TRIANGLE_SYMMETRICAL"], "formacje"], ["Bull Flag", ["FLAG", "PENNANT"], "formacje"],
  ["Bear Flag", ["FLAG", "PENNANT"], "formacje"], ["Rising Wedge", ["WEDGE_RISING"], "formacje"], ["Falling Wedge", ["WEDGE_FALLING"], "formacje"],
  ["Rectangle Breakout", ["RECTANGLE"], "formacje"], ["Bullish Liquidity Sweep", ["SWEEP"], "struktura M03"], ["Bearish Liquidity Sweep", ["SWEEP"], "struktura M03"],
  ["Fair Value Gap", ["FVG"], "struktura M03"], ["Order Block Rejection", ["ORDER_BLOCK"], "struktura M03 (OB; reakcja = kontekst, nie osobny detektor)"],
];
function Pattern({ ctx }: { ctx: Ctx }) {
  const { s } = ctx;
  const [st] = usePoll<any>("/api/v1/structure", 8000);
  const [live] = usePoll<any>("/api/v1/patterns/live", 10000);
  const [cd] = usePoll<any>("/api/v1/candles?tf=M5&limit=200", 10000);
  const [sel, setSel] = useState(0);
  const [qry, setQry] = useState("");
  const detections: any[] = [...((st?.candles?.patterns) || []).map((p: any) => ({ ...p, src: "świece" })), ...((st?.chart?.patterns) || []).map((p: any) => ({ ...p, src: "formacje" }))];
  const pid = (p: any) => String(p.pattern_id || p.id || p.kind || p.type || p.name || "").toUpperCase();
  const ov = cd?.overlays || {};
  const struct = (ids: string[]) => ids.includes("FVG") ? (ov.fvgs || []) : ids.includes("ORDER_BLOCK") ? (ov.order_blocks || []) : ids.includes("SWEEP") ? (ov.sweeps || []) : null;
  const [name, ids, fam] = PATTERNS[sel];
  const hits = ids ? (struct(ids) ?? detections.filter((p) => ids.some((i) => pid(p).includes(i)))) : [];
  const impl = PATTERNS.filter((p) => p[1]).length;
  return (<>
    <div className="nc-grid">
      <Kpi label="WZORCE W BIBLIOTECE" value="36" tone="purple" /><Kpi label="Z DETEKTOREM W BOCIE" value={impl} tone="cyan" st="VERIFIED" />
      <Kpi label="WYKRYCIA (M5, teraz)" value={detections.length} tone="green" st={st ? (s.synthetic ? "DEMO" : "VERIFIED") : "UNAVAILABLE"} />
      <Kpi label="BOS / CHoCH (M5)" value={(ov.breaks || []).length} tone="gold" />
    </div>
    <div className="nc-two nc-gap">
      <Panel title="WYKRES WZORCÓW (M5)" right={<St s={feedStatus(s)} />}><NcChart tf="M5" height={320} testId="nc-pattern-chart" />
        <div className="nc-small">Wybrany: <b data-testid="nc-pattern-selected">{name}</b> · rodzina: {fam}</div></Panel>
      <Panel id="nc-patterns" title="BIBLIOTEKA 36 WZORCÓW">
        <input className="nc-input" placeholder="Szukaj wzorca" value={qry} onChange={(e) => setQry(e.target.value)} aria-label="Szukaj wzorca" />
        <div className="nc-scroll">{PATTERNS.map(([n, i], k) => n.toLowerCase().includes(qry.toLowerCase()) && (
          <button key={n} className={`nc-pattern ${k === sel ? "on" : ""}`} onClick={() => setSel(k)} data-impl={i ? "1" : "0"}>{String(k + 1).padStart(2, "0")} · {n}
            <div className="nc-small">{i ? `detektor bota: ${i.join(", ")}` : <St s="NOT_IMPLEMENTED">brak detektora w bocie</St>}</div></button>))}</div>
      </Panel>
    </div>
    <div className="nc-two nc-gap">
      <Panel title="WALIDACJA WZORCA">
        <Line a="Wzorzec" b={name} /><Line a="Detektor" b={ids ? <St s="VERIFIED">{ids.join(", ")}</St> : <St s="NOT_IMPLEMENTED" />} />
        <Line a="Aktualne wykrycia" b={ids ? hits.length : "—"} />
        <Line a="Historyczny win rate" b={<St s="NOT_RUN">brak walidacji OOS wzorca</St>} />
        <Line a="Skalibrowane prawdopodobieństwo" b={<St s="UNAVAILABLE" />} />
        <Note>Pojawienie się wzorca nie jest prawdopodobieństwem zysku. Stan (kandydat / potwierdzony / unieważniony) pochodzi z detektora bota.</Note>
      </Panel>
      <Panel title="WYKRYCIA I ZDARZENIA">
        <div className="nc-scroll small">{hits.slice(-12).reverse().map((h: any, i: number) => <Line key={i} a={pid(h) || h.direction || h.side || "zdarzenie"} b={`${h.state || h.status || ""} ${h.confirmed_at || h.formed_at || h.observed_at || h.available_at || ""}`} />)}
          {!hits.length && <p className="nc-small">Brak bieżących wykryć tego wzorca.</p>}
          {(live?.events || []).slice(0, 6).map((e: any) => <Line key={e.id} a={`Double Bottom ${e.timeframe}`} b={`${e.status} · ${e.available_at}`} />)}</div>
      </Panel>
    </div>
  </>);
}

function Validation({ ctx }: { ctx: Ctx }) {
  const inst = ctx.sh?.instrument || "XAUUSD";
  const [v] = usePoll<any>(`/api/v1/sh/validation?instrument=${inst}`, 30000);
  const [stats] = usePoll<any>("/api/v1/stats", 15000);
  const S = (k: string) => v?.strategies?.[k];
  const card = (k: string) => {
    const x = S(k);
    const r = x?.report;
    const m = r?.metrics || {};
    return (<Panel key={k} id={`nc-val-${k}`} title={`${k} · walidacja replay (${inst})`} right={<St s={x?.status === "VERIFIED_REPLAY" ? (r?.data_kind === "REAL_USER_DATA" ? "VERIFIED" : "DEMO") : x?.status || "NOT_RUN"} />}>
      {!r && <Note>{x?.reason || "Brak raportu."}</Note>}
      {r && <>
        <Line a="Plany (cykle)" b={m.n} /><Line a="Wartość oczekiwana netto [R]" b={`${fmtNum(m.expectancy, 3)} (90%: ${(m.ci90 || []).map((z: number) => fmtNum(z, 3)).join(" … ") || "—"})`} />
        <Line a="Profit factor / max DD [R]" b={`${fmtNum(m.profit_factor, 2)} / ${fmtNum(m.max_drawdown, 2)}`} />
        <Line a="Reguła naiwna (baseline) [R]" b={fmtNum(r.baseline?.expectancy, 3)} />
        <Line a="Foldy chronologiczne E[R]" b={(r.folds || []).map((f: any) => fmtNum(f.expectancy, 2)).join(" · ") || "—"} />
        {r.variants && <Line a="HEDGE / NO_HEDGE / REDUCE E[R]" b={["HEDGE", "NO_HEDGE", "REDUCE"].map((z) => fmtNum(r.variants[z]?.expectancy, 3)).join(" / ")} />}
        <Line a="Model zdarzenia" b={r.event_model?.verdict} />
        <div className="nc-small">{(r.limitations || []).join(" · ")}</div></>}
    </Panel>);
  };
  const b = stats?.bot?.all || {};
  return (<>
    <div className="nc-grid">
      <Kpi label="RAPORT SCALPING" value={S("SCALPING")?.status} st={S("SCALPING")?.status === "VERIFIED_REPLAY" ? "VERIFIED" : "NOT_RUN"} />
      <Kpi label="RAPORT HEDGING" value={S("HEDGING")?.status} st={S("HEDGING")?.status === "VERIFIED_REPLAY" ? "VERIFIED" : "NOT_RUN"} />
      <Kpi label={`TRANSAKCJE BOTA (${stats?.bot?.mode || "—"})`} value={b.trades ?? b.count ?? b.n ?? "—"} st={ctx.s.synthetic ? "DEMO" : "VERIFIED"} />
      <Kpi label="WALK-FORWARD" value="foldy w raporcie" tone="cyan" />
    </div>
    <div className="nc-two nc-gap">{card("SCALPING")}{card("HEDGING")}</div>
    <Panel title="ZASADY WAŻNOŚCI BADANIA"><Note>Raport pochodzi z replay na danych wyeksportowanych z terminala (ten sam kod co na żywo, konserwatywne świece,
      koszty, holdout użyty raz). Dane syntetyczne nigdy nie trafiają do raportu używanego przez bota. Brak raportu = brak walidacji – panel niczego nie dorysowuje.</Note></Panel>
  </>);
}

function Decision({ ctx }: { ctx: Ctx }) {
  const { s, sh, strat } = ctx;
  const ev = sh?.last_eval?.[strat];
  const info = s.symbol?.info || {};
  const [entry, setEntry] = useState<string>("");
  const [stop, setStop] = useState<string>("");
  const [riskPct, setRiskPct] = useState("0.5");
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { if (ev?.status === "READY") { setEntry(String(ev.entry_ref)); setStop(String(ev.sl)); } else if (s.quote && !entry) { setEntry(String(s.quote.ask)); } }, [ev?.signal_id]);
  const eq = Number(s.account?.equity) || 0;
  const tv = Number(info.trade_tick_value) || 0, ts = Number(info.trade_tick_size) || 0;
  const dist = Math.abs(Number(entry) - Number(stop));
  const budget = (eq * Number(riskPct)) / 100;
  const perLot = ts > 0 ? (dist * tv) / ts : NaN;
  const lots = perLot > 0 ? budget / perLot : NaN;
  const cfg = sh?.config?.instruments?.[sh?.instrument]?.[strat] || {};
  return (<>
    <div className="nc-grid">
      <Kpi label="SYGNAŁ" value={ev ? `${ev.status} ${ev.side || ""}` : "—"} tone="cyan" st={ev ? (s.synthetic ? "DEMO" : "VERIFIED") : "NOT_RUN"} />
      <Kpi label="STRATEGIA" value={strat} tone="purple" /><Kpi label="MT5" value={s.connection?.state} st={feedStatus(s)} />
      <Kpi label="WYKONANIE" value={execView(s).label} tone={execView(s).tone} st={execView(s).st} />
    </div>
    <div className="nc-two nc-gap">
      <Panel id="nc-risk" title="PLAN CENOWY I RYZYKO" right={<St s={info.trade_tick_value ? (s.synthetic ? "DEMO" : "VERIFIED") : "UNAVAILABLE"}>specyfikacja z terminala</St>}>
        <div className="nc-fields">
          <label>Wejście<input className="nc-input" value={entry} onChange={(e) => setEntry(e.target.value)} aria-label="Wejście" /></label>
          <label>Stop loss<input className="nc-input" value={stop} onChange={(e) => setStop(e.target.value)} aria-label="Stop loss" /></label>
          <label>Ryzyko %<input className="nc-input" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} aria-label="Ryzyko procent" /></label>
          <label>Equity ({s.account?.currency})<input className="nc-input" value={fmtNum(eq, 2)} disabled aria-label="Equity" /></label>
        </div>
        <Line a="Budżet ryzyka" b={fmtNum(budget, 2)} /><Line a="Strata na 1 lot przy SL (bez kosztów)" b={fmtNum(perLot, 2)} />
        <Line a="Wolumen orientacyjny" b={`${fmtNum(lots, 3)} lot (min ${info.volume_min}, krok ${info.volume_step})`} />
        <Line a="Silnik ryzyka SH (wynik bota)" b={ev?.risk ? <St s={ev.risk.status === "PASS" ? "VERIFIED" : "LOCKED"}>{ev.risk.status} · {ev.risk.volume} lot</St> : "—"} />
        <Note>Kalkulator jest pomocniczy; wiążący wolumen liczy silnik ryzyka bota (koszty, depozyt, ekspozycja, min lot).</Note>
      </Panel>
      <Panel id="nc-exec" title="CHECKLISTA I WYKONANIE">
        {(ev?.checklist || []).map((c: any) => <Line key={c.id} a={c.label} b={<span className={c.status === "PASS" ? "green" : c.status === "FAIL" ? "red" : "gold"}>{c.status}</span>} />)}
        <Note>Ten panel nie wysyła zleceń. Wykonanie odbywa się w bocie zgodnie z trybem ({s.mode?.mode_label || s.mode?.mode || "—"}), po bramkach
          ryzyka i koordynatora; nowe wejścia SH w AUTO LIVE dopiero po zaliczonej walidacji ścieżki na Twojej historii.</Note>
        <button className="nc-btn" onClick={() => setMsg(ev ? `Symulacja: status ${ev.status} – ${ev.status_reason}${ev.risk ? `; ryzyko ${ev.risk.status}${(ev.risk.reasons || []).length ? ": " + ev.risk.reasons.join("; ") : ""}` : ""}. Żadne zlecenie nie zostało wysłane.` : "Brak oceny setupu.")}
          data-testid="nc-dry">Symuluj decyzję (bez zlecenia)</button>
        {msg && <p className="nc-small" data-testid="nc-dry-msg">{msg}</p>}
      </Panel>
    </div>
    <Panel title="REGUŁY SCALPING / HEDGING (konfiguracja bota)">
      <Line a="Cele TP (ruch ceny w USD od fill)" b={(cfg.tp_usd || []).map((x: number) => "+" + x).join(" / ") + " USD"} />
      <Line a="Udziały" b={(cfg.shares || []).map((x: number) => Math.round(x * 100) + "%").join(" / ")} />
      <Line a="BE" b={`po potwierdzonym ${cfg.be_after} (${cfg.be_rule === "ENTRY_PLUS_COSTS" ? "wejście + koszty" : "wejście"})`} />
      <Line a="BTC" b={sh?.config?.instruments?.BTC?.enabled === false ? <St s="LOCKED">wyłączony – parametry niezwalidowane</St> : "osobny profil"} />
      <Line a="Hedging" b={`tylko rachunek HEDGING (teraz: ${s.account?.margin_mode}); bez netowania różnych instrumentów`} />
    </Panel>
  </>);
}

function Mt5({ ctx }: { ctx: Ctx }) {
  const { s, sh } = ctx;
  const info = s.symbol?.info || {};
  const [busy, setBusy] = useState(false);
  const kill = s.mode?.kill_switch;
  const toggleKill = async () => {
    if (!confirm(kill ? "Wznowić możliwość nowych wejść? (pozostałe bramki nadal obowiązują)" : "STOP: zatrzymać nowe wejścia? Otwarte pozycje pozostają bez zmian.")) return;
    setBusy(true);
    await apiSend("POST", "/api/v1/kill", { on: !kill, reason: "panel Neural Cyberpunk" }).catch(() => undefined);
    setBusy(false);
  };
  const plans: any[] = sh?.open_plans || [];
  const positions: any[] = s.positions?.positions || [];
  return (<>
    <div className="nc-grid">
      <Kpi label="MT5" value={s.connection?.state} tone={s.connection?.state === "CONNECTED" ? "green" : "red"} st={feedStatus(s)} />
      <Kpi label="POZYCJE (terminal)" value={positions.length} tone="cyan" /><Kpi label="PLANY SH" value={plans.length} tone="purple" />
      <Kpi label="STOP NOWYCH WEJŚĆ" value={kill ? "AKTYWNY" : "nieaktywny"} tone={kill ? "red" : "gold"} />
    </div>
    <div className="nc-two nc-gap">
      <Panel id="nc-bridge" title="BRIDGE I SYMBOL" right={<St s={feedStatus(s)} />}>
        <Line a="Rachunek" b={s.account ? `${s.account.server}:${s.account.login} · ${s.account.trade_mode} · ${s.account.margin_mode}` : "—"} />
        <Line a="Symbol brokera" b={`${s.symbol?.symbol || "—"} (${s.symbol?.status || "—"})`} />
        <Line a="Cyfry / tick / wartość ticka" b={`${info.digits} / ${info.trade_tick_size} / ${info.trade_tick_value}`} />
        <Line a="Wolumen min / krok / max" b={`${info.volume_min} / ${info.volume_step} / ${info.volume_max}`} />
        <Line a="Stops / freeze level" b={`${info.trade_stops_level ?? "—"} / ${info.trade_freeze_level ?? "—"}`} />
        <Line a="Kontrakt" b={info.trade_contract_size} />
        <Line a="Wiek notowania" b={`${fmtNum(s.quote?.age_seconds, 1)} s`} />
        <Line a="Rekonsyliacja SH po restarcie" b={sh?.recovery ? `przejęte ${sh.recovery.adopted.length}, odrzucone ${sh.recovery.rejected.length}, sieroty ${sh.recovery.orphans.length}` : "—"} />
      </Panel>
      <Panel id="nc-safety" title="BEZPIECZEŃSTWO">
        <Line a="Tryb wykonania" b={s.mode?.mode_label || s.mode?.mode} />
        <Line a="Nowe wejścia" b={<St s={kill ? "LOCKED" : "VERIFIED"}>{kill ? "STOP" : "dozwolone wg trybu"}</St>} />
        <Note>Execution Lock został wycofany (1.24). O zleceniach decyduje tryb, potwierdzony rachunek, STOP i limity ryzyka. STOP zatrzymuje
          tylko nowe wejścia – otwarte pozycje są dalej prowadzone.</Note>
        <button className={`nc-btn ${kill ? "" : "danger"}`} disabled={busy} onClick={toggleKill} data-testid="nc-kill">{kill ? "Wznów nowe wejścia" : "STOP – zatrzymaj nowe wejścia"}</button>
      </Panel>
    </div>
    <Panel title="POZYCJE I PLANY">
      {positions.map((p: any) => <Line key={p.ticket} a={`#${p.ticket} ${p.symbol} ${p.type || p.side} ${p.volume}`} b={`magic ${p.magic} · ${fmtNum(p.profit, 2)}`} />)}
      {plans.map((p: any) => <Line key={p.plan_id} a={`${p.plan_id} ${p.strategy} ${p.side}`} b={`${p.state} · ${p.exec_mode}`} />)}
      {!positions.length && !plans.length && <p className="nc-small">Brak otwartych pozycji i planów.</p>}
    </Panel>
  </>);
}

function Liquidity({ ctx }: { ctx: Ctx }) {
  const [hm] = usePoll<any>("/api/v1/liquidity/heatmap", 15000);
  const [ses] = usePoll<any>("/api/v1/liquidity/sessions", 30000);
  return (<>
    <div className="nc-grid">
      <Kpi label="HEATMAPA (szacunek)" value={hm?.status} st={hm?.status === "OK" ? "VERIFIED" : "UNAVAILABLE"} />
      <Kpi label="DOSTAWCA" value={hm?.provider} tone="purple" /><Kpi label="KLUCZ API" value={hm?.key_status} tone="gold" />
      <Kpi label="SESJE / SWEEP" value={ses ? "dostępne" : "—"} st={ses ? (ctx.s.synthetic ? "DEMO" : "VERIFIED") : "UNAVAILABLE"} />
    </div>
    {hm?.reason && <Note>{hm.reason}</Note>}
    <div className="nc-gap"><LiquidityHeatmapPanel /></div>
    <Panel title="ŹRÓDŁA DANYCH"><Note>Heatmapa to SZACOWANE poziomy likwidacji z dostawcy (rodzaj: {hm?.data_kind || "—"}), nie zrealizowane likwidacje ani arkusz zleceń.
      Notowania XAUUSD od brokera nie są skonsolidowanym arkuszem zleceń.</Note></Panel>
  </>);
}

function Statistics({ ctx }: { ctx: Ctx }) {
  const [st] = usePoll<any>("/api/v1/stats", 15000);
  const b = st?.bot || {};
  const row = (k: string) => <tr key={k}><td>{k}</td>{["all", "day", "week", "month"].map((p) => <td key={p}>{fmtNum((b[p] || {})[k], 2)}</td>)}</tr>;
  const keys = Object.keys(b.all || {}).filter((k) => typeof (b.all || {})[k] === "number");
  return (<>
    <div className="nc-grid">
      <Kpi label="TRYB STATYSTYK" value={b.mode} tone="purple" st={ctx.s.synthetic ? "DEMO" : "VERIFIED"} />
      <Kpi label="DEALE NA RACHUNKU" value={st?.account?.deals} tone="cyan" /><Kpi label="WYNIK NETTO (symbol)" value={fmtNum(st?.account?.trading_net_symbol, 2)} tone="gold" />
      <Kpi label="ROI RACHUNKU" value={st?.account_roi?.status} st={st?.account_roi?.status === "OK" ? "VERIFIED" : "UNAVAILABLE"} />
    </div>
    <Panel id="nc-stats" title="FROG WIZARD – STATYSTYKI BOTA (z historii transakcji)">
      <div className="nc-scroll"><table className="nc-tbl"><thead><tr><th>Miara</th><th>Całość</th><th>Dzień</th><th>Tydzień</th><th>Miesiąc</th></tr></thead>
        <tbody>{keys.map((k) => row(k))}</tbody></table></div>
      <Note>{b.note} {st?.account?.note}</Note>
      <Line a="Krzywa equity" b={st?.equity?.status} /><Line a="Otwarte częściowe / nierozliczone" b={`${b.open_partial_positions ?? "—"} / ${b.unsettled_positions ?? "—"}`} />
      <Line a="Transakcje bez znanej prowizji" b={b.commission_unknown_trades} />
    </Panel>
  </>);
}

function Operations({ ctx }: { ctx: Ctx }) {
  const { s, sh } = ctx;
  const [dg] = usePoll<any>("/api/v1/diagnostics", 10000);
  const [tr] = usePoll<any>("/api/v1/training", 10000);
  const mods: [string, string, any][] = [
    ["MT5 Bridge", s.connection?.state === "CONNECTED" ? (s.synthetic ? "DEMO" : "VERIFIED") : "DISCONNECTED", `${s.connection?.state} · epoka ${s.connection?.session_epoch}`],
    ["Worker MT5", dg?.worker?.failures ? "ERROR" : "VERIFIED", `wywołania ${dg?.worker?.calls ?? "—"} · błędy ${dg?.worker?.failures ?? "—"}`],
    ["Strategie SH", sh?.status === "RUNNING" ? "VERIFIED" : "ERROR", `${sh?.status || "—"}${sh?.reason ? " – " + sh.reason : ""}`],
    ["Trening", tr?.lock?.alive ? "VERIFIED" : "NOT_RUN", tr?.run ? `${tr.run.run_id}: ${tr.run.status_effective}` : "brak runów"],
    ["Agent AI", dg?.agent?.state === "READY" ? "VERIFIED" : "UNAVAILABLE", `${dg?.agent?.state || "—"} ${dg?.agent?.detail || ""}`],
    ["Kalendarz makro", dg?.news?.status === "OK" ? "VERIFIED" : "UNAVAILABLE", dg?.news?.status],
    ["Zegar PC", dg?.pc_clock?.status === "OK" ? "VERIFIED" : "UNAVAILABLE", dg?.pc_clock?.status],
    ["Baza danych", "VERIFIED", `migracje ${(dg?.db_schema || []).slice(-1)[0] || "—"}`],
  ];
  return (<>
    <div className="nc-grid">
      <Kpi label="DANE RYNKOWE" value={feedStatus(s)} st={feedStatus(s)} /><Kpi label="WEBSOCKET" value={s.ws} tone="cyan" />
      <Kpi label="WERSJA" value={s.app_version} tone="purple" /><Kpi label="BŁĘDY POŁĄCZENIA" value={(s.connection?.errors || []).length} tone="gold" />
    </div>
    <Panel id="nc-health" title="ZDROWIE MODUŁÓW">{mods.map(([n, st, d]) => <Line key={n} a={n} b={<><St s={st} /> <span className="nc-small">{d}</span></>} />)}</Panel>
    <Panel title="DZIENNIK ZDARZEŃ"><div className="nc-scroll">{(s.logs || []).slice(0, 60).map((l: any, i: number) =>
      <div key={l.id ?? i} className="nc-line"><span className={l.level === "ERROR" ? "red" : l.level === "WARN" ? "gold" : ""}>{l.ts?.slice(11, 19)} {l.category}/{l.code}</span><span className="nc-small">{l.message}</span></div>)}
      {!(s.logs || []).length && <p className="nc-small">Brak zdarzeń w tej sesji.</p>}</div></Panel>
  </>);
}

function Settings(_p: { ctx: Ctx }) {
  const ui = useUi();
  const [cfg] = usePoll<any>("/api/v1/config", 30000);
  const tg = cfg?.telegram || {};
  return (<>
    <Panel title="INTERFEJS"><Note>Motyw Neural Cyberpunk (tokeny z handoff: tło #080c1b, panel #11192d, fiolet #b49aff, cyjan #76dcfc, zieleń #46e2b6, czerwień #ff819f,
      złoto #f4c883). Klasyczny panel i jego motywy pozostają dostępne.</Note>
      <div className="nc-ctrl"><button className="nc-btn" onClick={() => ui.openSettings()} data-testid="nc-open-settings">Ustawienia bota (MT5, klucze, limity)</button>
        <button className="nc-btn" onClick={() => navigate("pulpit")}>Klasyczny panel</button></div></Panel>
    <Panel id="nc-users" title="UŻYTKOWNICY, LICENCJE, POWIADOMIENIA">
      <Line a="Sesja panelu" b={<St s="VERIFIED">lokalna sesja + CSRF (tylko 127.0.0.1)</St>} />
      <Line a="Role / RBAC administratora" b={<St s="NOT_IMPLEMENTED">aplikacja jednoużytkownikowa</St>} />
      <Line a="System licencji 48 h" b={<St s="UNAVAILABLE">usunięty z bota na prośbę użytkownika (wersja 1.4)</St>} />
      <Line a="Telegram" b={<St s={tg.enabled ? "VERIFIED" : "UNAVAILABLE"}>{tg.enabled ? "włączony" : "wyłączony / nieskonfigurowany"}</St>} />
      <Line a="Telegram EN + 简体中文 w jednej wiadomości" b={<St s="NOT_IMPLEMENTED">obecnie komunikaty po polsku</St>} />
      <Line a="Sekrety" b="tylko w magazynie sekretów bota (DPAPI) – nigdy w przeglądarce" />
    </Panel>
  </>);
}

// ------------------------------------------------------------------------------------------------ shell
class Guard extends Component<{ page: string; children: ReactNode }, { err: string | null }> {
  state = { err: null as string | null };
  static getDerivedStateFromError(e: any) { return { err: String(e?.message || e) }; }
  componentDidUpdate(prev: { page: string }) { if (prev.page !== this.props.page && this.state.err) this.setState({ err: null }); }
  render() {
    return this.state.err ? <section className="nc-panel" data-testid="nc-error"><div className="nc-body"><St s="ERROR" /> Błąd ekranu: {this.state.err}</div></section>
      : this.props.children;
  }
}

type Ctx = { s: any; sh: any; tf: string; setTf: (x: string) => void; strat: string };

/** Execution state shown instead of the withdrawn Execution Lock: the real mode and the user's STOP, both from the backend. */
function execView(s: any): { label: string; tone: string; st: string } {
  const m = s.mode?.mode;
  if (s.mode?.kill_switch) return { label: "STOP NOWYCH WEJŚĆ", tone: "red", st: "LOCKED" };
  if (!m) return { label: "—", tone: "red", st: "NOT_RUN" };
  return { label: s.mode?.mode_label || m, tone: m === "AUTO_LIVE" ? "gold" : "cyan", st: m === "AUTO_DEMO" || m === "AUTO_LIVE" ? "VERIFIED" : "PARTIAL" };
}

export default function NeuralCyberpunk({ route }: { route: Route }) {
  const { s } = useStore();
  const page = (NC_PAGES.find((p) => p.id === route.params.get("p"))?.id || "dashboard") as NcPage;
  const meta = NC_PAGES.find((p) => p.id === page)!;
  const [tf, setTf] = useGlobal("nc.tf", "M15");
  const [strat, setStrat] = useGlobal("sh.strategy", "SCALPING");
  const [sh] = usePoll<any>("/api/v1/sh", 3000);
  const [assetMsg, setAssetMsg] = useState<string | null>(null);
  const go = (p: string) => navigate("nc", { params: { p } });
  const switchAsset = async (a: string) => {
    const r: any = await apiSend("POST", "/api/v1/assets/active", { asset: a }).catch((e) => ({ error: String(e?.message || e) }));
    setAssetMsg(r?.error ? `Nie przełączono: ${r.error}` : `Aktywny instrument: ${a}`);
  };
  const ctx: Ctx = { s, sh, tf, setTf, strat };
  const fs = feedStatus(s);
  return (
    <div className="nc" data-testid="nc-root" data-page={page}>
      <header className="nc-header">
        <div className="nc-brand">◈ PEPE<span>MARKET</span>WIZARD <small>NEURAL CYBERPUNK · panel bota {s.app_version}</small></div>
        <div className="nc-ctrl">
          <label>INSTRUMENT <select value={s.assets?.active || "XAUUSD"} onChange={(e) => switchAsset(e.target.value)} data-testid="nc-asset">
            {(s.assets?.allowed || ["XAUUSD", "BTC"]).map((a: string) => <option key={a}>{a}</option>)}</select></label>
          <label>TF <select value={tf} onChange={(e) => setTf(e.target.value)} data-testid="nc-tf">{TFS.map((x) => <option key={x}>{x}</option>)}</select></label>
          <label>STRATEGIA <select value={strat} onChange={(e) => setStrat(e.target.value)} data-testid="nc-strategy"><option>SCALPING</option><option>HEDGING</option></select></label>
          <St s={fs}>{fs === "DEMO" ? "● DANE DEMO (symulator)" : fs === "VERIFIED" ? "● MT5 NA ŻYWO" : `● ${fs}`}</St>
          <St s={execView(s).st}>WYKONANIE {execView(s).label}</St>
          <span className="nc-st y">{s.mode?.mode || "—"}</span>
        </div>
      </header>
      {assetMsg && <div className="nc-flash">{assetMsg}</div>}
      <div className="nc-layout">
        <aside className="nc-aside">
          <div className="nc-small nc-sidehead">WORKSPACE</div>
          <nav data-testid="nc-nav">{NC_PAGES.map((p) => <button key={p.id} className={p.id === page ? "on" : ""} onClick={() => go(p.id)} data-nc={p.id}
            aria-current={p.id === page ? "page" : undefined}>{p.icon} {p.label}</button>)}</nav>
          <div className="nc-sideinfo">Wykonanie <strong>{execView(s).label}</strong>
            <p>Panel nie wysyła zleceń. Wartości bez statusu VERIFIED nie są danymi rachunku rzeczywistego.</p>
            <button className="nc-btn" onClick={() => navigate("pulpit")} data-testid="nc-classic">← Klasyczny panel</button></div>
        </aside>
        <main className="nc-main">
          <div className="nc-heading"><div><h1 data-testid="nc-title">{meta.n} / {meta.title}</h1>
            <div className="nc-small">{s.symbol?.symbol} · {tf} · {strat} · {s.synthetic ? "dane z symulatora terminala (DEMO)" : "dane z terminala MT5"}</div></div></div>
          <Guard page={page}><section data-testid={`nc-page-${page}`}>
            {page === "dashboard" && <Dashboard ctx={ctx} />}
            {page === "market" && <Market ctx={ctx} />}
            {page === "pattern" && <Pattern ctx={ctx} />}
            {page === "validation" && <Validation ctx={ctx} />}
            {page === "training" && <TrainingPanel instrument={s.assets?.active} />}
            {page === "decision" && <Decision ctx={ctx} />}
            {page === "mt5" && <Mt5 ctx={ctx} />}
            {page === "liquidity" && <Liquidity ctx={ctx} />}
            {page === "statistics" && <Statistics ctx={ctx} />}
            {page === "operations" && <Operations ctx={ctx} />}
            {page === "settings" && <Settings ctx={ctx} />}
            {page === "models" && <MasterModels inst={s.assets?.active || "XAUUSD"} synthetic={!!s.synthetic} />}
          </section></Guard>
        </main>
      </div>
      <footer className="nc-footer">PEPEMARKETWIZARD · NEURAL CYBERPUNK <span>{s.synthetic ? "DANE SYMULATORA – NIE SĄ NOTOWANIAMI MT5" : "ŹRÓDŁO: TERMINAL MT5"} · PANEL BEZ ZLECEŃ</span></footer>
    </div>);
}
