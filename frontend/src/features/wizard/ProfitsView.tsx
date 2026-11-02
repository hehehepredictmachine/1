// Profits – account and results from the backend only: MT5 account (balance, equity, open P/L), /api/v1/stats (closed trades of
// the bot per mode, per engine / strategy / instrument / month, equity snapshots, MT5 deal totals, ROI by modified Dietz). Deposits
// and withdrawals are external flows, never profit; MT5 deals are not trades (a partially closed position is still open); drawdown is
// shown only where the data allows it and with its method. Missing data = "brak danych", never a made-up number.
import { useMemo, useState } from "react";
import { useStore } from "../../store";
import { cls, fmtNum, fmtTime } from "../../util";
import { usePoll } from "./PrecisionView";
import ViewHeader from "./ViewHeader";

type StatsMode = "PAPER" | "AUTO_DEMO" | "AUTO_LIVE";
type Period = "all" | "month" | "week" | "day";
const PERIOD_PL: Record<Period, string> = { all: "całość", month: "ten miesiąc", week: "ten tydzień", day: "dziś (UTC)" };

const money = (v: any, cur?: string | null) => (v == null || Number.isNaN(v) ? "brak danych" : `${fmtNum(v, 2)} ${cur ?? ""}`.trim());
const tone = (v: any) => (v == null ? "" : v > 0 ? "wz-pos" : v < 0 ? "wz-neg" : "");

function equityDrawdown(points: any[]): { dd: number; ddPct: number | null } | null {
  if (!points || points.length < 2) return null;
  let peak = -Infinity, dd = 0, ddPct = 0;
  for (const p of points) {
    const e = Number(p.equity);
    if (!Number.isFinite(e)) continue;
    peak = Math.max(peak, e);
    dd = Math.max(dd, peak - e);
    if (peak > 0) ddPct = Math.max(ddPct, (peak - e) / peak);
  }
  return { dd, ddPct: peak > 0 ? ddPct * 100 : null };
}

