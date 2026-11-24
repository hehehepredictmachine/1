// Open positions and results: terminal positions (WS positions) with who manages them, PAPER positions of the bot, and the bot's
// settled results of the current mode (/api/v1/stats). Missing data = "—".
import { useEffect, useState } from "react";
import { apiGet } from "../../../api";
import { href } from "../../../router";
import { useStore } from "../../../store";
import { cls, fmtMoney, fmtNum } from "../../../util";

export default function PositionsStrip() {
  const { s } = useStore();
  const pos: any[] = s.positions?.positions || [];
  const paper: any[] = (s.managed || []).filter((m: any) => m.mode === "PAPER");
  const cur = s.account?.currency ?? null;
  const mode = s.mode?.mode;
  const [st, setSt] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    const m = mode === "AUTO_DEMO" || mode === "AUTO_LIVE" ? mode : "PAPER";
    const load = () => apiGet(`/api/v1/stats?mode=${m}`).then((r: any) => alive && setSt(r.bot ?? null)).catch(() => alive && setSt(null));
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [mode]);
  const all = st?.all;
  return (
    <section className="t-card" aria-labelledby="ti-pos-h" data-testid="ti-positions">
      <header className="t-card-head"><h2 id="ti-pos-h">Pozycje i wyniki</h2>
        <a className="t-btn" href={href("pozycje")}>Wszystkie pozycje i dziennik</a></header>
      {pos.length === 0 && paper.length === 0 ? <p className="t-dim">{s.connection?.state === "CONNECTED" ? "Brak otwartych pozycji." : "Brak danych MT5."}</p> : (
        <div className="t-table-wrap">
          <table className="t-table">
            <thead><tr><th>Ticket</th><th>Symbol</th><th>Strona</th><th>Lot</th><th>Otwarcie</th><th>SL</th><th>TP</th><th>P/L</th><th>Prowadzi</th></tr></thead>
            <tbody>
              {pos.map((p) => {
                const m = (s.managed || []).find((x: any) => x.position_ticket === p.ticket);
                return (
                  <tr key={p.ticket}><td>{p.ticket}</td><td>{p.symbol}</td><td className={p.side === "BUY" ? "t-pos" : "t-neg"}>{p.side}</td><td>{p.volume}</td>
                    <td>{fmtNum(p.price_open)}</td><td>{fmtNum(p.sl)}</td><td>{fmtNum(p.tp)}</td>
                    <td className={cls(p.profit > 0 && "t-pos", p.profit < 0 && "t-neg")}>{fmtMoney(p.profit, cur)}</td>
                    <td>{m ? (m.adopted ? "bot (przejęta)" : "bot") : "ręczna – bot nie prowadzi"}</td></tr>);
              })}
              {paper.map((m) => (
                <tr key={m.position_key}><td>PAPER</td><td>{m.symbol ?? s.symbol?.symbol}</td><td className={m.side === "BUY" ? "t-pos" : "t-neg"}>{m.side}</td>
                  <td>{m.volume_open}</td><td>{fmtNum(m.entry_price)}</td><td>{fmtNum(m.sl)}</td><td>{fmtNum(m.tp2 ?? m.tp1)}</td><td>—</td><td>bot (symulacja)</td></tr>))}
            </tbody>
          </table>
        </div>)}
      <p className="t-note" data-testid="ti-results">
        Wyniki bota ({st?.mode ?? mode ?? "—"}, rozliczone transakcje): {all && all.trades > 0
          ? `${all.trades} transakcji · netto ${fmtMoney(all.net, st?.currency ?? cur)} · wygrane/(wygrane+przegrane) po kosztach ${all.win_rate != null ? fmtNum(all.win_rate, 1) + " %" : "—"} · PF ${fmtNum(all.profit_factor, 2)}`
          : "brak rozliczonych transakcji"}. {st?.note ?? ""}
      </p>
    </section>);
}
