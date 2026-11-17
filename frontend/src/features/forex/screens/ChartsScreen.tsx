// 01 CHARTS (E3, S3 §2). Silnik wykresu: wariant (a) – istniejący ChartPanel (lightweight-charts) z tymi samymi wskaźnikami,
// strefami, strukturą i planem co w 1.41 (warstwy liczone przez silnik, zapamiętywane w chartprefs). Bez nowych wzorów.
// Kronos: GET /api/v1/kronos (stan) + /api/v1/kronos/forecast (pola forecast.*), TF tylko M1/M3/M5/M15/M30/H1; panel „Kronos –
// interwały pracy” zapisuje ustawienie timeframes przez istniejące PUT /api/v1/kronos/settings (po potwierdzeniu).
// Plan bota: /api/v1/plans/chart (karta przy cenie tylko gdy jest plan). Sygnały AI: /api/v1/models/predictions (% tylko skalibrowane).
import { useEffect, useMemo, useState } from "react";
import { apiSend } from "../../../api";
import ChartPanel from "../../../components/ChartPanel";
import { useChartOpts } from "../../../components/ChartToolbar";
import { useStore } from "../../../store";
import { chanceLabel, fmt, fmtTime, tzLabel, usePoll } from "../data";
import type { ScreenProps } from "../ForexScene";

const KR_ALL = ["M1", "M3", "M5", "M15", "M30", "H1"];
type Tab = "ind" | "zones" | "vp" | "models" | "chart" | "kronos";

