// 1.13 pages of the grouped menu. Every value comes from the backend (shared engines: analytics/ta.py, signal.py,
// double_bottom.py, library.py and the existing modules) - the frontend never computes a second version of an indicator.
// UNKNOWN / missing data is shown as "—" with the reason, never as green; nothing on these pages changes the trading mode.
import { ManualPadCard } from "../components/StructureIntel";
import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, LineStyle, type Time } from "lightweight-charts";
import { apiGet, apiSend } from "../api";
import { AutoPanel, StrategiesPanel, useAutoFull } from "../components/AutoPanels";
import { BotLog, NewsPanel, RiskPanel } from "../components/BottomPanels";
import CandleForecastPanel from "../components/CandleForecastPanel";
import ChartPanel from "../components/ChartPanel";
import { useChartOpts } from "../components/ChartToolbar";
import { LeverageSettings } from "../components/LeverageSettings";
import { BotSignalsPanel, MarketDetail, MarketsPanel } from "../components/MarketsPanel";
import MLPanel from "../components/MLPanel";
import ScalpPanel from "../components/ScalpPanel";
import Section from "../components/Section";
import SignalsPanel, { EnginePlan } from "../components/SignalsPanel";
import StatsPanel from "../components/StatsPanel";
import VolPanel from "../components/VolPanel";
import { href, usePersisted } from "../router";
import { useStore } from "../store";
import { useTheme } from "../theme";
import { useUi } from "../ui";
import { cls, fmtMoney, fmtNum, fmtTime, tone } from "../util";

const TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const STATUS_PL: Record<string, string> = { ready: "gotowe", warming_up: "rozgrzewka", stale: "nieaktualne", unavailable: "niedostępne", error: "błąd", disabled: "wyłączone" };
const CTX_PL: Record<string, string> = { TREND_UP: "trend wzrostowy", TREND_DOWN: "trend spadkowy", CONSOLIDATION: "konsolidacja", CORRECTION: "korekta",
  MIXED: "mieszany", UNKNOWN: "nieznany" };
const DB_PL: Record<string, string> = { INVALID: "brak struktury", CANDIDATE: "kandydat", CONFIRMED: "potwierdzona", FAILED: "nieudana" };

export function useAnalytics() {
  const { s } = useStore();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    apiGet("/api/v1/analytics").then((r) => { setD(r); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
  }, [s.analytics?.updated_at]);
  return { a: s.analytics ? { ...(d || {}), ...s.analytics } : d, err };
}

function St({ r }: { r: any }) {
  if (!r) return <span className="badge warn">brak wyniku</span>;
  const k = r.status === "ready" ? (r.quality_flags?.length ? "warn" : "ok") : r.status === "error" ? "bad" : "warn";
  return <span className={cls("badge", k)} title={r.reason || (r.quality_flags || []).join(", ")}>{STATUS_PL[r.status] ?? r.status}{r.quality_flags?.length ? ` · ${r.quality_flags.join(", ")}` : ""}</span>;
}

function Prov({ r }: { r: any }) {
  if (!r) return null;
  return <p className="muted small">dane do {fmtTime(r.as_of, true)} · dostępne od {fmtTime(r.available_at, true)} · {r.samples} świec · {r.algorithm_version} · konfig. {r.config_hash}
    {r.latency_ms != null ? ` · ${r.latency_ms} ms` : ""}{r.closed_bars_only ? " · tylko zamknięte świece" : " · PODGLĄD"}</p>;
}

function TfPicker({ tf, set, list = TFS }: { tf: string; set: (t: string) => void; list?: string[] }) {
  return (
    <div className="tabs small" role="group" aria-label="Interwał">
      {list.map((t) => <button key={t} className={cls(tf === t && "on")} aria-pressed={tf === t} onClick={() => set(t)}>{t}</button>)}
    </div>);
}

function DemoFlag() {
  const { s } = useStore();
  return s.synthetic ? <span className="demo-flag" data-testid="demo-flag">DANE PRZYKŁADOWE</span> : null;
}

