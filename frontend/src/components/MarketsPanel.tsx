// Multi-market scanner (backend markets/scanner.py) and the bot's signals (backend markets/signals.py: strategies S01-S10).
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, createChart, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type Time,
} from "lightweight-charts";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { parseColor, toHex, useTheme } from "../theme";
import { cls, epochSec, fmtNum, fmtTime } from "../util";
import { ZonesPrimitive } from "../zones";
import { Modal } from "./Dialogs";

const REGIME_PL: Record<string, string> = { TREND_UP: "trend ↑", TREND_DOWN: "trend ↓", RANGE: "konsolidacja", HIGH_VOLATILITY: "wysoka zmienność", MIXED: "mieszany" };
const OBS_PL: Record<string, string> = {
  TREND_PULLBACK_TO_EMA20_H4: "korekta do EMA20 H4 w trendzie", H4_CLOSE_ABOVE_DONCHIAN20: "wybicie górą (Donchian 20 H4)",
  H4_CLOSE_BELOW_DONCHIAN20: "wybicie dołem (Donchian 20 H4)", AT_OR_ABOVE_UPPER_IV_WALL_1S: "przy górnej IV wall +1σ",
  AT_OR_BELOW_LOWER_IV_WALL_1S: "przy dolnej IV wall −1σ", D1_RSI_OVERBOUGHT: "RSI D1 > 70", D1_RSI_OVERSOLD: "RSI D1 < 30",
  SPREAD_HIGH_VS_ATR_H1: "wysoki spread vs ATR H1",
};
export const STATUS_PL: Record<string, string> = { OPEN: "aktywny", WIN: "TP ✓", LOSS: "SL ✗", TIMEOUT: "zamknięty czasem", REJECTED: "odrzucony" };
const REJECT_PL: Record<string, string> = {
  NO_QUOTE: "brak kwotowania", NO_STOP_LOSS: "brak SL", NO_VALID_TARGET: "brak celu", PRICE_ALREADY_BEYOND_STOP: "cena już za SL",
  PRICE_ALREADY_BEYOND_TARGET: "cena już za celem", PRICE_RAN_AWAY_FROM_TRIGGER: "cena odjechała od poziomu wyzwalacza",
  SPREAD_TOO_LARGE_VS_RISK: "spread za duży względem ryzyka",
};
const rejectPl = (r: string) => (r.startsWith("RR_BELOW_BOT_LIMIT_") ? `R:R poniżej limitu bota (${r.slice(19)})` : REJECT_PL[r] ?? r);
const tone = (st: string) => (st === "WIN" ? "ok" : st === "LOSS" ? "bad" : st === "REJECTED" || st === "TIMEOUT" ? "warn" : st === "OPEN" ? "ok" : "muted");
const STAGE_PL: Record<string, string> = { CONFIRMED: "potwierdzony", EARLY: "wczesny", WATCH: "obserwacja" };
const dirArrow = (d?: string) => (d === "LONG" ? "↑" : d === "SHORT" ? "↓" : "");
const arrow = (t?: string | null) => (t === "UP" ? "↑" : t === "DOWN" ? "↓" : t === "MIXED" ? "↔" : "·");
const pct = (x: any, d = 2) => (x == null ? "—" : `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}%`);
const withAlpha = (c: string, a: number) => { const p = parseColor(c); return p ? toHex({ ...p, a }) : c; };

function botSetup(b: any) {
  if (!b) return <span className="muted">—</span>;
  if (b.status === "MAIN_ENGINE") return <span className="muted" title="symbol główny – setupy w panelach AUTO / Setupy">silnik główny</span>;
  if (b.status !== "OK") return <span className="muted" title={b.error || ""}>{b.status === "STALE_QUOTE" ? "brak świeżych notowań" : b.status === "DISABLED" ? "wyłączone" : b.status}</span>;
  const top = (b.setups || [])[0];
  if (!top) return <span className="muted">brak setupu</span>;
  return <span className={cls("badge", top.stage === "CONFIRMED" ? "ok" : top.stage === "EARLY" ? "warn" : "muted")}
    title={(b.setups || []).map((x: any) => `${x.strategy_id} ${x.strategy_name} ${x.direction} ${x.timeframe} ${x.stage} ${x.setup_score}`).join("\n")}>
    {top.strategy_id} {dirArrow(top.direction)} {top.timeframe} · {STAGE_PL[top.stage] ?? top.stage} {Math.round(top.setup_score)}</span>;
}