export default function ChartsScreen({ active }: ScreenProps) {
  const { s } = useStore();
  const tfs = usePoll<any>("/api/v1/timeframes", 60000);
  const list: string[] = useMemo(() => (tfs.data?.timeframes || []).map((t: any) => t.tf), [tfs.data]);
  const [tf, setTf] = useState<string>(() => { try { return localStorage.getItem("pmw.charts.tf") || "M15"; } catch { return "M15"; } });
  useEffect(() => { if (list.length && !list.includes(tf)) setTf(list.includes("M15") ? "M15" : list[0]); }, [list]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem("pmw.charts.tf", tf); } catch { /* */ } }, [tf]);
  const [opts, setOpt] = useChartOpts("forex-charts", { showRsi: true, showMacd: true, showStructure: true, showZones: true, showVol: true, showMarketZones: true, showAiLevels: true });
  const [tab, setTab] = useState<Tab>("ind");
  const q = s.quote || {};
  const con = s.connection || {};
  const status = con.state === "CONNECTED" ? (s.dq?.status === "STALE" ? "stale" : "live") : con.state === "CONNECTING" ? "loading" : "offline";
  return (
    <section id="charts-screen" aria-label="CHARTS">
      <div id="ch-head" className="ci">
        <div id="ch-title" aria-hidden="true"><span className="n">01</span>CHARTS</div><span className="ch-sep" />
        <div id="ch-asset" className="segb" role="group" aria-label="Aktywny instrument"><button type="button" aria-pressed="true" data-autofocus>{s.symbol?.symbol ?? "—"}</button></div><span className="ch-sep" />
        <div id="ch-tf" className="segb" role="group" aria-label="Interwał" data-testid="charts-tf">
          {list.length ? list.map((x) => <button key={x} type="button" aria-pressed={x === tf} onClick={() => setTf(x)}>{x}</button>) : <span className="sp">BRAK DANYCH</span>}</div>
        <div id="ch-right"><span id="ch-quote">{q.bid != null ? <>BID <b>{q.bid}</b> ASK <b>{q.ask}</b> SPREAD <b>{q.spread_points ?? q.spread ?? "—"}</b></> : "BRAK KWOTOWAŃ"}</span>
          <span className="ch-tzl">{opts.tz === "UTC" ? "UTC" : opts.tz === "SERVER" ? "CZAS SERWERA" : "CZAS LOKALNY " + tzLabel()}</span>
          <div id="ch-status" data-s={status} role="status"><i /><span className="t">{{ live: "MT5 POŁĄCZONY", loading: "ŁADOWANIE", offline: "ROZŁĄCZONO", stale: "DANE NIEAKTUALNE" }[status]}</span></div></div>
      </div>
      <div className="cs-wrap">
        <div className="cs-win main ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          <div className="wh"><span className="ttl" id="mc-title">{s.symbol?.symbol ?? ""} · {tf}</span><span>WYKRES GŁÓWNY</span><span className="sp">PRZECIĄGNIJ · KÓŁKO = ZOOM</span></div>
          <div id="mc-plot" className="fx-chart" data-testid="charts-main">{active && tf && <ChartPanel tf={tf} index={0} chartId={`forex-${tf}`} opts={opts} variant="main"
            onFullscreen={() => undefined} fullscreen={false} />}</div>
        </div>
        <div className="cs-side">
          <KronosWindow />
          <div className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
            <div id="opt-tabs" role="tablist" aria-label="Warstwy wykresu">{([["ind", "WSKAŹNIKI"], ["zones", "STREFY"], ["vp", "VOLUME"], ["models", "PLAN · MODELE"], ["kronos", "KRONOS TF"], ["chart", "WYKRES"]] as [Tab, string][])
              .map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}</div>
            <div id="opt-body">
              {tab === "ind" && <Sw opts={opts} set={setOpt} items={[["showRsi", "RSI (okno pod wykresem)"], ["showMacd", "MACD (okno pod wykresem)"], ["showSar", "SAR Wildera"], ["showExtInd", "Wskaźniki zewnętrzne MQL5"], ["showVol", "Wolumen (tick volume MT5)"]]} />}
              {tab === "zones" && <Sw opts={opts} set={setOpt} items={[["showZones", "Strefy silnika (FVG / OB / S/R)"], ["showMarketZones", "Market zones (wiele TF)"], ["showStructure", "Struktura BOS / CHoCH"], ["showZoneMap", "Mapa stref"], ["showSessions", "Sesje"], ["showHeatmap", "Heatmapa płynności"]]} />}
              {tab === "vp" && <p className="note">Volume Profile, POC/VAH/VAL i SVP liczy silnik (moduły SVP / zones). Warstwy włączysz menu warstw w lewym górnym rogu wykresu – te same co w 1.41.</p>}
              {tab === "models" && <><PlanCard /><Sw opts={opts} set={setOpt} items={[["showAiLevels", "Plan bota i poziomy AI na wykresie"], ["showPatterns", "Formacje"]]} /><AiSignals /></>}
              {tab === "kronos" && <KronosTfs />}
              {tab === "chart" && <div className="sw-row"><label>STREFA CZASU</label>{(["LOCAL", "UTC", "SERVER"] as const).map((z) =>
                <button key={z} type="button" className="act" aria-pressed={opts.tz === z} onClick={() => setOpt("tz", z)}>{{ LOCAL: "LOKALNY", UTC: "UTC", SERVER: "SERWER" }[z]}</button>)}</div>}
            </div>
          </div>
        </div>
      </div>
    </section>);
}

function Sw({ opts, set, items }: { opts: any; set(k: any, v: any): void; items: [string, string][] }) {
  return <div>{items.map(([k, l]) => <div key={k} className="orow"><span>{l}</span><button type="button" className="sw" aria-label={l} aria-pressed={!!opts[k]} onClick={() => set(k, !opts[k])} /></div>)}</div>;
}