// ------------------------------------------------------------------------------------------------ Pulpit
export function DashboardPage() {
  const { s } = useStore();
  const { a } = useAnalytics();
  const [tf, setTf] = usePersisted<string>("dash.tf", "M5", (x) => ["M1", "M5", "M15", "M30", "H1"].includes(x));
  const [full, setFull] = useState(false);
  const [opts] = useChartOpts("dash", { showRsi: false, showMacd: false, showStructure: true, showZones: true, showVol: false, showPatterns: false, showAiLevels: false });
  const q = s.quote || {};
  const acc = s.account;
  const con = s.connection || {};
  const sup = a?.support;
  const d = s.decision;
  const blocks: string[] = [];
  if (con.state !== "CONNECTED") blocks.push(`MT5: ${con.state ?? "?"}`);
  if (s.mode?.kill_switch) blocks.push("STOP aktywny");
  for (const st of Object.entries(a?.timeframes || {})) if ((st[1] as any)?.status === "stale") blocks.push(`${st[0]}: dane nieaktualne`);
  const analysisState = con.state !== "CONNECTED" ? "Analiza wstrzymana — brak świeżych danych" : d?.checklist?.state_label || d?.signal?.status_pl || "Oczekiwanie na potwierdzenie";
  return (
    <div className="dash-page" data-testid="page-pulpit">
      <div className="page-head">
        <h1>Pulpit <small className="muted">{s.symbol?.symbol ?? "?"} · {s.auto?.selected_strategy_id ?? "—"} · MT5 {con.state === "CONNECTED" ? "połączony" : con.state ?? "…"}</small></h1>
        <DemoFlag />
        <span className={cls("badge", con.state === "CONNECTED" ? "" : "warn")} data-testid="dash-state">{analysisState}</span>
      </div>
      <div className="dash-bar" data-testid="dash-bar">
        <div className="card"><label>Cena (Bid / Ask)</label><b>{q.bid != null ? `${fmtNum(q.bid, s.symbol?.digits ?? 2)} / ${fmtNum(q.ask, s.symbol?.digits ?? 2)}` : "—"}</b>
          <small className="muted">{q.bid == null ? "brak kwotowania z MT5" : `źródło MT5 · tick ${q.age_seconds != null ? Math.round(q.age_seconds) + " s temu" : "?"}`}</small></div>
        <div className="card"><label>Saldo / equity (MT5)</label><b>{acc ? `${fmtMoney(acc.balance, acc.currency)} / ${fmtMoney(acc.equity, acc.currency)}` : "—"}</b>
          <small className="muted">{acc ? acc.server : "brak danych rachunku"}</small></div>
        <div className="card"><label>Koszt wykonania (spread)</label><b>{q.bid != null && q.ask != null ? fmtNum(q.ask - q.bid, s.symbol?.digits ?? 2) : "—"}</b>
          <small className="muted">prowizja: Ustawienia → koszty; „Zero” ≠ 0 kosztów</small></div>
        <div className="card"><label>Ostatnie dane</label><b>{fmtTime(q.time_utc, true) || "—"}</b><small className="muted">{s.decision?.data_quality ?? "?"}</small></div>
      </div>
      {blocks.length > 0 && <p className="small warn" data-testid="dash-blocks">Blokady analizy: {blocks.join(" · ")}</p>}
      <div className="dash-main">
        <div className="card">
          <div className="page-head" style={{ border: 0, padding: 0 }}><b>Wykres</b><TfPicker tf={tf} set={setTf} list={["M1", "M5", "M15", "M30", "H1"]} /></div>
          <div className="dash-chart"><ChartPanel key={tf} tf={tf} index={0} chartId={`dash-${tf}`} opts={opts} variant="main" fullscreen={full} onFullscreen={() => setFull(!full)} /></div>
        </div>
        <div className="card" data-testid="dash-conditions"><h3>Warunki wejścia</h3><EnginePlan />
          <p className="muted small">„4/6” oznacza liczbę spełnionych warunków, nie szansę powodzenia. Warunki opcjonalne są oznaczone osobno.</p></div>
      </div>
      <div className="mtf-tiles" data-testid="dash-mtf">
        {["H4", "H1", "M30", "M15", "M5", "M1"].map((t) => {
          const st = a?.timeframes?.[t] || {};
          const ma = st.moving_averages?.values;
          const bb = st.bollinger?.values;
          return (
            <a key={t} className="mtf-tile" href={href("wykresy", { params: { tf: t } })} data-tf={t}>
              <b>{t}</b> <span className={cls("badge", st.status === "ready" ? "" : "warn")}>{STATUS_PL[st.status] ?? "—"}</span>
              <div className="small">{ma ? CTX_PL[ma.context] ?? ma.context : "—"}</div>
              <div className="small muted">%b {bb?.percent_b ?? "—"} · {bb?.squeeze ? "squeeze" : bb?.expanding ? "rozszerzanie" : "BB normalne"}</div>
            </a>);
        })}
      </div>
      <div className="card" data-testid="dash-support"><h3>Co wspiera analizę <small className="muted">({sup?.main_tf ?? "M5"}, kontekst {sup?.context_tf ?? "H1"})</small></h3>
        {sup ? (<>
          <ul className="small">{(sup.groups || []).map((g: any, i: number) => <li key={i}><b>{g.group}</b> · {g.source}: <b>{g.state}</b> – {g.detail}{g.note ? ` (${g.note})` : ""}</li>)}</ul>
          {sup.explanation?.length > 0 && <div className="small"><b>Wyjaśnienie:</b> {sup.explanation.join(" ")}</div>}
          <p className="muted small">{sup.influence}</p></>) : <p className="muted">Analityka jeszcze nie policzona (czeka na zamknięte świece).</p>}
      </div>
    </div>);
}

