// 04 ROI (E6, S3 §5) – wszystkie wartości z jednego GET /api/v1/stats?mode=PAPER|AUTO_DEMO|AUTO_LIVE (stats.py).
// Oko wiru: account_roi.roi_pct (ROI CAŁEGO rachunku z 30 dni – nie ROI bota); PAPER: bot.all.net; status != OK -> BRAK DANYCH + note.
// Księżyce = engines.per_engine (rozmiar = trades, kolor = znak net). Znaczników wpłat brak: API podaje tylko sumy (raport E0).
import { useEffect, useState } from "react";
import { useStore } from "../../../store";
import { fmt, fmtTime, pnc, sgn, usePoll } from "../data";
import type { ScreenProps } from "../ForexScene";

const PER: [string, string][] = [["day", "DZIŚ"], ["week", "TYDZIEŃ"], ["month", "MIESIĄC"], ["all", "CAŁOŚĆ"]];
const ENG_PL: Record<string, string> = { ACTIVE_S01_S12: "ŚCIEŻKA A · S01–S12", SH_SCALPING: "SH · SCALPING", SH_HEDGING: "SH · HEDGING" };
const MON = ["STY", "LUT", "MAR", "KWI", "MAJ", "CZE", "LIP", "SIE", "WRZ", "PAŹ", "LIS", "GRU"];
const chip = (st?: string) => st === "OK" || !st ? null : st === "SMALL_SAMPLE" ? <span className="ro-chip warn">MAŁA PRÓBA · &lt;30</span> : <span className="ro-chip">BRAK DANYCH</span>;

