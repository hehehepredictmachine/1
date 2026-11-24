// 1.40 WTC$PEPE TRADER TERMINAL – layout and styles of the approved pack WTC_PEPE_2_1_HTML (index.html, wtc21.css) on REAL data:
//  every card of the pack is bound to a bot source or says it has none ("brak danych" / link to the screen that has it) – the synthetic
//  values of the HTML demo (equity, ROI, win ratio, regime, scenario weights, heatmap, correlations) are never shown.
//  Performance: the Chart Lab chart is mounted only when CUSTOMIZE CHART is open, the mini charts only when visible (IntersectionObserver),
//  the background film pauses when the tab is hidden and can be switched off (also off with reduced motion).
// PEPE$WTC V4 – Neural Market Command Center (PepeMarketWizard_PEPE_WTC_V4_Zones). Production tower in the existing architecture:
//  * charts  = the existing ChartPanel (candles of the MT5 bridge via /api/v1/candles + the single WebSocket) – main chart + Multi-Chart
//              Workspace (add / remove charts, independent TF each, click = move to the main chart). The symbol is the bot's ACTIVE
//              instrument (the MT5 bridge buffers only that one); switching it uses the existing /api/v1/assets/active flow.
//  * indicators = every layer the bot really has (EMA lines of the engine, AVWAP, RSI, MACD, BOS/CHoCH, FVG/OB, market zones, zone map
//              with the session profile, sessions, walls, SAR, IQ/PAL, ATR reading). BB is shown as UNAVAILABLE (no such engine indicator).
//  * Kronos  = /api/v1/kronos (status, targets), /api/v1/kronos/forecast (M1 / M5), enable / refresh – no confidence score is invented.
//  * AI Live Zones = the bot's market-zones engine (/api/v1/market-zones: AUTO = LIVE recompute on every closed candle, MANUAL = compute
//              on demand; layer filters per type on the chart).
//  * Volume Profile Auto Zones = /api/v1/svp/visible (backend PMW-SVP-1 engine: POC, VAH/VAL, HVN, LVN) for the main chart window;
//              zones are drawn as a separate, typed layer – a VP level is NOT a trade zone.
//  * signals / consensus / MTF = /api/v1/bot-signals, /api/v1/models/predictions, the engine's tf_overview.
//  * 1.39 Chart Lab 2.1 (chartlab/) = CUSTOMIZE CHART (themes, Candles / Hollow / Heikin Ashi / Line / Area, EMA / VWAP / BB / RSI / MACD /
//              ATR / SVP / SMC with period, colour, width, presets) + Session Volume Profile (POC / VA, London / New York / Asia, biggest
//              impulse 3 / 5 / 8 / 12) on the REAL bars of /api/v1/candles - the synthetic demo data of the pack is not used.
// The panel never sends an order: the Setup Builder only computes R:R; execution stays in the bot's own flow and gates.
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { apiSend } from "../../api";
import ChartPanel, { type Overlay } from "../../components/ChartPanel";
import { useChartOpts } from "../../components/ChartToolbar";
import { layerOf, loadPrefs, prefsKey, savePrefs, type ChartPrefs } from "../../chartprefs";
import { href, navigate, usePersisted, type Page } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { computeZones, setZonesLive, useMarketZones } from "../market-zones/mzStore";
import { usePmwLayers, type PmwLayers } from "../pmw133/overlays";
import { useTerminalContext } from "../shell/useTerminalContext";
import { TFS, consensus, dt, fmt, fmtSigned, hms, modelRows, mtfRows, rr, usePolled } from "./data";
import { Src, useClock, useEnvBadge } from "./TowerFrame";
import ChartLab from "./chartlab/ChartLab";
import "./wtc21.css";

type Slot = { id: string; tf: string };
const DEF_SLOTS: Slot[] = [{ id: "a", tf: "M5" }, { id: "b", tf: "M15" }, { id: "c", tf: "H4" }, { id: "d", tf: "D1" }];
const validSlots = (v: any) => Array.isArray(v) && v.length <= 8 && v.every((x) => x && typeof x.id === "string" && TFS.includes(x.tf));
const TF_SEC: Record<string, number> = { M1: 60, M3: 180, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400, D1: 86400 };
const MZ_LAYERS: [keyof ChartPrefs["layers"], string][] = [["SD", "Supply / Demand"], ["OB", "Order Blocks"], ["FVG", "Fair Value Gaps"], ["LIQ", "Liquidity (EQH/EQL)"], ["SR", "S/R Bands"]];
const VP_COL = { poc: "#ffcf5c", va: "#5fe3ff", hvn: "#39ff8f", lvn: "#ff6c8a" };

function useVolumeProfile(tf: string, bars: number, on: boolean) {
  const [tick, setTick] = useState(0);
  useEffect(() => { if (!on) return; const i = setInterval(() => setTick((n) => n + 1), Math.max(30000, (TF_SEC[tf] || 300) * 1000)); return () => clearInterval(i); }, [tf, on]);
  const t1 = new Date(Math.floor(Date.now() / 60000) * 60000 + 60000);
  const t0 = new Date(t1.getTime() - bars * (TF_SEC[tf] || 300) * 1000);
  const path = on ? `/api/v1/svp/visible?tf=${tf}&t0=${encodeURIComponent(t0.toISOString())}&t1=${encodeURIComponent(t1.toISOString())}&bin_ticks=50&_=${tick}` : null;
  const g = usePolled<any>(path, 0);
  // the backend recomputes the visible range at most once per second: a quick TF change gets RATE_LIMITED -> one retry, never shown as data
  // NO_DATA (e.g. the server clock is still being measured, so candles have no UTC time yet) or an error -> retry every 15 s
  useEffect(() => {
    const st = g.d?.status;
    const wait = st === "RATE_LIMITED" ? 1300 : st === "NO_DATA" || (g.err && !g.d) ? 15000 : 0;
    if (!on || !wait) return;
    const t = setTimeout(() => setTick((n) => n + 1), wait);
    return () => clearTimeout(t);
  }, [g.d, g.err, on]);
  return g;
}

