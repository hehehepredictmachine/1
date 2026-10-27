// SCALPING price-move scenario 2.5-10 USD (prompt MC §3/§7): per level the price move, leg volume, account result from the terminal
// tick value, spread / commission / slippage separately and the Monte Carlo P(TP before SL) as conservative-optimistic bounds (model
// probability unless the user's validation produced a calibrated one). Models are listed with their own event - never combined.
// Every value comes from /api/v1/sh/scenario; unknown = "—" or "N/A", never 0.
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../../../api";
import { cls, fmtMoney, fmtNum } from "../../../util";

const STATUS_PL: Record<string, string> = {
  PLAN: "plan setupu", NO_SETUP: "brak setupu", NO_PROFILE: "brak profilu", NO_SYMBOL: "brak symbolu", UNIT_ERROR: "błąd jednostek",
};
const USE_PL: Record<string, string> = {
  PROBABILITY: "prawdopodobieństwo", GATE: "bramka", GATE_UNAVAILABLE: "bramka niedostępna", EVIDENCE: "dowód", INFO: "informacja", NONE: "pominięty",
};

const pct = (v: any) => (v === null || v === undefined ? "N/A" : `${fmtNum(v * 100, 1)} %`);

export default function ScenarioCard() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [vol, setVol] = useState("");
  const load = useCallback(() => {
    const v = Number(vol.replace(",", "."));
    apiGet(`/api/v1/sh/scenario?strategy=SCALPING${vol && v > 0 ? `&volume=${v}` : ""}`)
      .then((r) => { setD(r); setErr(null); }).catch((e) => setErr(String(e?.message || e)));
  }, [vol]);
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);
  if (!d) {
    return (<section className="t-card" data-testid="ti-scenario"><header className="t-card-head"><h2>Scenariusz ruchu 2,5–10 USD</h2></header>
      <p className="t-dim">{err ? `Brak odpowiedzi: ${err}` : "Ładowanie…"}</p></section>);
  }
  const mc = d.montecarlo || {};
  const rows: any[] = d.levels || [];
  const plan = d.status === "PLAN";
  const cur = rows.find((r) => r.currency)?.currency;
  const used = (d.models || []).filter((m: any) => m.used !== false && m.use !== "NONE");
  const skipped = (d.models || []).filter((m: any) => m.used === false || m.use === "NONE");
  const trig = (d.trigger || [])[0];
  return (
    <section className="t-card" data-testid="ti-scenario" data-status={d.status}>
      <header className="t-card-head"><h2>Scenariusz ruchu 2,5–10 USD · {d.strategy} · {d.instrument}</h2>
        <span className={cls("t-badge", plan ? "t-badge-ok" : "t-badge-muted")} data-testid="ti-scenario-status">{STATUS_PL[d.status] ?? d.status}</span>
        <span className={cls("t-badge", mc.calibrated ? "t-badge-ok" : "t-badge-warn")} data-testid="ti-scenario-kind">
          {mc.status !== "OK" ? `Monte Carlo: ${mc.status ?? "—"}` : mc.calibrated ? "skalibrowane na Twoich danych" : "prawdopodobieństwo w modelu – nieskalibrowane"}</span>
        {mc.data?.kind === "SYNTHETIC_TEST" && <span className="t-badge t-badge-gold">DANE SYNTETYCZNE</span>}</header>
      <p className="t-note">Ruch ceny instrumentu w USD – to nie jest zysk rachunku. Wynik w walucie rachunku liczony z wartości ticka z terminalu; koszty pokazane osobno.</p>
      {d.reason && <p className="t-note" data-testid="ti-scenario-reason">{d.reason}</p>}
      <dl className="t-kv">
        <dt>Kierunek</dt><dd data-testid="ti-scenario-side">{d.side ?? "—"}</dd>
        <dt>Stan setupu</dt><dd>{d.setup_status ?? "—"}{d.setup_reason ? ` · ${d.setup_reason}` : ""}{d.score != null ? ` · score ${d.score} (heurystyka, nie prawdopodobieństwo)` : ""}</dd>
        <dt>Trigger</dt><dd>{trig ? `${trig.status}: ${trig.detail || trig.label}` : "—"}</dd>
        <dt>Unieważnienie</dt><dd>{d.invalidation != null ? fmtNum(d.invalidation, 2) : "—"}</dd>
        <dt>Horyzont</dt><dd>{d.horizon_minutes} min{mc.horizon_bars ? ` (${mc.horizon_bars} świec M1)` : ""}</dd>
        <dt>Monte Carlo</dt><dd>{mc.status === "OK" ? `${mc.variant} · ${mc.n_paths} ścieżek · ${mc.variant_basis ?? ""}` : mc.reason ?? mc.status ?? "—"}</dd>
        <dt>Powód braku zlecenia</dt><dd data-testid="ti-scenario-why">{d.order?.why_no_order ?? (plan ? "brak – zlecenie zależy od cyklu SCALPING (tryb, STOP, limity, broker)" : "—")}</dd>
      </dl>
      {d.no_plan_reason && <p className="t-note" data-testid="ti-scenario-noplan">Brak planu: {d.no_plan_reason}. Tabela pokazuje tylko zasięg ruchu w obu kierunkach.</p>}
      <div className="t-table-wrap">
        <table className="t-table" data-testid="ti-scenario-table">
          <thead><tr><th>Ruch</th><th>Rola</th><th>Cena</th><th>Wolumen</th><th>Wynik brutto</th><th>Spread</th><th>Prowizja</th><th>Poślizg</th><th>Wynik netto</th>
            {plan ? <><th>P(TP przed SL) ostrożnie–optymistycznie</th><th>Ta sama świeca</th><th>± błąd</th><th>Skalibrowane</th></>
              : <><th>P(+ruch w horyzoncie)</th><th>P(−ruch w horyzoncie)</th></>}</tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.level_usd} data-level={r.level_usd}>
              <td>{fmtNum(r.level_usd, 2)} USD</td><td>{r.role}</td><td>{r.price != null ? fmtNum(r.price, 2) : "—"}</td>
              <td>{r.leg_volume != null ? fmtNum(r.leg_volume, 2) : r.volume_used != null ? `${fmtNum(r.volume_used, 2)} (całość)` : "—"}</td>
              <td>{fmtMoney(r.gross_account, cur)}</td><td>{fmtMoney(r.spread_value, cur)}</td>
              <td>{r.commission_cost == null ? "nieznana" : fmtMoney(r.commission_cost, cur)}</td><td>{fmtMoney(r.slippage_cost, cur)}</td>
              <td title={r.net_note || ""}>{r.net_account == null ? "N/A" : fmtMoney(r.net_account, cur)}</td>
              {plan ? <><td>{pct(r.p_tp_before_sl_conservative)} – {pct(r.p_tp_before_sl_optimistic)}</td><td>{pct(r.p_ambiguous)}</td>
                <td>{r.mc_error_95 == null ? "—" : `± ${fmtNum(r.mc_error_95 * 100, 1)} pp`}</td><td>{pct(r.p_calibrated)}</td></>
                : <><td>{pct(r.p_up_reach)}</td><td>{pct(r.p_down_reach)}</td></>}
            </tr>))}</tbody>
        </table>
      </div>
      <p className="t-note">Spread: {d.costs?.spread_rule}. Prowizja {d.costs?.commission_known ? `${fmtNum(d.costs.commission_per_lot_side, 2)} / lot / stronę` : "nieznana – wynik netto N/A (nie zakładam 0)"};
        poślizg {fmtNum(d.costs?.slippage_usd_per_side, 2)} USD na stronę. „Ta sama świeca” = świeca dotknęła TP i SL – kolejność nieznana, stąd przedział.</p>
      <dl className="t-kv">
        <dt>Wolumen</dt><dd data-testid="ti-scenario-volume">{fmtNum(d.volume?.total, 2)} lot · {d.volume?.basis}
          {d.volume?.split?.status === "OK" ? ` · części ${(d.volume.split.legs || []).map((x: number) => fmtNum(x, 2)).join(" / ")}`
            : ` · podział niemożliwy: ${d.volume?.split?.reason ?? "—"}`}{d.volume?.on_broker_grid === false ? " · POZA siatką wolumenu brokera" : ""}</dd>
        <dt>Break-even</dt><dd>po {d.break_even?.after} ({d.break_even?.rule}) · {d.break_even?.price != null ? fmtNum(d.break_even.price, 2) : "—"} · {d.break_even?.note}</dd>
        <dt>Łączne P</dt><dd data-testid="ti-scenario-combined">{d.combined_probability?.status} – {d.combined_probability?.reason}</dd>
      </dl>
      <label className="t-field">Wolumen do kalkulacji (lot, puste = najmniejszy możliwy)
        <input value={vol} onChange={(e) => setVol(e.target.value)} inputMode="decimal" size={6} style={{ maxWidth: 140 }} data-testid="ti-scenario-vol" /></label>
      <details data-testid="ti-scenario-models"><summary>Modele: użyte {used.length}, pominięte {skipped.length}</summary>
        <div className="t-table-wrap"><table className="t-table t-table-wrapcells">
          <thead><tr><th>Model</th><th>Zdarzenie / wyjście</th><th>Stan</th><th>Udział</th><th>Wartość</th></tr></thead>
          <tbody>{(d.models || []).map((m: any) => (
            <tr key={m.model} data-used={m.used !== false && m.use !== "NONE" ? "1" : "0"}>
              <td>{m.model}</td><td>{m.event ?? "—"}</td><td title={m.reason || ""}>{m.status ?? "—"}</td>
              <td>{USE_PL[m.use] ?? m.use ?? "—"}</td><td>{m.value == null ? "N/A" : pct(m.value)}{m.kind ? ` (${m.kind})` : ""}</td></tr>))}</tbody>
        </table></div>
      </details>
    </section>);
}