export default function RoiScreen({ engine }: ScreenProps) {
  const { s } = useStore();
  const [mode, setMode] = useState<string>(() => (["PAPER", "AUTO_DEMO", "AUTO_LIVE"].includes(s.mode?.mode) ? s.mode.mode : "PAPER"));
  const [per, setPer] = useState("all");
  const [tab, setTab] = useState("engine");
  const st = usePoll<any>(`/api/v1/stats?mode=${mode}`, 30000);
  const d = st.data;
  const bot = d?.bot, a = bot?.[per] || {}, none = !bot || !(bot.all?.trades > 0);
  const roi = d?.account_roi, eng = d?.engines?.per_engine || {};
  useEffect(() => { engine?.setScreenData(3, { moons: Object.entries(eng).map(([k, v]: any) => ({ id: k, name: ENG_PL[k] ?? k, trades: v.trades || 0, net: v.net || 0 })) }); }); // eslint-disable-line react-hooks/exhaustive-deps
  const src: [string, any][] = tab === "engine" ? Object.entries(eng).map(([k, v]) => [ENG_PL[k] ?? k, v]) : Object.entries((d?.engines || {})[{ strat: "per_strategy", sym: "per_symbol", month: "per_month" }[tab] as string] || {});
  const mx = Math.max(1, ...src.map(([, v]) => Math.abs(v?.net || 0)));
  const months = Object.entries(d?.engines?.per_month || {}) as [string, any][];
  const mmx = Math.max(1, ...months.map(([, v]) => Math.abs(v.net || 0)));
  const showRoi = mode !== "PAPER";
  return (
    <section id="roi-screen" aria-label="ROI" data-testid="forex-roi">
      <div id="ro-head" className="ci">
        <div id="ro-title" aria-hidden="true"><span className="n">04</span>ROI</div><span className="ch-sep" />
        <div id="ro-mode" className="segb" role="group" aria-label="Tryb">{["PAPER", "AUTO_DEMO", "AUTO_LIVE"].map((m) =>
          <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)} data-testid={"roi-mode-" + m} {...(mode === m ? { "data-autofocus": "" } : {})}>{m}</button>)}</div>
        <div className="gates-sum"><span id="ro-gs"><span>{mode === "PAPER" ? "KAPITAŁ" : "KONTO MT5"}<b>{mode === "PAPER" ? "PAPER (SYMULACJA)" : d?.account ? "POŁĄCZONE" : "BRAK KONTA"}</b></span>
          <span>SNAPSHOTY EQUITY<b>{d?.equity?.label ?? "—"}</b></span><span>WALUTA<b>{bot?.currency ?? "—"}</b></span></span></div>
      </div>
      <div className="sg-wrap ro-wrap">
        <div id="ro-left" className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          <div id="ro-per" className="segb" role="group" aria-label="Okres">{PER.map(([k, l]) => <button key={k} type="button" aria-pressed={per === k} onClick={() => setPer(k)}>{l}</button>)}</div>
          <div id="ro-stats" data-testid="roi-stats">
            {st.err && <p className="empty">BŁĄD: {st.err}</p>}
            <div className="ro-big"><span>ZREALIZOWANY WYNIK NETTO BOTA · {PER.find((p) => p[0] === per)?.[1]} · {mode}</span>
              <b className={none ? "na" : pnc(a.net)}>{none ? "—" : sgn(a.net)}</b><em>{bot?.currency ?? ""} · {a.trades ?? 0} transakcji {chip(none ? "NO_DATA" : a.status)}</em></div>
            {none ? <div className="why">Brak rozliczonych transakcji bota w trybie {mode}. Statystyki pojawią się po pierwszych zamkniętych pozycjach – bez wartości zastępczych.</div>
              : a.trades ? <><div className="ro-wl"><i className="w" style={{ flex: a.wins || 0 }} /><i className="b" style={{ flex: a.breakeven || 0 }} /><i className="l" style={{ flex: a.losses || 0 }} /></div>
                <div className="ro-wll"><span>W {a.wins ?? "—"}</span><span>BE {a.breakeven ?? "—"}</span><span>L {a.losses ?? "—"}</span></div>
                <div className="lv2"><span>WIN RATE (BEZ BE)</span><b>{fmt(a.win_rate, 1)}%</b><span>WSZYSTKIE ZAMKNIĘTE</span><b>{fmt(a.win_rate_all_closed, 1)}%</b>
                  <span>PROFIT FACTOR</span><b>{a.profit_factor == null ? (a.profit_factor_note === "BRAK_STRAT" ? "brak strat" : "—") : fmt(a.profit_factor)}</b>
                  <span>E[R] ± SE</span><b className={pnc(a.expectancy_r)}>{sgn(a.expectancy_r)} <small>± {fmt(a.expectancy_r_se)}</small></b>
                  <span>MAX DD</span><b>{fmt(a.max_drawdown)}</b><span>MAX DD R</span><b>{fmt(a.max_drawdown_r)} R</b>
                  <span>ŚR. ZYSK</span><b className="pos">{sgn(a.avg_win)}</b><span>ŚR. STRATA</span><b className="neg">{sgn(a.avg_loss)}</b>
                  <span>PROWIZJE</span><b>{sgn(a.commission)}</b><span>SWAPY</span><b>{sgn(a.swap)}</b></div></> : <div className="why">Brak zamkniętych transakcji w tym okresie.</div>}
            <div className="sec"><span>{mode === "PAPER" ? "KAPITAŁ PAPER" : "RACHUNEK MT5 · " + mode}</span><span>OSTATNI SNAPSHOT</span></div>
            {(() => { const p = d?.equity?.points?.[d.equity.points.length - 1]; const ac = d?.account; return (
              <div className="lv2"><span>SALDO</span><b>{fmt(p?.balance)}</b><span>EQUITY</span><b>{fmt(p?.equity)}</b>
                {mode !== "PAPER" && ac ? <><span>WPŁATY / WYPŁATY</span><b>{sgn(ac.deposits)} / {fmt(ac.withdrawals)}</b><span>WYNIK CAŁEGO RACHUNKU</span><b className={pnc(ac.trading_net_all_symbols)}>{sgn(ac.trading_net_all_symbols)}</b></>
                  : <><span>ROI RACHUNKU</span><b>{mode === "PAPER" ? "nie dotyczy" : "brak konta"}</b></>}</div>); })()}
            <div className="note">{[roi?.scope, roi?.sampling_note, roi?.note, d?.account?.note, bot?.note].filter(Boolean).join(" · ")}</div>
          </div>
        </div>
        <div id="ro-center" className="ci">
          <div id="ro-hero" aria-label="Wir ROI: księżyce = ścieżki wykonania, rozmiar = liczba transakcji" onClick={(e) => { const id = engine?.nodeAt(3, e.clientX, e.clientY); if (id) setTab("engine"); }}>
            <div id="ro-eye" aria-live="polite" data-testid="roi-eye">
              {showRoi ? (roi?.status === "OK" ? <><span>ROI RACHUNKU · 30 DNI</span><b className={pnc(roi.roi_pct)}>{sgn(roi.roi_pct)}%</b><small>cały rachunek – nie ROI samego bota · {roi.method ?? ""}</small>
                <em>bot: {sgn(bot?.all?.net)} {bot?.currency ?? ""} netto · {bot?.all?.trades ?? 0} transakcji</em></>
                : <><span>ROI RACHUNKU · 30 DNI</span><b className="na">BRAK DANYCH</b><small>{roi?.note ?? "za mało snapshotów equity"}</small></>)
                : <><span>WYNIK NETTO BOTA · PAPER</span><b className={none ? "na" : pnc(bot?.all?.net)}>{none ? "BRAK DANYCH" : sgn(bot?.all?.net)}</b><small>{bot?.currency ?? ""} · {bot?.all?.trades ?? 0} transakcji · tryb PAPER</small></>}
            </div></div>
          <div id="ro-eqp" className="cs-win"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
            <div id="ro-eqh"><span>KRZYWA KAPITAŁU · {d?.equity?.label ?? ""}</span><span className="leg"><span><i style={{ background: "#f2f4ff" }} />EQUITY</span><span><i className="dsh" />SALDO</span></span></div>
            <div id="ro-eqa"><Equity pts={d?.equity?.points || []} status={d?.equity?.status} /></div></div>
          <div id="ro-months">{months.length ? months.map(([k, v], i) => (
            <div key={k} className="mo" style={{ ["--i" as any]: i }}><div className="col"><i className={v.net >= 0 ? "p" : "n"} style={{ ["--h" as any]: `${Math.abs(v.net) / mmx * 100}%` }} /></div>
              <b className={pnc(v.net)}>{sgn(v.net, 0)}</b><span>{MON[+k.slice(5) - 1]} {k.slice(2, 4)}</span><small>{v.trades} tr.</small></div>)) : <div className="empty">Brak zamkniętych transakcji – brak wyników miesięcznych.</div>}</div>
        </div>
        <div id="ro-right" className="cs-win ci"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
          <div id="ro-tabs" className="segb" role="group" aria-label="Rozbicie">{[["engine", "ŚCIEŻKI"], ["strat", "STRATEGIE"], ["sym", "INSTRUMENTY"], ["month", "MIESIĄCE"]].map(([k, l]) =>
            <button key={k} type="button" aria-pressed={tab === k} onClick={() => setTab(k)}>{l}</button>)}</div>
          <div id="ro-scroll"><div id="ro-table">{src.length ? <table className="jobs ro-tb"><thead><tr><th>{{ engine: "ŚCIEŻKA", strat: "STRATEGIA", sym: "INSTRUMENT", month: "MIESIĄC" }[tab]}</th><th>TR.</th><th>NETTO</th><th>WIN %</th><th>E[R]</th></tr></thead>
            <tbody>{src.map(([n, v], i) => <tr key={n} style={{ ["--i" as any]: i }}><td>{n}{v?.status === "SMALL_SAMPLE" && <small className="w">mała próba</small>}</td><td>{v?.trades ?? 0}</td>
              <td className={pnc(v?.net)}><span className="nb"><i className={(v?.net || 0) >= 0 ? "p" : "n"} style={{ ["--w" as any]: `${Math.abs(v?.net || 0) / mx * 100}%` }} /></span>{sgn(v?.net)}</td>
              <td>{fmt(v?.win_rate, 1)}</td><td className={pnc(v?.expectancy_r)}>{sgn(v?.expectancy_r)}</td></tr>)}</tbody></table> : <div className="empty">BRAK DANYCH</div>}
            <div className="note">Win % bez BE w mianowniku. Plany SH liczone jako jeden wynik za cały cykl. Tylko raport.</div></div>
            <div className="sec"><span>HISTORIA TRANSAKCJI BOTA</span><span>OSTATNIE 20</span></div>
            <div id="ro-trades">{(bot?.recent || []).length ? <table className="jobs ro-tr"><thead><tr><th>ZAMKNIĘCIE</th><th>SYMBOL</th><th>STRONA</th><th>NETTO</th><th>R</th><th>STRATEGIA</th></tr></thead>
              <tbody>{bot.recent.slice(0, 20).map((x: any, i: number) => <tr key={i} style={{ ["--i" as any]: i }}><td>{fmtTime(x.closed_at ?? x.close_time, true)}</td><td>{x.symbol}</td>
                <td className={"sd " + (String(x.side).startsWith("B") ? "b" : "s")}>{x.side}</td><td className={pnc(x.net_pnl ?? x.net)}>{sgn(x.net_pnl ?? x.net)}</td>
                <td className={pnc(x.r_multiple)}>{sgn(x.r_multiple)}</td><td>{x.strategy_id ?? x.strategy ?? ""}</td></tr>)}</tbody></table>
              : <div className="empty">Brak historii transakcji bota w tym trybie.</div>}</div></div>
        </div>
      </div>
    </section>);
}

function Equity({ pts, status }: { pts: any[]; status?: string }) {
  if (!pts.length) return <p className="empty">BRAK DANYCH{status ? " · " + status : ""}</p>;
  const W = 640, H = 150, xs = pts.map((p) => Date.parse(p.ts) || 0), ys = pts.flatMap((p) => [p.equity, p.balance]).filter((v) => v != null);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), mn = Math.min(...ys), mx = Math.max(...ys);
  const X = (t: number) => 4 + (t - x0) / (x1 - x0 || 1) * (W - 8), Y = (v: number) => H - 6 - (v - mn) / (mx - mn || 1) * (H - 12);
  return <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
    <polyline fill="none" stroke="#9aa0aa" strokeDasharray="3 3" points={pts.map((p, i) => `${X(xs[i])},${Y(p.balance)}`).join(" ")} />
    <polyline fill="none" stroke="#f2f4ff" strokeWidth="1.3" points={pts.map((p, i) => `${X(xs[i])},${Y(p.equity)}`).join(" ")} /></svg>;
}