export default function WtcTower() {
  const { s, refresh } = useStore();
  const ctx = useTerminalContext();
  const inst: string | null = s.assets?.active ?? null;
  const symbol: string = s.symbol?.symbol ?? "—";
  const digits = s.symbol?.info?.digits ?? 2;
  const meta = s.tf_meta || {};
  const [mainTf, setMainTf] = usePersisted<string>("wtc.mainTf", "H1", (v) => TFS.includes(v));
  const [slots, setSlots] = usePersisted<Slot[]>("wtc.slots", DEF_SLOTS, validSlots);
  const [cols, setCols] = usePersisted<number>("wtc.cols", 4, (v) => [2, 3, 4].includes(v));
  const [opts, setOpt] = useChartOpts("pepe-wtc", { showRsi: true, showMacd: true, showStructure: true, showZones: true, showMarketZones: true, showAiLevels: true });
  const [pmwOwn, setPmwOwn] = usePmwLayers();
  const [layers, setLayers] = useState<PmwLayers>(pmwOwn);
  const setLayer = (k: keyof PmwLayers, v: boolean) => { const n = { ...layers, [k]: v }; setLayers(n); setPmwOwn(n); };
  const [vp, setVp] = usePersisted<{ on: boolean; poc: boolean; va: boolean; auto: boolean; hvn: boolean; lvn: boolean; bars: number; mode: "AUTO" | "MANUAL" }>(
    "wtc.vp", { on: true, poc: true, va: true, auto: true, hvn: true, lvn: false, bars: 200, mode: "AUTO" }, (v) => v && typeof v.on === "boolean");
  const [vpTf, setVpTf] = useState<string | null>(null);
  const vpFrame = vpTf ?? mainTf;
  const [kr, setKr] = usePersisted<{ mode: "OFF" | "AUTO" | "MANUAL"; m1: boolean; m5: boolean; onChart: boolean }>(
    "wtc.kronos", { mode: "AUTO", m1: true, m5: true, onChart: true }, (v) => v && ["OFF", "AUTO", "MANUAL"].includes(v.mode));
  const [build, setBuild] = useState<{ dir: string; strategy: string; entry: string; sl: string; tp1: string; tp2: string; tp3: string; show: boolean }>(
    { dir: "BUY", strategy: "", entry: "", sl: "", tp1: "", tp2: "", tp3: "", show: true });
  const [msg, setMsg] = useState<string | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [fullMain, setFullMain] = useState(false);
  const [labOpen, setLabOpen] = useState(false);
  const openLab = () => { setLabOpen(true); setTimeout(() => document.querySelector("[data-testid=wtc-chartlab]")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); };

  // ---- data
  const sig = usePolled<any>("/api/v1/bot-signals?limit=30", 10000);
  const preds = usePolled<any>(inst ? `/api/v1/models/predictions?instrument=${inst}` : null, 20000);
  const kronos = usePolled<any>("/api/v1/kronos", 15000);
  const fc1 = usePolled<any>(inst && kr.m1 && kr.mode !== "OFF" ? `/api/v1/kronos/forecast?instrument=${inst}&tf=M1` : null, kr.mode === "AUTO" ? 15000 : 0);
  const fc5 = usePolled<any>(inst && kr.m5 && kr.mode !== "OFF" ? `/api/v1/kronos/forecast?instrument=${inst}&tf=M5` : null, kr.mode === "AUTO" ? 15000 : 0);
  const setups = usePolled<any>("/api/v1/setups", 15000);
  const setupId: string | null = setups.d?.engine_selected ?? (setups.d?.items || []).find((x: any) => x.status === "ACTIVE")?.setup_id ?? null;
  const details = usePolled<any>(setupId ? `/api/v1/setups/${encodeURIComponent(setupId)}/details` : null, 15000);
  const candles = usePolled<any>(`/api/v1/candles?tf=${mainTf}&limit=2`, 30000);
  const mz = useMarketZones(inst);
  // 1.40 sources of the pack cards (real data; nothing is invented when a source is missing)
  const statMode = ctx.mode === "AUTO_DEMO" || ctx.mode === "AUTO_LIVE" ? ctx.mode : "PAPER";
  const stats = usePolled<any>(`/api/v1/stats?mode=${statMode}`, 30000);
  const news = usePolled<any>("/api/v1/news", 60000);
  const cmpTf = ["M5", "M15"].includes(mainTf) ? mainTf : "M5";
  const cmp = usePolled<any>(inst ? `/api/v1/models/foundation/compare?instrument=${inst}&tf=${cmpTf}` : null, 20000);
  const fnd = usePolled<any>("/api/v1/models/foundation", 30000);
  const res = usePolled<any>("/api/v1/resources", 15000);
  const dxy = usePolled<any>("/api/v1/indicators/dxy", 60000);
  const gfc = usePolled<any>(inst ? `/api/v1/models/foundation/forecast?model=granite_ttm&instrument=${inst}&tf=${cmpTf}` : null, 20000);
  const [film, setFilm] = usePersisted<boolean>("wtc21.film", true, (v) => typeof v === "boolean");
  const [showTsfm, setShowTsfm] = usePersisted<boolean>("wtc21.tsfmLines", true, (v) => typeof v === "boolean");
  const vpd = useVolumeProfile(vpFrame, vp.bars, vp.on);
  const items: any[] = sig.d?.items || [];
  const rows = modelRows(preds.d?.items || []);
  const cons = consensus(rows);
  const mtf = mtfRows(s);
  const det = details.d;
  const kTargets: any[] = (kronos.d?.targets || []).filter((t: any) => t.instrument === inst);

  // ---- chart layer filters of the market zones (chart prefs of the main chart; ChartPanel reacts to the change event)
  const mainKey = prefsKey("wtc-main", symbol, mainTf);
  const [mzLayers, setMzLayersState] = useState<ChartPrefs["layers"]>(() => loadPrefs(mainKey).layers);
  useEffect(() => { setMzLayersState(loadPrefs(mainKey).layers); }, [mainKey]);
  const setMzLayer = (k: keyof ChartPrefs["layers"], v: boolean) => {
    const keys = [mainKey, ...slots.map((x) => prefsKey(`wtc-${x.id}`, symbol, x.tf))];
    for (const key of keys) { const p = loadPrefs(key); savePrefs(key, { ...p, layers: { ...p.layers, [k]: v } }); }
    setMzLayersState({ ...mzLayers, [k]: v });
  };
  const mzTfs = ["M1", "M5", "M15", "M30"];
  const mzZones: any[] = mzTfs.flatMap((tf) => (mz.view?.timeframes?.[tf]?.visible || mz.view?.timeframes?.[tf]?.zones || []).map((z: any) => ({ ...z, tf })));
  const mzLive = !!mz.view?.live?.enabled;

  // ---- price + change of the main TF (last closed candle vs the forming one)
  const bid = s.quote?.bid ?? null;
  const lastBars: any[] = candles.d?.bars || [];
  const prevClose = lastBars.length >= 2 ? lastBars[lastBars.length - 2]?.c : null;
  const chg = bid != null && prevClose != null ? bid - prevClose : null;
  const atr = candles.d?.indicators?.atr14 ?? null;

  // ---- Volume Profile auto zones (typed; a VP level is not a trade zone)
  const vpOk = vpd.d?.poc != null && !["NO_DATA", "RATE_LIMITED", "ERROR"].includes(vpd.d?.status);
  const bin = vpd.d?.bin_size ?? 0;
  const vpZones = useMemo(() => {
    if (!vpOk) return [] as { type: string; low: number; high: number; label: string }[];
    const z: { type: string; low: number; high: number; label: string }[] = [];
    if (vp.poc && vpd.d.poc != null) z.push({ type: "POC", low: vpd.d.poc - bin / 2, high: vpd.d.poc + bin / 2, label: "POC (Point of Control)" });
    if (vp.va && vpd.d.vah != null && vpd.d.val != null) z.push({ type: "VA", low: vpd.d.val, high: vpd.d.vah, label: `Value Area ${Math.round((vpd.d.value_area_pct ?? 0.7) * 100)}%` });
    if (vp.hvn) for (const p of vpd.d.hvn || []) z.push({ type: "HVN", low: p - bin, high: p + bin, label: "HVN – węzeł wysokiego wolumenu" });
    if (vp.lvn) for (const p of vpd.d.lvn || []) z.push({ type: "LVN", low: p - bin / 2, high: p + bin / 2, label: "LVN – węzeł niskiego wolumenu" });
    return z;
  }, [vpOk, vpd.d, vp.poc, vp.va, vp.hvn, vp.lvn, bin]);

  // ---- Kronos forecasts (only current ones are drawn)
  const fcs = [["M1", fc1], ["M5", fc5]] as const;
  const krLines = kr.onChart && kr.mode !== "OFF" ? fcs.flatMap(([tf, g]) => {
    const f = g.d?.forecast;
    return f && g.d?.is_current && f.pred_close_h != null ? [{ price: f.pred_close_h, title: `Kronos ${tf} +${f.horizon_bars}`, color: "#b46bff", dashed: true }] : [];
  }) : [];
  const num = (x: string) => (x.trim() === "" || !Number.isFinite(Number(x.replace(",", "."))) ? null : Number(x.replace(",", ".")));
  const bEntry = num(build.entry), bSl = num(build.sl), bTp = [num(build.tp1), num(build.tp2), num(build.tp3)];
  const builderLines = build.show ? [
    ...(bEntry != null ? [{ price: bEntry, title: "Builder: Entry", color: "#e8fff3" }] : []),
    ...(bSl != null ? [{ price: bSl, title: "Builder: SL", color: "#ff5d6c", dashed: true }] : []),
    ...bTp.flatMap((p, i) => (p != null ? [{ price: p, title: `Builder: TP${i + 1}`, color: "#39ff8f", dashed: true }] : [])),
  ] : [];
  const g = gfc.d?.forecast;
  const graniteLines = showTsfm && g && gfc.d?.is_current && g.pred_close_h != null && g.timeframe === mainTf
    ? [{ price: g.pred_close_h, title: `Granite TTM +${g.horizon_bars}`, color: "#e0a030", dashed: true }] : [];
  const overlay: Overlay = {
    lines: [...krLines, ...graniteLines, ...builderLines, ...(vp.on && vpOk && vp.poc && vpd.d.poc != null ? [{ price: vpd.d.poc, title: "VP: POC", color: VP_COL.poc }] : []),
      ...(vp.on && vpOk && vp.va && vpd.d.vah != null ? [{ price: vpd.d.vah, title: "VP: VAH", color: VP_COL.va, dashed: true }, { price: vpd.d.val, title: "VP: VAL", color: VP_COL.va, dashed: true }] : [])],
    zones: vp.on && vp.auto ? vpZones.filter((z) => z.type !== "VA").map((z) => ({ low: z.low, high: z.high, label: `VP ${z.type}`,
      color: z.type === "POC" ? "rgba(255,207,92,.16)" : z.type === "HVN" ? "rgba(57,255,143,.10)" : "rgba(255,108,138,.10)",
      border: z.type === "POC" ? VP_COL.poc : z.type === "HVN" ? VP_COL.hvn : VP_COL.lvn })) : [],
  };

  const loadFrom = (x: any) => {
    if (!x) return;
    const tps: number[] = x.take_profits || x.levels?.targets || [];
    const entry = x.entry_price ?? x.levels?.planned_entry ?? x.levels?.trigger_level ?? x.levels?.reference_price ?? null;
    const f = (v: any) => (v == null ? "" : String(Number(v).toFixed(digits)));
    setBuild({ ...build, dir: (x.action ?? x.direction ?? "BUY").replace("LONG", "BUY").replace("SHORT", "SELL"), strategy: x.strategy_id ?? "",
      entry: f(entry), sl: f(x.stop_loss ?? x.levels?.stop_loss), tp1: f(tps[0]), tp2: f(tps[1]), tp3: f(tps[2]) });
  };
  const switchAsset = async (a: string) => {
    if (!a || a === inst) return;
    if ((ctx.mode === "AUTO_DEMO" || ctx.mode === "AUTO_LIVE") && !window.confirm(`Zmienić aktywny instrument bota na ${a}? Bot w trybie ${ctx.mode} przełączy analizę na ten instrument.`)) return;
    try { await apiSend("POST", "/api/v1/assets/active", { asset: a }); await refresh(); setMsg(`Aktywny instrument: ${a}`); }
    catch (e: any) { setMsg(`Nie zmieniono instrumentu: ${String(e?.message || e)}`); }
  };
  const krMode = async (m: "OFF" | "AUTO" | "MANUAL") => {
    setKr({ ...kr, mode: m });
    try { await apiSend("POST", "/api/v1/kronos/enable", { on: m !== "OFF" }); kronos.reload(); }
    catch (e: any) { setMsg(`Kronos: ${String(e?.message || e)}`); }
  };
  const krRefresh = async (tf: string) => {
    if (!inst) return;
    try { await apiSend("POST", "/api/v1/kronos/refresh", { instrument: inst, tf }); setMsg(`Kronos ${tf}: zlecono przeliczenie`); setTimeout(() => { fc1.reload(); fc5.reload(); kronos.reload(); }, 2500); }
    catch (e: any) { setMsg(`Kronos ${tf}: ${String(e?.message || e)}`); }
  };
  const addChart = () => { if (slots.length >= 8) return; const used = new Set(slots.map((x) => x.tf)); setSlots([...slots, { id: Math.random().toString(36).slice(2, 8), tf: TFS.find((t) => !used.has(t)) ?? "M15" }]); };
  const resetView = () => {
    try { for (const k of Object.keys(localStorage)) if (k.startsWith("mq.") && /wtc-(main|[a-z0-9]+)\|/.test(k)) localStorage.removeItem(k); } catch { /* storage unavailable */ }
    setSlots(DEF_SLOTS); setMainTf("H1"); setCols(4); setResetKey((n) => n + 1);
  };
  useEffect(() => { if (!msg) return; const t = setTimeout(() => setMsg(null), 5000); return () => clearTimeout(t); }, [msg]);

  const krState = (tf: string) => kTargets.find((t) => t.timeframe === tf);
  const krMain = fcs.map(([tf, g]) => ({ tf, f: g.d?.forecast, cur: !!g.d?.is_current, tgt: g.d?.target ?? krState(tf) }));
  const krBest = krMain.find((x) => x.f && x.cur) ?? null;
  const envK = ctx.env === "LIVE" ? "live" : ctx.env === "DEMO" || ctx.env === "SYNTHETIC" ? "demo" : "na";
  const envTxt = ctx.env === "SYNTHETIC" ? "DEMO·SIM" : ctx.env === "LIVE" ? "LIVE" : ctx.env === "DEMO" ? "DEMO" : "N/A";
  const selDir = det?.direction ?? null;
  const mtfAgree = selDir ? mtf.filter((r) => r.direction === (selDir === "BUY" ? "UP" : "DOWN")).length : null;
  const mtfKnown = mtf.filter((r) => r.direction).length;
  const rrB = rr(build.dir, bEntry, bSl, bTp[1] ?? bTp[0]);
  const checklist: any[] = det?.checklist?.filter((r: any) => r.required).slice(0, 8) ?? [];
  const gates: any[] = s.decision?.checklist?.gates || [];

  const env = useEnvBadge();
  const clock = useClock();
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const st = stats.d;
  const roi = st?.account_roi;
  const winAll = st?.bot?.all;
  const eqv = s.account?.equity;
  const lastSig = items[0];
  const mdl = (cmp.d?.rows || []) as any[];
  const cmpSum = cmp.d?.summary;
  const macro = news.d?.macro;
  const nextEv = (news.d?.calendar || []).filter((e: any) => e.scheduled_at && new Date(e.scheduled_at).getTime() > Date.now()).slice(0, 3);
  const procs = res.d?.processes || {};
  const gst = fnd.d?.models?.granite_ttm;
  const gTarget = (gst?.targets || []).find((t: any) => t.timeframe === cmpTf);
  const gStatus = !gst ? "…" : !gst.enabled ? "OFF" : ["NOT_INSTALLED", "NO_WEIGHTS", "DISABLED"].includes(gst.status) ? "OFF"
    : ["STARTING", "LOADING", "INSTALLING"].includes(gst.status) ? "LOADING" : gst.status === "ERROR" ? "ERROR"
    : gTarget?.forecast_current ? "ACTIVE" : "STALE";
  const quality = det?.summary ? Math.round((det.summary.required_met / Math.max(1, det.summary.required_total)) * 100) : null;
  const regime = s.decision?.market_state ?? null;
  const modules: { key: string; icon: string; name: string; to: Page | null; src: string; state: string }[] = [
    { key: "liq", icon: "◉", name: "AI Liquidity Heatmap", to: "strefy", src: "strefy rynkowe (LIQ / EQH / EQL)", state: `${mzZones.filter((z) => layerOf(String(z.type || "")) === "LIQ").length} stref LIQ` },
    { key: "smc", icon: "⌁", name: "Smart Money Structure", to: "struktura", src: "Structure Intelligence (BOS / CHoCH)", state: opts.showStructure ? "BOS/CHoCH na wykresie" : "warstwa wyłączona" },
    { key: "cockpit", icon: "⊕", name: "Smart Trade Cockpit", to: "pozycje", src: "Pozycje i ryzyko (limity bota)", state: `${(s.positions || []).length ?? 0} pozycji` },
    { key: "vp", icon: "▥", name: "Volume Profile PRO", to: "svp", src: "PMW-SVP-1 + Chart Lab SVP", state: vpOk ? `POC ${fmt(vpd.d?.poc, digits)}` : "brak profilu" },
    { key: "mtf", icon: "▦", name: "Neural MTF Scanner", to: "wykresy", src: "tf_overview silnika", state: mtfKnown ? `${mtfKnown} TF z kierunkiem` : "brak danych" },
    { key: "corr", icon: "⥊", name: "Correlation Center", to: "dxy", src: "XAUUSD × DXY", state: dxy.d?.status === "OK" ? "DXY dostępny" : (dxy.d?.status ?? "…") },
    { key: "regime", icon: "◎", name: "Regime Detector", to: "kontekst", src: "stan rynku silnika", state: regime ?? "brak danych" },
    { key: "macro", icon: "⚑", name: "Macro News & Risk Shield", to: "kontekst", src: "/api/v1/news (kalendarz, makro)", state: macro?.risk_level ?? news.d?.status ?? "…" },
    { key: "replay", icon: "↺", name: "Trade Replay & Learning", to: "dziennik", src: "Dziennik i wyniki", state: winAll?.trades ? `${winAll.trades} zamkniętych` : "brak transakcji" },
    { key: "roi", icon: "◈", name: "ROI & Risk Analytics PRO", to: "profits", src: "Profits (ROI z equity)", state: roi?.status === "OK" ? `ROI ${fmt(roi.roi_pct, 2)}%` : "brak danych" },
    { key: "neural", icon: "✧", name: "Neural Activity Visualizer", to: "wind", src: "Wind Portal – przepływ modułów", state: `${rows.filter((r) => r.state === "READY").length} modeli READY` },
    { key: "alerts", icon: "◉", name: "Live Signal & Alert Center", to: "pepe-signal", src: "PEPE$SIGNAL", state: `${items.length} sygnałów` },
    { key: "cons", icon: "◇", name: "AI Consensus Matrix 2.0", to: "modele", src: "ModelHub + porównanie modeli", state: cons.active ? `${cons.agree}/${cons.active} zgodnych` : "brak aktywnych" },
    { key: "ws", icon: "⚙", name: "Workspace Personalization", to: null, src: "układ, film, Chart Lab, linie prognoz", state: "lokalnie w przeglądarce" },
  ];
  return (
    <div className={cls("wtc21", s.synthetic && "syn")} data-testid="page-pepe-wtc">
      {film && !reduced && <BgFilm />}
      <div className="backshade" /><div className="scanline" />
      <div className="app">
        <header className="topbar">
          <a className="brand" href={href("menu")} data-testid="tw-logo" aria-label="PepeMarketWizard – wróć do menu głównego (Galaxy)">
            <div className="brand-glyph">♛</div><div><strong>Pepe<em>Market</em>Wizard</strong><small>NEURAL TRADING ECOSYSTEM</small></div></a>
          <nav className="nav" aria-label="Sekcje">
            {([["menu", "⬡ MAIN MENU"], ["pepe-wtc", "◈ WTC$PEPE"], ["pepe-signal", "◉ BRAIN SIGNAL"], ["lightning", "⟡ PEPE$BANK"], ["profits", "▤ PEPE$ROI"]] as [Page, string][]).map(([p, l]) => (
              <button key={p} type="button" className={cls(p === "pepe-wtc" && "active")} onClick={() => navigate(p)} data-testid={`wtc21-nav-${p}`}>{l}</button>))}
          </nav>
          <div className="topright">
            <span className={cls("pill", env.tone !== "real" && "demo")} title={env.title} data-testid="tw-env">● {env.label}</span>
            <button type="button" className="pro-header-button" onClick={() => setFilm(!film)} title="Animowane tło (wideo) – wyłącz dla wydajności">{film ? "◐ TŁO ON" : "◑ TŁO OFF"}</button>
            <button type="button" className="pro-header-button" onClick={() => setFullMain(!fullMain)} title="Tryb skupienia na wykresie">⤢ FOCUS</button>
            <span className="smalltime">{clock}</span><span className="heartbeat" title={ctx.backend === "OPEN" ? "połączenie z backendem" : "brak połączenia"} />
          </div>
        </header>
        <section className="headline"><div><div className="overline">◈ TOWER 01 / TRADING CORE</div>
          <h1>WTC<span>$</span>PEPE <span style={{ fontWeight: 450, color: "#92c8e3" }}>/</span> <span style={{ color: "#d2eaff", fontWeight: 500, fontSize: ".67em", letterSpacing: "-.8px" }}>TRADER TERMINAL</span></h1>
          <p>{symbol} · {mainTf} · Kronos · Chronos-2 · Granite TTM · strefy AI · SVP · ryzyko bota – dane z MT5 ({envTxt})</p></div>
          <div className="headline-right"><div className="node" /><div><div className="overline">SYSTEM MODE</div>
            <strong style={{ fontSize: 12 }}>{ctx.modeLabel ?? ctx.mode ?? "—"} <span className={ctx.killSwitch ? "r" : "b"}>●</span></strong>
            <div className="tiny">{ctx.killSwitch ? "STOP aktywny – nowe wejścia wstrzymane" : "prognozy modeli: SHADOW / OBSERVE"}</div></div></div>
        </section>
        {msg && <div className="tw-msg" role="status" data-testid="wtc-msg">{msg}</div>}

        <section className="pro-spotlight" aria-label="Centrum inteligencji rynku">
          <article className="spotlight-card spot-radar" data-testid="wtc21-radar">
            <div className="spot-heading"><span>◉ LIVE SIGNAL RADAR</span><span className="source ghost">{sig.err ? "BŁĄD" : envTxt}</span></div>
            <div className="radar-main"><div className="radar-orb"><span className="radar-cross" />{lastSig && <><span className="radar-dot d1" /><span className="radar-dot d2" /></>}</div>
              <div className="radar-results">
                {lastSig ? <><b className={lastSig.action === "SELL" ? "r" : "g"}>{lastSig.action} <span className="dim">·</span> {lastSig.symbol}</b>
                  <small>{lastSig.strategy_id} {lastSig.strategy_name ?? ""} · {lastSig.timeframe}</small>
                  <div className="barmini"><i style={{ width: `${Math.max(0, Math.min(100, lastSig.setup_score ?? 0))}%` }} /></div>
                  <small className="muted-label">WYNIK SETUPU <b className="b">{lastSig.setup_score != null ? `${Math.round(lastSig.setup_score)}/100` : lastSig.status}</b> · heurystyka, nie prawdopodobieństwo</small></>
                  : <><b className="dim">BRAK SYGNAŁU</b><small>bot nie potwierdził setupu w tej sesji</small></>}
              </div></div>
            <button type="button" className="spot-action" onClick={() => lastSig ? navigate("pepe-signal", { params: { id: lastSig.signal_id } }) : navigate("pepe-signal")}>↗ Otwórz w PEPE$SIGNAL</button>
          </article>
          <article className="spotlight-card spot-kronos" data-testid="wtc21-models">
            <div className="spot-heading"><span>◈ PROGNOZY MODELI ({cmpTf}, H {cmp.d?.horizon_bars ?? "—"})</span><span className="source ghost">SHADOW</span></div>
            <div className="scenario-row">
              {(mdl.length ? mdl : [{ model: "kronos", name: "Kronos" }, { model: "chronos2", name: "Chronos-2" }, { model: "granite_ttm", name: "Granite TTM" }]).map((m: any) => (
                <div key={m.model} className={cls("scenario", m.comparable && "active")} title={m.reason || ""}>
                  <b>{m.direction === "UP" ? "↗" : m.direction === "DOWN" ? "↘" : m.direction === "FLAT" ? "↔" : "·"} {String(m.name || m.model).toUpperCase()}</b>
                  <span>{m.current && m.delta_price != null ? fmtSigned(m.delta_price, digits) : m.available ? "nieaktualna" : "brak"}</span></div>))}
            </div>
            <div className="forecast-details"><span>{cmpSum?.text ?? "Porównanie tylko prognoz aktualnych dla tej samej świecy i horyzontu"}</span>
              <b className="v">{cmpSum?.leading ? (cmpSum.leading === "UP" ? "WZROST" : cmpSum.leading === "DOWN" ? "SPADEK" : "BOCZNIE") : "BRAK PRZEWAGI"}</b></div>
            <div className="forecast-caption">Zmiana ceny prognozy (punkt) – nie jest prawdopodobieństwem; zgodność modeli z tych samych świec to nie niezależne potwierdzenie.</div>
          </article>
          <article className="spotlight-card spot-regime" data-testid="wtc21-regime">
            <div className="spot-heading"><span>⌁ MARKET STATE / DATA</span><span className="source ghost">SILNIK</span></div>
            <div className="regime-hero"><div><b>{regime ?? "BRAK DANYCH"}</b><small>stan rynku i jakość danych silnika bota</small></div><span>{regime === "OPEN" ? "◉" : "◌"}</span></div>
            <div className="regime-bars"><span className="regime-legend">ATR(14) {mainTf}</span><b>{atr != null ? fmt(atr, digits) : "N/A"}</b></div>
            <div className="regime-bars"><span className="regime-legend">Jakość danych</span><b>{s.decision?.data_quality ?? "—"}</b></div>
            <button type="button" className="spot-action" onClick={() => navigate("kontekst")}>↗ Kontekst rynku</button>
          </article>
          <article className="spotlight-card spot-risk" data-testid="wtc21-macro">
            <div className="spot-heading"><span>⚑ MACRO & RISK SHIELD</span><span className="source ghost">{news.d?.status ?? "…"}</span></div>
            <div className="risk-state"><span className="shield-icon">◇</span><div><b>{macro?.risk_level ? `RYZYKO MAKRO: ${macro.risk_level}` : "BRAK DANYCH MAKRO"}</b>
              <small>{nextEv.length ? `${nextEv[0].name} · ${new Date(nextEv[0].scheduled_at).toLocaleString("pl-PL", { weekday: "short", hour: "2-digit", minute: "2-digit" })}` : news.d?.enabled === false ? "moduł wiadomości wyłączony" : "brak nadchodzących wydarzeń w kalendarzu"}</small></div></div>
            <div className="risk-line"><span>STOP (wyłącznik wejść)</span><strong className={ctx.killSwitch ? "r" : "g"}>{ctx.killSwitch ? "AKTYWNY" : "nieaktywny"}</strong></div>
            <div className="risk-line"><span>Tryb wykonania</span><strong className="gold">{ctx.modeLabel ?? ctx.mode ?? "—"}</strong></div>
            <button type="button" className="spot-action" onClick={() => navigate("kontekst")}>⚑ Kalendarz i wiadomości</button>
          </article>
        </section>

        <section className="kpis" aria-label="Statystyki rachunku i bota" data-testid="wtc21-kpis">
          <div className="kpi"><div className="lbl">ROI / RACHUNEK</div><div className={cls("num", roi?.status === "OK" && (roi.roi_pct >= 0 ? "g" : "r"))}>{roi?.status === "OK" ? `${fmtSigned(roi.roi_pct, 2)}%` : "—"}</div><div className="note">{roi?.status === "OK" ? "z equity, bez wpłat/wypłat" : (roi?.note ?? "brak danych rachunku")}</div></div>
          <div className="kpi"><div className="lbl">EQUITY</div><div className="num">{eqv != null ? fmt(eqv, 2) : "—"}</div><div className="note">{s.account?.currency ?? ""} · {envTxt}</div></div>
          <div className="kpi"><div className="lbl">WIN RATIO ({statMode})</div><div className="num b">{winAll?.win_rate != null ? `${fmt(winAll.win_rate * 100, 1)}%` : "—"}</div><div className="note">{winAll?.trades ? `${winAll.trades} zamkniętych transakcji bota` : "brak zamkniętych transakcji"}</div></div>
          <div className="kpi"><div className="lbl">MODEL CONSENSUS</div><div className="num v">{cons.active ? `${cons.agree} / ${cons.active}` : "—"}</div><div className="note">{cons.dir ? `kierunek ${cons.dir}${cons.conflict ? " · KONFLIKT" : ""}` : "brak aktywnych predykcji"}</div></div>
          <div className="kpi"><div className="lbl">SETUP QUALITY</div><div className="num">{quality != null ? <>{quality}<small>/100</small></> : "—"}</div><div className="note">{det ? `checklista ${det.strategy_id} ${det.timeframe}` : "brak aktywnego setupu"}</div></div>
          <div className="kpi"><div className="lbl">MT5 DATA BRIDGE</div><div className={cls("num", ctx.mt5 === "CONNECTED" ? "g" : "gold")}>{ctx.mt5 === "CONNECTED" ? "ONLINE" : "OFFLINE"}</div><div className="note">{ctx.env === "SYNTHETIC" ? "symulator MT5 (dane syntetyczne)" : ctx.freshness}</div></div>
        </section>

        <div className="workspace">
          <aside className="stack left">
            <section className="card" data-testid="wtc-kronos-summary"><div className="cardhead"><h2><span className="sigil">◈</span> KRONOS AI / QUICK VIEW</h2><Src k={kronos.d?.status === "READY" ? (envK as any) : "na"}>{kronos.d?.status ?? "…"}</Src></div>
              <div className="cardbody"><div className="overline">FUTURE CANDLE PROJECTION</div>
                <div className="high-value" data-testid="wtc-kronos-bias">{krBest ? (krBest.f.direction === "UP" ? <span className="g">↗ BULLISH</span> : krBest.f.direction === "DOWN" ? <span className="r">↘ BEARISH</span> : <span className="gold">↔ NEUTRAL</span>) : <span className="dim">N/A</span>}</div>
                <div className="kv"><span>Zmiana prognozy</span><span className="val">{krBest ? `${fmtSigned(krBest.f.delta_price, digits)} (${fmtSigned(krBest.f.delta_pct, 3)}%)` : "N/A"}</span></div>
                <div className="kv"><span>Horyzont</span><span className="val">{krBest ? `${krBest.f.horizon_bars} świec ${krBest.tf}` : "M1 / M5"}</span></div>
                <div className="note-box">{krBest ? "Ścieżka świec Kronos (SHADOW) – bez zleceń; Kronos nie podaje confidence score." : (kronos.d?.status_pl ?? kronos.err ?? "brak prognozy")}</div></div></section>
            <section className="card" data-testid="wtc-signals"><div className="cardhead"><h2><span className="sigil">◉</span> LIVE SIGNAL FEED</h2><Src k={sig.err ? "err" : envK as any}>{sig.err ? "BŁĄD" : envTxt}</Src></div>
              {items.length ? items.slice(0, 6).map((x) => (
                <div key={x.signal_id} className={cls("signal", x.action === "SELL" ? "sell" : "buy")} role="button" tabIndex={0} data-testid="wtc-signal"
                  onClick={() => navigate("pepe-signal", { params: { id: x.signal_id } })} onKeyDown={(e) => { if (e.key === "Enter") navigate("pepe-signal", { params: { id: x.signal_id } }); }}>
                  <span className="direction">{x.action}</span><div className="siginfo"><strong>{x.symbol} · {x.timeframe}</strong><small>{x.strategy_id} {x.strategy_name ?? ""} · {hms(x.updated_at)}</small></div>
                  <span className="sigscore">{x.setup_score != null ? Math.round(x.setup_score) : "—"}</span></div>))
                : <div className="cardbody"><p className="subtle">{sig.d ? "Brak sygnałów strategii w tej sesji (bot nie potwierdził setupu)." : sig.err ?? "Ładowanie…"}</p></div>}
            </section>
            <section className="card" data-testid="wtc-mtf"><div className="cardhead"><h2><span className="sigil">≡</span> MULTI-TIMEFRAME</h2><span className="source">AI MATRIX</span></div>
              <div className="cardbody">{mtf.map((r) => (
                <div key={r.tf} className={cls("matrixrow", r.direction === "DOWN" ? "down" : r.direction === "FLAT" || !r.direction ? "flat" : "")} data-tf={r.tf}>
                  <b>{r.tf}</b><div className="matrixbar"><i style={{ width: r.direction ? "100%" : "0%" }} /></div><span className="dim">{r.data}</span>
                  <span className="arrow">{r.direction === "UP" ? "↗" : r.direction === "DOWN" ? "↘" : r.direction === "FLAT" ? "→" : "—"}</span></div>))}
                <p className="subtle">Kierunek silnika na zamkniętych świecach (tf_overview) – nie ocena modelu.</p></div></section>
            <section className="card" data-testid="wtc21-corr"><div className="cardhead"><h2><span className="sigil">▱</span> CROSS MARKET · DXY</h2><span className="source">{dxy.d?.status ?? "…"}</span></div>
              <div className="cardbody">{dxy.d?.status === "OK" ? <>
                <div className="kv"><span>Korelacja XAUUSD × DXY</span><span className="val">{dxy.d.correlation != null ? fmt(dxy.d.correlation, 2) : (dxy.d.corr != null ? fmt(dxy.d.corr, 2) : "—")}</span></div>
                <div className="kv"><span>Okno / TF</span><span className="val">{dxy.d.window ?? dxy.d.tf ?? "—"}</span></div></>
                : <p className="subtle">{dxy.d?.reason ?? "Brak danych DXY w tej sesji (symbol DXY brokera nie jest skonfigurowany albo brak migawki)."}</p>}
                <a className="tw-link" href={href("dxy")}>XAUUSD × DXY i wskaźniki →</a></div></section>
            <section className="card pro-corner-card" data-testid="wtc21-liq"><div className="cardhead"><h2><span className="sigil">◉</span> LIQUIDITY / STREFY</h2><span className="source">{mzLive ? "LIVE" : "NA ŻĄDANIE"}</span></div>
              <div className="cardbody">{MZ_LAYERS.map(([k, label]) => (
                <div key={k} className="kv"><span>{label}</span><span className="val">{mzZones.filter((z) => layerOf(String(z.type || "")) === k).length}</span></div>))}
                <p className="subtle">Strefy silnika market-zones M1–M30 – bez heatmapy DOM (bot nie ma danych księgi zleceń).</p></div></section>
          </aside>

          <main className="stack center">
            <section className={cls("wtc-main", fullMain && "full")} data-testid="wtc-main" aria-label="Wykres główny">
              <div className="marketbar">
                <select className="symbol" value={inst ?? ""} onChange={(e) => switchAsset(e.target.value)} data-testid="wtc-instrument" aria-label="Aktywny instrument bota">
                  {(s.assets?.allowed || []).map((a: string) => <option key={a} value={a}>{a}{s.assets?.assets?.[a]?.broker_symbol ? ` (${s.assets.assets[a].broker_symbol})` : ""}</option>)}</select>
                <span className="dim">TIMEFRAME</span>
                <div className="tfbar" role="group" aria-label="Interwał wykresu głównego">{TFS.map((tf) => (
                  <button key={tf} type="button" className={cls(mainTf === tf && "active")} aria-pressed={mainTf === tf} data-testid={`wtc-tf-${tf}`}
                    disabled={meta[tf] ? meta[tf].loaded === false : false} onClick={() => setMainTf(tf)}>{tf}</button>))}</div>
                <span className="spacer" />
                <button type="button" className="btn sm" onClick={addChart} disabled={slots.length >= 8} data-testid="wtc-add-chart">＋ Wykres</button>
                <button type="button" className="btn sm" onClick={resetView} data-testid="wtc-reset">⟲ Reset</button>
                <button type="button" className="btn sm" onClick={() => setFullMain(!fullMain)}>⤢ Powiększ</button>
              </div>
              <div className="chartbox">
                <div className="charttools" data-testid="wtc-indicators"><span className="indlabel">INDICATORS</span><div className="indicatorchips">
                  <Chip on title="EMA silnika bota dla tego interwału">EMA</Chip>
                  <Chip on={layers.avwap} set={(v) => setLayer("avwap", v)} disabled={!["M1", "M5"].includes(mainTf)} title="AVWAP sesji ±1σ/±2σ – tylko M1/M5" testid="ind-vwap">VWAP</Chip>
                  <Chip on={opts.showRsi} set={(v) => setOpt("showRsi", v)} testid="ind-rsi">RSI</Chip>
                  <Chip on={opts.showMacd} set={(v) => setOpt("showMacd", v)} testid="ind-macd">MACD</Chip>
                  <Chip on={false} disabled title="BB na głównym wykresie: tylko w Chart Lab (obliczane z barów MT5)" testid="ind-bb">BB · Chart Lab</Chip>
                  <Chip on={atr != null} title={atr != null ? `ATR(14) ${mainTf}` : "ATR niedostępny"} testid="ind-atr">ATR {atr != null ? fmt(atr, digits) : "N/A"}</Chip>
                  <Chip on={vp.on} set={(v) => setVp({ ...vp, on: v })} testid="ind-vp">Vol Profile</Chip>
                  <Chip on={opts.showZones} set={(v) => setOpt("showZones", v)} title="FVG i order blocks" testid="ind-fvg">OB / FVG</Chip>
                  <Chip on={opts.showStructure} set={(v) => setOpt("showStructure", v)} testid="ind-structure">BOS / CHoCH</Chip>
                  <Chip on={!!opts.showSessions} set={(v) => setOpt("showSessions", v)} testid="ind-sess">Sesje H/L</Chip>
                  <Chip on={!!opts.showMarketZones} set={(v) => setOpt("showMarketZones", v)} testid="ind-zones">Zones (Auto)</Chip>
                  <Chip on={!!opts.showZoneMap} set={(v) => setOpt("showZoneMap", v)} testid="ind-zonemap">S/R + profil</Chip>
                  <Chip on={layers.svp} set={(v) => setLayer("svp", v)} testid="ind-svp">Strefy SVP</Chip>
                  <Chip on={!!opts.showVol} set={(v) => setOpt("showVol", v)} testid="ind-walls">Walls</Chip>
                  <Chip on={!!opts.showSar} set={(v) => setOpt("showSar", v)} testid="ind-sar">SAR</Chip>
                  <Chip on={!!opts.showExtInd} set={(v) => setOpt("showExtInd", v)} testid="ind-iq">IQ / PAL</Chip>
                  <Chip on={!!opts.showAiLevels} set={(v) => setOpt("showAiLevels", v)} testid="ind-ai">Poziomy AI</Chip>
                  <Chip on={showTsfm} set={setShowTsfm} title="Linia prognozy Granite TTM (punkt, bez świec) na wykresie głównym" testid="ind-tsfm">Granite TTM</Chip>
                </div><span className="spacer" />
                  <button type="button" className="btn sm custom-btn" onClick={openLab} data-testid="wtc-customize">⚙ CUSTOMIZE CHART</button>
                  <a className="btn sm" href="#wtc-kronos" data-testid="wtc-kronos-link">◈ KRONOS</a></div>
                <div className="chartmeta"><h2><span className="b">◆</span> {symbol} / {mainTf}</h2>
                  <span className="price" data-testid="wtc-price">{bid != null ? fmt(bid, digits) : "N/A"}</span>
                  <span className={cls("micro", chg != null && (chg >= 0 ? "g" : "r"))}>{chg != null ? `${fmtSigned(chg, digits)} (${fmtSigned((chg / (prevClose || 1)) * 100, 2)}%)` : ""}</span>
                  <span className="spacer" /><span className="source ghost">OHLC · {envTxt}</span>
                  <span className={cls("wtc-krlink", krLines.length ? "on" : "")} data-testid="wtc-kronos-linked">⚡ KRONOS {krLines.length ? "NA WYKRESIE" : kr.mode === "OFF" ? "OFF" : "BRAK AKT. PROGNOZY"}</span></div>
                <div className="wtc-chart-row">
                  <div className="wtc-chart" style={{ "--h": fullMain ? "calc(100vh - 140px)" : "520px" } as CSSProperties}>
                    <ChartPanel key={`main-${resetKey}`} tf={mainTf} index={0} chartId="wtc-main" variant="main" opts={opts} layers={layers} overlay={overlay}
                      fullscreen={fullMain} onFullscreen={() => setFullMain(!fullMain)} /></div>
                  {vp.on && <VpColumn d={vpd.d} err={vpd.err} tf={vpFrame} digits={digits} />}
                </div>
                <div className="chart-bottom"><span><span className="g">●</span> WARSTWY: strefy {mzLive ? "LIVE" : "na żądanie"} · VP {vpOk ? "aktywny" : "brak danych"} · <span className="v">KRONOS / GRANITE SHADOW</span></span>
                  <span className="right">Edycja poziomów nie składa zleceń</span></div>
              </div>
            </section>
            {labOpen && <ChartLab initialTf={mainTf} digits={digits} symbol={symbol} open={labOpen} setOpen={setLabOpen} />}

            <div className="bottompanels">
              <section className="card" data-testid="wtc-builder"><div className="cardhead"><h2><span className="sigil">⊕</span> SMART TRADE SETUP BUILDER</h2><span className="source">TYLKO ANALIZA</span></div>
                <div className="cardbody"><div className="fieldgrid">
                  <label>KIERUNEK<select value={build.dir} onChange={(e) => setBuild({ ...build, dir: e.target.value })} data-testid="wtc-b-dir"><option>BUY</option><option>SELL</option></select></label>
                  <label>STRATEGIA<select value={build.strategy} onChange={(e) => setBuild({ ...build, strategy: e.target.value })}><option value="">— ręcznie —</option>
                    {(setups.d?.strategies || []).map((x: any) => <option key={x.strategy_id} value={x.strategy_id}>{x.strategy_id} / {x.name}</option>)}
                    {["SCALPING", "HEDGING"].map((x) => <option key={x} value={x}>{x}</option>)}</select></label>
                  {(["entry", "sl", "tp1", "tp2", "tp3"] as const).map((k) => (
                    <label key={k}>{k === "entry" ? "ENTRY" : k === "sl" ? "STOP LOSS" : k.toUpperCase()}
                      <input inputMode="decimal" value={build[k]} onChange={(e) => setBuild({ ...build, [k]: e.target.value })} data-testid={`wtc-b-${k}`} placeholder="—" /></label>))}
                </div>
                  <div className="setupstats"><div><small>RISK / REWARD (TP2)</small><strong className="g" data-testid="wtc-b-rr">{rrB != null ? `1 : ${fmt(rrB, 2)}` : "N/A"}</strong></div>
                    <div><small>SETUP QUALITY*</small><strong className="b">{det?.summary ? `${det.summary.required_met}/${det.summary.required_total}` : "N/A"}</strong></div>
                    <div><small>EXECUTION</small><strong className="gold" style={{ fontSize: 13 }}>{ctx.killSwitch ? "STOP" : (ctx.modeLabel ?? "—")}</strong></div></div>
                  <div className="row"><button type="button" className="btn sm" disabled={!det} onClick={() => loadFrom(det)} data-testid="wtc-b-load-setup">⇩ z setupu silnika</button>
                    <button type="button" className="btn sm" disabled={!items[0]} onClick={() => loadFrom(items[0])}>⇩ z ostatniego sygnału</button>
                    <label className="chk"><input type="checkbox" checked={build.show} onChange={(e) => setBuild({ ...build, show: e.target.checked })} /> na wykresie</label></div>
                  <p className="subtle">R:R = |TP − Entry| / |Entry − SL|. *Jakość = postęp checklisty silnika. Brak przycisku zlecenia.</p></div></section>
              <section className="card" data-testid="wtc-checklist"><div className="cardhead"><h2><span className="sigil">☑</span> LIVE SETUP CHECKLIST</h2>{det ? <Src k="ok">{det.strategy_id} {det.timeframe}</Src> : <Src k="na">BRAMKI</Src>}</div>
                <div className="cardbody"><div className="checks">
                  {(checklist.length ? checklist.map((r) => ({ name: r.name, st: r.state, why: r.reason ?? r.value }))
                    : gates.map((gg) => ({ name: gg.label, st: gg.status === "MET" ? "MET" : gg.status === "PENDING" ? "PENDING" : gg.status === "MISSING" ? "MISSING" : "NO_DATA", why: (gg.reasons || []).join(", ") })))
                    .map((r, i) => (<div key={i} className="checkline" title={r.why || ""}><span><span className="tick">{r.st === "MET" ? "✔" : r.st === "MISSING" ? "✖" : "…"}</span> {r.name}</span>
                      <span className={r.st === "MET" ? "g" : r.st === "MISSING" ? "r" : "gold"}>{r.st === "MET" ? "OK" : r.st === "MISSING" ? "NIE" : r.st === "PENDING" ? "PENDING" : "BRAK DANYCH"}</span></div>))}
                </div>{det?.levels?.invalidation_rule && <p className="subtle">Invalidation: {det.levels.invalidation_rule}</p>}</div></section>
              <section className="card" data-testid="wtc-ai-zones"><div className="cardhead"><h2><span className="sigil">◎</span> AI LIVE ZONES</h2>
                <span className="tw-seg mini"><button type="button" className={cls(mzLive && "on")} aria-pressed={mzLive} disabled={!inst || mz.busy === "live"} data-testid="wtc-mz-auto" onClick={() => inst && setZonesLive(inst, true, mzTfs)}>AUTO</button>
                  <button type="button" className={cls(!mzLive && "on")} aria-pressed={!mzLive} disabled={!inst || mz.busy === "live"} data-testid="wtc-mz-manual" onClick={() => inst && setZonesLive(inst, false, mzTfs)}>MANUAL</button></span></div>
                <div className="cardbody"><p className="subtle">{mzLive ? "AUTOMATYCZNE STREFY – NA ŻYWO" : "STREFY NA ŻĄDANIE"} · {mzZones.length} stref</p>
                  <ul className="tw-toggles"><li><span>Strefy na wykresie</span><Sw on={!!opts.showMarketZones} set={(v) => setOpt("showMarketZones", v)} testid="wtc-mz-all" /></li>
                    {MZ_LAYERS.map(([k, label]) => (<li key={k}><span>{label} <small>{mzZones.filter((z) => layerOf(String(z.type || "")) === k).length}</small></span><Sw on={mzLayers[k]} set={(v) => setMzLayer(k, v)} testid={`wtc-mz-${k}`} /></li>))}</ul>
                  <div className="row"><button type="button" className="btn sm" disabled={!inst || mz.busy === "compute"} onClick={() => inst && computeZones(inst, mzTfs)} data-testid="wtc-mz-compute">
                    {mz.view?.job && ["QUEUED", "RUNNING"].includes(mz.view.job.status) ? "Wyznaczanie…" : "Wyznacz teraz"}</button>
                    <small className="dim">{mz.err ? `błąd: ${mz.err}` : mzTfs.map((tf) => `${tf}: ${mz.view?.timeframes?.[tf]?.status?.status_pl ?? "—"}`).join(" · ")}</small></div></div></section>
              <section className="card" data-testid="wtc-vp"><div className="cardhead"><h2><span className="sigil">▥</span> SESSION VOLUME PROFILE</h2><Src k={!vp.on ? "off" : vpOk ? "ok" : vpd.err ? "err" : "na"}>{!vp.on ? "OFF" : vpOk ? "ACTIVE" : vpd.err ? "ERROR" : (vpd.d?.status ?? "…")}</Src></div>
                <div className="cardbody"><ul className="tw-toggles">
                  <li><span>Volume Profile</span><Sw on={vp.on} set={(v) => setVp({ ...vp, on: v })} testid="wtc-vp-on" /></li>
                  <li><span>POC</span><Sw on={vp.poc} set={(v) => setVp({ ...vp, poc: v })} testid="wtc-vp-poc" /></li>
                  <li><span>VAH / VAL</span><Sw on={vp.va} set={(v) => setVp({ ...vp, va: v })} testid="wtc-vp-va" /></li>
                  <li><span>Auto Zones (HVN / LVN)</span><Sw on={vp.auto} set={(v) => setVp({ ...vp, auto: v })} testid="wtc-vp-auto" /></li>
                  <li><span>HVN · LVN</span><span className="tw-seg mini"><button type="button" className={cls(vp.hvn && "on")} aria-pressed={vp.hvn} onClick={() => setVp({ ...vp, hvn: !vp.hvn })}>HVN</button>
                    <button type="button" className={cls(vp.lvn && "on")} aria-pressed={vp.lvn} onClick={() => setVp({ ...vp, lvn: !vp.lvn })}>LVN</button></span></li></ul>
                  <div className="row"><label className="tw-field sm">TF<select value={vpFrame} onChange={(e) => setVpTf(e.target.value === mainTf ? null : e.target.value)} data-testid="wtc-vp-tf">{TFS.map((t) => <option key={t} value={t}>{t}{t === mainTf ? " (główny)" : ""}</option>)}</select></label>
                    <label className="tw-field sm">Okno<select value={vp.bars} onChange={(e) => setVp({ ...vp, bars: Number(e.target.value) })}>{[100, 200, 500].map((n) => <option key={n} value={n}>{n} świec</option>)}</select></label>
                    <span className="tw-seg mini">{(["AUTO", "MANUAL"] as const).map((m) => (<button key={m} type="button" className={cls(vp.mode === m && "on")} aria-pressed={vp.mode === m} onClick={() => setVp({ ...vp, mode: m })}>{m}</button>))}</span>
                    {vp.mode === "MANUAL" && <button type="button" className="btn sm" onClick={() => vpd.reload()} data-testid="wtc-vp-recalc">Przelicz</button>}</div>
                  {vpOk ? <ul className="wtc-vpz" data-testid="wtc-vp-zones">{vpZones.slice(0, 8).map((z, i) => (<li key={i} className={`z-${z.type.toLowerCase()}`}><b>{z.type}</b><span>{fmt(z.low, digits)} – {fmt(z.high, digits)}</span><small>{vpFrame}</small></li>))}</ul>
                    : <p className="subtle">{vpd.err ? `Błąd: ${vpd.err}` : vpd.d?.reason ? `Brak danych: ${vpd.d.reason}` : "Liczenie profilu…"}</p>}
                  <p className="subtle">PMW-SVP-1 ({vpd.d?.method ?? "—"}; wolumen: {vpd.d?.volume_source ?? "—"}). Sesje London / NY / Asia i impuls 3/5/8/12: CUSTOMIZE CHART → SVP.</p></div></section>
            </div>
          </main>

          <aside className="stack right">
            <section className="card" id="wtc-kronos" data-testid="wtc-kronos"><div className="cardhead"><h2><span className="sigil">◈</span> KRONOS FORECAST CONTROL</h2><span className="source ghost">{kr.mode}</span></div>
              <div className="cardbody"><div className="tw-seg wide" role="group" aria-label="Tryb Kronos">{(["AUTO", "MANUAL", "OFF"] as const).map((m) => (
                <button key={m} type="button" className={cls(kr.mode === m && "on")} aria-pressed={kr.mode === m} onClick={() => krMode(m)} data-testid={`wtc-kr-${m}`}>{m}</button>))}</div>
                <ul className="tw-toggles">{(["M1", "M5"] as const).map((tf) => { const t = krState(tf); const k = tf === "M1" ? "m1" : "m5"; return (
                  <li key={tf} title={t ? `${t.state_pl ?? t.state}${t.reason ? ` – ${t.reason}` : ""}` : "TF nie jest skonfigurowany"}><span>Kronos {tf} <small className={cls(t?.state === "READY" ? "ok" : "warn")}>{t ? (t.state_pl ?? t.state) : "nie skonfigurowany"}</small></span>
                    {kr.mode === "MANUAL" && <button type="button" className="tw-btn xs" onClick={() => krRefresh(tf)} data-testid={`wtc-kr-refresh-${tf}`}>Przelicz</button>}
                    <Sw on={kr[k]} set={(v) => setKr({ ...kr, [k]: v })} testid={`wtc-kr-${tf}`} disabled={kr.mode === "OFF"} /></li>); })}
                  <li><span>Prognoza na wykresie</span><Sw on={kr.onChart} set={(v) => setKr({ ...kr, onChart: v })} testid="wtc-kr-chart" disabled={kr.mode === "OFF"} /></li>
                  <li><span>Stan inferencji</span><b className={cls(kronos.d?.status === "READY" ? "ok" : "warn")} data-testid="wtc-kr-state" title={kronos.d?.status_pl ?? ""}>{kronos.d?.status ?? "…"}</b></li></ul>
                {krMain.map(({ tf, f, cur }) => f ? <p key={tf} className="subtle">{tf}: {f.direction_pl ?? f.direction} {fmtSigned(f.delta_price, digits)} → {fmt(f.pred_close_h, digits)} ({hms(f.created_at)}){cur ? "" : " · NIEAKTUALNA"}</p> : null)}
                <a className="tw-link" href="#/neural">Pełny panel Kronos →</a></div></section>
            <section className="card" data-testid="wtc-granite"><div className="cardhead"><h2><span className="sigil">◇</span> GRANITE TTM</h2><span className={cls("source", gStatus === "ACTIVE" ? "" : "ghost")} data-testid="wtc-granite-status">{gStatus}</span></div>
              <div className="cardbody">
                <div className="kv"><span>Model</span><span className="val" title={gst?.repo}>TTM R2 512-96 · {String(gst?.revision ?? "").slice(0, 8)}{gst?.load?.checkpoint && gst.load.checkpoint !== "BASE" ? ` + ${gst.load.checkpoint}` : ""}</span></div>
                <div className="kv"><span>Instrument / TF</span><span className="val">{inst ?? "—"} · {cmpTf}</span></div>
                <div className="kv"><span>Prognoza close (+{g?.horizon_bars ?? "H"})</span><span className="val" data-testid="wtc-granite-pred">{g && gfc.d?.is_current ? fmt(g.pred_close_h, digits) : "—"}</span></div>
                <div className="kv"><span>Kierunek / zmiana</span><span className="val">{g && gfc.d?.is_current ? `${g.direction_pl ?? g.direction} ${fmtSigned(g.delta_price, digits)}` : (gTarget?.state_pl ?? gst?.status_pl ?? "—")}</span></div>
                <div className="kv"><span>Zgodność z Kronos / Chronos-2</span><span className="val">{(() => { const me = mdl.find((m) => m.model === "granite_ttm"); if (!me?.comparable) return "nieporównywalne"; const o = mdl.filter((m) => m.comparable && m.model !== "granite_ttm"); return o.length ? o.map((m) => `${m.name}: ${m.direction === me.direction ? "zgodny" : "różny"}`).join(" · ") : "brak innych aktualnych"; })()}</span></div>
                <div className="kv"><span>Ostatnia inferencja</span><span className="val">{g ? `${hms(g.created_at)} · ${fmt(g.compute_ms, 1)} ms` : "—"}</span></div>
                <div className="kv"><span>Pamięć procesu / CPU</span><span className="val" data-testid="wtc-granite-mem">{procs.granite_ttm?.rss_mb != null ? `${fmt(procs.granite_ttm.rss_mb, 0)} MB` : "proces nie działa"} · {gst?.load?.device ?? "cpu"} · {gst?.load?.threads ?? "—"} wątki</span></div>
                <div className="kv"><span>Walidacja</span><span className="val">{gst?.use?.SCALPING?.use ?? "OBSERVE"} · {gst?.use?.SCALPING?.validation_report ? "raport" : "NOT_VALIDATED"}</span></div>
                <p className="subtle">Prognoza punktowa (bez świec OHLC i kwantyli). OBSERVE – nie wpływa na decyzje bez walidacji.</p></div></section>
            <section className="card" data-testid="wtc-consensus"><div className="cardhead"><h2><span className="sigil">◎</span> AI CONSENSUS ENGINE</h2><Src k={envK as any}>{envTxt}</Src></div>
              <div className="cardbody"><div className="row"><div className="consensus-ring" style={{ "--p": cons.active ? Math.round((cons.agree / cons.active) * 100) : 0 } as CSSProperties}>
                <b>{cons.active ? `${cons.agree}/${cons.active}` : "—"}</b><small>ZGODNE</small></div>
                <div><div className="overline">MODEL ALIGNMENT</div><div className="high-value v">{cons.dir ?? "—"}</div><small className="dim">{cons.conflict ? "KONFLIKT kierunków" : "wagi równe"}</small></div></div>
                {rows.slice(0, 6).map((r) => (<div key={r.key} className="kv" title={`${r.task ?? ""}${r.reason ? ` · ${r.reason}` : ""}`}><span>{r.name}{r.tf ? <small> {r.tf}</small> : null}</span><span className="val">{r.state} · {r.bias ?? "—"}</span></div>))}
                <p className="subtle">Zgodność ≠ prawdopodobieństwo; modele skorelowane (Kronos / Chronos-2 / Granite z tych samych świec) liczone są jako jedna grupa w SH.</p></div></section>
            <section className="card" data-testid="wtc21-matrix"><div className="cardhead"><h2><span className="sigil">⌘</span> ACTIVE MODEL MATRIX</h2><span className="source">{res.d?.level ?? "…"}</span></div>
              <div className="cardbody">
                {[["kronos", "Kronos-base"], ["chronos2", "Chronos-2"], ["granite_ttm", "Granite TTM"]].map(([id, name]) => { const pr = procs[id]; const inf = res.d?.inference?.[id]; return (
                  <div key={id} className="kv"><span>{name}</span><span className="val">{pr?.running ? `${fmt(pr.rss_mb, 0)} MB` : "nie załadowany"}{inf?.n ? ` · p50 ${fmt(inf.p50_ms, 0)} ms` : ""}</span></div>); })}
                <div className="kv"><span>RAM komputera</span><span className="val">{res.d?.system?.used_pct != null ? `${fmt(res.d.system.used_pct, 0)} % · wolne ${fmt((res.d.system.available_mb ?? 0) / 1024, 1)} GB` : "brak pomiaru"}</span></div>
                <div className="kv"><span>Profil zasobów</span><span className="val">{res.d?.profile ?? "—"}</span></div>
                <p className="subtle">{res.d?.level_pl ?? "Memory Governor"} – pomiar systemu, nie szacunek.</p></div></section>
            <section className="card" data-testid="wtc-analysis"><div className="cardhead"><h2><span className="sigil">⚙</span> TRADING INTELLIGENCE</h2><Src k={det ? "ok" : "na"}>{det ? "SILNIK" : "BRAK SETUPU"}</Src></div>
              <div className="cardbody">
                <div className="kv"><span>Signal Strength</span><span className="val">{(() => { const v = Number(det?.checklist?.find((r: any) => String(r.name).startsWith("Wynik ACTIVE"))?.value); return Number.isFinite(v) ? `${Math.round(v)}/100` : "N/A"; })()}</span></div>
                <div className="kv"><span>MTF Agreement</span><span className="val">{mtfAgree != null ? `${mtfAgree}/${mtfKnown}` : "N/A"}</span></div>
                <div className="kv"><span>Invalidation</span><span className="val">{det?.levels?.invalidation_level != null ? fmt(det.levels.invalidation_level, digits) : "MONITOR"}</span></div>
                <div className="kv"><span>Tryb rachunku / wykonania</span><span className="val">{ctx.env === "SYNTHETIC" ? "SYMULATOR" : ctx.env} · {ctx.modeLabel ?? "—"}</span></div>
                <div className="kv"><span>Blokada (STOP)</span><span className={cls("val", ctx.killSwitch ? "r" : "g")}>{ctx.killSwitch ? "AKTYWNA" : "brak"}</span></div></div></section>
            <section className="card pro-corner-card" data-testid="wtc21-explainer"><div className="cardhead"><h2><span className="sigil">✧</span> AI DECISION EXPLAINER</h2><span className="source">BRAMKI</span></div>
              <div className="cardbody">{gates.length ? gates.slice(0, 8).map((gg: any, i: number) => (<div key={i} className="kv" title={(gg.reasons || []).join(", ")}><span>{gg.label}</span><span className={cls("val", gg.status === "MET" ? "g" : gg.status === "MISSING" ? "r" : "gold")}>{gg.status}</span></div>))
                : <p className="subtle">Brak bieżącej decyzji silnika (bramki pojawią się po zamkniętej świecy).</p>}</div></section>
          </aside>
        </div>

        <section className="system-intro" data-testid="wtc21-arsenal-head"><div><div className="overline">THE TRADER'S NEURAL ARSENAL</div><h2 style={{ margin: "4px 0" }}>14 modułów – każdy prowadzi do prawdziwego ekranu bota</h2></div>
          <div className="system-intro-right"><span className="tiny">stan z danych bota (bez wartości demonstracyjnych)</span></div></section>
        <div className="pro-modules" data-testid="wtc21-modules">{modules.map((m) => (
          <section key={m.key} className="pro-module" data-testid={`wtc21-mod-${m.key}`}>
            <div className="module-head"><b>{m.icon} {m.name}</b>{m.to ? <button type="button" className="btn sm" onClick={() => navigate(m.to as Page)}>Otwórz ↗</button> : <span className="source">TU</span>}</div>
            <div className="module-body"><div className="kv"><span>Źródło</span><span className="val">{m.src}</span></div><div className="kv"><span>Stan</span><span className="val">{m.state}</span></div></div></section>))}
        </div>

        <section className="card minicharts" data-testid="wtc-workspace" aria-label="Multi-Chart Workspace">
          <div className="cardhead"><h2><span className="sigil">▦</span> MULTI-CHART WORKSPACE · {slots.length} WYKRESY</h2>
            <div className="row"><label className="tw-field sm"><span className="sr">Układ</span><select value={cols} onChange={(e) => setCols(Number(e.target.value))} aria-label="Układ" data-testid="wtc-layout">{[2, 3, 4].map((n) => <option key={n} value={n}>▦ {n} w rzędzie</option>)}</select></label>
              <button type="button" className="btn sm" onClick={addChart} disabled={slots.length >= 8} data-testid="wtc-new-chart">＋ Nowy wykres</button></div></div>
          <div className="wtc-ws-grid" style={{ "--cols": cols } as CSSProperties}>
            {slots.map((x, i) => (
              <div key={`${x.id}-${resetKey}`} className="wtc-mini" data-testid="wtc-mini" data-tf={x.tf}>
                <div className="wtc-mini-h">
                  <button type="button" className="wtc-mini-t" onClick={() => setMainTf(x.tf)} title="Ustaw ten interwał na wykresie głównym" data-testid="wtc-mini-sync">◆ {symbol} · {x.tf}</button>
                  <select value={x.tf} onChange={(e) => setSlots(slots.map((y, j) => (j === i ? { ...y, tf: e.target.value } : y)))} aria-label={`Interwał wykresu ${i + 1}`} data-testid="wtc-mini-tf">
                    {TFS.map((t) => <option key={t} value={t} disabled={meta[t] ? meta[t].loaded === false : false}>{t}</option>)}</select>
                  <button type="button" className="wtc-mini-x" onClick={() => setSlots(slots.filter((_, j) => j !== i))} aria-label={`Usuń wykres ${x.tf}`} data-testid="wtc-mini-remove">×</button>
                </div>
                <LazyMount className="wtc-mini-c" placeholder={`${symbol} · ${x.tf}`}>
                  <ChartPanel tf={x.tf} index={i + 1} chartId={`wtc-${x.id}`} variant="compact" layers={layers}
                    opts={{ ...opts, showRsi: false, showMacd: false, showPatterns: false, showSessions: false, showHeatmap: false }} fullscreen={false} onFullscreen={() => setMainTf(x.tf)} />
                </LazyMount>
              </div>))}
            {slots.length < 8 && <button type="button" className="wtc-add" onClick={addChart} data-testid="wtc-add-slot"><b>＋</b>DODAJ WYKRES<small>(dowolny TF aktywnego instrumentu)</small></button>}
          </div>
          <p className="subtle" style={{ padding: "0 12px 10px" }}>Wszystkie wykresy pokazują aktywny instrument bota ({symbol}); wykres rysuje się dopiero, gdy jest widoczny (oszczędność CPU). Ostatnia aktualizacja sygnałów: {dt(items[0]?.updated_at)}.</p>
        </section>
        <footer className="statusfoot"><div className="footdots"><span className={ctx.mt5 === "CONNECTED" ? "g" : "gold"}>● MT5 {ctx.mt5}</span><span>● {envTxt}</span><span>● Kronos {kronos.d?.status ?? "…"}</span><span>● Granite {gStatus}</span><span>● RAM {res.d?.level ?? "…"}</span></div>
          <span className="tiny">PepeMarketWizard · WTC$PEPE TRADER TERMINAL · panel nie składa zleceń</span></footer>
      </div>
    </div>);
}