function PlanCard() {
  const p = usePoll<any>("/api/v1/plans/chart", 15000);
  const pl = p.data?.primary || (p.data?.plans || [])[0];
  if (!pl || (pl.entry ?? pl.entry_price) == null) return <p className="note">Brak aktywnego planu bota.</p>;
  const tp = pl.targets || pl.take_profits || [];
  return (
    <div className="plan-box" aria-live="polite" data-testid="plan-card">
      <div className="sh"><b>PLAN BOTA</b> <span>{pl.strategy_id ?? pl.strategy ?? ""} · {pl.side ?? pl.direction ?? ""} · {pl.state ?? pl.status ?? ""}</span></div>
      <div className="lv2"><span>WEJŚCIE</span><b>{fmt(pl.entry ?? pl.entry_price)}</b><span>SL</span><b>{fmt(pl.sl ?? pl.stop_loss)}</b>
        {tp.slice(0, 3).map((t: any, i: number) => <span key={i} style={{ display: "contents" }}><span>TP{i + 1}</span><b>{fmt(typeof t === "number" ? t : t.price)}</b></span>)}
        <span>RR NETTO</span><b>{pl.rr_net != null ? fmt(pl.rr_net) : pl.rr != null ? fmt(pl.rr) : "—"}</b></div>
    </div>);
}

function AiSignals() {
  const p = usePoll<any>("/api/v1/models/predictions?instrument=XAUUSD", 15000);
  const items: any[] = p.data?.items || [];
  if (p.err) return <p className="err">BŁĄD: {p.err}</p>;
  if (!items.length) return <p className="empty">BRAK DANYCH – żaden model nie zwrócił predykcji.</p>;
  return (
    <div className="ai-list" data-testid="charts-ai">{items.slice(0, 14).map((x, i) => { const c = chanceLabel(x); return (
      <div key={i} className="pm"><span className="nm">{x.model_name}</span><span className="v">{c.pct != null ? Math.round(c.pct * 100) + "%" : x.state === "READY" ? "—" : x.state}</span>
        <span className="st">{x.state === "READY" ? c.label : x.state_pl ?? x.state}</span></div>); })}</div>);
}

function KronosTfs() {
  const k = usePoll<any>("/api/v1/kronos", 30000);
  const on: string[] = k.data?.settings?.timeframes || [];
  const [msg, setMsg] = useState<string | null>(null);
  const toggle = (tf: string) => {
    const next = on.includes(tf) ? on.filter((x) => x !== tf) : [...on, tf];
    if (!next.length) { setMsg("Kronos musi liczyć co najmniej jeden interwał."); return; }
    if (!confirm(`Zmienić interwały pracy Kronosa na: ${next.join(", ")}? Każdy interwał to osobna prognoza (dodatkowe obciążenie CPU). Zmiana działa od następnej prognozy.`)) return;
    apiSend("PUT", "/api/v1/kronos/settings", { timeframes: KR_ALL.filter((x) => next.includes(x)) }).then(() => { setMsg("Zapisano – od następnej prognozy."); k.reload(); })
      .catch((e) => setMsg("BŁĄD: " + String(e?.message || e).slice(0, 200)));
  };
  return (
    <div data-testid="kronos-tfs"><p className="note">Na których interwałach Kronos ma liczyć prognozy (ustawienie bota, zapis przez PUT /api/v1/kronos/settings).</p>
      <div>{KR_ALL.map((tf) => <div key={tf} className="orow"><span>{tf} {on.includes(tf) ? "· liczony" : ""}</span><button type="button" className="sw" aria-label={"Kronos " + tf} aria-pressed={on.includes(tf)} onClick={() => toggle(tf)} data-testid={"kronos-tf-" + tf} /></div>)}</div>
      {msg && <p className="note">{msg}</p>}{k.data?.status && k.data.status !== "READY" && <p className="note">Stan Kronosa: {k.data.status_pl ?? k.data.status}. {k.data.reason ?? ""}</p>}</div>);
}

