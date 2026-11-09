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
// The panel never sends an order: the Setup Builder only computes R:R; execution stays in the bot's own flow and gates.
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { apiSend } from "../../api";
import ChartPanel, { type Overlay } from "../../components/ChartPanel";
import { useChartOpts } from "../../components/ChartToolbar";
import { layerOf, loadPrefs, prefsKey, savePrefs, type ChartPrefs } from "../../chartprefs";
import { navigate, usePersisted } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { computeZones, setZonesLive, useMarketZones } from "../market-zones/mzStore";
import { usePmwLayers, type PmwLayers } from "../pmw133/overlays";
import { useTerminalContext } from "../shell/useTerminalContext";
import { TFS, consensus, dt, fmt, fmtSigned, hms, modelRows, mtfRows, rr, usePolled } from "./data";
import TowerFrame, { Card, Dir, Src } from "./TowerFrame";

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
  const overlay: Overlay = {
    lines: [...krLines, ...builderLines, ...(vp.on && vpOk && vp.poc && vpd.d.poc != null ? [{ price: vpd.d.poc, title: "VP: POC", color: VP_COL.poc }] : []),
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

  return (
    <TowerFrame page="pepe-wtc" accent="#39ff8f" testid="page-pepe-wtc"
      status={<>
        <b className="tw-st-name">PEPE$WTC</b><span className="tw-st-c">NEURAL MARKET COMMAND CENTER</span>
        <span><i className={cls("tw-dot", ctx.mt5 === "CONNECTED" ? "ok" : "bad")} />Źródło: <b>{ctx.env === "SYNTHETIC" ? "SYMULATOR MT5 (dane syntetyczne)" : ctx.mt5 === "CONNECTED" ? `MT5 ${envTxt}` : "brak połączenia z MT5"}</b></span>
        <span>Auto Zones: <b data-testid="wtc-st-zones">{mzLive ? "AUTO (LIVE)" : mzZones.length ? "MANUAL" : "OFF"}</b></span>
        <span>Volume Profile: <b>{!vp.on ? "OFF" : vpOk ? "AKTYWNY" : vpd.d?.status ?? "…"}</b></span>
        <span>Kronos: <b>{kronos.d?.status ?? "…"}</b></span>
      </>}>
      {/* toolbar above the chart */}
      <div className="tw-bar" role="toolbar" aria-label="Wykres główny">
        <label className="tw-field"><span>INSTRUMENT</span>
          <select value={inst ?? ""} onChange={(e) => switchAsset(e.target.value)} data-testid="wtc-instrument" aria-label="Aktywny instrument bota">
            {(s.assets?.allowed || []).map((a: string) => <option key={a} value={a}>{a}{s.assets?.assets?.[a]?.broker_symbol ? ` (${s.assets.assets[a].broker_symbol})` : ""}</option>)}
          </select></label>
        <div className="tw-seg" role="group" aria-label="Interwał wykresu głównego"><span>TIMEFRAME</span>
          {TFS.map((tf) => (
            <button key={tf} type="button" className={cls(mainTf === tf && "on")} aria-pressed={mainTf === tf} data-testid={`wtc-tf-${tf}`}
              disabled={meta[tf] ? meta[tf].loaded === false : false} title={meta[tf] && !meta[tf].loaded ? "brak danych tego interwału" : `Wykres główny ${tf}`}
              onClick={() => setMainTf(tf)}>{tf}</button>))}
        </div>
        <span className="tw-grow" />
        <button type="button" className="tw-btn acc" onClick={addChart} disabled={slots.length >= 8} data-testid="wtc-add-chart">＋ Dodaj wykres</button>
        <a className="tw-btn" href="#wtc-kronos" data-testid="wtc-kronos-link">◈ Kronos AI</a>
        <label className="tw-field sm"><span className="sr">Układ</span>
          <select value={cols} onChange={(e) => setCols(Number(e.target.value))} aria-label="Układ Multi-Chart Workspace" data-testid="wtc-layout">
            {[2, 3, 4].map((n) => <option key={n} value={n}>▦ Układ: {n} w rzędzie</option>)}</select></label>
        <button type="button" className="tw-btn" onClick={resetView} data-testid="wtc-reset">⟲ Reset widoku</button>
      </div>
      {/* indicator manager – only layers the bot really has */}
      <div className="tw-ind" role="group" aria-label="Indicator Manager" data-testid="wtc-indicators">
        <b>✦ INDICATOR MANAGER</b>
        <Chip on title="EMA silnika bota dla tego interwału (linie z /api/v1/candles) – zawsze rysowane">EMA</Chip>
        <Chip on={layers.avwap} set={(v) => setLayer("avwap", v)} disabled={!["M1", "M5"].includes(mainTf)} title="AVWAP sesji ±1σ/±2σ (PMW-IND-1) – tylko M1/M5" testid="ind-vwap">VWAP</Chip>
        <Chip on={opts.showRsi} set={(v) => setOpt("showRsi", v)} testid="ind-rsi">RSI</Chip>
        <Chip on={opts.showMacd} set={(v) => setOpt("showMacd", v)} testid="ind-macd">MACD</Chip>
        <Chip on={false} disabled title="UNAVAILABLE – bot nie ma silnika Bollinger Bands (nie jest symulowany)" testid="ind-bb">BB · N/A</Chip>
        <Chip on={atr != null} title={atr != null ? `ATR(14) ${mainTf} z ostatniej zamkniętej świecy` : "ATR niedostępny (za mało świec)"} testid="ind-atr">ATR {atr != null ? fmt(atr, digits) : "N/A"}</Chip>
        <Chip on={vp.on} set={(v) => setVp({ ...vp, on: v })} testid="ind-vp">Vol Profile</Chip>
        <Chip on={opts.showZones} set={(v) => setOpt("showZones", v)} title="FVG i order blocks silnika struktury" testid="ind-fvg">Order Blocks / FVG</Chip>
        <Chip on={opts.showStructure} set={(v) => setOpt("showStructure", v)} title="BOS / CHoCH" testid="ind-structure">BOS / CHoCH</Chip>
        <Chip on={opts.showSessions !== false && !!opts.showSessions} set={(v) => setOpt("showSessions", v)} title="Session Sweep Boxes – sesyjne High/Low i sweepy płynności" testid="ind-sess">Liquidity / Sess H/L</Chip>
        <Chip on={!!opts.showMarketZones} set={(v) => setOpt("showMarketZones", v)} title="Supply/Demand, OB, FVG, EQH/EQL, S/R – strefy rynkowe M1–M30" testid="ind-zones">Zones (Auto)</Chip>
        <Chip on={!!opts.showZoneMap} set={(v) => setOpt("showZoneMap", v)} title="Mapa stref H/L + profil sesji (POC/VAH/VAL)" testid="ind-zonemap">S/R Bands + profil sesji</Chip>
        <Chip on={layers.svp} set={(v) => setLayer("svp", v)} title="Zapisane strefy SVP (MANUAL / ALGORITHM / AI)" testid="ind-svp">Strefy SVP</Chip>
        <Chip on={!!opts.showVol} set={(v) => setOpt("showVol", v)} title="Walls dzienne / Daily open-high-low" testid="ind-walls">Walls / Daily</Chip>
        <Chip on={!!opts.showSar} set={(v) => setOpt("showSar", v)} testid="ind-sar">SAR</Chip>
        <Chip on={!!opts.showExtInd} set={(v) => setOpt("showExtInd", v)} testid="ind-iq">IQ / PAL</Chip>
        <Chip on={!!opts.showAiLevels} set={(v) => setOpt("showAiLevels", v)} testid="ind-ai">Poziomy AI</Chip>
      </div>
      {msg && <div className="tw-msg" role="status" data-testid="wtc-msg">{msg}</div>}

      <div className="wtc-grid">
        {/* ---------------------------------------------------------------- left column */}
        <div className="wtc-left">
          <Card title="KRONOS AI" icon="◈" right={<Src k={kronos.d?.status === "READY" ? (envK as any) : "na"}>{kronos.d?.status ?? "…"}</Src>} testid="wtc-kronos-summary">
            <small className="tw-dim">AI FORECAST · {krBest ? `Kronos ${krBest.tf}` : "model"}</small>
            {krBest ? (
              <div className={cls("wtc-bias", krBest.f.direction === "UP" ? "up" : krBest.f.direction === "DOWN" ? "down" : "flat")} data-testid="wtc-kronos-bias">
                {krBest.f.direction === "UP" ? "▲ BULLISH" : krBest.f.direction === "DOWN" ? "▼ BEARISH" : "◆ NEUTRAL"}<small>{envTxt}</small></div>)
              : <><div className="wtc-bias flat" data-testid="wtc-kronos-bias">N/A</div><p className="tw-note clamp" title={kronos.d?.status_pl ?? ""}>{kronos.d?.status_pl ?? kronos.err ?? "brak prognozy"}</p></>}
            <dl className="tw-kv">
              <dt>Zmiana prognozy</dt><dd>{krBest ? `${fmtSigned(krBest.f.delta_price, digits)} (${fmtSigned(krBest.f.delta_pct, 3)}%)` : "N/A"}</dd>
              <dt>Zgodność modeli</dt><dd>{cons.active ? `${cons.agree} / ${cons.active}` : "N/A"}</dd>
              <dt>Horyzont</dt><dd>{krBest ? `${krBest.f.horizon_bars} świec ${krBest.tf}` : "M1 / M5"}</dd>
              <dt>Świeżość danych</dt><dd className={cls(ctx.freshness === "FRESH" ? "ok" : "warn")}>{ctx.env === "SYNTHETIC" ? "SYMULACJA" : ctx.freshness}</dd>
            </dl>
            <p className="tw-note">Kronos nie zwraca confidence score – pokazywany jest kierunek i zmiana ceny prognozy.</p>
          </Card>
          <Card title="SYGNAŁY LIVE" icon="◉" right={<Src k={sig.err ? "err" : envK as any}>{sig.err ? "BŁĄD" : envTxt}</Src>} testid="wtc-signals">
            {items.length ? (
              <ul className="wtc-sig">
                {items.slice(0, 7).map((x) => (
                  <li key={x.signal_id}><button type="button" onClick={() => navigate("pepe-signal", { params: { id: x.signal_id } })}
                    title={`${x.strategy_id} ${x.strategy_name ?? ""} – otwórz w PEPE$SIGNAL`} data-testid="wtc-signal">
                    <b>{x.symbol}</b><small>{x.timeframe}</small><Dir d={x.action} /><em>{x.setup_score != null ? `${Math.round(x.setup_score)}/100` : x.status}</em></button></li>))}
              </ul>) : <p className="tw-na">{sig.d ? "Brak sygnałów strategii w tej sesji (bot nie potwierdził setupu)." : sig.err ?? "Ładowanie…"}</p>}
          </Card>
          <Card title="MULTI-TIMEFRAME" icon="▤" right={<span className="tw-acc">AI MATRIX</span>} testid="wtc-mtf">
            <table className="tw-tbl compact">
              <thead><tr><th>TF</th><th>Trend</th><th>Dane</th><th>Stan</th></tr></thead>
              <tbody>{mtf.map((r) => (
                <tr key={r.tf} data-tf={r.tf}><td><b>{r.tf}</b></td>
                  <td className={r.direction === "UP" ? "ok" : r.direction === "DOWN" ? "bad" : ""}>{r.direction === "UP" ? "↗" : r.direction === "DOWN" ? "↘" : r.direction === "FLAT" ? "→" : "—"}</td>
                  <td className="tw-dim">{r.data}</td>
                  <td><Dir d={r.direction === "UP" ? "BUY" : r.direction === "DOWN" ? "SELL" : r.direction ? "WAIT" : "N/A"} /></td></tr>))}</tbody>
            </table>
            <p className="tw-note">Kierunek silnika bota na zamkniętych świecach (tf_overview) – nie ocena modelu.</p>
          </Card>
          <figure className="wtc-pepe" aria-label="Pepe Neural Assistant"><img src="/assets/towers/pepe-neural.webp" alt="" /><figcaption>PEPE NEURAL ASSISTANT</figcaption></figure>
        </div>

        {/* ---------------------------------------------------------------- centre */}
        <div className="wtc-center">
          <section className={cls("tw-card wtc-main", fullMain && "full")} data-testid="wtc-main" aria-label="Wykres główny">
            <header className="tw-card-h">
              <h2><span className="tw-ico">◆</span>{symbol} · {mainTf} — Główny wykres</h2>
              <Src k={envK as any}>{envTxt}</Src>
              <b className="wtc-price" data-testid="wtc-price">{bid != null ? fmt(bid, digits) : "N/A"}</b>
              <span className={cls("wtc-chg", chg != null && (chg >= 0 ? "ok" : "bad"))}>{chg != null ? `${fmtSigned(chg, digits)} (${fmtSigned((chg / (prevClose || 1)) * 100, 2)}%)` : ""}</span>
              <span className="tw-grow" />
              <span className={cls("wtc-krlink", krLines.length ? "on" : "")} data-testid="wtc-kronos-linked">
                ⚡ KRONOS AI — {krLines.length ? "POŁĄCZONY Z WYKRESEM" : kr.mode === "OFF" ? "WYŁĄCZONY" : "BRAK AKTUALNEJ PROGNOZY"}</span>
            </header>
            <div className="wtc-chart-row">
              <div className="wtc-chart" style={{ "--h": fullMain ? "calc(100vh - 140px)" : "520px" } as CSSProperties}>
                <ChartPanel key={`main-${resetKey}`} tf={mainTf} index={0} chartId="wtc-main" variant="main" opts={opts} layers={layers} overlay={overlay}
                  fullscreen={fullMain} onFullscreen={() => setFullMain(!fullMain)} />
              </div>
              {vp.on && <VpColumn d={vpd.d} err={vpd.err} tf={vpFrame} digits={digits} />}
            </div>
            <div className="wtc-legend" aria-label="Legenda warstw">
              <span><i className="lg-auto" />Automatyczne strefy ({mzLive ? "LIVE" : "na żądanie"}) + Volume Profile {vpOk ? "— aktywne ✓" : "— brak danych"}</span>
              <span><i style={{ background: "rgba(57,255,143,.35)" }} />Demand</span><span><i style={{ background: "rgba(255,93,108,.35)" }} />Supply</span>
              <span><i style={{ background: "rgba(255,207,92,.35)" }} />Order Block</span><span><i style={{ background: "rgba(95,227,255,.35)" }} />FVG</span>
              <span><i style={{ background: "rgba(180,107,255,.35)" }} />Liquidity</span><span><i className="dash" />S/R Band</span><span><i style={{ background: VP_COL.poc }} />Volume Profile</span>
            </div>
          </section>

          <div className="wtc-quad">
            <Card title="SMART TRADE SETUP BUILDER" icon="⊕" right={<Src k="info">TYLKO ANALIZA</Src>} testid="wtc-builder">
              <div className="wtc-form">
                <label>Kierunek<select value={build.dir} onChange={(e) => setBuild({ ...build, dir: e.target.value })} data-testid="wtc-b-dir"><option>BUY</option><option>SELL</option></select></label>
                <label>Strategia<select value={build.strategy} onChange={(e) => setBuild({ ...build, strategy: e.target.value })}>
                  <option value="">— ręcznie —</option>
                  {(setups.d?.strategies || []).map((x: any) => <option key={x.strategy_id} value={x.strategy_id}>{x.strategy_id} / {x.name}</option>)}
                  {["SCALPING", "HEDGING"].map((x) => <option key={x} value={x}>{x}</option>)}</select></label>
                {(["entry", "sl", "tp1", "tp2", "tp3"] as const).map((k) => (
                  <label key={k}>{k === "entry" ? "Entry" : k === "sl" ? "Stop Loss" : k.toUpperCase()}
                    <input inputMode="decimal" value={build[k]} onChange={(e) => setBuild({ ...build, [k]: e.target.value })} data-testid={`wtc-b-${k}`} placeholder="—" /></label>))}
                <label className="chk"><input type="checkbox" checked={build.show} onChange={(e) => setBuild({ ...build, show: e.target.checked })} /> Pokaż na wykresie</label>
              </div>
              <div className="wtc-tiles">
                <div><small>Risk / Reward (TP2)</small><b data-testid="wtc-b-rr">{rrB != null ? `1 : ${fmt(rrB, 2)}` : "N/A"}</b></div>
                <div><small>Setup Quality*</small><b>{det?.summary ? `${det.summary.required_met}/${det.summary.required_total}` : "N/A"}</b></div>
                <div><small>Execution</small><b className="sm">{ctx.killSwitch ? "STOP" : (ctx.modeLabel ?? "—")}</b></div>
              </div>
              <div className="tw-row">
                <button type="button" className="tw-btn sm" disabled={!det} onClick={() => loadFrom(det)} data-testid="wtc-b-load-setup">⇩ z setupu silnika</button>
                <button type="button" className="tw-btn sm" disabled={!items[0]} onClick={() => loadFrom(items[0])}>⇩ z ostatniego sygnału</button>
              </div>
              <p className="tw-note">R:R = |TP − Entry| / |Entry − SL|. *Jakość = postęp checklisty silnika (nie prawdopodobieństwo). Edycja poziomów nie otwiera zlecenia – brak przycisku zlecenia.</p>
            </Card>
            <Card title="LIVE SETUP CHECKLIST" icon="☑" right={det ? <Src k="ok">{det.strategy_id} {det.timeframe}</Src> : <Src k="na">BRAMKI</Src>} testid="wtc-checklist">
              <ul className="tw-checks">
                {(checklist.length ? checklist.map((r) => ({ name: r.name, st: r.state, why: r.reason ?? r.value }))
                  : gates.map((g) => ({ name: g.label, st: g.status === "MET" ? "MET" : g.status === "PENDING" ? "PENDING" : g.status === "MISSING" ? "MISSING" : "NO_DATA", why: (g.reasons || []).join(", ") })))
                  .map((r, i) => (
                    <li key={i} className={`c-${String(r.st).toLowerCase()}`} title={r.why || ""}><i aria-hidden="true" />{r.name}
                      <em>{r.st === "MET" ? "OK" : r.st === "MISSING" ? "NIE" : r.st === "PENDING" ? "PENDING" : r.st === "NO_DATA" ? "BRAK DANYCH" : r.st}</em></li>))}
              </ul>
              {!checklist.length && <p className="tw-note">Brak aktywnego setupu silnika – pokazane bramki decyzji (dane, rynek, ryzyko, AI, ML).</p>}
              {det?.levels?.invalidation_rule && <p className="tw-note">Invalidation: {det.levels.invalidation_rule}</p>}
            </Card>
            <Card title="AI LIVE ZONES" icon="◎" right={<span className="tw-seg mini">
              <button type="button" className={cls(mzLive && "on")} aria-pressed={mzLive} disabled={!inst || mz.busy === "live"} data-testid="wtc-mz-auto"
                onClick={() => inst && setZonesLive(inst, true, mzTfs)} title="AUTO: przeliczenie po zamknięciu każdej świecy M1–M30">AUTO</button>
              <button type="button" className={cls(!mzLive && "on")} aria-pressed={!mzLive} disabled={!inst || mz.busy === "live"} data-testid="wtc-mz-manual"
                onClick={() => inst && setZonesLive(inst, false, mzTfs)} title="MANUAL: strefy przeliczane przyciskiem">MANUAL</button></span>} testid="wtc-ai-zones">
              <p className="tw-sub">{mzLive ? "AUTOMATYCZNE STREFY – WYKRYWANE NA ŻYWO" : "STREFY NA ŻĄDANIE"} · {mzZones.length} stref</p>
              <ul className="tw-toggles">
                <li><span>Strefy na wykresie (wszystkie)</span><Sw on={!!opts.showMarketZones} set={(v) => setOpt("showMarketZones", v)} testid="wtc-mz-all" /></li>
                {MZ_LAYERS.map(([k, label]) => (
                  <li key={k}><span>{label} <small>{mzZones.filter((z) => layerOf(String(z.type || "")) === k).length}</small></span>
                    <Sw on={mzLayers[k]} set={(v) => setMzLayer(k, v)} testid={`wtc-mz-${k}`} /></li>))}
              </ul>
              <div className="tw-row">
                <button type="button" className="tw-btn sm acc" disabled={!inst || mz.busy === "compute"} onClick={() => inst && computeZones(inst, mzTfs)} data-testid="wtc-mz-compute">
                  {mz.view?.job && ["QUEUED", "RUNNING"].includes(mz.view.job.status) ? "Wyznaczanie…" : "Wyznacz teraz"}</button>
                <small className="tw-dim">{mz.err ? `błąd: ${mz.err}` : mzTfs.map((tf) => `${tf}: ${mz.view?.timeframes?.[tf]?.status?.status_pl ?? "—"}`).join(" · ")}</small>
              </div>
            </Card>
            <Card title="VOLUME PROFILE AUTO ZONES" icon="▥" right={<Src k={!vp.on ? "off" : vpOk ? "ok" : vpd.err ? "err" : "na"}>{!vp.on ? "OFF" : vpOk ? "ACTIVE" : vpd.err ? "ERROR" : (vpd.d?.status ?? "…")}</Src>} testid="wtc-vp">
              <ul className="tw-toggles">
                <li><span>Volume Profile (VP)</span><Sw on={vp.on} set={(v) => setVp({ ...vp, on: v })} testid="wtc-vp-on" /></li>
                <li><span>POC (Point of Control)</span><Sw on={vp.poc} set={(v) => setVp({ ...vp, poc: v })} testid="wtc-vp-poc" /></li>
                <li><span>VAH / VAL (Value Area)</span><Sw on={vp.va} set={(v) => setVp({ ...vp, va: v })} testid="wtc-vp-va" /></li>
                <li><span>VP Auto Zones (HVN / LVN)</span><Sw on={vp.auto} set={(v) => setVp({ ...vp, auto: v })} testid="wtc-vp-auto" /></li>
                <li><span>HVN · LVN</span><span className="tw-seg mini">
                  <button type="button" className={cls(vp.hvn && "on")} aria-pressed={vp.hvn} onClick={() => setVp({ ...vp, hvn: !vp.hvn })}>HVN</button>
                  <button type="button" className={cls(vp.lvn && "on")} aria-pressed={vp.lvn} onClick={() => setVp({ ...vp, lvn: !vp.lvn })}>LVN</button></span></li>
              </ul>
              <div className="tw-row">
                <label className="tw-field sm">TF<select value={vpFrame} onChange={(e) => setVpTf(e.target.value === mainTf ? null : e.target.value)} data-testid="wtc-vp-tf">
                  {TFS.map((t) => <option key={t} value={t}>{t}{t === mainTf ? " (główny)" : ""}</option>)}</select></label>
                <label className="tw-field sm">Okno<select value={vp.bars} onChange={(e) => setVp({ ...vp, bars: Number(e.target.value) })}>
                  {[100, 200, 500].map((n) => <option key={n} value={n}>{n} świec</option>)}</select></label>
                <span className="tw-seg mini">{(["AUTO", "MANUAL"] as const).map((m) => (
                  <button key={m} type="button" className={cls(vp.mode === m && "on")} aria-pressed={vp.mode === m} onClick={() => setVp({ ...vp, mode: m })}>{m}</button>))}</span>
                {vp.mode === "MANUAL" && <button type="button" className="tw-btn sm" onClick={() => vpd.reload()} data-testid="wtc-vp-recalc">Przelicz</button>}
              </div>
              {vpOk ? (
                <ul className="wtc-vpz" data-testid="wtc-vp-zones">
                  {vpZones.slice(0, 8).map((z, i) => (
                    <li key={i} className={`z-${z.type.toLowerCase()}`}><b>{z.type}</b><span>{fmt(z.low, digits)} – {fmt(z.high, digits)}</span><small>{vpFrame}</small></li>))}
                </ul>) : <p className="tw-na">{vpd.err ? `Błąd: ${vpd.err}` : vpd.d?.reason ? `Brak danych: ${vpd.d.reason}` : "Liczenie profilu…"}</p>}
              <p className="tw-note">Silnik PMW-SVP-1 bota ({vpd.d?.method ?? "—"}; wolumen: {vpd.d?.volume_source ?? "—"}). Poziom VP to typowana strefa informacyjna – nie sygnał ani strefa handlowa.</p>
            </Card>
          </div>
        </div>

        {/* ---------------------------------------------------------------- right column */}
        <div className="wtc-right">
          <Card title="KRONOS — M1 / M5" icon="◈" right={<span className="tw-acc">{kr.mode}</span>} testid="wtc-kronos" id="wtc-kronos">
            <div className="tw-seg wide" role="group" aria-label="Tryb Kronos">
              {(["AUTO", "MANUAL", "OFF"] as const).map((m) => (
                <button key={m} type="button" className={cls(kr.mode === m && "on")} aria-pressed={kr.mode === m} onClick={() => krMode(m)} data-testid={`wtc-kr-${m}`}>{m}</button>))}
            </div>
            <ul className="tw-toggles">
              {(["M1", "M5"] as const).map((tf) => {
                const t = krState(tf);
                const k = tf === "M1" ? "m1" : "m5";
                return (
                  <li key={tf} title={t ? `${t.state_pl ?? t.state}${t.reason ? ` – ${t.reason}` : ""}` : "TF nie jest skonfigurowany w ustawieniach Kronos"}>
                    <span>Kronos {tf} <small className={cls(t?.state === "READY" ? "ok" : "warn")}>{t ? (t.state_pl ?? t.state) : "nie skonfigurowany"}</small></span>
                    {kr.mode === "MANUAL" && <button type="button" className="tw-btn xs" onClick={() => krRefresh(tf)} data-testid={`wtc-kr-refresh-${tf}`}>Przelicz</button>}
                    <Sw on={kr[k]} set={(v) => setKr({ ...kr, [k]: v })} testid={`wtc-kr-${tf}`} disabled={kr.mode === "OFF"} /></li>);
              })}
              <li><span>Prognoza na wykresie</span><Sw on={kr.onChart} set={(v) => setKr({ ...kr, onChart: v })} testid="wtc-kr-chart" disabled={kr.mode === "OFF"} /></li>
              <li><span>Stan inferencji</span><b className={cls(kronos.d?.status === "READY" ? "ok" : "warn")} data-testid="wtc-kr-state" title={kronos.d?.status_pl ?? ""}>{kronos.d?.status ?? "…"}</b></li>
            </ul>
            {kronos.d?.status !== "READY" && kronos.d?.status_pl && <p className="tw-note clamp" title={kronos.d.status_pl}>{kronos.d.status_pl}</p>}
            {krMain.map(({ tf, f, cur }) => f ? (
              <p key={tf} className="tw-note">{tf}: {f.direction_pl ?? f.direction} {fmtSigned(f.delta_price, digits)} → {fmt(f.pred_close_h, digits)} ({hms(f.created_at)}){cur ? "" : " · NIEAKTUALNA"}</p>) : null)}
            <a className="tw-link" href="#/neural">Pełny panel Kronos (instalacja, walidacja) →</a>
          </Card>
          <Card title="MODEL CONSENSUS" icon="◉" right={<Src k={envK as any}>{envTxt}</Src>} testid="wtc-consensus">
            <ul className="tw-models">
              {rows.slice(0, 7).map((r) => (
                <li key={r.key} title={`${r.task ?? ""}${r.reason ? ` · ${r.reason}` : ""}`}>
                  <span>{r.name}{r.tf ? <small> {r.tf}</small> : null}</span>
                  <em className={cls(`st-${r.state.toLowerCase()}`)}>{r.state}</em>
                  <b>{r.bias ?? "—"}{r.score != null ? ` · ${Math.round(r.score)}` : ""}</b></li>))}
            </ul>
            {!rows.length && <p className="tw-na">{preds.err ?? "Brak predykcji modeli dla instrumentu."}</p>}
            <p className="tw-note">Konsensus: {cons.dir ?? "N/A"} ({cons.agree}/{cons.active} aktywnych{cons.conflict ? ", KONFLIKT" : ""}); wagi równe – bot nie konfiguruje wag. Wynik modelu ≠ prawdopodobieństwo, o ile nie oznaczono kalibracji.</p>
          </Card>
          <Card title="ANALIZA SETUPU" icon="▦" right={<Src k={det ? "ok" : "na"}>{det ? "SILNIK" : "BRAK SETUPU"}</Src>} testid="wtc-analysis">
            <div className="wtc-tiles two">
              <div><small>Signal Strength</small><b>{(() => { const v = Number(det?.checklist?.find((r: any) => String(r.name).startsWith("Wynik ACTIVE"))?.value); return Number.isFinite(v) ? `${Math.round(v)}/100` : "N/A"; })()}</b></div>
              <div><small>Quality</small><b>{det?.summary ? `${det.summary.required_met}/${det.summary.required_total}` : "N/A"}</b></div>
              <div><small>MTF Agreement</small><b>{mtfAgree != null ? `${mtfAgree}/${mtfKnown}` : "N/A"}</b></div>
              <div><small>Invalidation</small><b className="sm">{det?.levels?.invalidation_level != null ? fmt(det.levels.invalidation_level, digits) : "MONITOR"}</b></div>
            </div>
            <dl className="tw-kv">
              <dt>Tryb rachunku</dt><dd>{ctx.env === "SYNTHETIC" ? "SYMULATOR" : ctx.env}</dd>
              <dt>Tryb wykonania</dt><dd>{ctx.modeLabel ?? "—"}</dd>
              <dt>Blokada (STOP)</dt><dd className={cls(ctx.killSwitch ? "bad" : "ok")}>{ctx.killSwitch ? "AKTYWNA" : "brak"}</dd>
              <dt>Wejście</dt><dd>{det?.entry?.status ?? "—"}</dd>
            </dl>
            <p className="tw-note">Signal Strength = wynik ACTIVE silnika (heurystyka 0–100, nie prawdopodobieństwo). Execution Lock wycofany w 1.24 – wejścia blokują tryb wykonania, STOP i bramki ryzyka bota.</p>
          </Card>
        </div>
      </div>

      {/* ---------------------------------------------------------------- multi-chart workspace */}
      <section className="tw-card wtc-ws" data-testid="wtc-workspace" aria-label="Multi-Chart Workspace">
        <header className="tw-card-h"><h2><span className="tw-ico">▦</span>MULTI-CHART WORKSPACE <small>{slots.length} wykres{slots.length === 1 ? "" : "y"}</small></h2>
          <span className="tw-grow" />
          <button type="button" className="tw-btn sm acc" onClick={addChart} disabled={slots.length >= 8} data-testid="wtc-new-chart">＋ Nowy wykres</button></header>
        <div className="wtc-ws-grid" style={{ "--cols": cols } as CSSProperties}>
          {slots.map((x, i) => (
            <div key={`${x.id}-${resetKey}`} className="wtc-mini" data-testid="wtc-mini" data-tf={x.tf}>
              <div className="wtc-mini-h">
                <button type="button" className="wtc-mini-t" onClick={() => setMainTf(x.tf)} title="Ustaw ten interwał na wykresie głównym" data-testid="wtc-mini-sync">◆ {symbol} · {x.tf}</button>
                <select value={x.tf} onChange={(e) => setSlots(slots.map((y, j) => (j === i ? { ...y, tf: e.target.value } : y)))} aria-label={`Interwał wykresu ${i + 1}`} data-testid="wtc-mini-tf">
                  {TFS.map((t) => <option key={t} value={t} disabled={meta[t] ? meta[t].loaded === false : false}>{t}</option>)}</select>
                <button type="button" className="wtc-mini-x" onClick={() => setSlots(slots.filter((_, j) => j !== i))} aria-label={`Usuń wykres ${x.tf}`} data-testid="wtc-mini-remove">×</button>
              </div>
              <div className="wtc-mini-c">
                <ChartPanel tf={x.tf} index={i + 1} chartId={`wtc-${x.id}`} variant="compact" layers={layers}
                  opts={{ ...opts, showRsi: false, showMacd: false, showPatterns: false, showSessions: false, showHeatmap: false }} fullscreen={false} onFullscreen={() => setMainTf(x.tf)} />
              </div>
            </div>))}
          {slots.length < 8 && (
            <button type="button" className="wtc-add" onClick={addChart} data-testid="wtc-add-slot"><b>＋</b>DODAJ WYKRES<small>(dowolny timeframe aktywnego instrumentu)</small></button>)}
        </div>
        <p className="tw-note">Wszystkie wykresy pokazują aktywny instrument bota ({symbol}); dane jednego interwału są pobierane raz i współdzielone (jeden WebSocket). Ostatnia świeca formująca się jest oznaczona osobno od zamkniętych. Ostatnia aktualizacja sygnałów: {dt(items[0]?.updated_at)}.</p>
      </section>
    </TowerFrame>);
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