function Chip({ on, set, disabled, title, children, testid }: { on: boolean; set?: (v: boolean) => void; disabled?: boolean; title?: string; children: React.ReactNode; testid?: string }) {
  return (
    <button type="button" className={cls("tw-chip", on && "on", !set && "ro")} aria-pressed={set ? on : undefined} disabled={disabled || !set}
      onClick={() => set?.(!on)} title={title} data-testid={testid}><i aria-hidden="true" />{children}</button>);
}

function Sw({ on, set, testid, disabled }: { on: boolean; set: (v: boolean) => void; testid?: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={on} className={cls("tw-sw", on && "on")} onClick={() => set(!on)} data-testid={testid} disabled={disabled}>{on ? "ON" : "OFF"}</button>;
}

/** Volume Profile column next to the main chart (histogram of the backend profile with POC / VA / HVN / LVN). */
function VpColumn({ d, err, tf, digits }: { d: any; err: string | null; tf: string; digits: number }) {
  const h: any[] = d?.histogram || [];
  const ok = h.length > 0;
  const max = ok ? Math.max(...h.map((x) => x.weight)) || 1 : 1;
  const rows = [...h].reverse();
  return (
    <aside className="wtc-vpcol" aria-label={`Volume Profile ${tf}`} data-testid="wtc-vp-col">
      <header>VOLUME PROFILE ({tf})</header>
      {ok ? (
        <>
          <svg viewBox={`0 0 100 ${rows.length}`} preserveAspectRatio="none" role="img" aria-label={`POC ${d.poc}, VAH ${d.vah}, VAL ${d.val}`}>
            {rows.map((x, i) => {
              const inVa = x.price >= d.val && x.price <= d.vah, poc = Math.abs(x.price - d.poc) < 1e-9;
              return <rect key={i} x={100 - (x.weight / max) * 100} y={i} width={(x.weight / max) * 100} height={0.85}
                fill={poc ? VP_COL.poc : inVa ? "rgba(57,255,143,.75)" : "rgba(57,255,143,.32)"} />;
            })}
          </svg>
          <ul>
            <li className="z-va">VAH <b>{fmt(d.vah, digits)}</b></li>
            <li className="z-poc">POC <b>{fmt(d.poc, digits)}</b></li>
            <li className="z-va">VAL <b>{fmt(d.val, digits)}</b></li>
          </ul>
        </>) : <p className="tw-na">{err ? `Błąd: ${err}` : d?.reason ? d.reason : "Liczenie…"}</p>}
    </aside>);
}

/** Background film of the pack (assets/wtc21/neural_background.mp4): paused while the tab is hidden; not mounted when switched off / reduced motion. */
function BgFilm() {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const sync = () => { if (document.hidden) v.pause(); else v.play().catch(() => undefined); };
    document.addEventListener("visibilitychange", sync);
    sync();
    return () => { document.removeEventListener("visibilitychange", sync); v.pause(); v.removeAttribute("src"); v.load(); };
  }, []);
  return <video ref={ref} className="bgfilm" src="/assets/wtc21/neural_background.mp4" autoPlay muted loop playsInline preload="metadata" aria-hidden="true" />;
}

/** Mounts its children only while the box is (nearly) visible - a chart outside the viewport costs no canvas, no data request. */
function LazyMount({ children, className, placeholder }: { children: ReactNode; className?: string; placeholder?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") { setVis(true); return; }
    const io = new IntersectionObserver((es) => { for (const e of es) setVis(e.isIntersecting); }, { rootMargin: "300px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return <div ref={ref} className={className} data-mounted={vis ? "1" : "0"}>{vis ? children : <div className="wtc-lazy">{placeholder}</div>}</div>;
}