function KronosWindow() {
  const k = usePoll<any>("/api/v1/kronos", 30000);
  const on: string[] = k.data?.settings?.timeframes || [];
  const [tf, setTf] = useState("M5");
  const f = usePoll<any>(`/api/v1/kronos/forecast?instrument=XAUUSD&tf=${tf}`, 30000);
  const fc = f.data?.forecast;
  const ctx: any[] = f.data?.context || [];
  const notInstalled = k.data && ["NOT_INSTALLED", "NO_WEIGHTS", "DISABLED"].includes(k.data.status);
  return (
    <div className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
      <div className="wh"><span className="ttl">◈ KRONOS</span><div id="kr-tf" className="segb" role="group" aria-label="Interwał Kronos">
        {KR_ALL.map((x) => <button key={x} type="button" aria-pressed={x === tf} onClick={() => setTf(x)} title={on.includes(x) ? "liczony" : "nieliczony – włącz w zakładce KRONOS TF"}>{x}{on.includes(x) ? "" : "·"}</button>)}</div>
        <span className="sp">{k.data?.mode ?? ""}</span></div>
      <div id="kr-plot" data-testid="kronos-plot">
        {notInstalled ? <p className="empty">Kronos: {k.data.status_pl ?? k.data.status}. Instalacja: 33_KRONOS_INSTALUJ.bat (albo panel modeli).</p>
          : !fc ? <p className="empty">{!on.includes(tf) ? `Interwał ${tf} nie jest liczony – włącz go w zakładce KRONOS TF.` : f.err ? "BŁĄD: " + f.err : "BRAK PROGNOZY dla " + tf}</p>
            : <KronosSvg ctx={ctx} fc={fc} />}</div>
      <div id="kr-foot"><span id="kr-dir" data-d={fc?.direction}>{fc ? (fc.direction_pl ?? fc.direction) : "—"}</span>
        <span id="kr-delta">{fc ? `${fc.delta_price > 0 ? "+" : ""}${fmt(fc.delta_price)} (${fmt(fc.delta_pct, 3)}%) w ${fc.horizon_bars} świecach` : ""}</span>
        <span id="kr-meta">{fc ? `pasmo neutralne ±${fmt(fc.neutral_band)} · ${fmtTime(fc.created_at)} · ${f.data?.is_current ? "aktualna" : "nieaktualna"}` : ""}</span></div>
    </div>);
}

function KronosSvg({ ctx, fc }: { ctx: any[]; fc: any }) {
  const bars = ctx.slice(-60).map((b) => ({ o: +b.o, h: +b.h, l: +b.l, c: +b.c })).filter((b) => isFinite(b.c));
  const W = 420, H = 150;
  const last = fc.last_close ?? bars[bars.length - 1]?.c, pred = fc.pred_close_h, band = fc.neutral_band ?? 0;
  const vals = [...bars.flatMap((b) => [b.h, b.l]), pred, last + band, last - band].filter((v) => v != null && isFinite(v));
  if (!vals.length) return <p className="empty">BRAK DANYCH</p>;
  const mn = Math.min(...vals), mx = Math.max(...vals), Y = (v: number) => 6 + (mx - v) / (mx - mn || 1) * (H - 12);
  const n = bars.length + Math.max(2, fc.horizon_bars || 6), cw = (W - 10) / n, xNow = 5 + bars.length * cw;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" aria-label="Świece rzeczywiste i prognoza Kronos">
      <rect x={xNow} y={Y(last + band)} width={W - xNow} height={Math.max(1, Y(last - band) - Y(last + band))} fill="rgba(181,168,255,.08)" />
      {bars.map((b, i) => { const x = 5 + (i + .5) * cw, up = b.c >= b.o; return (<g key={i}>
        <line x1={x} x2={x} y1={Y(b.h)} y2={Y(b.l)} stroke={up ? "rgba(236,239,245,.7)" : "rgba(138,145,158,.9)"} />
        <rect x={x - cw * .3} y={Math.min(Y(b.o), Y(b.c))} width={cw * .6} height={Math.max(1, Math.abs(Y(b.o) - Y(b.c)))} fill={up ? "rgba(236,239,245,.9)" : "#000"} stroke={up ? "none" : "rgba(138,145,158,.9)"} /></g>); })}
      <line x1={xNow} x2={xNow} y1={0} y2={H} stroke="#3a4152" strokeDasharray="3 3" />
      {pred != null && <polyline fill="none" stroke="#b5a8ff" strokeWidth="1.6" points={`${xNow},${Y(last)} ${W - 5},${Y(pred)}`} />}
    </svg>);
}
