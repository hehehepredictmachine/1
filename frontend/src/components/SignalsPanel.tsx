import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { useStore } from "../store";
import { cls, fmtNum, fmtTime, reasonPl } from "../util";

const ACTIVE = ["EARLY_SETUP", "QUALIFIED", "ARMED", "TRIGGERED", "CONFIRMED", "WATCH", "EARLY"];

export default function SignalsPanel({ index }: { index: number }) {
  const { s } = useStore();
  const d = s.decision;
  const [tab, setTab] = useState<"setups" | "orders" | "positions" | "settled">("setups");
  const [sig, setSig] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const setupKey = `${d?.setup?.setup_id}:${d?.setup?.state}:${(s.attempts || []).length}`;
  useEffect(() => {
    apiGet("/api/v1/signals").then(setSig).catch(() => undefined);
  }, [setupKey]);
  const st = d?.setup;
  const lv = d?.levels;
  const risk = d?.risk;
  const allowed = d?.execution_permission === "ALLOWED";
  const execute = async () => {
    if (!d) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await apiSend("POST", "/api/v1/execute", { decision_id: d.decision_id });
      setMsg(`${r.status}${r.reason ? ": " + r.reason : ""}${r.ticket ? " ticket " + r.ticket : ""}`);
    } catch (e: any) {
      setMsg(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };
  const dirCls = d?.analysis_direction === "LONG" ? "pos" : d?.analysis_direction === "SHORT" ? "neg" : "";
  const blockers: string[] = (d?.reason_codes || []).slice(0, 6);
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="pnum">{index}</span>
        <span className="ptitle">SIGNALS & TRADE MANAGEMENT</span>
        <span className="spacer" />
        <div className="tabs small">
          {(["setups", "orders", "positions", "settled"] as const).map((t) => (
            <button key={t} className={cls(tab === t && "on")} onClick={() => setTab(t)}>
              {{ setups: "Propozycje", orders: "Zlecenia", positions: "Pozycje", settled: "Rozliczone" }[t]}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        {tab === "setups" && (
          <table className="tbl">
            <thead><tr><th>Symbol</th><th>Kier.</th><th>Strategia</th><th>Etap</th><th>Powstał</th><th>SL (inw.)</th><th>Wynik</th></tr></thead>
            <tbody>
              {(sig?.setups || []).slice(0, 12).map((x: any) => (
                <tr key={x.setup_id} className={cls(ACTIVE.includes(x.state) && "active")}>
                  <td>{s.symbol?.symbol}</td>
                  <td className={x.direction === "LONG" ? "pos" : "neg"}>{x.direction === "LONG" ? "BUY" : "SELL"}</td>
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
      <div className="signal-box">
        <div className="sig-left">
          <div className="sig-tag">{st && ACTIVE.includes(st.state) ? (st.state === "CONFIRMED" ? "SYGNAŁ POTWIERDZONY" : "SETUP W TOKU") : "OBSERWACJA"}</div>
          <div className="sig-title">
            {s.symbol?.symbol} · <span className={dirCls}>{d?.analysis_direction ?? "—"}</span> ({d?.signal_stage ?? "—"})
            <span className={cls("badge", d?.decision === "BUY" || d?.decision === "SELL" ? "ok" : "muted")}>{d?.decision ?? "—"}</span>
          </div>
          <div className="sig-sub">{d?.direction_basis === "STRUCTURE_OBSERVATION" ? "Kierunek = obserwacja struktury M02 (to nie sygnał)" : d?.direction_basis === "REGIME_OBSERVATION" ? "Kierunek = obserwacja reżimu (to nie sygnał)" : st ? (st.profile === "ACTIVE" ? `${st.strategy_id} ${st.strategy_name ?? ""} · ${st.setup_tf} · etap ${st.state} · wynik ${st.setup_score ?? "—"}` : `${st.strategy_id} ${st.profile} · ${st.setup_tf} · etap M10A ${st.state}`) : "Brak setupu"}</div>
          <div className="levels">
            <div><label>WEJŚCIE</label><b>{risk?.entry ? fmtNum(risk.entry) : lv?.entry_zone ? `${fmtNum(lv.entry_zone.low)}–${fmtNum(lv.entry_zone.high)}` : "—"}</b></div>
            <div><label>SL</label><b className="neg">{fmtNum(lv?.stop_loss)}</b></div>
            <div><label>TP1</label><b className="pos">{fmtNum(lv?.targets?.[0]?.price)}</b></div>
            <div><label>TP2</label><b className="pos">{fmtNum(lv?.targets?.[1]?.price)}</b></div>
            <div><label>RR NETTO</label><b>{risk?.rr_net ?? "—"}</b>{risk && risk.rr_complete === false && <small>niepełne koszty</small>}</div>
            <div><label>LOT</label><b>{risk?.lots ?? "—"}</b></div>
            <div><label>DANE</label><b className={d?.data_quality === "GOOD" ? "pos" : "neg"}>{d?.data_quality ?? "—"}</b></div>
          </div>
          <div className="blockers">{blockers.map((b) => <span key={b} className="badge bad" title={b}>{reasonPl(b)}</span>)}</div>
        </div>
        <div className="sig-right">
          <button className={cls("exec", allowed ? "on" : "off")} disabled={!allowed || busy} onClick={execute}
            title={allowed ? "Wyślij zlecenie przez gateway" : `Zablokowane: ${(d?.reason_codes || []).join(", ")}`}>
            EXECUTE TRADE
          </button>
          <div className="exec-note">{allowed ? `Tryb ${d?.mode_gate?.mode}` : d?.mode_gate?.mode === "READ_ONLY" ? "READ_ONLY: wykonywanie wyłączone" : "Wykonanie zablokowane"}</div>
          <div className="quality-note">Ocena jakości ≠ prawdopodobieństwo wygranej. Brak skalibrowanego prawdopodobieństwa.</div>
          {msg && <div className="exec-msg">{msg}</div>}
        </div>
      </div>
    </div>
  );
}