// ------------------------------------------------------------------------------------------------ Indykatory
export function IndicatorsPage() {
  const { a, err } = useAnalytics();
  const [tf, setTf] = usePersisted<string>("ind.tf", "M5", (x) => TFS.includes(x));
  const st = a?.timeframes?.[tf] || {};
  const bb = st.bollinger, ma = st.moving_averages;
  const bv = bb?.values, mv = ma?.values;
  return (
    <div data-testid="page-indykatory">
      <div className="page-head"><h1>Indykatory</h1><TfPicker tf={tf} set={setTf} /><DemoFlag />{err && <span className="badge bad">{err}</span>}</div>
      <div className="an-grid">
        <div className="card" data-testid="ind-bb"><h3>Bollinger Bands <small className="muted">(BB – pasma zmienności wokół średniej)</small> <St r={bb} /></h3>
          {bv ? (<dl className="an-kv">
            <dt>Parametry</dt><dd>close, SMA {bb.config.period}, ×{bb.config.k} odchylenia (populacyjne, ddof=0)</dd>
            <dt>Środek / górne / dolne</dt><dd>{bv.middle} / {bv.upper} / {bv.lower}</dd>
            <dt>%b</dt><dd>{bv.percent_b ?? "— (płaskie okno)"} <small className="muted">(może być poza 0–1)</small></dd>
            <dt>Szerokość</dt><dd>{bv.bandwidth_ratio} (ułamek ceny) · {bv.bandwidth_pct}% · percentyl {bv.bandwidth_percentile ?? "—"}</dd>
            <dt>Squeeze / rozszerzanie</dt><dd>{bv.squeeze == null ? "—" : bv.squeeze ? "tak" : "nie"} / {bv.expanding == null ? "—" : bv.expanding ? "tak" : "nie"}</dd>
            <dt>Zdarzenia (ostatnia zamknięta)</dt><dd>{bv.events.join(", ") || "brak"}</dd>
            <dt>Trend przy paśmie</dt><dd>{bv.trend_walk ?? "nie"}</dd>
            <dt>Nachylenie środka</dt><dd>{bv.middle_slope_atr_per_bar ?? "—"} ATR/bar</dd>
            <dt>Interpretacja</dt><dd>{bv.interpretation.join("; ")}</dd>
          </dl>) : <p className="muted">{bb?.reason ?? "brak wyniku"}</p>}
          <Prov r={bb} />
          <p className="muted small">Dotknięcie pasma nie jest poleceniem kupna/sprzedaży. Środek BB = SMA {bb?.config?.period ?? 20} – nie liczy się jako osobny głos średnich.</p>
        </div>
        <div className="card" data-testid="ind-ma"><h3>MAs – średnie kroczące <St r={ma} /></h3>
          {mv ? (<>
            <div className="table-wrap"><table className="tbl"><thead><tr><th>Średnia</th><th>Wartość</th><th>Cena</th><th>Odległość (ATR)</th><th>Nachylenie (ATR/bar)</th><th>Wykres</th></tr></thead>
              <tbody>{mv.mas.map((m: any) => (
                <tr key={m.id}><td><b>{m.id}</b>{m.same_as_bb_middle ? <small className="muted"> = środek BB</small> : null}</td><td>{m.value ?? "rozgrzewka"}</td>
                  <td>{m.price_vs ?? "—"}</td><td>{m.distance_atr ?? "—"}</td><td>{m.slope_atr_per_bar ?? "—"}</td><td>{m.visible ? "tak" : "nie"}</td></tr>))}</tbody></table></div>
            <dl className="an-kv"><dt>Uporządkowanie</dt><dd>{mv.ordering}</dd><dt>Kontekst</dt><dd><b>{CTX_PL[mv.context] ?? mv.context}</b> – {mv.context_rule}</dd>
              <dt>ATR14</dt><dd>{mv.atr14 ?? "—"}</dd></dl>
            <h4>Przecięcia potwierdzone zamknięciem</h4>
            <ul className="small">{mv.crosses.length ? mv.crosses.slice().reverse().map((c: any) => <li key={c.event_id}>{fmtTime(c.bar_open_utc, true)} · {c.kind} {c.fast}/{c.slow} <small className="muted">{c.event_id}</small></li>)
              : <li className="muted">brak w ostatnich 50 świecach</li>}</ul></>) : <p className="muted">{ma?.reason ?? "brak wyniku"}</p>}
          <Prov r={ma} />
        </div>
        <div className="card wide"><h3>Parametry</h3><p className="small">Parametry BB i średnich ustawiasz w <code>data\config.json</code>, sekcja <code>analytics</code>
          (walidowane przed zapisem). Widoczność linii na wykresie nie zmienia reguł strategii. Profil przykładowy EMA 9/21, SMA 50/200 nie jest optymalizowany dla XAUUSD-.</p></div>
      </div>
    </div>);
}

// ------------------------------------------------------------------------------------------------ Analiza sygnału
function Spectrum({ spec }: { spec: any[] }) {
  const t: any = useTheme().effective;
  if (!spec?.length) return <p className="muted small">brak widma</p>;
  const W = 600, H = 160, mx = Math.max(...spec.map((x) => x.power_share)) || 1;
  const lp = (p: number) => Math.log(p);
  const p0 = lp(Math.min(...spec.map((x) => x.period_bars))), p1 = lp(Math.max(...spec.map((x) => x.period_bars)));
  const X = (p: number) => 30 + ((lp(p) - p0) / ((p1 - p0) || 1)) * (W - 40);
  return (
    <svg className="spec-svg" viewBox={`0 0 ${W} ${H + 24}`} role="img" aria-label="Widmo FFT: udział mocy względem okresu w świecach">
      <line x1={30} y1={H} x2={W - 10} y2={H} stroke="currentColor" opacity={0.4} />
      {spec.map((x, i) => <line key={i} x1={X(x.period_bars)} x2={X(x.period_bars)} y1={H} y2={H - (x.power_share / mx) * (H - 10)} stroke={String(t?.accent ?? "#d8b45f")} strokeWidth={2} />)}
      {[2, 4, 8, 16, 32, 64, 128].filter((p) => lp(p) >= p0 && lp(p) <= p1).map((p) => <text key={p} x={X(p)} y={H + 16} fontSize={11} textAnchor="middle" fill="currentColor">{p}</text>)}
      <text x={W - 10} y={H + 16} fontSize={11} textAnchor="end" fill="currentColor">okres [świece]</text>
    </svg>);
}

function Lines({ series, label }: { series: number[][]; label: string }) {
  const t: any = useTheme().effective;
  if (!series?.length) return null;
  const W = 600, h = 50;
  const cols = [t?.accent, t?.info, t?.ind3, t?.ind4, t?.ind5, t?.ind6].map(String);
  return (
    <svg className="comp-svg" viewBox={`0 0 ${W} ${series.length * (h + 8)}`} role="img" aria-label={label}>
      {series.map((s, k) => {
        const mn = Math.min(...s), mx = Math.max(...s), r = mx - mn || 1;
        const pts = s.map((v, i) => `${(i / (s.length - 1)) * (W - 50) + 46},${k * (h + 8) + h - ((v - mn) / r) * h}`).join(" ");
        return <g key={k}><text x={2} y={k * (h + 8) + h / 2} fontSize={11} fill="currentColor">#{k + 1}</text>
          <polyline points={pts} fill="none" stroke={cols[k % cols.length]} strokeWidth={1.5} strokeDasharray={k % 2 ? "4 2" : undefined} /></g>;
      })}
    </svg>);
}