// ------------------------------------------------------------------------------------------- markets table
type SortKey = "score" | "symbol" | "change_d1_pct" | "atr_d1_pct" | "hv" | "rsi_h1" | "adx_h4" | "sigma_position";

export function MarketsPanel({ onOpen }: { onOpen: (symbol: string) => void }) {
  const { s } = useStore();
  const m = s.markets || {};
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: "score", desc: true });
  const [scanMsg, setScanMsg] = useState<string | null>(null);
  const items = useMemo(() => {
    const f = (m.items || []).filter((x: any) => !q || x.symbol.toLowerCase().includes(q.toLowerCase()) || (x.description || "").toLowerCase().includes(q.toLowerCase()));
    const v = (x: any) => (sort.k === "symbol" ? x.symbol : x[sort.k] ?? -1e9);
    return [...f].sort((a, b) => (v(a) < v(b) ? -1 : v(a) > v(b) ? 1 : 0) * (sort.desc ? -1 : 1));
  }, [m.items, q, sort]);
  const th = (k: SortKey, label: string, title?: string) => (
    <th className="sortable" title={title} onClick={() => setSort({ k, desc: sort.k === k ? !sort.desc : k !== "symbol" })}>
      {label}{sort.k === k ? (sort.desc ? " ▾" : " ▴") : ""}
    </th>
  );
  const scan = async () => {
    try { await apiSend("POST", "/api/v1/markets/scan"); setScanMsg("Skanowanie…"); } catch (e: any) { setScanMsg("Błąd: " + (e.message || e)); }
  };
  useEffect(() => { if (m.state === "OK") setScanMsg(null); }, [m.last_scan_at, m.state]);
  const lastSig = (sym: string) => (s.bot_signals?.items || []).find((x: any) => x.symbol === sym && x.status !== "REJECTED");
  return (
    <div className="panel markets-panel" data-testid="markets-panel">
      <div className="panel-head">
        <span className="ptitle">RYNKI · SKANER</span>
        <span className="psub">{m.source === "MARKET_WATCH" ? "Market Watch" : m.source === "ALL" ? "wszystkie symbole" : m.source === "LIST" ? "lista" : ""}
          {m.symbols_total != null ? ` · ${m.symbols_total} w terminalu` : ""}</span>
        <span className="spacer" />
        <input className="search" placeholder="Szukaj symbolu…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className={cls("badge", m.state === "OK" ? "ok" : m.state === "SCANNING" ? "warn" : "muted")} title={m.last_scan_at ? `ostatni skan ${fmtTime(m.last_scan_at)} (${m.duration_ms} ms)` : ""}>
          {m.state ?? "…"} · {m.count ?? 0}
        </span>
        <button className="icon" title="Skanuj teraz" onClick={scan}>↻</button>
      </div>
      {scanMsg && <div className="muted small pad">{scanMsg}</div>}
      <div className="table-wrap">
        <table className="tbl markets-tbl">
          <thead><tr>
            {th("symbol", "Symbol")}<th>Cena</th>{th("change_d1_pct", "D1 %", "zmiana od zamknięcia poprzedniego dnia")}
            <th title="kierunek EMA20/50/200 na H1 · H4 · D1">Trend H1·H4·D1</th><th>Reżim</th>
            {th("rsi_h1", "RSI H1")}{th("adx_h4", "ADX H4")}{th("atr_d1_pct", "ATR D1 %")}{th("hv", "HV %", "zmienność historyczna 20 dni, roczna")}
            {th("sigma_position", "Poz. σ", "położenie ceny względem Daily Open w odchyleniach dziennych (IV walls ±1σ)")}
            {th("score", "Ranking", "heurystyka do przeglądu – nie prawdopodobieństwo")}<th>Obserwacje</th>
            <th title="najlepszy setup strategii S01–S10 bota na tym rynku">Setup bota</th><th>Sygnał</th>
          </tr></thead>
          <tbody>
            {items.map((x: any) => {
              const sig = lastSig(x.symbol);
              return (
                <tr key={x.symbol} className="clickable" onClick={() => onOpen(x.symbol)} data-symbol={x.symbol}>
                  <td title={x.description || ""}><b>{x.symbol}</b></td>
                  <td>{x.status === "OK" ? fmtNum(x.price, x.digits) : <span className="muted">{x.status}</span>}</td>
                  <td className={cls(x.change_d1_pct > 0 ? "pos" : x.change_d1_pct < 0 ? "neg" : "")}>{pct(x.change_d1_pct)}</td>
                  <td>{arrow(x.trend?.H1)} {arrow(x.trend?.H4)} {arrow(x.trend?.D1)}</td>
                  <td>{REGIME_PL[x.regime] ?? x.regime ?? "—"}</td>
                  <td>{fmtNum(x.rsi_h1, 0)}</td><td>{fmtNum(x.adx_h4, 0)}</td><td>{fmtNum(x.atr_d1_pct, 2)}</td>
                  <td title={x.hv_pct != null ? `percentyl roczny ${x.hv_pct}` : ""}>{fmtNum(x.hv, 1)}</td>
                  <td className={cls(Math.abs(x.sigma_position ?? 0) >= 0.9 && "warn")}>{x.sigma_position == null ? "—" : `${x.sigma_position > 0 ? "+" : ""}${x.sigma_position}σ`}</td>
                  <td><div className="score-bar" title={`${x.score}`}><i style={{ width: `${x.score ?? 0}%` }} /><span>{fmtNum(x.score, 0)}</span></div></td>
                  <td className="obs">{(x.observations || []).map((o: string) => OBS_PL[o] ?? o).join(" · ")}</td>
                  <td className="bot-setup">{botSetup(x.bot)}</td>
                  <td>{sig ? <span className={cls("badge", tone(sig.status))} title={`${sig.strategy_id} ${sig.timeframe} · ${STATUS_PL[sig.status] ?? sig.status}`}>
                    {sig.action} {sig.strategy_id}</span> : ""}</td>
                </tr>
              );
            })}
            {!items.length && <tr><td colSpan={14} className="muted">{m.state === "WAITING_FOR_MT5" ? "Czekam na połączenie z MT5…" :
              m.state === "WAITING_FOR_SERVER_CLOCK" ? "Czekam na synchronizację czasu serwera MT5…" : m.state === "DISABLED" ? "Skaner wyłączony (Ustawienia → Rynki / Sygnały bota)." : "Brak wyników – trwa pierwszy skan."}</td></tr>}
          </tbody>
        </table>
      </div>
      {Object.keys(m.errors || {}).length > 0 && <div className="muted small pad">Pominięte: {Object.entries(m.errors).map(([k, v]) => `${k} (${v})`).join(", ")}</div>}
      <div className="muted small pad">Na każdym rynku działają strategie bota S01–S10 (te same progi i przełączniki). Zlecenia składa wyłącznie symbol główny
        {s.symbol?.symbol ? ` (${s.symbol.symbol})` : ""} zgodnie z trybem wykonania. Ranking to heurystyka do przeglądu.</div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------- bot signals list
export function BotSignalsPanel({ onOpen }: { onOpen: (symbol: string) => void }) {
  const { s } = useStore();
  const a = s.bot_signals || {};
  const [stats, setStats] = useState<any>(a.stats);
  const [sel, setSel] = useState<any>(null);
  const [hideRejected, setHideRejected] = useState(false);
  useEffect(() => { apiGet("/api/v1/bot-signals?limit=1").then((r) => setStats(r.stats)).catch(() => undefined); }, [s.signalSeq]);
  const st = stats || a.stats || {};
  const items = (a.items || []).filter((x: any) => !hideRejected || x.status !== "REJECTED");
  return (
    <div className="panel bot-signals-panel" data-testid="bot-signals-panel">
      <div className="panel-head">
        <span className="ptitle">SYGNAŁY BOTA · S01–S10</span>
        <span className="spacer" />
        <label className="small"><input type="checkbox" checked={hideRejected} onChange={(e) => setHideRejected(e.target.checked)} /> ukryj odrzucone</label>
        <span className={cls("badge", a.enabled === false ? "muted" : "ok")}>{a.enabled === false ? "wyłączone" : a.scan_other_markets === false ? "tylko symbol główny" : "wszystkie rynki"}</span>
      </div>
      <div className="ai-stats">
        <div><label>Win rate</label><b>{st.win_rate_pct == null ? "—" : `${st.win_rate_pct}%`}</b></div>
        <div><label>Śr. wynik</label><b>{st.avg_r == null ? "—" : `${st.avg_r > 0 ? "+" : ""}${st.avg_r} R`}</b></div>
        <div><label>Rozliczone</label><b>{st.closed ?? 0}</b><span className="muted small"> ({st.wins ?? 0}✓/{st.losses ?? 0}✗)</span></div>
        <div><label>Aktywne</label><b>{st.open ?? 0}</b></div>
        <div><label>Odrzucone</label><b>{st.rejected ?? 0}</b></div>
      </div>
      <div className="table-wrap">
        <table className="tbl ai-tbl">
          <thead><tr><th>Czas</th><th>Symbol</th><th>Strategia</th><th>TF</th><th>Akcja</th><th>Wejście</th><th>SL</th><th>TP</th><th>R:R</th><th>Wynik setupu</th><th>Status</th><th>Rezultat</th></tr></thead>
          <tbody>
            {items.map((x: any) => (
              <tr key={x.signal_id} className="clickable" onClick={() => setSel(x)} data-signal={x.signal_id}>
                <td>{fmtTime(x.created_at, true)}</td><td><b>{x.symbol}</b>{x.trigger === "MAIN" ? <span className="muted small"> główny</span> : null}</td>
                <td title={x.strategy_name}>{x.strategy_id}</td><td>{x.timeframe}</td>
                <td className={cls(x.action === "BUY" ? "pos" : "neg")}>{x.action}</td>
                <td>{x.entry_price ?? "—"}</td><td>{x.stop_loss == null ? "—" : +Number(x.stop_loss).toPrecision(8)}</td>
                <td>{(x.take_profits || []).map((t: number) => +Number(t).toPrecision(8)).join(" / ") || "—"}</td>
                <td>{x.rr1 == null ? "—" : x.rr1}</td><td>{x.setup_score == null ? "—" : Math.round(x.setup_score)}</td>
                <td><span className={cls("badge", tone(x.status))} title={(x.validation?.reasons || []).map(rejectPl).join(", ")}>{STATUS_PL[x.status] ?? x.status}</span>
                  {x.tp_hit ? <span className="muted small"> TP{x.tp_hit}</span> : null}</td>
                <td>{x.outcome_r == null ? "" : `${x.outcome_r > 0 ? "+" : ""}${x.outcome_r} R`}</td>
              </tr>
            ))}
            {!items.length && <tr><td colSpan={12} className="muted">Brak sygnałów. Sygnał powstaje, gdy strategia bota potwierdzi setup (CONFIRMED) na dowolnym skanowanym rynku.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="muted small pad">{st.note ?? ""} Wejście = cena w chwili potwierdzenia (Ask/Bid), SL i cele ze strategii, R:R ważony wagami celów.
        Odrzucone: nie spełniły reguł bota (np. R:R poniżej limitu z zakładki Ryzyko).</div>
      {sel && <SignalModal sig={sel} onClose={() => setSel(null)} onChart={() => { onOpen(sel.symbol); setSel(null); }} />}
    </div>
  );
}

function SignalModal({ sig, onClose, onChart }: { sig: any; onClose: () => void; onChart: () => void }) {
  const d = sig.detail || {};
  const ep = d.entry_plan || {};
  return (
    <Modal title={`Sygnał bota ${sig.symbol} · ${sig.action} · ${sig.strategy_id} ${sig.strategy_name ?? ""}`} onClose={onClose} wide>
      <div className="form">
        <div className="note">{fmtTime(sig.created_at, true)} · {sig.trigger === "MAIN" ? "silnik bota (symbol główny)" : "strategie bota na skanowanym rynku"} · TF {sig.timeframe}
          · reżim {d.regime ?? "—"} · wersja {d.strategy_version ?? "—"}{sig.synthetic ? " · DANE SYNTETYCZNE" : ""}</div>
        {sig.status === "REJECTED" && <div className="warn">Odrzucony: {(sig.validation?.reasons || []).map(rejectPl).join(", ")} – setup pokazany informacyjnie, nie liczy się do wyników.</div>}
        <div className="kv">
          <div><label>Wejście (cena potwierdzenia)</label><b>{sig.entry_price ?? "—"}</b></div><div><label>Stop loss</label><b>{sig.stop_loss}</b></div>
          <div><label>Cele</label><b>{(sig.take_profits || []).join(" / ")}</b></div><div><label>R:R (ważony / TP1…)</label><b>{sig.rr1 ?? "—"} / {(sig.validation?.rr || []).join(" / ")}</b></div>
          <div><label>Wynik setupu</label><b>{sig.setup_score}</b></div><div><label>Status</label><b>{STATUS_PL[sig.status] ?? sig.status}{sig.outcome_r != null ? ` (${sig.outcome_r} R)` : ""}</b></div>
          <div><label>Unieważnienie</label><b>{d.invalidation_level ?? "—"} ({d.invalidation_rule ?? ""})</b></div><div><label>Kontra trendowi</label><b>{d.countertrend ? "tak" : "nie"}</b></div>
        </div>
        {ep.trigger && <p className="prewrap">Wyzwalacz: {ep.trigger}{ep.trigger_level != null ? ` (poziom ${ep.trigger_level})` : ""}</p>}
        {(d.reason_codes || []).length > 0 && <div className="small">Powody: {d.reason_codes.join(" · ")}</div>}
        {(d.missing_confirmations || []).length > 0 && <div className="small muted">Brakujące potwierdzenia: {d.missing_confirmations.join(" · ")}</div>}
        {d.score?.points && <div className="small muted">Punkty: {Object.entries(d.score.points).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>}
        <div className="note">Strategie mają status {d.validation_status ?? "—"} (bez testu OOS). Wynik sygnału liczony na świecach M15 (Bid) bez spreadu i prowizji.</div>
        <div className="row"><button className="btn" onClick={onChart}>Pokaż wykres {sig.symbol}</button></div>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------------------------------- market detail with chart
export function MarketDetail({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const { s } = useStore();
  const theme = useTheme();
  const tk = theme.chartTokens("market");
  const [tf, setTf] = useState("H1");
  const [data, setData] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const ser = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const zones = useRef<ZonesPrimitive | null>(null);
  const lines = useRef<IPriceLine[]>([]);
  useEffect(() => {
    let alive = true;
    apiGet(`/api/v1/markets/chart?symbol=${encodeURIComponent(symbol)}&tf=${tf}&bars=300`).then((d) => alive && (setData(d), setErr(null)))
      .catch((e) => alive && setErr(String(e.message || e)));
    return () => { alive = false; };
  }, [symbol, tf, s.signalSeq]);
  useEffect(() => { apiGet(`/api/v1/markets/detail?symbol=${encodeURIComponent(symbol)}`).then(setDetail).catch(() => undefined); }, [symbol]);
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, { autoSize: true, layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 10 },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 6 } });
    chart.current = c;
    ser.current = c.addSeries(CandlestickSeries, {});
    zones.current = new ZonesPrimitive();
    ser.current.attachPrimitive(zones.current);
    (window as any).__mqMarketChart = { bars: () => (ser.current?.data() || []).length, lines: () => lines.current.map((p) => p.options().title) };
    return () => { c.remove(); chart.current = null; ser.current = null; lines.current = []; };
  }, []);
  useEffect(() => {
    const c = chart.current, sr = ser.current;
    if (!c || !sr || !data) return;
    const d = data.meta?.digits ?? 5;
    c.applyOptions({ layout: { textColor: String(tk.chartLabels) }, grid: { vertLines: { color: String(tk.chartGrid) }, horzLines: { color: String(tk.chartGrid) } } });
    sr.applyOptions({ upColor: String(tk.upBody), downColor: String(tk.downBody), wickUpColor: String(tk.upWick), wickDownColor: String(tk.downWick),
      borderUpColor: String(tk.upBorder), borderDownColor: String(tk.downBorder), priceFormat: { type: "price", precision: d, minMove: 10 ** -d } });
    sr.setData(data.bars.filter((b: any) => b.open_utc).map((b: any) => ({ time: epochSec(b.open_utc) as Time, open: b.o, high: b.h, low: b.l, close: b.c })));
    lines.current.forEach((p) => sr.removePriceLine(p));
    lines.current = [];
    const add = (price: number, color: string, title: string, style = LineStyle.Dashed, w: 1 | 2 = 1) =>
      price != null && lines.current.push(sr.createPriceLine({ price, color, title, lineStyle: style, lineWidth: w, axisLabelVisible: true }));
    const v = data.volatility;
    if (v?.status === "OK") {
      zones.current?.setZones((v.zones || []).map((z: any) => {
        const col = String(z.side === "UP" ? tk.ivWallUp : tk.ivWallDown);
        return { from: z.from_utc ? epochSec(z.from_utc) : 0, low: z.low, high: z.high, color: col, border: withAlpha(col, 0.7), label: z.label };
      }));
      add(v.day?.open, String(tk.dailyOpen), "Daily Open", LineStyle.Solid);
      add(v.expected_high, String(tk.expectedHL), "Daily High (IV 1σ)", LineStyle.Dashed, 2);
      add(v.expected_low, String(tk.expectedHL), "Daily Low (IV 1σ)", LineStyle.Dashed, 2);
    } else zones.current?.setZones([]);
    for (const sg of data.bot_signals || []) {
      add(sg.entry_price, String(tk.entry), `${sg.strategy_id} ${sg.action}`, LineStyle.Dotted);
      add(sg.stop_loss, String(tk.sl), `${sg.strategy_id} SL`);
      (sg.take_profits || []).forEach((t: number, i: number) => add(t, String(tk.tp), `${sg.strategy_id} TP${i + 1}`));
    }
    c.timeScale().fitContent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, JSON.stringify(tk)]);
  const a = detail || {};
  const sigs = (s.bot_signals?.items || []).filter((x: any) => x.symbol === symbol).slice(0, 8);
  const scanned = (s.markets?.items || []).find((x: any) => x.symbol === symbol);
  return (
    <Modal title={`${symbol}${a.description ? " · " + a.description : ""}`} onClose={onClose} wide>
      <div className="market-detail" data-testid="market-detail">
        <div className="row">
          <div className="tabs small">{["M15", "H1", "H4", "D1"].map((t) => <button key={t} className={cls(tf === t && "on")} onClick={() => setTf(t)}>{t}</button>)}</div>
          <span className="spacer" />
          {data?.synthetic && <span className="badge warn">DANE SYNTETYCZNE</span>}
        </div>
        {err && <div className="warn">Błąd: {err}</div>}
        <div className="market-chart" ref={box} />
        {a.status === "OK" && <div className="kv market-kv">
          <div><label>Cena</label><b>{fmtNum(a.price, a.digits)}</b></div><div><label>Zmiana D1 / 5D</label><b>{pct(a.change_d1_pct)} / {pct(a.change_5d_pct)}</b></div>
          <div><label>Reżim / kierunek</label><b>{REGIME_PL[a.regime] ?? a.regime} · {a.bias}</b></div>
          <div><label>Trend H1·H4·D1</label><b>{["H1", "H4", "D1"].map((t) => arrow(a.timeframes?.[t]?.trend)).join(" ")}</b></div>
          <div><label>RSI H1 / H4 / D1</label><b>{["H1", "H4", "D1"].map((t) => fmtNum(a.timeframes?.[t]?.rsi14, 0)).join(" / ")}</b></div>
          <div><label>ADX H4 / D1</label><b>{fmtNum(a.timeframes?.H4?.adx14, 0)} / {fmtNum(a.timeframes?.D1?.adx14, 0)}</b></div>
          <div><label>ATR H1 / D1</label><b>{fmtNum(a.atr_h1, a.digits)} / {fmtNum(a.atr_d1, a.digits)}</b></div>
          <div><label>Spread / ATR H1</label><b>{a.spread_atr_h1_pct == null ? "—" : `${a.spread_atr_h1_pct}%`}</b></div>
          <div><label>HV / percentyl</label><b>{fmtNum(a.volatility?.hv_annual_pct, 1)}% / {a.volatility?.hv_percentile_1y ?? "—"}</b></div>
          <div><label>Daily High/Low (IV 1σ)</label><b>{fmtNum(a.volatility?.expected_high, a.digits)} / {fmtNum(a.volatility?.expected_low, a.digits)}</b></div>
          <div><label>Ranking</label><b>{fmtNum(a.score, 0)}</b></div>
          <div><label>Obserwacje</label><b className="small">{(a.observations || []).map((o: string) => OBS_PL[o] ?? o).join(" · ") || "—"}</b></div>
        </div>}
        {a.status && a.status !== "OK" && <div className="warn">Analiza: {a.status}</div>}
        {scanned?.bot?.setups?.length > 0 && <table className="tbl" data-testid="bot-setups"><thead><tr><th>Strategia</th><th>Kierunek</th><th>TF</th><th>Etap</th><th>Wynik</th></tr></thead>
          <tbody>{scanned.bot.setups.map((x: any) => <tr key={x.setup_id}><td>{x.strategy_id} {x.strategy_name}</td><td>{x.direction}</td><td>{x.timeframe}</td>
            <td>{STAGE_PL[x.stage] ?? x.stage}</td><td>{Math.round(x.setup_score)}</td></tr>)}</tbody></table>}
        {scanned?.bot?.status === "MAIN_ENGINE" && <div className="muted small">Symbol główny – setupy bota są w panelach AUTO / Setupy na żywo.</div>}
        {sigs.length > 0 && <table className="tbl"><thead><tr><th>Czas</th><th>Strategia</th><th>Akcja</th><th>Wejście</th><th>SL</th><th>TP</th><th>Status</th><th>Wynik</th></tr></thead>
          <tbody>{sigs.map((x: any) => <tr key={x.signal_id}><td>{fmtTime(x.created_at, true)}</td><td>{x.strategy_id} {x.timeframe}</td><td>{x.action ?? "—"}</td><td>{x.entry_price ?? "—"}</td>
            <td>{x.stop_loss ?? "—"}</td><td>{(x.take_profits || []).join(" / ")}</td><td>{STATUS_PL[x.status] ?? x.status}</td>
            <td>{x.outcome_r == null ? "" : `${x.outcome_r} R`}</td></tr>)}</tbody></table>}
      </div>
    </Modal>
  );
}
