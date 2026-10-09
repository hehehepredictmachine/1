import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime } from "../util";
import Checklist from "./Checklist";

const ACTIVE = ["EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED", "WATCH", "EARLY"];

export default function SignalsPanel({ index }: { index: number }) {
  const { s } = useStore();
  const d = s.decision;
  const [tab, setTab] = useState<"setups" | "orders" | "positions" | "settled">("setups");
  const [sig, setSig] = useState<any>(null);
  const setupKey = `${d?.setup?.setup_id}:${d?.setup?.state}:${(s.attempts || []).length}`;
  useEffect(() => {
    apiGet("/api/v1/signals").then(setSig).catch(() => undefined);
  }, [setupKey]);
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="pnum">{index}</span>
        <span className="ptitle">CHECKLISTA WEJŚCIA & POZYCJE</span>
        <span className="spacer" />
        <div className="tabs small">
          {(["setups", "orders", "positions", "settled"] as const).map((t) => (
            <button key={t} className={cls(tab === t && "on")} onClick={() => setTab(t)}>
              {{ setups: "Scenariusze", orders: "Zlecenia", positions: "Pozycje", settled: "Rozliczone" }[t]}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        {tab === "setups" && (
          <table className="tbl">
            <thead><tr><th>Symbol</th><th>Scenariusz</th><th>Strategia</th><th>Etap</th><th>Powstał</th><th>SL (inw.)</th><th>Wynik</th></tr></thead>
            <tbody>
              {(sig?.setups || []).slice(0, 12).map((x: any) => (
                <tr key={x.setup_id} className={cls(ACTIVE.includes(x.state) && "active")}>
                  <td>{s.symbol?.symbol}</td>
                  <td>{x.direction === "LONG" ? "wzrostowy" : "spadkowy"}</td>
                  <td title={x.profile}>{x.strategy_id} {x.profile}</td>
                  <td><span className={cls("badge", x.state === "CONFIRMED" ? "ok" : ACTIVE.includes(x.state) ? "warn" : "muted")}>{x.state}</span></td>
                  <td>{fmtTime(x.created_at)}</td>
                  <td>{fmtNum(x.invalidation_level)}</td>
                  <td>{x.terminal_reason ?? "—"}{x.synthetic ? " ·SYN" : ""}</td>
                </tr>
              ))}
              {!sig?.setups?.length && <tr><td colSpan={7} className="muted">Brak setupów – silnik nie wygenerował kandydata (nie tworzymy sygnałów na siłę).</td></tr>}
            </tbody>
          </table>
        )}
        {tab === "orders" && (
          <table className="tbl">
            <thead><tr><th>Czas</th><th>Tryb</th><th>Strona</th><th>Lot</th><th>Stan</th><th>Retcode</th><th>Cena</th></tr></thead>
            <tbody>
              {(s.attempts || []).map((o: any) => (
                <tr key={o.attempt_id}><td>{fmtTime(o.created_at)}</td><td>{o.mode}</td><td className={o.side === "BUY" ? "pos" : "neg"}>{o.side}</td>
                  <td>{o.volume}</td><td><span className={cls("badge", o.state === "FILLED" ? "ok" : o.state === "REJECTED" ? "bad" : "warn")}>{o.state}</span></td>
                  <td title={o.retcode_text}>{o.retcode ?? ""} {o.retcode_text ?? ""}</td><td>{fmtNum(o.fill_price ?? o.price_requested)}</td></tr>
              ))}
              {!s.attempts?.length && <tr><td colSpan={7} className="muted">Brak wysłanych zleceń.</td></tr>}
            </tbody>
          </table>
        )}
        {tab === "positions" && (
          <table className="tbl">
            <thead><tr><th>Ticket</th><th>Strona</th><th>Lot</th><th>Otwarcie</th><th>SL</th><th>TP</th><th>P/L</th><th>Źródło</th></tr></thead>
            <tbody>
              {(s.positions?.positions || []).map((p: any) => {
                const managed = (s.managed || []).find((m: any) => m.position_ticket === p.ticket);
                return (
                  <tr key={p.ticket}><td>{p.ticket}</td><td className={p.side === "BUY" ? "pos" : "neg"}>{p.side}</td><td>{p.volume}</td>
                    <td>{fmtNum(p.price_open)}</td><td>{fmtNum(p.sl)}</td><td>{fmtNum(p.tp)}</td>
                    <td className={(p.profit ?? 0) >= 0 ? "pos" : "neg"}>{fmtNum(p.profit)}</td>
                    <td>{managed ? (managed.adopted ? "PRZEJĘTA" : "BOT") : "RĘCZNA (nie zarządzana)"}</td></tr>
                );
              })}
              {(s.managed || []).filter((m: any) => m.mode === "PAPER").map((m: any) => (
                <tr key={m.position_key}><td>PAPER {m.position_ticket}</td><td className={m.side === "BUY" ? "pos" : "neg"}>{m.side}</td><td>{m.volume_open}</td>
                  <td>{fmtNum(m.entry_price)}</td><td>{fmtNum(m.sl)}</td><td>{fmtNum(m.tp2)}</td><td>—</td><td>PAPER</td></tr>
              ))}
              {!s.positions?.positions?.length && !(s.managed || []).length && <tr><td colSpan={8} className="muted">Brak otwartych pozycji.</td></tr>}
            </tbody>
          </table>
        )}
        {tab === "settled" && (
          <table className="tbl">
            <thead><tr><th>Zamknięta</th><th>Tryb</th><th>Strona</th><th>Lot</th><th>Wejście</th><th>Wyjście</th><th>Netto</th><th>R</th></tr></thead>
            <tbody>
              {(sig?.trades || []).map((t: any) => (
                <tr key={t.trade_id}><td>{fmtTime(t.closed_at, true)}</td><td>{t.mode}</td><td>{t.side}</td><td>{t.volume}</td><td>{fmtNum(t.entry_price)}</td>
                  <td>{fmtNum(t.exit_price_avg)}</td><td className={t.net_pnl >= 0 ? "pos" : "neg"}>{fmtNum(t.net_pnl)}</td><td>{t.r_multiple ?? "—"}</td></tr>
              ))}
              {!sig?.trades?.length && <tr><td colSpan={8} className="muted">Brak rozliczonych transakcji.</td></tr>}
            </tbody>
          </table>
        )}
      </div>
      <Checklist c={d?.checklist} positions={(s.positions?.positions || []).length + (s.managed || []).filter((m: any) => m.mode === "PAPER").length} />
    </div>
  );
}