export function SignalAnalysisPage() {
  const { a } = useAnalytics();
  const [tf, setTf] = usePersisted<string>("sig.tf", "M5", (x) => ["M1", "M5", "M15", "M30", "H1"].includes(x));
  const [full, setFull] = useState<any>(null);
  useEffect(() => { apiGet(`/api/v1/analytics/tf/${tf}`).then(setFull).catch(() => setFull(null)); }, [tf, a?.timeframes?.[tf]?.fft?.as_of, a?.timeframes?.[tf]?.vmd?.as_of]);
  const fft = full?.fft, emd = full?.emd, vmd = full?.vmd;
  const sigTfs = a?.config?.signal_timeframes || ["M5", "M15", "H1"];
  return (
    <div data-testid="page-sygnal">
      <div className="page-head"><h1>Analiza sygnału</h1><TfPicker tf={tf} set={setTf} list={["M1", "M5", "M15", "M30", "H1"]} /><DemoFlag /></div>
      {!sigTfs.includes(tf) && <p className="small warn">Interwał {tf} nie jest liczony (analytics.signal_timeframes = {sigTfs.join(", ")}).</p>}
      <p className="small muted">VMD, FFT i EMD opisują to samo okno ceny – nie są trzema niezależnymi potwierdzeniami i nie przewidują kierunku. Tryb: obserwacyjny (bez wpływu na decyzje).</p>
      <div className="an-grid">
        <div className="card" data-testid="sig-fft"><h3>FFT – widmo (Fast Fourier Transform) <St r={fft} /></h3>
          {fft?.values ? (<>
            <dl className="an-kv"><dt>Wejście</dt><dd>{fft.values.input}</dd><dt>Próbkowanie</dt><dd>{fft.values.sampling}, okno {fft.values.window_bars} świec, funkcja okna {fft.values.window_function}</dd>
              <dt>Normalizacja</dt><dd>{fft.values.normalization}; zero-padding: {fft.values.zero_padding}</dd>
              <dt>Dominujące okresy</dt><dd>{fft.values.dominant.map((d: any) => `${d.period_bars} świec (${d.period_minutes} min, ${(d.power_share * 100).toFixed(1)}% mocy)`).join(" · ") || "brak"}</dd>
              <dt>Stabilność</dt><dd>{fft.values.dominant_stable == null ? "—" : fft.values.dominant_stable ? "stabilny względem okna o 5 świec wcześniej" : "niestabilny"}</dd></dl>
            <Spectrum spec={fft.values.spectrum} /></>) : <p className="muted">{fft?.reason ?? "brak wyniku"}</p>}
          <Prov r={fft} />
        </div>
        <div className="card" data-testid="sig-vmd"><h3>VMD – mody (Variational Mode Decomposition) <St r={vmd} /></h3>
          {vmd?.values ? (<>
            <div className="table-wrap"><table className="tbl"><thead><tr><th>Mod</th><th>Okres</th><th>Energia</th><th>Hipoteza</th></tr></thead>
              <tbody>{vmd.values.modes.map((m: any) => <tr key={m.mode}><td>#{m.mode}</td><td>{m.period_bars == null ? "trend (DC)" : `${m.period_bars} św.`}</td>
                <td>{(m.energy_share * 100).toFixed(1)}%</td><td>{m.role}</td></tr>)}</tbody></table></div>
            <dl className="an-kv"><dt>K / alpha</dt><dd>{vmd.values.K} / {vmd.values.alpha}</dd><dt>Zbieżność</dt><dd>{vmd.values.converged ? "tak" : "NIE"} ({vmd.values.iterations} iteracji)</dd>
              <dt>Błąd rekonstrukcji</dt><dd>{vmd.values.reconstruction_rel_error}</dd><dt>Zmiana częstotliwości vs okno −5</dt><dd>{vmd.values.omega_change_vs_lag ?? "—"}</dd></dl>
            <Lines series={vmd.values.series?.modes_last_64 || []} label="Ostatnie 64 wartości modów VMD" />
            <p className="muted small">{vmd.values.assignment_rule}</p></>) : <p className="muted">{vmd?.reason ?? "brak wyniku"}</p>}
          <Prov r={vmd} />
        </div>
        <div className="card" data-testid="sig-emd"><h3>EMD – składowe IMF (Empirical Mode Decomposition) <St r={emd} /></h3>
          {emd?.values ? (<>
            <div className="table-wrap"><table className="tbl"><thead><tr><th>IMF</th><th>Śr. okres</th><th>Energia</th><th>Sifting</th></tr></thead>
              <tbody>{emd.values.imfs.map((m: any) => <tr key={m.imf}><td>#{m.imf}</td><td>{m.mean_period_bars ?? "—"} św.</td><td>{(m.energy_share * 100).toFixed(1)}%</td><td>{m.sifts}</td></tr>)}</tbody></table></div>
            <dl className="an-kv"><dt>Rekonstrukcja</dt><dd>max błąd {emd.values.reconstruction_max_abs_error}</dd><dt>Rewizja końca okna</dt><dd>{emd.values.end_revision_vs_lag ?? "—"}</dd>
              <dt>Metoda brzegów</dt><dd>{emd.values.method}</dd></dl>
            <Lines series={emd.values.series?.imf_last_64 || []} label="Ostatnie 64 wartości IMF" /></>) : <p className="muted">{emd?.reason ?? "brak wyniku"}</p>}
          <Prov r={emd} />
        </div>
      </div>
    </div>);
}

// ------------------------------------------------------------------------------------------------ Formacje i biblioteka
function SampleChart({ sample, result }: { sample: any; result: any }) {
  const box = useRef<HTMLDivElement>(null);
  const t: any = useTheme().effective;
  useEffect(() => {
    if (!box.current || !sample) return;
    const c = createChart(box.current, { autoSize: true, layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: String(t?.chartLabels ?? "#a8b3bf"), fontSize: 10 },
      grid: { vertLines: { color: String(t?.chartGrid ?? "#ffffff0a") }, horzLines: { color: String(t?.chartGrid ?? "#ffffff0a") } }, timeScale: { timeVisible: true } });
    const ser = c.addSeries(CandlestickSeries, { upColor: String(t?.upBody), downColor: String(t?.downBody), wickUpColor: String(t?.upWick), wickDownColor: String(t?.downWick),
      borderUpColor: String(t?.upBorder), borderDownColor: String(t?.downBorder) });
    const T = (iso: string) => Math.floor(Date.parse(iso) / 1000) as Time;
    ser.setData(sample.bars.map((b: any) => ({ time: T(b.open_utc), open: b.o, high: b.h, low: b.l, close: b.c })));
    const v = result?.values;
    if (v?.coordinates) {                                  // exact coordinates of the validator - never searched again here
      const co = v.coordinates;
      const mk: any[] = [{ time: T(co.bottom1.time), position: "belowBar", shape: "arrowUp", color: String(t?.accent), text: "Dołek 1" },
        { time: T(co.bottom2.time), position: "belowBar", shape: "arrowUp", color: String(t?.accent), text: "Dołek 2" }];
      if (co.decisive) mk.push({ time: T(co.decisive.time), position: co.decisive.kind === "BREAK_ABOVE_NECKLINE" ? "aboveBar" : "belowBar", shape: "circle",
        color: String(co.decisive.kind === "BREAK_ABOVE_NECKLINE" ? t?.checkMet : t?.bad), text: v.status });
      createSeriesMarkers(ser, mk.sort((a, b) => a.time - b.time));
      ser.createPriceLine({ price: co.neckline.price, color: String(t?.info), lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: "neckline" });
    }
    c.timeScale().fitContent();
    return () => c.remove();
  }, [sample, result, t]);
  return <div ref={box} className="sample-chart" data-testid="sample-chart" />;
}

export function PatternsPage() {
  const { s } = useStore();
  const [rows, setRows] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [flt, setFlt] = useState({ tf: "", status: "" });
  const [view, setView] = useState<{ sample: any; result: any; saved: any; revalidated?: boolean } | null>(null);
  const [job, setJob] = useState<any>(null);
  const [live, setLive] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState({ tf: "M5", start: "", end: "", note: "" });
  const load = () => {
    const q = new URLSearchParams(Object.entries(flt).filter(([, v]) => v) as any).toString();
    apiGet(`/api/v1/patterns/samples${q ? "?" + q : ""}`).then((r) => { setRows(r.items); setJobs(r.jobs); }).catch((e) => setMsg(String(e?.message || e)));
    apiGet("/api/v1/patterns/live").then(setLive).catch(() => undefined);
  };
  useEffect(load, [flt.tf, flt.status, s.analytics?.updated_at]);
  useEffect(() => {
    // the report (report_id / export_status) is written just AFTER the final status - keep polling until it lands (bounded)
    const settled = (j: any) => j.status !== "RUNNING" && (j.report_id || j.export_status);
    if (!job || settled(job)) return;
    let after = 0;
    const t = setInterval(() => apiGet(`/api/v1/patterns/jobs/${job.job_id}`).then((j) => {
      setJob(j);
      if (j.status !== "RUNNING" && (settled(j) || ++after >= 15)) { clearInterval(t); load(); }
    }).catch(() => undefined), 700);
    return () => clearInterval(t);
  }, [job?.job_id, job?.status, job?.report_id, job?.export_status]);
  const run = async (ids: number[] | null) => {
    setMsg(null);
    try { const r = await apiSend("POST", "/api/v1/patterns/validate", { ids }); setJob({ job_id: r.job_id, status: "RUNNING", progress: 0, total: r.total }); }
    catch (e: any) { setMsg(String(e?.message || e)); }
  };
  // SHOW ON CHART = saved immutable result (sample_id + result_id) - no re-analysis; REVALIDATE is a separate explicit action
  const show = async (id: number) => {
    setMsg(null);
    const sample = await apiGet(`/api/v1/patterns/samples/${id}`);
    try {
      const saved = await apiGet(`/api/v1/patterns/samples/${id}/result`);
      setView({ sample, result: saved.result, saved });
    } catch { setView({ sample, result: null, saved: null }); }
  };
  const revalidate = async (id: number) => {
    const [sample, r] = await Promise.all([apiGet(`/api/v1/patterns/samples/${id}`), apiSend("POST", `/api/v1/patterns/samples/${id}/validate`)]);
    setView({ sample, result: r.result, saved: null, revalidated: true });
  };
  const add = async () => {
    setMsg(null);
    try {
      const r = await apiSend("POST", "/api/v1/patterns/samples", { tf: form.tf, start_utc: form.start, end_utc: form.end, note: form.note });
      setMsg(r.duplicate ? `Próbka już istnieje (#${r.id}) – nie nadpisano.` : `Zapisano próbkę #${r.id} (${r.bars} świec).`);
      load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
  };
  const exportAll = async () => {
    const d = await apiGet("/api/v1/patterns/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url; a.download = `biblioteka_formacji_${Date.now()}.json`; a.click();
    URL.revokeObjectURL(url);
  };
  const importFile = async (f: File | undefined) => {
    if (!f) return;
    try { const r = await apiSend("POST", "/api/v1/patterns/import", JSON.parse(await f.text())); setMsg(r.ok ? `Import: dodano ${r.added}, duplikaty ${r.duplicates_kept_existing}, błędy ${r.errors.length}` : r.error); load(); }
    catch (e: any) { setMsg(`Import nieudany: ${e?.message || e}`); }
  };
  const del = async (id: number) => { await apiSend("DELETE", `/api/v1/patterns/samples/${id}`); load(); };
  return (
    <div data-testid="page-formacje">
      <div className="page-head"><h1>Formacje i biblioteka – Double Bottom</h1><DemoFlag /></div>
      <div className="an-grid">
        <div className="card wide" data-testid="db-live"><h3>Skaner bieżących danych (causal_as_of, tylko zamknięte świece)</h3>
          <div className="table-wrap"><table className="tbl"><thead><tr><th>TF</th><th>Status</th><th>Dołki</th><th>Neckline</th><th>Rozstrzygnięcie</th><th>Dostępne od</th><th>pattern_id</th></tr></thead>
            <tbody>{Object.entries(live?.timeframes || {}).map(([tf, r]: any) => {
              const v = r?.values || {};
              const co = v.coordinates;
              return <tr key={tf}><td>{tf}</td><td><b>{DB_PL[v.status] ?? r?.status ?? "—"}</b> <small className="muted">{v.reason}</small></td>
                <td>{co ? `${co.bottom1.price} (${fmtTime(co.bottom1.time, true)}) / ${co.bottom2.price} (${fmtTime(co.bottom2.time, true)})` : "—"}</td>
                <td>{co?.neckline?.price ?? "—"}</td><td>{co?.decisive ? `${co.decisive.kind} ${fmtTime(co.decisive.time, true)}` : "—"}</td>
                <td>{v.available ? `dołek 2: ${fmtTime(v.available.bottom2_pivot_known_at, true)}${v.available.decisive_known_at ? ` · rozstrz.: ${fmtTime(v.available.decisive_known_at, true)}` : ""}` : "—"}</td>
                <td><small>{v.pattern_id ?? "—"}</small></td></tr>;
            })}</tbody></table></div>
          <p className="muted small">Profil: {live?.profile === "CONTEXT_FOR_STRATEGY" ? "kontekst dla istniejącej strategii" : "samodzielna analiza struktury"}. Wynik zgodności kształtu nie jest prawdopodobieństwem zysku;
            retest i zasięg to hipotezy.</p>
          <details className="small"><summary>Zdarzenia ({live?.events?.length ?? 0})</summary><ul>{(live?.events || []).map((e: any) => <li key={e.id}>{fmtTime(e.created_at, true)} · {e.timeframe} · {e.status} · {e.pattern_id}</li>)}</ul></details>
        </div>
        <div className="card wide" data-testid="db-library"><h3>Biblioteka próbek</h3>
          <div className="page-head" style={{ border: 0, padding: 0 }}>
            <select value={flt.tf} onChange={(e) => setFlt({ ...flt, tf: e.target.value })} aria-label="Filtr TF"><option value="">wszystkie TF</option>{TFS.map((t) => <option key={t}>{t}</option>)}</select>
            <select value={flt.status} onChange={(e) => setFlt({ ...flt, status: e.target.value })} aria-label="Filtr statusu"><option value="">wszystkie statusy</option>
              {["INVALID", "CANDIDATE", "CONFIRMED", "FAILED", "ERROR", "MISSING"].map((x) => <option key={x}>{x}</option>)}</select>
            <button className="btn" disabled={!sel.size} onClick={() => run([...sel])} data-testid="db-validate-selected">VALIDATE SELECTED ({sel.size})</button>
            <button className="btn" onClick={() => run(null)} data-testid="db-validate-all">VALIDATE ALL</button>
            <button className="btn ghost" onClick={exportAll}>Eksport JSON</button>
            <label className="btn ghost">Import JSON<input type="file" accept="application/json" hidden onChange={(e) => importFile(e.target.files?.[0])} /></label>
          </div>
          {job && <p className="small" data-testid="db-job">Zadanie {job.job_id}: <b>{job.status}</b> {job.progress}/{job.total}
            {job.counts ? ` · ${Object.entries(job.counts).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}{job.report_id ? ` · raport ${job.report_id}` : ""}{job.export_status && job.export_status !== "OK" ? ` · eksport: ${job.export_status}` : ""}
            {job.status === "RUNNING" && <button className="link" onClick={() => apiSend("POST", `/api/v1/patterns/jobs/${job.job_id}/cancel`)}> Anuluj</button>}
            {job.status === "CANCELLED" && " – wynik częściowy, nie jest pełną walidacją"}</p>}
          {msg && <p className="small warn">{msg}</p>}
          <div className="table-wrap"><table className="tbl" data-testid="db-table"><thead><tr><th></th><th>#</th><th>Symbol</th><th>TF</th><th>Zakres</th><th>Pochodzenie</th><th>Ostatni status</th><th>Reguły</th><th></th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.id}><td><input type="checkbox" aria-label={`Zaznacz próbkę ${r.id}`} checked={sel.has(r.id)}
              onChange={(e) => { const n = new Set(sel); e.target.checked ? n.add(r.id) : n.delete(r.id); setSel(n); }} /></td>
              <td>{r.id}</td><td>{r.symbol}</td><td>{r.timeframe}</td><td className="small">{fmtTime(r.start_utc, true)} – {fmtTime(r.end_utc, true)}</td><td className="small">{r.origin}</td>
              <td>{r.last_status ?? "—"}</td><td className="small">{r.last_rules_version ?? "—"}</td>
              <td><button className="link" onClick={() => show(r.id)}>SHOW ON CHART</button> <button className="link" onClick={() => del(r.id)} aria-label={`Usuń próbkę ${r.id}`}>usuń</button></td></tr>)}
              {!rows.length && <tr><td colSpan={9} className="muted">Biblioteka pusta – dodaj próbkę z zakresu świec poniżej albo zaimportuj plik.</td></tr>}</tbody></table></div>
          <details className="small" open={!rows.length}><summary>Dodaj próbkę z zakresu zamkniętych świec</summary>
            <div className="page-head" style={{ border: 0, padding: 0 }}>
              <select value={form.tf} onChange={(e) => setForm({ ...form, tf: e.target.value })} aria-label="TF próbki">{TFS.map((t) => <option key={t}>{t}</option>)}</select>
              <input placeholder="od (UTC) 2026-10-15T08:00:00Z" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} aria-label="Początek zakresu UTC" />
              <input placeholder="do (UTC) 2026-10-15T14:00:00Z" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} aria-label="Koniec zakresu UTC" />
              <input placeholder="notatka" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} aria-label="Notatka" />
              <button className="btn" onClick={add}>Zapisz próbkę</button></div>
            <p className="muted">Zapisywane są surowe OHLCV z feedu bota (symbol, TF, granice, hash danych). Istniejąca próbka nie jest nadpisywana.</p></details>
          {jobs.length > 0 && <details className="small"><summary>Ostatnie zadania walidacji ({jobs.length})</summary><ul>{jobs.map((j) => <li key={j.job_id}>{fmtTime(j.created_at, true)} · {j.kind} · {j.status} {j.progress}/{j.total} · {j.rules_version}{j.report_id ? ` · raport ${j.report_id}` : ""}</li>)}</ul></details>}
        </div>
        {view && <div className="card wide" data-testid="db-view"><h3>Próbka #{view.sample.id} · {view.sample.symbol} {view.sample.timeframe} – <b>{view.result ? (DB_PL[view.result?.values?.status] ?? view.result?.status) : "brak zapisanego wyniku"}</b>
          <button className="link" onClick={() => setView(null)}> zamknij</button> <button className="link" onClick={() => revalidate(view.sample.id)} data-testid="db-revalidate">REVALIDATE</button></h3>
          <p className="small muted" data-testid="db-view-source">ARCHIVED_SAMPLE_VIEW – oryginalne świece próbki (osobny wykres przeglądu, aktywny instrument bez zmian).{" "}
            {view.saved ? <>Wynik zapisany <code>{view.saved.result_id}</code> · zadanie {view.saved.job_id} · reguły {view.saved.rules_version}</> : view.revalidated ? "Wynik REVALIDATE (nowe obliczenie, nie zapisane w zadaniu)." : null}</p>
          {view.saved && view.saved.sample_sha && view.saved.sample_sha !== view.sample.data_sha256 && <p className="bad small" data-testid="db-hash-mismatch">Hash próbki ≠ hash z wyniku – nakładka zablokowana.</p>}
          {!view.result && <p className="warn small" data-testid="db-no-result">Ta próbka nie ma zapisanego wyniku – najpierw waliduj (VALIDATE SELECTED / ALL) albo użyj REVALIDATE.</p>}
          {view.result && !(view.saved && view.saved.sample_sha && view.saved.sample_sha !== view.sample.data_sha256) && <SampleChart sample={view.sample} result={view.result} />}
          {view.result?.values ? (<dl className="an-kv"><dt>Powód</dt><dd>{view.result.values.reason}</dd>
            {view.result.values.measurements && <><dt>Pomiary</dt><dd>głębokość {view.result.values.measurements.depth} ({view.result.values.measurements.depth_pct}%), różnica dołków {view.result.values.measurements.bottom_diff_frac}×głęb.,
              odstęp {view.result.values.measurements.separation_bars} św., asymetria {view.result.values.measurements.asymmetry}</dd>
              <dt>Zgodność kształtu</dt><dd>{view.result.values.geometry_score} <small className="muted">({view.result.values.score_note})</small></dd></>}
            <dt>Tryb</dt><dd>{view.result.mode} · {view.result.algorithm_version}</dd></dl>) : <p className="bad small">{view.result?.reason}</p>}
        </div>}
      </div>
    </div>);
}

// ------------------------------------------------------------------------------------------------ pages composed of existing modules
export function ContextPage() {
  const [full] = useAutoFull();
  const { a } = useAnalytics();
  return (
    <div data-testid="page-kontekst">
      <div className="page-head"><h1>Kontekst rynku</h1><DemoFlag /></div>
      <div className="mtf-tiles">{TFS.map((t) => { const st = a?.timeframes?.[t] || {}; return (
        <div key={t} className="mtf-tile"><b>{t}</b><div className="small">{CTX_PL[st.moving_averages?.values?.context] ?? "—"}</div>
          <div className="small muted">BB: {st.bollinger?.values ? (st.bollinger.values.squeeze ? "squeeze" : st.bollinger.values.expanding ? "rozszerzanie" : "normalne") : "—"}</div></div>); })}</div>
      <Section id="ctx.regime" title="Reżim rynku i stan AUTO" defaultOpen testid="ctx-regime"><AutoPanel full={full} /></Section>
      <Section id="ctx.vol" title="Zmienność i walls (źródło: HV_PROXY / IV)" defaultOpen testid="ctx-vol"><VolPanel /></Section>
      <Section id="ctx.news" title="Kalendarz makro i wiadomości (brak feedu pokazany jawnie)" defaultOpen testid="ctx-news"><NewsPanel /></Section>
    </div>);
}

export function PositionsPage() {
  const ui = useUi();
  return (
    <div data-testid="page-pozycje">
      <div className="page-head"><h1>Pozycje i ryzyko</h1><DemoFlag /></div>
      <Section id="pos.list" title="Pozycje, zlecenia, scenariusze" defaultOpen testid="pos-list"><SignalsPanel index={5} /></Section>
      <Section id="pos.risk" title="Ryzyko, blokady i koszty (moduł ryzyka)" defaultOpen testid="pos-risk"><RiskPanel onSettings={ui.openSettings} /></Section>
      <Section id="pos.manual" title="Manual Trade Pad (jawne akcje użytkownika)" testid="pos-manual"><ManualPadCard /></Section>
      <Section id="pos.lev" title="Dźwignia z rachunku i limit ekspozycji" testid="pos-lev"><LeverageSettings /></Section>
    </div>);
}

export function JournalPage() {
  const [mode, setMode] = usePersisted<string>("statsmode", "PAPER");
  const [stats, setStats] = useState<any>(null);
  useEffect(() => { apiGet(`/api/v1/stats?mode=${mode}`).then(setStats).catch(() => setStats(null)); }, [mode]);
  return (
    <div data-testid="page-dziennik">
      <div className="page-head"><h1>Dziennik i wyniki</h1><DemoFlag /></div>
      <Section id="jr.stats" title="Wyniki (liczone z określonej próby)" defaultOpen testid="jr-stats"><StatsPanel index={6} stats={stats} mode={mode} setMode={setMode} /></Section>
      <Section id="jr.log" title="Dziennik bota" defaultOpen testid="jr-log"><BotLog /></Section>
    </div>);
}

export function TestsPage() {
  const [full, reload] = useAutoFull();
  return (
    <div data-testid="page-testy">
      <div className="page-head"><h1>Testy i raporty</h1><DemoFlag /></div>
      <p className="small muted">Replay i porównania uruchamiasz launcherami (19_REPLAY_SCALP.bat, 17_TRENING_SCALP_ML.bat, 12_TRENING_MODELI_XAUUSD.bat); tutaj są ich wyniki.
        Wyniki na danych syntetycznych nie są wynikami rynkowymi.</p>
      <Section id="ts.scalp" title="Scalp: replay, warianty, trening (SHADOW)" defaultOpen testid="ts-scalp"><ScalpPanel /></Section>
      <Section id="ts.ml" title="Modele ML (Decision Tree / XGBoost)" testid="ts-ml"><MLPanel index={7} /></Section>
      <Section id="ts.fc" title="Prognozy świec 5/15/30 (SHADOW)" testid="ts-fc"><CandleForecastPanel /></Section>
      <Section id="ts.strat" title="Monitor strategii (S01–S12)" testid="ts-strat"><StrategiesPanel full={full} reload={reload} /></Section>
    </div>);
}

export function MarketsSection() {
  const [market, setMarket] = useState<string | null>(null);
  return (<><div className="markets-row"><MarketsPanel onOpen={setMarket} /><BotSignalsPanel onOpen={setMarket} /></div>
    {market && <MarketDetail symbol={market} onClose={() => setMarket(null)} />}</>);
}

export function DiagnosticsPage() {
  const { s } = useStore();
  const [diag, setDiag] = useState<any>(null);
  const [tfm, setTfm] = useState<any>(null);
  const load = () => {
    apiGet("/api/v1/analytics/diagnostics").then(setDiag).catch(() => setDiag(null));
    apiGet("/api/v1/timeframes").then(setTfm).catch(() => setTfm(null));
  };
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  const con = s.connection || {};
  return (
    <div data-testid="page-diagnostyka">
      <div className="page-head"><h1>Diagnostyka</h1><DemoFlag /><button className="btn ghost" onClick={load}>Odśwież</button></div>
      <div className="an-grid">
        <div className="card"><h3>MT5 / bridge</h3><dl className="an-kv">
          <dt>Stan</dt><dd><span className={cls("badge", tone(con.state))}>{con.state ?? "?"}</span> {con.reason ?? ""}</dd>
          <dt>Terminal</dt><dd className="small">{con.terminal?.path ?? con.terminal?.name ?? "—"}</dd><dt>Rachunek</dt><dd>{con.account_key ?? "—"}</dd>
          <dt>Połączony od</dt><dd>{fmtTime(con.connected_since, true) || "—"}</dd><dt>Heartbeat</dt><dd>{fmtTime(con.last_heartbeat, true) || "—"}</dd>
          <dt>Próby / epoka</dt><dd>{con.attempts ?? 0} / {con.session_epoch ?? "—"}</dd><dt>Czas serwera</dt><dd>{con.clock?.status ?? "?"} {con.clock?.offset_hours != null ? `UTC${con.clock.offset_hours >= 0 ? "+" : ""}${con.clock.offset_hours}` : ""}</dd>
          <dt>Ostatnie błędy</dt><dd className="small">{(con.errors || []).slice(-3).map((e: any) => (typeof e === "string" ? e : JSON.stringify(e))).join(" · ") || "brak"}</dd>
          <dt>Backend WS</dt><dd>{s.ws}</dd><dt>Wersja</dt><dd>{s.app_version} · kontrakt API {s.contract}</dd></dl></div>
        <div className="card" data-testid="diag-tf"><h3>Aktualność danych per TF</h3>
          <div className="table-wrap"><table className="tbl"><thead><tr><th>TF</th><th>Rola</th><th>Dane</th><th>Zamknięte</th><th>Wymagane</th></tr></thead>
            <tbody>{(tfm?.timeframes || []).map((t: any) => <tr key={t.tf}><td>{t.tf}</td><td className="small">{t.role}</td><td><span className={cls("badge", t.data === "OK" ? "" : "warn")}>{t.data ?? "?"}</span></td>
              <td>{t.closed_bars ?? "—"}</td><td>{t.required ?? "—"}</td></tr>)}</tbody></table></div></div>
        <div className="card wide" data-testid="diag-analytics"><h3>Moduły analityczne</h3>
          {diag ? (<>
            <div className="table-wrap"><table className="tbl"><thead><tr><th>Moduł</th><th>Wersja</th><th>p50 [ms]</th><th>p95 [ms]</th><th>N</th></tr></thead>
              <tbody>{Object.entries(diag.versions).map(([m, v]: any) => { const l = diag.latency_ms[m] || diag.latency_ms[m === "ta" ? "bollinger" : m] || {}; return (
                <tr key={m}><td>{m}</td><td>{v}</td><td>{l.p50 ?? "—"}</td><td>{l.p95 ?? "—"}</td><td>{l.n ?? 0}</td></tr>); })}</tbody></table></div>
            <p className="small">Kolejka: {diag.queue} · policzone {diag.counters.computed} · odrzucone przestarzałe {diag.counters.discarded_stale} · cache {diag.counters.cache_hits}/{diag.cache_size} ·
              timeouty {diag.counters.timeouts} · zarchiwizowane {diag.counters.archived ?? 0}</p>
            {diag.errors.length > 0 && <ul className="small bad">{diag.errors.map((e: any, i: number) => <li key={i}>{fmtTime(e.at, true)} {e.where}: {e.error}</li>)}</ul>}</>) : <p className="muted">brak danych</p>}
        </div>
        <div className="card wide"><h3>Inne rynki (podgląd – nie zmienia symbolu silnika)</h3><MarketsSection /></div>
      </div>
    </div>);
}