function EquityCurve({ points, cur }: { points: any[]; cur?: string | null }) {
  const W = 760, H = 190, P = 28;
  const pts = (points || []).filter((p) => Number.isFinite(Number(p.equity)));
  if (pts.length < 2) return <p className="wz-dim" data-testid="wz-equity-empty">Brak danych krzywej kapitału – equity jest zapisywane co 60 s podczas pracy programu.</p>;
  const t = pts.map((p) => Date.parse(p.ts)), eq = pts.map((p) => Number(p.equity)), bal = pts.map((p) => Number(p.balance));
  const lo = Math.min(...eq, ...bal.filter(Number.isFinite)), hi = Math.max(...eq, ...bal.filter(Number.isFinite));
  const x = (v: number) => P + ((v - t[0]) / Math.max(1, t[t.length - 1] - t[0])) * (W - 2 * P);
  const y = (v: number) => H - P - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - 2 * P);
  const line = (arr: number[]) => arr.map((v, i) => `${i ? "L" : "M"}${x(t[i]).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="wz-equity" role="img" aria-label={`Krzywa kapitału: od ${fmtNum(eq[0], 2)} do ${fmtNum(eq[eq.length - 1], 2)} ${cur ?? ""}`}
      data-testid="wz-equity">
      <defs><linearGradient id="wzEq" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#ffcf5c" stopOpacity="0.35" /><stop offset="1" stopColor="#ffcf5c" stopOpacity="0" /></linearGradient></defs>
      <path d={`${line(eq)} L${x(t[t.length - 1])},${H - P} L${x(t[0])},${H - P} Z`} fill="url(#wzEq)" />
      {bal.every(Number.isFinite) && <path d={line(bal)} fill="none" stroke="#2fe6a0" strokeWidth="1.2" strokeDasharray="4 3" />}
      <path d={line(eq)} fill="none" stroke="#ffcf5c" strokeWidth="2" />
      <text x={P} y={14} className="wz-svg-label">{fmtNum(hi, 2)}</text>
      <text x={P} y={H - 8} className="wz-svg-label">{fmtNum(lo, 2)}</text>
      <text x={W - P} y={H - 8} textAnchor="end" className="wz-svg-label">{fmtTime(pts[pts.length - 1].ts, true)}</text>
    </svg>);
}

function AggTable({ rows, cur, testid }: { rows: [string, any][]; cur?: string | null; testid: string }) {
  if (!rows.length) return <p className="wz-dim">Brak zamkniętych transakcji w tym zakresie.</p>;
  return (
    <table className="wz-table" data-testid={testid}>
      <thead><tr><th>Pozycja</th><th>Transakcje</th><th>Wynik netto</th><th>Win rate</th><th>W / L / BE</th><th>Oczekiwanie R</th><th>Maks. obsunięcie</th></tr></thead>
      <tbody>{rows.map(([k, a]) => (
        <tr key={k}><td>{k}</td><td>{a.trades}</td><td className={tone(a.net)}>{money(a.net, cur)}</td><td>{a.win_rate != null ? `${fmtNum(a.win_rate, 1)} %` : "—"}</td>
          <td>{a.trades ? `${a.wins ?? 0} / ${a.losses ?? 0} / ${a.breakeven ?? 0}` : "—"}</td><td>{a.expectancy_r != null ? fmtNum(a.expectancy_r, 3) : "—"}</td>
          <td>{a.max_drawdown != null ? money(a.max_drawdown, cur) : "—"}</td></tr>))}</tbody>
    </table>);
}

export default function ProfitsView() {
  const { s } = useStore();
  const cur = s.mode?.mode;
  const [mode, setMode] = useState<StatsMode>(cur === "AUTO_DEMO" || cur === "AUTO_LIVE" ? cur : "PAPER");
  const [period, setPeriod] = useState<Period>("all");
  const st = usePoll<any>(`/api/v1/stats?mode=${mode}`, 20000);
  const d = st.d;
  const acc = s.account || {};
  const ccy = d?.bot?.currency ?? acc.currency ?? null;
  const agg = d?.bot?.[period];
  const roi = d?.account_roi;
  const ac = d?.account;
  const eqDd = useMemo(() => equityDrawdown(d?.equity?.points || []), [d?.equity?.points]);
  const openPl = (s.positions?.positions || []).reduce((a: number, p: any) => a + Number(p.profit || 0), 0);
  return (
    <div className="wz-view wz-profits" data-testid="page-profits">
      <ViewHeader tower="profits">
        <div className="wz-filters" role="group" aria-label="Tryb wyników">
          {(["PAPER", "AUTO_DEMO", "AUTO_LIVE"] as StatsMode[]).map((m) => (
            <button key={m} className={cls("wz-mini", mode === m && "on")} aria-pressed={mode === m} onClick={() => setMode(m)} data-testid={`wz-stats-${m}`}>{m.replace("_", " ")}</button>))}
        </div>
      </ViewHeader>
      {st.err && <p className="wz-panel wz-bad" role="alert">Statystyki niedostępne: {st.err}</p>}
      <section className="wz-cards" aria-label="Rachunek i wyniki" data-testid="wz-profit-cards">
        <div className="wz-card"><span>Saldo (MT5)</span><b data-testid="wz-balance">{money(acc.balance, acc.currency)}</b><small>rachunek {acc.trade_mode ?? "—"} · {acc.login ? `#${acc.login}` : "brak rachunku"}</small></div>
        <div className="wz-card"><span>Equity (MT5)</span><b>{money(acc.equity, acc.currency)}</b><small>saldo + wynik otwartych pozycji</small></div>
        <div className="wz-card"><span>Wynik otwartych pozycji</span><b className={tone(acc.profit)}>{money(acc.profit ?? (s.positions ? openPl : null), acc.currency)}</b>
          <small>{(s.positions?.positions || []).length} otwartych pozycji (terminal)</small></div>
        <div className="wz-card"><span>Zrealizowany wynik netto bota</span><b className={tone(agg?.net)} data-testid="wz-net">{agg ? money(agg.net, ccy) : "brak danych"}</b>
          <small>{mode} · {PERIOD_PL[period]} · {agg?.trades ?? 0} zamkniętych transakcji</small></div>
        <div className="wz-card" data-testid="wz-roi"><span>ROI rachunku</span><b className={tone(roi?.roi_pct)}>{roi?.status === "OK" ? `${fmtNum(roi.roi_pct, 2)} %` : "brak danych"}</b>
          <small>{roi?.status === "OK" ? `${fmtTime(roi.period_from, true)} – ${fmtTime(roi.period_to, true)} · ${roi.method}`
            : `${roi?.note ?? (roi?.status === "NO_ACCOUNT" ? "brak rachunku MT5" : "—")} · metoda: zmodyfikowany Dietz (wpłaty i wypłaty to przepływy, nie wynik)`}</small></div>
        <div className="wz-card"><span>Win rate</span><b data-testid="wz-winrate">{agg?.win_rate != null ? `${fmtNum(agg.win_rate, 1)} %` : "brak danych"}</b>
          <small>wygrane {agg?.wins ?? 0} · przegrane {agg?.losses ?? 0} · breakeven {agg?.breakeven ?? 0} (BE poza mianownikiem)</small></div>
        <div className="wz-card"><span>Prowizje / swapy</span><b>{agg ? `${money(agg.commission, ccy)} / ${money(agg.swap, ccy)}` : "brak danych"}</b>
          <small>{d?.bot?.commission_unknown_trades ? `${d.bot.commission_unknown_trades} transakcji bez znanej prowizji` : "z rozliczeń transakcji"}</small></div>
        <div className="wz-card" data-testid="wz-flows"><span>Wpłaty / wypłaty</span><b>{ac ? `${money(ac.deposits, acc.currency)} / ${money(ac.withdrawals, acc.currency)}` : "brak danych"}</b>
          <small>{ac ? `${ac.balance_operations_count} operacji · nie są zyskiem` : "brak historii rachunku"}</small></div>
        <div className="wz-card"><span>Obsunięcie</span><b>{agg?.max_drawdown != null ? money(agg.max_drawdown, ccy) : "brak danych"}</b>
          <small>z krzywej zrealizowanych wyników{eqDd ? ` · equity (snapshoty 60 s): ${money(eqDd.dd, acc.currency)}${eqDd.ddPct != null ? ` (${fmtNum(eqDd.ddPct, 2)} %)` : ""}` : " · equity: brak snapshotów"}</small></div>
        <div className="wz-card"><span>Deale MT5 a transakcje</span><b>{ac ? `${ac.deals} deali` : "—"} · {d?.bot?.all?.trades ?? 0} transakcji</b>
          <small>częściowo zamknięte (otwarte): {d?.bot?.open_partial_positions ?? 0} · nierozliczone: {d?.bot?.unsettled_positions ?? 0}</small></div>
      </section>
      <div className="wz-filters" role="group" aria-label="Okres wyników">
        {(Object.keys(PERIOD_PL) as Period[]).map((p) => (
          <button key={p} className={cls("wz-mini", period === p && "on")} aria-pressed={period === p} onClick={() => setPeriod(p)}>{PERIOD_PL[p]}</button>))}
        <span className="wz-dim">{d?.bot?.note ?? ""}</span>
      </div>
      <div className="wz-view-grid wz-profits-grid">
        <section className="wz-panel" aria-label="Krzywa kapitału">
          <h2>Krzywa kapitału <span className="wz-dim">{d?.equity?.label ?? ""}</span></h2>
          <EquityCurve points={d?.equity?.points || []} cur={acc.currency} />
          <p className="wz-note">Złota linia: equity · zielona przerywana: saldo. ROI liczony metodą zmodyfikowaną Dietza (wpłaty i wypłaty jako przepływy zewnętrzne). {roi?.scope ?? ""}</p>
        </section>
        <section className="wz-panel" aria-label="Historia transakcji">
          <h2>Historia transakcji bota <span className="wz-dim">(ostatnie 20, {mode})</span></h2>
          {!(d?.bot?.recent || []).length ? <p className="wz-dim" data-testid="wz-history-empty">Brak zamkniętych transakcji bota w tym trybie.</p> : (
            <div className="wz-table-wrap">
              <table className="wz-table" data-testid="wz-history">
                <thead><tr><th>Zamknięcie</th><th>Symbol</th><th>Strona</th><th>Wolumen</th><th>Wejście → wyjście</th><th>Netto</th><th>Prowizja</th><th>Swap</th><th>R</th><th>Strategia</th></tr></thead>
                <tbody>{d.bot.recent.map((r: any) => (
                  <tr key={r.trade_id}><td>{fmtTime(r.closed_at, true)}</td><td>{r.symbol}</td><td>{r.side}</td><td>{fmtNum(r.volume, 2)}</td>
                    <td>{fmtNum(r.entry_price, 2)} → {fmtNum(r.exit_price_avg, 2)}</td><td className={tone(r.net_pnl)}>{money(r.net_pnl, r.currency)}</td>
                    <td>{fmtNum(r.commission, 2)}</td><td>{fmtNum(r.swap, 2)}</td><td>{r.r_multiple != null ? fmtNum(r.r_multiple, 2) : "—"}</td><td>{r.strategy_id ?? "—"}</td></tr>))}</tbody>
              </table>
            </div>)}
        </section>
      </div>
      <div className="wz-view-grid wz-profits-grid">
        <section className="wz-panel"><h2>Ścieżki wykonania</h2>
          <AggTable rows={Object.entries(d?.engines?.per_engine || {})} cur={ccy} testid="wz-per-engine" /></section>
        <section className="wz-panel"><h2>Strategie</h2>
          <AggTable rows={Object.entries(d?.engines?.per_strategy || {})} cur={ccy} testid="wz-per-strategy" /></section>
        <section className="wz-panel"><h2>Instrumenty</h2>
          <AggTable rows={Object.entries(d?.engines?.per_symbol || {})} cur={ccy} testid="wz-per-symbol" /></section>
        <section className="wz-panel"><h2>Miesiące</h2>
          <AggTable rows={Object.entries(d?.engines?.per_month || {})} cur={ccy} testid="wz-per-month" /></section>
      </div>
      <p className="wz-note">Wyniki z rozliczonych transakcji – mała próba nie pozwala wnioskować o skuteczności. Wynik całego rachunku MT5 (wszystkie symbole, także ręczne):
        {" "}{ac ? money(ac.trading_net_all_symbols, acc.currency) : "brak danych"}.</p>
    </div>);
}
